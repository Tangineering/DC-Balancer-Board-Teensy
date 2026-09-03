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

**Why 1 kHz is enough for the SIMPLE engine.** This statement is scoped to the simple
electrical engine and to the mechanical model. Every dynamic in *those* is far slower than
the tick:

| Timescale | Value | Source |
|---|---|---|
| Drive-loop crossover | ≈ 17.25 rad/s (≈ 2.7 Hz) | fw v18 re-synthesis, CLAUDE.md fw v18 addendum |
| Drive controller update | 500 Hz (`DRIVE_CTRL_TS_US`) | `drive_controller.h` |
| Mechanical pole | −0.1526 rad/s (`−b_eff/m_eff`) | fw v14 addendum |
| Bus decay when dark | τ = `R_BUS_BLEED·C_BUS_F` = 14.1 s | §4, §4.8 |
| Injection tick | 1 ms | this loop |

Within that scope the *slowest* modelled pole is the 14.1 s bus decay and the fastest
*consumer* is the 500 Hz controller. A 1 ms explicit-Euler step is one to four decades
inside both, so the integration error is negligible compared with the model's structural
simplifications (§4). What 1 kHz does **not** cover is anything the model omits —
converter switching, RT1987 turn-on, encoder edges — and those are omitted by design, not
by rate.

**The hi-fi engine is a different statement, and the tick is not its step.** The hi-fi
electrical engine (§8) contains dynamics far faster than 1 ms: a 0.77 µs switch/node RC
(§8.2) and the 100 µs boost voltage-loop lag `τ_r` (§8.3). It does not integrate at the
tick rate — it takes *n* backward-Euler substeps inside every tick, `n` chosen adaptively
from measured wall-clock cost (§8.1), so the simulated step is `1 ms / n`. Backward Euler
is L-stable at any `n`, so a coarse tick cannot destabilise the solve; what it can degrade
is the accuracy of the repaired RT1987 soft-start current, which the engine's own comment
bounds at a substep of about **125 µs** (`n ≥ 8`). Measured across campaign
`hil_report_20260902_011926` (3.55 M ticks, `n` reconstructed from `elec_substep_hz`, a
wall-clock rate): **99.98 % of ticks ran at `n` = 20, i.e. h = 50 µs**; the reconstruction
placed two ticks at h = 142.9 µs, but the direct `elec_substep_n` column added afterwards
(campaign `hil_report_20260902_041414`, 38 runs) shows a minimum of `n` = 11 (h = 91 µs) and
zero sub-gate ticks — the reconstruction over-stated the excursion. Every run whose verdict rests on sub-millisecond
behaviour — `scp-inrush`, `sag`, `handoff-sag`, `comm-loss` — carried **zero** coarse
ticks. The hazard if `n` ever fell to 1 is quantified: 4.27 A of soft-start current against
the converged 0.22 A, i.e. a spurious `OC_FC`. Incidence to date is zero, and the
`substep_resolution` suite gate (`n_min ≥ 8`, from the logged `elec_substep_n` column)
exists so that it stays an assertion rather than an assumption.

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
held, V_bus unmoved* (CLAUDE.md 2026-08-17b). The coupling is not merely small, it is
**structurally absent while the clamp is active**: `MOT_PWR` is instantiated
`strict_forward`, so the model stamps no BUS↔MOT conductance unless `V_BUS − V_MOT`
exceeds `RT_V_FWD` (35 mV). At the clamp `V_MOT` ≈ 18.1 V, so bus-fed clamping would need
`V_BUS` > 18.135 V — above `LIMIT_V_BUS_MAX` 17.5 V, hence unreachable outside an OV
latch. Measured clamp-attributable bus sag is **below 1e-5 V**; the "≈ 0.03–0.06 V of bus
sag" this paragraph carried until 2026-09-02 was arithmetic on a mechanism the model does
not instantiate. Meanwhile the Ag105 is dark for its first `AG105_SETTLE_S` (0.5 s) and
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
draw its 2.5 A profile out of a 3 W brake. The cap is **output-referred and exact** from
2026-09-01:

```
    i_target = min(ag105_i_max, ETA_CHG * p_regen_w / V_pack)
```

The previous form was `p_regen_w / V_chg`, an input-referred current compared against an
output-referred target. That form understated the harvest by roughly `V_chg/V_pack ≈ 2×`.
It was retained only because the model carried no charger efficiency. `ETA_CHG` supplies
one, so the conversion is now defined rather than approximated.

One bias direction remains. `p_regen_w` is the power available **pre-chopper**, so the cap
is **optimistic** by the chopper's own share factor — part of that power is burnt across
the chopper before it reaches the Ag105 input.

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

### 3.5 Road-load drag profiles (`--drag`, 2026-09-02)

The road load in the §3 force law is one of **three named profiles**, selected by
`--drag {rig,scaled-air,scaled-air-matched}` and defaulting to `rig`. The flag mirrors
`--asymmetry` and `--droop` in shape: a mode choice whose default reproduces every campaign
recorded before the flag existed. A scenario may declare a `drag` meta key; an explicit
`--drag` overrides it, and the resolution source is recorded as `config.drag_from`.

Table 3.5 gives the three profiles and what each does to the braking energy of the
compressed FTP-75 cycle `ftp75c`.

| Mode | Road load `F_road(v)` | `k_air` [N/(m/s)²] | Regen share of braking KE on `ftp75c` |
|---|---|---|---|
| `rig` *(default)* | `sgn(v)·F_COULOMB + B_EFF·v` | 0.0 | 0.00 % |
| `scaled-air` | `k_air·v·abs(v)`, `F_c = 0` | 0.059806901748516605 | 51.25 % |
| `scaled-air-matched` | `k_air·v·abs(v)`, `F_c = 0` | 0.013330032560214096 | 79.09 % |

The compensated coefficient follows from the scaling study's own similarity rules and one
pair of vehicle assumptions. The vehicle road load is taken as air drag alone,
`0.5·rho·Cd·A_f·v_v²`, and the study scales a force by `S_L³` at the corresponding vehicle
speed `v_v = v / S_L`, so the rig coefficient collapses to a single constant:

```
    S_L    = 3.0 / 25.3472 = 0.1183563                     (DRAG_SCALE_LENGTH)
    k_air  = 0.5 · rho · Cd · A_f · S_L
           = 0.5 · 1.225 · 0.33 · 2.5 · 0.1183563
           = 0.059806901748516605                          (K_AIR)
```

`Cd` = 0.33 and `A_f` = 2.5 m² are **NEXO-class assumptions and are not present in the
extracted text of the scaling paper**, `TODO(verify: operator)`. `k_air` is linear in their
product, so an operator correction of `Cd·A_f` rescales `K_AIR`, `K_AIR_MATCHED` and every
energy figure in this subsection proportionally. `rho` = 1.225 kg/m³ is the standard
sea-level value.

At the cycle peak of 3.0 m/s the compensated load is 0.538 N against the rig's own 3.602 N,
so the compensated plant is approximately 6.7 times more freely rolling there. The Coulomb
term is **zero** in both compensated modes, because the compensation replaces the rig
friction rather than adding to it. `M_EFF` stays at 3.5 kg: the flywheel inertia is a
physical property of the rig, and moving it would invalidate the `K_F` and drag
identification of `motor_id_20260815.md`.

**The third mode exists because the rig is still too light for the drag it is given.** The
compressed rig's drag-to-inertia ratio, referred to the vehicle it stands for, is

```
    DRAG_INERTIA_RESIDUAL = S_L² · 2242 · TIME_FACTOR / M_EFF = 4.486628331803267
```

so `scaled-air` reaches only 51.25 % of braking kinetic energy where the full-scale vehicle
reaches 79.09 %. Dividing `k_air` by that residual gives `K_AIR_MATCHED`, which reproduces
the full-scale share to five significant figures. **The `ems-ftp75c-*` scenarios run
`scaled-air`** (operator ruling, 2026-09-02); `scaled-air-matched` ships as a named profile
so the choice between the two can be made on measurements, and **no registered scenario runs
it**.

The two compensated arms share one implementation property worth stating. `Plant.step()`
carries **two force branches, not one generalized expression**: the `rig` arm is the
pre-2026-09-02 code verbatim, and the compensated arm is `f_net = f_drive − k_air·v·abs(v)`
with no Coulomb term and no stiction deadband. A single expression parameterized by `F_c`
would be a silent physics defect, because the deadband test `abs(f_drive) <= F_COULOMB`
becomes trivially true at `F_c = 0` and would delete a coasting body's momentum. The signed
form `v·abs(v)` is load-bearing for the same class of reason: a bare `v²` term accelerates
the body in reverse. The `v_try` zero-crossing guard is kept on both arms although quadratic
drag alone cannot push the body through zero, so that the two profiles differ only where
they are meant to.

**Effect on the drive controller: none that needs re-synthesis.** The drag term enters the
Youla plant as a single pole, `−B_EFF/M_EFF` = −0.1526 rad/s under `rig` and
`−2·k_air·v/M_EFF` under compensation, which is −0.1025 rad/s at 3.0 m/s and zero at
standstill. The largest possible pole movement is therefore 0.1526 rad/s, 0.88 % of the
17.25 rad/s crossover, and it moves the pole toward the origin, that is toward the
free-integrator plant the synthesis corners already bracket. Removing the Coulomb term
reduces a constant load disturbance from 2.00 N to zero, which reduces integrator excursion
and cannot destabilize the loop.

⚠️ **THE COMPENSATED MODES ARE HIL-ONLY AND CANNOT BE REPLICATED ON THIS BENCH WITH THE
SINGLE MOTOR NOW FITTED.** The reason is structural, not one of tuning. Compensation would
have to be a friction feedforward cancelling `F_COULOMB + B_EFF·v`, up to 3.60 N at 3.0 m/s,
and the only actuator able to apply it is the traction motor itself. A feedforward of that
form keeps the net motor force **positive** through a stop, because the motor is supplying
the friction the compensation cancels. No instant exists at which the current reverses, so
there is no physical regeneration to measure, and a bench run would exercise the firmware
regen branch only if the command were falsified. Replicating the profile needs a **second
motor acting as a road-load brake on the flywheel**, sized in
`docs/modeling/ftp75c_regen_cycle_design_20260902.md` §7 at approximately **3.1 N rim force,
0.24 N·m, 400 rpm, under 10 W, four-quadrant**, under torque control rather than speed
control. Three requirements attach to it, and none is optional.

- **Coast-down calibration** of `F_COULOMB` and `B_EFF`, repeated after any drivetrain
  rework. The compensation is only as good as the friction model it cancels, and the
  FITTED values, not the model constants, must drive the road-load command.
- A **speed-floor interlock** below approximately 0.2 m/s. The friction model is
  unreliable there and the Coulomb term's sign is ill-defined, so the brake motor can
  otherwise drive the flywheel backwards through zero.
- A **setpoint-zero interlock**. A standing torque command at standstill is a stall
  condition on a sub-10 W motor, which is a thermal hazard.

### 3.6 Physics change record: road-load compensation and the regen credit (2026-09-02)

*Written in the §4.6.2 pattern.*

**What changed.** Three things landed together, and they are one round because the middle one
is unobservable without the first and the third is unusable without the middle. First, the
plant gained the two compensated road-load profiles of §3.5, so that a registered drive cycle
can brake regeneratively at all. Second, a compressed FTP-75 cycle `ftp75c` was generated
(`tools/gen_ftp75_profile.py --time-factor 0.5` → `tools/ftp75c_profile.py`, 234 points,
t = 5.0–175.0 s, peak 3.0 m/s at t = 125.0 s), doubling every acceleration to ±0.3492 m/s²
and bringing the required regen current into the same decade as the VESC clip. Third, the
offline demand model shared by the DP generator, the offline walk and the MPC gained a
**regen credit**, expressed as a per-stage pack current; §9.4.2 states that half.

**Why the compression alone is not enough, and the compensation is.** Under the rig road load
regeneration requires `M_EFF·|a| > F_road(v)`, that is `|a| > 0.571 + 0.153·v` m/s². The
compressed cycle's peak deceleration is 0.3492 m/s², still below the 0.571 m/s² floor at
standstill. Table 3.6 gives the measured energy chain, at 1 kHz inverse dynamics over the
piecewise linear speed table.

| Configuration | Braking KE (J) | Shaft regen, PRE-CLIP (J) | Regen share |
|---|---|---|---|
| `ftp75`, `rig` | 30.819 | 0.001 | 0.00 % |
| `ftp75c`, `rig` | 30.818 | 0.001 | 0.00 % |
| `ftp75c`, `scaled-air` | 30.818 | 15.794 | 51.25 % |
| `ftp75c`, `scaled-air-matched` | 30.818 | 24.373 | 79.09 % |

Table 3.6 shows that the compression moves the regen share not at all and the compensation
moves it to half the braking energy. The compression is nonetheless load-bearing: on
`scaled-air` the peak drive current is 1.7789 A and the peak unclipped regen current is
−1.6210 A, so the mechanism is exercised against the 1.5 A `VESC_REGEN_I_MAX_A` clip rather
than far below it. 14.94 % of braking samples sit above that clip, which costs 0.83 % of
shaft regen energy: 15.794 J becomes **15.662 J**, and at `ETA_REGEN` = 0.80 that is
**12.530 J** at the regen node.

**The commanded regen windows, and one deviation from the design note.** The scenario layer
does not harvest wherever the physics allows; it commands `charge_goal = 1.0` over derived
windows, because asserting `charge_goal` one tick before the commanded current has gone
negative takes `chargingControl()`'s CRUISE branch, calls `assertFcChargeEnable(true)`, drops
BT off the bus and creates the single-source condition that has latched `OC_FC` before.
`derive_regen_windows()` therefore applies a 0.20 s lead-in, a 0.20 s lead-out and a 0.50 s
minimum duration. **The design note's segment rule was tightened in implementation.** Its
rule admits a profile segment when the required motor force is negative at *either* endpoint,
which admits a segment whose force crosses zero inside it and builds a window over an interval
where the motor command is still positive; measured on `ftp75c`, that rule opened an FC charge
window at t = 53.6 s and yielded ten windows carrying 29.000 s. The implementation trims each
segment to the exact sub-interval over which the force is negative, located by bisection,
which is valid because the force is monotone in time inside a segment: the acceleration is
constant, the velocity affine and the road load monotone in velocity on the forward half-line.
With the trim the derivation reproduces the design note's Table 5 exactly: **nine windows
carrying 28.400 s of commanded duty, 16.7 % of the 170 s cycle**

⚠️ **RE-DERIVED (H1, 2026-09-02).** The windows above were trimmed against `force < 0`. The firmware branches on `regenActive = (current < -0.1f)` (.ino:10807). An instant whose required current sits in (-0.1, 0) A is therefore braking in physics and NOT-REGEN in firmware. Commanding `charge_goal` there takes the cruise branch, calls `assertFcChargeEnable(true)` and drops BT off the bus. Seven of the nine windows contained 2.900 s of such instants, one of them for 100 % of its length. The trim is now against the firmware's own test with a 2x margin. That costs three windows and 8.8 s of duty, leaving **six windows carrying 19.600 s, 11.5 % of the 170 s cycle**. They are 23.200-24.300, 30.200-31.800, 62.700-67.300, 96.200-97.800, 159.200-162.800 and 164.200-171.300 s, and the worst in-window required current is -0.2045 A.
, from 12 regen-capable
intervals totalling 34.0 s before trimming. The windows are 21.200–24.300, 30.200–31.800,
41.700–42.300, 57.200–57.800, 62.200–67.300, 91.700–92.800, 95.700–98.300, 156.700–162.800
and 163.700–171.300 s. Under `--drag rig` the same derivation yields **zero** windows, which
is the correct behaviour for a control run: the manager is re-derived at run time from the
resolved drag mode, not from the scenario's declared one.

⚠️ **THE TRAILING EDGE IS NOW A CONDITION, NOT A WALL CLOCK (ruling D-4,
2026-09-03).** The leading-edge trim above is unchanged; what changed is where a
window ENDS. The manager used to command `charge_goal = 1.0` to the window's
wall-clock end, and campaign `hil_report_20260902_220604` measured what that costs:
on windows 3 and 6 the vehicle reaches **standstill before the window ends**, so the
firmware's commanded motor current leaves the braking region (measured −12.0 → 0.0 A
at t = 67.2051 s against a window end of 67.217 s), `regenActive` goes FALSE while
the host is still asserting charge intent, and `chargingControl()` falls through to
its CRUISE branch — `assertFcChargeEnable(true)`, BT dropped off the bus, the whole
load carried single-source on the FC. That is the hazard the LEADING-edge trim was
written to prevent, arriving at the other edge. Measured on every one of the five
legs: handoff windows at 67.22 s (0.08–0.10 s, 6–9.5 mC) and 171.04–171.06 s
(0.26–0.28 s, 55–64 mC), peak `I_fc` 0.37–0.38 A — 27 % of `LIMIT_I_FC_MAX`, and the
recorded `OC_FC` topology reached on a light cycle.

**The rule is a two-level comparator.** A window OPENS on the required motor current
ENTERING the braking region at `EMS_REGEN_MGR_I_MARGIN` × `REGEN_ACTIVE_I_A` =
−0.2 A (`RegenManager.i_arm_a`), and it RELEASES on the commanded motor current
reaching −`REGEN_ACTIVE_I_A` = −0.1 A (`RegenManager.i_release_a`), the firmware's
own `regenActive` exit, whichever comes first with the wall clock. The release is ARMED only after the firmware has been seen
braking inside the window (so the lead-in ramp cannot close a window before it
starts) and LATCHED for the remainder of it (so a current chattering across the level
cannot re-open the path). `regen_commanded` on the feedback view follows the same
decision, so the dwell accounting and the charge census cannot disagree with the
command stream. Mutual exclusion and the 8 s dwell semantics are unchanged.
`regen_early_releases` in the sidecar counts the windows that ended on the current
rather than on the clock, and `regen_duty_s` remains the WALL-CLOCK duty, i.e. an
upper bound on the commanded one whenever that count is non-zero.

⚠️ **THE TWO LEVELS ARE NOT INTERCHANGEABLE, AND ONE LEVEL WAS A DEFECT** (review
finding H1, 2026-09-03). The rule shipped with a single level: arm at −0.2 A,
release at −0.2 A. That is a zero-hysteresis comparator, and because the release is
LATCHED, one sample grazing the level closes the window for the rest of the cycle.
Replayed against campaign `hil_report_20260902_220604`'s own `ems-ftp75c-5050`
`current` column it fires twice in the middle of braking: window 1 releases at
t = 23.3854 s at −0.1999 A, 200 ms before the vehicle brakes to −1.55 A, and window
6 releases at t = 167.1162 s at −0.1997 A with 3.94 s of −0.65 … −8.09 A braking
still to come. `regen_commanded` then reads False THROUGH heavy braking, which
un-guards the three consumers that read it to refuse an FC-charge dwell inside a
braking window, i.e. it re-creates the hazard this ruling exists to close.

The release level is therefore the firmware's own exit, so the host can never drop
regen intent while the firmware still calls the instant regen. On the same trace the
two spurious releases disappear, window 5's benign 0.14 s-early release goes with
them, and both genuine standstill releases survive — window 3 at t = 67.2041 s and
window 6 at t = 171.0441 s, that is `regen_early_releases` = **2 of 6**. The
regression fixture is the measured trace itself
(`test_hil_plant_sim._FTP75C_REGEN_CURRENT`); a synthetic −12 → 0 A step cannot
stand in for it, because the defect is a graze in the middle of sustained braking
and no step contains one.

⚠️ **THE 67.22 s HANDOFF IS BOUNDED, NOT CLOSED.** The release condition removes
the host's charge intent, but the host commands at **50 Hz**, so a release lands up
to 20 ms before the next command reaches the firmware. Measured on campaign
`hil_report_20260902_220604`, release instant to the first `FC_CHARGE` rise:

| leg | window 3 (≈ 67.2 s) | window 6 (≈ 171.04 s) |
|---|---|---|
| `ems-ftp75c-5050` | 12.93 ms | 15.98 ms |
| `ems-ftp75c-dp` | 20.25 ms | 6.29 ms |
| `ems-ftp75c-mpc` | 4.88 ms | 10.75 ms |
| `ems-ftp75c-sdp` | 13.04 ms | 1.95 ms |
| `ems-ftp75c-socband` | 1.04 ms | 7.30 ms |

Nine of those ten margins are INSIDE one commander period, so a short single-source
`FC_CHARGE` handoff may still occur at both edges on a live run. The earlier reading
that the 171.04 s handoff was closed with a 3.9 s margin was an artefact of the
single-level release closing window 6 at 167.1162 s, and it does not survive the H1
fix. `ftp75c_fc_bounded_charging` (arm 2, a 0.60 A whole-window ceiling against a
measured 0.3818 A) is what BOUNDS the residual handoff; closing it needs either a
commander-rate change or a firmware-side standstill guard, and neither is in this
round.

