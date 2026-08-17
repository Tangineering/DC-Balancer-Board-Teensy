# Scale-Car DC Balancer Board — Bench Result Showcase

Assembled 2026-08-17. This package presents nine bench runs that demonstrate four aspects of
the balancer-board firmware: velocity tracking, power-share tracking, the share-setpoint
governor, and the open-loop/closed-loop handoff. Every figure comes from an on-board SD log
sampled at 1 kHz. No result in this package is a simulation.

---

## 1. What the board is

The board is a bidirectional power-pathing balancer for a 1:10 scale fuel-cell hybrid vehicle.
Two boost converters, one fed by a fuel cell (FC) and one fed by a 2S battery (BT), feed a
common 16.0 V bus. The bus feeds a VESC motor controller. Two control loops run on a Teensy 4.1
at 1 kHz:

- The **drive loop** commands motor current to track a velocity setpoint. The controlled body is
  a flywheel driven through the vehicle's tire; `v_actual` is flywheel surface speed.
- The **power-share loop** sets the fraction of total bus current supplied by the fuel-cell
  channel. The actuator is a pair of multiplying DACs that program the droop resistance of each
  boost converter. The commanded ratio `r_cmd` maps to the two droop gains as
  `r_cmd = gBT / (gFC + gBT)`.

Both loops are Youla-parameterised H-infinity designs with Hanus self-conditioned anti-windup,
synthesised offline and shipped as generated coefficient headers.

---

## 2. Directory layout

| Directory | Topic | Runs |
|---|---|---|
| `01_velocity_tracking` | Drive-loop step response | ML0149, ML0151 (+ family figure over ML0146–ML0150) |
| `02_power_share_tracking` | Share-loop trajectory tracking | WP0124, WP0122 |
| `03_setpoint_governor` | Minority-current governor | TP0105, TP0116 |
| `04_open_closed_loop_handoff` | Loop-mode transition | TP0134, TP0129, WP0123 |

Each run directory holds the standard figure set produced by the project analysis pipeline plus
the decoder provenance report (`decode_report.txt`, which records the log format version,
firmware version, and profile parameters). The figures named at the top level of a topic
directory are purpose-built for this package. Raw `.BLG` logs and decoded CSVs are available on
request; they were omitted here for size.

### Log-name prefixes

- `ML` — a manual log opened by the operator around a hand-commanded run.
- `TP` — a trapezoidal motor-current profile. The motor is used as a programmable bus load.
- `WP` — a combined motor-current and power-share profile: a 16-region, 40 s table that sweeps
  the current command and the share setpoint together.

---

## 3. Firmware versions, and why they differ between topics

| Topic | Firmware | Date |
|---|---|---|
| Velocity tracking | v14 | 2026-08-17 |
| Handoff (TP runs) | v8 | 2026-08-16 |
| Share tracking, governor, handoff (WP runs) | v6 | 2026-08-12 |

The velocity results are the newest available. The share-loop results are not, and the reason is
a bench limitation rather than a firmware regression. The share loop closes only above 0.60 A of
total source current (Section 6). No fw v14 run has yet carried a bus load that crosses that
threshold: the one combined-profile run on fw v14, YP0152, held a median total of 0.13 A and
therefore ran open-loop for 99.8 % of its duration. The share-loop control law, the governor
constants, and the mode-transition logic are **unchanged** between fw v6 and fw v14; the fw
v7–v14 changes are confined to the drive channel, the encoder estimator, and observability. The
fw v6/v8 runs are therefore representative of the shipped share-loop behaviour, but a repeat
under fw v14 with a real bus load above 0.6 A is outstanding.

---

## 4. Velocity tracking — `01_velocity_tracking`

The drive controller tracks a velocity step with a steady-state error of 2 to 4 mm/s at every
level tested from 0.5 to 2.66 m/s.

### `velocity_step_family.png`

Five single-step runs (ML0146–ML0150 at 0.5, 0.75, 1.0, 1.5 and 2.0 m/s), normalised by their
own setpoint and aligned at the step instant. The upper panel shows the responses collapsing
onto one curve, which confirms the loop is operating in its linear regime across a 4:1 range of
setpoint. The lower panel shows the commanded motor current against the ±12 A actuator rail.

Measured performance, per run, over the settled hold:

