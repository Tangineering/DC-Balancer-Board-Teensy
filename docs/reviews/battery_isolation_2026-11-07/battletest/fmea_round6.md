# Battle-Test Round 6: FMEA of the FC Window Between Purges, Detailed Design IC1 Revision 9

Date: 2026-11-08. Target: `detailed_design_IC1.md` revision 9 (cited "DD"), in particular section 9.11 (Tables 20-27),
Table 0f (R9-1 to R9-7), Appendix G and the rows, faults and gates that revision 9 brought into line. Lens: FMEA of the
FC window between purges, with the operator's purge predictor taken as ideal (ruling OR-P) and the predictor itself not
attacked. Under ruling OR-SC a bus collapse that ends in a State 99 shutdown is acceptable and is not a finding; a
finding is a path to component damage, a hazardous pack configuration, or a false latch that makes the feature unusable
on a healthy purge train. Calculation script: `calc/fmea_round6_calcs.py` (output `calc/fmea_round6_calcs_output.txt`,
cited "r6 section N"). Other evidence: the firmware (`teensy_controller/teensy_controller.ino`, fw v37 rev 2, cited
"ino:line"), calc9, `calc/purge_collapse_sim.py` (cited "pc section N") and `calc/purge_seq_bags_output.txt`. Nothing
was ordered, built or flashed, and nothing outside this review folder was edited.

## 1. Scope and method

The window between purges was decomposed into the following sub-states: entry before the BT_BUS drop (entry steps 1-4),
entry after the BT_BUS drop (step 5 to `chargerHasPower()`), charging (`CHG_FC`), the pre-purge exit before the bond
(feed dropped, drain), the exit after the bond and before the BT_BUS write, the interval from the BT_BUS write to the
D-BT-EN conduction, the predicted purge itself with both sources closed, the share override and the shift back, and the
re-entry. Each sub-state was attacked with the following events: an unpredicted purge, a pin, latch or switch fault, a
late or failed BT_BUS re-close, a traction or regen request in State 2, a Pi link loss and a State 99 entry from another
fault. The share-loop behaviour at standstill was read from the firmware, not from the DD description.

Section 2 gives the findings. Section 3 gives the FMEA table by sub-state. Section 4 lists the items that were attacked
and cleared.

## 2. Findings

Table 1 summarises the findings. No blocker was found. The two major findings are a single-fault path that re-opens the
recovery race that policy E2 was adopted to remove, and a predictor-interface requirement derived from a share-loop
mechanism that does not run at standstill.

Table 1. Round-6 findings.

| ID | Severity | Title |
|---|---|---|
| FM6-1 | Major | A failed BT_BUS re-close in the pre-purge sequence leaves only the 20 ms UV_BUS dwell, so FC_BUS can still be HIGH when the FC recovers into a bus at 8.2-11.7 V (the hazard class H-R that E2 removed) |
| FM6-2 | Major | The share override R_OV and the shift back are no-ops at standstill: the open-loop feedforward clip holds the ratio below a 0.25 A total, so T_lead,nom 290 ms, the W2b R_OV criterion and the D-s re-entry figures of Table 22 rest on a walk that does not occur |
| FM6-3 | Minor | The State-2 exit releases traction at the BT_BUS write, 28-47 ms before D-BT-EN conducts; row F62 and gate W2b do not cover the launch on the FC-only bus, and the W2b 7 ms traction-delay criterion contradicts Table 21 |

### 2.1 FM6-1 (major): a failed BT_BUS re-close at a predicted purge re-opens the recovery race

**Defect.** The detector `ERR_FC_ONLY_COLLAPSE` stops at the BT_BUS re-close write of the exit (DD Table 16; DD 9.11.5
SC-1; DD Appendix G item 2). From that write to the onset and through the purge, the only bus detector is UV_BUS, which
latches after 20 ms of accumulated dwell below 12.0 V (ino:2163, ino:7369-7377; DD 12.6 item 5). The DD treats this
interval only for a **late** D-BT-EN (row F59) and states that UV_BUS "puts FC_BUS LOW about 22-23 ms after the onset,
before the earliest FC recovery at 80 ms" (DD 9.11.3 last paragraph). That figure assumes a step FC fall onto the
2.57 V/ms aux decay (pc section 1). The DD does not treat a BT_BUS re-close that **never** conducts. The following
single faults produce it:

