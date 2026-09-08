# fw v28 — The source-selector package

## 1. Purpose and scope

This document is the design record for firmware version 28. Firmware version 28 changes five
things, all of them inside the never-closed (sub-gate) region that firmware version 27 revision 2
created, and each of them a consequence that region produced on the board:

1. the fuel-cell charge window no longer opens while a controller-initiated cut holds the fuel cell
   off the bus, and no longer opens onto a fuel cell that is not conducting;
2. the battery-only arm becomes a **source selector** that holds either the battery or the fuel
   cell on the bus, chosen from the commanded share;
3. the hysteresis sliver in the closed-loop minority clip **holds** the reference instead of
   pinning it at the balanced split;
4. the conduction floor `SHARE_MINORITY_I_MIN_A` moves from 0.15 A to 0.125 A, and the two
   conduction-handoff thresholds move with it;
5. the load-scheduled droop scale holds at `K_DROOP` in single-source windows.

The motor controller, the power-share Youla controller and its coefficients, the encoder path, the
bench-log record format (version 8, 112 bytes), the user datagram protocol telemetry (version 4,
58 bytes), the 22-byte command packet and the two hardware-in-the-loop frames (40 bytes and 18
bytes) are **unchanged**. `FW_VERSION` moves 27 to 28.

Two items from the same review round are **not** built. Item F6 is a tooling item: the offline walk
does not model the share loop's own feedback-filter overshoot on the firmware version 26 current
clamp. Item F7 is recorded in section 8 as a residual.

## 2. The evidence

Campaigns G (`hil_report_20260903_233736`), G2 (`hil_report_20260904_003108`) and H
(`hil_report_20260904_022637`) ran firmware version 27 revision 2 on the board. The numbers below
are from those campaign ledgers and are what each change is sized against.

Table 1. The board-measured findings this round closes.

| Item | Measurement | Where |
|---|---|---|
| F1 | Undervoltage-bus dwell 17.9 ms (`ems-ftp75c-*`), 19.07 ms (`charge-to-full`) against the 20 ms latch; two State-99 latches on campaign H at 20.12 ms and 20.22 ms | charge-window entry from a cut state |
| F1 | Bus collapse rate 2.57 V/ms, from `I_AUX` into `C_VBUS`, while both bus switches read low | the same |
| F1 | Firmware version 26 on the same stimuli: a 37 mV step | the same |
| F2 | The arm never releases on a cycle whose total stays under the 0.30 A gate; the compressed cycle peaked at 0.278 A and ran battery-only for its whole length (hydrogen −99 %, the pack drained) | `ems-ftp75c-*` |
| F3 | Totals in [0.25, 0.30) A held the delivered split at exactly 0.5000, that is 0.14 A per channel, for 17 s spans | `ems-sdp-cross` |
| F4 | The schedule saturated at its 0.906 ohm cap, the fuel-cell converter word sat at full scale for 9057 ticks, and the charge-window sag tripled | `mppt-tracking` |
| F5 | 58 load-guard cut and restore events in 90 s, at a maximum of 0.21 A | `ems-ftp75-sdp` |
| F7 | A re-entry on inherited converter codes overshot 0.2355 A for about 12 ms | `ems-ftp75-sdp` |

## 3. F1 — clear the arm before the charge path opens

### 3.1 The mechanism of the defect

`chargingControl()`'s cruise branch calls `assertFcChargeEnable(true)` on intent, that is whenever
`charge_goal` is positive and the vehicle is neither braking nor in the undervoltage backoff. That
call does two things in one tick when the share loop's setpoint latch holds the fuel cell off the
bus. Its S2 restore re-closes `FC_BUS_ENABLE`, because `shareSpCutFC` is set; its mutual-exclusion
guard then drives `BT_BUS_ENABLE` low, because the battery must be off the bus before the fuel cell
is routed into the charger.

The two writes are correct individually and wrong together. The ideal-diode controller needs about
8 milliseconds to turn the fuel-cell switch on, so for that interval the bus has **no source**: the
switch that was conducting has been opened and the switch that was opened has not yet conducted.
The bus then decays at `I_AUX / C_VBUS`, and the undervoltage dwell reached the values in Table 1.

The firmware version 27 revision 2 suppression did not prevent this. The arm was **suppressed**
while `FC_CHARGE_ENABLE` read high, but the window had not opened yet at the moment
`assertFcChargeEnable(true)` was called, so the suppression could not act. The arm was suppressed,
not disarmed, so `shareSpCutFC` was still set from the tick before.

### 3.2 The fix

The fix is two tests at the call site, and no change inside `assertFcChargeEnable()`.

First, **disarm before opening**. If the selector currently owns a fuel-cell cut, the branch clears
the arm this commander period and does not open the window. The selector's effective setpoint
disappears with the arm, so on the next 1 kilohertz `powerBalance()` tick the setpoint latch's own
release branch re-closes `FC_BUS_ENABLE`. That release is gated on `V_BUS_CHARGED_THRESH` and on
`FC_REG_ENABLE`, and it acts on a bus the battery is still regulating, which is the
make-before-break order the defect inverted.

Second, **conduction-gate the open**. The window opens only when `FC_BUS_ENABLE` reads high and
`busSwitchBlanked(FC_BUS_ENABLE)` is false. This is a test of the switch, not a count of commander
periods, so it does not depend on the commander cadence. It also covers every other reason the fuel
cell can be off the bus — a ratio-based `shareIsoFC` cut, an operator key, a share of 0.0 commanded
by the energy-management strategy — and it therefore covers the charge-window handoff that was the
third trigger on campaign H. Refusing to route a fuel cell that is not on the bus into the charger
is correct on its own terms as well: there is nothing to harvest from a source whose ideal diode is
held open.

The cost is one commander period of delayed harvest at the start of each window.

The S2 restore inside `assertFcChargeEnable()` is **kept**, unchanged. It is unreachable from this
call site, because the conduction test proves `FC_BUS_ENABLE` is already high before the call is
made. It remains the belt-and-braces path for `doState99()`'s capacitor drain and the staged
bring-up, which call the guard directly.

The State-98 `'5'` key also calls the guard directly, and is the sanctioned way to toggle the
charge path by hand, so it reached the same break-before-make sequence the fix removes from
`chargingControl()`. The key now **refuses** the open when `shareSpCutFC` or `shareIsoFC` is set and
`FC_BUS_ENABLE` reads low, printing what is wrong and what to do about it: release the fuel cell
onto the bus first, by commanding an in-band share or by walking the ratio back with `'O'`, then
press `'5'` again. Closing the path is never refused. The refusal is a guard on the operator's
sequence, not on the guard function, so the drain and bring-up paths are untouched.

The blanking window that makes the survivor safe is now asserted rather than remembered. A named
constant `RT1987_T_D_ON_MS` (8 ms typical, RT1987 datasheet sections 17.4 and 17.6, Table 1) sits
beside `SHARE_CUT_SURVIVOR_BLANK_MS` with a `static_assert` that the blanking window covers it, so a
future shortening of the window for a faster handoff cannot silently re-open F1 in miniature.

### 3.3 The symmetric cases

The `charge_goal <= 0.05` branch calls `assertFcChargeEnable(false)`, which only ever drives
`FC_CHARGE_ENABLE` low. It cannot move a bus switch and needs no guard. Its conditional
`if (!shareSpCutBT) writeBusSwitch(BT_BUS_ENABLE, HIGH)` already respects a selector cut on the
battery side.

