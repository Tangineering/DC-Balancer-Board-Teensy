# Battery-isolation study: pre-purge sequence and predictor interface (IC1 revision 8)

## 1. Scope and sources

This fact sheet gives the end-to-end timeline of an FC-window close on a purge prediction, the minimum predictor lead
time T_lead, the earliest window re-entry after the purge, and the usable charge time per purge period. It applies to
design IC1 revision 8 (`detailed_design_IC1.md`, cited as DD) and to fw v37 rev 2 (`teensy_controller/teensy_controller.ino`,
cited as ino).

The operator rulings of 2026-11-08 frame the sheet. The purge predictor is ideal and is not modelled. An unpredicted purge
may collapse the bus and latch State 99, provided that no component is damaged. FC windows may open in State 2 between
purges (**variant D**) as well as parked in State 1 (**variant P**). The purge figures are those of facts_prior section 7
only: period 10.34 s, duration 100-140 ms (+/-20 ms per edge), floor about 1 V.

All numbers come from `calc/purge_sequencing_timeline.py` (output in `calc/purge_sequencing_timeline_output.txt`) unless
another source is named. The evidence classes are as follows:

- **SOURCED**: stated in the cited datasheet, design document or firmware line;
- **CALC**: computed by the script from SOURCED inputs;
- **ESTIMATE**: computed from a model whose form is not verified on this board;
- **BENCH**: only a measurement can fix the value;
- **UNCONFIRMED**: a reading of a source that the source does not state outright.

The safe-collapse analysis of an unpredicted purge and the demand budget of variant D are outside the scope of this
sheet. The demand budget is in `calc/purge_demand_budget.py`.

## 2. Constraints that the sequence inherits

### 2.1 Order of the close

In an IC1 FC window BT_BUS is open and clamped by Q_X1 (DD Table 12, row "FC window"). In the charge mode a closed BT_BUS
lets the BT boost draw from the pack through the Ag105 sense in reverse (DD section 9.6). Therefore the shift of load
toward the battery cannot start inside a window. The order is fixed by DD section 9.7, exit steps 1-4:

1. FC_CHARGE LOW through `assertFcChargeEnable(false)`, with the exit hold check of pin 8 (DD section 9.5 exit step 1).
2. Drain wait: pin 8 (MOD_COLD_N) LOW on two successive iterations, deadline T_drain,max (DD section 9.5 exit step 2).
3. Pin 33 LOW: FF1 clears and both S_GND turn on (the pack is bonded).
4. Bonded confirmation within 4 iterations, then BT_BUS re-closed through the guarded path (`busHotPlugUnsafe()`,
   ino:13043).
5. Pin 10 LOW and pin 5 LOW once pin 8 has read LOW for 20 ms (cold-module rule, DD section 12.4 item 2). These two writes
   do not delay the bond or the BT_BUS re-close.

### 2.2 Conduction of a re-closed bus switch

The KEY CONSTRAINT text of this round uses t_D_ON (about 8 ms) as the BT_BUS re-close time. However, the firmware
derivation of `SHARE_CUT_SURVIVOR_BLANK_MS` states that a bus switch closing onto an energized bus sources no current
until its CSS soft-start ramp is also complete (ino:4853-4860). FC_BUS and BT_BUS carry CSS = 100 nF, so the ramp is
tON = (VIN/35) x (CSS_nF/0.0023 - 100) us = 19.77 ms at 15.95 V (RT1987 DS soft-start formula, as quoted at ino:4855).
The conduction onset is therefore t_D_ON + tON = 27.77 ms at the typical t_D_ON of 8 ms (CALC). The RT1987 datasheet
gives no t_D_ON maximum (DD Table 11), so the 12 ms sensitivity value of DD Table 8a gives 31.77 ms (CALC). The onset is
BENCH: the bench check is V_bus and BT_CURRENT against the BT_BUS rising edge.

### 2.3 Behaviour of the share loop at the points of the sequence

- `powerBalance()` runs only in State 2 (ino:7944-7950); State 1 does not call it (ino:7826-7869). In variant P no share
  shift exists in the current firmware. The MDACs hold the split of the last Run (ino:7874-7880 comment). SOURCED.
- The in-band reference is clamped to [`DROOP_R_MIN` 0.15, `DROOP_R_MAX` 0.85] (fw v29, ino:14723-14726). The applied
  ratio slews at 0.02 per tick (`DROOP_RATIO_SLEW_PER_TICK`, ino:3242). While a channel reads dark (below
  `SHARE_HANDOFF_MIN_A` 0.10 A) or the filtered total is under the 0.25 A gate, it slews at 0.002 per tick for at most
  175 ticks (ino:3288-3325). SOURCED.
