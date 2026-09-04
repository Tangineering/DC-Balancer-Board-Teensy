# fw v27 — The minority-current clip on the open-loop feedforward path

## 1. Purpose and scope

This document is the design record for firmware version 27. Firmware version 27 applies the share
governor's minority-current clip to the **open-loop feedforward submode**, in a **relaxing** form.
The change makes the open-loop-to-closed-loop handover continuous in the reference **magnitude**,
which firmware version 6 did not achieve by bounding the reference **rate**.

The scope is one mechanism. No pin, protocol, fault limit, controller coefficient, state-machine
structure, or charger behaviour changes. The telemetry packet stays at version 4 and 58 bytes, the
command packet stays at 22 bytes, the bench-log record stays at BLG version 7, and the
hardware-in-the-loop frames stay at 40 and 18 bytes. The share PI and the Youla share controller,
their gains and their `sampleTime` gating are untouched.

The change is defined by `WORK_QUEUE.md` section 7c item 3 and by
`docs/modeling/low_current_share_stability_20260903.md` section 4.4.

## 2. The evidence

Table 1 states the two dropouts of the firmware version 6 ladder, taken from
`docs/share_sweep_whitepaper/main.tex`.

Table 1. The two dropouts observed anywhere in the firmware version 6 campaign.

| Run | Setpoint | Position | Event | Bus minimum |
|---|---|---|---|---|
| `TP0115` | 0.85 (`DROOP_R_MAX`) | open-to-closed handover | 5.9 ms total source dropout | 12.19 V |
| `TP0105` | 0.15 (`DROOP_R_MIN`) | open-to-closed handover | fuel-cell-only dropout | 15.89 V |

Both occurred at the handover and both at an exact band edge. Every run crosses into closed loop
at the same 0.6 A of total, where the 0.30 A conduction floor demands half the total current from a
channel the open-loop feedforward had been running at 61 mA. The discriminator is monotonic in the
setpoint: the measured minority current in the 50 ms before the crossing is 0.061 A at a setpoint of
0.85, 0.072 A at 0.83, and 0.179 A at 0.65.

The whitepaper states the conclusion that this round acts on: firmware version 6 slewed the
reference rate, but the exposure is the reference magnitude. A swing of 0.42 in commanded share,
applied at 0.6 A of total, opens both channels however slowly it is applied.

`docs/modeling/low_current_share_stability_step0_20260903.md` adds a constraint on any fix. Three of
six recorded first-passage dropouts sit at 66 % to 94 % of the ratio slew limiter's ceiling, that is
they are slew-driven. A clip that introduces a fast reference movement of its own would therefore
trade one failure mode for another. The form adopted below introduces **no** movement.

## 3. The mechanism

`shareFeedforwardClipTarget(sp, prevRatio)` returns the reference the feedforward branch aims at on
this tick. It computes the same band the closed-loop path uses, on the same filtered total
`share_govTotAFilt` (the governor's approximately 20 ms exponential moving average, never a raw
analog-to-digital read):

    lo = SHARE_MINORITY_I_MIN_A / I_tot_filt
    hi = 1 - lo

and returns `constrain(sp, lo, hi)` when `lo < hi`, and `prevRatio` when it does not. The caller
passes `droopSlew_prev`, the ratio physically on the multiplying digital-to-analog converters, as
`prevRatio`, and puts the result through the tick's slew ceiling `shareSlewStepThisTick` exactly as
before. The clip therefore cannot step the reference under any input.

### 3.1 Why an empty band is a hold, and not a collapse to 0.5

Firmware version 5 deleted the previous collapse-to-0.5 fallback because it ignited the failure it
existed to prevent. Below twice the conduction floor that fallback forced an effective setpoint of
0.5, which at 0.075 A to 0.60 A of filtered total commands 0.038 A to 0.30 A per channel, at or
below the floor it was enforcing, against approximately 20 mV of droop authority. Six runs of the
firmware version 4 sweep source-commutated, collapsed the bus to 7 V to 9 V and latched
`ERR_UV_BUS`; `TP0053` is the representative event. The whitepaper restates that argument as still
sound, which is why firmware version 6 did not clip the feedforward at all.