- Q_X1 drain-source short: EN_BE_X is held at GND, so D-BT-EN never turns on. Row F40 lists only the open mode of
  Q_X1, and Q_X1 has no readback pin (DD Table 2 G7; it is checked at C-2 and B10 only).
- The FCQ net stuck HIGH after the feed drop: Q_X1 clamps EN_BE_X. `ERR_VCHG_FED` is blanked for 1.0 s after the pin-31
  fall (DD Table 16), which is longer than any T_lead.
- An open EN_BE_X lead or R_S28 (DD 5.5 item M4), or a failed RT1987 on D-BT-EN.

**Failing scenario.** A variant-P window closes on a prediction with T_lead,min 60 ms. The worst healthy chain writes
BT_BUS HIGH 15.27 ms after the prediction (DD Table 21), that is 44.73 ms before the onset. D-BT-EN does not conduct.
The bus stays FC-only with FC_BUS, FC_REG and MOT_PWR HIGH. The purge starts with the same FC fall-time sweep as pc
section 3b (0-75 ms; no primary gives the fall time, DD open item 34).

**Numbers (r6 section 1).** Over 54 cases (aux 0.5/15/150 mA on VBUS, V-MOT 0.48/1.5/5 mF, T_fall 0-75 ms), the UV_BUS
latch falls at 36.7-103.4 ms after the onset. At the 80 ms FC recovery, FC_BUS and FC_REG are still HIGH in 18 cases;
in 5 of them the bus is below 12.0 V (8.88-11.74 V, HAZARD class of pc section 3b). At 100 ms the count is 4 HAZARD
cases, lowest bus 8.22 V (aux 15 mA, V-MOT 5 mF, T_fall 75 ms: 12 V crossing at 84.3 ms, latch at 103.4 ms, FC_BUS LOW
at 104.7 ms). For comparison, policy E2 inside a window gives 0 HAZARD cases at 80 ms and 100 ms (pc section 3b), and
policy E1, which the DD rejected for this reason, gives 8-20 per 324 cases (pc section 3b). A **late** but working
D-BT-EN is safe: with t_D_ON up to 100 ms at 0.81 V/ms, and up to 80 ms at 0.50 V/ms, every case is OPEN or BENIGN at
80 ms, because the ramp catches the falling bus (r6 section 1). The hazard is therefore specific to a re-close that
does not conduct, which row F59 does not describe.

**Consequence.** The H-20 recovers through a boost whose EN is still HIGH into a bus at 8-12 V. This is the TP0010 class
(sags to 6.5 V with reconnect spikes above 3 A, recorded as nondestructive "Death-5-family stress",
`docs/boost-bringup-debug.md` 2026-08-11). Its severity depends on the TPS61288 restart after VIN UVLO with EN HIGH,
which no primary states (DD open item 33). The DD itself classifies this outcome as the hazard that policy E2 exists to
remove (DD 9.11.5, "Why not ride through"). The fault is latent: a Q_X1 short also leaves BT_BUS non-conducting outside
windows, so every purge in bonded Idle or Run meets the same UV_BUS-only race until the next power cycle. It is not
damage on the present evidence; it is a single-fault path into the stress class that revision 9 claims to have excluded
(Table 24 row D1 is stated for sessions only).

**Recommended fix (firmware, no hardware).**

1. Keep reading (b) of `ERR_FC_ONLY_COLLAPSE` (V_bus, no dwell, State 99) armed from the BT_BUS write of a
   prediction exit until the declared end of the purge (PI-2), and raise its threshold in that interval to 13.5 V, the
   window-entry floor. Recorded two-source purges held 15.29-15.93 V (`calc/purge_seq_bags_output.txt` section 5), so a
   healthy re-close keeps a margin of at least 1.79 V. With this rule r6 section 1 gives 0 HAZARD cases at 80 ms and at
   100 ms (8 and 6 IN-FAMILY cases with the bus at 12.0 V or more); at a 12.0 V threshold 1 HAZARD case remains (11.74 V
   at 80 ms, T_fall 75 ms).
2. Apply the same no-dwell rule while `purge_active` is TRUE in every state, not only after a window, so that a latent
   Q_X1 short or a failed D-BT-EN is caught at the first purge of the power cycle. The predictor is ideal by ruling OR-P,
   so `purge_active` is a valid key.
