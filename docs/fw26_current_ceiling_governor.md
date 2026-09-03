# fw v26 — Source current-ceiling governor

## 1. Purpose and scope

This note records the design of the source current-ceiling governor added to the power-share
loop in firmware version 26, and the bench and hardware-in-the-loop (HIL) validation plan for it.

The objective is a reduction in the number of `FAULT_OC_FC` latches during high-power actions.
The overcurrent fault itself is not modified. The governor is a reference-side constraint: it
holds the **commanded** fuel-cell current at a ceiling below the fault limit and forces every
additional ampere of total demand onto the battery. A battery-side ceiling of the same form is
added. The battery ceiling is much higher and is not expected to bind in normal operation.

The following are outside the scope of this document: the plant model used by the HIL simulator,
the energy-management strategies that command the share setpoint, and the Raspberry Pi telemetry
bridge.

## 2. The fault the governor answers

`detectFaults()` evaluates the fuel-cell overcurrent condition as a single comparison:

    if (I_fc > LIMIT_I_FC_MAX) triggerFault(FAULT_OC_FC, ERR_OC_FC);

`LIMIT_I_FC_MAX` is 1.4 A, bus-side. Two properties of this check are load-bearing for the design.

1. The check has **no persistence filter and no dwell**. `FAULT_OV_BUS` accumulates
   `OV_BUS_PERSIST_MS` of continuous over-limit time, and `FAULT_UV_BUS` uses the
   `UV_BUS_DWELL_*` leaky accumulator. The overcurrent check has neither. One raw sample above
   1.4 A latches State 99.
2. The check runs on the **raw** `I_fc` from `updateSensors()`, not on any filtered quantity.

A reference-side clamp therefore cannot answer a fast transient. It acts on a filtered total
current and moves a slew-limited reference. The design consequence is that the ceiling must sit a
real margin below the limit, and that margin must be justified against the tracking error the
clamp cannot remove.

## 3. The share convention

The quantity the share loop tracks is the **fuel-cell fraction** of the total source current.
This is confirmed in `powerBalance()`:

    float power_share_actual_local = fabsf(I_fc) / totalA;

with `totalA = |I_fc| + |I_batt|`. A ceiling on fuel-cell current is therefore an **upper** bound
on the effective setpoint, and a ceiling on battery current is a **lower** bound:

    sp <= I_FC_CEIL / I_tot
    sp >= 1 - I_BT_CEIL / I_tot

Both bounds are evaluated against `share_govTotAFilt`, the governor's exponential moving average
of the total current at `SHARE_GOV_FILT_ALPHA` (approximately 20 ms). No raw measurement gates
the reference. This follows the existing governor doctrine: an unfiltered bound would feed
per-tick analogue-to-digital converter noise directly into the setpoint.

## 4. Constants

| Constant | Value | Derivation |
|---|---|---|
| `SHARE_GOV_I_FC_CEIL_A` | 1.25 A | 0.15 A (10.7 %) below `LIMIT_I_FC_MAX` = 1.4 A |
| `SHARE_GOV_I_BT_CEIL_A` | 2.70 A | 0.30 A (10.0 %) below `LIMIT_I_BT_MAX` = 3.0 A |
| `SHARE_GOV_CEIL_HYST_A` | 0.05 A | Same value and class as `SHARE_GOV_OL_HYST_A` |

### 4.1 The fuel-cell margin

The margin must cover three error terms that separate the clamped command from the raw sample the
fault sees.

- Raw-against-filtered sample noise. The filtered total lags the instantaneous per-channel
  reading.
- Filter lag over a load ramp. At `SHARE_GOV_FILT_ALPHA` = 0.05 the estimate reaches 63 % of a
  step in 20 ticks.
- The closed loop's own tracking error against the clamped reference.

0.15 A is approximately four times the per-channel post-averaging idle noise implied by
`SHARE_I_TOT_MIN_A` (0.075 A of total, set at approximately nine standard deviations).

The ceiling also sits above the largest legitimate fuel-cell peak measured on the board to date.
Campaign B recorded three peaks in that region:

- 1.1920 A on `ems-sdp-cross`;
- 1.1863 A on `ems-sdp-alpha-cal`;
- 1.1370 A on `ems-ftp75-socband`.

The governing figure is therefore **1.1920 A**, and the headroom between it and the ceiling is
**0.058 A**, not the 0.113 A implied by the `ems-ftp75-socband` peak alone. That headroom is the
quantity to watch on the first firmware version 26 campaign. A clamp that engages on
`ems-sdp-cross` indicates the ceiling is set too low; it is not evidence the mechanism works.

This margin is argued from the detection semantics, not measured. It carries a
`TODO(calibrate)` at the constant: re-derive it from the distribution of `I_fc` peaks observed
under a bound clamp in the first firmware version 26 campaign.