The relaxing form answers the argument rather than overriding it. What firmware version 5 refuted is
**commanding a move** to a balanced split at a total that cannot carry one. When the band is empty
no split is feasible, so there is no least-bad target to walk toward and every direction of motion
is a commutation the load cannot support. The clip therefore returns the ratio the hardware already
holds: the multiplying digital-to-analog converter codes do not change, the droop gains do not move,
and the tick is a no-op in actuation terms. "Hold what the hardware already has" and "drive the
hardware to 0.5" are different actions, and only the second is `TP0053`.

The distinction is asserted directly in the host suite: `shareFeedforwardClipTarget(0.85, 0.62)`
returns 0.62 at an empty band, not 0.5.

### 3.2 At the shipped constants the clip is always the hold

`SHARE_MINORITY_I_MIN_A` is 0.30 A and the closed-loop entry gate is
`2 * SHARE_MINORITY_I_MIN_A` = 0.60 A of filtered total, tested strictly. Every tick that reaches
the feedforward branch therefore has `share_govTotAFilt` at or below 0.60 A, where the band is
empty, degenerating to the single point 0.5 exactly at 0.60 A. **The relaxing branch is
structurally unreachable through `powerBalance()` today.** It is written anyway, for the same
reason firmware version 26 calls its ceiling clamp on this path: a future retune of either constant
must not silently leave the only writing open-loop path unguarded.

This is stated with the same honesty discipline as the firmware version 26 MED-4 note. The relaxing
branch is covered by direct-call tests only; a test that drives the loop can prove the hold half
alone.

### 3.3 Consequences that are behaviour changes, not side effects

1. **The two open-loop submodes now actuate identically below the gate, whenever both channels are
   on the bus.** Both hold. They still differ in bookkeeping, and in that FEEDFORWARD keeps calling
   `applyShareRatio()`, which is where the guarded channel re-entry lives (firmware version 5
   exception (a)). A hold that never called it would strand an isolated channel off the bus for the
   rest of the run. Section 3.4 states why calling it is necessary but not sufficient.
2. **A setpoint change at low load is deferred, not swallowed.** Firmware version 5 exception (b)
   still fires: a changed setpoint clears `shareClosedLoopRun` and re-arms the feedforward path. The
   clip then holds the ratio until the load can carry the commanded split, at which point the closed
   loop tracks it. The command is honoured late instead of being honoured infeasibly.
3. **The feedforward slew site is inert on every clipped tick.** Its `constrain()` against
   `shareSlewStepThisTick` cannot bind when the target it is given is `droopSlew_prev` itself. It is
   not inert on the bypass path of section 3.4, which is the one remaining firmware-driven source of
   ratio motion below the gate.

### 3.4 The clip is bypassed while a controller-initiated cut is outstanding

The first version of this change fed `shareFeedforwardClipTarget()` on every feedforward tick,
including ticks reached through firmware version 5 exception (a). The review round found that this
defeats the exception those ticks fall through for.

`applyShareRatio()` re-closes an isolated channel on the ratio it is handed: fuel cell at
`r >= DROOP_R_MIN + SHARE_CUTOFF_HYST` (0.16), battery at `r <= DROOP_R_MAX - SHARE_CUTOFF_HYST`
(0.84). While a channel is isolated the function returns before it records `droopSlew_prev`, so
`droopSlew_prev` is frozen at the last ratio physically written. In the converge-to-a-rail case that
value is exactly `DROOP_R_MIN` (or `DROOP_R_MAX`), one hysteresis width short of re-entry. The
clip's held output is `droopSlew_prev`. A clip applied there therefore proposes the frozen rail on
every tick, forever, and the cut channel stays off the bus for the whole sub-0.60 A window. Firmware
version 26 fed the raw setpoint here, which walks the proposed ratio off the rail and re-enters on
the next tick.

The fix is a bypass. While `shareIsoFC || shareIsoBT` the raw setpoint is fed forward,
bit-identically to firmware version 26. Nothing is lost, because an isolated tick writes no
multiplying digital-to-analog converter words at all, so there is no reference for the clip to
protect. The clip resumes on the first tick after the re-entry, holding from the value that re-entry
actually wrote. `test_fw27_iso_bypass_preserves_reentry` pins both directions.