- The source selector arms only at a filtered total at or below 0.25 A with a rail command (inclusive 0.15 or 0.85),
  FC_CHARGE LOW, and no re-arm inhibit (ino:14107-14123). An FC selection is refused while `fcUvLockoutActive()` holds,
  that is 30 s after a purge-class dip (ino:2256, 14119-14130). DD section 12.12 item 3 keeps this lockout for share
  selection under OR-P. SOURCED.
- The design closed-loop bandwidth of the share loop is 30-60 rad/s, with the target "track EMS steps in < 100 ms"
  (`controller_design/system_model.md`:342). SOURCED as a design target, not as a measurement.

## 3. Pre-purge exit timeline

Table 1 lists the exit chain from the instant at which the prediction is visible to `chgModeTick()`. The assumption is
that the predictor output is evaluated every iteration, so the feed drop follows within one iteration. The worst
healthy case uses the p99 iteration (1.341 ms), one 9.76 ms iteration gap (facts_firmware section 8), the slow module
node (221 uF, 8.69 V edge) and t_D_ON = 12 ms.

Table 1. Exit chain on a purge prediction (times from the prediction).

| Event | Typical (median loop) | Worst healthy | Class | Source of the step |
|---|---|---|---|---|
| FC_CHARGE LOW (feed drop); eFuse off within microseconds | 1.13 ms | 1.34 ms | CALC | DD 9.7 exit step 1; facts_firmware 8 |
| Module node 15.95 V to the U_MS edge through R_MD 15 Ohm | 0.83-2.01 ms after the drop | 2.01 ms after the drop | CALC | DD R6-3 (R_MD, U_MS 8.69-9.15 V); C_mod 100-221 uF (DD Table 11) |
| Second pin-8 LOW read; pin 33 LOW written | 3.54-4.67 ms | 12.59 ms | CALC | DD 9.5 exit step 2 |
| Both S_GND on (pack bonded) | 3.84-4.97 ms | 12.89 ms | CALC | DD Table 11 (gate rise tau 88-114 us; "about 0.3 ms") |
| Bonded confirmation (two settled reads); BT_BUS written HIGH | 5.81-6.94 ms | 15.27 ms | CALC | DD 12.4 item 4; DD 9.7 exit step 4 |
| BT pass FET conducting (t_D_ON + tON) | 33.57-34.70 ms | 47.04 ms | ESTIMATE (BENCH) | ino:4853-4860; RT1987 DS 17.4/17.6 |
| Survivor blanking of BT_BUS ends (write + 30 ms) | 35.80-36.94 ms | 45.27 ms | CALC | ino:4869 |

The drain values are shorter than the DD Table 11 figures of 1.3-2.9 ms because an FC window starts the node at about
15.95 V, not at the 21.5 V of a regen pulse. The model neglects the module's own input current, which only speeds the
dump, so it is conservative.

When a step misses its deadline, the chain still ends in a defined state. A missed drain deadline (T_drain,max: the later
of 10 ms and 4 iterations, capped at 30 ms) latches `ERR_MOD_DRAIN`, and the sequence continues to pin 33 LOW (DD 9.5 exit
step 2). A failed bonded confirmation latches `ERR_CHG_EXIT` and enters State 99 (DD 9.5 exit step 4). The deadline bound
of the chain to BT conduction is therefore 93.26 ms (CALC: 30 ms drain cap, 30 ms confirmation cap, onset at
t_D_ON 12 ms). A chain that exceeds the bound has latched State 99 and does not re-close BT_BUS.

## 4. Share shift toward the battery

### 4.1 Mechanism in State 2 (variant D)

The shift can use the existing in-band path: a firmware override of `power_share_setpoint` to `DROOP_R_MIN`. The Youla
controller then tracks the FC fraction down to the clamp. Two bounds apply:

- **Typical.** The design bandwidth of 30-60 rad/s gives a 2 % settle of about 4/wc = 67-133 ms after BT conducts
  (ESTIMATE, first-order approximation of a design target). At full rate the slew limiter needs only 35 ticks
  (39.6 ms median loop) for the whole 0.85-0.15 band, so the limiter does not bind (CALC).
- **Worst.** BT reads dark at the re-close, so the reduced handoff rate applies: 175 ticks at 0.002 (span 0.35), then
  18 ticks at 0.02. This takes 218.3 ms at the median loop and 258.8 ms at the p99 loop from the BT_BUS write (CALC). The
  value covers the conduction onset of section 2.2.