3. Add the Q_X1 drain-source short (and the FCQ-stuck-HIGH case after a feed drop) to Table 11 as a new row, with the
   rule above as its detector, and correct the F59 sentence "about 22-23 ms after the onset" to the swept range.
4. Add a W2c sub-step: with the Q_X1 gate jumpered to 3V3 (or EN_BE_X grounded), run one predicted purge from a
   bench supply on J-FC with a 60 ms supply fall, and require State 99 with FC_BUS LOW before the supply returns.

### 2.2 FM6-2 (major): the share override does nothing at standstill

**Defect.** DD 9.11.3 step 5 replaces the EMS setpoint with R_OV (just above `DROOP_R_MIN`) and DD 9.11.4 restores it
after the purge; DD Table 20 derives T_lead,nom = 290 ms from the share loop's dark-channel walk to R_OV (258.8 ms at
the p99 loop), and DD Table 22 charges variant D-s with a shift back of 39.6 ms plus a Youla settle of 67-133 ms. Variant
D-s is, by definition, at standstill, where the bus load is the auxiliary load of 0.09-0.15 A (DD 9.11.3). Below a
filtered total of 0.20 A the share loop is in open-loop mode (ino:14367; `SHARE_GOV_OL_HYST_A` 0.05, ino:3233), and the
open-loop path passes the setpoint through `shareFeedforwardClipTarget()` (ino:14495-14497). That function returns the
previous ratio unchanged whenever the band [lo, 1 - lo] with lo = `SHARE_MINORITY_I_MIN_A` / total (0.125 A, ino:3202)
is empty (ino:13772-13782). The band is empty at every total up to 0.25 A: lo is 1.389 at 0.09 A, 0.833 at 0.15 A and
0.500 at 0.25 A (r6 section 2). The closed-before HOLD returns before the feedforward when the setpoint has not
changed, and clears `shareClosedLoopRun` and falls into the same empty-band feedforward when it has (ino:14361-14374).
In both cases no MDAC code moves. The Youla controller does not run in open-loop mode, so the "Youla settle" of the
shift back does not occur either.

**Numbers (r6 section 2).** After the feed drop, the filtered total (alpha 0.05 per tick, ino:3330, ino:14292) falls
from the window value to below 0.20 A in 42 ticks (1.03 A to 0.09 A; 47.5 ms at the median loop, 56.3 ms at the p99
loop) or 61 ticks (1.25 A to 0.15 A; 68.9-81.8 ms). R_OV is applied at the bonded confirmation, 5.8-15.3 ms after the
prediction (DD Table 21). The closed loop therefore has at most about 33-76 ms with R_OV, while D-BT-EN is not yet
conducting (27.8-47.0 ms after the write, DD Table 21), so the BT channel reads dark and the walk runs at the handoff
rate of 0.002 per tick (ino:3292). At most about 0.07-0.12 of ratio is walked before the hold freezes it; the 258.8 ms
walk of Table 20 cannot complete. After the purge the shift back is applied in open-loop mode and moves nothing.

**Consequences.**

- The predictor interface over-specifies the lead time in State 2 by 230 ms (290 ms instead of 60 ms) on a mechanism that
  does not act. That is the main deliverable of this round (task item (a)): the operator would design the predictor to
  a requirement 4.8 times longer than the isolation needs.
- Gate W2b requires "share at R_OV before each onset recorded"; the recorded share will be the ratio held at the window
  close, so the gate either fails or records a value that the override did not set.
- The ratio at the onset is the one that the closed loop reached during the window. With an FC-only bus the delivered
  share is 1.0, so for an in-band command the fw v29 span clamp drives the output to 0.15 (ino:14723-14728); for an
  out-of-band command the latch freezes the last in-band ratio. The ratio is therefore usually already battery-leaning
  at the window close, which DD 9.11.3 records as UNCONFIRMED (open item 36). Safety does not depend on it: 172 recorded
  two-source purges held at least 15.29 V at a pre-purge I_fc up to 0.712 A against 0.09-0.15 A here.
- Table 22's D-s rows bind on "end of purge plus shift back" and give 0.573-0.785 s of dead time per period; without the
  shift back and with T_lead 60 ms, D-s binds on the V_chg gate as variant P does (0.450-0.569 s, calc9 section 2).