| Run | Setpoint | Steady-state error | Std. dev. | Time to 90 % | Overshoot | Time at the rail |
|---|---|---|---|---|---|---|
| ML0146 | 0.50 m/s | −2.3 mm/s | 30 mm/s | 122 ms | +18.2 % | 1.1 % |
| ML0147 | 0.75 m/s | −2.0 mm/s | 26 mm/s | 111 ms | +11.6 % | 1.1 % |
| ML0148 | 1.00 m/s | −2.4 mm/s | 27 mm/s | 239 ms | +11.9 % | 2.7 % |
| ML0149 | 1.50 m/s | −2.5 mm/s | 25 mm/s | 195 ms | +8.4 % | 3.9 % |
| ML0150 | 2.00 m/s | −4.0 mm/s | 66 mm/s | 498 ms | +11.3 % | 7.2 % |

The design point is 4.8 % overshoot at a 17.5 rad/s crossover. The measured rise is 1.3 to 1.6
times faster than the small-signal design and the overshoot is correspondingly larger, which
indicates the true plant is slightly stiffer than the nominal model. This is consistent with an
independent observation: measured hold currents sit at 0.89 to 0.92 times the drag-law
prediction.

### `ML0149` — 1.5 m/s step, 12.3 s

The cleanest single step in the set. Look at `tracking_overlay.png` for the response and
`drive_controller_conditioning.png` for the anti-windup evidence: the controller's pre-clamp
output `u_unsat` is logged alongside the commanded current, and during saturation it hugs the
rail rather than diverging from it. Divergence would indicate integrator windup. Across all
seven runs of this session, approximately 90 saturation episodes were checked and the worst
sustained excursion past the rail was +3.4 A, with a clean release every time.

The share panels in the ML figures carry no information. These runs had no programmed bus load,
so the total source current was near zero and the measured share is numerically ill-conditioned.

### `ML0151` — stepladder, 0 to 2.66 m/s and back, 56.6 s

A six-level ladder that exercises the full speed range in one run. Settled error is at or below
19 mm/s at every level, and at or below 2 mm/s at four of the six.

**Two features of this run require explanation before it is presented.**

1. **A mechanical drag step-change occurs at t ≈ 27.5 s**, during the 2.0 → 2.5 m/s step. The
   real speed collapses from 2.55 to 1.30 m/s, the loop recovers over 688 ms at full rail, and
   the drag is permanently about 2.2 times higher afterwards (bus input power at 2.0 m/s rises
   from 4.30 W to 9.44 W). The encoder edge rates match the predicted rates on both sides of the
   event, so the cause is physical — tire/roller contact or preload — and not a sensor artefact.
   The elevated standard deviations at the 1.00 and 2.00 m/s levels are dominated by this event
   and by the recovery transient, since those two levels are visited on both sides of it.
2. **A VESC dead window of approximately 428 ms follows the hard regen-to-drive reversal at
   t = 42.0 s.** The firmware commands +11.4 A, the delivered current stays below 50 mA, and the
   vehicle continues to decelerate. This is the entire cause of the 87 % undershoot on the
   2.66 → 2.0 m/s step. It originates in the motor controller, not in this board's firmware, and
   it is scheduled for separate characterisation.

### Known limitations of the velocity channel

- **The encoder front end has no hysteresis.** The two optical sensors are bare phototransistors
  with pull-up resistors. Signal edges ramp over 0.5 to 1 ms, which admits threshold-region
  noise. Above 0.307 m/s the firmware's adaptive period-plausibility filter suppresses the
  resulting edge corruption completely: zero rung-family corruption was found in approximately
  130 000 samples. Below about 0.4 m/s the filter is disarmed by design and sign reversals
  occur. A Schmitt buffer is the root fix and is not yet fitted.
- **A residual current chatter of 3.5 to 5.6 Hz is present at cruise**, up to approximately
  11–13 A peak-to-peak, while the measured velocity ripples only about 0.03 m/s. This is
  estimator edge jitter amplified by the controller's 545 A/(m/s) low-frequency gain. It is
  visible on the current axis only and is not a velocity limit cycle. Judging it properly
  requires the Schmitt buffer first.
- **The synthesis is gate-checked for v ≥ 0.5 m/s only.** The 0.5 m/s run (ML0146) shows an
  estimator warm-up transient in the first 0.3 s after the step — the peak of 1.06 m/s in the
  family figure — because the edge-period estimator needs three edges before it publishes a
  first reading. No other run in the family shows this. Below 0.5 m/s the estimator behaves as a
  deadband relay and limit cycling is expected.

---

## 5. Power-share tracking — `02_power_share_tracking`

With the loop closed, the measured share tracks its setpoint to a median absolute error of
0.001 to 0.003, against a setpoint range of 0.2 to 0.8. The relevant figure in each run
directory is `share_controller.png`: the upper panel is tracking, the lower panel pairs the
share error against the commanded ratio `r_cmd` that produced it.

