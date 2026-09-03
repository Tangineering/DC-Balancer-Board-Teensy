# Compressed FTP-75 (`ftp75c`) and the road-load drag profile: design note

Status: DESIGN ONLY. No tool, firmware, or scenario file is modified by this note.
Date: 2026-09-02. Author: stage-1 design pass, from the operator ruling of the same date.

This note designs a second drive-cycle stimulus for the HIL rig, `ftp75c`, and the plant
configuration it requires. The existing `ftp75` cycle and the measured rig drag profile are
unchanged. The published scaling study
(`references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf`) deliberately
did not time-scale its cycle; `ftp75c` is a separate stimulus and does not amend that study.

The problem `ftp75c` solves is that the rig, as instrumented, regenerates nothing. Section 1
quantifies this. Sections 2 to 7 design the cycle, the drag profile, the regen command path, the
regen term in the dynamic-programming demand model, the campaign expectations, and the bench
replication requirement.

---

## 0. Notation and constants

Table 1 lists every constant this note uses, with its source.

| Symbol | Value | Source |
|---|---|---|
| `M_EFF` | 3.5 kg | `tools/hil_plant_sim.py:301` |
| `F_COULOMB` | 2.00 N | `tools/hil_plant_sim.py:303` |
| `B_EFF` | 0.534 N s/m | `tools/hil_plant_sim.py:304` |
| `K_F` | 0.7538 N/A | `tools/hil_plant_sim.py:302` |
| `V_STICTION` | 0.02 m/s | `tools/hil_plant_sim.py:305` |
| `VESC_REGEN_I_MAX_A` | 1.5 A | `tools/hil_plant_sim.py:330`, `TODO(verify)` |
| `ETA_REGEN` | 0.80 | `tools/hil_plant_sim.py:336`, `TODO(verify)` |
| `ETA_CHG` | 0.88 | `tools/hil_electrical.py:463` |
| `AG105_I_MAX` | 2.5 A | `tools/hil_plant_sim.py:230` |
| `AG105_SETTLE_S` | 0.5 s | `tools/hil_plant_sim.py:231` |
| `AG105_TAU_S` | 0.4 s | `tools/hil_plant_sim.py:232`, `TODO(verify)` |
| `V_CHOPPER_TRIP` | 18.1 V | `tools/hil_electrical.py:474` |
| `ETA_BOOST` | 0.85 | `tools/hil_plant_sim.py:406` |
| `I_AUX_A` | 0.15 A | `tools/hil_plant_sim.py:407` |
| `BATT_CAPACITY_AH` | 5.0 Ah | `tools/hil_electrical.py:860`, `TODO(verify)` |
| `LIMIT_I_FC_MAX` | 1.4 A | firmware limit, quoted at `tools/hil_plant_sim.py:3080` |
| `SDP_CHG_MIN_DWELL_S` | 8.0 s | `tools/hil_plant_sim.py:4391` |
| Paper vehicle mass | 2242 kg | scaling paper |
| Air density `rho` | 1.225 kg/m^3 | standard sea-level value |
| `Cd` | 0.33 | NEXO-class assumption, `TODO(verify: operator)` |
| `A_f` | 2.5 m^2 | NEXO-class assumption, `TODO(verify: operator)` |

The drag coefficient and frontal area are not present in the extracted text of the scaling paper.
Both are assumptions and are marked `TODO(verify: operator)` wherever they propagate.

All energy figures in this note come from a 1 kHz inverse-dynamics evaluation of the piecewise
linear speed table, using the plant force law of `Plant.step()` without the stiction deadband.
This is the same reduction `gen_dp_ems_table.build_demand()` makes, and its docstring states the
justification: the profile never dwells inside `V_STICTION` while commanding force.

---

## 1. Why the rig regenerates nothing

The rig road load is `F_road(v) = F_COULOMB * sgn(v) + B_EFF * v`. At any speed above the
stiction band this drag exceeds 2.00 N. The motor force required to follow a deceleration `a` is
`F_m = M_EFF * a + F_road(v)`, so regeneration requires `M_EFF * |a| > F_road(v)`, that is
`|a| > 0.571 + 0.153 * v` m/s^2.

Table 2 gives the resulting regen share of braking kinetic energy on the existing cycle and on
three candidate configurations. Braking kinetic energy is `-M_EFF * integral(v * a) dt` over
decelerating samples; shaft regen energy is `-integral(F_m * v) dt` over samples where `F_m < 0`.

| Configuration | Peak decel (m/s^2) | Braking KE (J) | Shaft regen (J) | Regen share |
|---|---|---|---|---|
| `ftp75`, rig drag | 0.1746 | 30.819 | 0.000 | 0.00 % |
| `ftp75c` (factor 0.5), rig drag | 0.3492 | 30.817 | 0.000 | 0.00 % |
| `ftp75c`, drag-free | 0.3492 | 30.817 | 30.817 | 100.00 % |
| `ftp75c`, scaled air drag | 0.3492 | 30.817 | 15.793 | 51.25 % |

The compressed cycle peak deceleration, 0.3492 m/s^2, is still well below the 0.571 m/s^2 floor
at standstill. Time compression alone therefore does not produce regeneration on this rig. This
confirms the orchestrator arithmetic quoted in the ruling. Road-load compensation is required, and
it is the compensation, not the compression, that creates the regenerative braking energy.

The compression is nonetheless necessary. Section 3.4 shows that it is what brings the required
regen current into the same decade as the VESC clip, and Section 2.4 shows that it partially
corrects the rig inertia deficit.

---

## 2. The cycle

### 2.1 Construction

`ftp75c` is the same EPA source segment as `ftp75`, with the time axis multiplied by 0.5 before
the profile offset is applied. The velocity axis is untouched. In terms of the existing generator
(`tools/gen_ftp75_profile.py`), the only change is one line:

```
full = [(float(t) * TIME_FACTOR + PROFILE_START_S, float(mph) * SCALE_MPH_TO_MPS)
        for (t, mph) in segment]
```

with `TIME_FACTOR = 1.0` reproducing `tools/ftp75_profile.py` byte for byte and
`TIME_FACTOR = 0.5` emitting `tools/ftp75c_profile.py`. The raw file, its sha256 gate
(`9791a45a7fb2415de0bf01948b96e8aeff499bfd63744a8c6ca781ae88826f8a`), the segment slice
`0 <= t <= 340`, the end-at-rest assertion, and the mph-to-m/s constant `3.0 / 56.7` are all
carried over unchanged.

### 2.2 Decimation and point count