`doState2()` reaches `chargingControl()` through `chargingControlGated()`, and the State-98 drive
cycle reaches it through the same call. The three profile branches that sweep the share axis
(`'R'`, `'Y'`, `'W'`) deliberately do not call `chargingControl()` at all, so no charge window can
open during them. The trapezoid branch is the same. The fix therefore sits on every path that can
open a window.

### 3.4 The fuel-cell selection inside a window

When the selector has the **fuel cell** selected, the battery is the cut channel and `FC_BUS_ENABLE`
is already high, so the conduction test admits the window on the same commander period. The
sequence that follows is traced here because it is the one case where the charge path and the
selector both act on the same switch.

**The disarm fires on either cut.** The disarm test is `shareBatteryOnlyArmed && (shareSpCutFC ||
shareSpCutBT)`, not on the fuel-cell cut alone. With the fuel cell selected the arm holds the
**battery** off the bus, and an arm that survived into the window produced ownership churn:
`assertFcChargeEnable()` clears `shareSpCutBT` as part of taking ownership of `BT_BUS_ENABLE`, the
`!shareSpCutBT` re-close at every window close puts the battery back, and the still-armed selector
cuts it again — one guarded cut per window transition, with ownership of that switch oscillating
between the charge path and the latch. A charge window **is** a single-source state, and the
selector must not also claim one. From a fuel-cell selection the disarm costs nothing and delays
nothing: the two tests are sequential rather than exclusive, so the window still opens on the same
period. From a battery selection the disarm leaves `FC_BUS_ENABLE` low and the conduction test
refuses the open on that period exactly as before.

1. `assertFcChargeEnable(true)` finds `FC_BUS_ENABLE` high, so the S2 restore does not fire. It
   drives `BT_BUS_ENABLE` low, which it already is, and **clears `shareSpCutBT` and `shareIsoBT`**:
   the charge path takes ownership of that switch.
2. The selector was **disarmed** on the same period, so for the whole window the topology is
   exactly what the selector wanted — the fuel cell alone on the bus — with the charge path as its
   sole owner. The selector's own cut cannot re-fire, both because it is disarmed and because the
   entry's last-source guard requires **both** bus switches high.
3. At window close, `chargingControl()`'s `!shareSpCutBT` re-close puts the battery back on the
   bus. That re-close lands on a bus the fuel cell is regulating, so it is a make, not a break, and
   nothing cuts it again: the closed loop takes the split from there through the ordinary
   open-loop-to-closed-loop handover.

Each step is a make-before-break, and no tick has both bus switches low. The sequence therefore
**needs no additional guard**. It costs one pair of switch transitions per window rather than the
per-window churn an armed selector would have produced.

## 4. F2 — the source selector

### 4.1 The rule

While the selector is armed the selected source is chosen from the commanded share on every tick:

    power_share_setpoint >= DROOP_R_MAX (0.85)  ->  select the fuel cell
    power_share_setpoint <= DROOP_R_MIN (0.15)  ->  select the battery
    anything in between                         ->  hold the current selection

Both thresholds are **inclusive**. The Pi clamps its commanded share into [0.15, 0.85], and the
setpoint latch's own out-of-band tests are strict (`sp < DROOP_R_MIN`, `sp > DROOP_R_MAX`), so a
strict test here could never fire on a real command. Every arm site defaults the selection to the
battery, so a profile whose commanded share never reaches a rail behaves exactly as firmware
version 27 revision 2 did.

### 4.2 One owner per setpoint, by construction

The effective setpoint the selector feeds `updateShareSetpointCutoff()` is 0.0 for a battery
selection and 1.0 for a fuel-cell selection. Both are **out of band**, so the setpoint latch owns
the setpoint on every active tick, and the selector cannot compete with it.

That is why two firmware version 27 revision 2 rules are removed.

The **permanent disarm on an out-of-band command** is gone. It existed because an out-of-band
command was a competing owner. Under the selector it is an **input**: a command of 1.0 selects the
fuel cell, a command of 0.0 selects the battery, and a command of 0.95 selects the fuel cell and is
realised as the same cut it would have caused directly.

The **fuel-cell charge-window suppression** is gone, replaced by the disarm-before-open of section
3. The suppression was never the only defence: the latch entry's last-source guard requires both
bus switches high, and `assertFcChargeEnable()` holds the battery switch low for the whole window,
so a selector cut is refused outright inside a window whichever source is selected. That structural
refusal is unchanged and is what makes the removal safe.

### 4.3 A selection change is make-before-break, through the existing machinery only

No topology code was added. A change from the battery selection to the fuel-cell selection runs
like this.

1. **Tick n.** The commanded share crosses 0.85. `shareSelectorFC` becomes true and the effective
   setpoint becomes 1.0. `updateShareSetpointCutoff()` evaluates its release branch first: the
   condition `shareSpCutFC && sp >= DROOP_R_MIN` is met at `sp = 1.0`, so — subject to
   `V_bus >= V_BUS_CHARGED_THRESH` and `FC_REG_ENABLE` high — `FC_BUS_ENABLE` is re-closed, the
   claims are dropped, `releasedThisTick` is set and `resetShareControlState()` runs. The function
   returns false, so the loop gets one live tick. **Both bus switches are now high.**