⚠️ **THE WALK DOES NOT SEE THE NEW TRAILING EDGE, and this is recorded rather than
hidden.** The release reads `fb["current"]`, the HIL observation frame's commanded
motor current, which is not telemetry-equivalent and is not produced by `ems_walk`'s
reduced feedback view. With the key absent the manager falls back to the wall-clock
end exactly as before, so **every offline walk is unchanged across this round** — the
five `ems-ftp75c-*` legs still walk six windows carrying 19.600 s and 1.172913 C to
the pack — and only a live run sees the shorter windows. A walk therefore models the
LONGER window and its regen duty is an upper bound on the live one. Closing that gap
needs a standstill model in the walk's demand chain, which it does not have.

**The credit is small against the drain, and no conclusion may rest on it being otherwise.**
Roughly 1.39 C reaches the pack per cycle against roughly 96.8 A·s of pack draw, that is
1.4 %, a SoC gain near +5.5e-5 against a −0.0054 excursion. Because the regen manager is a
**common layer over every strategy** and the credit is share-independent, all five
`ems-ftp75c-*` legs receive the identical **1.1729 C** on the identical six windows,
confirmed in the governor walk, which is the design's share-independence property measured
rather than assumed. As of this writing (pre-campaign), `ftp75c` REDUCES the DP's
regen divergence rather than closing it, and validation of the regen model against
board measurement is deferred to §4.8, which later records a measured realizable
fraction of 0.63 against this section's modelled 0.707. The bound earns the same credit the run
does; what remains is the Ag105 settle and ramp, which cost roughly the first
0.9 s of every window and hold the modelled realizable fraction near 70.7 %. However, it is **not** expected to reorder the strategies, and a
reordering on this stimulus is a defect signal rather than a result.

**What it does to the offline bound.** The `ems-ftp75c-dp` table is the first DP table ever
solved with the braking credit in its demand model. A credit-free table must supply with
hydrogen the SoC the run gets back from braking, so its total is inflated and the run's
deviation against it is correspondingly optimistic. The `regen_bound` correction that
`hil_report_analysis.matched_dp_for_run()` prices per run goes to zero on a regen-era run.
⚠️ **The bound is not strictly below the causal reference on this stimulus.** The offline
matched solve reads the DP **+0.06 % above** the causal `soc-band` walk at matched terminal
SoC (0.00598238 g against 0.00597881 g; matched terminal SoC target 0.697961, `lambda_term`
2.48383 in 21 solves, match residual +1.82e-06 SoC). That is the discrete control grid;
`LAMBDA_TERM` to terminal SoC is monotone but not continuous, and it is why the `ftp75c`
tuple's vs-bound arm reads about 1.01 rather than under 1.

**A DP grid-sizing guard was required, and it is gated on the regen era.** The first
`ems-ftp75c-dp` solve failed with an infinite cost-to-go at the initial state. The mechanism
is a grid-edge artefact and not a regen defect: at the bottom grid row every discharge control
steps below `soc_grid[0]` and is marked infeasible, its cost-to-go becomes infinite, and on
the next backward stage a row one step above brackets the infinite row, so `np.interp` returns
infinity. The infeasibility therefore creeps upward at **exactly one grid row per stage**. On
`ems-ftp75c-dp` that is 1800 stages against an 1861-row grid whose bottom pad is 219 rows, so
it climbs past the initial state's row 1046. The compensated road load is what exposes it: the
tractive demand falls by roughly 4.5×, so the reachable window narrows, so the proportional
pad narrows, while the stage count is unchanged. The guard pads the grid by at least
`(n_stages + 1) * soc_step`. **The gate is about artefacts, not about physics.** The guard is
correct for every solve, and applying it universally would move the SoC grid of all three
committed pre-regen tables and every stored `dp_db` record for a defect none of them reaches
at their own initial state. Measured on `ems-dp-replay`: 611 stages climb 0.003055 SoC from a
bottom edge 0.001782 below the reachable low, so the poison does enter the low end of that
table's reachable window and simply never reaches 0.7. A `TODO(verify)` at the site records
the outstanding work: re-solve the pre-regen tables under the guard and quantify the change
before making it unconditional.

**Fingerprint and era keys.** The DP profile fingerprint gains **two optional keys**, `drag`
and `eta_regen`, and they are two rather than one because they are independent: a rig-drag run
in the regen era is legitimate and earns zero credit, and a compensated run in the pre-regen
era is a defined configuration. Both are **omitted entirely** when they resolve to `rig` and
`None`, which is what keeps the four committed tables, the SDP policy artifacts and all 16
`dp_db` records reachable and byte-identical. `DpReplayStrategy.bind_scenario()` gains a third
era guard, alongside the accounting and `eta_chg` guards, and it states in its message that the
fingerprint cannot catch the `eta_regen` half at all and catches the `drag` half only when the
scenario declares the key. `K_AIR` and the other new module constants are swept up by
`collect_model_constants()`, so `constants_hash` moves; that is correct, and a run recorded
before the change carries the old hash and neither era key, which places it unambiguously.

**No new SDP artifact was solved for `ems-ftp75c-sdp`,** and the omission is deliberate rather
than deferred. The regen credit enters through the plant and the pack, not through the policy's
decision law, and `sdp_policy_v4`'s axes, relative SoC and a demand bin, are
stimulus-independent by construction. Re-solving would have produced a second artifact
differing from `sdp_policy_v4` only in the demand map it was fitted on, with no campaign able
to tell the two apart.

⚠️ **SUPERSEDED (2026-09-03).** "No campaign has run any of this" is false since campaign D
(`hil_report_20260902_220604`, 2026-09-02), which ran the `ems-ftp75c-*` legs and recorded
their result in §4.8. The paragraph below is retained as the pre-campaign prediction it was
written as.

**Downstream comparability.** No campaign has run any of this. Every trace in the archive
carries the rig road load and the pre-regen demand model, so the boundary is entered rather
than crossed: a compensated run is a different vehicle and is not comparable with any `ftp75`
or 61 s leg, and a rig-drag run is unaffected because both era keys resolve to their absent
sentinels. Every `ems-ftp75c-*` expectation band and both compressed-cycle frontier tuples are
**PROVISIONAL on the first campaign that evaluates them**, and `ETA_REGEN` = 0.80 and
`VESC_REGEN_I_MAX_A` = 1.5 A remain `TODO(verify)`, with the whole harvest column linear in
the first.

**REVERSAL PATH: thirteen edits, not one.** Setting `--drag rig` and `eta_regen = None` puts a
single run back in the old era; it does not revert the round, because the era plumbing, the
generated cycle, the scenarios and the solved artifacts remain. A return to the rig-only,
credit-free configuration must touch every item below.

1. `tools/hil_plant_sim.py`: drop `DRAG_MODES`, `DRAG_MODE_*`, `K_AIR`, `K_AIR_MATCHED`,
   `DRAG_SCALE_LENGTH`, `DRAG_INERTIA_RESIDUAL`, `drag_k_air()` and `drag_era_label()`, the
   `--drag` flag and its scenario-key resolution, and collapse `Plant.step()` back to the
   single `rig` force branch.
2. `tools/hil_plant_sim.py`: drop `derive_regen_windows()`, the `RegenManager` class,
   `unwrap_policy()` and the `ems_regen_manager` scenario key.
3. `tools/hil_plant_sim.py`: drop the `ftp75c` profile import and its generator gate, the
   `FTP75C_*` constants, the five `ems-ftp75c-*` scenario entries,
   `FTP75C_SOCBAND_CHARGE_ENTER_A` / `_EXIT_A`, and `SocBandStrategy`'s per-scenario
   charge-threshold overrides with its `bind_scenario()`.
4. `tools/hil_plant_sim.py`: drop the fingerprint and sidecar plumbing, that is `drag` and
   `eta_regen` from `DP_FINGERPRINT_META_KEYS` and `DP_FINGERPRINT_OPTIONAL_KEYS`,
   `dp_drag_mode()`, `plant_drag_mode()`, `dp_eta_regen()`, `plant_eta_regen()`, the third era
   guard in `DpReplayStrategy.bind_scenario()`, and the `drag` / `drag_k_air` / `drag_from` /
   `regen_manager` / `regen_windows` / `regen_duty_s` sidecar keys.
5. `tools/gen_dp_ems_table.py`: restore `build_demand()`'s five-tuple return, drop the
   `i_regen` credit from both SoC transitions and from `reachable_soc_window()`'s two extreme
   walks, drop `charge_mask()`'s `i_regen <= 0` exclusivity term, drop the `--drag` and
   `--eta-regen` flags and the four era header lines, restore the pre-committed E-M2 contract
   text, and drop the era-gated grid-sizing guard.
6. `tools/mpc_ems.py` and `tools/ems_walk.py`: the same demand port in lockstep, that is
   `Preview.i_regen`, `StagePrecompute.i_regen_mean`, the `_rollout()` SoC integrator, the
   charge-enumeration admissibility, and the walk's `regen_charge_c` / `regen_windows` /
   `regen_duty_s`.
7. `tools/regen_power.py`: delete.
8. `tools/gen_ftp75_profile.py`: drop `--time-factor`, the `TIME_FACTORS` registry and the
   `POINTS_INVARIANT` generation-time assertion; delete `tools/ftp75c_profile.py`.
9. `tools/dp_tables/dp_ems_table_ems-ftp75c-dp.csv`: delete. The three pre-regen tables are
   byte-identical across this round and need no regeneration, which is the whole point of
   omitting an absent era key from the fingerprint.
10. `tools/dp_results_db.py`: drop `drag` and `eta_regen` from `KEY_FIELDS` and
    `OPTIONAL_KEY_FIELDS`, and drop any `ems-ftp75c-*` record prefilled by then. The 16
    pre-regen records keep their keys.
11. `tools/run_hil_suite.py`: drop `FTP75C_SCENARIOS`, `--with-ftp75c` and its gate, the
    `ftp75c` and `ftp75c-mpc` frontier tuples, the five expectation blocks, `drag` from
    `EMS_FRONTIER_STIMULUS_KEYS`, and the opt-in-set cost line's `ftp75c` entry.
12. `tools/hil_report_analysis.py` and `tools/hil_ems_comparison.py`: drop the two era keys
    from the matched-DP resolution and `drag` from the comparison's profile-group identity.
13. `docs/HIL_PLANT.md` §3.5, §3.6 and §9.4.2, `docs/HIL_SCENARIOS.md` §6.2,
    `docs/HIL_USER_MANUAL.md` §3.2.1c and the run-era field list in
    `.claude/skills/hil-agent-analysis/references/hil-conventions.md`.
14. The NINE test modules: `tools/test_regen_power.py` (delete), and the additions to
    `test_hil_plant_sim.py`, `test_gen_dp_ems_table.py`, `test_ems_walk.py`,
    `test_mpc_ems.py`, `test_run_hil_suite.py`, `test_dp_results_db.py`,
    `test_hil_ems_comparison.py` and `test_hil_report_analysis.py`. Several of them
    ASSERT the new behaviour rather than merely exercising it, so they fail loudly on a
    partial reversal, which is the intended behaviour.
15. The FIVE prefilled matched-DP solves under `tools/dp_db/solves/` and the
    `tools/dp_db/index.json` entries that point at them. They are keyed on the two era
    keys, so they become unreachable rather than wrong once the keys are dropped;
    deleting them is a housekeeping step and not a correctness one.
16. `tools/hil_report_analysis.py`'s two prose records: `MATCHED_DP_REGEN_NOTE`, which
    states the era-conditional form of the boundary, and the note built inside
    `_matched_dp_regen_bound()`, which records that the per-run bound goes to zero in
    the regen era. Both revert to their unconditional pre-round wording.

Items 1 to 3 are behavioural, 4 and 10 are the baseline keying, 5 to 7 are the offline demand
model, 8 and 9 are generated artefacts, and 11 to 13 are the campaign and documentation
surface. Reverting a subset leaves a plant running one road load and a demand model priced
against another, which is the state this round's era keys exist to make impossible.

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
    tau = R_BUS_BLEED · C_BUS_F = 30 kΩ · 470 µF = 14.1 s
    V_bus += (−V_bus / tau) · dt
```

`C_BUS_F` = 470 µF matches the board's bulk capacitance as referenced throughout the
bring-up record. `R_BUS_BLEED` = 30 kΩ is an *effective* bleed and is
**`TODO(calibrate)`**: it was 2 kΩ (τ = 0.94 s) from this engine's first commit until
2026-09-02, when the operator ruled the physical bus decays full-to-near-zero in 30 to
60 s and the constant moved to match `hil_electrical.R_NODE_BLEED_BUS` — see §4.8 for
the change record, the reversal path and the bench decay capture that settles it. The decay matters mostly for
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
    frac_fc = code_bt / (code_fc + code_bt)          (0.5 if the denominator underflows)
    I_fc    = I_total · α(frac_fc, I_total)
    I_batt  = I_total · (1 − α)
```

With exactly one source live the split degenerates to 1.0 / 0.0 as appropriate; with
none, both currents are zero. α is the converter-asymmetry law of §4.4a below; with
`--asymmetry off` it is the identity and `frac_fc` is delivered directly.

> **⚠️ THE SIGN WAS INVERTED HERE UNTIL 2026-09-01 (the C1 round), in this document
> and in the code under it.** The firmware commands `g_FC = K_DROOP/(R_E,max·r)` and
> `g_BT = K_DROOP/(R_E,max·(1−r))` (the `droop_gain_FC_actual`/`droop_gain_BT_actual` assignment at the tail of `applyShareRatio()`), so a channel's MDAC code is
> proportional to its droop **resistance** and its current is proportional to the
> **reciprocal** of that code. **Raising the FC code raises the FC droop resistance and
> LOWERS its current** — the opposite of the claim this section used to make. The error
> was invisible to every campaign because simple mode's split is only ever read
> alongside a commanded ratio the firmware itself computes, so both ends moved together.
> A pinned unit test now reads `code_fc = 3000` against `code_bt = 1000` as **0.25** of
> the total on FC, not 0.75.

This is **the** named simplification of the electrical model. On the real board the split
is set by the analog droop network's equivalent resistances, which the MDAC codes only
*parametrize*; proportional-to-reciprocal-code preserves the **sign and monotonicity** of
the share loop's authority without claiming the true gain. It is therefore adequate to test that the share loop *closes in the right
direction*, that its cutoff/governor logic fires, and that its MDAC writes reach the
chokepoint. It is **not** adequate to tune share-loop gains, and the plant it implies is
not the plant `controller_design/system_model.md` synthesizes against.

> **⚠️ AND THE CLOSED LOOP HAS NO AUTHORITY AT ALL BELOW 0.55 A** — a firmware
> property, not a plant one, but it decides what a scenario or an offline walk
> may claim. The firmware enters closed-loop share control above
> `2·SHARE_MINORITY_I_MIN_A` = 0.60 A of filtered source total and drops out
> below 0.55 A (`SHARE_MINORITY_I_MIN_A`, `SHARE_GOV_OL_HYST_A`, and the
> `shareClosedLoopMode` mode gate at the head of `powerBalance()`).
>
> **Open loop is TWO submodes, and only one of them holds** (corrected
> 2026-09-02; the claim that open loop "does not write the MDACs" was false):
>
> - **HOLD.** Taken only when the closed loop has already run this profile
>   (`shareClosedLoopRun`), the setpoint has not moved by more than
>   `SHARE_SP_CHANGE_EPS` = 1e-4 since the last acted-on setpoint, and no
>   controller-initiated isolation (`shareIsoFC` / `shareIsoBT`) is outstanding.
>   `powerBalance()` then returns without calling `applyShareRatio()`, and
>   `droopSlew_prev` keeps the last physically-applied ratio. This is the case
>   the paragraph used to describe as the whole of open loop.
> - **FEEDFORWARD.** Taken on a fresh profile with no closed-loop authority yet,
>   on a **changed** setpoint while parked, or with an isolation recovery
>   outstanding. The raw setpoint is fed forward through the same slew limiter
>   the controller path uses — `DROOP_RATIO_SLEW_PER_TICK` **0.02**/tick, or
>   `DROOP_RATIO_SLEW_HANDOFF_PER_TICK` **0.002**/tick when
>   `updateShareSlewMode()` has flagged a conduction handoff this tick — and
>   `applyShareRatio()` **writes the MDACs**. An out-of-band setpoint
>   (outside `[DROOP_R_MIN, DROOP_R_MAX]`) is still never actuated here: the
>   setpoint latch owns it.
>
> Measured, not inferred: on `ems-y-b00-v3` (campaign
> `hil_report_20260902_011926`) **356 open-loop ticks wrote the MDACs, in 8
> episodes**, the largest running 174 ticks and walking the command 0.650 →
> 0.152 with the codes moving (5354, 5279) → (8119, 4815), i.e. 0.00286
> ratio/tick — between the two slew constants, as both being in play predicts.
> Campaign `hil_report_20260901_191509` shows 369 on the same leg.
> `tools/governor_model.py` reproduces both submodes.
>
> So under 0.55 A a `power_share_setpoint` is accepted and appears in
> `cmd_share_sp`, and whether it is acted on depends on which submode applies.
> Campaign `20260901_024231` measured a delivered share of **0.1656** against a
> commanded 0.85 at a 0.355 A cruise — a HOLD — and an offline walk that assumed
> the loop was closed put a suite check on a limit-cycle period **5.7× wrong**
> (see the `ems-sdp-cross` row in the scenario table). **The standing rule is
> therefore: model the open-loop HOLD *and* the feedforward SLEW.** Size a
> scenario's `aux_preload_a` if the loop must be closed instead.
>
> This is also the mechanism behind the governor-aware MPC's failing Gate 1:
> its open-stage surrogate models a hold, and every re-command landing in an open
> stage produces a feedforward slew it does not represent — see
> `docs/modeling/mpc_design_20260901.md` §6.5.
>
> ⚠️ **THE PRELOAD IS NO LONGER A DRIVE-CYCLE DEFAULT (operator ruling,
> 2026-09-01).** `aux_preload_a` is **0.0 on every drive-cycle scenario** — the
> four `ems-ftp75-*` legs included — because the sub-0.55 A stretches are TEST
> CONTENT, not a mode to be loaded away: a drive-cycle scenario that never
> enters open-loop hold never exercises it. The mechanism is unchanged and the
> constants are kept at zero (they are inside `collect_model_constants()` and
> `DP_FINGERPRINT_META_KEYS`, so a deleted key would silently un-cover the DP
> fingerprint). `Y_AUX_LOAD_A` is the deliberate exception and STAYS at 0.85 A:
> on `ems-y-b30-*` the load CONSTRUCTS the stimulus — it is what makes those
> scenarios' share bounds deliverable at all — rather than masking a mode.
> Consequence for the FTP-75 legs: governor walk **open_hold 9.71 % /
> open_feedforward 57.12 % / closed 33.17 %** of ticks, against open_hold
> 0.00 % / closed 98.25 % at 0.65 A. Any check whose derivation assumed a
> closed loop through an idle segment was re-derived with the ruling.

