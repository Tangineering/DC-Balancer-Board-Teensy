# Battle-test round 7: FMEA of the FC window between purges (IC1 revision 10)

## 1. Scope and method

This report attacks section 9.11 ("FC windows between purges") of `detailed_design_IC1.md` revision 10 and the seven
revision-10 changes of Table 0g (R10-1 to R10-7), with `calc/ic1_rev10_calcs.py` (calc10) and its output. The lens is
an FMEA of the window between purges under the operator rulings of 2026-11-08: the purge predictor is ideal and is not
attacked (OR-P), and a bus collapse that ends in State 99 without damage is acceptable (OR-SC). A bare collapse to
State 99 is therefore not a finding. The calculation script of this round is `calc/fmea_round7_calcs.py` (cited "r7"),
with its output in `calc/fmea_round7_calcs_output.txt`. Firmware citations are to
`teensy_controller/teensy_controller.ino` fw v37 rev 2 ("ino").

The round produced 1 major and 2 minor findings, and no blocker. Section 3 lists the failure modes that were examined
and gave no finding, so that a later round does not repeat them.

Table 1 lists the findings.

Table 1. Round-7 FMEA findings.

| ID | Severity | Title |
|---|---|---|
| FM7-1 | Major | Every D-s window needs a State-1/98 dump-check pass that no specified trigger produces; on every recorded EMS session D-s delivers 0 s |
| FM7-2 | Minor | The PI-4 late-prediction latch rests on a 9.24 ms loop-gap margin measured only on a State-98 build without Ethernet |
| FM7-3 | Minor | Gate W2b requires MDAC codes unchanged from the window close to the onset, which the design's own closed-loop tail contradicts; the fail action disables D-s |

## 2. Findings

### 2.1 FM7-1 (major): the D-s window has no reachable dump-check pass

**Claim.** Section 9.7b makes a dump-check pass in the current power cycle a precondition of every FC window, and
states that the dump check "runs in State 1 or State 98 only; a State-2 window (variant D-s) needs a dump-check pass
earlier in the same power cycle and is otherwise refused (Table 25, reason code 12)". Section 12.4 item 7 refuses
`CHG_CONFIG` (configuration check, dump check, probe) unless `mainState` is 1 or 98. The only trigger that the design
gives for the dump check is "before the first FC window of a power cycle without a configuration check" in State 1 or
98. The configuration check has its own trigger only as the proposed ruling OR-Z, which applies when `IC1_STAGE` is 2.
In a Stage-1 build, a session that goes from Idle to Run without an FC-window request in Idle therefore never obtains
a pass, and every D-s request of that power cycle is refused with code 12.