### 3.5 `share_actedSp` records actuation, not arrival

`share_actedSp` is read by exactly one test, the HOLD branch's `spChanged`, whose question is
whether a setpoint has already been actuated. A held feedforward tick reaches no multiplying
digital-to-analog converter, so a record made there answers that question with a yes the hardware
cannot support. It is harmless at present only because a `spChanged` tick clears `shareClosedLoopRun`
and therefore stops the HOLD branch from running at all. However, a future change that re-armed HOLD
without clearing that flag would silently swallow the setpoint change. The record is therefore made
only on a tick whose target differs from `droopSlew_prev`.
`test_fw27_acted_setpoint_records_motion_only` pins both halves.

## 4. The design points

### 4.1 A raw setpoint outside the band while the total rises

The band opens monotonically with the filtered total, so the clipped reference moves outward toward
the raw setpoint as load grows, and reaches it once `I_tot_filt` is at or above
`SHARE_MINORITY_I_MIN_A / min(sp, 1 - sp)`. That movement is bounded by the existing slew limiter,
so the release is rate-bounded and never a step. At the shipped constants the opening happens above
the gate, that is inside closed loop, where the identical band already governs the reference.

### 4.2 Interaction with the deferred-cut path and with single-source commands

A commanded 0.0 or 1.0 is a **cut**, not a share. It is owned by `updateShareSetpointCutoff()`,
which runs at the top of `powerBalance()` and returns before anything else, and by the F1 early
return for an out-of-band setpoint on a release tick. Both precede the clip, so the cut path never
reaches it and cannot be clipped into the band. This is asserted in the suite for both directions
and for the intermediate out-of-band case 0.95.

The firmware version 25 deferred-cut clip and the firmware version 26 ceiling clamp live on the
closed-loop path only. The clip does not interact with either.

### 4.3 Behaviour above the gate

Unchanged, and structurally so: the clip has exactly one call site, inside the open-loop branch, so
no closed-loop tick can reach it. The suite pins a closed-loop trajectory entered directly above the
gate (no feedforward tick runs at all in that fixture), including a clamped point at 3.0 A of total
where the firmware version 26 reference bound is still exactly `SHARE_GOV_I_FC_CEIL_A / I_tot`.

### 4.4 The firmware version 26 ceilings on this path

They remain applied on the feedforward path, after the new clip, in the firmware's global order
(minority clip, then ceilings, then band, then slew). Removing the call was considered, on the
ground that the ceilings are reference-side bounds for the closed loop. It was rejected: the call is
arithmetically inert below the gate (no channel can draw 1.25 A out of a 0.60 A total), so removing
it changes no behaviour, and firmware version 26 placed it there deliberately as a guard against a
future retune. Deleting a shipped guard for a documentation-only gain is the wrong trade.

## 5. Observability

No wire change, and no new state. The clip is a pure function of `share_govTotAFilt` and the
setpoint, so there is nothing to reset and nothing that can publish a stale value.

- The State-98 `S` dump gains a `share ff clip:` line reporting either `EMPTY (hold at r=...)` or
  the open band, with `SHARE_MINORITY_I_MIN_A`.
- In a bench log the clip is **reconstructible offline**, unlike the firmware version 26 ceiling
  clamp, which needed a log bit: `flags` bit 2 clear and bit 3 clear identify the feedforward
  submode, and `share_sp` against the applied ratio recovered from `gFC`/`gBT` gives the raw
  setpoint against what was actuated. A held tick is a submode-FEEDFORWARD tick whose applied ratio
  differs from `share_sp` and does not move.
- No bench-log flag bit was taken because the `flags` byte has none free (bits 0 to 7 are all
  allocated, bit 7 by firmware version 26). Hardware-in-the-loop auxiliary-byte bits 6 and 7 are
  free but were left alone: the observable is reconstructible without them, and spending a wire bit
  on it would require a change in the host tooling, which is out of scope for this round.

## 6. Validation

### 6.1 Host-native tests

Four new groups, in `test/test_main.cpp`:

- `test_fw27_feedforward_handover_continuity` — a rising total crosses the gate with a raw setpoint
  of 0.15 and of 0.85, between 0.55 A and 0.70 A of total. It asserts that the feedforward never
  walks out to the band edge, that no tick anywhere across the crossing moves the applied ratio by
  more than one slew step, that the multiplying digital-to-analog converter code written on the
  first closed-loop tick is within one slew step of the code the feedforward left, and that no
  channel is off the bus at the crossing tick. This is the `TP0105`/`TP0115` mechanism as a test.
- `test_fw27_feedforward_clip_relaxes` — direct-call coverage of the relaxing branch (empty band
  returns the held ratio and not 0.5; an out-of-band setpoint clips to the band edge; an in-band
  setpoint passes through byte-identically; the target is monotone non-decreasing in the total and
  reaches the raw setpoint), plus a loop-level 400-tick hold at 0.30 A of total from an off-centre
  seeded split, which separates "held" from "collapsed to 0.5".
- `test_fw27_feedforward_clip_does_not_touch_cuts` — 0.0 and 1.0 below the gate still take the cut
  path and still latch `shareSpCutFC`/`shareSpCutBT`; an out-of-band 0.95 is never actuated.
- `test_fw27_closed_loop_unchanged_above_the_gate` — a closed-loop trajectory entered directly above
  the gate, including a firmware version 26 clamped point.

Existing fixtures that used the feedforward walk were re-pointed rather than deleted. Two classes:

1. Fixtures whose subject was the walk itself (G1/G2, T4, governor C, G6 and the effective-setpoint
   slew setups, G7, the firmware version 26 open-loop case, the minimum-load boundary) now assert
   the hold. G7 needed a new discriminator between the FEEDFORWARD and HOLD branches, because the
   applied ratio no longer separates them. It uses the serial-peripheral-interface traffic, because
   FEEDFORWARD re-writes the multiplying digital-to-analog converters through `applyShareRatio()`
   and HOLD returns before writing anything. `share_actedSp` served this purpose in the first
   version of the round and is no longer valid for it, per section 3.5.
2. Firmware version 19 fixtures that used the walk merely as a deterministic, controller-free source
   of ratio motion for the motion-gated dwell logic (the `TP0201` static-hold regression, the burn
   test, the live-stretch test, the mode-name test) now drive that motion through
   `applyShareRatio()` directly, via the `openLoopWalkTick()` helper. This is legitimate rather than
   a workaround: `updateShareSlewMode()` reads motion from `droopSlew_prev`, the multiplying
   digital-to-analog converter truth, and the firmware states explicitly that motion from the
   one-shot paths counts. The dwell logic under test is unchanged by this round.

`test_share_handoff_slew_openloop_dark_channel` lost its original subject, because the feedforward
slew site is inert on a clipped tick. It was rewritten to assert that inertness and that the
conduction-aware machinery still runs on open-loop ticks. The handoff ceiling remains covered at the
two closed-loop sites by `test_share_handoff_slew_tp0201_regression` and
`test_share_handoff_slew_reference_actuation_agreement`.

The open-loop site is not unreachable, however. The bypass of section 3.4 restores it. During a cut
the raw setpoint is fed forward, and a cut channel reads dark within about thirty ticks, so the site
selects `DROOP_RATIO_SLEW_HANDOFF_PER_TICK` and the re-entry write is made at that reduced ceiling.
`test_fw27_openloop_handoff_slew_via_iso_bypass` drives it there from a seed one handoff step under
the re-entry threshold, and bounds the motion it produces. That is the only firmware-driven ratio
motion left on the open-loop path.

The review round added three fixtures: `test_fw27_iso_bypass_preserves_reentry`,
`test_fw27_acted_setpoint_records_motion_only` and
`test_fw27_openloop_handoff_slew_via_iso_bypass`.

Tallies: 4024 production, 175 bench, 4506 hardware-in-the-loop, zero warnings on all three builds.
The pre-change baseline was 3961, 175, 4443; the figures before the review round were 3998, 175,
4480.

### 6.2 What the hardware-in-the-loop plant can and cannot validate

It can validate the **commanded** side completely: which submode runs, what the reference is, what
the applied ratio is, that the handover carries no jump, and that a 0.0 or 1.0 command still cuts.
The board executes the real governor, so a scenario that walks a load up through 0.60 A of total
with a band-edge setpoint exercises the whole mechanism.