### 4.1.1 Reachability: where the ceiling can act at all

The minority-current clip runs before the ceiling clamp, so the largest fuel-cell current the
loop can ever command is

    I_fc_cmd_max = min(DROOP_R_MAX, 1 - SHARE_MINORITY_I_MIN_A / I_tot) * I_tot
                 = min(0.85 * I_tot, I_tot - 0.30)

The second term is the tighter one. The ceiling can therefore be exceeded only above

    I_tot > SHARE_GOV_I_FC_CEIL_A + SHARE_MINORITY_I_MIN_A = 1.55 A

of **two-source** total current. The `DROOP_R_MAX` branch alone would admit it from 1.47 A.
Measured first engagement in the host suite is 1.60 A at a setpoint of 0.85, which is the
analytic threshold plus one sweep step. **1.55 A is the governing reachability number for this
feature.** Below it, firmware version 26 is arithmetically identical to firmware version 25.

**The clamp cannot act in a fuel-cell charge window.** Every overcurrent-class fuel-cell
excursion measured on this board is single-source. `assertFcChargeEnable()` holds `BT_BUS_ENABLE`
low for the whole window, so `I_tot` equals `I_fc`, the share ratio is pinned at `DROOP_R_MIN`,
and there is no second channel to move load onto. At 1.40 A single-source the clamp does not
engage. It could not help if it did, because the load has nowhere else to go.

The consequence for this round is stated plainly: **firmware version 26 is inert on the entire
registered stimulus set.** Validating it requires a deliberately constructed two-source
high-total run. Section 8.2 gives the bench command line and the proposed HIL scenario.

### 4.2 The battery ceiling

`LIMIT_I_BT_MAX` is 3.0 A, the validated per-channel envelope. 2.70 A applies the same 10 %
fractional margin.

The two ceilings together admit only 3.95 A of total bus current. That figure is **below** the
platform's validated 4.2 A to 5.4 A budget, so the corner in which both ceilings bind at once
sits **inside** the operating envelope rather than above it. An earlier draft of this note, the
firmware comment and PLAN.md all stated the inequality the wrong way round.

Above 3.95 A of total, the fuel-cell-last rule resolves the infeasible pair in the fuel cell's
favour and the commanded battery current is knowingly pushed over 2.70 A. It crosses
`LIMIT_I_BT_MAX` at

    I_tot > SHARE_GOV_I_FC_CEIL_A + LIMIT_I_BT_MAX = 4.25 A

Measured: 3.15 A of commanded battery current at 4.40 A of total. From that point `ERR_OC_BT` is
the **intended** latch. The fuel cell is the fragile source; the battery has a 10 A pack behind
it and `FAULT_OC_BT` is unchanged and still guards it independently.

The operator surface for this regime is the `I_bt_cmd` figure on the State-98 `'S'` dump's
`share I-ceiling:` line. A reading above 3.0 A means the board is in the fuel-cell-priority
corner, and an `OC_BT` latch there is the design's own answer rather than a defect. The 4.25 A
crossing has never been reached on hardware and carries a `TODO(calibrate)`.

### 4.3 Compile-time tripwires

Four `static_assert`s are placed at the constants.

- Each ceiling sits strictly below its fault limit.
- Each ceiling sits above `SHARE_MINORITY_I_MIN_A`, so a ceiling can never demand a channel
  current below the light-load conduction floor.
- The release hysteresis stays inside the fuel-cell margin, so a released clamp is still under
  the fault limit.

`SHARE_MINORITY_I_MIN_A` was made `constexpr` in this round so that the second assertion can be
written against the **symbol** rather than a restated `0.30f` literal. A literal would have
stopped tracking the conduction floor silently the first time that floor was retuned. The host
test suite asserts the same ordering against the live constants.

## 5. Placement and ordering

The clamp is applied in the closed-loop branch of `powerBalance()`, after the minority-current
clip and before the effective-setpoint slew. The open-loop `FEEDFORWARD` submode also applies it.
The open-loop `HOLD` submode does not.

### 5.1 Against the minority-current clip

The minority clip is a **conduction feasibility** floor. Commanding a channel below it ignites
the light-load dropout limit cycle observed in logs TP0010 and TP0013, which collapses the bus.
The ceiling clamp is fault avoidance. The clip is therefore applied first.

The two bounds provably cannot conflict. The fuel-cell upper bound `I_FC_CEIL / I_tot` is above
the conduction floor `SHARE_MINORITY_I_MIN_A / I_tot` for every total, because
1.25 A > 0.30 A; the battery bound is symmetric. The ordering is fixed anyway, so that a future
retune that breaks that inequality cannot overwrite the conduction floor.