The collinear decimation of `decimate_collinear()` tests a ratio of time differences. That test
is invariant under a uniform scaling of the time axis, so the compressed table keeps exactly the
same points as the uncompressed one. This was verified rather than assumed: the generator run at
`TIME_FACTOR = 0.5` reduces 341 raw samples to **234 points**, with a worst reconstruction error
against every original sample of **4.44e-16 m/s**, both identical to `ftp75`. A point-count
divergence between the two tables would indicate a defect in the time-scaling change and should be
asserted at generation time.

### 2.3 Emitted constants

Table 3 gives the emitted profile constants and the derived scenario timings, alongside the
existing cycle for comparison.

| Constant | `ftp75` | `ftp75c` |
|---|---|---|
| `*_T_START` | 5.0 s | 5.0 s |
| `*_T_END` | 345.0 s | 175.0 s |
| Table duration | 340.0 s | 170.0 s |
| `*_PEAK_MPS` | 3.0 | 3.0 |
| `*_PEAK_T` | 245.0 s | 125.0 s |
| `*_POINTS` | 234 | 234 |
| Peak acceleration | +0.1746 m/s^2 | +0.3492 m/s^2 |
| Peak deceleration | -0.1746 m/s^2 | -0.3492 m/s^2 |
| `*_RUN_EXIT_S` | 346.0 s | 176.0 s |
| `*_DURATION_S` | 350.0 s | 180.0 s |

The run-exit and duration follow the existing derivation at `tools/hil_plant_sim.py:7629-7630`:
`RUN_EXIT = T_END + 1.0` and `DURATION = RUN_EXIT + 4.0`. The one-second margin rather than the
usual three seconds remains justified, because the compressed table also ends inside a native
idle: raw `t = 333` onward is 0 mph, which compresses to a 3.5 s idle tail.

The ruling anticipated a duration near 172 s. The exact figure is 170.0 s, because the source
segment is exactly 340 s and the factor is exactly 0.5.

### 2.4 What the compression does and does not claim

The scaling paper defines a length scale for the velocity axis, a mass scale `S_m = S_L^2`, and a
drag scale `S_Fd = S_L^3`. With `S_L = 3.0 / 25.3472 = 0.118356`, the similar mass is
`2242 * S_L^2 = 31.41 kg`, whereas the rig effective mass is 3.5 kg. The rig is therefore
**8.97 times lighter than dynamic similarity requires**. Under an unscaled time axis this deficit
makes drag 8.97 times more influential on the rig than on the vehicle. Halving the time axis
doubles every acceleration and therefore doubles the inertial force at a given speed, which halves
that factor. The residual is:

```
(drag / inertia)_rig / (drag / inertia)_vehicle = S_L^2 * 2242 * TIME_FACTOR / M_EFF = 4.487
```

The compressed rig is therefore still 4.49 times more drag-dominated than the vehicle it stands
for. `ftp75c` makes no dynamic-similarity claim. It is a stimulus chosen so that the regenerative
braking mechanism is exercised at currents the hardware can produce, and Section 3.5 records what
that residual costs in regen share.

### 2.5 Names and registration

The profile module is `tools/ftp75c_profile.py`, generated by `tools/gen_ftp75_profile.py` under a
new `--time-factor` flag with a matching `--out` default. The five scenarios are
`ems-ftp75c-5050`, `ems-ftp75c-socband`, `ems-ftp75c-sdp`, `ems-ftp75c-dp` and `ems-ftp75c-mpc`,
mirroring the five `ems-ftp75-*` entries. Gating is a new frozen set `FTP75C_SCENARIOS` and a new
flag `--with-ftp75c`, following `FTP75_SCENARIOS` (`tools/run_hil_suite.py:393-395`) and its gate
(`tools/run_hil_suite.py:5918-5946`) exactly. The set form, not a name prefix, is required for the
reason recorded at `tools/run_hil_suite.py:380-392`.

Note that the existing `--with-ftp75` help text at `tools/run_hil_suite.py:10014-10020` already
understates its own set as "the pair" at "~11.7 min". It should be corrected in the same change.

### 2.6 Frontier tuple

A compressed profile is a different `ems_v_profile` and a different `duration_s`, so it fails the
stimulus-coherence precondition `EMS_FRONTIER_STIMULUS_KEYS` (`tools/run_hil_suite.py:8720`)
against the `ftp75` legs. `ftp75c` therefore needs its own three-leg tuple and must not be slotted
into the existing `ftp75` entry. The roles mirror `EMS_FRONTIER_FTP75`:

```
{"reference": "ems-ftp75c-socband",
 "candidate": "ems-ftp75c-sdp",
 "bound":     "ems-ftp75c-dp"}
```

The thresholds should start as the `ftp75` tuple thresholds, `vs_reference_max` 1.02 and
`vs_bound_max` 1.06, with a `provisional_note` recording that no campaign has evaluated the tuple.
A second tuple `ftp75c-mpc` substitutes `ems-ftp75c-mpc` as candidate, mirroring `ftp75-mpc`
(`tools/run_hil_suite.py:8667-8692`).

---

## 3. The plant drag profile

### 3.1 The named configuration

A new flag `--drag {rig,scaled-air}` selects the road-load model, defaulting to `rig`. The flag
mirrors `--asymmetry` in shape (`tools/hil_plant_sim.py:9455-9463`): a mode choice with a stated
default that is byte-identical to every campaign recorded before the flag existed. A scenario meta
key `drag` supplies the mode when the flag is absent, so the `ems-ftp75c-*` scenarios can declare
`"drag": "scaled-air"` without the operator having to remember a flag.

The measured rig profile is unchanged and stays the default. It remains the bench profile, because
it is what the hardware actually does.

### 3.2 Derivation of `k_air`

The paper vehicle road load is taken as air drag alone:

```
F_d,vehicle(v_v) = 0.5 * rho * Cd * A_f * v_v^2 = 0.505313 * v_v^2   [N]
```

Under the paper scaling the rig force is `S_L^3` times the vehicle force at the corresponding
vehicle speed `v_v = v / S_L`. Substituting:

```
F_road(v) = S_L^3 * 0.505313 * (v / S_L)^2 = (0.505313 * S_L) * v^2
```

so the rig drag coefficient is a single constant:

```
k_air = 0.5 * rho * Cd * A_f * S_L = 0.505313 * 0.1183564 = 0.0598066 N/(m/s)^2
```

At the cycle peak of 3.0 m/s this gives 0.538 N, against the rig own 3.602 N at the same speed.
The compensated plant is therefore approximately 6.7 times more freely rolling at peak speed. The
Coulomb term is zero in this profile: `F_c = 0`, because the compensation replaces the rig
friction rather than adding to it.

Both `Cd` and `A_f` are assumptions. `k_air` is linear in their product, so an operator correction
of `Cd * A_f` scales `k_air` and every drag-dependent figure in this note proportionally.

### 3.3 How the velocity plant takes it