**Recommended fix.** State in DD 9.11.3 that at standstill the BT_BUS re-close is the whole shift of ruling (1), set the
D-s lead requirement to T_lead,min 60 ms, delete the override duration from Table 20 and Table 21 for D-s, and restate
Table 22, Table 26 and W2b accordingly. If the operator wants a defined battery-leaning ratio at each onset, specify a
direct MDAC write by the mode manager through `applyShareRatio()` (the path the State-98 open-loop write uses) at the
bonded confirmation, and add a host test that asserts the written MDAC codes at a 0.09-0.15 A total. Keep the
R_OV-in-band rule only as the selector guard (DD Appendix G row "Share-shift target"). Variant D (in motion), where the
total exceeds the gate, is not adopted (OR-DM) and is not affected.

### 2.3 FM6-3 (minor): traction is released onto an FC-only bus at the BT_BUS write

**Defect.** DD 9.7 exit step 4 re-closes BT_BUS and "release[s] the motor command" in the same step. D-BT-EN conducts
27.8-31.8 ms after the write at t_D_ON 8-12 ms, and 47.0 ms after the prediction in the worst healthy chain (DD Table 21).
A launch from a D-s window therefore draws its first 28-47 ms of traction from the FC alone, while `OC_FC` latches on
one sample above 1.4 A (ino:2090) and the fw v28 raw escape at 1.25 A acts on the selector only. Row F62 covers a
traction step inside the window, not this interval. The drive command can reach `MOTOR_I_CMD_MAX` 12 A on a speed step
(ino:3649); the bus power at near-zero speed is I^2 x R_motor plus the VESC loss, which no primary gives (UNCONFIRMED).
The result is a State 99 at worst (no damage path), but it would make D-s launches trip at random.

Two documentation defects sit in the same place. Gate W2b requires a traction delay of at most 7 ms at the p99 loop
(the V2-5 regen-window criterion), while DD Table 21 gives 15.27 ms from the trigger to the BT_BUS write in the worst
healthy chain. DD Table 21 also gives the survivor-blanking end (45.3 ms) before the worst healthy D-BT-EN conduction
(47.0 ms); the blanking of ino:4869 covers the conduction only for t_D_ON at or below 10.23 ms (r6 section 3), which open
item 32 already records.

**Recommended fix.** W2b records the peak FC_CURRENT from the BT_BUS write to the D-BT-EN conduction on each launch and
requires it below 1.25 A; the W2b delay criterion is restated against Table 21 (worst healthy 15.27 ms to the release);
row F62 gains the post-write interval.

## 3. FMEA by sub-state

Table 2 gives the result for each sub-state of the window between purges. "Accepted" means a bus collapse that ends in
State 99 with no damage path found (ruling OR-SC).

Table 2. Sub-state FMEA.

| Sub-state | Unpredicted purge | Switch, pin or latch fault | Late or failed BT_BUS re-close | Traction or regen request (State 2) | Pi loss | State 99 from another fault | Verdict |
|---|---|---|---|---|---|---|---|
| Entry steps 1-4 (pin 33 HIGH, BT_BUS still closed) | Bus held by BT; the charger is unfed; the BT boost draws from the pack through the sense in reverse (designed, OR-S). Step 5 then drops BT_BUS onto a purging FC (the permit is not re-checked at step 5), reading (b) latches | ERR_CHG_ENTRY on a failed confirmation | n/a | Exits the entry; motor held at 0 A | State 2: ERR_PI_TIMEOUT, State 99 (ino:7463-7470) | DD 9.9 order | Accepted |
| Entry step 5 to `chargerHasPower()` | FC-only aux bus collapses; reading (b) V_bus below 12 V latches | Q_X1 open (F16b): `assertFcChargeEnable()` and D5 | n/a | Exit before the feed | As above | As above | Accepted |
| Charging (`CHG_FC`) | DD Table 23/24; pc section 3: 0 HAZARD cases | FCQ stuck, eFuse bypass: existing rows | n/a | Exit keyed on the command (F62) | As above | DD 9.9 | Accepted |
| Exit, feed dropped, before the bond | Reading (b) (EF_EN L) latches | `ERR_MOD_DRAIN` continues to pin 33 LOW; `ERR_CHG_EXIT` enters State 99 without a BT re-close | n/a | Motor held at 0 A | As above | As above | Accepted |
| BT_BUS written, not yet conducting | Healthy D-BT-EN: the ramp catches the falling bus, BENIGN (r6 section 1) | Q_X1 short, FCQ stuck HIGH, EN_BE_X open: **FM6-1** | Late: BENIGN up to t_D_ON 80-100 ms; failed: **FM6-1** | Traction released onto the FC-only bus: **FM6-3** | As above | Both buses LOW, then the purge: collapse, accepted | FM6-1, FM6-3 |
| Predicted purge, both sources conducting | n/a (predicted) | A share-loop cut of FC_BUS: R_OV in band, no latch cut; BT survivor not cut (in-band) | n/a | v_setpoint step: normal State-2 traction on the two-source bus | As above | As above | Cleared |
| Share override and shift back | n/a | n/a | n/a | n/a | Override state across State 3 not defined (see section 4) | n/a | **FM6-2** |
| Re-entry after the purge | A purge cannot follow within the 1.262/1.492 s admission horizon under the ideal predictor | The literal V_chg rule refuses a fed VCHG-IN (F15, F17) | n/a | Refused (code 3) | As above | As above | Cleared |

