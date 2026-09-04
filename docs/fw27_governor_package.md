# fw v27 — The governor package

## 1. Purpose and scope

This document is the design record for firmware version 27. It is written at **revision 2**, which
supersedes revision 1 before any flash. No board has ever run revision 1, so the firmware ledger
carries no revision 1 era and `FW_VERSION` stays 27.

Firmware version 27 changes four things in the power-share governor, and retunes one constant.

1. **The battery-only start.** From a profile start until the share loop first closes, the fuel
   cell is held off the bus and the battery carries the whole load.
2. **The closed-before hold** — revision 1, retained exactly. The open-loop feedforward submode
   clips its reference to the governor's minority-current band, which below the closed-loop gate is
   empty, so the submode holds the ratio the multiplying digital-to-analog converters already carry.
3. **The load-scheduled droop scale.** In closed loop the droop scale `k_d` follows the filtered
   total current, so the droop authority `k_d * I_tot` stops collapsing at light load.
4. **Bench-log format version 8.** The record appends the live `k_d` and the multiplying
   digital-to-analog converter clamp count.

The retuned constant is `SHARE_MINORITY_I_MIN_A`, the light-load conduction floor, which moves from
0.30 A to 0.15 A on the operator's ruling of 2026-09-03.

No pin, telemetry protocol, command packet, fault limit, controller coefficient, state-machine
structure, or charger behaviour changes. The telemetry packet stays at version 4 and 58 bytes, the
command packet stays at 22 bytes, and the hardware-in-the-loop frames stay at 40 and 18 bytes. The
share proportional-integral controller and the Youla share controller, their gains and their
`sampleTime` gating, are untouched.

Sections 2 to 7 are the revision 1 record, unchanged. Sections 8 to 13 are revision 2.

## 2. The evidence

> **Sections 2 to 7 are the revision 1 record, retained verbatim.** They are written at revision
> 1's constants: a conduction floor of 0.30 A, a closed-loop gate of 0.60 A, bench-log format
> version 7, and tallies of 4024, 175 and 4506. Revision 2 changes each of those, and section 8.4
> gives the substitutions. The MECHANISM they describe — the relaxing clip, the empty-band hold,
> the cut-outstanding bypass and the actuation-only record of `share_actedSp` — is unchanged by
> revision 2, except for the walk anchor of section 12.

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

---

# Revision 2

## 8. The conduction floor moves to 0.15 A

### 8.1 The ruling and its arithmetic

The operator ruled on 2026-09-03 that the constant low-current droop authority shall be
`D = k_d * I_tot = 0.30 V` at design scale. With `RE_MAX = K_sns * A_v * RD1/RINJ = 2.0136 ohm`
and a safety factor `SHARE_KD_SAFETY = 0.9`, the schedule of section 10 delivers a constant
authority `RE_MAX * I_min * SHARE_KD_SAFETY`, so the ruling fixes the floor:

    I_min = D / RE_MAX = 0.30 / 2.0136 = 0.149 A   ->  SHARE_MINORITY_I_MIN_A = 0.15 A

The realized constant at the shipped safety factor is `2.0136 * 0.15 * 0.9 = 0.272 V`.

The operator's rationale is recorded verbatim: "Using D=0.30V as the constant bus sag in the low
current region still gives plenty more droop strength and enough of a voltage differential to
ensure conduction when a source re-enters the bus."

### 8.2 Why the bench bracket does not forbid this

Firmware version 4 raised the floor to 0.30 A on a bench bracket: `TP0016` commanded 0.245 A of
minority current and collapsed the bus to 8.2 V; `TP0017` commanded 0.29 A and was clean. The
bracket is (0.245, 0.29] A at one total current.

That bracket was measured at a **fixed** droop scale, `K_DROOP = 0.30 ohm`, where the authority
`k_d * I_tot` collapses with load: 0.18 V at 0.6 A of total. The quantity that failed in `TP0016`
was therefore not the minority current in isolation. Section 4.2 of
`docs/modeling/low_current_share_stability_20260903.md` states the boundary as a bus-versus-
reference margin under 100 mV, and section 2 item 4 of that note records the realized droop as
about one quarter of the design value. The revision 2 schedule holds the authority constant at
0.272 V of design scale for every total below the crossover, which is 1.5 times what the fixed
scale produced at 0.6 A and 6 times what it produced at 0.30 A.

### 8.3 This is a hypothesis, and the plant cannot test it

The claim that conduction margin becomes load-independent once the authority is held constant is
**not measured**. It follows from the droop model, and the model's own realized-authority gap is
open (section 10.5). The hardware-in-the-loop plant cannot falsify it: the high-fidelity engine has
no pulse-frequency-modulation model and no light-load converter branch
(`controller_design/system_model.md` section 6e item 3; `tools/hil_electrical.py` has no light-load
case), so a channel commanded to 0.15 A in the model simply carries 0.15 A.