That proof has a testability consequence, recorded here rather than left implicit. Because the
two bounds cannot conflict at the shipped constants, **swapping this order is an equivalent
mutant**: running the ceiling clamp before the minority clip produces identical behaviour, and no
host test can distinguish it. The ordering guards a future retune; it is not a behaviour the
current suite verifies. The `static_assert`s in section 4.3 are what make the equivalence true,
so they are the part that must not be deleted.

### 5.2 Against the effective-setpoint slew

The clamp modifies the target that `share_spEffPrev` walks toward. It does not modify
`share_spEffPrev` directly. The clamp therefore reaches the controller through the same
`shareSlewStepThisTick` ceiling as every other reference movement, including the conduction-aware
reduced rate. A clamp engagement cannot step the reference.

### 5.3 The infeasible pair

Above `I_FC_CEIL + I_BT_CEIL` = 3.95 A of total, no split keeps both channels under their
ceilings. The battery bound is applied first and the fuel-cell bound second, so the fuel-cell
bound wins. This is the correct priority. The fuel cell has the lower limit, the single-sample
overcurrent check and a fuel-cell stack behind it; the battery has a 3.0 A limit, a 10 A pack
behind it, and `FAULT_OC_BT` as an independent guard.

**Known trade-off.** In that corner the battery is knowingly asked for more than its own ceiling.
A sustained overload can therefore latch `OC_BT` where firmware version 25 would have latched
`OC_FC`. Both faults are unchanged and either latch is correct. The corner sits **inside** the
platform's bus budget, not above it, and the commanded battery current crosses `LIMIT_I_BT_MAX`
at 4.25 A of total. Section 4.2 states that regime in full.

### 5.4 The droop band

The clamped result is finally constrained into `[DROOP_R_MIN, DROOP_R_MAX]`. A reference outside
that band **is** the channel-cutoff signal in `applyShareRatio()`. A current ceiling must never
open a bus switch. The constraint is therefore structural, not arithmetical. Arithmetically the
fuel-cell bound leaves the band only above 8.33 A of total, which is unreachable on this board.
Structurally, no path through the clamp can produce a cut at any total.

### 5.5 Against the firmware version 25 share-cut guard

While `shareCutDeferredFC` or `shareCutDeferredBT` is set, the clamp is suppressed and both clamp
flags are dropped. The deferral has deliberately parked the reference on a band edge to starve a
doomed channel. A deferred battery cut parks it at `DROOP_R_MAX`, which the fuel-cell ceiling
would claw back above approximately 1.47 A of total. One owner per tick applies. The share-cut
guard is that owner, and `OC_FC` is the protection in the window.

### 5.6 Open loop

`HOLD` performs no digital-to-analogue converter write at all. Applying the clamp there would
require a write and would break the hold invariant, so it is not applied. It is also structurally
unreachable: `HOLD` runs only below `2·SHARE_MINORITY_I_MIN_A − SHARE_GOV_OL_HYST_A` = 0.55 A of
filtered total, and no channel can carry 1.25 A out of a 0.55 A total.

`FEEDFORWARD` does write the converters, so it takes the clamp. It is inert there today for the
same arithmetic reason, and is applied so that a future ceiling retune cannot silently leave a
writing path unguarded.

### 5.7 Hysteresis and state

The clamp engages when the demanded channel current exceeds the ceiling. It releases only when
that demand falls `SHARE_GOV_CEIL_HYST_A` below the ceiling. The two flags therefore carry memory
across ticks. They are dropped on every path that stops the share loop:

- the setpoint-latch return;
- the minimum-load return;
- the open-loop `HOLD` return;
- the deferral branch;
- `resetShareControlState()`;
- `doState3()`, the Run to Finish to Idle exit;
- the State-98 `'Q'` exit to Idle.

The last two are not loop freezes. `powerBalance()` simply stops being called on those exits, so
without an explicit clear the flags would survive the whole of Idle and publish a stale clamp on
all three observables. The `'Q'` case was found by the same reasoning as `doState3()` and is
fixed the same way.

One further early return, the open-loop out-of-band quiet return, deliberately does **not** clear
the flags. Reaching it with a flag set is provably impossible: a flag can only be set by a tick
whose filtered total exceeded 1.47 A, and that branch runs only in open-loop mode, which exists
only below 0.55 A. Any tick that could arrive there with a flag set would have cleared it on the
`HOLD` or minimum-load path first.

State 99 is deliberately **not** a clear site. `powerBalance()` does not run once the board has
latched, so the flags freeze at their value on the latching tick, in the same way `fault_flags`
does. That is the reading an operator wants from the observation frame.

## 6. Observability

No wire protocol changes in this round. Three observables carry the clamp state.