## 4. Items attacked and cleared

1. **Damage on an unpredicted purge inside a window.** The pc grid (864 cases) and the 1296-case fall-time sweep give
   FC_BUS LOW before the recovery or the bus at 12.04 V or more in every E2 case (pc section 3b); the teardown order of
   DD Table 23 opens every bus switch and MOT_PWR before the boosts (ino:8320-8337). No new damage path was found in
   the window sub-states themselves.
2. **BT_BUS closed with the pack in the charge mode and the charger fed.** Entry steps 3-5 put the pack in the charge
   mode with BT_BUS closed but with the eFuse source term false; from step 6 Q_X1 clamps EN_BE_X in hardware and D5
   covers a D-BT-EN short. The pre-purge exit bonds the pack (step 3) before the BT_BUS write (step 4). No sequence of
   the window reaches the loop configuration on a single fault.
3. **Late (working) D-BT-EN.** Up to t_D_ON 80 ms at 0.50 V/ms and 100 ms at 0.81 V/ms, every case is OPEN or BENIGN at
   80 ms (r6 section 1). Row F59's verdict holds for a late re-close; only its "22-23 ms" figure is wrong (FM6-1).
4. **Pi loss.** In State 2 `checkPiWatchdog()` latches `ERR_PI_TIMEOUT` and State 99 (ino:7463-7470), which tears the
   window down in the DD 9.9 order; in State 1 and 98 a parked window continues, bounded by `FC_CHG_MAX_MS` and the
   predictor (DD 9.11.6). The predictor runs on the Teensy (PI-6), so a Pi loss does not blind it.
5. **Regen request at standstill.** `v_setpoint` 0 gives no braking command; a pushed vehicle gives an |I_cmd| above
   I_still, which exits the FC window before any regen arm, and the window types stay exclusive (DD 12.4 item 3).
6. **Selector re-arm at the override and the shift back.** R_OV is strictly in band, so the rev 5 re-entry rule cannot
   arm the selector at the window close (ino:14096-14111). At the shift back, a rail command restored in the closed-before
   region with the total under the gate can re-arm the selector battery-only (the fw v30 lockout forces BT) and cut
   FC_BUS (ino:14107-14139); the next window then waits for the F1 disarm and the latch's FC_BUS re-close. This is an
   availability cost of about one FC_BUS re-close per period, UNCONFIRMED (code reading only), and is left to the
   host test of open item 36.
7. **Override persistence.** DD 9.11.3 does not say what happens to a standing override when State 2 ends before the
   shift back. The shift back of DD 9.11.4 runs in `chgModeTick()` in every state, so the stored EMS value is restored
   at the purge end whatever the state; no defect follows if that is implemented as written. A host test should cover
   a State 2 to 3 transition with the override standing.
8. **R_MD and eFuse duty on a purge train.** One dump per period (DD 9.11.4) at 6.1-28.1 mJ (pc section 6) gives at most
   2.7 mW mean; one eFuse cold start per period is inside the revision-8 duty analysis. No new stress.