Only the bench can settle it. The measurement is the two-axis dropout-boundary sweep, per channel
direction, repeated at the **scheduled** droop scale. Until that runs, the floor is an argued value
and this section is the record of that status.

### 8.4 Everything derived from the floor, re-derived

Every downstream quantity is written against the symbol, not a literal, and each moves:

| Quantity | Expression | fw v27 rev 1 | fw v27 rev 2 |
|---|---|---|---|
| Closed-loop entry gate | `2 * I_min` | 0.60 A | 0.30 A |
| Closed-loop exit | `2 * I_min - SHARE_GOV_OL_HYST_A` | 0.55 A | 0.25 A |
| Minority clip band | `[I_min/I_tot, 1 - I_min/I_tot]` | `[0.30/I, ...]` | `[0.15/I, ...]` |
| Droop-scale crossover | `RE_MAX * SAFETY * I_min / K_DROOP` | 1.812 A | 0.906 A |
| Constant authority | `RE_MAX * I_min * SAFETY` | 0.544 V | 0.272 V |
| Ceiling reachability | `max(CEIL/DROOP_R_MAX, CEIL + I_min)` | 1.55 A | 1.471 A |

The hysteresis `SHARE_GOV_OL_HYST_A` is unchanged at 0.05 A, which is now 17 % of the gate rather
than 8 %. The sliver in which the closed-loop clip degenerates to the balanced split therefore
widens in relative terms; it is handled by the pre-existing `if (lo > 0.5f) lo = 0.5f` clamp, and
the fixture that pins that clamp was re-pointed from 0.58 A to 0.29 A of filtered total.

### 8.5 The current-ceiling governor's reachability changes hands

Firmware version 26 bounds the commanded fuel-cell current at `SHARE_GOV_I_FC_CEIL_A = 1.25 A`. The
minority clip runs first, so the largest commandable fuel-cell current is
`min(DROOP_R_MAX * I_tot, I_tot - I_min)`, and the ceiling can bind only where both terms exceed
it:

    0.85 * I_tot > 1.25   ->  I_tot > 1.4706 A
    I_tot - I_min > 1.25  ->  I_tot > 1.40 A      (at I_min = 0.15 A)

At `I_min = 0.30 A` the conduction-floor term was the tighter of the two and set the threshold at
1.55 A. At 0.15 A the two swap: the **band edge**, not the conduction floor, now governs, and the
threshold moves to **1.4706 A of two-source total**. Two points follow.

1. The conduction-floor term now lands at exactly `LIMIT_I_FC_MAX` (1.25 + 0.15 = 1.40 A). That is
   a coincidence of two independently chosen constants, not a design coupling. The band-edge term
   keeps the real engagement 0.071 A above it, so the clamp still cannot first engage at the fault
   limit.
2. A new `static_assert` pins the property that matters, which the old assertion did not express:
   the total at which the clamp becomes reachable must sit strictly below
   `LIMIT_I_FC_MAX / DROOP_R_MAX = 1.6471 A`, the total at which the band edge alone already
   commands the fault limit. At the shipped constants that reads 1.4706 < 1.6471. The ceilings were
   **not** loosened to satisfy it. The older assertion — each ceiling above the conduction floor —
   is retained but is now weak, and the code says so.

The firmware version 26 validation artefacts were designed at `I_min = 0.30 A`: the measured first
engagement of 1.60 A, the bridged clamp sweep, the joint-transient leg and the `fw26-clamp-*`
scenarios. Their stimulus arithmetic does not carry over. Re-deriving them belongs to the tools
round; this round flags it.

### 8.6 What was NOT retuned

- `SHARE_CUT_MAX_HANDOFF_A` (0.5 A) is derived from bench evidence about a one-tick current
  handoff — `WP0097` and `WP0101` failed at 1.3 to 1.5 A, `TP0074` and its siblings were clean at
  about 0 A — and has no dependence on the conduction floor. Unchanged.
- `SHARE_CUT_SURVIVOR_BLANK_MS` is an RT1987 turn-on delay. Unchanged.
- `SHARE_HANDOFF_MIN_A` (0.15 A) and `SHARE_HANDOFF_LIVE_A` (0.20 A) are unchanged, and this breaks
  one of their stated properties. They were sized so that "a channel the governor considers healthy
  is never called dark", which held when the floor was 0.30 A. At 0.15 A the dark threshold now
  **equals** the floor and the live threshold sits above it, so a channel commanded exactly at the
  floor reads dark and the reduced handoff slew ceiling is selected. That is the conservative
  direction — slower, never faster — but it is a real behaviour change, it is stated at the
  constant, and it is what made section 12 necessary. Re-deriving these two against the scheduled
  authority is queued with the two-axis bench sweep.