### `WP0124` — combined profile, Imax 8.0 A, 14.6 s

The highest-load run in the set, and the cleanest share tracking on record. The profile steps to
0.50, steps to 0.65, then ramps down toward 0.38. The measured share follows the ramp with no
visible lag. Median absolute error in closed loop is **0.0009**, with a 95th percentile of
0.0043 — that is, the loop holds the fuel-cell fraction to within half a percent of command.

**This run ended in a board brownout at 14.57 s of a 40 s profile, and the log file is
truncated — it carries no trailer.** The signature is unambiguous: the battery rail `V_batt`
decayed to 5.54 V while the bus stayed in regulation at 15.7 V, at a commanded motor current of
7.68 A. The board's own logic supply is derived from `V_batt` through an LDO, so a `V_batt`
collapse stops the microcontroller with the bus apparently healthy, and no bus-referenced fault
can see it. No fault flag was raised, which is correct behaviour rather than a miss. A `V_batt`
undervoltage fault is a deliberately deferred item, blocked on capturing the LDO input threshold.

The data before the cut are valid and are not affected by the ending — the loop had been holding
the ramp for several seconds when the supply failed. The run is presented here because it is the
best share-tracking data on record, but it should be presented as a 14.6 s excerpt and its ending
should be stated, not omitted.

### `WP0122` — combined profile, Imax 6.0 A, clip bound b = 0.20, 40 s

The complete 40 s profile. The setpoint trajectory covers 0.20 to 0.80 in steps and ramps, which
makes this the better run for showing the shape of the reference the loop is asked to follow.
Median absolute closed-loop error is 0.0028.

The visible standing offsets — for example approximately +0.06 between t = 8 and 11 s, and
+0.13 between t = 22 and 27 s — are **not** tracking failures. Those intervals are open-loop
segments, where the load fell below the closed-loop entry threshold and the firmware
deliberately stopped stepping the controller. Section 6 quantifies this.

---

## 6. Setpoint governor — `03_setpoint_governor`

### The problem the governor solves

An in-band share setpoint asks the droop split to hold one channel at a small fraction of the
total current. Below a light-load conduction floor of about 0.30 A that command is infeasible:
the minority boost converter cannot hold a stable operating point, the bus commutates between
sources, and the loop limit-cycles chasing a target it cannot reach. A validation sweep
bracketed the floor directly — a commanded 0.245 A minority still collapsed the bus to 8.2 V,
while 0.29 A was clean.

### The mechanism

In closed-loop mode the firmware clips the **effective** setpoint so that the commanded minority
current stays at or above `SHARE_MINORITY_I_MIN_A` = 0.30 A:

```
lo      = min(0.30 A / I_total_filtered, 0.5)
hi      = 1 − lo
sp_eff  = clip(sp_commanded, lo, hi)
```

The bound relaxes as load grows, so at high load the governor is inert and the commanded
setpoint passes through untouched. Setpoints outside the usable droop band [0.15, 0.85] never
reach the governor; a separate setpoint-latched channel cutoff owns those.

### `TP0105_governor_action.png` — commanded setpoint 0.15, low side

The upper panel plots the commanded setpoint, the governed effective setpoint, and the measured
share, over a shaded band marking the infeasible region. The lower panel plots the minority
current the raw setpoint would have commanded against the minority current the governed setpoint
actually commands.

At this setpoint the governor is active for **100 % of the closed-loop interval**. The raw
setpoint would have commanded as little as 0.083 A into the minority channel; the governed
setpoint holds it at 0.30 A throughout. The maximum clip is 0.35 in share units. The measured
share follows the governed setpoint, not the commanded one — which is the correct and intended
behaviour, and is the single most important thing to read off this figure.

### `TP0116_governor_action.png` — commanded setpoint 0.83, high side

The mirror case, and the better figure for showing the governor's **relaxation**. As the
trapezoidal load ramps up, the bound retreats; between t ≈ 6.7 s and t ≈ 9.7 s the commanded
0.83 becomes feasible, the governor goes inert, and the minority current is allowed to rise to
0.345 A. As the load ramps back down the clip re-engages smoothly. The governor is active for
61.9 % of the closed-loop interval here, against 100 % on the low side.

Note that the effective setpoint is walked toward its clipped target through a rate limiter of
0.02 share units per tick rather than stepped. Every converged hold point is identical to the
unlimited implementation; only the transients differ.

---

## 7. Open-loop / closed-loop handoff — `04_open_closed_loop_handoff`

### The mechanism