> **⚠️ A THIRD BOUND SITS ON THE REFERENCE FROM fw v26: the source
> current-ceiling clamp** (`applyShareCurrentCeilings()`,
> `docs/fw26_current_ceiling_governor.md`). It bounds the **commanded** fuel-cell
> fraction so the commanded per-channel current stays at or under that channel's
> ceiling, and forces every further amp of total demand onto the other source:
>
> ```
>     sp <= SHARE_GOV_I_FC_CEIL_A / I_tot          (1.25 A, an UPPER bound)
>     sp >= 1 - SHARE_GOV_I_BT_CEIL_A / I_tot      (2.70 A, a LOWER bound)
> ```
>
> Both are evaluated on `share_govTotAFilt`, the governor's approximately 20 ms
> filtered total, never on a raw sample. The order is fixed: the
> minority-current clip first (conduction feasibility owns the floor), then the
> battery bound, then the fuel-cell bound so the fuel cell wins the infeasible
> pair above 3.95 A of total, then a constrain into
> `[DROOP_R_MIN, DROOP_R_MAX]` applied only where a ceiling actually bound.
> Release is hysteretic at `SHARE_GOV_CEIL_HYST_A` = 0.05 A.
>
> **Which submode takes it.** FEEDFORWARD does, because it writes the
> converters. HOLD does not, because it writes nothing and applying the clamp
> there would break the hold invariant. The clamp is also suppressed while a
> deferred cut owns the setpoint: the fw v25 share-cut guard has parked the
> reference on a band edge to starve a doomed channel, and one owner per tick
> applies.
>
> **Reachability, and why every registered stimulus is unaffected.** The
> minority clip caps the commanded fuel-cell fraction at
> `1 - SHARE_MINORITY_I_MIN_A/I_tot`, so the fuel-cell ceiling is reachable only
> above **1.55 A of two-source total**. It cannot act at all in a fuel-cell
> charge window, where `assertFcChargeEnable()` holds `BT_BUS_ENABLE` low and
> there is no second channel to move load onto. Measured offline on the walks
> that carry the Gate tables: the highest two-source total on `ems-soc-band` is
> **1.462 A** and the clamp engages on **0 of 61 000** governor ticks, so
> Gate 1 and Gate 2 are unmoved to every digit they are quoted at.
>
> WARNING - corrected 2026-09-02: "every registered stimulus is unaffected" is
> not true of the whole set. The statement above is measured on the EMS legs,
> and the `ems-y` quartet is not one of them. Reconstructing the governor's own
> filtered total and minority clip from the campaign CSVs
> (`tools/probes/probe_fw26_clamp_reachability.py`, both campaigns of
> 2026-09-02) puts **`ems-y-b30-v3`** over the ceiling: filtered `I_tot`
> **2.3355 A**, commanded `I_fc` **1.5180 A**, **11 ticks** at
> t = 27.020-27.029 s (campaign B: 2.3343 A / 1.5173 A / 9 ticks at 27.007 s).
> That leg carries no hydrogen anchor and no offline walk, and what the clamp
> withholds there is 0.268 A of bus-side fuel cell for 11 ms - 2.9 mC, or
> 9.7e-07 g of hydrogen. Nothing else on the registered set reaches the
> ceiling: the next-highest commanded fuel-cell current is `ems-sdp`'s
> **1.1861 A**, 5.1 % under it. The Gate figures above stand, because
> `ems-soc-band` is genuinely clear.
>
> Validating the mechanism under control requires the two deliberately
> constructed scenarios
> `fw26-clamp-cruise` and `fw26-clamp-sweep` (`docs/HIL_SCENARIOS.md`). The
> first holds one high two-source total and steps the share once; the second is
> a `'Y'`-shaped twelve-region sweep that crosses the boundary on both axes and
> carries the on-board bit-identity pin, which asserts that below the ceiling
> fw v26 reproduces the fw v25 droop codes.
>
> `tools/governor_model.py` ports the clamp in the firmware's exact order, and
> `tools/test_governor_ceiling_equivalence.py` compares the port against the
> compiled firmware over one scripted sequence rather than against a written
> expectation.
>
> **THE THIRD CASE (campaign E, 2026-09-03).** This note named two regimes -- a
> demand step at the converged ratio, and the clamp's own roughly 5 slew ticks
> plus 20 ms filter -- and both were confirmed numerically on the board, against
> the hi-fi plant; the delivered peak is an upper bound for a lagging converter.
> It did
> not name the regime that latched `FAULT_OC_FC` on `fw26-clamp-sweep`: a
> **demand step CONCURRENT with an upward share request**, where the two errors
> add. The filter under-read the rising total by **25.6 %** against the clamp's
> 12 % design headroom, and the governor held what it believed was 1.2500 A
> while the board delivered **1.4890 A**. The governing comparison is a race
> between the slew-limited reference (4.3 ticks to cross the safe delivered
> share) and the filter (25 ticks to make the clamp bind), and the necessary
> condition is `I_tot > LIMIT_I_FC_MAX / DROOP_R_MAX` = **1.647 A** two-source.
> No registered EMS stimulus exceeds 1.4714 A, so the hazard is presently
> unreachable on the registered set -- a statement about the stimuli, not a
> structural guarantee. The firmware is unchanged by operator ruling (closing
> the race would need the filter alpha at or above 0.25, or a share slew at or
> under 0.0027 per tick); the sweep's stimulus now carries a bridging
> sub-region and the EMS strategies carry a rule. Full statement:
> `docs/fw26_current_ceiling_governor.md` section 8.6.
>
> **First hardware calibration** (`fw26-clamp-cruise`, campaign E): engagement
> 3.3 to 17.7 ms and Pi-cadence-limited rather than clamp-limited; the
> reference walks onto the bound in about 6 ticks; settling 35 ms; overshoot
> 0.016 % at a settled total and +0.031 to +0.045 A on a pure upward load step
> at an already-clamped share.

### 4.4a Converter asymmetry (`--asymmetry`, 2026-09-01)

The two boost chains are not identical parts. `--asymmetry` selects whether the plant
models the difference. **`measured` is the DEFAULT** (operator ruling, 2026-09-01); `off`
restores the two identical chains and reproduces every trace recorded before this switch
existed, bit for bit.

| Parameter | Value | CI₉₅ | Applied as |
|---|---|---|---|
| ΔV₀ = V₀,FC − V₀,BT at s_B = 1 | **+0.013522 V** | [+0.00097, +0.02429] | `v0_offset_fc` = +ΔV₀/2, `v0_offset_bt` = −ΔV₀/2 |
| ρ = s_F/s_B → `droop_scale_fc` | **0.9434** | [0.9205, 0.9636] | multiplies the FC chain's realized droop resistance |
| `droop_scale_bt` | 1.000 | — | reference channel |

Source: `docs/modeling/asymmetry_fit_20260901/fit_summary.json`, `M2.params`.

**These two numbers are one fit and move together.** The first implementation of this
section took **M1**'s ΔV₀ = +0.0444 V — a one-parameter fit that sets ρ = 1 *by
construction* — and combined it with a ρ estimated separately from the single-source
regime. That double-counts: with ρ pinned at 1, M1's ΔV₀ has already absorbed whatever
droop-ratio mismatch the corpus contains, so adding ρ back on top applies the same physical
asymmetry twice. Against CAL-1 (α = 0.5354 / 0.5262 / 0.5327 at I_tot = 0.452 / 0.935 /
1.346 A, commanded r = 0.5), RMS share error:

| parameterization | ΔV₀ | ρ | RMS |
|---|---|---|---|
| M1 ΔV₀ + separately-fitted ρ (first shipped) | 0.0444 | 0.930 | 0.0402 |
| M1 alone (ρ = 1) | 0.0444 | 1.000 | 0.0253 |
| **M2 consistent pair (adopted)** | **0.013522** | **0.9434** | **0.0063** |

The decisive evidence is the *shape*, not only the RMS: CAL-1's deviation from r is **flat
in I_tot**, which is the ρ signature. A voltage mismatch produces a deviation going as
1/I_tot, so a fit placing the whole effect in ΔV₀ must over-predict at light load and
under-predict at heavy load. The engine reproduces CAL-1 at **RMS 0.0064** in `design`
mode, confirming the adopted pair end to end. Note also that ρ's interval **excludes
1.000** — under the consistent pair the droop mismatch is significant, where the retired
single-source estimate 0.930 [0.834, 1.079] was not.

⚠️ **Until 2026-09-03, the simple engine and the offline controller models
(`governor_model.py`, the walk, the MPC surrogate) carried only the ΔV₀ half of this pair
and omitted the 0.033 Ω common series floor.** The corrected split law is recorded in
`docs/modeling/governor_split_law_20260903.md` (written in parallel with this fix round).

**Sign, stated once.** ΔV₀ > 0 means the FC chain regulates high and over-delivers current
at every load. The offsets are applied **antisymmetrically** about `V0_NOLOAD`, so the mean
no-load voltage of the two chains is unchanged and the bus-level baselines move as little
as the mismatch allows. A reviewer confirmed `V_bus` **bit-identical** at a pinned actuator
point between `off` and `measured`: every `V_bus`-referenced pin in the suite is
mean-preserved and none of them moves with this switch.

**The injected voltage scales with the droop mode.** What the corpus measures is a *share*
deviation; the fit converts it to a voltage through A = ΔV₀/(k_d·s_B), so the reported ΔV₀
is a **lumped A·k_d at the design droop** and the physical voltage it names is only as
certain as the droop realization assumed to derive it. Injecting the literal number under
`--droop measured` (`DROOP_SCALE` 0.21171) drives the share deviation up by 1/0.21171 — with
the M1 value the delivered α at r = 0.5 and 0.5 A reached **0.80**. The plant therefore
scales the injected voltage by the mode's own droop scale, making the **share** deviation
the invariant across droop modes. Measured at r = 0.5: α = **0.5248** (`design`) /
**0.5207** (`measured`) at ≈ 1.0 A; the residual is the fixed 0.033 Ω series floor, which
does not scale.

**The sense-arm correction is discriminated on the INA offsets actually injected**, not on
whether a `NoiseConfig` object exists. A pair of zero offsets shifts the *measured* share,
and at r = 0.5 its equivalent voltage is k_d(δ_F − ½(δ_F+δ_B))/0.25 = **+0.0120 V** at the
plant's injected defaults {+0.020, 0.0} (fit document §7.1). `NoiseConfig(ina_zero_offset=0.0)`
is a real configuration that injects nothing, and simple and replay modes construct no
`NoiseConfig` at all — all three correctly keep the full ΔV₀.

> **⚠️ THE CONFRONTATION, RECORDED HONESTLY.** Under the M2 pair the sense arm (+0.0120 V)
> is *comparable to the whole voltage term* (+0.013522 V), so a `--noise` run injects a
> residual near zero (0.001522 V). That is not an arithmetic defect: the M2 partition says
> most of the corpus deviation is **droop ratio**, which `droop_scale_fc` carries and the
> sense arm does not touch — so a `--noise` run keeps essentially all of the asymmetry and
> loses only the small voltage term the INA offsets were already supplying. The result is
> **clamped at ≥ 0**: a negative ΔV₀ would invert the fitted sign on the strength of two
> near-equal numbers with overlapping intervals, which the data supports in neither
> direction.

**Where it acts.** In hi-fi mode the two `Boost` objects carry it: the voltage offset moves
each channel's regulation target and the droop scale multiplies whatever
`--droop {design,measured}` already realizes (BT at 1.000 keeps the measured anchor). In
simple mode there are no converter models, so the same physics enters as the document's
static share law with ρ = 1 — α = r + ΔV₀·r(1−r)/(k_d·I_tot), k_d = `K_DROOP` 0.30 Ω,
clipped to [0, 1] and skipped below 0.10 A of source total where the term diverges. Simple
mode is **not** droop-scaled: `--droop` has no effect under `--electrical simple`.

**Light-load single-source behaviour.** A voltage mismatch starves the low channel entirely
once ΔV₀ exceeds the bus drop across the other channel's droop, i.e. below roughly ΔV₀/R_B
of total current. With the retired M1 value that threshold was **~140 mA** — inside the
idle segments of several scenarios. With the adopted M2 value it is **~21 mA**, below
`I_AUX_A` = 0.15 A and therefore below anything a live scenario dwells at. The retired
parameterization would have made the plant single-source through every idle segment of the
FTP-75; the adopted one does not.

**What this mode does NOT claim.** Two open findings are untouched by it, and neither may
be cited as explained by it:

- **The +8.1 % shared/single droop residual remains open.** With a *pooled* bench anchor
  the shared-regime identity is ½(R_F+R_B)/(R_F ∥ R_B), which is stationary at equal
  channels; the measured mismatch moves the shared value by **−0.078 %**. The asymmetry is
  real and belongs in the plant for its own sake, but it is not the mechanism behind the
  ratio discrepancy (fit document §8).
- **The ~4× `K_DROOP` design-versus-bench gap remains open** (see the `K_DROOP_BUS`
  banner). This mode changes the *ratio* between the channels, not the *level*, which is
  what `--droop` addresses and does not explain either.

**Comparability.** Every share, per-channel current and EMS total from a `measured` run is
on the far side of a baseline boundary from every campaign before 2026-09-01. Campaign
`20260901_151156` is the last symmetric one. `config.asymmetry`, `config.asymmetry_dv0_v`
and the two droop scales are written into every run's meta sidecar unconditionally, so a
key that is absent reads as "old tool", never as "symmetric".

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
| `ETA_CHG` | 0.88 | Ag105 input→pack energy efficiency, both engines. `AG105_Silvertel.pdf` "DC Electrical Characteristics" item 1 ("Charge Efficiency EFF 88 % typ"), whose Note 2 states the point as 25 °C, 12 Vin, 3 series cells. **Our point differs** (15–16 V in, 2S), no data exist for it, and the operator ruled a static 0.88. **`TODO(verify)`** — bench-measure input/output power at 15 V in, 2S. See §4.6.1. |
| `V_CHG_LOAD_FLOOR` | 8.0 V | Floor on the charger input-current stamp's division, pinned equal to `AG105_V_IN_MIN`. PHYSICAL, not numerical: the plant carries no charge current below it, so no legitimate state evaluates the stamp between 1 and 8 V. Bounds the stamp at 2.98 A on a dark node. Deliberately NOT equal to `V_MOT_LOAD_FLOOR`, which guards a load that does operate down to a dark node. |

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
filtered). **THE THRESHOLD VALUE COMES OFF observation-frame byte 15**, which the
model converts with `hil_plant_sim.ag105_mppt_volts()` — 11.0 V + 0.088 V/count,
the firmware's `AG105_MPPT_V_BASE` / `AG105_MPPT_V_PER_CNT` / `AG105_MPPT_VOLTS`
macros, pinned host-side by `tools/test_hil_plant_sim.py`'s `ag105_mppt_volts`
test.

> ⚠️ **BYTE 15 IS A FIAT HIL MIRROR, NOT A BOARD REGISTER WITNESS**
> (corrected 2026-09-02; this section previously called it "the board's").
> Under `HIL_SIM` the fw v24 threshold **manager is never called** — its sole
> call site sits outside the HIL branch — and the branch instead recomputes
> `ag105MpptRegCnt` by fiat from the injected `V_chg` on every settled tick,
> gated only on `chargerHasPower()`. That bypasses the manager's entire state
> machine: the windowed-minimum tracking, the ≤2-per-session monotone-lower
> ratchet, the 3-count deadband, the ≤8-per-boot EPROM write budget, the
> read-verify handshake — **and the regen exclusion**. The real manager samples
> only while `fcChargePathIsPowering()` (`FC_CHARGE_ENABLE` high AND
> `REGEN_ENABLE` low); the mirror also runs on the REGEN path, where regen lifts
> `V_chg` toward the 18.1 V clamp. Divergence measured on campaign
> `hil_report_20260902_011926`: inside a braking window (switch `0x2f` — REGEN,
> no FC_CHARGE) the mirror reads **27** at `V_chg` 18.08 V while the board would
> hold 15–19; over the whole run **11.8 % of ticks differ, by at most 12 counts
> (1.056 V)**, with 40 gate-binding ticks either way (an observational tie here,
> not a causal one).
>
> What an HIL run therefore validates: the count arithmetic, the clamp band
> [15, 27], the frame plumbing, and the charger model's response to a threshold.
> What it does **not** evidence: that the manager ran, that a write policy was
> honoured, or that any count motion is write-budget evidence. Suite checks
> named for the manager (`mppt_threshold_written`, `mppt_threshold_moved`) are
> mirror-carried readings and are labelled as such.
>
> **Calibration note, corrected 2026-09-02 (N2).** The `ETA_CHG` = 0.88 charger
> era lifts `V_chg` by **+0.487 V** in the mean (**+0.774 V** at the window
> minimum), and the count band was predicted to shift up with it, to about
> 21–22. It did not: the measured cruise **peak is 19**, because
> `AG105_MPPT_N_FLOOR` **binds**. `V_chg` sags to ≈ 14.45 V under charge, so
> (windowed minimum − `AG105_MPPT_MARGIN_V` 3.0 V) = 11.27 V, below the floor's
> 12.320 V; the effective margin is therefore ≈ 2.13 V, not 3.0 V, over about
> 85 % of the harvest. A cruise tripwire on this count must be written as a
> **peak-reaching** bound (a `min_value` on the peak), not as a floor the count
> must clear, and it must be windowed clear of the regen-lifted braking windows —
> where the mirror alone reaches 27.