## 9. The battery-only start

### 9.1 Mechanism

While the arm is up, `updateShareSetpointCutoff()` is fed an effective setpoint of 0.0 instead of
the commanded share. That is exactly the share-zero cut this function already implements, so the
cut inherits, without a line of new topology code:

- the last-source guard (both bus switches must read high),
- the firmware version 25 load guard on the doomed channel (`SHARE_CUT_MAX_HANDOFF_A`),
- the firmware version 25 survivor-turn-on blanking,
- the deferral path when the load guard alone refuses,
- and, for the re-entry, the latch's own guarded release, which requires a charged bus and an
  enabled boost.

No second cut mechanism exists. `shareSpCutFC` and `shareIsoFC` are the claims, exactly as they are
for an operator-commanded share of 0.0.

### 9.2 How "never closed this profile" is tracked, and where the profile boundaries are

`shareClosedLoopRun` is **not** used for this. It is cleared by `resetShareControlState()`, which
the latch's own release path calls — so an arm keyed on it would re-arm the cut on the tick the
release undid it, and cycle forever. A dedicated flag `shareBatteryOnlyArmed` is set by
`armShareBatteryOnlyStart()` at the profile boundaries, which are, in full:

1. State 1 to State 2, the production Run entry;
2. the State-98 `'R'` power-share profile start;
3. the State-98 `'D'` drive-cycle start;
4. the State-98 `'T'` trapezoid and sweep start;
5. the State-98 `'Y'` combined velocity-and-share start;
6. the State-98 `'W'` combined current-and-share start.

It is deliberately not armed by `resetShareControlState()`, by `setPowerShareSetpointLive()` (the
`'P'` key is a setpoint change inside a run, not a new run), by the State-98 `'O'` one-shot droop
write, or by any fault path. `hilWarmReset()` clears it, because a warm reset is not a profile
start and the recovery re-enters through State 1 and State 2, which arm it at a boundary that is.

The arm is one-shot per profile: it is dropped the moment the governor's filtered total crosses the
closed-loop gate, and nothing re-arms it until the next boundary.

### 9.3 The frozen loop must still advance the governor filter

A latched cut returns from `powerBalance()` before `share_govTotAFilt` is updated, by design: a
frozen loop has no governed state to advance. That is fatal for an arm whose release condition is
the filtered total crossing the gate, because the filter could never cross it and the profile would
run single-sourced for its whole length.

So while, and only while, the arm owns the cut, the frozen path keeps the load estimate alive and
drops the arm the instant the gate is met. The next tick then sees the arm inactive, the commanded
in-band setpoint reaches the release branch, the fuel cell re-closes on a charged bus through the
latch's own guarded release, and `resetShareControlState()` hands the loop to the open-loop
feedforward submode for the 20 to 40 ms the re-zeroed exponential moving average needs — the
firmware version 5 S9 behaviour, unchanged. Because the arm is one-shot, that reset cannot re-arm
it and the release cannot cycle.

The re-entry closes `FC_BUS_ENABLE` at **inherited multiplying-digital-to-analog-converter truth**.
`resetShareControlState()` does not touch `droopSlew_prev`, and it must not: the converters
physically hold the last applied split across the reset. The consequence is a light-load conduction
exposure at the handover. A profile that converged to the low rail leaves `droopSlew_prev` at
`DROOP_R_MIN` = 0.15, so a re-entry at the gate total of 0.30 A commands a fuel-cell current of
0.15 × 0.30 = 0.045 A, which is 30 % of the 0.15 A conduction floor. Three things bound the
exposure. The scheduled droop scale at that total is 0.906 ohm, the schedule's cap, so the droop
authority behind the command is 0.906 × 0.30 = 0.272 V at design scale, and about 0.068 V at the
one-quarter realized authority of section 10.5. The minority clip then walks the reference to the
band edge 0.15/0.30 = 0.5 on the ticks that follow, under the handoff slew rate. And the channel is
re-closed onto a bus that is already regulated by the surviving source, so a failure to conduct is
a share error, not a bus event.

A pre-release write to the converters was considered and **rejected**: it would put a second writer
on the split, outside the rate limiter that every other write goes through, at exactly the handover
the limiter exists to protect. The hardware-in-the-loop plant cannot test the residual either — its
bus law is linear and has no conduction knee (section 8.3) — so this is a **bench watch item**:
observe the fuel-cell current on the first ticks after a battery-only re-entry, on a profile that
ran to the low rail beforehand.

### 9.4 One owner per setpoint

An out-of-band commanded setpoint — 0.0, 1.0, or anything outside `[DROOP_R_MIN, DROOP_R_MAX]` — is
a **cut**, owned by the setpoint latch. The arm **disarms permanently** on sight of one, rather
than merely deferring: the profile's topology is the operator's or the energy-management strategy's
to command, and a battery-only rule that took the fuel cell back after the operator's own cut
released would be a second owner arriving late. A band-edge setpoint of 0.15 or 0.85 is in band and
is a share, not a cut, so it does not disarm.