The insertion point is the force balance in `Plant.step()`, `tools/hil_plant_sim.py:1406-1421`.
Two branches carry the drag terms. In the sub-`V_STICTION` branch the Coulomb term follows the
sign of `f_drive`; above it the term follows the sign of `self.v` through `f_sign`. Under
`--drag scaled-air` both branches become:

```
f_net = f_drive - K_AIR * self.v * abs(self.v)
```

with the breakaway test `abs(f_drive) <= F_COULOMB` removed, because a zero Coulomb term makes
that deadband unreachable and the body free to creep. The `v_try` zero-crossing guard should be
kept: quadratic drag alone cannot push the body through zero, but the guard is inexpensive and its
absence would be a silent behavioural difference between the two profiles.

The signed form `v * abs(v)` rather than `v^2` is load-bearing. The rig profile drag always
opposes motion through `f_sign`; a bare `v^2` term would accelerate the body in reverse.

`M_EFF` stays at 3.5 kg. The rig rotating inertia is a physical property of the flywheel and the
drivetrain, and road-load compensation changes only what the machine has to push against. Changing
`M_EFF` would be a different intervention and would invalidate the `K_F` and drag identification
recorded in `controller_design_MIMO/calibration/motor_id_20260815.md`.

### 3.4 The regen share the ruled derivation produces

Table 4 gives the energy chain on `ftp75c` under the ruled `scaled-air` profile, and, for
reference, under two bracketing cases. The clip row applies `VESC_REGEN_I_MAX_A` to the
commanded current, which is where `Plant.step()` applies it (`tools/hil_plant_sim.py:1404`), so
the clip caps braking force and harvest from one number.

| Quantity | drag-free | scaled-air (ruled) | matched-`k_air` (Section 3.5) |
|---|---|---|---|
| Peak drive current | 1.6214 A | 1.7789 A | 1.6408 A |
| Peak regen current, unclipped | -1.6214 A | -1.6210 A | -1.6213 A |
| Braking kinetic energy | 30.817 J | 30.817 J | 30.817 J |
| Shaft regen, unclipped | 30.817 J | 15.793 J | 24.373 J |
| Regen share of braking KE | 100.00 % | **51.25 %** | **79.09 %** |
| Shaft regen after the 1.5 A clip | 30.375 J | 15.661 J | 24.017 J |
| Energy beyond the clip | 0.442 J (1.43 %) | 0.132 J (0.83 %) | 0.356 J (1.46 %) |
| Braking samples above the clip | 10.83 % | 14.95 % | 11.76 % |

The drag-free column reproduces the orchestrator arithmetic in the ruling exactly: a 1.6 A peak
regen current against the 1.5 A clip, 1.4 % of braking energy beyond the clip, and a 1.6 A peak
drive current. This is the check that the model used here is the model the ruling used.

### 3.5 Finding: the ruled derivation does not reach the full-scale regen share

The full-scale vehicle, evaluated on the uncompressed cycle with the same air-drag-only road load,
gives a regen-capable share of **79.09 %** of braking kinetic energy. The ruled `scaled-air`
profile gives **51.25 %**. The gap is exactly the 4.487 residual drag-to-inertia ratio of
Section 2.4: the rig is still too light for the drag it has been given, so its air drag absorbs a
larger fraction of each stop than the vehicle air drag does.

Dividing `k_air` by that residual gives a second candidate constant:

```
k_air,matched = k_air / 4.487 = 0.0133302 N/(m/s)^2
```

This variant reproduces the full-scale share to five significant figures (79.09 %), which is not a
coincidence: matching the drag-to-inertia ratio makes the two braking energy balances similar.

The ruling fixes the derivation, so `scaled-air` as specified is what this note designs and what
the implementer should build. However, the stated intent of the ruling is that "roughly the
full-scale proportion of braking energy is regenerative", and 51.25 % against 79.09 % does not meet
that intent. The recommendation is to implement `--drag` with **three** modes, `rig`, `scaled-air`
and `scaled-air-matched`, ship `scaled-air` on the `ems-ftp75c-*` scenarios as ruled, and put the
choice between the two compensated modes to the operator with these two numbers. The
implementation cost of the third mode is one constant.

### 3.6 Effect on the drive controller

The Youla drive controller in `controller_design_MIMO` was synthesized against the rig plant. The
drag term enters that plant as a single pole. Under the rig profile the pole is
`-B_EFF / M_EFF = -0.1526 rad/s`. Under `scaled-air` the linearized pole is
`-2 * k_air * v / M_EFF`, which is `-0.1025 rad/s` at 3.0 m/s, `-0.0342 rad/s` at 1.0 m/s, and
zero at standstill.

The controller crossover is 17.25 rad/s (CLAUDE.md, fw v18 re-synthesis). The **largest possible
pole movement is 0.1526 rad/s, which is 0.88 % of the crossover**, and it moves the pole toward
the origin, that is toward the free-integrator plant the synthesis corners already bracket at the
low-speed end. The `K_v` corner set `{0.75, 1.00, 1.35}` is a gain uncertainty and is unaffected
by this term.

The Coulomb term is a load disturbance rather than a plant pole. Removing it reduces the constant
disturbance the integrator must reject from 2.00 N to zero, which reduces steady-state control
effort and reduces integrator excursion. It cannot destabilize the loop.

The recommendation is therefore to state the argument above in the scenario documentation and not
to re-run the synthesis gates for this profile. If the implementer prefers a verified statement, a
single 72-corner robustness run in `controller_design_MIMO/ctrl-venv` with `B_EFF` swept from
0.534 to 0.0 discharges it; that sweep is inexpensive and covers the whole range the quadratic term
spans.

### 3.7 Sidecar and fingerprint

The drag mode is recorded in two places, following the `eta_chg` and `asymmetry` precedents.

First, the run sidecar `config` block gains `"drag": drag_mode` and, when the mode is not `rig`,
`"drag_k_air": K_AIR`, alongside `asymmetry` at `tools/hil_plant_sim.py:10490`. The resolved-value
pattern of `asymmetry_dv0_v` is copied so a reader never has to re-derive the constant.

Second, and more consequentially, the drag mode changes the tractive demand for a given speed
profile, which is exactly the class of change `eta_chg` was. `drag` therefore joins
`DP_FINGERPRINT_META_KEYS` (`tools/hil_plant_sim.py:3363`) and
`DP_FINGERPRINT_OPTIONAL_KEYS` (`:3375`), and `dp_profile_fingerprint()` **omits the key entirely
when the mode resolves to `rig`** (`:3479-3490`). This is what keeps every committed DP table,
every SDP policy artifact and all 16 `dp_db` records reachable and byte-identical. A `drag` key
hashed as the string `"rig"` would orphan all of them.