2. **Tick n+1 onwards.** The entry block sees `sp > DROOP_R_MAX` and proposes to cut the battery.
   It requires both bus switches high (true), `FC_REG_ENABLE` high (the survivor's regulator), the
   fuel-cell switch to be out of its turn-on blanking window, and the battery current to be at or
   under `SHARE_CUT_MAX_HANDOFF_A`. If the blanking refuses, no latch and no deferral flag is set
   and the entry simply re-runs next tick — the existing fall-through. If the load guard refuses,
   `shareCutDeferredBT` is set and the reference is clipped onto `DROOP_R_MAX` to migrate the load
   off the battery, which is the existing deferral.
3. When the guards admit, `BT_BUS_ENABLE` goes low and `shareSpCutBT` latches.

The change from the fuel-cell selection to the battery selection is the mirror: the release branch
`shareSpCutBT && sp <= DROOP_R_MAX` fires at `sp = 0.0`, and the entry then cuts the fuel cell.

Two properties follow and are the whole safety argument for this change.

**Two bus switches never move in the same tick.** The release returns before the entry can run, by
the `releasedThisTick` early return that has been in this function since firmware version 4.

**The load guard always admits below the gate.** A selection change under the closed-loop gate
carries at most `2 * SHARE_MINORITY_I_MIN_A` = 0.25 A of total, so the doomed channel carries at
most 0.25 A against a `SHARE_CUT_MAX_HANDOFF_A` of 0.5 A. A selection change above the gate is
possible only on the same tick the loop closes, which drops the arm.

### 4.4 The gate release works from either selection

The frozen-path filter advance keeps `share_govTotAFilt` alive while the selector owns the cut, and
drops the arm when it crosses `2 * SHARE_MINORITY_I_MIN_A`. It reads `|I_fc| + |I_batt|`, which is
selection-agnostic: the cut channel simply contributes about zero. From a fuel-cell selection the
release therefore re-closes the **battery** through the latch's own battery release branch, exactly
as it re-closes the fuel cell from a battery selection, and `resetShareControlState()` hands the
loop to open-loop feedforward for the 20 to 40 milliseconds the re-zeroed filter needs.

### 4.5 What was not changed

The closed-before hold and the open question of hold versus return-to-battery on **re-entering**
the open-loop region after the loop has closed are unchanged. They remain a recorded operator
to-do, and the switch-cycle census a first firmware version 28 campaign produces is the evidence
that decision needs. The selector adds switch cycles at every selection change, so that census
matters more than it did.

### 4.6 The raw-current escape from a fuel-cell selection

A fuel-cell selection puts the fuel cell **alone** on the bus, and single-source is the one regime
in which the firmware version 26 current-ceiling clamp is structurally inert: that clamp acts on the
two-source split, and a single source has no split to move. The only protection left is
`FAULT_OC_FC`, which latches State 99 on a **single raw sample** above `LIMIT_I_FC_MAX` (1.4 A),
with no filter and no persistence. A launch from standstill with the fuel cell selected — the
`sdp_policy_v6` table commands 1.00 below its state-of-charge target at low demand — therefore
carries the whole rising load on the fuel cell until the approximately 20 ms governor filter crosses
the gate, the latch's release fires, and the battery's ideal diode turns on some 8 ms later.

Firmware version 28 adds an escape on the frozen path, beside the filter advance: while the selector
is armed **and** the fuel cell is selected, the arm is dropped the instant the **raw**
`fabsf(I_fc)` exceeds `SHARE_GOV_I_FC_CEIL_A` (1.25 A, which leaves 0.15 A of headroom under the
fault limit). The latch's own guarded battery release then runs on the next tick.

This is the **one** place a raw sample gates the selector, and the exception is deliberate. The
governor doctrine that no raw measurement moves the reference exists to keep converter noise out of
the control path. This is not a reference movement; it is a race against a detector that is itself
raw and single-sample, and filtering it would guarantee the escape loses that race by construction.
A false trip costs one early battery re-close on a charged bus through the ordinary guarded release,
which is the benign direction.

**Decided and declined.** Refusing a fuel-cell **selection change** above a fraction of the gate was
considered and rejected as adding nothing. The arm is dropped at the gate, so while it is alive the
filtered total is below `2 * SHARE_MINORITY_I_MIN_A` = 0.25 A; a battery-to-fuel-cell change at that
instant hands the fuel cell at most about 0.25 A, a factor of five under the ceiling. The hazard is
the **rise** after the change, which is what the escape covers.

## 5. F3 — the hysteresis sliver holds

Closed-loop mode is held down to `2 * I_min - SHARE_GOV_OL_HYST_A`, so inside
[2·I_min − hysteresis, 2·I_min) the minority clip's band inverts: `lo > hi`, and no split is
feasible. Firmware versions 5 through 27 answered that with `if (lo > 0.5f) lo = 0.5f`, which
degenerates the bound to the balanced split.

Campaign G measured what that costs. On `ems-sdp-cross` a cruise total of 0.2817 A sat in the
sliver for 17-second spans, and the reference was walked to and pinned at exactly 0.5000, that is
0.14 A per channel. That is **below the conduction floor the clip exists to enforce**, and it
discards whatever the strategy commanded. A forced 0.5 is not a least-bad feasible command; it is
an infeasible one, and it is the same command shape firmware version 5 deleted from the open-loop
path for igniting the TP0053 relay cycle.

Firmware version 28 answers it the way `shareFeedforwardClipTarget()` already answers an empty
band: **hold**. When `lo > hi` the clip assigns `share_spEffPrev` to the target. That is the
variable the effective-setpoint slew immediately below integrates, so the assignment makes that
slew a no-op and the controller sees **zero reference motion** for as long as the total stays in
the sliver — not a walk toward a different value at a slower rate.

**The held value is bounded.** `share_spEffPrev` is re-anchored from `droopSlew_prev` on the
open-to-closed reseed and on a latch release, so a loop that closes at a rail reference (0.85) and
then falls into the sliver before the clip has walked it would hold 0.85 at 0.20 to 0.25 A of total.
The minority is then about 0.03 A, which reads **dark**. Holding an infeasible reference is the same
defect as pinning an infeasible 0.5, one rail further out. The hold is therefore bounded by the
**dark threshold** rather than by the conduction floor:

    loD = min(0.5, SHARE_HANDOFF_MIN_A / share_govTotAFilt)
    spTarget = constrain(share_spEffPrev, loD, 1 - loD)

At `SHARE_HANDOFF_MIN_A` = 0.10 A this evaluates to 0.400 at 0.250 A of total and to 0.500 at
0.200 A. The bound is therefore a **no-op** for any held reference already inside [0.4, 0.6] across
the whole sliver, and only at the very bottom of the sliver does it name the balanced split — where
that split is the only commandable point keeping both channels out of the dark, not a fallback.
`SHARE_HANDOFF_LIVE_A` was rejected for this bound: 0.12 / 0.24 = 0.5 would reproduce the exact
0.5000 pin campaign G measured, across most of the sliver. The bound never steps the reference,
because it moves `share_spEffPrev`, which the effective-setpoint slew then walks from at the tick
ceiling like any other movement.

Nothing else changes. A genuine coast-down still leaves closed loop at the exit threshold on the
tick the filtered total crosses it. Above `2 * I_min` the branch never fires, because `lo < 0.5 <
hi` there.

The `k_d` schedule's own 0.5 cap in `shareDroopScaleTarget()` is **unchanged**: it bounds the
actuator gain `g`, not the reference. Its comment previously derived the cap by mirroring the clip's
0.5 pin, and that derivation is now dead, so the rationale is restated at the constant. The cap
stands on its own argument — the band edge `r_lo` is meaningful only as a minority fraction, that
is below 0.5, and sizing `k_d` above 0.5 would ask for up to 1.133 ohm at the sliver's deepest
point. Capping at 0.5 bounds the scale at 0.906 ohm, which is unchanged, because the **cap**, not
`I_min`, sets it.

## 6. The conduction floor at 0.125 A, and F5

### 6.1 The ruling

The operator retargeted the constant low-current droop authority from `D = 0.30 V` to
`D = 0.25 V` at design scale on 2026-09-08. The firmware version 27 revision 2 schedule delivers a
constant authority `RE_MAX * I_min * SHARE_KD_SAFETY`, so the ruling fixes the floor:

    I_min = D / RE_MAX = 0.25 / 2.0136 = 0.124 A   ->  SHARE_MINORITY_I_MIN_A = 0.125 A

The realised constant at the shipped safety factor is `2.0136 * 0.125 * 0.9 = 0.227 V`.

The **hypothesis status is unchanged**. Nothing has demonstrated that conduction margin becomes
load-independent once the authority is held constant, and the hardware-in-the-loop plant cannot
demonstrate it — the high-fidelity engine has no pulse-frequency-modulation model and no light-load
converter branch, so a channel commanded to 0.125 A in the model simply carries 0.125 A. Only the
bench can settle it, through the two-axis dropout-boundary sweep at the **scheduled** droop scale.
Lowering the floor makes that measurement more load-bearing, not less.

### 6.2 The derived-constant table

Table 2. Everything derived from the conduction floor, at both values. Each quantity is written
against the symbol in the firmware, never restated as a literal.

| Quantity | Expression | fw v27 rev 2 (0.15 A) | fw v28 (0.125 A) |
|---|---|---|---|
| Closed-loop entry gate | `2 * I_min` | 0.30 A | **0.25 A** |
| Closed-loop exit | `2 * I_min - SHARE_GOV_OL_HYST_A` | 0.25 A | **0.20 A** |
| Hysteresis sliver | `[exit, gate)` | [0.25, 0.30) A | **[0.20, 0.25) A** |
| Minority clip band | `[I_min/I_tot, 1 - I_min/I_tot]` | `[0.15/I, ...]` | `[0.125/I, ...]` |
| Droop-scale crossover | `RE_MAX * SAFETY * I_min / K_DROOP` | 0.906 A | **0.755 A** |
| Maximum scheduled `k_d` | `RE_MAX * 0.5 * SAFETY` (the cap) | 0.906 ohm | 0.906 ohm (unchanged) |
| Constant authority | `RE_MAX * I_min * SAFETY` | 0.272 V | **0.227 V** |
| Constant authority at unity safety | `RE_MAX * I_min` | 0.302 V | **0.252 V** |
| Worst-case bus sag | `V_BUS_NOMINAL - authority` | 15.73 V | **15.77 V** |
| Ceiling reachability, band-edge term | `CEIL / DROOP_R_MAX` | 1.4706 A | 1.4706 A (unchanged) |
| Ceiling reachability, floor term | `CEIL + I_min` | 1.40 A | **1.375 A** |
| Ceiling reachability, governing | `max` of the two | 1.4706 A | 1.4706 A (unchanged) |

Three of those deserve a sentence.

The **maximum scheduled `k_d` does not move**, because the 0.5 cap sets it, not `I_min`. Every
comment quoting 0.906 as an **ohm** value is therefore still correct; every comment quoting 0.906
as an **ampere** value is the crossover and moves to 0.755.

The **firmware version 26 ceiling reachability does not move either**, and the coincidence firmware
version 27 revision 2 recorded is gone. At `I_min = 0.15 A` the conduction-floor term landed at
exactly `LIMIT_I_FC_MAX` (1.25 + 0.15 = 1.40 A); at 0.125 A it lands at 1.375 A, that is 0.025 A
below the fault limit. The band-edge term still governs, and now does so by 0.0956 A rather than
0.071 A. The reachability `static_assert` re-derives unchanged: `max(1.4706, 1.375) = 1.4706 A`
against `LIMIT_I_FC_MAX / DROOP_R_MAX = 1.6471 A`. **No ceiling was loosened.**

The **bus-sag margin improves**. The worst-case bus moves from 15.73 V to 15.77 V against
`LIMIT_V_BUS_MIN` of 12.0 V and `V_BUS_CHARGED_THRESH` of 13.5 V.

### 6.3 F5 — the two handoff thresholds

Firmware version 27 revision 2 left `SHARE_HANDOFF_MIN_A` at 0.15 A and `SHARE_HANDOFF_LIVE_A` at
0.20 A while moving the floor to 0.15 A, and recorded that this broke the firmware version 19
property that "a channel the governor considers healthy is never called dark". The dark threshold
**equalled** the floor and the live threshold sat above it, so a channel commanded exactly at the
floor read dark.

Campaign G measured the cost: 58 load-guard cut and restore events in 90 seconds on
`ems-ftp75-sdp`, at a maximum of 0.21 A. Nothing was unsafe — a dark reading selects the slower
handoff slew ceiling, which is the conservative direction — but the churn was created by the
equality.

Firmware version 28 restores the property by retuning both thresholds rather than by moving the
floor back: `SHARE_HANDOFF_MIN_A` 0.15 to **0.10 A**, `SHARE_HANDOFF_LIVE_A` 0.20 to **0.12 A**. The
ordering the firmware version 19 rationale requires holds again with margin:

    SHARE_HANDOFF_MIN_A (0.10) < SHARE_HANDOFF_LIVE_A (0.12) < SHARE_MINORITY_I_MIN_A (0.125)

and a new `static_assert` pins it, so a future retune of the floor or of either threshold fails the
build instead of silently re-creating the churn. A second `static_assert` pins
`SHARE_I_TOT_MIN_A` (0.075 A) under the dark threshold. The three constants become `constexpr` for
that reason and for no other; their values and their linkage are otherwise unchanged.

Two consequences are stated rather than hidden. The separation
`SHARE_HANDOFF_LIVE_A / SHARE_HANDOFF_MIN_A` narrows from 1.33 to 1.20, which is the price of
keeping both under the halved floor; it is still several standard deviations of the filtered
per-channel magnitude at that level. And the dark threshold stays above TP0201's 0.08 A pre-arm
trickle, which is the one measurement bounding it from below, with 25 % of margin.

The firmware version 27 revision 2 coverage note said no fixture could exercise the full-rate ratio
slew below the gate, because two live channels needed 0.40 A against a 0.30 A gate. Retuning the
thresholds briefly broke that: two live channels now need only 0.24 A against a 0.25 A gate, so the
full rate became reachable below the gate in the band [0.24, 0.25) A whenever the split was close
enough to balanced to hold both channels over 0.12 A — a region where no closed loop is authorised
and every movement is an open-loop feedforward walk near the conduction floor.

`updateShareSlewMode()` therefore selects the **handoff** ceiling whenever the filtered total is
below the gate, independent of the per-channel dark test. The property firmware version 27
revision 2 had by accident of the threshold values now rests on its proper predicate, the gate. The
coverage note stands as written for firmware version 28: the full rate is not reachable below the
gate through the both-live path, and `shareIsoPropRatio` is still what makes a re-entry possible
there.

The **spent-allowance** path is deliberately not covered by this test. When a channel has been dark
long enough to exhaust `SHARE_HANDOFF_DWELL_MAX_TICKS`, the full rate is restored even below the
gate, exactly as at firmware version 27 revision 2, where that combination was the only reachable
sub-gate state. The dwell cap is a bounded safety valve against an unbounded slow walk, and
retiring it below the gate would be a behaviour change beyond the defect; the change above closes
only the path firmware version 28 itself opened.

## 7. F4 — `k_d` holds at `K_DROOP` in single-source windows

The schedule's premise is a **minority channel to protect**: `k_d` is sized from the band edge
`I_min / I_tot`, which is the fraction the minority must carry. In a single-source window there is
no minority. One channel carries the entire filtered total and the other is off the bus, so the
band edge describes nothing, and feeding the single-source total into the schedule asks for the
light-load scale against a ratio pinned at a rail.

Campaign G measured the consequence on `mppt-tracking`: the schedule saturated at its 0.906 ohm cap,
the fuel-cell converter word sat at full scale for 9057 ticks, and the charge-window sag tripled
against the firmware version 26 era. Nothing was unsafe — the `g` guard at `setDroopMdac()` clamps
the write and counts it — but the droop the board applied bore no relation to what the schedule
meant.

Firmware version 28 separates the two kinds of single-source window, because the slew is only honest
where the converter words are actually **written**.

**A charge window holds at `K_DROOP`.** While `FC_CHARGE_ENABLE` reads high, `applyShareRatio()`
still writes, so the target is set to `K_DROOP` and reached through the existing
`SHARE_KD_SLEW_FRAC_PER_TICK` bound like every other schedule motion. Entering and leaving a window
can therefore never step the converter codes, and on window close the schedule resumes from
`K_DROOP` at the normal rate.

**A cut freezes the schedule outright.** `applyShareRatio()` writes no converter word at all while
`shareIsoFC` or `shareIsoBT` is outstanding, and a latched `shareSpCutFC` or `shareSpCutBT` returns
from `powerBalance()` before any write. Walking `shareDroopKd` toward `K_DROOP` against codes that
cannot follow it would land the whole accumulated move as a **step** on the first post-release
write — up to a factor of three, the very discontinuity the fractional slew exists to prevent, and
at the re-entry, which is already the most hazardous tick in the design (see F7 below). Under any of
the four cut flags the function therefore returns early: no target, no slew, and `shareKdSchedTot`
untouched. The release re-writes at exactly the `k_d` the codes already carry.

A single-source window that sets **none** of these flags is not detected. A battery bus switch
opened without a charge window — the State-98 `'2'` key, or the backoff branch's refused re-close —
is single-source and the schedule still runs on a single-source total there. That path is
bench-only and is recorded as a residual rather than fixed.

**Decision on the schedule input.** `shareKdSchedTot`, the held hysteretic sample, is **frozen** for
the duration of the window and is not updated from the single-source filtered total. The reasoning
is the same as the target's: that total describes one channel, and sampling it would leave the held
input carrying a load the schedule's law does not describe. Frozen, it re-samples on the first
post-window tick whose filtered total differs from it by more than `SHARE_KD_HYST_A`, which is
immediately if the window changed the load at all. The freeze therefore costs at most one tick of
staleness on window close, and the State-98 status dump's `sched-in` field reads the pre-window load
throughout the window, which is the honest reading of a frozen schedule.

## 8. Residuals and open items

**F7, recorded and not built.** A re-entry closes a channel at **inherited** converter truth.
`resetShareControlState()` does not touch `droopSlew_prev`, and must not: the converters physically
hold the last applied split across the reset. Campaign G measured the exposure at 0.2355 A for
about 12 milliseconds on `ems-ftp75-sdp`. Firmware version 28 makes this **more frequent**: through
firmware version 27 revision 2 a re-entry happened once per profile, at the gate; with the selector
a re-entry happens at **every selection change**, and a strategy that oscillates its commanded share
across a band rail under the gate produces one per oscillation. A pre-release write to the
converters was considered and **rejected** in firmware version 27 revision 2, because it would put a
second writer on the split outside the rate limiter, at exactly the handover the limiter exists to
protect. That rejection stands. The plant cannot test the residual either — its bus law is linear
and has no conduction knee — so this remains a **bench watch item**: observe the re-entering
channel's current on the first ticks after a selection change, on a profile that ran to a rail
beforehand.

**An undetected single-source window.** The `k_d` hold and freeze in section 7 key on the four share
flags and on `FC_CHARGE_ENABLE`. A battery bus switch opened by any other means — the State-98
`'2'` key, or the backoff branch's refused re-close — is single-source and sets none of them, so the
schedule still runs on a single-source total there and campaign G's saturation stays reachable. The
path is bench-only; the fix would be a topology test rather than a flag test, and is not built here.

**The State-98 keys remain a hand-sequencing surface.** The `'5'` refusal closes the one key that
could reproduce the F1 break-before-make, and the blanking `static_assert` pins the survivor window,
but the other switch keys still drive `writeBusSwitch()` directly by design: State 98 is the
hardware exerciser, and turning it into a second sequencer would defeat its purpose. The residual is
therefore bounded and named rather than removed.

**Switch-cycle count.** The selector adds a pair of bus-switch transitions per selection change, and
section 3.4 adds another pair per fuel-cell-selected charge window. The first firmware version 28
campaign should census them. That census is also the evidence the open hold-versus-return-to-battery
ruling needs.

**F6, a tooling item, not built here.** The offline walk does not model the share loop's own
feedback-filter overshoot on the firmware version 26 current clamp — about 3 % of the reference for
about 12 milliseconds, measured on campaign G's joint leg as a 0.039 A excess, which is half the
ceiling margin at 1.57 A.

**Stimulus re-derivation.** Every hardware-in-the-loop stimulus expressed as a designed total moves
with the floor: the `fw26-clamp-joint` step, the sweep and cruise legs, and the compressed-cycle
legs, which are now fuel-cell-selectable under the gate. That is the tools round's work; this round
flags it.

**Unchanged open rulings.** Hold versus return-to-battery on re-entering the open-loop region; the
realised droop authority gap in the converter-to-amplifier injection chain, which still delivers
about one quarter of the design value and gates the on-board payoff of the whole schedule.

## 9. Validation

### 9.1 Host-native tests, to be written by the test-writer

The behaviours this round adds, each of which needs a fixture:

1. **F1 from a battery-only state.** A charge window requested while the selector holds the fuel
   cell off the bus disarms the selector and does not open `FC_CHARGE_ENABLE`; the next
   `powerBalance()` tick re-closes `FC_BUS_ENABLE` through the latch's release; the window then
   opens on a later commander period. **No tick has both bus switches low while `MOT_PWR_ENABLE`
   is high** — the property, asserted directly.
2. **F1 conduction gate.** The window does not open while `FC_BUS_ENABLE` is low for a
   non-selector reason, and does not open inside `SHARE_CUT_SURVIVOR_BLANK_MS` of its rising edge.
3. **F2 selection thresholds.** A commanded share of exactly 0.85 selects the fuel cell and exactly
   0.15 selects the battery (inclusive); 0.8499 and 0.1501 hold the current selection; the default
   at every arm site is the battery.
4. **F2 transitions, tick by tick.** Battery to fuel cell and fuel cell to battery: the release
   tick re-closes the cut channel and returns the loop, the entry tick cuts the other channel, and
   **no tick moves two bus switches**.
5. **F2 gate release from a fuel-cell selection.** The frozen-path filter advance drops the arm,
   the battery re-closes, and the loop then closes.
6. **F2 under the guards.** The load guard admits at every total under the gate; a selection change
   while a deferred cut is outstanding resolves through the existing deferral; the
   survivor-regulator guard refuses on both sides without setting a deferral flag.
7. **F3 sliver hold, and its bound.** A total parked in [0.20, 0.25) A after converging at a
   commanded share of 0.55 keeps the reference within one slew step of 0.55 for 1000 ticks — the
   bound is a no-op there. A loop that closed at 0.85 and falls into the sliver is walked, at the
   tick ceiling and never as a step, to `1 - min(0.5, 0.10 / I_tot)`: 0.600 at 0.250 A, 0.500 at
   0.200 A. A coast-down through the sliver still exits to open loop at the exit threshold.
8. **F4 window hold.** A charge window opened at 0.16 A single-source leaves the fuel-cell converter
   word short of full scale and `shareGGuardCount` at zero; the schedule resumes after the window;
   the held schedule input does not move during it.
9. **The raw-current escape (section 4.6).** With the fuel cell selected and the arm alive, a single
   raw `I_fc` sample above 1.25 A drops the arm on that tick even below the load gate, and the
   battery re-closes on the next tick; a sample at 1.24 A does not; a battery selection is
   unaffected by any `I_fc` value.
10. **The either-cut disarm (section 3.4).** With the fuel cell selected, a charge window opens on
    the same commander period, the arm is cleared, and no re-cut of the battery follows the window
    close.
11. **The `k_d` freeze under a cut (section 7).** `shareDroopKd` and `shareKdSchedTot` do not move
    on any tick with `shareIsoFC` / `shareIsoBT` / `shareSpCutFC` / `shareSpCutBT` set, however long
    the cut lasts, and the first post-release write lands at the pre-cut `k_d`. A charge window
    still slews toward `K_DROOP`.
12. **The sub-gate slew ceiling (section 6.3).** A near-balanced split at 0.245 A of total with both
    channels above 0.12 A selects `DROOP_RATIO_SLEW_HANDOFF_PER_TICK`; the same split at 0.30 A
    selects the full rate; a spent dwell allowance still restores the full rate below the gate.
13. **The State-98 `'5'` refusal (section 3.2).** The key refuses to open the charge path while a
    share cut holds the fuel cell off the bus, and closing the path is never refused.
14. **The constants.** The three `static_assert` groups; every derived quantity in Table 2
   recomputed from the symbols; the firmware version 26 reachability fixture re-asserting that the
   band-edge term still governs.

Existing fixtures pinned at 0.15 A, 0.30 A, 0.25 A and 0.20 A of designed total, and at the 0.906 A
crossover, will fail at run time and need re-pointing proportionally, with the justification at each
site, exactly as firmware version 27 revision 2 re-pointed them.

### 9.2 What the hardware-in-the-loop plant can and cannot validate

It can validate the commanded side of all five changes completely: which channel is on the bus and
when, the switch ordering across a selection change and across a charge window, the reference's
behaviour in the sliver, the scheduled scale and every code derived from it, and the aux-byte
mirrors. The board executes the real governor.

It cannot validate the physics F1 exists for. The plant models the source-less bus decay linearly
and has no ideal-diode turn-on transient beyond a fixed delay, so it reproduces the **dwell** the
defect produced but not the converter stress. And it cannot validate the conduction floor at all,
for the reason section 6.1 gives.

### 9.3 The bench gates

Unchanged in kind, re-pointed to the new constants:

- the firmware version 6 ladder at commanded shares **0.125 and 0.875** on one profile: no source
  dropout at either band edge, bus minimum at or above the firmware version 5 figure of 15.75 V;
- the two-axis dropout-boundary sweep **CAL-6**, per channel direction, at the **scheduled** droop
  scale, which is what turns the conduction floor from an argued value into a measured one.

### 9.4 What the first campaign should look at

1. **The F1 witnesses**, which are the legs that latched: `charge-to-full`, the five
   `ems-ftp75c-*` legs and `ems-sdp-cross`. The measurement is the bus excursion at window entry,
   which should be a step of the firmware version 26 class rather than a dwell.
2. **The selector's occupancy and its switch-cycle count**, per leg, split by selection. The
   compressed-cycle legs are the ones that never released the arm at the 0.30 A gate and are now
   fuel-cell-selectable under a 0.25 A one.
3. **The sliver.** The delivered split on totals in [0.20, 0.25) A should track the commanded share,
   not 0.5000.
4. **`g_clamp_count` in charge windows.** It should be zero.
5. **Every anchor with open-loop time is a re-pin, a third time.** The gate moved again.

---

# Revision 2

Revision 2 supersedes revision 1 before any flash. No board has run firmware version 28, so
`FW_VERSION` stays 28 and there is no revision 1 era in the ledger; the precedent is firmware
version 27 revision 2. Revision 1, sections 1 to 9 above, is unchanged in every respect. Revision 2
adds one mechanism, on the encoder path, and touches nothing else. No wire change: the telemetry
stays version 4 at 58 bytes, the command packet stays 22 bytes, the hardware-in-the-loop frames
stay 40 and 18 bytes, and the bench-log format stays version 8.

## 10. Purpose and scope of revision 2

The operator ruled on 2026-09-08 that the encoder decoder shall detect the positive-feedback
runaway that an inverted direction assumption produces, and shall flip the assumed sense in
firmware without raising a fault. The detection threshold shall be significant, to prevent chatter.
The motivation is physical: the encoder harness can be plugged into the board the wrong way round
on any rebuild.

Revision 2 implements that ruling. Out of scope: the encoder interrupt service routines, the
velocity math in `updateWheelSpeed()`, `encoderVelReset()`, and any persistence of the corrected
sense across a power cycle.

## 11. The evidence

Section 5.4 of `docs/encoder_defect_harness.md` measured the defect on firmware version 27
revision 2, production build. With the B channel offset by 180 degrees the decode inverts as a
step, and stays inverted from 180 to 358 degrees.

| Quantity | 0 to 179 degrees | 180 to 358 degrees |
|---|---|---|
| settled reading, as a ratio to truth | +1.00000 | -1.00000 |
| control ticks on the current rail, of 20000 | up to 212 | **19900** |
| peak commanded current | 12.00 A | 12.00 A |

Three properties of that measurement drive the design. The magnitude is exact, so the defect is a
pure sign error and a sign factor is a complete correction. No fault is raised, because
`detectFaults()` carries no encoder-sign plausibility check. The firmware version 20 phase
diagnostic does not help either: `encPhaseEwma` folds forward-direction samples only, so it reads
0 under a full inversion, which is the same value it reports for no data at all. A reversed harness
therefore presents on the bench as a motor that runs away at full current behind a clean-looking
status dump.

## 12. The mechanism

### 12.1 The seam

A single signed factor, `encDirSign`, is applied where `updateWheelSpeed()` publishes `v_actual`,
through the helper `encDirApply()`. Six publish sites carry it: the boot and post-reset hold, the
two re-accumulation holds, the single-pitch sign embargo, the corroboration hold, and the live
reading. The two hard zeros on the stale paths are sign-invariant and are left as plain literals.

The seam is the publish boundary and not the estimator. The interrupt service routines,
`encPeriodDir`, the period ring, `encVelLastValid`, `encVelResetHold` and `encoderVelReset()` all
keep the decoder's own frame and are byte-identical to revision 1. Two consequences follow. First,
nothing inside `updateWheelSpeed()` has to be re-reasoned, so the "What NOT to change" boundary in
`CLAUDE.md` holds. Second, because the held values live in the decoder frame, a flip re-signs the
holds and the live readings together: the published stream is self-consistent from the first tick
after the flip, and no mixed-frame window exists.

### 12.2 Hardware-in-the-loop gating

Under `HIL_SIM` the sign factor cannot reach an injected value. `updateSensors()` writes `v_actual`
from offset 30 of the 40-byte injection frame and returns before `updateWheelSpeed()` is called, so
`encDirApply()` never executes. The plant's sign is authoritative, which is the required behaviour.
The detector is compiled out under the same flag: a flip there could change no number, but it would
still print a line and move the status dump. The function keeps its symbol in every build, so the
call site and the host tests link identically in all three flag sets.

### 12.3 The detector

`updateEncoderDirectionSense()` runs once per main-loop tick, at approximately 1 kHz, immediately
after `detectFaults()` and before the state machine. That position is load-bearing on both sides. A
genuine fault still latches State 99 first, so the detector can never pre-empt the fault path; and
the state machine, hence `motorControlGated()`, has not yet run, so a flip takes effect on the same
tick's motor command. Note that the same-tick claim holds only because the flip site also negates
the live `v_actual`. `updateSensors()` published `v_actual` through `encDirApply()` with the
pre-flip sign at the top of this tick, and nothing re-publishes it before `motorControlGated()`
runs; see section 12.5. The function writes no motor current and moves no switch, so the one writer
per tick discipline at `commandMotorCurrent()` is untouched.

The detector reads the current tick's published `v_actual` against the previous tick's post-clamp
mirrored `current`. That one-tick skew is immaterial against a 500-tick window, and it is the
honest pairing: `current` is what the loop commanded in response to the reading that produced this
one.

Six conditions are required on the same tick. Any single miss zeroes the counter.

0. The velocity loop is closed: `manualMotorMode != MOTOR_TEST_CURRENT`. The detector's premise is
   a closed velocity loop, in which the encoder reading is the measurement that produced the
   command it is compared against. In the State-98 `A` manual-current mode no velocity loop exists:
   the operator sets `current` by hand and the encoder does not influence it, so an opposing sign
   carries no information about the decoder's sense and a wheel driven backwards at a hand-set 12 A
   is a false positive by construction. `MOTOR_TEST_VELOCITY`, production State 2 and the `D` and
   `Y` profiles all run `motorControlGated()` and remain in scope.
1. The published velocity opposes the commanded current, `sign(current) == -sign(v_actual)`.
2. `|v_actual| >= ENC_DIR_RUNAWAY_V_MIN`, 0.30 m/s.
3. `|current| >= ENC_DIR_RUNAWAY_I_FRAC * MOTOR_I_CMD_MAX`, that is 0.5 x 12.0 A = 6.0 A.
4. `|v_actual|` is not decreasing: it stays within `ENC_DIR_RUNAWAY_MAG_TOL` (0.02 m/s) of the
   maximum magnitude seen since the window opened, which the detector ratchets upward.
5. The above hold for `ENC_DIR_RUNAWAY_TICKS`, 500 consecutive ticks, that is 0.5 s.

One further condition is tested once, when the counter completes the window.

6. Growth: `|v_actual|` at completion exceeds `|v_actual|` when the window opened by at least
   `ENC_DIR_RUNAWAY_GROWTH_MIN`, 0.10 m/s. Conditions 1 to 5 admit a constant magnitude, and a
   constant magnitude against the current rail is what a correctly wired vehicle looks like when it
   is held at a steady speed it cannot exceed: an incline, a dyno, or a bench flywheel driven
   externally. Without condition 6 such a vehicle flips falsely after 0.5 s, and the flip is
   permanent and silent for the boot (section 12.7). A window that completes without the growth
   resets and takes no flip, so a sustained stall costs one restarted window per 0.5 s and nothing
   else.

   The trade-off is stated rather than avoided. An inversion first noticed only after the vehicle
   has already reached its drag-limited terminal speed produces no further growth and is not
   caught. That is accepted because an inversion accelerates through 0.30 m/s from standstill on
   every run start, so the growth window exists on every normal start of every run; the case that
   is lost is an inversion that appears mid-run at terminal speed, which no wiring fault produces.

A valid reading is also required (`encVelHaveValid`), so a boot or standstill publication and the
pre-first-reading corroboration hold cannot contribute ticks.

Condition 4 is the discriminator. Legitimate braking satisfies conditions 1 to 3 by construction,
and fails 4 within a few ticks of the tolerance being spent, because a commanded deceleration
collapses the magnitude. Condition 4 is evaluated against a ratcheted maximum rather than against
the previous tick, because a per-tick comparison would be broken by the estimator's single-pitch
variance while the running maximum plus a tolerance tracks the envelope.

### 12.4 The constants

| Constant | Value | Derivation |
|---|---|---|
| `ENC_DIR_RUNAWAY_V_MIN` | 0.30 m/s | 5.6x the estimator's reportable floor of 0.0532 m/s and 4.3x the `v_setpoint` zero cutoff of 0.07 m/s, so the whole deadband-relay regime is excluded; equal to the slowest cruise speed in the harness sweep and in the drive-cycle profiles, so a real inversion still trips at the slowest speed the vehicle is driven at. |
| `ENC_DIR_RUNAWAY_I_FRAC` | 0.5, that is 6.0 A | An inverted encoder rails the loop at 12.00 A (measured), so this is a factor of two of margin under the observed signature, while every gentle manoeuvre, the trapezoid's low steps and all coast and regen phases sit below it. |
| `ENC_DIR_RUNAWAY_TICKS` | 500, that is 0.5 s | The harness railed for 99.5 percent of a 20 s run, so a real inversion satisfies the window within the first half second of motion above the speed threshold. |
| `ENC_DIR_RUNAWAY_MAG_TOL` | 0.02 m/s | Under half the estimator's zero floor and 6.7 percent of the speed threshold: large enough to absorb timer quantisation and single-pitch variance, small enough that a genuine deceleration spends it in a few ticks. |
| `ENC_DIR_RUNAWAY_GROWTH_MIN` | 0.10 m/s | The growth the window must show to close on a flip. An inverted encoder at the current rail accelerates the vehicle at approximately 4.8 m/s^2, which is about 2.4 m/s of growth over the 500-tick window, so 0.10 m/s is a factor of 24 under the real signature. It is also five times `ENC_DIR_RUNAWAY_MAG_TOL`, hence far above the estimator's single-pitch variance, so a genuinely constant magnitude cannot drift across it. |
| `ENC_DIR_FLIP_LOCKOUT_MS` | 5000 ms | Long against the drive loop's settling, which at the 16 rad/s design crossover is of order 0.3 s, and ten times the detection window, so the corrected loop is fully settled before the detector can arm again. |
| `ENC_DIR_FLIP_MAX` | 4 | An inverted harness needs exactly one flip. A small allowance covers an operator re-plugging the connector mid-session; past it the sign is frozen. |

### 12.5 What happens at a flip

`encDirSign` is negated, `encDirFlipCount` increments, the live `v_actual` is negated in place,
`resetDriveControlState()` is called, one ASCII line prints, the window is cleared and the lockout
arms.

The negation of `v_actual` is what makes the same-tick claim of section 12.3 true.
`updateSensors()` published `v_actual` through `encDirApply()` at the top of this tick, with the
sign that was in force then, and no code re-publishes it before the state machine runs
`motorControlGated()`. Without the negation the new sign would first reach the motor command on the
next tick, and this tick's command would be computed from a wrong-signed error. The negation also
matters to the reset that follows, because `resetDriveControlState()` back-dates
`driveCtrl_lastMicros` so that the controller's first step after the reset runs immediately, on
this tick and on this error. Negating the live value produces exactly what the next
`updateWheelSpeed()` will publish from the same reading under the new sign.

The controller reset is not optional. The harness shows the controller pinned at the
`MOTOR_I_CMD_MAX` rail at the moment the window completes, and the flip instantaneously negates the
measurement, so the error steps by twice the magnitude. Carrying a saturated Hanus state across
that step would answer a now-correct measurement with a saturated command until the state unwinds.
The reset is a controller-state reset only: it commands no current and moves no switch. It is the
same call, and the same doctrine, as the firmware version 13 `v_setpoint` zero-cutoff entry edge.

On a `USE_YOULA_DRIVE_CONTROLLER=0` build the proportional-integral fallback's integrator is not
owned by `resetDriveControlState()`. It is cleared at the flip site alongside the call, together
with the `pi_motor_lastMicros` reference, exactly as the zero cutoff does, so a railed integrator
cannot survive the sign reversal and answer the corrected measurement with a saturated command.

Past the flip cap the sign is held where it is and only a line prints. The lockout applies to that
path as well, so the print rate is bounded at one per 5 s however hard the detector is fooled.

The flip is not a fault, by ruling. It takes no `fault_flags` bit, sets no error code and never
enters State 99.

### 12.6 A wrong flip is silent and permanent, so the entry test is the only real lever

A flip taken in error does not self-correct, and this governs the whole design of the entry test.
After a wrong flip the published sign agrees with the drive current on every tick of normal
driving, so condition 1 fails on every tick, the counter never leaves zero, and the detector can
never observe the state it created. The board then runs the rest of the boot with an inverted
velocity, without a fault, without a further Serial line, and with only the `S` dump's `dirSign`
field to show it. Recovery is a power cycle.

Neither the lockout nor the per-boot cap bounds that case, and an earlier revision of this section
claimed otherwise. What they bound is repeated genuine detections, that is a sense that really does
keep changing, such as a connector that is intermittently reversed or a harness that is being
re-plugged mid-session. For that case the lockout makes a second flip impossible for 5 s, which is
longer than the loop needs to settle at the corrected sign, and the cap freezes the sign after four
flips and prints a line asking the operator to check the wiring.

The defence against a wrong flip is therefore the entry test alone, and it is built from five
independent bounds.

- Condition 0 excludes the one mode in which the comparison is meaningless, namely manual current.
- Condition 6 excludes a constant magnitude, which is the entire class of correctly wired vehicles
  held at speed against the rail.
- Two magnitude thresholds, on speed and on current, exclude the regimes where the sign of a
  reading is not trustworthy and where the loop is not pushing hard.
- The window is unbroken: a single non-qualifying tick zeroes the counter, so the detector cannot
  integrate an intermittent signature into a flip.

Under correct wiring the detector's steady state is a counter at zero, because the drive current
and the velocity share a sign.

### 12.7 The false-positive bound

The residual class is an external push: the vehicle pushed backwards while the drive commands
forward. To be mistaken for an inversion the push must hold the drive above 6 A, keep the published
magnitude non-decreasing within 0.02 m/s of its running maximum, grow that magnitude by at least
0.10 m/s, and do all of it continuously for 0.5 s with the velocity above 0.30 m/s throughout. A
push that ends, that steadies, or that the drive begins to overcome breaks the window or fails the
growth test. The cost, should such a push occur, is one silent inverted boot as described in
section 12.6, not an oscillation.

### 12.8 Lifetime across resets

The sense is a fact about the wiring, so it survives every run boundary: `hilWarmReset()`, the
State-98 `Q` exit, `resetControlRateLimiters()` and State 3 all leave `encDirSign` and
`encDirFlipCount` alone, and only a power cycle returns the sign to +1. Re-deriving the sense at
every profile boundary would cost another half second of runaway per run for no gain, because the
harness cannot change while the board is powered.

The window counter is transient state and is dropped at the `Q` profile boundary, so ticks earned
under one profile can never complete a window under the next. Everywhere else the counter clears
itself within one tick, because Idle commands 0 A and any non-qualifying tick zeroes it.

The sense is not persisted to non-volatile memory. The wiring is fixed per build, a stale stored
sign on a re-wired board would be worse than half a second of runaway, and the detector re-derives
the correct sense within 0.5 s of motion above the thresholds. A persistent option is a follow-up
ruling.

### 12.9 Interactions traced

- **The firmware version 13 `v_setpoint` zero cutoff (`driveZeroCutActive`).** Inside the cutoff
  the loop commands 0 A, so condition 3 fails and the window is zero throughout. The detector
  cannot fire on a standstill.
- **The firmware version 17 hold-until-corroborated path (`encVelCorrobPending`,
  `encVelResetHold`).** The held value is published through `encDirApply()` like every other, so a
  hold spanning a flip re-signs with it. The detector requires `encVelHaveValid`, so the
  pre-first-reading hold contributes no ticks.
- **The estimator's reversal clear (`encPeriodDir = 0` with `encPhaseEwma = 0`, MED-1).** Unchanged
  and untouched. A cleared direction publishes a hold, which carries the sign factor; the phase
  statistic stays in the decoder frame, which is correct, because it describes the sensor geometry
  and not the published sense.
- **Regen windows.** The RegenManager arms and releases `charge_goal` on the observed motor
  current, at -0.2 A and -0.1 A. Those magnitudes are far below the 6 A current condition, and a
  regen window is a deceleration, so condition 4 fails as well.
- **The State-98 `D` and `Y` profiles.** Their coast-down and regen-hold phases are the braking
  case: conditions 1 to 3 can hold, condition 4 cannot, because the profile's own velocity setpoint
  is falling and the magnitude follows it.
- **The velocity-chain interlock (`velocityChainCalibratedFlag`).** Unrelated and untouched. The
  interlock gates the two velocity-mode entry points; the detector runs in every state and simply
  finds no qualifying ticks while the motor is not driven.
- **The State-98 `A` manual-current mode (`MOTOR_TEST_CURRENT`).** Excluded by condition 0. There
  is no velocity loop, so the operator's hand-set current and the encoder reading are independent
  and their relative sign says nothing about the decoder. This is the one mode in which the
  detector's premise does not hold.
- **The `MOTOR_I_CMD_MAX` rail decode.** The detector reads the post-clamp mirrored `current`, so a
  railed command reads exactly 12.00 A and clears the 6.0 A condition with a factor of two.

## 13. Observability, and the gap

The flip prints one ASCII line on USB Serial, of the form
`ENC DIR FLIP #1: runaway 500 ticks, |v|=1.512 m/s vs I=12.00 A - sign now -1`, and the cap prints
its own line. The State-98 status dump's Encoder block gains `dirSign`, `flips` and the live window
count on the `periods= ... dir=` line, so the published sense is `dir` multiplied by `dirSign` and
an operator can read both.

The gap is stated rather than worked around. The hardware-in-the-loop observation frame's auxiliary
byte has no spare bit left: bits 0 to 3 are pin levels, bits 4 and 5 are the firmware version 26
ceiling clamps, and revision 1 of this package took bits 6 and 7 for the selector. The bench-log
`flags` byte is fully allocated at format version 8. Neither the 18-byte frame nor the 112-byte
record may grow this round, and `switch_state` is the topology word the plant solves the network
from and must not carry a non-switch semantic. The flip therefore has no wire-level observable in
firmware version 28: a hardware-in-the-loop run cannot see it, and a bench log cannot either. Since
the detector is compiled out under `HIL_SIM`, the first of those costs nothing today; the bench-log
gap is real and is a candidate for the next format bump.

## 14. Residuals of revision 2

1. **No wire-level observable**, as above. A bench log of a run in which a flip occurred shows the
   sign change in `v_act` and nothing that names its cause.
2. **No persistence.** A board with a reversed harness re-derives the sense on every power cycle,
   at the cost of up to 0.5 s of railed current per boot. A follow-up ruling could store it.
3. **The external-push false positive** is bounded, not eliminated; section 12.7 states the bound.
   Its cost is one silent inverted boot, because a wrong flip does not self-correct; section 12.6.
4. **A partial inversion is out of scope.** Section 5.5 of the harness document measures the
   near-aligned case, where the reading alternates sign at the dither rate. That signature breaks
   the window on its own alternation and will not flip; it is a front-end defect, and the standing
   answer to it is the Schmitt buffer, not a sense flip.
5. **The detector cannot run under `HIL_SIM`**, so the hardware-in-the-loop suite can never
   exercise it. Its validation is host-native, in the harness and in the unit suite.
6. **A terminal-speed inversion is not caught.** Condition 6 requires growth, so an inversion first
   seen at the vehicle's drag-limited terminal speed produces no window that closes. Section 12.3
   states why the case is accepted: an inversion accelerates through the speed threshold from
   standstill on every run start.
7. **A wrong flip is recoverable only by a power cycle**, and has no observable beyond the `S`
   dump's `dirSign`. Persistence of the sense (residual 2) would make this worse, not better, and
   any follow-up ruling on persistence must weigh it.

## 15. Validation of revision 2

The test writer owns these. All are host-native; none touches a board.

1. An inverted wiring produces exactly one flip within the window, and the drive recovers: the
   commanded current leaves the rail and the error converges after the flip.
2. Braking never flips, at any speed and current inside the thresholds.
3. An external push shorter than the window never flips.
4. The lockout blocks a second flip inside 5 s, and the per-boot cap holds the sign at four flips.
5. The `HIL_SIM` build applies no sign factor and takes no flip.
6. The status dump prints `dirSign`, `flips` and the window count.
7. A constant magnitude never flips: a run held at 0.30 m/s or above, opposing a 12 A command, for
   many multiples of the window, takes no flip, because the growth of condition 6 is absent. A
   companion case with the same stimulus plus 0.10 m/s of growth across the window does flip.
8. The `A` manual-current mode never flips: driving `manualMotorMode = MOTOR_TEST_CURRENT` with an
   opposing velocity at the rail for many windows takes no flip.
9. The flip corrects the same tick: after the flip returns, `v_actual` has the corrected sign
   before the state machine runs, so the motor command computed in the same tick uses it.
10. A wrong flip does not re-fire: with the sign flipped so that the command and the velocity now
    agree, no further flip occurs however long the stimulus is held, and `encDirFlipCount` stays 1.
11. The 180 degree phase case already in `test/encoder_defect_harness.cpp` now asserts the flip and
   the recovery instead of the runaway, and the regression band for that case moves from -1.00000
   to +1.00000 after the flip.