The share loop runs in one of two modes, selected hysteretically on the filtered total source
current `|I_fc| + |I_batt|` (a 20 ms exponential filter, so that ADC noise cannot dither the
decision):

- **Closed loop**, entered above **0.60 A** ( = 2 × 0.30 A): the Youla controller steps, and the
  governor of Section 6 applies.
- **Open loop**, entered below **0.55 A**: the controller does not step at all. The raw setpoint
  is fed forward through the same rate limiter the actuation path uses, and the last applied
  ratio is held thereafter.

The 0.05 A hysteresis band prevents a total current dithering on the threshold from chattering
between modes. On the open-to-closed transition the controller is reseeded from the ratio the
feedforward path had reached, and the reference is walked — not stepped — onto the governed
target. Without that reseeding the first closed-loop tick would apply a reference step of up to
0.35 share units at exactly the load level where the failures being mitigated live.

The open-loop mode exists because the earlier fallback at low load actively caused harm: it
collapsed the effective setpoint to 0.5, which at 0.075–0.60 A of total commands 0.038–0.30 A
per channel — at or below the very conduction floor it was meant to enforce — and it ignited a
source-commutation relay limit cycle that collapsed the bus in six runs of one sweep.

### `TP0134_ol_cl_handoff.png` — trapezoid Imax 5.5 A, setpoint 0.50

The clearest single handoff on record. The upper panel plots the mode decision variable, raw and
filtered, against both thresholds, with the closed-loop interval shaded. The lower panel plots
the actuation.

The filtered total crosses 0.60 A at **t = 5.24 s**. At that instant the commanded ratio leaves
the open-loop feedforward hold of 0.500 and settles at 0.459, and the share error collapses from
**+0.047 to +0.002** — a factor of 20. The run falls back to open loop at t = 16.52 s as the
filtered total decays through 0.55 A; the commanded ratio moves by 0.002 across that transition,
which is the continuity guarantee working.

### `handoff_threshold_bracket.png` — TP0125 to TP0134

Ten trapezoidal load runs of increasing amplitude, plotted as time spent in closed-loop mode
against the peak filtered total current the run reached. Every run whose peak stayed below 0.60 A
spent zero time in closed loop; every run above it entered. TP0129 is the tightest negative
case, peaking at 0.531 A and never entering. The threshold behaves exactly as specified.

### `TP0129` — trapezoid Imax 4.5 A, 41.8 s

The negative control for the figure above, included in full so the null result can be inspected
directly. Peak filtered total 0.531 A; the loop never closes; `r_cmd` holds the feedforward value
for the entire run.

### `WP0123_ol_cl_handoff.png` and `WP0123` — combined profile, full-band share sweep, 40 s

A harder case, included because it is more representative of a drive cycle than a trapezoid is.
The setpoint sweeps the full 0.0 to 1.0 span while the load varies, so the run makes **two
complete open-to-closed-to-open round trips** (transitions at t = 11.19, 16.71, 20.39 and
23.05 s). The transitions are less clean than TP0134's because the setpoint is moving at the same
time; this figure is offered as the realistic case, not the best case.

### What the handoff is worth

Comparing settled, in-band samples at comparable load (total filtered current above 0.30 A) in
the three combined-profile runs:

| Run | Open-loop median abs. error | Closed-loop median abs. error |
|---|---|---|
| WP0124 | 0.055 | 0.0009 |
| WP0122 | 0.064 | 0.0028 |
| WP0123 | 0.063 | 0.0027 |

The open-loop feedforward is good enough to keep the board safe and the split approximately
correct — which is its purpose — and closing the loop improves share accuracy by roughly a
factor of 20.

---

## 8. Reading the figures

Colour and line conventions are fixed across every figure in this package.

- Blue is the velocity family; orange is the power-share family; green is the commanded droop
  ratio `r_cmd`; aqua is the fuel-cell channel and violet the battery channel; red is bus
  voltage; magenta is total bus current.
- Dashed lines are references and setpoints. A darker shade of a hue is the filtered overlay of
  the low-alpha raw trace beneath it; the filter time constant is stated in the legend.
- Light blue shading marks closed-loop mode. Light red shading marks the governor-infeasible
  band.
- Gaps in a trace are missing samples. Nothing is interpolated.

## 9. Provenance

Each run directory contains `decode_report.txt`, which records the log format version, the
firmware version, the profile type and its committed parameters, the number of records read, and
the trailer. Every run in this package decoded with **zero missed sampling periods and zero
faults**. Eight of the nine also carry a clean trailer reporting zero dropped records; WP0124 is
the exception and is truncated, for the reason given in Section 5.