### 9.5 The fuel-cell charge window

`assertFcChargeEnable()` holds `BT_BUS_ENABLE` low for the whole charge window, so the fuel cell is
the only source there. The arm is **suppressed** — not disarmed — while `FC_CHARGE_ENABLE` reads
high: the window is transient, the loop still runs and still closes, and the arm is then dropped
through the normal path.

Suppression is defence in depth, not the only defence. The latch entry's last-source guard requires
**both** bus switches high, so a share-zero cut is refused outright whenever the battery is already
off the bus. Both facts are asserted in the suite, the second by driving a bare share-zero command
with `BT_BUS_ENABLE` low. There is therefore no combination in which the battery-only rule and the
charge window can both act on the topology.

### 9.6 The deferral case, re-derived

The revision 2 gate is 0.30 A of total and the load guard refuses above 0.5 A on the doomed
channel. A start **below** the gate therefore carries at most 0.30 A of fuel-cell current and can
never be refused on load: the case of a start sitting in the deferral until the loop closes, which
existed at the revision 1 gate of 0.60 A, **no longer exists**. What remains is a start already
**above** the gate: the cut may be refused on load, but the loop closes on the first tick and the
arm is dropped there, so the deferral resolves by ownership rather than by load migration, and the
fuel cell is never taken off the bus at high current. `test_fw27_battery_only_deferral_and_high_start`
pins both halves, including the refusal counter.

### 9.7 What the bench operator and the hardware-in-the-loop suite will see

All five State-98 profiles start single-sourced on the battery. The `'S'` dump's
`share batt-only:` line reports the arm, whether it is active, whether the cut has been taken, and
whether it is deferred, so the early window of a `'T'` or `'W'` run reads as battery-only by design
rather than as a fuel-cell fault.

In a hardware-in-the-loop build the observation frame's switch word now shows `FC_BUS` low at every
profile start. The frame is unchanged — this is a value, not a layout change — but every
early-window switch check in the suite will see it, and the tools round must re-pin those.

### 9.8 The survivor's boost must be enabled before the cut

`updateShareSetpointCutoff()`'s cut entry carried a last-source guard on the two **bus** switches
only, while its own release branch and the ratio-based re-entry in `applyShareRatio()` both also
require the channel's `*_REG_ENABLE` — the S5 back-feed rule of CLAUDE.md section 2. The
battery-only start makes that asymmetry reachable. The cut now fires unconditionally at the five
State-98 profile starts, and the bench operator can leave `BT_BUS_ENABLE` high with
`BT_REG_ENABLE` low, because the `'B'` and `'2'` toggles are independent. Opening `FC_BUS_ENABLE`
there would leave the bus fed by a **disabled** TPS61288, which is a capacitive decay to
`ERR_UV_BUS`, and the release is gated on `V_BUS_CHARGED_THRESH` and could never re-close.

The entry therefore also tests the **survivor's** regulator: `BT_REG_ENABLE` high for a fuel-cell
cut, `FC_REG_ENABLE` high for the battery mirror. A block takes the same fall-through the
last-source guard has always taken — no latch, no deferral flag, live governed control — so the
battery-only arm is **suppressed, not disarmed**, and the cut is retried on every tick until the
operator enables the boost. `test_fw27_battery_only_survivor_regulator_guard` pins the refusal, the
absence of a deferral flag, the arm's disposition, and the cut firing on the first tick after the
boost is enabled, on both sides.

## 10. The load-scheduled droop scale

### 10.1 The schedule

    k_d(I_tot_filt) = max( K_DROOP,
                           RE_MAX * clamp(I_min / I_tot_filt, DROOP_R_MIN, 0.5) * SHARE_KD_SAFETY )

with `SHARE_KD_SAFETY = 0.9` (operator). Table 2 gives the values.

Table 2. The scheduled droop scale and the resulting design-scale authority.

| Filtered total (A) | `r_lo` | `k_d` (ohm) | Authority `k_d * I_tot` (V) | `g` at the band edge |
|---|---|---|---|---|
| 0.30 | 0.500 | 0.9061 | 0.272 | 0.900 |
| 0.40 | 0.375 | 0.6796 | 0.272 | 0.900 |
| 0.50 | 0.300 | 0.5437 | 0.272 | 0.900 |
| 0.70 | 0.2143 | 0.3883 | 0.272 | 0.900 |
| 0.906 | 0.1656 | 0.3000 | 0.272 | 0.900 |
| 1.00 | 0.150 | 0.3000 | 0.300 | 0.993 |
| 1.50 | 0.150 | 0.3000 | 0.450 | 0.993 |
| 2.00 | 0.150 | 0.3000 | 0.600 | 0.993 |
| 3.00 | 0.150 | 0.3000 | 0.900 | 0.993 |