- **Bench log record.** `flags` bit 7 is set on a tick where either ceiling binds. This is a
  spare bit in an existing byte, so the record size and bench log format v7 are unchanged and no
  new column appears. It follows the precedent of bit 6 (HIL provenance, firmware version 21).
- **HIL observation frame.** Aux byte (offset 4) bit 4 mirrors the fuel-cell clamp and bit 5 the
  battery clamp. These are spare bits in an existing byte; `HIL_OUTPUT_SIZE` stays 18 and the
  checksum span is unchanged. A host that does not know the bits masks them off as before.
- **State-98 `'S'` dump.** A `share I-ceiling:` line prints both flags, both ceilings, both fault
  limits, the effective setpoint and the two commanded channel currents.

The clamp is a reference-side bound, so a decoded run cannot distinguish "the governor held the
fuel cell at 1.25 A" from "the load happened to stop there" out of the logged currents alone.
These three observables are the only evidence that the mechanism acted.

### 6.1 Why `switch_state` was not used

The 58-byte version 4 telemetry packet has two free bits in `switch_state` (0x40 and 0x80). They
are deliberately left free. `switch_state` is the topology word the plant simulator solves the
electrical network from, and the campaign records compare its numeric value across runs. A
non-switch semantic in that byte would perturb that reading during the campaign this firmware is
flashed for. Exposing the clamp to the Raspberry Pi is a protocol-bump follow-up, to be done
through the `protocol-bump` procedure with the bridge updated in lockstep.

## 7. Bit-identity below the ceilings

When neither ceiling is exceeded, no arithmetic touches the setpoint: the clamp function returns
its argument unmodified. Firmware version 26 is therefore bit-identical to firmware version 25 on
any stimulus whose commanded channel currents stay under 1.25 A and 2.70 A respectively. This is
asserted in the host suite by running an identical fixture twice and comparing the
digital-to-analogue converter codes, and by confirming the reference still converges exactly on
the commanded setpoint.

## 8. Validation

### 8.1 Host-native tests

Thirteen test groups were added. They cover:

- the constants, and their relation to the two fault limits;
- the reachability threshold, pinned at 1.55 A analytic with first engagement in [1.55, 1.60] A,
  including the inert single-source fuel-cell-charge case at 1.40 A;
- inertness and digital-to-analogue converter code reproducibility below the ceilings;
- the fuel-cell clamp binding and holding the commanded current at the ceiling across a demand
  step, with the increase going to the battery;
- hysteretic release;
- the battery clamp, and the infeasible-pair priority;
- the droop-band constraint, and the absence of any cutoff;
- non-interference with the minority-current clip;
- suppression under a deferred cut;
- open-loop `HOLD` and `FEEDFORWARD` behaviour;
- that `FAULT_OC_FC` still latches on a single-sourced overload despite the clamp;
- the clamp state being cleared on both exits to Idle, and deliberately frozen in State 99;
- the sustained clamped regime described in section 8.5;
- the three observability sites, including the bench-log bit on a written record and that
  `switch_state` is unchanged.

Counts after this round: 3926 production, 175 bench, 4408 HIL.

Three pre-existing slew fixtures were re-pointed from 4.0 A of total to 1.5 A or 2.0 A. Their
stated intent is that the governor is a no-op at their operating point. That stopped being true
once the ceilings existed. At the new totals both the minority clip and the ceiling clamp are
inert, so those tests measure the slew behaviour they were written to measure.

### 8.2 What can and cannot be validated on the existing stimulus set

**Nothing on the registered set exercises this feature.** Section 4.1.1 gives the reason: the
clamp needs more than 1.55 A of two-source total, and every overcurrent-class fuel-cell excursion
on the board is a single-source fuel-cell-charge window in which the clamp is structurally inert.
The following are therefore **expected to be unchanged**, and a change in any of them is a
finding rather than a success:

- `ems-ftp75-socband`, peak `I_fc` 1.1370 A;
- `ems-sdp-alpha-cal`, peak `I_fc` 1.1863 A;
- `ems-sdp-cross`, peak `I_fc` 1.1920 A — the closest to the ceiling, with 0.058 A of headroom;
- `charge-cruise`, which reaches the overcurrent condition single-source and is discussed in
  section 8.7.

Validation requires a deliberately constructed two-source high-total run. Two are specified
below: a bench run that can be performed tonight, and a HIL scenario for the tools round.

#### 8.2.1 Bench run, State 98

The `W` command runs the current-mode combined profile: a 16-region, 40 s table that sweeps the
commanded motor current against the power-share setpoint, with the share axis clipped to
`[b, 1-b]` after interpolation. It uses the State-98 motor conventions, so no velocity-chain
calibration is required.

    W 4.0 0.15