The `K_AIR` module constant is picked up automatically by `collect_model_constants()`
(`tools/hil_plant_sim.py:678`), which sweeps module-level uppercase numerics, so `constants_hash`
will move when the constant is added. That is correct and expected: it is a new model constant.
Runs recorded before the change carry the old hash and the absent `drag` key, which places them in
the rig era unambiguously.

---

## 4. Regen on the compressed cycle

### 4.1 How the plant produces regen today

The chain is documented in `docs/HIL_PLANT.md` section 3.4 and is summarised here because the
scenario design depends on each stage.

The commanded motor current is clipped on the regen side at `VESC_REGEN_I_MAX_A` before it becomes
force (`tools/hil_plant_sim.py:1404`), so braking force and electrical return derive from one
number. Negative shaft power becomes regen node power at `ETA_REGEN`
(`tools/hil_plant_sim.py:1445`). That power drives the V-MOT node capacitance. The TL431 and
BSP170P chopper sits directly on V-MOT, upstream of the REGEN switch, regulates the node at
`V_CHOPPER_TRIP` = 18.1 V through `R_CHOPPER_REG` = 0.5 ohm, and is not under firmware control. The
Ag105 takes an output-referred share, `i_target = min(AG105_I_MAX, ETA_CHG * p_regen_w / V_pack)`
(`tools/hil_plant_sim.py:1839-1843`), only when `SW_REGEN` is set and `SW_FC_CHARGE` is clear. The
charger requires `AG105_SETTLE_S` = 0.5 s of powered settle and then follows its target through a
first-order lag of `AG105_TAU_S` = 0.4 s. `MOT_PWR` is instantiated strict-forward, so no regen
current reaches the bus.

Two consequences shape the expectations of Section 6. The chopper is a residual absorber, not a
prior claimant, which is why the cap is deliberately not netted against it
(`docs/HIL_PLANT.md`, the un-netted-cap ruling). And the settle plus lag mean the first roughly
0.9 s of every regen window is burnt in the chopper rather than banked.

### 4.2 What the EMS scenarios must command

Energy reaches the pack only when `REGEN_ENABLE` and `MOT_PWR_ENABLE` are both closed and
`FC_CHARGE_ENABLE` is open. In firmware, `chargingControl()` (`teensy_controller.ino:10771-10893`)
selects that branch when two conditions hold simultaneously: `charge_goal > 0.05` and
`regenActive`, where `regenActive = (current < -0.1f)` reads the commanded motor current
(`:10807`). The branch then drives `assertFcChargeEnable(false)`, `REGEN_ENABLE` HIGH, and
`MPPT_DISABLE` LOW (`:10817-10819`). `MOT_PWR_ENABLE` is already closed throughout Run.

The mutual exclusion is enforced by `assertFcChargeEnable()`
(`teensy_controller.ino:9259-9294`), which drives `BT_BUS_ENABLE` LOW, then `REGEN_ENABLE` LOW,
then waits 100 microseconds, then raises `FC_CHARGE_ENABLE`. A belt-and-suspenders check in
`detectFaults()` (`:5364-5370`) latches `FAULT_SWITCH_CONFLICT` if the illegal combination is ever
observed. Firmware therefore cannot be made to charge from both paths at once, and the host does
not need to enforce that invariant; it needs to avoid provoking the wrong branch.

The hazard the host must avoid is documented at `tools/hil_plant_sim.py:2729-2738`. Asserting
`charge_goal > 0` one tick before the commanded current has gone negative takes the **cruise**
branch, which calls `assertFcChargeEnable(true)`, drops BT off the bus, and creates the
single-source condition that previously latched `OC_FC`. This is why `ems_regen_harvest()` carries
`EMS_REGEN_CHARGE_LEAD_IN_S` = 0.20 s and `EMS_REGEN_CHARGE_LEAD_OUT_S` = 0.10 s.

Today only `regen-harvest` and `regen-harvest-hard` command this, and both do so from hardcoded
window tables (`EMS_REGEN_BRAKE_WINDOWS`, `EMS_REGENTRUE_BRAKE_WINDOWS`). No EMS strategy commands
it at all.

### 4.3 The regen manager

The design is a **common layer in the strategy proxy, not per-strategy logic**. Three reasons make
this the right decomposition.

- Regen admission is a function of the stimulus, not of the energy-management decision. Every
  strategy brakes at the same instants, because every strategy follows the same `ems_v_profile`.
- Making it common makes regeneration strategy-independent, which is what allows a frontier
  comparison on `ftp75c` to remain a comparison of share policies rather than a comparison of which
  strategy remembered to close a switch.
- Duplicating the lead-in and lead-out reasoning across six strategies is exactly the failure the
  `assertFcChargeEnable()` history warns about.

The proposed shape is a function `regen_manager(t, fb, cmd, windows)` applied to every strategy
returned command dictionary immediately before it is encoded, inside the same layer that already
validates `POLICY_ALLOWED_FIELDS` (`tools/hil_plant_sim.py:2379`). Its rules are:

1. When `t` lies inside a commanded regen window, force `charge_goal = 1.0` and leave every other
   field untouched.
2. When `t` lies outside every window, leave `charge_goal` exactly as the strategy returned it.
3. When the strategy own `charge_goal` is already positive at the start of a regen window, the
   window still wins, because the firmware `regenActive` branch will take precedence anyway and
   the host model of which path is open must match.

Rule 3 is the only interaction with the `SDP_CHG_MIN_DWELL_S` = 8.0 s dwell. That dwell is a host
construct in `SdpStrategy.charge_hold_status()` (`tools/hil_plant_sim.py:5494`) and
`mpc_ems.py:1110`, and it governs the **FC-path** charge windows. A regen window that overlaps a
latched FC charge window does not violate it: the firmware silently moves from the cruise branch to
the regen branch and back, and the host dwell timer continues to count. What must change is that
the SDP and MPC charge-window bookkeeping must **not** count regen-window ticks as FC charge ticks,
or the dwell accounting and the `chg_holds` census will both be wrong. The clean implementation is
for the regen manager to set a separate `regen_commanded` flag on the feedback view that the
strategies own charge bookkeeping excludes.

### 4.4 Window derivation

The windows are derived from the profile at scenario-bind time rather than hand-tabulated. The
derivation rule is the physical one: a profile segment is regen-capable when the required motor
force `M_EFF * a + k_air * v * abs(v)` is negative at either endpoint. Contiguous segments are
merged, a lead-in of 0.20 s and a lead-out of 0.20 s are applied, and windows shorter than 0.50 s
after trimming are dropped.

The lead-out is lengthened from the 0.10 s of `ems_regen_harvest()` to 0.20 s because the
compressed cycle decelerations end in immediate re-acceleration far more often than the hand-built
regen scenarios do, and a late release would take the cruise branch with a still-negative bus.

