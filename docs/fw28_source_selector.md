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