- `Imax` = 4.0 A of commanded motor current. With the housekeeping load this drives the
  two-source total through roughly 1.6 A to 2.5 A in the high-current regions, which brackets the
  1.55 A reachability threshold from both sides within one run.
- `b` = 0.15 clips the share axis to `[0.15, 0.85]`, so the profile's high-share regions command
  the most fuel-cell-biased split the droop band admits. That is the condition under which the
  ceiling is reachable at the lowest total.

Expected clamp windows: the regions where the commanded share is above roughly 0.6 **and** the
total is above 1.6 A. Below either threshold the run must be indistinguishable from firmware
version 25.

#### 8.2.2 Proposed HIL scenario, for the tools round

A two-source high-total cruise. Sketch, for the tools round to register properly:

- both source paths open, no charger path, so the total is genuinely two-source;
- an auxiliary preload plus a steady drive command sized to hold the total in the 1.8 A to 2.4 A
  band for at least 10 s, which is well clear of the 1.55 A threshold;
- a commanded share of 0.75, high enough that the unclamped fuel-cell demand is 1.35 A to 1.80 A,
  above the 1.25 A ceiling by a margin larger than the measurement noise;
- a second phase at a commanded share of 0.40 at the same total, where the unclamped demand is
  0.72 A to 0.96 A, to give an in-run release and a same-run negative control.

This scenario does not exist yet. Registering it is a tools-round item; see section 9.

### 8.3 Acceptance criteria

Per clamp window, over the ticks where the clamp flag is set:

1. `I_fc` lies in **[1.20, 1.30] A**, the ceiling plus or minus the 0.05 A hysteresis band. The
   window is measured from the first flagged tick plus 50 ms of settling, to the last flagged
   tick, so the reference slew is excluded from the statistic.
2. `I_batt` closes the balance to within **0.10 A**. The quantity `|I_tot - I_fc - I_batt|` must
   stay under that bound over the same window, which confirms the current the fuel cell did not
   supply actually went to the battery.
3. No `sw_ring` event, no channel cutoff, and both `FC_BUS_ENABLE` and `BT_BUS_ENABLE` high for
   the whole window. The clamp must never open a bus switch.
4. `I_fc` never exceeds `LIMIT_I_FC_MAX` = 1.4 A, and no `OC_FC` latch occurs in the window.

The observability bits are **manual observables this round**. The HIL suite has no named mask for
aux bits 4 and 5, and the bench-log decoder has no helper for `flags` bit 7. Both must be read by
hand, or by an ad-hoc script, until the tools round lands the two decoders listed in section 9.

The State-98 `'O'` one-shot open-loop droop write **bypasses the clamp**, in the same way it
already bypasses the minority-current clip and the slew limiter. It is a deliberate operator
action and lands exactly where commanded in one call. An `'O'` write is therefore not a test of
the governor, and a governor test must not be built on one.

### 8.4 Bench procedure, State 98

1. Enter State 98 with `T` from State 1 and confirm `MOT_PWR_ENABLE` is high.
2. Run `S` and confirm the `share I-ceiling:` line reports both clamps off, with the two
   commanded currents consistent with the measured split.
3. Run `W 4.0 0.15` as specified in section 8.2.1.
4. Run `S` during a high-current, high-share region and confirm the fuel-cell clamp reads `CLAMP`.
5. Confirm from the bench log that `flags` bit 7 is set exactly over the ticks where the commanded
   current is at the ceiling, and that `I_fc` satisfies the criteria in section 8.3.
6. Re-run at `W 1.5 0.15`, which holds the total below the reachability threshold, and confirm the
   clamp never engages and the run reproduces the firmware version 25 droop codes.

### 8.5 Residual: the sustained clamped regime

A new steady state exists that firmware version 25 never reached. At 4.0 A of total with a
commanded share of 0.60, the clamp pulls the reference well below the measured share, the
controller winds the commanded ratio down onto `DROOP_R_MIN`, and `applyShareRatio()` refuses the
resulting fuel-cell cut on load on **every tick**.

The regime is benign. No cut occurs, `FC_BUS_ENABLE` stays high, no controller isolation is
claimed, droop authority stays live, and the board does not fault. The cost is that
`shareCutRefusedLoad` grows without bound for as long as the regime lasts, so that counter can no
longer be read as evidence that a rare refusal happened. A host test asserts the benign
properties: no cut, both bus switches high, no fault, and the applied ratio pinned at
`DROOP_R_MIN`.

### 8.6 A commanded share step during a rising total

Campaign E (`hil_report_20260903_031220`) produced the first hardware measurement of this
governor, and the `fw26-clamp-sweep` leg latched `FAULT_OC_FC` at t = 38.029241 s with a
fuel-cell current of 1.4890 A. The board behaved as designed. This section states the regime the
design record did not predict, because section 5 treats the commanded share and the load as
independent inputs and they are not.