Table 5 gives the resulting windows on `ftp75c` under the `scaled-air` profile.

| Window | Start (s) | End (s) | Duration (s) |
|---|---|---|---|
| 1 | 21.201 | 24.300 | 3.099 |
| 2 | 30.201 | 31.800 | 1.599 |
| 3 | 41.701 | 42.300 | 0.599 |
| 4 | 57.201 | 57.800 | 0.599 |
| 5 | 62.201 | 67.299 | 5.098 |
| 6 | 91.701 | 92.800 | 1.099 |
| 7 | 95.701 | 98.300 | 2.599 |
| 8 | 156.701 | 162.800 | 6.099 |
| 9 | 163.701 | 171.299 | 7.598 |

Nine windows carry 28.39 s of commanded regen duty, which is 16.7 % of the 170 s cycle. Before
trimming there are 12 regen-capable intervals totalling 34.0 s. Five of the eight inter-window gaps
are shorter than 8 s, which is the reason rule 3 of Section 4.3 has to be stated explicitly.

### 4.5 Energy delivered

Table 6 gives the energy chain on `ftp75c` under `scaled-air`, both in an idealized form that
ignores the charger settle and lag, and in the form the simulator will actually produce.

| Stage | Idealized | With `AG105_SETTLE_S` and `AG105_TAU_S` |
|---|---|---|
| Braking kinetic energy | 30.817 J | 30.817 J |
| Shaft regen after the 1.5 A clip | 15.661 J | 15.661 J |
| Regen node energy, `ETA_REGEN` = 0.80 | 12.529 J | 12.529 J |
| Regen node energy inside commanded windows | 12.030 J | 12.030 J |
| Energy into the pack | 11.026 J | **7.793 J** |
| Charge delivered | 1.3956 C | **0.9865 C** |
| SoC gain per cycle | +7.75e-5 | **+5.48e-5** |
| Chopper burn, in window | 1.504 J | 4.237 J |
| Chopper burn, outside windows | 0.499 J | 0.499 J |
| Peak `I_charge` | 0.1464 A | 0.1242 A |

The realizable fraction is 70.7 %. The 0.5 s settle plus the 0.4 s lag cost roughly 0.9 s at the
head of each of nine windows, which is why windows 3 and 4 (0.599 s each) deliver essentially
nothing and are retained only so that the switch and path coverage exists.

`AG105_I_MAX` = 2.5 A is never approached. The peak `I_charge` of 0.124 A is 5.0 % of the ceiling,
so the Ag105 cap is not a binding constraint anywhere on this cycle. The VESC clip is the binding
constraint, and it costs 0.83 % of shaft regen energy.

### 4.6 Finding: the regen credit is small against the cycle drain

The traction demand on `ftp75c` under `scaled-air` integrates to 65.34 A s of motor current at
V-MOT, and the fixed auxiliary load contributes 25.50 A s at the bus over 170 s. At an even share
this is roughly 96.8 A s of pack draw, that is a SoC excursion near -0.0054. The regen credit of
0.9865 C is **1.4 % of that drain**.

This is the honest scale of the effect. `ftp75c` makes regeneration observable, repeatable, and
correctly modelled. It does not make regeneration a large term in the hydrogen economy of this rig,
and no frontier conclusion should be drawn on the basis that it might be. Section 5.6 quantifies
the frontier consequence.

---

## 5. The regen term in the demand model

### 5.1 The pre-committed contract

Adding a regen term is not a free change. `tools/gen_dp_ems_table.py:1232-1244` states the
obligation in advance: `ETA_REGEN` and `VESC_REGEN_I_MAX_A` are deliberately absent from the DP
table header and from the drift guard **because** `build_demand()` has no regen term, and if a
generator ever gains one, "BOTH must move into this header and into the guard".

This note discharges that contract by making the regen term an **era**, exactly as `eta_chg` is an
era. The mechanism is the convention of `charger_power.py` (`:24-27`): an absent key means the old
era.

### 5.2 The signed demand

`build_demand()` currently computes, at `tools/gen_dp_ems_table.py:596-599`:

```
force  = M_EFF * a + f_coul + B_EFF * v
p_mech = max(0.0, force * v)
```

The regen era replaces the one-sided floor with a signed pair. Braking power available at the
shaft is the negative part, limited by the VESC clip, and it is converted to a pack charge current
by the same output-referred rule the plant uses:

```
force    = M_EFF * a + F_road(v)                          # F_road per the drag era
p_pos    = max(0.0, force * v)                            # unchanged; the traction demand
f_regen  = max(force, -K_F * VESC_REGEN_I_MAX_A)          # the clip, as a force
p_brake  = max(0.0, -(f_regen * v))                       # shaft power available to return
p_regen  = ETA_REGEN * p_brake                            # electrical, at the regen node
i_regen  = min(ETA_CHG * p_regen / V_pack, ag105_i_max)   # output-referred, un-netted
```

`p_pos` is unchanged, and this is the point the 2026-09-02 correction at
`tools/gen_dp_ems_table.py:553-557` already made: the DP deceleration demand was never
overstated. What the DP omitted was the credit. `i_regen` is that credit, expressed directly as a
pack current rather than as a negative bus power.

Expressing the credit as a current rather than as a negative `p_dem` is the central design choice
here, and it is made for four concrete reasons rooted in the existing code.

- Nothing flows back to the bus. `MOT_PWR` is strict-forward, and `docs/HIL_PLANT.md` records the
  bus contribution as structurally zero while the chopper clamps. A negative `p_dem` would
  incorrectly credit the bus.
- The split-control feasibility test of `solve_dp()`, `(p_fc / V) <= LIMIT_I_FC_MAX_A`
  (`tools/gen_dp_ems_table.py:754`), and its stage cost at `:750` both assume `p_dem >= 0`. A
  negative `p_dem` would bill negative hydrogen.
- The budget test of `charge_mask()`, `(p_dem / v_bus + i_chg_bus) <= margin * LIMIT_I_FC_MAX_A`
  (`:639-640`), would become trivially true on braking stages and would admit FC charge windows the
  firmware never opens there.
- The MPC violation tables (`tools/mpc_ems.py:1735-1737`) bound `d * i_tot` and
  `(1 - d) * i_tot` one-sidedly and would not catch a regen current limit.

### 5.3 Where it enters the stage transition

The SoC transition on the split column, `tools/gen_dp_ems_table.py:749`, becomes:

```
soc_next[:, :m] = soc_col - i_pack * dt / cap_as + i_regen[k] * dt / cap_as
```