The FC fraction that the loop holds at the window close is UNCONFIRMED. During the window BT_BUS is LOW but is not
claimed by the share latch (`assertFcChargeEnable(true)` clears `shareIsoBT` and `shareSpCutBT`, ino:12770-12771), so the
controller sees an actual share near 1.0. Read from the code, it can wind to the 0.15 clamp during the window; the shift
would then be complete at BT conduction. TODO(verify: host test of the ratio held at a window close).

A rail command (0.15 inclusive) at a filtered total at or below 0.25 A can re-arm the selector to battery-only, which
cuts FC_BUS through the setpoint latch (ino:14107-14123). This removes the FC from the bus for the purge. However, the
re-entry then needs the F1 disarm and the FC_BUS re-close, which measured 39.6-39.9 ms from the disarm to FC_CHARGE HIGH
on campaigns I and II (CLAUDE.md addenda; SOURCED for the HIL plant, BENCH for the board). A shift command strictly
inside the band (above 0.15) avoids the selector cut.

### 4.2 Mechanism in State 1 (variant P)

No shift mechanism exists in State 1, because `powerBalance()` is not called there (section 2.3). The load is the aux
load of about 0.09-0.15 A (facts_prior section 7). Any preemptive shift in Idle is new firmware: for example a State-1
call of the share loop, or a direct MDAC write under the existing slew doctrine. The slew arithmetic of section 4.1
then bounds it at 35-193 ticks.

### 4.3 What carries the bus during the purge

The bus survives the purge when BT_BUS conducts; the share shift is not needed for that. The existing bag analysis
(`calc/purge_seq_bags_output.txt` section 5, already computed for this study) found that 172 purges with FC_BUS and
BT_BUS both closed gave a V_bus minimum of 15.29-15.93 V, at pre-purge I_fc up to 0.712 A. Four FC-only purges fell to
12.89-14.62 V within the 50 Hz sample. The two-source result does not cover a pre-purge I_fc above 0.712 A, which
variant D can reach (up to the 1.25 A governor). BENCH: a two-source purge at I_fc 1.0-1.25 A. The operator's ruling (1)
asks for the shift in addition, so section 5 states both tiers.

## 5. Predictor interface: lead time T_lead

Table 2 states the requirement on the predictor. T_lead is the time from the "purge predicted" output to the purge onset.
An ideal predictor needs no allowance for prediction error; any real error band adds to Table 2.

Table 2. Minimum predictor lead time.

| Tier | Condition at the purge onset | Typical | Worst healthy | Class |
|---|---|---|---|---|
| Hard (variants P and D) | BT pass FET conducting, pack bonded, feed off | 34.7 ms | 47.0 ms | CALC with ESTIMATE onset; BENCH |
| Hard, deadline bound | Chain complete or State 99 latched | - | 93.3 ms | CALC |
| Full (variant D) | Share shift to `DROOP_R_MIN` complete | 101-168 ms | 274 ms | ESTIMATE; HIL-measurable |
| Full (variant P) | Not defined: no shift mechanism in State 1 | - | - | SOURCED (ino:7826-7869) |

The requirement for the operator's predictor is therefore as follows:

1. The "purge predicted" output reaches `chgModeTick()` at least 47 ms before the onset for bus safety, and at least
   274 ms before the onset when the share shift of ruling (1) must be complete in variant D.
2. When the deadline bound is used instead, the lead is at least 93 ms. A late chain then ends in State 99, which ruling
   (2) accepts as a safe collapse.
3. The predictor also reports the purge end (section 6). Firmware must additionally see V_fc at or above
   `V_FC_ARM_THRESH` 7.0 V (ino:2278) before the shift back.
4. A prediction must be suppressible: the predictor must not permit a window when the interval to the next onset is
   shorter than the re-entry chain of section 6 plus T_lead.

The worst hard-tier value rests on t_D_ON = 12 ms. Each millisecond of t_D_ON adds one millisecond to T_lead.

## 6. Earliest post-purge re-entry

### 6.1 Gates

Re-entry needs every DD section 9.7 entry condition. Three of them bind after a purge:

- **Purge end.** The onset plus 100-140 ms, plus 20 ms of edge uncertainty: 160 ms (facts_prior section 7). The FC
  recovery to a stable loaded rail after the dip is BENCH.
- **Shift back (variant D only).** Both channels are live, so the full-rate slew applies: 39.6 ms (median loop); the
  Youla settle is 67-133 ms (ESTIMATE). The shift back is limited to 0.85, because an FC selection stays refused by
  `fcUvLockoutActive()` for 30 s after every purge (ino:2256; DD 12.12 item 3). Entry step 5 then drops BT_BUS and moves
  the remaining BT share (at least 15 % of the load) onto the FC in one step.