The stimulus stepped both inputs upward in one command packet: the velocity setpoint from 2.5 m/s
to 3.0 m/s, which railed the drive controller at its 12 A current clamp and moved the two-source
total from 1.8418 A to 2.9895 A, and the commanded share from 0.40 to 0.84. The clamp engaged on
the first tick that carried the new setpoint, so there was no engagement delay. At the latch tick
the governor's filtered total read 2.2244 A against a true 2.9895 A, an under-read of 25.6 %,
against a design headroom of `LIMIT_I_FC_MAX - SHARE_GOV_I_FC_CEIL_A` = 0.15 A = 12 % of the
ceiling. The +0.2390 A error decomposes exactly: the filter under-read contributes +0.4298 A and
the plant lagging the reference contributes -0.1910 A.

#### 8.6.1 The governing comparison is a race

Two clocks run from the command edge, and the fuel cell is protected only if the second finishes
first.

The **slew-limited reference** crosses the safe delivered share `LIMIT_I_FC_MAX / I_tot,new` in

    (LIMIT_I_FC_MAX / I_tot,new - s_prev) / DROOP_RATIO_SLEW_PER_TICK    ticks.

The **load filter** makes the clamp bind only after the filtered total exceeds
`SHARE_GOV_I_FC_CEIL_A / s_new`, which takes

    ln((I_new - I_new * SHARE_GOV_I_FC_CEIL_A / LIMIT_I_FC_MAX) / (I_new - I_old))
    / ln(1 - SHARE_GOV_FILT_ALPHA)                                       ticks.

At the measured operating point the first is 4.3 ticks and the second is 24.9 ticks, a factor
of 5.8 (24.9 / 4.3) short. The clamp cannot win that race.

A necessary condition follows. The commanded fuel-cell demand can reach `LIMIT_I_FC_MAX` only
where the droop band itself allows it, so no share step can produce `OC_FC` below

    I_tot > LIMIT_I_FC_MAX / DROOP_R_MAX = 1.4 / 0.85 = 1.647 A       (two-source).

No registered energy-management stimulus exceeds 1.4714 A, which is `ems-mpc`'s peak, so the
margin on the current stimulus set is 10.7 %. That is a statement about the stimuli, not a
structural guarantee.

#### 8.6.2 The three controls, measured in one campaign

| stimulus | what steps | total at the step | peak `I_fc` | outcome |
|:--|:--|--:|--:|:--|
| `fw26-clamp-cruise`, t = 8.0 s | share 0.50 -> 0.75 | settled 2.0007 A | 1.2502 A | 0.016 % overshoot, 35 ms settling |
| `fw26-clamp-sweep`, regions 1->2 and 3->4 | load only, share already 0.84 | rising | 1.2811 / 1.2954 A | clamp catches it, 7.5 % clear of the limit |
| `ems-y-b30-v3`, t = 27.011 s | share 0.35 -> 0.65 while the load FALLS | falling | 0.6505 A | the filter over-reads, so the clamp is conservative |
| `fw26-clamp-sweep`, region 5->6 | share 0.40 -> 0.84 AND load up | rising 1.84 -> 2.99 A | 1.4890 A | `OC_FC` latch |

A commanded share step is therefore safe at a settled total and unsafe during a rising one. Each
error alone is contained; the two add.

#### 8.6.3 Ruling: the stimulus must not create the condition

Closing the race in firmware would require `SHARE_GOV_FILT_ALPHA` at or above approximately 0.25,
or a share slew at or below 0.0027 per tick, which is one seventh of the shipped value. Both were
rejected by the operator's design-intent ruling: a faster filter surrenders the noise immunity the
governor's approximately 20 ms averaging exists for, a slower slew makes every commanded share
change sluggish, and `OC_FC` in this regime is the intended feedback. The firmware is unchanged.

The obligations fall on the stimulus and on the energy-management strategies instead.

- The `fw26-clamp-sweep` table now carries an unscored bridging sub-region at every boundary that
  would move both axes upward, at `hil_plant_sim.FW26_CLAMP_SWEEP_BRIDGE_S` = 1.5 s. The velocity
  axis steps first, at the previous region's commanded share, and the share axis steps once the
  drive controller's own current rail has cleared.
- **EMS rule.** No strategy may command an upward share step in the same decision as an upward
  demand step, wherever the resulting two-source total exceeds 1.65 A. The model-predictive
  controller's ladder moves one rung of 0.0875 per decision, so the rule constrains it only where
  a demand step lands on the same decision boundary; see
  `docs/modeling/mpc_design_20260902_nonlinearities.md`. **IMPLEMENTED 2026-09-03** (operator
  ruling) as a block-0 candidate-admissibility constraint in `tools/mpc_ems.py`, named
  `SHARE_STEP_GUARD_I_TOT_A`; inert on all six registered MPC scenarios, whose largest predicted
  two-source total is `ems-mpc`'s 1.4714 A. The design record's "Implemented, 2026-09-03" section
  carries the definition of "rising", the plan-invariance table and the observability contract.