with `stage[:, :m]` unchanged. This gives the property the design needs: **SoC gains during
braking stages independently of the share decision**, because `i_regen[k]` is a per-stage constant
that does not depend on the control index. The stage cost stays separable, and the DP stays
tractable at the same complexity.

The charge column at `:757` gains the same additive term, subject to the exclusivity constraint of
Section 5.4. `forward_pass()` and `step_discharge()` / `step_charge()`
(`tools/gen_dp_ems_table.py:648-673`) mirror the change term for term.

### 5.4 Exclusivity, the mask, and the reachable window

A stage cannot both FC-charge and regen-charge. This is the host-side image of the hardware guard
in `assertFcChargeEnable()`, and it is expressed as one term in `charge_mask()`:

```
return in_run & cruise & budget_ok & (i_regen <= 0.0)
```

`cruise` already excludes most braking stages, but not all: a shallow deceleration inside the
cruise-slope tolerance can be regen-capable under the compensated drag. The explicit term makes
the exclusion exact rather than incidental. Note that this keeps the mask **state-independent**,
which `tools/gen_dp_ems_table.py:627-628` identifies as the property that makes the stage cost
separable.

`reachable_soc_window()` (`:679-704`) needs the regen term in both extreme-policy walks, because
regeneration raises the upper bound reachable from any state. Omitting it would place the SoC grid
below trajectories the DP can actually reach, and transitions off the grid are infeasible rather
than clamped (`:774-775`), so the omission would silently truncate the optimum.

The matched-DP terminal target logic (`solve_matched()`, `:1089-1117`) needs no structural change.
Its argument at `:1506-1520` is unaffected: the comparison is still at matched terminal SoC. What
changes is that the DP now earns the same braking credit the live run earns, so the
`regen_bound` correction that `hil_report_analysis.matched_dp_for_run()` currently prices as a
per-run bound becomes zero on regen-era runs. That is the purpose of the change: the bound stops
being an unquantified inflation of the DP hydrogen total.

### 5.5 Lockstep and the fingerprint

Three sites must move together, or the DP bound and the MPC prediction are no longer comparable,
which is the stated reason the omission was inherited in the first place.

1. `tools/gen_dp_ems_table.py:599`, the array form.
2. `tools/mpc_ems.py:587`, the scalar port, plus the SoC integrator in `Planner._rollout()`
   (`:1778-1781`) and the charge enumeration admissibility (`:2536-2556`).
3. `tools/ems_walk.py:438-448` and its per-stage loop at `:556-583`, which consumes both.

The era key is `eta_regen`, resolved exactly as `eta_chg` is. It is `None` by default, meaning the
term is absent, which reproduces every committed table byte for byte. `tools/charger_power.py` is
stdlib-only by design (`:38-42`); a parallel `tools/regen_power.py` holding
`resolve_eta_regen()`, `check_eta_regen()` and `regen_pack_current_a()` must hold the same
constraint so `ems_walk` and `mpc_ems` can import it without numpy.

The fingerprint gains **two** optional keys, `eta_regen` and `drag`, both omitted when they resolve
to `None` and `"rig"` respectively (`tools/hil_plant_sim.py:3479-3490`). They are two keys and not
one because they are independent: a rig-drag run in the regen era is legitimate and produces zero
regen, and a compensated run in the pre-regen era is a defined, if pointless, configuration. When
`eta_regen` is set, `VESC_REGEN_I_MAX_A` moves into the DP table header and the drift guard, as
`tools/gen_dp_ems_table.py:1243-1244` requires.

Also to be reconciled in the same change: `tools/ems_walk.py:33-34`, `tools/mpc_ems.py:155-158`
and `tools/mpc_ems.py:557` still assert the "over-states demand on decelerating stages" reading
that `tools/gen_dp_ems_table.py:553-557` retracted on 2026-09-02.

### 5.6 Which strategies benefit

None differentially, by construction. Because the regen manager is common (Section 4.3) and the
regen credit `i_regen[k]` is share-independent, every strategy receives the same +0.9865 C on the
same nine windows. The frontier ratios are therefore affected only through second-order coupling:
a slightly higher SoC changes the pack terminal voltage and hence the bus current the battery
branch must supply for a given power. Against a 1.4 % credit on the drain and a pack that moves
5.5e-5 in SoC, that coupling is far below the campaign C repeatability floor of approximately
50 ppm on h2.

The correct statement for the campaign report is therefore that `ftp75c` **validates the regen
model end to end and REDUCES the DP regen divergence**, and that it is **not** expected to
reorder the strategies. A reordering on this stimulus should be treated as a defect signal rather
than as a result.

---

## 6. Expectations

### 6.1 Fault-free requirement

All five legs are expected completely fault-free: `allow_only: 0`, with
`survive_to: {"t": 175.0, "states": {2, 3}}`. The specific latch to watch is
`FAULT_SWITCH_CONFLICT` (bit 0x0008), which would indicate that the regen manager provoked the
cruise branch inside a braking window. It should never fire, and if it does the lead-in of
Section 4.4 is the first thing to re-derive.

### 6.2 Peak `I_fc` bands

Road-load compensation reduces the traction demand by roughly a factor of 4.5. Table 7 gives the
peak bus current and the resulting peak `I_fc` at three commanded shares.

| Cycle and drag | Peak `p_mech` | Peak `I_total` | Peak `I_fc` at share 0.50 / 0.6667 / 0.85 |
|---|---|---|---|
| `ftp75`, rig | 10.94 W | 0.960 A | 0.480 / 0.640 / 0.816 A |
| `ftp75c`, rig | 11.28 W | 0.985 A | 0.492 / 0.657 / 0.837 A |
| `ftp75c`, scaled-air | 2.43 W | 0.330 A | 0.165 / 0.220 / 0.281 A |

The `LIMIT_I_FC_MAX` of 1.4 A is never approached: the worst case is 20 % of it. Every `I_fc` band
inherited from the `ems-ftp75-*` legs must therefore be **re-derived downward**, not carried over.
Carrying over the 0.56 A floor of `socband_fc_carried`, for example, would fail a correct board on
every tick.

### 6.3 Finding: the `soc-band` charge thresholds are unreachable on this plant profile

`SOC_BAND_CHARGE_ENTER_ITOT_A` is 0.60 A and `SOC_BAND_CHARGE_EXIT_ITOT_A` is 1.30 A
(`tools/hil_plant_sim.py:3123-3124`). The compensated cycle peak `I_total` is 0.330 A, which is
**below the entry threshold at every instant of the cycle**. The consequence is that
`ems-ftp75c-socband` would admit a charge window at the first cruise sample and never exit it by
current. That is not a defect in the strategy; it is a threshold calibrated against a plant with
4.5 times the drag.