- **VCHG-IN unfed.** Entry needs "V_chg below 11 V outside its blanking" (DD 9.7), and `ERR_VCHG_FED` is blanked for
  1.0 s after any pin-31 fall (DD 12.6). VCHG-IN decays only on its bleed (tau 0.984 s, TODO(calibrate)). The two
  readings are as follows:
  - **strict**: entry waits for the blanking to end, 1.0 s after the feed drop. This is the reading that keeps the
    stuck-feed check in service at entry;
  - **literal**: entry waits only for V_chg below 11 V, 365.6 ms after the feed drop from 15.95 V (CALC).
  Which reading DD intends is UNCONFIRMED. Under either reading this gate binds in variant P.

### 6.2 Entry chain

From the instant that the gates are met, the entry chain to charge current is 83.5 ms typical, 188.5 ms with the slow
cold start, and 201.8 ms worst (CALC). The chain is: pin 10, pin 5 and pin 33, two settled reads; BT_BUS LOW and
BT_CURRENT below 0.2 A (two iterations, ESTIMATE: the RT1987 turn-off after EN LOW is TODO(verify: RT1987 DS-00));
`assertFcChargeEnable(true)` (0.1 ms, ino:12773); D-BC-FC t_D_ON (8 ms, or 12 ms worst); the ramp to the eFuse UVLO
(1.07 ms); the eFuse turn-on and ramp (1.24 ms plus 3.6 ms, DD Table 11); and the Ag105 cold start of 65-170 ms
(facts_prior section 6; BENCH S0-6). `AG105_SETTLE_MS` (500 ms) gates only the register reads, not the charge
(DD Table 11). The cold-start figure was measured on the regen rig; its applicability to the FC profile at a 15.9 V input
is UNCONFIRMED.

Table 3 gives the resulting earliest resume of charge current, relative to the purge onset.

Table 3. Earliest resume of charge current after the purge onset.

| Variant | VCHG reading | T_lead used | Binding gate | Charge current resumes | Dead time per period |
|---|---|---|---|---|---|
| P | strict | 34.7-47.0 ms | VCHG blanking | 1.049-1.155 s | 1.084-1.202 s |
| P | literal | 34.7-47.0 ms | V_chg below 11 V | 0.414-0.520 s | 0.449-0.567 s |
| D | strict | 168-274 ms | VCHG blanking | 0.916-0.928 s | 1.084-1.202 s |
| D | literal | 168-274 ms | Purge end plus shift back | 0.377-0.495 s | 0.545-0.769 s |

Under the strict reading the dead time does not depend on T_lead, because the 1.0 s blanking starts at the feed drop and
outlasts the lead, the purge and the shift back in both variants.

## 7. Usable charge time per purge period

The usable charge time per 10.34 s period is the period minus the dead time of Table 3:

- variant P: 9.14-9.26 s (88.4-89.5 %) under the strict reading, and 9.77-9.89 s (94.5-95.7 %) under the literal reading;
- variant D: 9.14-9.26 s (88.4-89.5 %) under the strict reading, and 9.57-9.80 s (92.6-94.7 %) under the literal reading.

These figures are an upper bound set by the sequence alone. They hold only if the Ag105 starts in 65-170 ms on every
window. DD Table 11 also records a Bring-Up of about 8.4-11.7 s without a keep-alive (ML0227, sense shorted;
applicability to an isolated return UNCONFIRMED). The Ag105 datasheet gives no Bring-Up duration (facts_ag105 section 3).
If every cold start ran such a Bring-Up, the usable time would be 0.91-1.56 s per period at 8.4 s and zero at 11.7 s
(CALC). Gate S0-6, with S0-8b, therefore decides whether FC windows between purges deliver any charge at all.

At one window per period the transitions are 11.6 per minute, inside the [RER] limit of 20 per minute (DD 12.4 item 3).
`FC_CHG_MAX_MS` (30 s) does not bind, and `FC_CHG_COOLDOWN_MS` applies only after a 30 s dwell close (ino:15472-15480).

## 8. Variant D compared with variant P

The sequence itself does not make variant D unsafe. In variant D the feed drop removes the charger load (0.82-0.93 A of
input, DD Table 8 via `calc/purge_demand_budget.py`) from the FC before any other step, so the FC carries only traction and
aux load until BT conducts 35-47 ms later. However, variant D depends on four changes to the IC1 specification:

1. OR-O is reversed: the chokepoint "CHG_FC refused unless `mainState` is 1 or 98 with the motor command 0" (DD 12.4
   item 7) and the exits on any non-zero motor command or State-1-to-2 request (DD 9.7) must change.
2. The traction-request rule of the FC exit (hold the VESC at 0 A until the bonded confirmation, DD 9.7 exit step 1) is
   not needed for a purge exit, because BT_BUS stays open until the pack is bonded. A State-2 window needs its own exit
   rules for traction.
3. At entry, pin 33 rises (DD 9.7 entry step 3) while BT_BUS is still closed and BT carries at least 15 % of the load
   (the shift back stops at 0.85). For the 2-4 iterations up to entry step 5, that BT current returns through the Ag105
   sense in reverse. Within the variant-D budget the total load is at most 1.247 A minus the charger input, that is
   0.32-0.43 A, so the BT share is at most about 0.065 A bus-side. This is far below the U_C1 trip of 2.52-3.50 A
   (DD 9.6). CALC from SOURCED limits; the reverse-sense interval itself is part of the IC1 design.
4. Entry step 5 moves the BT share onto the FC in one step. The FC then carries the whole traction and aux load before
   the charger starts, which must stay below `OC_FC` (1.4 A, one sample, ino:2090).

Whether variant D is worthwhile is a demand-budget question. The demand sheet's calculation finds that windows are
admissible in 34.4 % of live time but coincide with an EMS request in only 4.5 % (nominal case,
`calc/purge_demand_budget_output.txt`, section 5 TOTAL line). That result is outside this sheet and is cited only for
orientation.

## 9. Observations for the design owner

1. **Survivor blanking and t_D_ON.** `SHARE_CUT_SURVIVOR_BLANK_MS` (30 ms) covers the conduction onset only at t_D_ON
   = 8 ms (27.77 ms). At t_D_ON = 12 ms the onset is 31.77 ms, beyond the blanking (CALC). The RT1987 has no specified
   t_D_ON maximum (DD Table 11), so a cut decision can still meet a dark survivor. This concerns every bus-switch
   re-close, not only the purge sequence.
2. **Idle inherits a share cut.** `doState3()` keeps the bus switches as they are and does not clear `shareSpCutFC`
   (ino:7961-7999). If a Run ends with the selector holding FC_BUS LOW, the variant-P entry condition "F1 conduction gate"
   (FC_BUS HIGH and unblanked) is refused in State 1, where no code releases the cut. TODO(verify: host test of a Run
   that ends battery-only, then an Idle window request).
3. **The VCHG-IN blanking dominates the dead time.** Under the strict reading, 1.0 s of every 10.34 s is lost to the
   `ERR_VCHG_FED` blanking, against 0.18-0.29 s for the whole purge, lead and shift. The literal reading recovers about
   0.6 s per period. The bleed tau and the blanking are both TODO(calibrate) at C-2.
4. **No shift in Idle.** Ruling (1) asks for a preemptive shift toward the battery. Variant P has no mechanism for it
   (section 4.2), and the bus does not need one at the aux load (section 4.3).
5. **First-order Youla settle.** The full-tier T_lead rests on a first-order reading of the 30-60 rad/s design
   bandwidth. The HIL can measure the shift on the existing plant, because the path is firmware-only.

## 10. Open items

| Item | Class | Where it is closed |
|---|---|---|
| BT_BUS conduction onset after a re-close onto a live bus (t_D_ON + CSS ramp) | BENCH | V_bus and BT_CURRENT against the BT_BUS edge |
| Ratio held by the share loop at a window close | TODO(verify) | Host test |
| Share shift duration from the re-close to `DROOP_R_MIN` | ESTIMATE | HIL leg on the existing plant |
| Two-source purge at pre-purge I_fc 1.0-1.25 A | BENCH | Bench purge with BT_BUS conducting |
| FC recovery after the purge to a stable loaded rail | BENCH | 1 kHz V_fc log |
| Intended reading of "V_chg below 11 V outside its blanking" | UNCONFIRMED | Design-owner ruling |
| VCHG-IN bleed tau | TODO(calibrate) | Gate C-2 |
| Ag105 cold start on the FC profile; Bring-Up on every cold start | BENCH | Gates S0-6, S0-8b |
| RT1987 turn-off after EN LOW (BT_BUS drop at entry) | TODO(verify: RT1987 DS-00) | Datasheet, then bench |
| Survivor blanking against a t_D_ON above 8 ms | TODO(verify: RT1987 DS-00) | Datasheet, then bench |