It cannot validate the **physics the change exists for**. The dropouts are an analog source
commutation across an RT1987 ideal-diode handoff, and the plant model has no pulse-frequency-
modulation model and no diode-recovery dynamics: a channel commanded to 61 mA in the model simply
carries 61 mA. `docs/HIL_PLANT.md` is explicit that the light-load conduction behaviour is not
modelled. So a hardware-in-the-loop campaign can show that the extreme pre-crossing split is gone
and that nothing else regressed; it cannot show that the dropout is gone. Only the bench can, by
repeating the firmware version 6 ladder at the two band edges.

### 6.3 What the first campaign should look at

1. The open-loop occupancy and what the split does during it. Every leg that spends time below
   0.60 A of total should now show a frozen applied ratio there, with `share_sp` visibly different.
   A moving ratio in the feedforward submode is a defect.
2. The handover ticks. Sort by the mode-flag transition in `flags` bits 2 and 3, and check that the
   applied-ratio step across each transition is at or below `DROOP_RATIO_SLEW_PER_TICK`.
3. The energy-management legs' equivalent-hydrogen figures against campaign F, and **expect them to
   move**. This is not a small effect. `docs/HIL_PLANT.md` records the FTP-75 legs at preload 0 as
   **9.71 % open-loop hold, 57.12 % feedforward, 33.17 % closed** in the walk: on more than half of
   an FTP-75 leg the commanded split was being fed forward, and it is now held instead. The same
   document's measured open-loop census on `ems-y-b00-v3` (campaign `hil_report_20260902_011926`) —
   356 open-loop ticks writing the multiplying digital-to-analog converters in 8 episodes, the
   largest walking the command 0.650 to 0.152 over 174 ticks — is exactly the motion firmware
   version 27 removes. Every anchor with open-loop occupancy is a re-pin, and the offline walk in
   `tools/` does not yet model the clip, so walk-versus-board deviations on those legs are expected
   until it does. Treat the first campaign as an era boundary, not as a regression check.
4. The `fw26-clamp-*` legs, which must be bit-identical: they run well above the gate.

## 7. Residuals and open items

1. **A split parked outside the feasible band by another writer is now stickier.** Before firmware
   version 27, a feedforward tick at low load would walk an extreme split back toward a less extreme
   commanded one; it now holds. The only writers that can create such a split are the closed loop
   (after which the HOLD branch owns it, with exactly this residual, since firmware version 5), the
   State-98 `O` one-shot, and the run-completion restore, which writes the benign mid-band 0.5. In
   production State 2 there is no such writer other than the closed loop, so the residual is
   bench-only in practice. It is accepted on the firmware version 5 evidence: walking an extreme
   split toward 0.5 at very low current is precisely what collapsed the bus in six runs.
2. **The relaxing branch has direct-call coverage only**, per section 3.2.
3. **The gate itself is unchanged.** Section 4.4 of the exploration note argues that making the
   handover continuous is a prerequisite for moving the gate, not a substitute for it. Whitepaper
   item 17 argues for raising the engagement point; lowering it needs the load-scheduled droop scale
   or the margin-referred governor first. Neither is in this round.
4. **Documents and tooling this round did not own, and which are now stale.** They are listed here
   rather than edited, because the round's scope was the firmware.
   - `docs/HIL_PLANT.md`, the FEEDFORWARD paragraph of the share-loop section: it states that the
     raw setpoint is fed forward through the slew limiter and that `applyShareRatio()` writes the
     multiplying digital-to-analog converters. From firmware version 27 the reference is clipped
     first, and below the gate that means it is held. The measured open-loop census quoted there
     belongs to the firmware version 21 to 26 era.
   - The offline governor walk (`tools/governor_model.py`, `tools/ems_walk.py`) does not model the
     clip, so it will over-state open-loop share motion against the board.
   - The energy-management strategies may command a share the board will now defer at low load.
     That is a strategy-level question for the next tools round, not a firmware one.
5. **Bench gate.** The firmware version 6 ladder at setpoints 0.15 and 0.85, at the same profile,
   is the measurement that closes this change. The acceptance criterion is no source dropout at
   either band edge, with the bus minimum at or above the firmware version 5 figure of 15.75 V.