**Evidence.** r7 section 1 examines the six recorded Pi sessions that carry a charge request
(`charge_goal` above 0.05): in all six the first request comes 12-17 s after the first launch (67.5-72.4 s against
55.4-55.7 s), and none carries a request before the first launch, although the H-20 produced (V_fc above 7 V) for
53.6-55.2 s before it. The Pi telemetry carries no `mainState`, so the Idle part of that interval is not identifiable;
the conclusion does not depend on it, because no request exists at any time before the launch. The request-gated HR2
figures of revision 10 (D-s 107.3 s and 37.3 mAh, 24.0 % of the 446.6 s requested; Table 26, section 9.11.7, OR-O')
come from `calc/bt6_req_ds_request_gate.py`, which applies the standstill, request, V_batt and purge-block masks but
not reason code 12 (the script contains no dump-check term). With code 12 applied as specified, D-s carries 0 s on
every recorded session, and the adopted variant delivers nothing in Run.

**Failing scenario.** Stage-1 build with `IC1_FC_RUN_STANDSTILL` 1, the operator boots, the Pi starts an SDP drive
session, and the policy requests charge at stops in Run, as in `rosbag_sdp_2026-10-28_20-46-53`. Every stop is
refused with code 12; the HR2 claim for D-s is not met, and gate W2b cannot be run "inside drive sessions" unless the
procedure inserts an Idle window first.

**Proposed fix.** Specify the dump-check trigger for Stage 1: the mode manager starts the dump check of section 9.7b at
the first Idle dwell after a self-test pass when `IC1_FC_RUN_STANDSTILL` is 1 and no pass is recorded in this power
cycle, under the FC-window entry conditions and the purge permit (OR-Z extended to `IC1_STAGE` 1), with a State 1 to 2
request aborting it as the self-test abort does. Alternatively, admit the dump check in State 2 under the D-s standstill
conditions (it holds pin 32 LOW and the module output path is R_KA only, section 9.7b). In either case, state the
operating procedure (the H-20 running in Idle through one purge so that the permit is known, PI-4), add a host test
(boot, Idle, Run, first D-s request: no code 12), and re-run the request-gated HR2 figure with code 12 and code 4
applied.

### 2.2 FM7-2 (minor): the late-prediction latch margin is unmeasured on the production build

**Claim.** Revision 10 (R10-1, PI-4) latches `ERR_FC_ONLY_COLLAPSE` (State 99) when a prediction is first observed
with `purge_tto` below T_late = 61 ms inside a session that holds BT_BUS open. With T_lead,min = 80 ms, an ideal
announcement is observed at 70.2 ms or more only if the iteration before the observing iteration is at most 9.76 ms
long (calc10 section 1: margin 9.24 ms). Any single iteration longer than about 19 ms (80 ms less 61 ms) that ends at
the announcement converts a healthy, ideally predicted purge into a State-99 latch.

**Evidence.** The 9.76 ms figure is the worst of five gaps above 1.5 ms in one 422 s log, ML0226: fw v37, BENCH_TEST
1, State 98, a bench supply on the FC input (`docs/reviews/noise_fw37_2026-11-05/agents/vbus_blg1k.md` section 1;
facts_firmware section 8). That flash was a USE_ETHERNET 0 build (CLAUDE.md, 2026-11-04 addendum). The same source
records "TODO(verify): the State-2 loop period". Variant D-s runs in State 2 with the Pi link (USE_ETHERNET 1), the
50 Hz Ag105 poll in a powered module, and the revision-10 mode manager, none of which ML0226 contains. Section 12.4
item 5 records an iteration-time histogram at W1 and V2-4 but sets no criterion against T_lead,min less T_late. W2d
counts false latches, so a frequent false latch would be found; a rare long iteration at about 5.8 predictions per
minute would not be found in 30 min.

**Failing scenario.** D-s window open; a 20-25 ms iteration (an Ethernet service call or an I2C transaction, below the
40 ms pump threshold of PI-6) ends 70-75 ms before the onset; the first observing iteration reads `purge_tto` at 55-60
ms, under T_late; the board latches State 99 on a healthy predicted purge. This is a nuisance shutdown, not damage.

**Proposed fix.** Add a hard criterion to W1 and W2b: the maximum iteration on the production build (USE_ETHERNET 1,
State 2, Ag105 poll active, SD logging as flown) is at most T_lead,min less T_late less a margin, about 15 ms;
otherwise raise T_lead,min by the excess (a predictor requirement under OR-P). Record the iteration preceding every
prediction observation in the BLG so that W2d attributes any `ERR_FC_ONLY_COLLAPSE` to a long iteration or to a
source loss.

### 2.3 FM7-3 (minor): the W2b MDAC criterion contradicts the closed-loop tail

**Claim.** W2b (revisions 9 and 10) passes only if "MDAC codes unchanged from the window close to the onset", and its
fail action is "Keep `IC1_FC_RUN_STANDSTILL` 0". Section 9.11.3 states that the split at the onset "is recorded at W2b
and carries no requirement". At an auxiliary load at or above `SHARE_I_TOT_MIN_A` 0.075 A, the share loop in a D-s
window is in closed loop on the charger current and stays there after the feed drop until its EMA falls below the
open-loop exit: 40 ticks (45-54 ms) from 0.91 A at 0.09 A of auxiliary load and 57 ticks (64-76 ms) from 1.08 A at
0.15 A (calc10 section 4). The onset comes 78.7-78.9 ms after the feed drop (Table 21). In that tail, BT_BUS conducts
at 33.6-47.0 ms; both bus switches then read HIGH, so the fw v28 single-source hold of k_d ends and
`updateShareDroopScale()` slews k_d toward the schedule target, which exceeds `K_DROOP` below the 0.755 A crossover
(ino:13797-13810; a filtered total of 0.2-0.5 A gives r_lo 0.25-0.5). `applyShareRatio()` writes the slewed codes on
every closed-loop tick.

**Evidence.** calc10 section 4 (EMA tail); Table 21 (feed drop, conduction); ino:14287 (frozen return only when the
instantaneous total is below 0.075 A); ino:13797-13810 and the topology hold block that follows (k_d target).

**Failing scenario.** W2b on a vehicle whose standstill auxiliary load reads 0.09-0.15 A (the design's own Table 26
figure and the HIL plant value `I_AUX_A` 0.09 A): the codes move between the window close and the onset on a healthy
board, the gate fails, and the adopted variant is disabled. On the bag figure (0.016-0.024 A) the loop freezes on the
first sample and the criterion holds, so the outcome depends on an auxiliary load that W2b does not fix.

**Proposed fix.** Replace the criterion by the statement of section 9.11.3: record the codes and V_bus at the onset,
with the pass condition V_bus above `LIMIT_V_BUS_MIN` at the onset and no FC_BUS or BT_BUS write from the share latch or
the selector in the SC-8 interval. Record the standstill auxiliary load at W2b and state which of the two regimes
(frozen or closed-loop tail) applies.

## 3. Failure modes examined without a finding

The following modes were examined against the revision-10 text, the firmware and the earlier scripts. Each closes on
the evidence cited.

- **Unpredicted purge in entry steps 3-4 (pin 33 HIGH, BT_BUS HIGH).** The BT boost carries the auxiliary load through
  the reverse sense: 0.016-0.15 A bus-side (`calc/bt6_bag_launch_output.txt`; Table 26), against the U_C1 trip of
  2.52-3.50 A and the S0-10 reverse limit of 3.5 A. Step 5 then drops BT_BUS onto a dead FC; reading (b) latches and
  Table 23 applies. Not a finding (OR-SC).
- **Non-prediction exit with an unpredicted onset between the BT_BUS write and conduction.** This is the late-conducting
  D-BT-EN of row F59; r6 section 1 gives BENIGN or OPEN at the FC recovery for t_D_ON up to 100 ms. A traction release
  in the same interval draws at most 0.040 A in the first 60 ms of a recorded launch (`calc/bt6_bag_launch_output.txt`).
- **Launch during the purge interval with reading (b) armed (no dwell, 12.0 V).** The recorded launches draw at most
  0.451 A bus-side in the first 200 ms; a BT-only bus does not approach 12.0 V at that load. W2d records the minimum.
- **`busHotPlugUnsafe()` refusal at exit step 4 (R10-1).** The predicate is BT_REG HIGH and V_bus below 13.5 V
  (ino:13043-13045, ino:2317). After the feed drop the FC-only bus carries the auxiliary load only, and the entry
  condition already requires 13.5 V, so a healthy exit does not meet the predicate.
- **SC-8 ownership through the purge interval.** It refuses only pin-27/28 writes of the share latch, the selector and
  the load guard. No protective write of those owners is needed during a two-source purge; the State-99 teardown keeps
  its writes.
- **Pi loss.** In State 2 it latches `ERR_PI_TIMEOUT` (ino:7463-7471), which is the State-99 teardown of an open
  session. In State 1 a parked window continues on the last request (CC-B15, ruling OR-PK); this is a recorded exposure,
  not a new mechanism.
- **Request toggles at a stop ending the in-band substitution.** r7 section 2 finds no falling edge of the request at a
  stop in the recorded sessions, so the once-per-stop F1 disarm is not exhausted on that evidence.
- **Damage mechanisms D1-D11 under the PI-4 latch.** The 4860-case grid of calc10 section 5 reproduces as stated (no
  BT_BUS write after the onset, no peak above 2.5 A). No new path to the TPS61288 back-feed, RT1987 turn-on stress,
  Ag105 damage, the pack in charge mode with BT_BUS closed, or R_MD overload was found in the revision-10 changes.