#### 8.6.4 First calibration of the clamp

Every figure below is from campaign E and supersedes the walked values wherever the two disagree.

| quantity | measured | note |
|:--|:--|:--|
| engagement latency | 3.3 to 17.7 ms | Pi-cadence-limited at 48.7 Hz, not clamp-limited; the clamp engages on the first tick that carries the new setpoint |
| reference slew to the bound | about 6 ticks | `DROOP_RATIO_SLEW_PER_TICK` 0.02 |
| settling | 35 ms | `fw26-clamp-cruise`, at a settled total |
| overshoot, settled total | 0.016 % | 1.2502 A against the 1.2500 A ceiling |
| overshoot, upward load step at a clamped share | +0.031 to +0.045 A | sweep regions 1->2 and 3->4 |
| held current, phase A | 1.2499 to 1.2502 A | duty 15500 of 15500 ticks |
| battery, phase A | 0.7505 to 0.7508 A | balance closure at or below 0.0008 A |
| release, phase B | 0 clamped ticks, `I_fc` 0.8003 A | the same-run negative control |
| battery ceiling | 0 ticks | never exercised, as designed |

#### 8.6.5 The joint-transient leg, designed 2026-09-03 and registered the same day

**Status.** Registered as `fw26-clamp-joint` on 2026-09-03 (operator ruling), in the default
suite plan. The history below is kept as written, because it is the derivation of the
operating point; what changed is that the leg exists.

A third scenario was designed to pin the joint transient as a number at a total the fault limit
cannot be reached from: motor-free, with the auxiliary preload stepping upward at the same instant
as a commanded share step of 0.40 to 0.84. It was not registered at first, and the reason was a
result rather than a deferral.

The proposed operating point, a step from 1.20 A to 1.55 A, **does not exercise the clamp at all**.
The reachability threshold is `SHARE_GOV_I_FC_CEIL_A + SHARE_MINORITY_I_MIN_A` = 1.55 A exactly, so
at that total the minority-current clip bounds the commandable fuel-cell share at
`1 - 0.30/1.55` = 0.8065 and the delivered current at 1.2500 A. Walked through
`tools/governor_model.py`, the clamp engages on **zero** ticks and the peak is 1.2500 A with no
overshoot. The "worst case at the band rail, 0.85 x 1.55 = 1.32 A" reasoning that produced the
figure omits the clip, and 0.85 is not commandable at that total.

The walk also identifies what the leg would actually measure. During the transient the peak
delivered current is set by the **minority clip**, not by the ceiling: the clip rail is
`I_tot - SHARE_MINORITY_I_MIN_A`, the load filter has not yet seen the new total, and the clamp
therefore binds only after the filter catches up. The joint overshoot is bounded by

    (I_tot - 0.30) - SHARE_GOV_I_FC_CEIL_A ,

which is a structural statement worth pinning. Walked peaks against a 1.20 A pre-step total, at a
share step of 0.40 to 0.84:

| step total | walked peak `I_fc` | clamp ticks | clip rail |
|--:|--:|--:|--:|
| 1.55 A | 1.2500 A | 0 | 1.2500 A |
| 1.60 A | 1.2900 A | 5960 | 1.3000 A |
| 1.62 A | 1.3062 A | 5966 | 1.3200 A |
| 1.65 A | 1.3303 A | 5971 | 1.3500 A |

Re-walked on 2026-09-03 under the **corrected split law** (rho 0.9434 plus the 0.033 ohm series
floor, `docs/modeling/governor_split_law_20260903.md`), at the shipped 1.65 A operating point:

| law | walked peak `I_fc` | first engagement | post-step clamp duty | settled `I_fc` / `I_batt` | settled MDAC (fc, bt) |
|:--|--:|--:|--:|--:|--:|
| pre-correction | 1.3303 A | +29 ms | 0.9976 | 1.2500 / 0.4000 A | (4906, 6560) |
| corrected | 1.3303 A | +29 ms | 0.9976 | 1.2500 / 0.4000 A | (4906, 6560) |

The two rows are identical to six digits, and that is a result rather than a coincidence: the
firmware pins the applied **ratio** on its own rails, so the split law only re-inverts the ratio
that delivers a current it does not move. The clamp-absent arm, walked the same way with the
ceilings pinned out of reach, settles at 1.3500 A with `I_batt` 0.3000 A and MDAC (4843, 7413) --
which is what makes the leg a fw v25 / fw v26 discriminator rather than a description of the plant.