Two options exist. The first is a per-scenario override of the two thresholds, scaled by the same
ratio, giving approximately 0.13 A entry and 0.29 A exit; this preserves the strategy mechanism
and is the recommendation. The second is to accept the permanently-open window and score the leg
as a charge-saturated control. That would make it useless as a frontier reference. The override
should be a scenario meta key, so the 61 s and `ftp75` legs are untouched.

The `sdp-v4` and `dp-replay` legs do not have this problem, because their charge admission comes
from a solved policy over an SoC and demand grid rather than from an absolute current threshold.
However, their policies must be re-solved against the compensated demand, which Section 9 lists.

### 6.4 Regen observables

Four checks make the regen path observable. Their forms follow the vocabulary at
`tools/run_hil_suite.py:6614-6730` and their values come from Table 5 and Table 6, de-rated for
first-campaign uncertainty.

- `ftp75c_regen_duty`: `switch_bit: SW_REGEN`, `min_ticks: 20000`, `t_window: (5.0, 175.0)`.
  20000 ticks is 20 s against a modelled 28.39 s of commanded duty, a 30 % margin. Prefer this
  aggregate over phase-locked window assertions, per the standing guidance at
  `tools/run_hil_suite.py:3053-3057`.
- `ftp75c_regen_charge`: `column: I_charge`, `min_value: 0.06`, `t_window: (62.0, 68.0)`.
  Window 5 is the first long one; the modelled peak inside it is 0.124 A, so 0.06 A carries
  a factor of two.
- `ftp75c_chopper_total`: `{"total_of": "chopper_clamp", "field": "energy_j", "min_value": 2.5}`,
  against a modelled in-window burn of 4.237 J. Note that `max_of` bounds the largest single
  coalesced episode and not a per-window sum (`tools/run_hil_suite.py:953-963`); a `max_of` floor
  of 0.6 J is defensible against the 1.056 J of window 5 but is the weaker of the two.
- `ftp75c_node_lift`: `column: V_rgn`, `min_value: 17.9`, `min_ticks: 400`, `t_window: (62.0, 68.0)`.
  This asserts that V-MOT actually lifts onto the clamp. It is the check that distinguishes real
  energy capture from a closed switch with no current behind it.

Every one of these is **provisional** on the first campaign and must carry a `provisional_note`
saying so. The four values above are walk predictions, not measurements. In particular
`ETA_REGEN` = 0.80 and `VESC_REGEN_I_MAX_A` = 1.5 A are both `TODO(verify)`, and the entire
harvest column of Table 6 is linear in the first and roughly linear in the second.

Do not assert SoC direction on these legs. `docs/HIL_SCENARIOS.md:219-222` already states this for
`regen-harvest-true`, and the reason applies with more force here: a +5.5e-5 SoC credit against a
-0.0054 drain is invisible in the SoC trace.

### 6.5 Campaign cost

Table 8 gives the campaign cost. The wall-time estimate uses `DEFAULT_SETTLE_S` = 5.0 s per run.

| Item | Cost |
|---|---|
| Five `ems-ftp75c-*` legs at 180 s | 900 s |
| Settle pauses, five at 5 s | 25 s |
| **On-bench total** | **925 s, 15.4 min** |
| Matched-DP per leg, `13 * (180/61)^2.7` | 241 s, 4.0 min |
| Five matched-DP solves | 1207 s, 20.1 min |
| One `ems-ftp75c-dp` table generation, matched | approximately 241 s |
| **Offline total** | **approximately 24 min** |

The cost model is `matched_dp_cost_estimate_s()` at `tools/hil_report_analysis.py:1675-1692`. The
~6 min per solve in the ruling is a conservative planning figure against the 4.0 min of the model;
the model is an interpolation between two measured anchors (13 s at 61 s and 20 to 30 min at 340 s)
and a 180 s solve would be a new measured anchor for it.

One implementation obstacle: `MATCHED_DP_LONG_DURATION_S` is 100.0 s
(`tools/hil_report_analysis.py:1700`) and the refusal gate at `:1978-1985` will decline a 180 s
matched solve unless `--matched-dp-allow-long` is passed. Either the flag is passed for these
legs, or the five solves are prefilled into `tools/dp_db/` ahead of the campaign with
`_cmd_prefill()` of `dp_results_db.py` (`:863`). Prefilling is the recommendation, because it moves
24 minutes off the campaign critical path.

Adding `ftp75c` to the default campaign is not proposed. It is gated behind `--with-ftp75c` for
the same reason `ftp75` is gated: run time alone.

---

## 7. Bench replication

Road-load compensation cannot be replicated on the bench with the single motor now fitted. The
reason is structural. The compensation would have to be a friction feedforward that cancels
`F_COULOMB + B_EFF * v`, that is up to 3.60 N at 3.0 m/s, and the only actuator able to apply it is
the traction motor itself. A feedforward of that form keeps the net motor force **positive**
throughout a stop, because the motor is supplying the friction the compensation is cancelling.
There is no instant at which current reverses, so there is no physical regeneration to measure.
The bench would exercise the firmware regen branch only if the command were falsified, which is
not a measurement.

Option 1 on the bench therefore requires a **second motor acting as a road-load brake on the
flywheel**. Sizing follows from the drag difference the compensation represents. The road-load
motor must absorb the rig own friction, `F_COULOMB + B_EFF * v` minus the scaled air drag
`k_air * v^2`, which at 3.0 m/s is `3.602 - 0.538 = 3.064 N` and is approximately 3.1 N. At the
0.076 m flywheel rim this is:

- Rim force: approximately 3.1 N
- Torque: `3.1 * 0.076 = 0.236 N m`, approximately 0.24 N m
- Speed: `3.0 / (2 * pi * 0.076) = 6.28 rev/s`, approximately 377 rpm
- Mechanical power: `3.1 * 3.0 = 9.3 W`, under 10 W

A sub-10 W, 0.24 N m, 400 rpm four-quadrant drive is a small brushless motor with a bidirectional
controller, or a small brushed motor with a current-controlled H-bridge and a dump resistor. The
requirement is torque control, not speed control: the road-load motor must present a commanded
opposing force regardless of speed.

Three calibration and interlock requirements attach to it.

- **Coast-down calibration.** The compensation is only as good as the friction model it cancels.
  A coast-down from 3.0 m/s with the traction motor free gives `F_COULOMB` and `B_EFF` directly
  from the deceleration against speed, and it must be repeated after any drivetrain rework. The
  fitted values, not the model constants, drive the road-load command.
- **Speed floor interlock.** Below approximately 0.2 m/s the friction model is unreliable and the
  Coulomb term sign is ill-defined, so the road-load command must be forced to zero. Without
  this the brake motor can drive the flywheel backwards through zero.