Two design decisions are visible in that table.

**The 0.5 cap** mirrors the closed-loop clip's own sliver rule, `if (lo > 0.5f) lo = 0.5f`. The
reference can never be pushed past 0.5 by the clip, so the schedule must not size `k_d` for a band
edge above 0.5 either. Without it, the 0.25 to 0.30 A hysteresis sliver would ask for `k_d` up to
`RE_MAX * 0.60 * 0.9 = 1.087 ohm` against a reference the clip pins at 0.5.

**The floor is `max(K_DROOP, schedule)`, not the bare schedule.** The bare schedule at the low band
edge is `RE_MAX * 0.15 * 0.9 = 0.272 ohm`, which is **below** the shipped `K_DROOP = 0.30 ohm`, so
a pure schedule would weaken the droop at high load — a change nobody asked for, and one that would
move every firmware version 26 anchor. Taking the maximum recovers firmware version 26 exactly
above the crossover

    RE_MAX * SAFETY * I_min / K_DROOP = 2.0136 * 0.9 * 0.15 / 0.30 = 0.906 A

At and above 0.906 A of filtered total the scale **is** `K_DROOP`, so every firmware version 26
fixture that runs above it holds bit-exact. `test_fw27_kd_bit_identical_above_crossover` asserts
that at 1.0, 1.5, 2.0 and 3.0 A of total the live scale equals `K_DROOP` to the bit and the
multiplying digital-to-analog converter word equals the firmware version 26 closed form.

### 10.2 `g <= 1`, and the guard for when it is not

At the band edge the minority clip enforces, the mapping gives
`g = RE_MAX * r_lo * SAFETY / (RE_MAX * r_lo) = SAFETY = 0.9` exactly, and the majority channel's
`g` is smaller still. Above the crossover it is the firmware version 26 value
`K_DROOP / (RE_MAX * DROOP_R_MIN) = 0.993`. The suite sweeps every total from 0.25 to 4.0 A and
asserts the bound.

That is a statement about the **reference**, and it does not hold off the band edge. The schedule
reads a 20 ms filtered total that under-reads a rising load — the firmware version 26 clamp-sweep
measurement put the under-read at 25.6 % against a 12 % design headroom — so a stale light-load
`k_d` can meet a ratio the controller has already slewed toward a high-load value. A hard guard
therefore sits at the only site where the code can saturate, `setDroopMdac()`: the existing
`constrain()` clamps the word at full scale, and a saturating counter now records the event.
`test_fw27_g_guard_fires_on_a_stale_schedule` drives exactly that combination — a 0.906 ohm scale
against `DROOP_R_MIN`, a commanded `g` of 3.0 — and asserts the clamp, the count and the fact that
the commanded-gain mirror still shows the demand that was refused.

The count appears on the `'S'` dump and in the bench-log record. It counts **writes that were
clamped**, so a tick whose two gains both exceed full scale charges one event.

The **direction** of the residual error matters, because it is the safety argument. `g` is
inversely proportional to the channel's droop resistance, so clamping `g` down to unity caps that
channel's droop at `RE_MAX`, and the clamped channel therefore **over-delivers** relative to the
command. At the worst case the schedule admits — `k_d` = 0.906 ohm against `r` = `DROOP_R_MIN` —
the commanded gains are 0.906/(2.0136 × 0.15) = 3.00 and 0.906/(2.0136 × 0.85) = 0.529, the first
clamps to 1.00, the effective resistances become 0.450 and 0.850 ohm, and the delivered fuel-cell
fraction is 0.450/(0.450 + 0.850) = **0.346 against 0.15 commanded**. The share is wrong; nothing
is starved and no channel is driven toward its limit, so this is not an over-current path.

The guard is also **reachable only where `k_d` exceeds `K_DROOP`**, that is below the 0.906 A
crossover. At `k_d` = `K_DROOP` the largest gain the band can ask for is
0.30/(2.0136 × 0.15) = 0.993 < 1, which is why firmware version 26 never needed the guard and why
its bit-identity above the crossover is unaffected by it. Finally, the firmware version 26 current
ceilings cannot see a clamped write: they act on the reference, upstream of the code mapping. The
counter is the only observable.

### 10.3 The rate bound on `k_d`