The commander-cadence skew was walked as well. The share step arrives on the Pi's own ~50 Hz packet
while the auxiliary load steps at 1 kHz, so the two land up to one commander period apart in either
order. At +/- 20 ms the peak is 1.3303 A (share first, or simultaneous) or 1.2931 A (load first):
the order cannot make it worse than simultaneous, because the peak is set by the rail crossing and
the reference has reached 0.84 long before the filtered total passes 1.55 A.

As registered, the leg is 30 s and motor-free. The auxiliary preload ramps to 1.05 A from t = 4 s
and **steps** to 1.50 A at t = 16.0 s, at the same instant the Pi timeline commands the share step;
the stepped load needs the `aux_preload_step` scenario key, which the generic `aux_preload_a`
cannot express. `FAULT_EXPECTATIONS["fw26-clamp-joint"]` carries twenty-two walked specs behind a
`provisional_note`, including the 1.36 A acceptance bound on the transient peak, a settled band that
refuses the 1.3500 A clamp-absent point, and the two settled droop-code pins. Nothing in the entry
has been scored on the board; the first campaign that runs the leg re-derives all of it.

**The shippable design is a step to 1.65 A**, which is 0.10 A above the reachability threshold, or
twice `SHARE_GOV_CEIL_HYST_A`, so a small modelling error cannot make the leg inert. Its acceptance
bound is 1.36 A, which is 0.4 % above the walk and 2.9 % under `LIMIT_I_FC_MAX`. The leg is
motor-free, so there is no drive rail and the walk carries none of the modelling uncertainty the
sweep's boundaries do. Registering it needed a stepped auxiliary-load branch in `apply_scenario()`,
which the generic `aux_preload_a` key cannot express; that branch is the `aux_preload_step`
scenario key, shipped 2026-09-03.

### 8.7 Open items

- `TODO(calibrate)` at `SHARE_GOV_I_FC_CEIL_A`: the 0.15 A margin is argued, not measured, and
  the headroom over the measured peak is only 0.058 A.
- The battery ceiling has never been exercised on hardware and is not expected to bind. The 4.25 A
  crossing at which the commanded battery current passes `LIMIT_I_BT_MAX` has never been reached.
- `FAULT_EXPECTATIONS["charge-cruise"]` currently carries `require: FAULT_OC_FC`. That scenario is
  single-source, so the clamp cannot change its outcome and the expectation remains correct as
  written. It nonetheless needs **operator re-adjudication**: the registered intent of a scenario
  that requires an overcurrent latch should be revisited now that a mechanism exists whose purpose
  is to prevent that class of latch elsewhere. This is a decision, not a defect.
- The interaction between the clamp and the charger window is unmodelled. The charger's bus draw
  is part of the total the clamp bounds, so a clamped fuel cell during a charge window shifts the
  charging energy source toward the battery. The energy-management tooling must learn the clamp
  before the frontier numbers are read again; see section 9.

## 9. Follow-ups for the tooling side

These are not part of this firmware round.

- `tools/governor_model.py` must gain the ceiling clamp, in the same order the firmware applies
  it, or the offline governor will disagree with the board wherever the clamp binds.
- `tools/ems_walk.py` must apply the clamped share rather than the commanded share, or every walk
  above the ceiling will over-credit the fuel cell.
- The dynamic-programming charge mask carries a delivered-share semantic that becomes incorrect
  when the clamp binds: the delivered share is no longer the commanded share.
- The model-predictive controller's stage surrogate predicts a share the board may now clamp,
  which is a new component of `mpc_share_pred_err`.
- The HIL suite must learn the aux-byte bits 4 and 5 as named masks, so an `aux_bit` check can
  score the clamp. Until it does, the HIL observable is manual.
- The bench-log decoder, `tools/decode_benchlog.py`, must learn `flags` bit 7 the way it already
  knows bits 4 to 6, so a decoded run carries the clamp in its `flags` column. Until it does, the
  bench-log observable is manual.
- A two-source high-total scenario must be registered, per the sketch in section 8.2.2. Without
  one, no campaign can exercise this feature at all.
- `_ALPHA_FC_CEIL` in `tools/run_hil_suite.py` is 1.28 A. That now exceeds the largest fuel-cell
  current the board can command in the clamped regime, 1.25 A, so a check written against it can
  no longer fail for the reason it was written to catch. It needs re-pointing at
  `SHARE_GOV_I_FC_CEIL_A` or re-adjudicating.
- `FAULT_EXPECTATIONS["charge-cruise"]` requires `FAULT_OC_FC`. See section 8.7: correct as
  written, but flagged for operator re-adjudication.
- The Raspberry Pi bridge exposure of the clamp requires a telemetry protocol bump, using the two
  free `switch_state` bits.