- **Setpoint-zero interlock.** When the drive setpoint is zero and the flywheel is at rest, the
  road-load command must be zero and the brake motor must be de-energized. A standing torque
  command at standstill is a stall condition on a sub-10 W motor and is a thermal hazard.

Neither the sizing nor the interlocks are in scope for the HIL work. They are recorded here so
that the HIL result is not later mistaken for a bench-replicable one. On the bench, the rig drag
profile remains the only physically honest configuration, and it regenerates nothing.

---

## 8. Open items

- `Cd` = 0.33 and `A_f` = 2.5 m^2 are assumptions. `TODO(verify: operator)`. `k_air` is linear in
  their product.
- The choice between `scaled-air` (51.25 % regen share, the ruled derivation) and
  `scaled-air-matched` (79.09 %, the full-scale share) is an operator decision. Section 3.5.
- `ETA_REGEN` = 0.80 and `VESC_REGEN_I_MAX_A` = 1.5 A remain `TODO(verify)`. The whole harvest
  column of Table 6 scales with the first.
- The `soc-band` charge thresholds need a per-scenario override on the compensated profile.
  Section 6.3.
- `BATT_CAPACITY_AH` = 5.0 Ah is `TODO(verify)`; the SoC-gain figures scale inversely with it.
- Whether the campaign should also run `ems-ftp75c-*` on `--drag rig` as a zero-regen control is
  not decided here. It would cost another 15.4 min on bench and would isolate the drag change from
  the regen change. It is recommended if the campaign budget allows.

---

## 9. Implementation file list, in dependency order

1. `tools/gen_ftp75_profile.py`: add `--time-factor` and a matching `--out` default; assert the
   234-point invariance at generation.
2. `tools/ftp75c_profile.py`: generated output. Do not hand-edit.
3. `tools/regen_power.py`: new, stdlib-only. `resolve_eta_regen()`, `check_eta_regen()`,
   `regen_pack_current_a()`, `era_label()`.
4. `tools/hil_plant_sim.py`: the `K_AIR` constant, the `--drag` flag, the `Plant.step()` force
   branch, the `ftp75c` profile import and sha gate, the `FTP75C_*` timing constants, the five
   `ems-ftp75c-*` scenario entries, the regen-manager layer and window derivation, the two new
   optional fingerprint keys, and the sidecar `config` keys.
5. `tools/gen_dp_ems_table.py`: the signed demand in `build_demand()`, the stage transitions,
   `charge_mask()`, `reachable_soc_window()`, the table header, and the drift guard.
6. `tools/mpc_ems.py`: the scalar port at `:587`, `_rollout()`, the violation tables, and the
   charge enumeration.
7. `tools/ems_walk.py`: the walk consumption of both, and the stale docstring at `:33-34`.
8. `tools/sdp_ems_solver.py` and `tools/sdp_policies/`: re-solve the SDP policy against the
   compensated demand if `ems-ftp75c-sdp` is to run on a policy of its own rather than on
   `sdp_policy_v4`.
9. `tools/dp_results_db.py`: prefill the five `ems-ftp75c-*` matched solves.
10. `tools/run_hil_suite.py`: `FTP75C_SCENARIOS`, `--with-ftp75c`, the gate, the two frontier
    tuples, the five expectation blocks, and the stale `--with-ftp75` help text.
11. `docs/HIL_PLANT.md`, `docs/HIL_SCENARIOS.md`, `docs/HIL_USER_MANUAL.md`: the drag era, the
    regen era, and the new scenarios.
12. `tools/test_*.py`: coverage for each of the above, including the byte-identity fixtures that
    prove the rig and pre-regen eras are unchanged.

---

## 10. Implementation corrections (2026-09-02, stage-2 fix round)

This note is a DESIGN record and is preserved above as written. Four of its decisions did
not survive implementation and review, and the corrections are recorded here rather than
edited into the sections, so the reasoning that produced them stays legible.

### 10.1 The regen-window rule is the firmware's, not the physics'

Section 4.4 derives the windows from `M_EFF*a + F_road(v) < 0`. That is the wrong
threshold. `chargingControl()` branches on `regenActive = (current < -0.1f)`
(`teensy_controller.ino:10807`), so an instant whose required current lies in
(-0.1, 0) A is braking in physics and NOT regen in firmware. Commanding `charge_goal`
there takes the CRUISE branch, calls `assertFcChargeEnable(true)` and drops BT off the
bus, which is the single-source condition that has latched `OC_FC` before;
`FAULT_SWITCH_CONFLICT` does not catch it, because FC_CHARGE with BT open is legal.

Measured on `ftp75c` under `scaled-air`, the force rule left 2.900 s of such instants
across seven of its nine windows, one of them (57.200-57.800 s) for the whole of its
length. The implementation trims against the firmware's own test with a 2x margin
instead. Table 10.1 gives the cost.

| Quantity | Section 4.4 rule | Shipped |
|---|---|---|
| Commanded windows | 9 | 6 |
| Commanded duty | 28.400 s | 19.600 s |
| Duty as a fraction of the cycle | 16.7 % | 11.5 % |
| Worst in-window required current | -0.0021 A | -0.2045 A |

The shipped windows are 23.200-24.300, 30.200-31.800, 62.700-67.300, 96.200-97.800,
159.200-162.800 and 164.200-171.300 s.

### 10.2 The soc-band thresholds are percentile-matched, not drag-scaled

Section 6.3 recommends scaling both thresholds by the drag ratio. The source total is
`I_AUX_A + i_motor + i_par`, and the 0.15 A auxiliary floor does not scale with the road
load; only the motor term does. Scaling the whole threshold put the entry at 0.13373 A,
below this cycle's own minimum source total of 0.15079 A, so the leg opened ZERO charge
windows and the frontier's reference never exercised the soc-band mechanism.

The shipped pair is percentile-matched against the rig leg: 0.18074 A enter and
0.33107 A exit. An aux-preserving alternative, scaling only the motor term, gives
0.25030 A and 0.40632 A and is unusable, because the exit sits above this cycle's
maximum source total and the hysteresis then has no upper arm.

### 10.3 The credit is gated on the commanded window

The walk initially credited every regen-CAPABLE stage. Energy reaches the pack only where
the manager has commanded `charge_goal` and the firmware has opened `REGEN_ENABLE`, and
the two sets differ by the lead times, the minimum-window drop and the threshold of
§10.1. The ungated form banked 4.0 % of the credit on stages where no path was open.

### 10.4 The divergence is reduced, not closed

Section 5 states that the regen term "closes the DP regen divergence". It reduces it. The
bound now earns the same braking credit the run earns, which removes the systematic term,
but the Ag105 settle and ramp still cost roughly the first 0.9 s of every window, and the
realizable fraction of §4.5 (70.7 %) is the residual. That residual is disclosed on every
walk that carries the credit.