`AG105_MPPT_V_THRESH` 18.0 V is only the **fallback**, used when there is
no count to use — a count ≥251 (external-resistor mode / never written, which
*is* the datasheet's 18 V default), a legacy 16-byte frame from a fw v21–v23
flash, or the window before the first observation frame. In all three the
module genuinely sits at its factory threshold, so the fallback is the
physical value rather than a placeholder.

**The threshold's semantics carry an asymmetry, and it is the datasheet's own:**
the threshold belongs to the MPPT regulator, so it binds **only while tracking is
released** (pin HIGH). Below the threshold there the module reports GENSTAT **001 Low Power** with
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

#### 4.6.1 Charge efficiency and the charger's input draw

The Ag105 is modelled as an **energy converter at a static efficiency**, `ETA_CHG` =
**0.88** (`tools/hil_electrical.py`). One rule governs both electrical engines:

```
    i_in = i_charge * V_pack / (ETA_CHG * V_input)      # input current
    i_out = i_charge                                    # pack current, unchanged by eta
    p_chg_loss = i_charge * V_pack * (1/ETA_CHG - 1)    # module dissipation
```

The input node is a switch question, and both engines answer it from
`chargerHasPower()`. With `FC_CHARGE_ENABLE` closed the input is VBUS, so the **sources**
pay. With `REGEN_ENABLE` and `MOT_PWR_ENABLE` closed alone the input is V-MOT, so the
**braking power** pays and the bus is untouched. Three sites implement the rule: the
hi-fi `N_CHG` stamp, the simple-mode bus draw, and the simple-mode motor-node sink.

**Provenance, and its limits.** The figure is `AG105_Silvertel.pdf`, "DC Electrical
Characteristics" item 1, "Charge Efficiency EFF 88 % typ". Note 2 of that table qualifies
it: "Typical figures are at 25 °C, 12 Vin, 3 series cell configuration". This rig runs
15–16 V in and a 2S (8.4 V) pack, so the conversion ratio is roughly 1.9:1 where the
datasheet measured roughly 1.0:1. No efficiency data exist for our operating point. The
operator ruled a static 0.88 for both engines rather than an unmeasured curve.
`TODO(verify)`: bench-measure input and output power at 15 V in, 2S.

**Stamp form in the hi-fi engine.** A true constant-power load has `i(v) = P/v` and
therefore a negative incremental conductance `-P/v²`. Stamping that linearization would
place a negative term on the diagonal of `G`, which is the one form that can make the
solve indefinite. The element is stamped as a **chord conductance** through the operating
point instead, referred to the **previous substep's** node voltage:

```
    v_prev = max(v[N_CHG], V_CHG_LOAD_FLOOR)
    i_in   = i_charge * V_pack / (ETA_CHG * v_prev)
    G[N_CHG][N_CHG] += i_in / v_prev
```

At `v == v_prev` this delivers exactly `i_in`. The diagonal term is positive, so the solve
stays positive-definite, and the delivered current shrinks as the node sags instead of
holding a fixed draw into a collapsing rail. This is the same form the motor draw `g_mot`
uses. It is **not** the regen Norton pattern: that element is a two-element source pair
with a zero-crossing bound, and the charger is a load.

`V_CHG_LOAD_FLOOR` is **8.0 V**, pinned equal to `AG105_V_IN_MIN`, and the value is
physical rather than numerical. The plant zeroes `i_charge` below `AG105_V_IN_MIN`, so no
legitimate state evaluates the stamp between 1 and 8 V; the floor can therefore be the
lowest input the module can charge from. With `V_pack ≤ 8.4 V` and `i_charge ≤ 2.5 A` the
stamped input current is bounded at **2.98 A** on a dark node, where the 1.0 V floor of the
first cut bounded it at 23.86 A. `V_MOT_LOAD_FLOOR` keeps its 1.0 V: the motor load does
operate down to a dark node, so its floor is an arbitrary small number and the two are
deliberately not coupled.

**The seventh power column.** `p_chg_loss_w` is appended after the six power-balance
columns and carries the module's dissipation. It is a **load-side** term, so the residual
identity is now

```
    p_mot + p_chg_loss = p_fc + p_batt + p_chop + p_bal
```

A CSV written before 2026-09-01 has six power columns and no `p_chg_loss_w`. Such a file
is a 1:1-charger-era file, and its `p_bal_w` still contains the charger term. The
`hil_power_balance` figure detects the column's absence and annotates the residual panel
accordingly.

#### 4.6.2 Physics change record — charger efficiency (2026-09-01)

**What changed.** The Ag105 was a **1:1 current transfer element** in both engines, in two
opposite ways. The hi-fi engine stamped `J[N_CHG] -= i_charge` and handed the pack the same
`i_charge`, so it destroyed `i_charge * (V_chg − V_pack)` by construction and over-drew the
bus. The simple engine computed `i_total = i_motor + i_aux` and never billed the sources
for the charger at all, so pack charge there was free energy. Both now run the one rule of
§4.6.1.

**Why.** The residual of the power-balance columns shipped 2026-09-01f made the defect
visible and quantified: on a 6 s charge probe the whole 11 W charge-window residual was the
charger term, to two decimals. A model that destroys 11 W while charging bills the fuel
cell for hydrogen the real charger would not cost.

**Measured before and after,** on a 6 s FC-fed charge probe at a 1.4 A ceiling
(`plant.v_bus` 15.9 V, `soc0` 0.6, no motor load, aux 0.15 A, **both droop codes at
mid-scale**, `MDAC_CMD_LOAD_UPDATE | MDAC_RES//2`). The droop codes are part of the recipe,
not a detail: at code 0 the same probe reads 0.9600 A / 1.4911 W / −0.4171 W and the table
below does not reproduce.

| Quantity | Simple, before | Simple, after | Hi-fi, before | Hi-fi, after |
|---|---|---|---|---|
| Bus draw `I_fc + I_batt` [A] | 0.1500 | 0.9283 | 1.5726 | 0.9799 |
| Residual after aux, `p_bal + p_aux` [W] | +11.0012 | 0.0000 | −10.6477 | −0.3957 |
| `p_chg_loss_w` [W] | — | 1.4832 | — | 1.4832 |

The two engines disagreed by 21.6 W on the same probe and now agree to 0.40 W. The
remaining hi-fi residual is the documented motoring level: aux is subtracted, and what is
left is bulk-capacitor storage plus the hi-fi motor/conductance stamp's transient term.

**One pre-existing defect is NOT fixed here, and is now stated.** `p_chop` sits on the
source side of the residual identity although it is a dissipation, so during a braking
window it enters `p_bal` twice — the braking residual is dominated by `−2·p_chop`. That
form predates this round and is unchanged by it. Moving it to the load side beside
`p_mot` and `p_chg_loss` is the obvious correction and was **deliberately deferred**
(review decision, 2026-09-01): it would change the meaning of `p_bal_w` in every CSV
written since 2026-09-01f, and that column's era boundary is better moved once, together
with any other identity change, than twice in one week. `TODO`: fold the chopper onto the
load side in the next power-balance round.

**The regen-path cap, and one alternative that was measured and rejected.** On the
REGEN-only path the charger's ceiling is the braking power, converted at `ETA_CHG` and
referred to the pack:

```
    i_target = min(ag105_i_max, ETA_CHG * p_regen_w / max(V_pack, V_CHG_LOAD_FLOOR))
```

The review proposed netting the chopper dissipation out of that first
(`p_regen_w − regen_chopper_w`), on the reading that the shunt takes its share and the
charger may only have the remainder. Measured on a 2 s braking window (`v0` 3.0 m/s,
`i_cmd` −12 A):

| Engine | Cap | Charger input | Chopper burnt | Bus-sourced |
|---|---|---|---|---|
| simple | as shipped | 1.4388 J | 1.7128 J | +0.0000 J |
| simple | netted | 0.0045 J | 3.1314 J | +0.0000 J |
| hi-fi | as shipped | 1.4016 J | 1.3046 J | +0.0881 J |
| hi-fi | netted | 0.7632 J | 1.7950 J | +0.0318 J |

The netted form removes 0.06 J of bus-sourced leak and destroys 0.64 J (hi-fi) to 1.43 J
(simple) of genuine harvest, because **the chopper is a residual absorber, not a prior
claimant**. It is a voltage clamp: a charger that sinks current pulls the node down and the
clamp backs off. The simple-mode row shows the displacement exactly — the charger's
1.4388 J of input is matched by the chopper burning 1.4230 J less, with the bus
contributing nothing. Netting removes the displacement and latches the charger off, since
`p_avail` then stays near zero and the hard clamp holds `i_charge` there. The pre-existing
test `test_charger_takes_its_share_once_powered_through_the_regen_path` fails outright
under the netted form (0.0015 A peak against its 0.02 A floor). The un-netted cap is
therefore kept.

**The hi-fi bus contribution, and what it actually is (mechanism identified 2026-09-02).**
The hi-fi row shows **+0.088059 J of the 1.4016 J charger input arriving from VBUS**,
**6.28 %** of the window's harvest. It is neither a solver transient nor a start-of-episode
precharge, and it is not a double claim on the harvest. Three measurements identify it:

- Binned at 100 ms, the bus contribution is **exactly zero in every bin in which the
  chopper is clamping**. `MOT_PWR` is reverse-blocked there (see §3.4's strict-forward
  bound), so no bus energy can reach the motor node at all.
- It appears **after clamp release**, as a steady **0.118 W**. Once the braking transient
  ends, `V_MOT` parks at `V_BUS − 35.3 mV`, which is on the conducting side of `RT_V_FWD`,
  and `MOT_PWR` forward-conducts BUS → MOT → REGEN → VCHG-IN at `mp.i` = 14.93 mA. The
  window tail is therefore **bus-fed charging** — the charger continuing to draw after the
  kinetic energy is spent — not harvest attributed to the wrong source.
- Deleting the `MOT_PWR` stamp drives the contribution to **0.000000 J** and leaves `V_mot`
  ending at 8.44 V, confirming the link, and only the link, as the path.

**The co-solve `TODO` is therefore retired.** It proposed solving the charger and the clamp
at one node voltage to remove a leak that does not exist while the clamp is active; there
is no mechanism there to close. The corresponding aggregate test ceiling (0.15 J / 12 % on
the hi-fi contribution) was **not an invariant** — it bounded a number that legitimately
scales with the tail's length — and is replaced by two mechanism-specific assertions: (a)
bus energy over chopper-active ticks differs from the charger-off run by less than 1e-6 J,
and (b) every tick with a non-zero `dE_bus` satisfies `V_bus − V_rgn ≥ RT_V_FWD`.
`tests: test_regen_harvest_is_not_sourced_from_the_bus` pins the simple-mode zero, the
one-for-one chopper displacement, and those two assertions.

**Fingerprint and hash movement.**

| Artefact | Before | After |
|---|---|---|
| `constants_hash` | `250683275d00874d…` | `6a88d04ba8a36e61…` |
| `ElectricalSim` design-mode bus anchor | 15.624602041790853 | 15.624602041790853 (unmoved) |

The engine anchor is pinned at `i_charge = 0`, where the new stamp reduces to the old one
term for term, so it does not move.

⚠️ **SUPERSEDED BY THE BLEED ERA (2026-09-02, §4.8), and only in its "after" column.** The
`eta_chg` round left the design-mode bus anchor at 15.624602041790853, and the sentence
above is the correct account of why. The per-node bleed then moved it to
**15.633912867500921**, because a 15× weaker `N_BUS` bleed draws 9.3 mV less droop across
the source resistance. That is a change of PLANT, not of accounting, and it is the value
`tools/test_hil_electrical.py` now pins. `constants_hash` moved again in the same change,
`6a88d04ba8a36e61…` → **`07530e9466a00c2a…`**. The `--asymmetry off` byte-identity claim is therefore
also intact for every charge-free trace. A trace **with** charging is not byte-identical
and is not intended to be.

**Reversal path — six edits, not one.** Setting `ETA_CHG = 1.0` does **not** revert the
round. It reproduces the old behaviour bit-for-bit only when `V_pack == V_chg`, which is
never true on this rig: the stamp becomes `i_charge * V_pack / V_chg`, not `i_charge`. A
true bit-for-bit revert is:

1. `tools/hil_electrical.py`, the `if i_charge:` block in the substep stamp — replace the
   chord conductance `G[N_CHG][N_CHG] += i_in / v_chg_prev` with `J[N_CHG] -= i_charge`,
   and drop `ETA_CHG` and `V_CHG_LOAD_FLOOR` with it.
2. `tools/hil_plant_sim.py`, `Plant.step()`, the CHARGER BILLING block — delete the
   `i_chg_in` term and restore `i_total = i_motor + self.i_aux`.
3. `tools/hil_plant_sim.py`, `Plant.step()`, the simple-mode motor-node integration —
   restore the sink to `i_sink = self.i_charge`.
4. `tools/hil_plant_sim.py`, `Plant.step()`, the Ag105 regen cap — restore the
   INPUT-referred form `i_target = min(i_target, self.p_regen_w / max(v_chg_in, 1.0))`.
5. `tools/hil_plant_sim.py` and `tools/hil_report_analysis.py` — drop `p_chg_loss_w`
   everywhere: the `Plant` attribute, the returned rails key, both CSV header lists and the
   row writer, the four-term `p_bal_w`, and the figure's trace, labels and annotation.
6. `tools/hil_plant_sim.py` and `tools/hil_report_analysis.py` — drop the fingerprint
   plumbing: `eta_chg` from `DP_FINGERPRINT_META_KEYS`, `dp_eta_chg()` and its call in
   `dp_profile_fingerprint()`, the `eta_chg` sidecar field in `main()`, and the
   `eta_chg=sim.dp_eta_chg(fp_meta)` argument in `matched_dp_for_run()`. Every table in
   `tools/dp_tables/` must then be regenerated again.

Items 1–4 are behavioural; 5 is the CSV schema; 6 is the baseline-keying. Reverting a
subset produces a plant that bills the charger inconsistently between engines, which is the
state this round removed.

**Downstream comparability.** Every campaign up to and including `20260901_151156` ran the
1:1 charger. Any figure that depends on the charger's bus draw or on hydrogen consumed
during a charge window is **not comparable** across this change. Two conclusions rest
directly on the old accounting and must be re-measured before being quoted again: campaign
`20260901_000816`'s "Ag105 charging is loss-making at rig scale", and the measured charge
lever `L_chg` = 0.2364 SoC/g behind `sdp_policy_v3`'s α calibration. Both were derived
under a plant that over-drew the bus by roughly 1.8× while charging.

**This change is expected to REVERSE the "charging is loss-making" conclusion.** The
arithmetic is direct. The bus cost of a given pack current scaled by `V_bus` before and
scales by `V_pack / ETA_CHG` now, so the ratio is

```
    V_pack / (ETA_CHG * V_bus) = 7.7689 / (0.88 * 15.3172) = 0.5764
```

at the settled operating point of the §4.6.2 probe (`V_batt` and `V_chg` read from the run
itself, not from nominal values). Charging costs **0.5764×** what it cost, so the charge
lever scales by **1.735×**: `L_chg` = 0.2364 → **0.4102 SoC/g**. Two consequences follow
mechanically:

* 0.4102 crosses the **0.31 SoC/g revisit trigger** written into the campaign-`000816`
  ruling — the condition that ruling itself named for charging to return on its own.
* 0.4102 lands inside the share lever's measured 0.409–0.415 band, i.e. the two levers
  become comparable rather than the charge lever being the clearly worse one.

`sdp_policy_v3`'s α follows `α = (1−γ)/√(L_share·L_chg)`, so α scales by `1/√1.735`:
0.1629624 → **≈ 0.1237**, which sits below the 0.239249990 charge-admission threshold
measured in the refined α-sweep and therefore does **not** by itself admit charging in the
solver. ⚠️ None of this is a measurement of the new plant: it is the old measurements
rescaled by the ratio above, and every number is sensitive to the operating point through
`V_pack/V_bus`. The re-measurement is a campaign, not an arithmetic exercise, and until it
runs neither the old conclusion nor this reversal should be quoted as a result.

### 4.7 Simplifications and their consequences

| Simplification | Consequence |
|---|---|
| **No boost-converter dynamics.** The bus is algebraic in `I_total`; there is no voltage loop, no RHP zero, no compensator lag. | Nothing here reproduces the boost-death class of failure, the τ_r lag the share-loop plant is built on, or a converter's transient response. Do not fit `τ_r` or any converter parameter against a HIL trace. |
| **No RT1987 turn-on transient.** A switch bit change takes effect within the same tick. | The *ordering* of switch operations is fully observable at 1 ms; the *hot-plug energy* that killed a boost (Death 5) is not modelled at all. A HIL pass says the sequencing logic is right, not that a real closure would be survivable. |
| **Split proportional to MDAC code ratio.** Sign- and monotonicity-preserving, wrong gain. | Share-loop *logic* testable; share-loop *tuning* not. |
| **Regen modelled end to end (§3.4, WP-C 2026-09-01) — but on THREE unmeasured constants.** The floor is gone: braking energy reaches the chopper and the Ag105. `VESC_REGEN_I_MAX_A`, `ETA_REGEN` and `R_CHOPPER_REG` are all `TODO(verify)`. | The regen PATH, the chopper clamp and the **§3.4 energy invariant tested by `test_regen_energy_balance`** are now genuine HIL results. ⚠️ That invariant is NOT the `p_bal_w` CSV column: `p_bal_w` carries `p_chop` on the source side although it is a dissipation, so on braking ticks the residual is dominated by `−2·p_chop` and closure cannot be read off it. Measured on `regen-harvest-true`, chopper-active mean `p_bal + p_aux` = **−2.3876 W**, of which **−2.0208 W** is the `−2·p_chop` term and the remaining −0.3668 W is the ordinary motoring floor. The column is a pure observer — no published number derives from it in a braking window — and the load-side migration stays deferred to **the next change of the identity** (§4.6.2). The MAGNITUDES are not: a harvest figure from a HIL run inherits the 1.5 A clip's unmeasured commanded-vs-delivered mapping and the 0.80 efficiency guess. Quote the ratio (what fraction the chopper burnt vs the charger banked), not the absolute joules. Bus-side regen rise is still absent by construction, and correctly so — `MOT_PWR` is an ideal diode. |
| **Charger status-level only; MPPT modelled at the THRESHOLD, not the tracking.** `I_charge` and `ag105_status` are injected (§4.6), so `chargingControl()`'s readiness gating and the GENSTAT fault check are live and testable. SoC and the CV/Fully-Charged branch are modelled (§4.2). **MPPT (2026-08-31, scoped; dynamic from fw v24):** with `mppt_emulation` the part's real mechanism — the **input-voltage threshold** (datasheet p.10; **not** perturb-and-observe) — IS modelled at the value carried on observation-frame byte 15 — a **fiat HIL mirror**, not a board register witness (§4.6: the fw v24 manager is never called under `HIL_SIM`, and the mirror bypasses its window, ratchet, deadband, EPROM budget and regen exclusion) — and `MPPT_DISABLE` becomes causal. The **tracking dynamics** (how the module walks its operating point once above the threshold) are **not** modelled, and neither is the I2C transport or config handshake. Off by default. | Sequencing and status-decode logic around the charger are meaningful HIL results, and so is the *threshold gate*'s interaction with the firmware's readiness-gated MPPT release (`mppt-tracking`). Charger **tuning** results are still not available. Charge **efficiency** is modelled from 2026-09-01 (§4.6.1) at a static `ETA_CHG` 0.88 whose datasheet point is not this rig's, so a harvest-efficiency figure from a HIL run is the model's constant played back, not a measurement. ⚠️ The `mppt-tracking` **hunt is fw v23 history and is now the FAILURE signature** — fw v24 lowers the threshold under the bus, so the scenario asserts harvest holding, not hunting. |
| **Single lumped bus node.** No wiring impedance, no per-source bus segment, no capacitance between nodes. | Handoff-gap phenomena of the TP0178 class (a source dropping out and the other ideal diode picking up only reactively) are not reproduced faithfully; the split here is instantaneous. |
| **No sensor noise, no quantization, no ADC path.** | Steady-state error in a HIL drive run validates the loop's *structure*, not its noise rejection. There is no encoder jitter, so the current-side chatter seen on the bench cannot appear. |

### 4.8 Physics change record — per-node bleed (2026-09-02)

*Written in the §4.6.2 pattern.*

**What changed.** `tools/hil_electrical.py` stamped one constant `R_NODE_BLEED` = 2000.0 Ω
on every node of the six-node network. It is replaced by two: `R_NODE_BLEED_BUS` = 30 kΩ on
`N_BUS`, and `R_NODE_BLEED_OTHER` = 60 kΩ on every other node. A new module function
`node_bleed_conductances()` returns the per-node conductance list, `ElectricalSim.__init__`
resolves it into `self.g_bleed` at construction, and `_substep` stamps `self.g_bleed[i]`.
Resolution at construction is the useful property: a monkeypatch of either constant places
a subsequently-constructed simulator in that bleed era.

`tools/hil_plant_sim.py`'s `R_BUS_BLEED`, the simple engine's dark-bus decay used only in
the no-source-closed branch, moves 2000.0 → 30 kΩ to match. The simple engine's LIVE bus
law (`K_DROOP_BUS_SHARED`, `V_BUS_DROOP_V0`) is deliberately unchanged.

**Why (operator ruling, 2026-09-02).** The physical bus decays from full to near zero in 30
to 60 s, and the 2 kΩ value was never calibrated against that. Most nodes bleed forward into
the bus rather than to ground, which is why the non-bus nodes take the larger resistance.

**Both values are `TODO(calibrate)`.** The bench procedure recorded at the definition site
is a **dark-node decay capture**: bring up in State 98 and close `FC_BUS` so VBUS reaches
nominal; command the boosts off and open every path switch; log `V_bus` at 1 kHz to SD until
it falls below 1 V; fit τ on ln(`V_bus`) over the linear region and take R = τ / C_node;
repeat with `MOT_PWR` closed and difference the two conductances for the `N_MOT` value.

**What it does to the DP.** The bleed the sources carry was never billed in the offline
demand model, which is one of the two defects the static-loss map corrects. The
decomposition, the map and the re-priced deviations are
`docs/modeling/dp_loss_map_20260902.md`; §9.4.1 states the result.

**REVERSAL PATH — six edits, not one.** A revert to the uniform 2 kΩ bleed must touch every
item below, because the shipped DP coefficients are fitted against the new bleed and the
stored baselines are keyed on the demand model those coefficients produce.

1. `tools/hil_electrical.py` — collapse `R_NODE_BLEED_BUS` and `R_NODE_BLEED_OTHER` back to
   one `R_NODE_BLEED` = 2000.0 constant, and with them `node_bleed_conductances()`, the
   `self.g_bleed` resolution in `ElectricalSim.__init__` and the per-node `_substep` stamp.
2. `tools/hil_plant_sim.py` — `R_BUS_BLEED` back to 2000.0.
3. `tools/hil_plant_sim.py` — the shipped `DP_BUS_V0_EFF`, `DP_BUS_R_FIX`, `DP_BUS_K_G` and
   `DP_DROOP_G_PAR` coefficients are **bleed-specific**. They cannot be reverted by
   arithmetic; the probe of `dp_loss_map_20260902.md` §3 must be re-run against the reverted
   bleed, or the map dropped entirely.
4. `tools/dp_tables/` — all FOUR committed tables must be regenerated
   (`ems-dp-replay`, `ems-ftp75-5050`, `ems-ftp75-dp`, `ems-ftp75c-dp`).
5. `tools/dp_db` — the prefilled records must be re-prefilled against the regenerated tables.
6. `tools/run_hil_suite.py` — the bands re-derived for this change must be re-derived again.

Reverting a subset leaves a demand model fitted against one bleed and a plant running
another, which is the state this round removed.

**Downstream comparability.** Every campaign up to and including `20260902_041414` ran the
uniform 2 kΩ bleed. The split removes a static load the sources carried on every tick, so no
energy total, settled operating point or cut-current anchor compares across the boundary,
whether or not the scenario charges. The predicted move is about −1.7 % `h2` on the 61 s
cycle and −2.9 % on FTP-75, with the `soc-depletion` latch about 1.5 s later. The
`scp-inrush`, `handoff-sag`, `comm-loss` and `share-staircase` anchors must be re-measured
rather than predicted, and their bit-exactness records are expected to break. Because both
values are `TODO(calibrate)`, a second move is expected after the bench decay capture.

**FIRST BLEED-ERA CAMPAIGN, and what it actually measured**
(`hil_report_20260902_220604`, fw v26, 70 of 70 executed runs correct, zero board
defects). The campaign compared the offline walk against the hi-fi engine and
recorded the firmware's response; every number in the table below is a hi-fi
PLANT output read through the firmware's response, not a hardware measurement —
this is a model-vs-model check, and the board-anchored dark-node decay capture
below (§4.8, `TODO(calibrate)`) is the step that would make it one. Every
prediction above is confirmed in direction, one is confirmed to a tenth of a
percent, the latch-shift prediction under-counted a node (see below), and one
mechanism was not predicted at all.

| quantity | predicted | plant output (firmware response observed) | kind | note |
|---|---|---|---|---|
| `h2`, loaded 61 s legs | −1.7 % | **−1.2 to −2.0 %** | plant output | confirmed |
| `h2`, `ems-ftp75-5050` | −2.9 % | **−2.88 %** | plant output | confirmed to 0.1 % |
| `h2`, low-current runs | (not predicted) | **−8 %** | plant output | `sag` −7.96, `v-bus-sense-offset` −8.01, `comm-loss` −8.54, `bringup` −8.02, `soc-depletion` −7.86 |
| `soc-depletion` UV_BATT latch | +1.5 s | **+2.6174 s** (273.593513 s) | firmware response (fault latch time against the plant's simulated `V_batt`) | see the node arithmetic below |
| `scp-inrush` `i_cut` | re-measure | **6.360327 A** (−0.031 %) | firmware response (OC teardown current against the plant's simulated current) | 16-digit bit-exactness broken as predicted; band ±0.5 % |
| `handoff-sag` cut | re-measure | **0.370455804372 A** (−1.98 %) | firmware response | same |
| `comm-loss` warm re-close | re-measure | **`I_fc` 0.1088 / `I_batt` 0.0816 A** (−71 / −76 %) | firmware response | see below |
| `share-staircase` | re-measure | **0.9008 / 0.5981 A** | plant output | FC high step / redistribution |

**The `soc-depletion` latch-shift arithmetic.** The published +1.5 s prediction was an
undocumented two-node hand estimate, not a calibrated model. Recomputed on the plant's
constants at the scenario's 14.377 V bus and 33.786 W draw: removed bleed 0.0965 W (bus)
+ 0.0999 W per other node; two pack-fed nodes give 0.578 % → +1.49 s (the published
+1.5 s — the estimate omitted a third node); three nodes (`N_OBT`, `N_BUS`, `N_MOT` with
`MOT_PWR` closed) give 0.869 % → +2.24 s against the measured +2.6174 s (1.015 %); the
remaining +0.38 s residual is the lower sag term at the state-condition latch.

The **low-current runs move about four times as far as the loaded ones**, and in the
correct direction: the removed static bleed is a larger FRACTION of a light run's
draw. A single era percentage must not be applied across scenario classes.

**The `comm-loss` collapse is the bleed itself, not a board drift**, and the control
that identifies it is in the same run. The hi-fi engine stamps N_MOT at 970 µF
(470 µF + 0.5 mF VESC input capacitance; quote one capacitance per engine — the
pre-era simple-engine τ 0.94 s is that engine's own 2 kΩ × 470 µF closed form, not
this node). The node now retains **95.15 %** of its charge across the 2.323 s
teardown (τ 1.94 → 58.20 s on the 970 µF node), so the warm `MOT_PWR`
re-close is a small step onto a nearly-full node — predicted 0.05 A, measured
0.040 A — rather than a charge-up. The COLD bring-up peak, which starts from 0 V,
moved only **−1.5 %** (0.4906 vs 0.4983 A) across the same boundary. A −72 % warm
collapse beside a −1.5 % cold peak is node retention. Report both channels: they
have not been equal since the converter-asymmetry default landed.

**Two chopper quantities rose with the bleed**, because with 60 kΩ the residual
clamp no longer releases mid-window: on `regen-harvest-true` the clamp dwell is 1418
ticks against 1227 (+15.6 %), the run coalesced **3** clamp episodes where the
asymmetry era had 6, the largest episode rose 1.5938 → **2.6707 J** (+67.6 %) and the
run total 6.3578 → **7.9741 J** (+25.4 %). On `mppt-tracking` the same mechanism
gives a clamp dwell of 1962 of 2100 ticks against 1035, and 0.9132 J per window
against 0.4908. The `ems-ftp75c-*` legs' OUT-OF-WINDOW chopper energy is
1.60–1.63 J against a 0.5 J model, 3.2×, for the same reason: the RGN node parks at
18.10–18.11 V between windows and the chopper trickles about 11 mW.

**Realizable regen fraction on `ftp75c`: 0.63, not the modelled 0.707.** Regen charge
to the pack is 0.734–0.737 C per cycle (whole run 0.796–0.809 C) against the walk's
~1.17 C. The cause is the WINDOW-LENGTH DISTRIBUTION — four of the six windows are
1.0–1.6 s against roughly 0.9 s of Ag105 dead time — and not `ETA_REGEN` or the VESC
clip. The SoC credit remains unresolvable in the trace (+4.1e-5 SoC, below the
column's quantization, against a cycle drain near −0.0019), which confirms the
standing rule that `ftp75c` is a model validation and not an EMS discriminator.

**The unbilled `FC_BUS`/`BT_BUS` diode-drop is an accounting-boundary omission, not an
implicit billing.** The two boost-link switches drop `rt_v_fwd + i·(rt_r_on + R_SHUNT)`,
and that drop **is** burnt in the plant. But `ElectricalSim._source_current` refers both
stack currents at `v[N_BUS]`, never at the switch's own output node, so the drop is billed
to **neither** source — it is not "billed implicitly through `r_fix`": that sentence is
false as an energy statement, because the drop never reaches the bus law at all. The bus
law's fixed part is instead the fitted intercept, `DP_BUS_V0_EFF` 15.871722 agreeing with
`V0_NOLOAD − RT_V_FWD` = 15.871716 to 6e-6 V, and its resistive part is `R_FIX`
(0.017986 Ω vs the two-link parallel 0.0165 Ω) — both fitted quantities, not a channel for
this drop. The resulting absolute under-bill of source energy is 0.25–0.36 % (0.250 % at
0.19 A/channel, rising to 0.362 % at 0.86 A). It cancels in every table-vs-run deviation,
because the DP demand model, `ems_walk` and `mpc_ems` all price the same `N_BUS` boundary
(`dp_loss_map_20260902.md` §1); it biases only the absolute level of `h2_cum_g` and pack
drain, inside the declared absolute-scale caveat. A share-dependent residue remains — the
`i²R` part only, since `rt_v_fwd` is linear in the total — of 0.087 % of source power in
favour of single-source at 1.15 A; disclose this residue wherever the `ems-mpc-single`
gain is quoted (§9.4.3, §11).

---

## 5. Actuator inputs — what the plant consumes

Everything the plant reads about the board comes from the **18-byte** (fw v25;
17 B under fw v24, 16 B before) observation frame, decoded by `parse_output()` (which validates length, sync
`0xB6` and the length-derived XOR span, returning `None` on any failure). The
**16-byte** fw v21–v23 layout is still accepted — same offsets below byte 15,
XOR over bytes 1–14, and `mppt_cnt` decodes as `None`. `parse_output()` prints
the length once and warns loudly if a run sees both.

| Frame field | Plant use |
|---|---|
| `mppt_cnt` (byte 15, fw v24) | the reg-`0x02` count the **HIL mirror** computed → the MPPT threshold the charger model gates on (§4.6). ⚠️ Under `HIL_SIM` this is a fiat recomputation from injected `V_chg` on every settled `chargerHasPower()` tick, **not** the fw v24 manager's output — the manager is never called, and the mirror runs on the REGEN path the manager excludes. `None` on a legacy frame → the `AG105_MPPT_V_THRESH` fallback. Also written to the CSV as `mppt_thresh_cnt` |
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
| `ems-ftp75-sdp` **(EMS-driven, opt-in, SDP-INTERIOR ROUND, 2026-08-31; rebound to `sdp-v3` 2026-09-01)** | the SAME EPA FTP-75 profile LIST OBJECT as the other two FTP-75 scenarios, at **`FTP75_SDP_PRELOAD_A` = 0.0 A** since 2026-09-01 (it was a re-derived 0.45 A against the siblings' 0.65 A; ⚠️ EVERY WALK NUMBER IN THIS ROW BELONGS TO THE 0.45 A ERA — at preload 0 the governor walk gives a single flip at **t = 272.0 s** (band re-opened to (240, 295)), governed FC peak **0.7046 A** (50 % under `LIMIT_I_FC_MAX`, so the de-rating that sized the preload is moot), pre-flip window I_fc peak 0.0788 A through an OPEN-LOOP window, and `h2_cum_g` **0.019347 g**; every threshold on the entry is PROVISIONAL again), driven by **`sdp-v3`, playing `sdp_policy_v3.json` (policy-block sha256 `0443febf…`)** with **`sdp_soc_ref_offset` = +0.013**. (Every action quoted below was read off the `v2` artifact `740c802e…`; the two share maps are identical on SoC rows 3+ and this trajectory never leaves them — see the row-diff test.) | The SDP policy's **bang-bang SHARE law**, which no run before this round could put on the wire: every earlier `ems-sdp` run started EXACTLY on the policy's target node and could only discharge, so the table sat on its fuel-cell branch and the wire carried ONE constant clamped 0.8500 for the whole run. The offset starts the run 0.013 SoC ABOVE the node, i.e. on the table's OTHER branch (action 0.00, emitted at the `SOC_BAND_SHARE_MIN` clamp as **0.15**), and the cycle's own drain walks the state across the switching boundary. | OFFLINE WALK (2026-08-31, method in the SCENARIOS entry; cross-checked against the MEASURED `ems-ftp75-5050` trace of campaign 20260901_000816, which runs +2.6 % hot against the model): a SINGLE share step **0.15 -> 0.85 at t = 195.9 s**, +/-10 % of drain moving it to 180/205 s and +/-20 % to 158/216 s - hence the suite's (150, 250) s band. Raw table requests {0.00} before, {1.00, 0.95} after. **NO charge stage is reachable** (demand never falls below bin 9 in Run), so this is a pure share-axis test. Currents: on the battery-heavy branch the commanded 0.15 is always below the governor's minority floor, so **I_fc is pinned at 0.300 A** and peak I_bt is 0.676 A (77 % under `LIMIT_I_BT_MAX`); on the fuel-cell branch **I_fc = I_tot - 0.300**, peaking at 1.112 A model / **1.1546 A measured** (the ADDITIVE composition 0.15 + 0.45 + 0.8546 - 0.300; do not scale the model's FC branch by the +2.6 % offset, which also scales the firmware's fixed 0.300 A governor floor and reads 1.141 A) - **17.5 % under `LIMIT_I_FC_MAX`**, which is what sized the preload down from 0.65 A (there the same peak is 1.355 A, 3.2 % of margin, and an OC_FC latch would truncate the run at exactly its post-flip half). **Expected fault-free**; `allow_only: 0`, unlike its socband sibling. ✔ **CALIBRATED, campaign `20260901_024231`** (the `provisional_note` is deleted): flip MEASURED at **198.537 s** (+1.35 % on the walk — an integral quantity inside 1.4 %, this walk's best result), so the band tightened (150, 250) -> **(185, 212)**; `I_fc` peaks 0.3039 A pre-flip / 1.1516 A at the cycle peak (ceilings/floors now 0.35 / 1.08 A); `I_batt` peaks 0.7117 A **at the flip**, newly bounded at 0.90 A; `h2_cum_g` 0.0621749 g, band [0.020, 0.120] -> **[0.056, 0.070]**. Bin 24 was NOT entered, so the 0.89 raw floor deliberately stays at its boundary-case value rather than tightening to the measured 0.95. ⚠️ **REBOUND TO the calibrated `sdp-v3` artifact on 2026-09-01, AND THE WALK TRANSFERS VERBATIM.** The walk above was measured against `v2` and was NOT re-run, because a row-by-row diff settles it: `policy.share` is identical at every SoC row from 3 upward (the two artifacts differ in 30 cells, all on rows 1-2) and this scenario spans rows ~63 down to ~44. On the charge axis, `v2`'s cells sit in demand bins 0-5 only and this walk's demand never falls below bin 9 in Run, so `v3`'s zero map removes cells the trajectory could not visit either way — 'no charge stage is reachable' was already the claim and is now additionally true by construction. |
| `ems-sdp-cross` **(EMS-driven, SDP-INTERIOR ROUND, 2026-08-31)** | a **two-level cruise** - 2.2 m/s to t = 70, then 1.0 m/s to the Run exit at 196 - with **no preload** (`I_AUX_A` alone), 200 s, charge ceiling 0.8 A, `sdp_soc_ref_offset` = **+0.0025**. The high level sits at P_dem ~10.6 W (bin 10, charge-FORBIDDEN) and above the 0.60 A closed-loop gate, so the governor's minority floor keeps 0.30 A on the standby channel and both the pre-flip drain and the post-flip node traverse are fast enough to fit a bench run; the low level sits at P_dem 5.37 W (bin 5, the top charge-admissible bin) - `ems-soc-band`'s own validated charge operating point. | The artifact's **two SoC switching surfaces**, which are one grid node apart: node >= 51 gives share 0.00 with no charging, node 50 gives 0.85 with no charging (a 1e-3-wide dead band), node <= 49 gives 0.85 **with** charging in bins 0-5. So this run crosses the SHARE threshold downward and then cycles on the CHARGE threshold. An UPWARD share crossing is **not reachable on this rig** - it would need a charge ceiling above 2.25 A, which on the single-source FC path is an immediate OC_FC - and nothing in the entry asserts one. | OFFLINE WALK: share **0.15 -> 0.85 at t = 43.85 s** (the run's only share transition), then **three sustained charge windows** - 75.4-83.8, 115.3-123.7, 172.9-180.9 s - each one `SDP_CHG_MIN_DWELL_S` long, period ~50-57 s. One 1.05 s admit-then-drop at t = 73.3 INSIDE the deceleration is EXPECTED and not asserted: the demand falls into bin 5 before the ramp ends and `charge_hold_status()`'s `SDP_CHG_CRUISE_DELTA_MPS` guard withdraws the intent on the next decision - the only live exercise that early-drop branch has ever had. Peak I_fc 1.1372 A (single-source FC carrying 0.337 A of load plus the 0.8 A ceiling), **18.8 % under `LIMIT_I_FC_MAX`**; peak I_bt 0.6087 A. SoC 0.700000 -> 0.697195. **Expected fault-free.** No board-side SHARE-BRANCH check is possible here and the suite entry says so: at 0.67 A of total the governor clips both branches to within 0.07 A of each other. ✔ **CALIBRATED, campaign `20260901_024231`** (the `provisional_note` is deleted) **— AND THIS SCENARIO PRODUCED THE ROUND'S ONE FAILURE.** MEASURED: flip **42.292 s** (-3.5 % on the walk, band (25, 65) -> **(35, 50)**); **NINE** charge windows at a **16.13 s** period, gaps 8.04-8.08 s (sigma 17 ms), 64103 of 120000 ticks over t = 70..190 (released fraction 0.466), longest hold **8.085 s** = `SDP_CHG_MIN_DWELL_S` + 1.1 %; `I_charge` reached its full 0.8000 A ceiling (floor 0.5 -> **0.75 A**); `I_fc` peaked **1.1920 A**, 14.9 % under `LIMIT_I_FC_MAX`, now bounded at 1.28 A. Both switching surfaces located for the first time: share at SoC 0.69800, charge at 0.69700, both on the predicted grid nodes. ⚠️ **THE WALK'S CHARGE PERIOD WAS WRONG BY 5.7x**, and the retired check `sdpx_charge_released_between` asserted the ABSENCE of a window at t = 90..108 s taken from it — so it sat on top of a real window and failed a correct board. Root cause: the walk applied the firmware's CLOSED-LOOP minority governor at a cruise drawing I_tot ~ 0.355 A, below the **0.55 A open-loop drop-out** (the `shareClosedLoopMode` gate in `powerBalance()`), where the board HOLDS its last converged split — delivered share **0.1656** against the commanded 0.85, so the real drain is -3.90e-5 SoC/s, not ~6.9e-6. The check is replaced by four PHASE-FREE properties (tick floor 12000 -> **45000**, `max_continuous_ticks` <= 9000, released-fraction ceiling 84000 ticks, `edge_count_between` (6, 12)). |
| `ems-sdp-braking` **(EMS-driven, SDP-INTERIOR ROUND, 2026-08-31)** | **four braking cycles** - 10 s at 2.2 m/s, 3 s decel to 1.0 m/s, 12 s plateau, 6 s accel back - built from the `SDP_BRAKE_*` constants (the profile is GENERATED, and asserts that its last plateau ends exactly at the Run exit), 134 s, no preload, charge ceiling **0.7 A**, `sdp_soc_ref_offset` = **-0.005**. | The policy's **charge decision on the DEMAND axis alone**. Starting below the target node pins the share command at a constant 0.85 for the whole run BY DESIGN, so with the SoC axis held still every FC_CHARGE transition in the trace is attributable to demand: the low plateaus are bin 5 (admissible) and the cruises are bin 10 (forbidden). **HONEST CAPTION: the SoC rise is FUEL-CELL-FED through FC_CHARGE, not regen harvest** - by this scenario's own demand-axis design (the decel plateaus are the charge-admissible bins), this validates the policy's decel-window charge behaviour and NOT regen capture. The zero-regen-power floor this caption used to blame was removed by the regen-fidelity model round (WP-C, shipped 2026-09-01) — regen capture itself is now exercised by `regen-harvest-true`, not by this scenario. | OFFLINE WALK: **four sustained windows, one per plateau** - 21.3-34.4, 52.2-64.8, 83.7-96.3, 114.2-126.0 s, 50.1 s of charging total - and **ZERO charge ticks inside any of the four cruise holds**. Five ~1.05 s admit-then-drop blips (Run entry plus one per deceleration), same cruise-guard mechanism as `ems-sdp-cross`'s, each shorter than `AG105_SETTLE_S` so no charge is actually delivered; expected, not asserted. Peak I_fc **1.1671 A at t = 34.4**, which is the ONE-DECISION charge overhang into the acceleration out of a plateau - the cruise guard withdraws the latch only at the next decision, so the accel current adds to the charger's on the single-source FC channel. That peak is why BOTH `SDP_BRAKE_ACCEL_S` (6.0 s = 0.20 m/s^2) and `SDP_BRAKE_CHG_CEILING_A` (0.7 A) are current-budget constants: at 0.40 m/s^2 and 0.8 A the same peak is 1.379 A, **1.5 %** under `LIMIT_I_FC_MAX`. As shipped it is 16.6 % under. Peak I_bt 0.300 A (the minority floor, all run). SoC 0.700000 -> 0.699662 - very nearly charge-sustained. **Expected fault-free.** ✔ **CALIBRATED, campaign `20260901_024231`** (the `provisional_note` is deleted) **— AND THIS WALK WAS RIGHT, for a stated reason:** these windows are DEMAND-driven, so they land on the profile's own fixed instants rather than on an integrated drain (contrast `ems-sdp-cross`, whose SoC-driven period the same walk missed by 5.7x). MEASURED: four sustained windows of four, **52.479 s** (walk 50.1, +4.7 %; floor 25000 -> **45000** ticks), longest 13.108 s, **ZERO** ticks inside both asserted cruise windows (ceiling 500 -> **100**), and the walk's **five** cruise-guard early drops to the instant (t = 3.008 / 19.175 / 50.390 / 81.624 / 112.842) - the first live exercise of that branch, now censused by `sdpb_charge_edge_census` at 8-10 rising edges = 4 windows + 4-6 drops. `I_charge` reached its full 0.7000 A ceiling (floor 0.4 -> **0.65 A**). ⚠️ Peak `I_fc` **1.2617 A** at t = 65.51 in the one-decision overhang - **9.9 % under `LIMIT_I_FC_MAX`, the tightest margin in the suite** and 8.1 % above the walk's 1.1671 A. Newly asserted by `sdpb_fc_peak_bounded` at 1.32 A; never raise it to make a run green. |
| `handoff-sag` **(hi-fi only)** | cruise from 4 s with a **+0.40 A pre-load** (pre-rail total ~0.74 A: above the 0.60 A closed-loop governor gate, below the cut's 0.5 A/channel handoff guard), share commanded to **0.0** at 6 s so the **FC** channel is cut, then a **+1.5 A** step at 20 s against the surviving BT channel (2.24 A vs `LIMIT_I_BT_MAX` 3.0 A, 25 % margin) | the share **setpoint latch** (`updateShareSetpointCutoff()`) opening a bus switch, its `SHARE_CUT_MAX_HANDOFF_A` 0.5 A load guard, and the single-source sag + UV dwell decision that follows | Bus switch open and held open, a deeper single-source droop, and either a clean ride or a correctly-latched `UV_BUS`. ⚠️ **Not** a reactive-pickup test: a setpoint-latched cut drives the switch EN-low, and an EN-low RT1987 does not conduct — nor will the firmware re-close it (the re-closers gate on `!shareSpCut*`). The rail direction is BT-surviving because at the FC rail the 1.4 A limit leaves too little perturbation budget to excite anything. Refused under `--electrical simple`. |
| `bringup` **(hi-fi only)** | none; plant from dark | the firmware's staged bring-up P0–P3 against the **real** RT1987 `t_D(ON)` 8 ms + soft-start ramps (~19.8 ms on the 100 nF switches, ~1.07 ms on the 5.6 nF ones) | Operator runs `'G'`; the phase timings in the USB log should sit outside the switch delays rather than racing them. |
| `scp-inrush` **(hi-fi only)** | VESC input capacitance forced to the **top of the envelope (0.9 mF)**, and a **three-phase V-MOT load** (behind the switch, *not* `i_aux` on VBUS; 2026-08-31 deterministic redesign): the bring-up P3 ramp runs **unloaded**, a **6.5 A fold pulse** (`SCP_INRUSH_FOLD_LOAD_A`) steps in once V-MOT crosses `SCP_INRUSH_ARM_V` 1.2 V mid-soft-start (above the model's 1.0 V Norton load floor, so the full current appears in one substep and the cut fires inside that same 1 kHz tick — phase-independent of the firmware's OC teardown), a one-shot latch withdraws it, and a **5.0 A run load** at +110 ms latches `OC_FC`. The pre-redesign t = 0 flat 5.0 A load faded in through the Norton floor and its cut raced the firmware's teardown (the 2026-08-31 two-outcome episode); the older-still +6 A at t = 8 s arrived when `MOT_PWR` had been ON since t ≈ 0.62 s, and the foldback branch exists only in `SOFT`: **zero** `scp_cut`/fold events fired. | RT1987 soft-start **foldback** on `MOT_PWR` | `scp_cut` + `sw_ring` entries in the event sidecar. Verified offline: the margin holds at 2 A (soft-start completes, `V_mot` reaches 15.1 V) and breaks at ≥ 4 A into a **64 ms burst-retry cycle** — the Death-5-class ring pattern. **Not** the Death-5 stimulus itself: that was a full-bus hot-plug onto a discharged node, no longer reproducible (`MOT_PWR` carries a 100 nF CSS and the firmware pre-charges the node). This is the nearest *legitimate* case that can still bind the foldback. Ring peaks here stay under the 20 V abs-max because the cut happens at low `V_mot`; a cut at full bus on `--trace-config long` (BT, 3.480 nH) does cross it. |
| `ems-y-b30-v1`, `ems-y-b30-v3` **(EMS-driven, 2026-08-31)** | the firmware's own `'Y'` combined table (16 regions, 40 s), copied VERBATIM from the firmware's `COMBINED_PROFILE` region table into `hil_plant_sim.COMBINED_PROFILE` and walked by `y_profile_at()` — an exact reproduction of `advanceComboRegion()`, including the clip-AFTER-interpolation rule and its intended kink. Vmax 1 and 3 m/s at the firmware's documented bound b = 0.30, plus a **+0.85 A `aux_preload_a`** (`Y_AUX_LOAD_A`, raised from 0.60 A on 2026-08-31) that holds the source total in **1.00–2.27 A**, above the 0.60 A closed-loop governor gate for the whole table. ⚠️ **Why it was raised, and why b30 results do not cross the change:** at 0.60 A the firmware's minority-current governor clipped the share to `1 − I_min/I_tot` = **0.624 / 0.672** at region 6 — *below* the table's own 0.70 clip — so the hi bound was **structurally undeliverable** and every b30 run characterised the governor instead (campaign `hil_report_20260831_191509` measured the rails at 0.632 / 0.679). At 0.85 A the bounds land at 0.714 / 0.743 and both the hi (0.70) and lo (0.30) clips are reachable at both speeds. Worst channel currents 0.999 A FC (28.7 % under `LIMIT_I_FC_MAX`) / 1.475 A BT. ⚠️ The preload **ramps in** over `SOC_LOAD_RAMP_S` from t = 4.0, so the table's first **0.59 s** (was 1.25 s) is still below the gate — inside region 0's settle, so no assertion window is affected. ⚠️ The commands are evaluated at 50 Hz, not the firmware's ~1 kHz: the share axis is unaffected (the share loop's own tick is 50 Hz), and the motor axis quantises to ≤ 12 mm/s at Vmax 3, against `e_sat` ≈ 26.4 mm/s. | **Closed-loop share tracking** under a two-axis cross-coupled excitation — the reason the firmware's table exists — reachable unattended for the first time. | `cmd_share_sp` reaches its clip **0.70** in region 6 (t = 22.0–23.5), sweeps 0.65 → 0.30 across region 10 (t = 32.0–35.0); `cmd_v_sp` reaches ≈ 0.996·Vmax at the region-7 ramp top (t → 27.0); `I_fc` ≥ **0.50 A** (Vmax 1) / **0.66 A** (Vmax 3) through **region 3 alone** (t = 13.0–16.0, where v is held constant so only the share command moves `I_fc`), against measured 0.50-split peaks of 0.4353 / 0.5850 A and measured true-run peaks of 0.5659 / 0.7606 A. ⚠️ Window and floors RE-DERIVED FROM MEASUREMENT 2026-08-31 (campaign `hil_report_20260831_191509`): the previous t = 13–20 window included region 4's ramp, where a 0.50 split alone reaches 0.4915 / 0.9217 A, and the MODELLED 0.58 / 0.80 floors sat above the true run's own region-3 peaks; the 0.45 / 0.60 pair before them belongs to the 0.60 A stimulus. **Expected fault-free.** |
| `ems-y-b00-v1`, `ems-y-b00-v3` **(EMS-driven, 2026-08-31)** | the same table at **b = 0.00** and with **NO preload**. Regions 6 and 11 command share 1.00 and 0.00, outside `[DROOP_R_MIN 0.15, DROOP_R_MAX 0.85]`. The preload is omitted deliberately: the cut is gated on the doomed channel's own current by `SHARE_CUT_MAX_HANDOFF_A` 0.5 A, so a preload would put the load exactly where the latch is REFUSED. Source total spans 0.15–1.41 A. | The **cut-and-RESTORE topology** of `updateShareSetpointCutoff()`, both channels and both directions. The two RESTORE assertions are novel: `handoff-sag` asserts a cut and then perturbs, so nothing in this suite has ever checked that a latch is released. | `SW_BT_BUS` **clear** through region 6 (≤ 100 of ~1100 ticks) and **set** again through region 7 (≥ 2000 of 3000); `SW_FC_BUS` clear across regions 10/11 and set again from region 12. **Expected fault-free.** ⚠️ At Vmax 1 the total **never** reaches the 0.60 A governor gate, so the share loop runs **open-loop** for the whole run — and Vmax 3 is barely better: campaign `hil_report_20260831_191509` measured only **20.6 %** of that run above the gate, against **12.7 %** from the model walk over the table alone. ⚠️ **The two figures are NOT reconciled and 20.6 % does not reproduce** — three later recomputations give 16.98 %, 19.33 % and 19.13 %. They are a denominator/stimulus discrepancy, not evidence about the share loop's modes; quote the range, not either endpoint, until a `governor_model.py` replay of this leg settles it. Note also that "open loop" here is not synonymous with "inert": below the gate the firmware is in HOLD or in slew-limited FEEDFORWARD (§4.4), and this leg's own commanded setpoint changes put it in the latter. This pair is a **topology** test, not a tracking one; its cut/restore verdicts are sound and any share *amplitude* read off it is not. |
| `ems-ftp75-5050`, `ems-ftp75-socband` **(EMS-driven, opt-in, 2026-08-31)** | the **EPA FTP-75** cycle at raw t = 0..340 s inclusive, 341 samples at 1 Hz (the segment of `references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf`; the raw EPA file is committed at `references/drive_cycles/ftpcol.txt` and `tools/gen_ftp75_profile.py` verifies its sha256 before generating `tools/ftp75_profile.py` — 341 raw samples decimated to 234 points, worst reconstruction error 4.4e-16 m/s). Scaled by ONE constant, 3.0/56.7 m/s per mph, so the 56.7 mph peak lands on 3.0 m/s; shifted to start at t = 5.0; ends at rest (the trace is 0 mph from raw t = 333, so no synthetic tail is appended). 350 s each, `aux_preload_a` **0.0 A** (`FTP75_PRELOAD_A`) since 2026-09-01. ⚠️ IT WAS **+0.65 A**, which put 100.00 % of the post-ramp run above the 0.60 A governor gate at a 0.800 A floor; every number in this row's last two columns belongs to that era. At preload 0 the idle total is `I_AUX_A` = 0.15 A, the peak source total is **0.9603 A** (model) / ~0.985 A measured-scaled, the share loop runs OPEN-LOOP HOLD through the idle segments (walk: 9.71 % hold / 57.12 % feedforward / 33.17 % closed), and `soc-band`'s charge branch is REACHABLE again. | The EMS layer as an **endurance** test rather than a transient one: 345 s of continuous 50 Hz commanding, ~30 accelerate/cruise/decelerate/idle cycles, and an H2 total over a cycle a reader outside this project recognises. | `cmd_v_sp` reaches 3.0 m/s at t = 245; peak source total 1.613 A, so `hold-5050`'s fixed 0.50 split puts **0.807 A** on a channel (42 % under `LIMIT_I_FC_MAX`) and `soc-band`'s 0.75 ceiling puts **1.210 A** (14 %); `h2_cum_g` ≈ 5.5e-2 g (`hold-5050`) / 8.2e-2 g (`soc-band` saturated). Both legs are expected **fault-free**. ⚠️ **The `ems-ftp75-socband` `OC_FC` ALLOWANCE IS RETIRED** (operator ruling, 2026-09-01): six campaigns ran the scenario and never used it, the measured peak `I_fc` held the 14 % margin its derivation predicted, and an allowance nothing exercises is a hole rather than protection — it silently excused the one fault this scenario is most likely to produce. Operator ruling (b) itself is unchanged (`charge-cruise` still REQUIRES `OC_FC` under it); what is retired is hedging on this entry. ⚠️ **RETIRED 2026-09-01:** the 0.800 A floor was ABOVE `SOC_BAND_CHARGE_ENTER_ITOT_A` 0.60 A, so the policy's charging branch could not open here. With the preload removed the floor is 0.15 A and the branch IS reachable — newly asserted by `socband_ftp_charge_opened` (existence only; the window schedule is unmodelled because `ems_walk.py` gates charge admission on the DP's `charge_mask()`, not on the strategy's own hysteresis). PROVISIONAL bands at preload 0 **and at the plant's default converter asymmetry** (§4.4a, the M2 consistent pair): `I_fc` ≥ 0.40 A (5050) / 0.56 A and ≤ 0.85 A (socband) at the peak, `h2_cum_g` [0.022, 0.037] / [0.028, 0.046] g. ⚠️ **TWO ERA BOUNDARIES, and campaign `20260901_151156` is the last campaign on the far side of BOTH** — the preload removal and the asymmetry default. Symmetric → asymmetric governor-walk hydrogen deltas at the M2 pair: 5050 **+6.40 %**, socband **+3.22 %**, sdp **+2.95 %**, dp **+4.32 %**; every SoC fall shrinks correspondingly. (These are ~two thirds of the figures first recorded here, which were walked at the retired M1 ΔV₀ 0.0444 — the M2 partition puts most of the mismatch in the droop ratio, the weaker hydrogen lever.) The walk has no ρ, so it is driven at the ΔV₀ that reproduces the plant's own α at r = 0.5, 1.0155 A (0.030223 V); the two laws agree there and diverge away from it, well inside the ±25 % band. `V_bus`-referenced pins are **mean-preserved** and do not move (§4.4a). Do not quote a pre-2026-09-01 total against these bands. |
| `mppt-tracking` **(EMS-driven, 2026-08-31)** | the `charge-regen` speed profile (**the same list object** — a comparison across the two is only meaningful on one stimulus) driven by `mppt-harvest`: `charge_goal` on the braking windows (regen path, `MPPT_DISABLE` held LOW by the firmware's own regen branch) **and** on the 0.4 m/s low-cruise plateaus (FC path, tracking released). `mppt_emulation` **True**; `chg_i_ceiling_a` **1.0 A**. The FC path is single-source (`assertFcChargeEnable()` drops BT off the bus), so the budget is 0.15 aux + ~0.06 motor + 1.0 charge = **1.21 A**, 14 % under `LIMIT_I_FC_MAX`. `mppt-harvest` is a SEPARATE function from `regen-harvest`, deliberately: `charge-regen` has pinned measurements across five campaigns and must not move because this scenario's windows did. | The **MPPT input-voltage threshold** against the firmware's readiness-gated MPPT release — the first scenario in which `MPPT_DISABLE` does anything causal. From fw v24 it also exercises the **threshold manager**: the FC path feeds the charger from the ~15.95 V bus, and the firmware must lower reg `0x02` under it rather than hunt against the 18 V default. | ⚠️ **THE OBJECTIVE INVERTED AT fw v24 — the hunt below is now the FAILURE signature.** fw v24's manager writes reg `0x02` to (windowed-min `V_chg` − 3.0 V), clamped in counts to **[15, 27] = 12.320–13.376 V** (`AG105_MPPT_N_FLOOR` = 15 / `AG105_MPPT_N_CEIL` = 27 through `AG105_MPPT_VOLTS`), so the module stops refusing, `ag105IsReady()` holds and the pin stays released. The suite's retired 2200-tick ceiling is replaced by a phase-free **edge census** (3–8 rises across the cruise windows), the Low-Power check is inverted to an absence bound, `MPPT_EN|PWR_TRACK` — unreachable under fw v23 — becomes the steady state, and the new `mppt_thresh_cnt` column is a mirror-only byte exercise: under HIL the real `ag105ManageMpptThreshold()` is bypassed, and the count evidences the fiat mirror's formula, not the manager's execution. **THE fw v23 RECORD, kept because a regression reproduces it:** the firmware releases tracking only once the charger reports ready (`ag105IsReady()`, in `chargingControl()`), and releasing it is exactly what stopped the charging that made it ready, so the two **hunted**. Measured on hardware (campaign `20260831_191509`): full period **~40.05 ms** median — ⚠️ RECORD CORRECTED 2026-08-31, this line quoted the offline probe's 80.0 ms, which the campaign's 138 MPPT_DISABLE toggles over the cruise windows arithmetically rule out (80 ms would give about half that many). The firmware acts on the previous 50 Hz poll, so it lags by one tick in each direction. Pin HIGH 50.0 % of ticks, GENSTAT 001 on 50.0 %, `MPPT_EN`-without-`PWR_TRACK` on 50.0 %, `I_charge` equilibrium **0.465–0.525 A** — near half the ceiling, which is why the suite's `charging_occurred` floor is 0.25 A and not 0.5. The pin can only be HIGH inside the strategy's INSET cruise-charge windows, i.e. 3 × 1.5 s less 3 × `AG105_SETTLE_S` = **3.0 s**, so the hunt is ~1500 ticks and a stuck-high pin ~3000 — the retired `mppt_not_stuck_high` ceiling was **2200** between them. ⚠️ Under fw v24 the ~3000-tick outcome is the EXPECTED one, which is why that ceiling had to be replaced rather than re-tuned. **Expected fault-free**, though the realized FC-path margin narrows: the hunt used to hold the mean charge current near half the ceiling, and continuous harvest draws the full 1.0 A that the 1.21 A budget already assumes. |
| `charge-to-full` **(2026-08-31)** | `pi_timeline`: MODE_SAFE 0.5, MODE_HYBRID 3.0, `v_setpoint` **0.0** and share 0.5 at 5.0, `charge_goal` 1.0 at 8.0. 130 s, `chg_i_ceiling_a` **1.0 A**, and the suite overrides **`--soc0 0.990`** (the second such override, mirroring `soc-depletion`'s — which starts LOW to reach a UV latch where this one starts next to FULL). 0.995 − 0.990 = 0.005 of a 5 Ah pack = 90 A·s = **90 s** at the ceiling, so FULL is expected ~t = 100. Standstill is load-bearing: `v_setpoint` 0 < `V_SP_ZERO_THRESH` means 0 A to the motor, which is what makes the single-source budget 0.15 + 1.0 = **1.15 A** (18 % margin) work for 120 s. ⚠️ `mppt_emulation` is deliberately **OFF**, and stays off under fw v24 — the 18 V gate would have blocked this very path outright, and the fw v24 clamped threshold would simply be inert on a continuously-fed standstill charge. | The Ag105 **Fully-Charged / CV** branch, never reached by any prior campaign (largest SoC rise on record ~0.0009 against the ~0.29 that `--soc0 0.7` needs), and the firmware's deliberate **no-action** response to it. | `I_charge` ≥ 0.8 A in CC (t = 10–60); GENSTAT **011** and the **CV** flag held ≥ 500 ticks after t = 60; `I_charge` ≤ 0.05 A after t = 125 (the new `max_value` ceiling kind); and `SW_FC_CHARGE` **still set** after t = 110 — the no-action baseline made visible, so a future policy change to it fails a check instead of surprising a reader. **Expected fault-free.** ⚠️ Zero drive-channel coverage. `CHARGER_STAT` (pin 6) is on neither HIL frame and `chargingControl()` does not read it, so its Fully-Charged blink signature is out of scope; carrying it would be a frame extension. |
| `pi-silence` **(EMS-driven, 2026-08-31)** | `hold-5050` with **no `ems_v_profile`**, so it falls back to `EMS_DEFAULT_CRUISE_MPS` = 1.2 m/s — that fallback IS the setpoint here, chosen because the model's ~3.5 A hold current makes the motor cut-off unmistakable. The commander goes **permanently silent at t = 8.0** (`pi_mute_after_s`): `PiCommander.tick()` returns `None` without advancing its timeline, counter or `next_tx`, so a dead Pi neither scripts nor queues. The **injection** stream keeps running at full rate. 14 s. | The firmware's **Pi watchdog** (`checkPiWatchdog()`, `PI_TIMEOUT_MS` 500, armed in State 2/3 once `pi_ever_connected`), isolated from the HIL link. Its clock is stamped **only** by `receiveCommands()`’s 22-byte command branch; every prior stimulus gated both streams together (`apply_scenario()`’s `tx_enabled` return) and tripped the HIL staleness path instead. | **`FAULT_PI_TIMEOUT` REQUIRED**, `not_before_s` 8.0, in State 2 at t = 7.5. Plus `motor_halted`: commanded `current` falls ≥ 2.0 A across the latch — the fault's consequence, not just its flag. ⚠️ 0x0010 is shared with `FAULT_HIL_LINK`, so the entry declares **`child_tx_healthy`**. From **fw v25** that is a DIRECT READ of frame byte 16 (`ERR_PI_TIMEOUT` 0x05 vs `ERR_HIL_STALE` 0x10); on fw v21–v24 it falls back to the older inference **by elimination** (a continuous injection stream rules the alias out). Injection never stops, so no fw v23 run boundary forms and the latch persists; a mid-run warm reset would prove contamination *and* clear `pi_ever_connected`, disarming the watchdog under test — which is why `warm_resets_expected` is deliberately absent. |
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
  ⚠️ **Do not reconstruct these columns from `V_fc·I_fc`.** `Gfc` takes the fuel cell's
  **stack** power, not the bus-side product of the two logged rails; reconstructing
  `h2_cum_g` from `V_fc·I_fc` reads **31 % low**. If a consumer needs hydrogen, it reads
  these columns; there is no supported way to re-derive them from the rail columns.
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
- `p_mot_w`, `p_fc_w`, `p_batt_w`, `p_chop_w`, `p_aux_w`, `p_bal_w` (appended
  **last, after `error_code`**, 2026-09-01f) and `p_chg_loss_w` (appended after
  those six, 2026-09-01) — the per-tick power balance in
  watts, 6 dp. Declared in **both schemas** so their tail indices are fixed, but
  populated on **simulated ticks only**: a replay bypasses the plant integrator,
  so every replay row is **blank**, never `0`. `p_mot_w` is the electrical power
  at the **V-MOT node** — `+ i_motor·V_rgn` while motoring, `− p_regen_w` while
  braking. The two branches are exclusive by construction: `p_mech` and
  `p_regen_w` are the positive and negative halves of one `p_shaft`, so at most
  one is non-zero on any tick. **V-MOT is the correct node because of the regen
  sign, not the diode drop:** braking power enters the network at `N_MOT` and
  leaves through `REGEN`, never back through `MOT_PWR` (the RT1987 blocks
  reverse), so a VBUS booking `V_bus·i_motor` would be **identically zero
  throughout every braking window** and would show no returned energy at all.
  `p_fc_w` is the **bus-side** fuel-cell power
  `V_bus·I_fc`; it is **not** the stack power `Gfc` integrates (§9.3 uses
  `v_terminal·i` on the source side), and the two differ by the boost efficiency
  and voltage ratio. `p_batt_w` is the **net** pack power, `V_bus·I_batt` minus
  `V_batt·i_charge` — power into the pack **terminals**, with the pack's own I²R
  inside that boundary; the current is the same one the SoC integrator is
  given in both engines, so this column and `soc` tell one story, and charging
  drives it negative. The charge term reads the **clean** pack terminal voltage,
  not the sensed `V_batt` rail, so the identity still closes under `--noise`;
  the two `V_bus·I` terms stay on the sensed side, since those are the powers a
  consumer reconstructs from this CSV's own rail and current columns. `p_chop_w` is the braking-shunt dissipation. `p_aux_w` is
  the housekeeping load `V_bus·i_aux`, including any scenario preload or drain.
  `p_chg_loss_w` is the Ag105's own dissipation,
  `i_charge·V_batt·(1/ETA_CHG − 1)`, ≥ 0 by construction (§4.6.1). `p_bal_w` is
  the residual `p_mot + p_chg_loss − (p_fc + p_batt + p_chop)`, written out so a
  consumer can test the identity per tick without recomputing it. ⚠️ A CSV
  written before 2026-09-01 has **six** power columns and no `p_chg_loss_w`; its
  `p_bal_w` still contains the charger term, because the plant that wrote it had
  a 1:1 charger.

  ⚠️ **The identity is not exact, and the residual's components are named.** In
  descending magnitude:

  1. **The auxiliary load** — hence `p_aux_w` as its own column; subtract it first.
  2. **Bulk-capacitor storage**, `d/dt(½CV²)` on the VBUS 470 µF and, in hi-fi,
     the other node capacitances.
  3. **The hi-fi motor stamp's transient term.** The load is a conductance
     `g_mot = i_motor/v_prev` (`hil_electrical.py`), so the solved tick
     draws `i_motor·v_new²/v_prev` while `p_mot_w` books `i_motor·v_new` — a
     difference of `i_motor·v_new·(v_new − v_prev)/v_prev`. With (2) this is what
     makes the motoring residual peak near 13 W during bring-up while its
     steady-state mean stays under 0.4 W.
  4. **RT1987 ideal-diode drops** — `MOT_PWR` only, `i_motor·(V_bus − V_rgn)`,
     small, ≤ 35 mW at 1 A (the servo holds ~35 mV, not a PN V_f). Observer-only:
     the two boost-link (`FC_BUS`/`BT_BUS`) drops have no item here and are not
     billed to either source (§9.4, the `_source_current` accounting boundary).
  5. **The chopper's sign in this identity form.** `p_chop` is a dissipation but
     is grouped with the sources, so during a braking window it enters the
     residual twice. This form predates the charger-efficiency round and is
     unchanged by it; the braking residual is dominated by `−2·p_chop`.
     Measured on `regen-harvest-true`, chopper-active mean `p_bal + p_aux` is
     **−2.3876 W**, of which **−2.0208 W** is that doubled term and the residual
     −0.3668 W is the ordinary motoring floor of items 2–4. **Consequence:
     `p_bal_w` is not a closure test in any chopper-active interval.** It is a
     pure observer — no published result in this document derives from it in a
     braking window — and the §3.4 energy invariant, which `test_regen_energy_balance`
     asserts, is the statement that actually carries closure. Moving `p_chop` to
     the load side is deferred to **the next change of the identity**, so the
     column's era boundary moves once rather than twice.

  ⚠️ **THE CHARGER LEFT THIS LIST ON 2026-09-01.** It used to be item 2 and the
  largest term of all: the model's Ag105 was a **1:1 current transfer element**,
  so it destroyed `i_charge·(V_chg − V_batt)` in hi-fi and gave the sources free
  energy in simple mode. Both engines now bill it through `ETA_CHG` (§4.6.1) and
  the module's dissipation is the `p_chg_loss_w` column. **Do not read a
  pre-2026-09-01 CSV's residual against this list** — on those files the charger
  is still inside `p_bal_w`, and the `hil_power_balance` figure says so on the
  residual panel.

  Measured on a 6 s FC-fed charge probe (1.4 A ceiling, 15.9 V bus, aux 0.15 A),
  `p_bal + p_aux`: simple mode **+11.0012 W before, 0.0000 W after**; hi-fi
  **−10.6477 W before, −0.3957 W after**. `p_chg_loss_w` reads 1.4832 W in both.
  The bus draw `I_fc + I_batt` moves 0.1500 → 0.9283 A in simple mode and
  1.5726 → 0.9799 A in hi-fi; the two engines disagreed by 21.6 W on this probe
  and now agree to 0.40 W. §4.6.2 is the full change record.

  ⚠️ **This bears on a published EMS conclusion.** The retired over-draw billed
  the sources for hydrogen a real charger would not cost, so campaign
  `20260901_000816`'s finding that **Ag105 charging is loss-making at rig scale**,
  and the measured charge lever **L_chg = 0.2364 SoC/g** behind `sdp_policy_v3`'s
  two-sided α calibration, both rest on the pre-η charger. The finding's
  *direction* is not in question — the share lever is 0.409–0.415 SoC/g, well
  clear — but its *margin* was model-dependent and must be re-measured on a
  post-η campaign before being quoted as measured physics.
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

Observed on a typical host: **20 substeps/tick, 55.9–77.0 kHz achieved** (campaign
`hil_report_20260902_011926`, per-run means; the earlier "~30–40 kHz" figure is stale).
Single-tick dips to ~2–10 kHz on host descheduling are normal and are absorbed by the
EWMA; the 6859 Hz minimum recorded in that campaign is one stalled tick, and `n` never
fell below 17 around it.

⚠️ **Two reporting caveats.** First, the sidecar's `achieved_substep_hz` is the
**last-tick** rate, not a run aggregate — read the CSV column, not the sidecar, when the
question is about the run. Second, the rate alone does not answer the accuracy question:
the quantity the 125 µs caveat (§2) constrains is the substep **count**, so the
`elec_substep_n` column is logged per tick and the `substep_resolution` suite gate asserts
`n_min ≥ 8` (equivalently h ≤ 125 µs). The gate is non-vacuous: it fires on two runs of
that campaign. Tick 0 initialises at `n` = 8 before the first cost measurement exists.

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
> `tps61288_full_model.py` (its simplified share plant) / system_model.md §6d.
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
> with `over_absmax: true` reports a bound, not a computed ring; it is non-certifying, and
> the run summary calls it out.

**The `over_absmax` VERDICT is confined to the load-dump class (2026-09-03).**
`DI_DT_LOAD_DUMP` is a FIXED worst-case slew with no `i_cut` scaling — the constant
says so — so `_open()` adds the same **1.95 V** allowance (1.5 nH × 1.3e9 A/s)
whether the switch was carrying 6 A or 65 mA. That is a defensible bound for a
Death-5-class cut and a nonsense one for a milliamp release.

The conflict this created is **structural, not a calibration**. The estimator's
implied node ceiling is `V_ABSMAX − 1.95` = **18.050 V**, which sits **50 mV BELOW**
the chopper clamp's forward-conduction state `V_CHOPPER_TRIP − RT_V_FWD` =
**18.065 V**. `regen-harvest-true` REQUIRES that clamp (`signal_regen_clamp_dwell`
≥ 800 ticks), so **any commanded REGEN open while the chopper conducts failed the
check, in any era, at any cut above the 50 mA emission gate**. Campaign
`hil_report_20260902_220604` measured it: three commanded REGEN opens at `i_cut`
0.065 A, `v_node` 18.0639 V, estimated peak 20.0139 V — over by 13.9 mV, against the
hot-loop, current-scaled bound `peak = v_node + 0.130 V/A · i_cut` (0.130 V/A from the
FC output-cap hot-loop's 1.95 V / 15 A commutation record, `docs/boost-bringup-debug.md:1572-1573`),
which gives **8.5 mV** above `v_node` at this cut. Campaign
`20260902_041414` passed only because its 2 kΩ bleed had pulled the node ~2 V off
the clamp before the window closed.

The gate uses **the firmware's own definition of a hazardous cut** rather than a
number fitted to the census: `SW_RING_LOAD_DUMP_I_A` = 0.5 A =
`SHARE_CUT_MAX_HANDOFF_A` (`teensy_controller.ino:2290`), the fw v6 share-cut load
guard — a cut of a channel carrying more than this is exactly what the firmware
refuses to perform. Every Death-5 datapoint is multi-amp and the largest legitimate
non-teardown cut in the campaign census is 0.66 A, so the class still contains every
cut the verdict was written for.

**`V_ABSMAX` is NOT relaxed, and neither is the emission gate.** An `sw_ring` event
with its `peak_v` is still emitted for every cut above 0.05 A, so the census and the
peak history are unchanged; each event now carries a `load_dump_class` boolean
saying which side of the gate it fell. Replace the fixed allowance with the hot-loop,
current-scaled bound `peak = v_node + 0.130 V/A · i_cut` (provenance above; the boost
hot-loop inductance is stamped on the RT1987 node, not the node's own characteristic
impedance). This form is verdict-invariant against the fixed and the `i·sqrt(L/C)`
node-ring forms — all three give 0 → 0 → 0 over the corpus's 1028 `sw_ring` events —
and the 0.5 A classification gate stands unchanged; re-banding `peak_v` is
**deferred to the physics review**.

### 8.6 Regen chopper

The TL431 + BSP170P clamp on the regen node is autonomous — **not** under firmware
control. The chopper sits directly on V-MOT (2026-08-30 topology fix — upstream of
the REGEN switch, matching the bench observation that the clamp held 18.1 V with
`REGEN_ENABLE` open), so it does not reach the bus through the REGEN path.

**It is a REGULATING clamp, not a bare shunt** (wording corrected 2026-09-02). The bare
`V_rgn / 47 Ω` description, and the 0.385 A it implies, describe the dump resistor alone
and are retired: the modelled clamp regulates the node and draws **0.1248 A at 18.1624 V**
at its operating point. The bare 47 Ω conduction is reached only above **18.294 V**, i.e.
on an excursion the clamp cannot hold.

**There is no bus KCL term for the clamp current, and there cannot be one at the clamp.**
`MOT_PWR` is instantiated `strict_forward`, so BUS↔MOT is stamped only when
`V_BUS − V_MOT` > `RT_V_FWD` (35 mV). Holding V-MOT at 18.1 V therefore requires
`V_BUS` > 18.135 V to source anything — above `LIMIT_V_BUS_MAX` 17.5 V, unreachable
outside an OV latch. `MOT_PWR` is measured **open throughout** the clamp; the
clamp-attributable bus sag is **below 1e-5 V**, not the 0.03–0.06 V this section carried
until 2026-09-02. That is agreement with the bench observation "`V_bus` unmoved"
(CLAUDE.md 2026-08-17b) by construction rather than by margin. §3.4 records what the
post-release bus current actually is.
The clamp level is **bench-calibrated at 18.1 V** (operator, 2026-08-27, from the
observed 13.3 → 18.1 V clamping excursion, CLAUDE.md 2026-08-17b; the earlier 16.5 V
`TODO(calibrate)` placeholder is retired).

**The reason the chopper is simulated at all is the power question:** does dissipation
in the 47 Ω dump resistor ever exceed its **20 W rating**? The bare-shunt bound at the
clamp is `18.1²/47 ≈ 6.97 W`, and the rating is only reached through excursions past
`√(20·47) ≈ 30.7 V`. ⚠️ That bound is **conservative by about 3×** for the regulating
clamp described above: at its measured operating point (0.1248 A into 18.1624 V) the
steady dissipation is ≈ 2.27 W. The engine computes `V_rgn²/47` per substep
while the chopper conducts, keeps the worst value (`chopper_peak_w`, reported in
`summary()`), and emits a `chopper_over_power` event once per excursion above
`P_CHOPPER_MAX_W` — which `run_hil_suite.py` turns into a failing check.

### 8.7 Noise injection

Applied to the **injected values**, never to the internal states.

- **ADC quantization** is real and computed from the firmware's own scale constants
  (the firmware's `SCALE_V_*` / `SCALE_I_*` constants): `V_fc` 3.01 mV/count, `V_batt` 2.11, `V_bus` 4.55,
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
>    *electrical* `FC_TAU_S = 0.020 s` double-layer lag `hil_electrical.FC_TAU_S`. They
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
a trace. The wire protocol was untouched by that round (40 B inject / 16 B observe / 22 B command); **fw v24 grew the observation frame to 17 B and fw v25 to 18 B** (error_code at offset 16) — see §5.

### 9.4 The DP-optimal EMS benchmark — `dp-replay` and its table

> ### ⚠️ A BENCHMARK, NOT A CONTROLLER
> The `dp-replay` strategy plays back a **time-indexed setpoint table** computed
> **offline**, with **full foreknowledge of the entire drive cycle and the entire
> auxiliary load**, by backward dynamic programming. It reads no feedback and reacts to
> nothing. It exists to be the **offline model-optimum reference** (a lower bound on the
> Gfc DC-gain stage cost, not on the logged `h2_cum_g`) the causal strategies are ranked
> against, and it is **meaningless against any profile other than the one it was generated
> for** — which is why it refuses to start on a fingerprint mismatch.
>
> ⚠️ And it is a **bound on the generator's model**, not on the board. The generator has
> no share loop and no governor, so it cannot represent the firmware's sub-0.55 A open-loop
> behaviour (§4.4); the measured table-versus-run gaps below are attributed to exactly that.
> Read a deviation as "the run departed from the modelled optimum", never as "the run beat
> the optimum".

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
| D4 | stage cost uses the **`Gfc` DC gain** (§9.3), imported from `hil_plant_sim.py` | puts the objective and the logged `h2_cum_g` on the **same `Gfc` map**; `DPtrial.m:43`'s static proxy disagrees by +16.4 %. ⚠️ Same map, not the same evaluation: the run integrates `Gfc`'s **dynamics** (0.2212 s, ZOH) and the DP takes its **DC gain**. Measured on this campaign's own inputs, that difference is **−0.0116 %** of the integrated total on `ems-ftp75-dp` and **−0.0316 %** on `ems-dp-replay` — two orders below the observed table-versus-run gaps below, so it does **not** explain them |
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

*The share control grid was `[0.25, 0.75]` until 2026-09-02; it is now the widened
`[0.15, 0.85]` firmware command band (n_share 57), see §9.4.3.* The grid gives the DP the
same authority the causal `soc-band` policy gives itself. Both halves matter: an
unconstrained DP sits at 0.15 and 0.85, i.e. exactly **on** the
`updateShareSetpointCutoff()` boundary where a float round-trip decides whether
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

**The measured table-versus-run gap, by era.** The qualitative "the realised run will
differ" caveat above is now quantified. Each row is the run's own `h2_cum_g` / `delta_soc`
against the table its `dp-replay` played:

| Era / campaign | Leg | h2, run vs table | ΔSoC, run vs table |
|---|---|---|---|
| `hil_report_20260901_151156` (0.65 A preload, 1:1 charger) | `ems-ftp75-dp` | **−2.15 %** | **+4.8 %** more depleted |
| `hil_report_20260902_011926` (zero preload, `ETA_CHG` 0.88, asymmetry default) | `ems-ftp75-dp` | 0.0380476458 g vs 0.0396922994 g = **−4.14 %** | −0.007940 vs −0.006636163 = **+19.6 %** more depleted |
| `hil_report_20260902_011926` | `ems-dp-replay` | **+0.33 %** | **−1.2 %** |

**Attribution: the firmware's open-loop hold, not `Gfc` dynamics.** The dynamic-versus-DC
`Gfc` difference is −0.0116 % / −0.0316 % (D4 above) and cannot produce a percent-scale
gap. The generator has no share loop and no governor, while the firmware runs **open-loop**
(HOLD or feedforward slew, §4.4) below 0.55 A — and at zero preload that covers **64.5 % of
the FTP-75 Run window**. The 61 s `ems-dp-replay` cycle, which is loaded above the gate for
most of its length, gaps by only +0.33 %. The gap grew from −2.15 % to −4.14 % across the
preload removal, which is the direction that attribution predicts.

**Regen exposure is era-dependent, and on the rig-drag legs it is exactly zero.**

⚠️ **This paragraph described the PRE-REGEN era and is now scoped to it.** Section 9.4.2
below carries the current model. Two eras have to be read apart:

- **Pre-regen era** (`eta_regen` absent, and every campaign on record). The generator's
  demand model has no regen term; the deceleration demand itself is unchanged, so what
  is omitted is only the **returned** energy. All 11 rig-drag frontier/EMS runs carry
  **0.000 J** of regen energy, because no rig-drag drive cycle in this suite ever
  commands a negative motor current, so on those legs the omission is exact rather than
  merely small.
- **Regen era** (`eta_regen` set, which the `ems-ftp75c-*` family is the first family to
  use). `build_demand()` carries the braking credit, so the bound earns what the run
  earns and the omission is not the boundary any more. The residual there is the Ag105
  settle and ramp, disclosed in 9.4.2.

Regen-bearing scenarios outside those two cases are `frontier_eligible: False` by role,
and the residual optimism there is bounded at **≤ 0.9 % of `h2`** (measured on
`charge-regen`). A run whose `∫min(p_mot, 0) dt` is negative is labelled
**regen-bearing** in the matched-DP block so the boundary travels with the number.

#### 9.4.1 The demand model, and the static-loss map (2026-09-02)

**The bound is only as good as its demand model, and that model was wrong in two ways.**
The DP did not bill the node bleed the sources carry on `N_BUS` and `N_MOT`, and it solved
the `--droop measured` bus law (15.95 − 0.074 I) while every campaign runs `--droop design`
(realized 15.8652 − 0.3015 I). The two errors carry opposite signs and partially cancelled,
so the 61 s leg read −0.198 % and looked healthy with both present. The full decomposition,
the probe that fitted the correction and the fit residuals are
`docs/modeling/dp_loss_map_20260902.md`; this section states only what the map is and
what it corrects.

The map replaces the single-term bus law with a five-constant static model of the boost pair
plus the node bleed, iterated to a fixed point inside `gen_dp_ems_table.build_demand()`. Its
constants live in `tools/hil_plant_sim.py` under the block titled "THE DP DEMAND MODEL'S
STATIC-LOSS MAP". It is applied only for the configuration it was fitted at, resolved by
`hil_plant_sim.loss_map_for_config()`: hi-fi engine, `--droop design`, `--asymmetry
measured`. Any other configuration, `--electrical simple` included, resolves to `None`.

**The map does not depend on the control.** `p_dem` must be control-independent or the DP's
stage cost is not separable. The map depends on the codes only through the parallel droop
code `g_par`, which the firmware holds constant while it trades the split, measured to
better than 1e-04 over four scenarios and half a million rows
(`dp_loss_map_20260902.md` §4). A tripwire test pins that constancy.

Table 9.4.1 gives the re-priced table-versus-run deviations. The board side is campaign
`20260902_041414` with the bleed energy the new per-node conductances no longer burn removed
and share-weighted onto the two sources (§4.8); the DP side is the demand rebuilt with the
map.

| Leg | Configuration | E_dem (J) | h2_dp (g) | h2_run (g) | Deviation |
|---|---|---|---|---|---|
| `ems-ftp75-dp` | today (no map, 2 kΩ bleed) | 2707.43 | 0.0364618 | 0.0380466 | +4.3463 % |
| `ems-ftp75-dp` | no map, new bleed | 2707.43 | 0.0370397 | 0.0369286 | −0.2999 % |
| `ems-ftp75-dp` | **shipped map, new bleed** | 2701.55 | 0.0369177 | 0.0369286 | **+0.0294 %** |
| `ems-dp-replay` | today (no map, 2 kΩ bleed) | 804.61 | 0.0118184 | 0.0117951 | −0.1979 % |
| `ems-dp-replay` | no map, new bleed | 804.61 | 0.0119031 | 0.0115904 | −2.6273 % |
| `ems-dp-replay` | **shipped map, new bleed** | 791.24 | 0.0116256 | 0.0115904 | **−0.3031 %** |

Table 9.4.1 shows both legs landing inside ±0.31 % with the map applied, against +4.35 % and
−0.20 % before. However, the middle row of each pair is the reason the two defects are fixed
together: the bleed change alone moves the 61 s cycle from −0.198 % to −2.627 %, because it
removes the cancellation without correcting the droop-mode term.

✅ **FIRST BLEED-ERA READING OF THE BOUND, and its SIGN (campaign
`hil_report_20260902_220604`).** The `dp-replay` legs now sit slightly **BELOW**
their matched bound: `ems-dp-replay` **−0.18 %**, `ems-sdp` **−0.09 %**,
`ems-mpc-cross` **−0.80 %**. A causal run below its own non-causal bound is not a
result and not a defect — it is the DOCUMENTED STAGE-COST BIAS, quoted with its
sign for the first time. The two hydrogen totals are computed by different halves
of one model: the run's `h2_cum_g` is the **dynamic Gfc integrator**
(`H2Consumption`, a ZOH discretization of the transfer function) while the DP's
stage cost is the **Gfc DC gain** times stage energy. The two agree at steady
state and differ through every transient, always in one direction for a given
transient shape. **A deviation of a few tenths of a percent, of EITHER sign, is
inside this bias and is not a policy result.** The standing text is
`hil_report_analysis.MATCHED_DP_GFC_NOTE`; the magnitude to carry is
**|deviation| ≤ ~0.8 %** on the legs measured so far, and a bound-crossing inside
it must not be read as a controller beating the optimum.

⚠️ **THE DRAIN-SCENARIO LIST WENT STALE TWICE, and the second instance was found
in this campaign's matched-DP pass (2026-09-03).** `gen_dp_ems_table.py` carried
its own transcription of the scenario names whose auxiliary load is the bespoke
1.0 A SoC-band drain rather than the generic `aux_preload_a` term. It omitted
`ems-sdp` in 2026-09-01 (defect B2) and it omitted the three `ems-sdp-alpha-*`
sweep legs until now. The consequence is the same both times and is large:
`ems-sdp-alpha-cal` has a delta-SoC IDENTICAL to `ems-sdp` and a run hydrogen
within 24 ppm of it, yet its solved bound came out at **0.0034595 g** against
`ems-sdp`'s **0.0124009 g** — a **+258 %** apparent deviation that is the missing
drain and nothing else (`alpha-charge` +170 %, `alpha-greedy` +268 % with
`lambda_term` pinned at 1.000000 and NOT converged, because no lambda can match a
terminal SoC the demand cannot reach). 0.0034 g is the same figure the B2 note
records for `ems-sdp`. The list is now **derived from
`hil_plant_sim.SOC_BAND_DRAIN_SCENARIO_NAMES`** in both offline mirrors
(`gen_dp_ems_table.py` and `ems_walk.py`), since `apply_scenario()` is what
actually applies the drain and any copy that can disagree with it is a defect
waiting for a third instance. Membership is unchanged for every previously-listed
scenario, so the four committed tables are unaffected.
⚠️ **THE FINGERPRINT DOES NOT COVER THIS.** `dp_profile_fingerprint()` hashes the
drain CONSTANTS but not whether a scenario is inside the drain branch, so a stale
mirror produces a wrong record under a correct key and no lookup can detect it.
The three affected records were therefore DELETED rather than invalidated, then
RE-SOLVED against the corrected derivation: `7d8f75b3…` (alpha-cal),
`92fdcbbc…` (alpha-charge) and `af588d59…` (alpha-greedy) all carry
`created_utc` 2026-09-03T09:10–09:11Z, all three converged, and `alpha-cal`'s
`h2_g` is **0.012400850710342052**, bit-identical to `ems-sdp`'s own record
(`6bc5a65c…`) as the identical drain and terminal SoC require. The store
therefore holds **71 records**, not 68; a reading of "71 → 68" describes the
window between the deletion and the re-solve and is not the shipped state.

⚠️ **A matched-DP baseline now carries a demand-model era.** `loss_map` joins the DP
fingerprint keys and `dp_results_db.KEY_FIELDS` as an **optional** key, so an absent
`loss_map` names the pre-2026-09-02 model and every stored record keeps its meaning and its
key. A baseline solved in one era is not comparable with one solved in the other.
`hil_report_analysis.matched_dp_for_run()` resolves the era from the run's own
`config.electrical` / `config.droop_mode` / `config.asymmetry`, exactly as it resolves
`accounting` and `eta_chg`, and names the demand era in every run's `notes`.

#### 9.4.2 The regen credit in the demand model (2026-09-02)

**Until this round the offline demand model had no regen term at all.** `build_demand()`
computed `p_mech = max(0.0, force * v)` and stopped there, so a braking stage cost nothing and
returned nothing. The traction half of that was never wrong, since the 2026-09-02 correction at the
site records that the DP deceleration demand was not overstated. However, the credit was missing,
and a bound that omits energy the run gets back must buy that energy with hydrogen.

**One chain, four consumers.** `tools/regen_power.py` is stdlib-only, on
`tools/charger_power.py`'s constraint, and holds the chain the plant, the DP generator, the
offline walk and the MPC all price braking with: `resolve_eta_regen()`, `check_eta_regen()`,
`clip_regen_force_n()`, `regen_shaft_power_w()`, `regen_node_power_w()`,
`regen_pack_current_a()`, `regen_pack_current_from_force_a()` and `era_label()`. The chain, in
the order the energy flows, is

```
    f_regen = max(force, -K_F * VESC_REGEN_I_MAX_A)          the clip, as a FORCE
    p_brake = max(0.0, -(f_regen * v))                       shaft power available
    p_regen = ETA_REGEN * p_brake                            electrical, at V-MOT
    i_pack  = min(ETA_CHG * p_regen / V_pack, ag105_i_max)   output-referred, un-netted
```

The clip is applied before the force becomes motion, so braking force and electrical return
come from one number, exactly as `Plant.step()` does it. The last line is deliberately **not
netted** against the braking chopper, on §4.6.2's measured ruling: the clamp is a residual
absorber and not a prior claimant.

**The credit is a pack CURRENT and not a negative `p_dem`,** and the choice is not
presentational. Four properties of the existing code depend on it.

- Nothing flows back to the bus. `MOT_PWR` is instantiated strict-forward, and §4.6.2 records
  the bus contribution as structurally zero while the chopper clamps. A negative `p_dem` would
  credit the bus for energy that never reaches it.
- `solve_dp()`'s split-control feasibility test, `(p_fc / V) <= LIMIT_I_FC_MAX_A`, and its
  stage cost both assume `p_dem >= 0`. A negative `p_dem` would bill negative hydrogen.
- `charge_mask()`'s budget test, `(p_dem / v_bus + i_chg_bus) <= margin * LIMIT_I_FC_MAX_A`,
  would become trivially true on braking stages and would admit FC charge windows the firmware
  never opens there.
- The MPC's violation tables bound `d * i_tot` and `(1 - d) * i_tot` one-sidedly and would not
  catch a regen current limit.

**Where it enters, and the property that keeps the DP tractable.** `build_demand()` now returns
a seven-tuple `(v, a, p_dem, v_bus, i_total, cruise, i_regen)` and takes `drag_mode`,
`eta_regen`, `eta_chg`, `v_pack_ref` and `regen_i_max_a`. `i_regen[k]` is a **per-stage,
share-independent** pack current, added to the SoC transition of both the split column and the
charge column and mirrored term for term in `step_discharge()` and `step_charge()`. Because it
does not depend on the control index, the stage cost stays separable and the DP stays tractable
at the same complexity, and SoC gains during braking stages independently of the share decision.
`reachable_soc_window()` carries the credit on both extreme-policy walks, because regeneration
raises the upper bound reachable from any state and a transition off the grid is infeasible
rather than clamped.

**Exclusivity, and its hardware origin.** A stage cannot both FC-charge and regen-charge, so
`charge_mask()` gains one term, `i_regen <= 0.0`. This is the host-side image of
`assertFcChargeEnable()`, which drives `BT_BUS_ENABLE` low, then `REGEN_ENABLE` low, then waits
100 µs before raising `FC_CHARGE_ENABLE`, with `detectFaults()` latching
`FAULT_SWITCH_CONFLICT` if the illegal combination is ever observed. The `cruise` term already
excludes most braking stages but not all, since a shallow deceleration inside the cruise-slope
tolerance can be regen-capable under the compensated drag; the explicit term makes the
exclusion exact rather than incidental. It also keeps the mask **state-independent**, which is
the property that makes the stage cost separable.

Table 9.4.2 gives the demand the round produces on `ems-ftp75c-dp`, that is `ftp75c` under
`scaled-air`, over its 1800 stages.

| Quantity | Value |
|---|---|
| Peak `p_dem` | 5.221 W (0.331 A of bus current) |
| Mean `p_dem` | 3.011 W |
| Charge-admissible stages | 609 of 1800 |
| Stages carrying a regen credit | 329 of 1800 |
| Peak `i_regen` | 0.1441 A |
| Total credit over the cycle | 1.1729 C |

Table 9.4.2 shows the credit reaching 329 of the cycle's 1800 stages, at a peak of about
44 % of the peak bus current the same cycle demands. The two masks are disjoint by
construction rather than by measurement, because `charge_mask()` ANDs the exclusivity term in.

**The pre-committed contract is discharged era-conditionally.** `gen_dp_ems_table.py` recorded
in advance that `ETA_REGEN` and `VESC_REGEN_I_MAX_A` were absent from the table header and the
drift guard *because* the demand model had no regen term, and that a generator gaining one must
move both into the header and the guard. The generator now takes `--drag` and `--eta-regen` and
emits `# drag:`, `# drag_k_air:`, `# eta_regen:` and `# vesc_regen_i_max_a:` **only in the new
eras**, so a pre-regen table's header is byte-identical and its drift guard checks exactly what
it checked before.

⚠️ **An absent `eta_regen` key means the pre-regen era,** on `charger_power.eta_chg`'s
convention verbatim, and `resolve_eta_regen()` maps the absence onto `None`. A consumer must
resolve the era through that function rather than defaulting an efficiency, or a table solved
for an archived run will price a credit that run never earned. The era is **not** the drag
profile: `eta_regen` and `drag` are two independent optional keys, and both join
`dp_results_db.KEY_FIELDS` and `OPTIONAL_KEY_FIELDS` on `loss_map`'s terms, so all 16 stored
records keep their meaning and their key.

---

### 9.4.3 The share-control band: widened to the firmware command band (2026-09-02)

The DP's share grid and the MPC's ladder both spanned [0.25, 0.75], and both now span the
full firmware command band [0.15, 0.85]. This subsection records the change, its measured
consequences and its reversal path.

**The standing rule.** Every EMS strategy has access to the full [0.15, 0.85] range, and
the benchmarks are strategies for this purpose (operator ruling, 2026-09-02). The band is
taken from `governor_model.GOV_CONST["DROOP_R_MIN"/"DROOP_R_MAX"]` and never re-typed.

**Why the old margin was not needed.** The old grid stopped 0.10 short of both rails so
that `updateShareSetpointCutoff()` could never latch. Three facts retire that margin.
The cut compares **strictly** (`.ino:9231-9257`), so 0.15 and 0.85 are themselves IN
band. The firmware carries `SHARE_CUTOFF_HYST` = 0.01 **beyond** the band on top of that.
And `sdp-v4` has railed at 0.8500 on 100 % of ticks across campaigns `20260902_011926`
and `20260902_041414` with zero hazard cuts. The grid edges are the same floats
`SdpStrategy.clamp_share()` emits, and they round-trip through the 22-byte command
packet to the same float32.

**What it fixes.** The old grid was NARROWER than the policies it bounded, because
`SdpStrategy.clamp_share()` clamps to the band. On every `ems-*-sdp` leg the DP was
solving over a control set that did not contain the policy's operating point, and the
causal run beat its own lower bound. That is a benchmark the referent beats, which ranks
nothing.

**Resolution is held, not the point count.** The DP goes 41 points over 0.50 to 57 over
0.70, both at 0.0125 spacing. The MPC goes 7 points to 9, spacing 0.0833 to 0.0875, a
5 % coarsening against 20 % at 8 points and 40 % at 7. Holding the count instead would
have made the widening a change of resolution as well as of reach and confounded every
before/after comparison. Cost: about 2x the DP solve, and 2187 MPC candidates against
1029, measured at 0 % budget expiry over 183 decisions x 3 repeats on a loaded host.

**Era handling.** `n_share` and `share_span` are already key fields of
`dp_results_db.KEY_FIELDS`, are already written into every table header and are already
checked by `DpReplayStrategy.bind_scenario()`'s drift guard. A table or a stored record
solved on the old grid therefore keys and binds as its own era rather than colliding with
a new one. Nothing is orphaned; old artifacts simply stop matching a live scenario, which
is the correct outcome for a benchmark solved over a control set the firmware does not
bound the strategies to.

⚠️ **Single-source commands (share 0 and 1) are NOT in either control set.** They are
issued through the setpoint latch rather than through the share loop and are subject to
the fw v25 share-cut load guard, so they need their own control column with its own
feasibility test. Queued as a separate round.

**REVERSAL PATH.** Seven items.

1. `tools/gen_dp_ems_table.py`: `DP_SHARE_MIN`/`DP_SHARE_MAX` back to
   `SOC_BAND_SHARE_NOMINAL -/+ SOC_BAND_SHARE_SPAN`, `DP_N_SHARE` back to 41,
   `DP_CHARGE_SHARE` follows `DP_SHARE_MAX` automatically, and the
   `prepare_problem()` band guard back to a strict comparison.
2. `tools/mpc_ems.py`: `SHARE_BAND_DP` back to the literal `(0.25, 0.75)`,
   `SHARE_BAND_SDP` back to `(0.15, 0.85)`, `SHARE_LEVELS` back to 7.
3. `tools/hil_plant_sim.py`: `MPC_CAMPAIGN_MAX_CANDIDATES` back to 1029.
4. Regenerate every committed table under `tools/dp_tables/`, and re-prefill every
   `tools/dp_db/` record solved on the wide grid. Both are era-keyed, so the old
   artifacts remain valid and reachable throughout.
5. `tools/run_hil_suite.py`: the five `walk_h2` pins on the MPC legs, the
   `ems-mpc-cross` share-range note, the `ems-ftp75c-mpc` constant-share note, and
   every frontier `provisional_note` that quotes a re-derived ratio.
6. The tests that encode the band: `test_no_candidate_leaves_the_share_band`,
   `test_delivery_table_applies_the_minority_clip`,
   `test_index_five_is_reachable_from_a_coarsened_decision`,
   `test_the_terminal_price_moves_the_first_move` (its explicit budget),
   `test_the_committed_plan_is_insensitive_to_the_projection` (its 0.675 pin), and the
   old-grid restoration inside
   `test_old_era_regeneration_reproduces_the_pre_change_table_byte_for_byte`.
7. The standing rule in `docs/HIL_SCENARIOS.md` §6.0 and the share-band era note in
   `.claude/skills/hil-agent-analysis/references/hil-conventions.md`.

**Single-source topology, and what the plant already models.** The MPC is to gain 0 and 1
single-source commands as candidates (operator ruling, 2026-09-02; the DP and the SDP are
not). Two plant-side facts bear on that and are recorded here because they are properties
of the plant rather than of the planner.

The **bus law changes with the topology.** The loss map's `g_par` is the parallel droop
code `g_fc*g_bt/(g_fc+g_bt)`, which does not exist with one channel off the bus. Probing
the hi-fi engine at `--droop design --asymmetry measured` over three droop codes gives a
slope ratio of 1.9453 for FC-only and 2.0579 for BT-only against the two-source law, each
stable to 0.03 % across a factor-of-two code range, with no-load intercepts of 15.87821 V
and 15.86468 V. `hil_plant_sim.single_source_bus_law()` is the implementation and
`docs/modeling/dp_loss_map_20260902.md` carries the measurement. The four constants sit
outside the loss map deliberately: the map is a fingerprinted era key, and adding fields
would orphan every committed DP table and every stored `dp_db` record.

**The separability claim is band-interior, not band-uniform.** `tools/hil_plant_sim.py`'s
loss-map separability banner states a "±0.9 % share dependence"; that figure is measured
near mid-band. Against the fitted governor asymmetry law (§4.4a), the true effective
parallel resistance `K_eff` deviates **+4.16 % at r = 0.15** and **−0.47 % at r = 0.68**
from `0.308502 Ω`, and the deviation is non-monotone across the band. The consequent h2
bias stays inside the ±0.8 % DP-vs-run tolerance (§9.4) — ≤ 0.05 % on `ems-sdp`, ≤ 0.2 % on
a rail-pinned leg — but a reader quoting "±0.9 %" as a control-independence bound anywhere
in the band should read the rail figure instead.

The **cut and its restore are already ported.** `governor_model._setpoint_cutoff()`
carries the firmware's own sequence in both directions: the last-source guard, the load
guard (`abs(i) <= SHARE_CUT_MAX_HANDOFF_A` 0.5 A, with refusals counted), survivor
turn-on blanking over `SHARE_CUT_SURVIVOR_BLANK_MS` 30 ms, the S1 ownership self-heal, and
the release path with its charged-bus guard and its
`DROOP_RATIO_SLEW_HANDOFF_PER_TICK` 0.002/tick restore slew. No porting is required before
the candidates are added.

⚠️ **SUPERSEDED 2026-09-03. One registered scenario now commands 0 or 1.** The statement
that stood here — "no run commands 0 or 1 today; a trace showing a commanded share outside
[0.15, 0.85] is a defect" — held only until the enumeration shipped on the operator's
**rollout-time test** ruling (`docs/modeling/mpc_design_20260901.md`, section 2026-09-03).

The reading rule is now per leg:

* **`ems-mpc-single`** arms `mpc_single_source` and may command exactly **0.0** or exactly
  **1.0**. Those two values are LEGAL there — the firmware constrains a received setpoint
  to `[0, 1]` (.ino:5663) and `updateShareSetpointCutoff()` reads an out-of-band value as a
  topology instruction — and the suite's two band checks exempt them and report the exempt
  sample count. A share outside `[0.15, 0.85]` that is **not** one of those two values is
  still a defect there.
* **Every other leg** keeps the old rule verbatim: any commanded share outside
  `[0.15, 0.85]` is a defect.

**Plant-side consequence:** a latched stage must be priced on the single-source bus law
above, not on the two-source one — at the 61 s cycle's peak that is worth about 0.45 V of
bus. The live plant does this by construction (it solves the network from `switch_state`).
The offline walk does **not** by default: `ems_walk.walk(single_source_demand=True)` is the
opt-in that switches its demand arrays on every latched stage, and it is off by default so
the `ems-y-b00-*` anchors — which have always commanded 1.00 and 0.00 through that walk on
the two-source law — do not move.

**Unmodelled cut deferral (campaign F, 2026-09-03).** `ems-mpc-single` on the board defers a
loaded single-source cut for 24–45 ms past the commanded switch, firing only once the doomed
channel's own current has fallen to 0.44–0.50 A under the firmware's load guard
(`SHARE_CUT_MAX_HANDOFF_A`). Neither the offline walk nor the MPC surrogate models this
deferral; pricing the stage-cost transition immediately, as they do, produced a +0.18 %
eq-H2 error against the board on the identical stimulus (walk −0.04 %) — a wash, not a win,
and it is disclosed wherever the `ems-mpc-single` gain is quoted (§11).

---


## 10. `PiCommander` — driving the firmware from the scenario

Several of the new scenarios need the board to be *commanded*, not just fed sensors:
`charge_goal` reaches the firmware only through the Pi's 22-byte command packet, and the
firmware's charging path had **no scenario coverage at all** before this.

`PiCommander` plays a scenario's `pi_timeline` onto the **same socket and destination**
as the injection frames — the firmware's `receiveCommands()` drains both frame types and
dispatches by length (fw v21 bounded drain).

Packet layout, **verified from `teensy_controller/teensy_controller.ino`
`processPiCommandPacket()`** and the `SYNC_BYTE_RX` constant, and **pinned by
`test/test_main.cpp`'s `test_command_parsing`** — nothing guessed, and the firmware body is
byte-frozen because the Pi bridge parses fixed offsets. (⚠️ The line numbers this table
carried until 2026-09-02 were stale by roughly 600 lines and pointed into the main loop;
provenance is symbol- and test-based from here on, because a line number ages silently
while a fixed-offset consumer diverges in the same silence.)

| Offset | Type | Field |
|---|---|---|
| 0 | u8 | sync `0xBB` (`SYNC_BYTE_RX`) |
| 1 | u32 | timestamp |
| 5 | u16 | `pkt_counter_Pi` |
| 7 | f32 | `v_setpoint` (constrained ±20 m/s) |
| 11 | f32 | `power_share_setpoint` (constrained [0,1]) |
| 15 | f32 | `charge_goal` |
| 19 | u8 | `mode_cmd` — 0 HYBRID, 1 FC_ONLY, 2 BATT, 3 CHARGE, 4 SAFE |
| 20 | u8 | `droop_enable` — **reserved**, parsed and discarded |
| 21 | u8 | XOR over bytes 1..20 |

A timeline is `[(t_seconds, {field: value}), …]`; unspecified fields **hold** their
previous value, matching the firmware, which also holds a field it rejects. The commander
transmits at **50 Hz** and keeps sending the held state between entries, because a
command packet is what marks the Pi link alive (`last_rx_ms`, stamped in `processPiCommandPacket()`).

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
it), charger *energy* behaviour beyond the coulomb count (no **MPPT tracking loop** — only
the input-voltage threshold is modelled, §4.6), encoder/estimator behaviour, or anything
the board's analog front end does beyond the quantization of §8.7. Nor is it trustworthy
for the **exact trajectory of a transient realization** — a load-rise rate or a
delivered-share trajectory during a fast transient — because the share loop's re-split
is algebraic (zero-lag), the plant's own zero-lag limit: a real converter with τ_r
7–300 µs delivers at or below the plant's peak. The fw v26 clamp figures at §4.4a
(:1055-1072) are conditioned on this realization, and the board's peak on the campaign-E
stimulus brackets [≈ 1.49, ≤ 1.68] A; the `OC_FC` outcome itself is plant-invariant,
because a single raw sample above 1.40 A latches regardless of the bracket.

⚠️ **On the CV branch specifically** (wording corrected 2026-09-02; this list previously
read "no CV taper", which contradicts the implementation). The model **does** produce a
CV/Fully-Charged branch: at `soc >= 0.995` it sets `AG105_ST_FULL | AG105_FLAG_CV` in the
injected status byte and decays `i_charge` on `AG105_TAU_S`. That is a **synthetic status
and taper stimulus**, not simulated Ag105 constant-voltage regulation — Ag105 Table 6
defines the status fields but justifies neither the 0.995 threshold nor the taper law, and
`AG105_TAU_S` (0.4 s) is simulator-local and `TODO(verify)` (see its caveat in §4.6). What
`charge-to-full` therefore validates is the **firmware's handling of an injected FULL/CV
status** — that it takes no wrong action on it — and nothing about the charger's own CV
physics.

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
| **A physical Ag105 CV loop and MPPT tracking** | ⚠️ Corrected 2026-09-02 — this row used to say a stateful SoC model "would let `AG105_ST_FULL` and a genuine CV taper appear". SoC **is** modelled (§4.2) and the FULL/CV branch **is** reached (`soc >= 0.995`, `charge-to-full`), so what remains open is different: the branch is a **synthetic** status + `AG105_TAU_S` taper rather than a regulated constant-voltage loop, and the MPPT **tracking** dynamics above the threshold are still unmodelled (§4.6). Closing either needs a bench charge cycle, not a simulator state. |
| **Bench-measured transient realization** | Place the board inside the [≈ 1.49, ≤ 1.68] A bracket noted in §11.1 (:1055-1072): a τ_r step test on one boost channel (measured turn-on/turn-off current slew, against the plant's assumed 7–300 µs), and a `W 4.0 0.15` (State-98) joint current-and-share-step run reproducing the `fw26-clamp-sweep` stimulus on hardware without the HIL plant's algebraic re-split. |