`k_d` and `r` are both slewed, under the same hysteresis and from the same filtered total. The
per-tick bound on `k_d` is fractional and is derived from the code mapping. With
`g = k_d / (RE_MAX * r)`, a step in `k_d` at fixed `r` moves the code by `|dg|/g = dk/k_d`, while
the ratio limiter's own full step at fixed `k_d` moves it by `|dg|/g = dr/r`. The ratio path's
smallest admissible fractional motion anywhere in the band is at `r = DROOP_R_MAX`, so

    SHARE_KD_SLEW_FRAC_PER_TICK = DROOP_RATIO_SLEW_PER_TICK / DROOP_R_MAX = 0.02 / 0.85 = 2.353 %

Bounding the `k_d` path by that value guarantees a `k_d` step can never move the codes faster than
a full-rate ratio step already may. The widest excursion the schedule can ask for, `K_DROOP` to the
0.5-capped maximum 0.906 ohm, takes `ln(3.02) / ln(1.02353)` = 47 ticks, about 47 ms.

The schedule **input** is a held, hysteretic sample of `share_govTotAFilt` with the 0.05 A class
deadband `SHARE_KD_HYST_A`, written against `SHARE_GOV_OL_HYST_A` so the two cannot drift apart.
Without it, governor-filter noise would re-target `k_d` on every tick and the slew would never
settle.

### 10.4 Where the schedule runs, and where it does not

The schedule advances in **closed loop only**, once per tick, above every write site. The open-loop
hold writes nothing to the multiplying digital-to-analog converters, so publishing a new scale
there would describe hardware that did not move; the feedforward submode is left on the inherited
value for the same reason. `test_fw27_kd_slew_and_gating` pins both.

`shareDroopKd` is multiplying digital-to-analog converter truth, exactly like `droopSlew_prev`, and
is therefore **not** reset by `resetShareControlState()`: the converters physically hold their codes
across a profile boundary, and snapping the scale back to `K_DROOP` there would jump the codes by
the full schedule span in one write. The one place it is re-anchored is `hilWarmReset()`, where the
post-recovery bring-up re-runs `initMdacOutputs()` and the hardware really does move to the
`K_DROOP` 50/50 codes. The schedule **input** is a load estimate and is zeroed with
`share_govTotAFilt`.

The open-to-closed reseed needs no special case. The codes are recomputed from `droopSlew_prev`
under whatever `k_d` is live on the handover tick, and both factors are rate-bounded, so neither
jumps. `test_fw27_kd_reseed_continuity` drives a converged high-load run down through the gate and
back up at a light load, and bounds the per-tick motion of the fuel-cell word by one full-rate
ratio step.

The firmware version 26 ceilings and the firmware version 25 load guard operate entirely in
**current** space and never read `k_d`. Neither is affected, and the suite proves it by the fixtures
that already pin them, which move only where the scale differs from 0.30 ohm — that is, below
0.906 A of filtered total. The controller coefficients are likewise untouched: the static plant
gain is `alpha = r` for symmetric channels and is independent of `k_d`, so the Youla synthesis is
unchanged and nothing in the schedule references `share_controller_coeffs.h`.

### 10.5 Bus sag and the `LIMIT_V_BUS_MIN` margin

The sag a channel contributes is `R_ch * I_ch = (k_d / r) * (r * I_tot) = k_d * I_tot`, so the
schedule caps the design-scale sag at the constant authority 0.272 V. Against
`V_BUS_NOMINAL = 16.0 V` the worst case bus is 15.73 V, which is 3.73 V above
`LIMIT_V_BUS_MIN = 12.0 V` and 2.23 V above `V_BUS_CHARGED_THRESH = 13.5 V`. The schedule never
exceeds what firmware version 26 already produces at and above the crossover, where the two are the
same expression.

Those are design-scale figures. `docs/modeling/droop_authority_gap_20260903.md` measures the
AD5443-to-OPA197 injection chain delivering about **one quarter** of the design droop, so the sag
actually seen on this board is about 0.068 V and the margin is correspondingly larger. Both figures
clear the limit by a wide margin.

That gap is also the schedule's main caveat: **the schedule is correct, and its on-board payoff is
hardware-gated.** Until the realized authority is recovered, the constant 0.272 V of design
authority is a constant 0.068 V on the board, and the conduction-margin argument of section 8.2 is
correspondingly weaker in absolute terms. Closing the gap is not in this round.

## 11. The open to-do the operator recorded

On re-entering the open-loop region after the loop has closed, the firmware **holds** the split at
`droopSlew_prev`. The operator has an open question whether it should instead **return to battery
only**, that is re-arm the cut of section 9. This round does not implement it, and the two options
are not equivalent: a hold leaves both sources on the bus at a split nothing is regulating, while a
return-to-battery would repeat the profile-start topology every time a cruise or coast drops the
total under the gate, and would therefore multiply bus-switch cycles across a drive cycle. The
decision needs the switch-cycle count from a first campaign at revision 2.

## 12. A stranding hazard the floor change exposed, and its fix

The revision 1 review added a bypass: while a controller-initiated cut is outstanding, the raw
setpoint is fed forward rather than the clip's held value, so the proposed ratio walks off the rail
and the guarded re-entry in `applyShareRatio()` can fire. The **slew** below that bypass, however,
walked from `droopSlew_prev` — which is frozen for the duration of the cut, since an isolated
channel returns before it is recorded. Every isolated tick therefore proposed the same
`rail + one step`, and the proposal could never accumulate.

That is harmless only while one step alone clears the re-entry hysteresis:

    DROOP_RATIO_SLEW_PER_TICK          = 0.020 > SHARE_CUTOFF_HYST = 0.01  ->  re-enters, one tick
    DROOP_RATIO_SLEW_HANDOFF_PER_TICK  = 0.002 < SHARE_CUTOFF_HYST         ->  never re-enters

At revision 1 the second case was reachable but rare: it needed a channel to read dark, which takes
about thirty ticks of exponential-moving-average decay after a cut. At revision 2 it is the
**ordinary** case. The gate is 0.30 A of total, so no sub-gate total can hold both channels above
`SHARE_HANDOFF_LIVE_A` (0.20 A each is 0.40 A), the conduction-aware ceiling is therefore always the
handoff one below the gate, and the cut channel would have been stranded off the bus for the entire
sub-gate window — the exact stranding firmware version 5 exception (a) and the revision 1 bypass
exist to prevent.

The fix is a separate walk anchor. `shareIsoPropRatio` accumulates the **proposal** across isolated
ticks and is re-anchored to `droopSlew_prev` on every tick that is not isolated, and at each of the
four sites that take a cut — including the two in `applyShareRatio()`, because a cut can be taken by
a one-shot caller (the State-98 `'O'` write, the completion restore) that never reaches the
feedforward branch's own anchor.

The rate bound is preserved end to end. The proposal advances by at most one tick's ceiling, and the
single write the re-entry finally makes lands at the proposal, never more than one tick's ceiling
past the rail. How far past depends on which ceiling is live, and the two cases differ. At the
handoff rate the proposal accumulates in 0.002 steps and the re-entry fires on the first step past
`SHARE_CUTOFF_HYST`, so the write lands at most 0.002 beyond 0.15 + 0.01, that is **0.012** off the
rail. At `DROOP_RATIO_SLEW_PER_TICK` one step clears the hysteresis outright, so the walk crosses
0.15 to **0.17** in a single 0.02 step. Either way the motion is bounded by one full-rate ratio
step, and therefore is not a slam.
`test_fw27_iso_bypass_proposal_accumulates` pins the premise (one handoff step is smaller than the
hysteresis), the re-entry itself, the five-tick arithmetic, and that bound.

## 13. Bench-log format version 8

### 13.1 Why a format bump and not a flag bit

Through format version 7 the droop scale was the compile-time constant `K_DROOP`, logged once in
the 32-byte header, and the pair `(gFC, K_DROOP)` recovered the applied ratio exactly as
`r = K_DROOP / (RE_MAX * gFC)`. With a load-scheduled scale that identity fails: a single header
value no longer describes a run, and a format version 7 decoder reading a revision 2 log would
silently mis-recover **every** applied ratio. The live scale is therefore a record field, not a flag
bit, and the format moves.

### 13.2 The record

The record grows from 106 to **112 bytes**. Two fields are appended, so every version 1 to 7 field
keeps its byte offset:

| Offset | Type | Field | Class |
|---|---|---|---|
| 106 | `uint16` | `g_clamp_count` | saturating boot-monotonic counter |
| 108 | `float32` | `k_d` | level, in ohms |

The unsigned 16-bit count is placed first so the float lands 4-byte aligned and the structure
carries no implicit padding; 112 is a multiple of 4. Both offsets are pinned by `static_assert` and
by the host suite's golden-record fixture.

The field classes extend the version 6 and 7 three-class contract. `k_d` is a **level**: read it
directly, never difference it. `g_clamp_count` is a **cumulative counter that saturates** at 65535
rather than wrapping, so a run of equal maximum values means saturated, not quiet.

The header layout is unchanged. Its `K_DROOP_x1000` field keeps its offset and its units and now
means the schedule's **floor**, which is stated in both the firmware and the decoder.

### 13.3 The decoder

`tools/decode_benchlog.py` gains a format version 8 branch: `RECORD_FMT_V8`, `RECORD_SIZE_V8`,
`CSV_FIELDS_V8` and a 34-column `CSV_HEADER_V8`. The two new columns are appended after
`enc_duty_b_ewma`, that is still before `fault_flags`, following the convention every previous bump
used, and the derived `share_gov_ceiling` helper remains the last column. Versions 1 to 7 decode
byte-identically: each has its own `RECORD_INFO` entry and its own header constant, none of which
this bump touches, and `test_v7_unchanged_by_the_v8_bump` pins that separately from the version 7
fixture because the version 8 branch touches the shared row builder.

`tools/benchlog_analysis/common.py` accepts the new 34-column header, and
`tools/benchlog_analysis/make_test_blg.py` gains a `--v8` mode whose synthetic `k_d` reproduces the
firmware's own schedule from the synthetic channel currents, so a generated version 8 log satisfies
the field's own contract rather than carrying an unrelated trace.

The 1 kHz logging path is unchanged in kind: `logSampleTick()` still performs one fixed-size copy
into the static ring and no card input or output, and the ring, chunk and pre-allocation sizes are
untouched. At 112 bytes a 512-byte chunk still carries four records, as it did at 106.

## 14. Observability

- The State-98 `'S'` dump gains two lines. `share droop k_d:` reports the live scale, the fixed
  `K_DROOP` beside it, the schedule's current target, the **held** schedule input (deliberately not
  `share_govTotAFilt`, so a stale schedule is visible as the difference between them), the
  crossover total, and the clamp count. `share batt-only:` reports the arm, whether it is active,
  whether the cut has been taken, and whether it is deferred.
- The bench log carries `k_d` and `g_clamp_count` per record, per section 13.
- The hardware-in-the-loop frames are unchanged. The switch word will show `FC_BUS` low at every
  profile start, which is a value change, not a layout change.

## 15. Validation

### 15.1 Host-native tests

Ten new groups in `test/test_main.cpp`: the schedule as a table with its crossover and its
`g <= 1` sweep; the `k_d` rate bound, hysteresis and closed-loop-only gating; reseed continuity
across the handover; bit-identity to firmware version 26 above the crossover; the g-guard's clamp,
count and saturation; the g-guard firing on a stale schedule; the battery-only start at both band
edges with its re-entry at the gate; the battery-only ownership rules and the charge-window
non-conflict; the deferral re-derivation and the high start; and the iso-bypass proposal anchor. An
eleventh group covers the survivor-regulator guard on the cut entry (section 9.8).

One **coverage consequence of the halving** is recorded here rather than left implicit. No fixture
exercises the full-rate ratio slew below the closed-loop gate, and none can: the gate is
`2 * SHARE_MINORITY_I_MIN_A` = 0.30 A of total, while `SHARE_HANDOFF_LIVE_A` did **not** halve and
stays at 0.20 A per channel. Two live channels therefore need 0.40 A, which is above the gate, so
the conduction-aware limiter is always in its handoff state below the gate and the full-rate step
is unreachable there. Every sub-gate fixture runs at 0.002 per tick by construction.

Tallies: **4114 production, 175 bench, 4596 hardware-in-the-loop**, zero warnings on all three
builds. The revision 1 figures were 4024, 175 and 4506; the pre-review revision 2 figures were
4107, 175 and 4589.

### 15.2 What the hardware-in-the-loop plant can and cannot validate

It can validate the commanded side of all four mechanisms completely: which channel is on the bus
during the battery-only window and when it re-enters, the scheduled `k_d` and every code derived
from it, the clamp count, and the bench-log record. The board executes the real governor.

It cannot validate the physics any of it exists for. Section 8.3 states this for the conduction
floor. The same limit applies to the schedule: the plant's bus law is a fixed linear model, so a
larger `k_d` changes the modelled sag but not the light-load conduction behaviour that the extra
authority is meant to buy, and the plant has no model of the realized-authority gap of section 10.5
either. A campaign can show that nothing regressed and that the commanded quantities are what the
design says; it cannot show that the dropout is gone.

### 15.3 The bench gate

Unchanged in kind from revision 1, with one addition. The firmware version 6 ladder at setpoints
0.15 and 0.85, at the same profile, remains the measurement that closes the round: no source
dropout at either band edge, bus minimum at or above the firmware version 5 figure of 15.75 V. The
addition is the two-axis dropout-boundary sweep of section 8.3, at the scheduled droop scale, which
is what converts the 0.15 A floor from an argued value into a measured one.

### 15.4 What the first campaign should look at

Everything revision 1 listed, plus:

1. **The battery-only window.** Its length on each leg, the switch-cycle count it adds, and whether
   any leg spends a large fraction of its time inside it. That count is also the evidence the
   open to-do of section 11 needs.
2. **`k_d` against the filtered total**, straight from the bench-log columns: the schedule should
   be visible as a curve that flattens at 0.30 ohm above 0.906 A.
3. **`g_clamp_count`.** It should be zero or near zero. A rising count means the schedule and the
   applied ratio disagreed about the load, and its rate is the measurement of how badly.
4. **Every anchor with open-loop time is a re-pin, again.** The gate halved, so the open-loop
   occupancy census in `docs/HIL_PLANT.md` moves a second time, and the offline walk models neither
   the clip nor the schedule.
