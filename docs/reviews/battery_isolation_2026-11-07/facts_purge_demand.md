# Battery-isolation study: in-drive demand budget for FC windows between purges (2026-11-08)

## 1. Scope, rulings and sources

This fact sheet sizes the fuel-cell (FC) charge windows of design IC1 revision 8
(`detailed_design_IC1.md`, cited [DD]) between H-20 purges, for two variants:

- **Variant P** (parked): FC windows in State 1 or State 98 only, as [DD] section 9.7 and ruling OR-O specify.
- **Variant D** (in drive): FC windows also in State 2 between purges, at any speed, when the demand leaves room.
  **Variant D-s** is the subset of D that opens only at standstill inside State 2 (the option that [DD] ruling OR-O
  records and does not adopt).

The operator rulings of 2026-11-08 frame the work. (1) Firmware closes FC charging before and during a purge and shifts
the share towards the battery before the purge; FC charging occurs between purges when the EMS requests it. (2) The purge
predictor is outside the scope of this study and is taken as ideal; an unpredicted purge may collapse the bus and latch
State 99, provided that no component is damaged. This fact sheet therefore states the timing that the predictor must
provide (section 3) and does not model, measure or criticise the predictor. Purge facts are the facts_prior section 7
figures only: period 10.34 s, duration 100-140 ms, floor about 1 V.

All numbers in sections 2-7 come from `calc/purge_demand_budget.py` (output `calc/purge_demand_budget_output.txt`,
cited "out sN"), unless another source is named. The script reads the HIL plant (`tools/hil_plant_sim.py`,
`tools/gen_dp_ems_table.py`), the drive cycles in `references/drive_cycles/` and the HIL scenarios, the SDP policies in
`tools/sdp_policies/`, and the 22 Pi bags in `logs/rosbags/` (23 directories; one has no live Run samples).

Evidence tags follow [DD] section 0.2, with two additions:

- **PROVEN_CALC**: computed by the cited script from cited primaries; the result is no stronger than its weakest input.
- **MEASURED**: read from a recorded log (Pi bag or BLG) by the cited script.

## 2. The FC-window bus budget

In an FC window, Q_X1 holds BT_BUS open (EN_BE = p28 AND NOT FCQ, [DD] section 6 item 9), so the bus is FC-only. It
carries the traction current, the auxiliary load and the Ag105 input current. The binding steady ceiling is
LIM = min(P_MAX 1.247 A bus, governor 1.25 A) = 1.247 A; `OC_FC` latches at 1.4 A on one sample (ino:2090). The Ag105
draws (I_set + I_L) x V_pack / (eta x V_bus) on the FC profile, with I_set 1.25 A and I_L 0.30 A (ASSUMED, gate B8;
[DD] Table 8). Table 1 gives the traction allowance that remains.

Table 1. Traction allowance on the FC-only bus with the charger running (out s1; PROVEN_CALC on ASSUMED I_L and eta).

| V_pack | eta 0.88: charger bus current | Allowance at aux 0.09 / 0.15 A | eta 0.80: charger bus current | Allowance at aux 0.09 / 0.15 A |
|---|---|---|---|---|
| 7.4 V | 0.827 A | 0.330 / 0.270 A | 0.910 A | 0.247 / 0.187 A |
| 7.8 V | 0.872 A | 0.285 / 0.225 A | 0.960 A | 0.197 / 0.137 A |
| 8.0 V | 0.895 A | 0.262 / 0.202 A | 0.985 A | 0.172 / 0.112 A |
| 8.4 V | 0.940 A | 0.217 / 0.157 A | 1.035 A | 0.122 / 0.062 A |

The allowance is 0.06-0.33 A of bus current, that is about 1-4 W of traction. Rig cruise needs 0.187 A of traction at
1.0 m/s and 0.311 A at 1.5 m/s on the plant model (out s5); the Pi bags show a bus total of 0.298 A at 1.0 m/s and
0.443 A at 1.5 m/s (MEASURED, out s5). An in-drive window is therefore feasible at standstill, during coast and at slow
cruise only. Note that the INA253A1 zero error is up to 0.1 A per channel (SLOS954A section 7.5, as cited in the script),
which is of the same size as the allowance; the firmware decision to open a D window cannot rest on the measured current
alone with a margin smaller than that error (UNCONFIRMED for the fitted parts; BENCH).

The exit frees capacity at once. Exit step 1 drops FC_CHARGE and the eFuse turns off within microseconds ([DD] Table 11).
The FC alone then carries up to LIM - aux = 1.157 / 1.097 A of traction (aux 0.09 / 0.15 A) until BT_BUS conducts
(out s1). The single-sample margin from LIM to `OC_FC` is 0.153 A.

## 3. Interface requirement on the purge predictor

### 3.1 Lead time before the onset

The sequence before a predicted purge is fixed by IC1 ([DD] section 9.7 exit steps 1-4 and the key constraint that
BT_BUS re-closes only after the pack is bonded). Table 2 lists the chain from "purge predicted" to the onset.

Table 2. Exit chain before a predicted onset (out s2).

| Step | Nominal | Worst | Source and tag |
|---|---|---|---|
| Exit hold check after the feed-drop write | 0.15 ms | 0.15 ms | [DD] Table 11 |
| T_drain (module node LOW on two iterations) | 4.0 ms | 13.15 ms (deadline) | [DD] Table 11, calc6; BENCH S0-11 |
| Pin 33 LOW, bonded confirmation | 4.52 ms | 13.15 ms | [DD] Table 11 |
| BT_BUS conducting: t_D_ON + tON (CSS 100 nF at 16 V) | 8 + 19.8 = 27.8 ms (firmware blank 30 ms) | 12 + 19.8 = 31.8 ms | RT1987 t_D_ON typical only, no maximum (facts_prior s5); tON formula and blank, ino:4852-4869 |
| Share shift towards the battery once BT conducts | 20 ms | 50 ms | ~20 ms share-loop EMA (CLAUDE.md campaign G, F6); 50 ms ESTIMATE; BENCH |
| **T_lead,safety** (BT_BUS conducting at onset) | **38.7 ms** | **58.2 ms** | PROVEN_CALC |
| **T_lead,ruling** (share shifted at onset) | **58.7 ms** | **108.3 ms** | PROVEN_CALC on an ESTIMATE |

The BT_BUS term dominates. It is 27.8 ms, not the 8 ms t_D_ON alone, because the RT1987 reverse comparator holds the
switch off through its soft-start ramp onto a live bus (ino:4852-4862). The [DD] 13 ms figure applies to D-BT-SQ
(CSS 5.6 nF), not to D-BT-EN.

The requirement on the predictor is therefore: assert "purge predicted" at least T_lead before the onset, with
T_lead >= 58.2 ms for the safety condition and >= 108.3 ms for the ruling-(1) share shift at the worst chain timings.
Because the RT1987 t_D_ON has no specified maximum, the lead time cannot be closed by calculation. The firmware must
confirm BT_BUS conduction (for example a rising BT_CURRENT or a bus that holds when the FC current is shed) before the
predicted onset; a purge that arrives before the confirmation is then handled as an unpredicted purge (ruling 2). This
confirmation step is UNCONFIRMED as a firmware mechanism; it is not in [DD] section 9.7.

### 3.2 Earliest re-entry after the purge

The ideal predictor declares the purge end. A window then needs the entry chain of [DD] section 9.7 entry steps 3-7
(32.3 ms nominal, 44.2 ms worst: pin-33 confirmation, BT_CURRENT below 0.2 A, 100 us, D5 arming 2.8-6.1 ms, eFuse
1.24 + 3.6 ms) and the Ag105 start. Table 3 gives the time from the purge end to charge current.

Table 3. Re-entry after the predicted purge end (out s2).

| Item | Variant P | Variant D | Tag |
|---|---|---|---|
| Recovery declared by the predictor | 0 (ideal); 0.5 s sensitivity | same | ASSUMED (no primary gives the recovery time) |
| Share back to FC-only before BT_BUS drops | none | 110 ms nominal (selector dwell 250 ms from the pre-purge shift, ino:3466, then 20 ms) | PROVEN_CALC; the dwell applies only if the pre-purge shift is a selection change (UNCONFIRMED) |
| Entry chain | 32.3-44.2 ms | 32.3-44.2 ms | [DD] Table 11 |
| Ag105 cold start with R_KA | 65-170 ms | 65-170 ms | prior measurement (facts_prior s6); BENCH S0-6 |
| Ag105 Bring-Up without R_KA | 8.4-11.7 s | 8.4-11.7 s | [DD] Table 11; UNCONFIRMED for an isolated return |
| **Purge end to charge current, R_KA fitted** | **97 ms nominal** | **207 ms nominal** | PROVEN_CALC |

A further constraint comes from the VCHG-IN entry condition ([DD] section 9.7: "V_chg below 11 V outside its blanking";
Table 16 `ERR_VCHG_FED`, 1.0 s blanking after any pin-31 fall; bleed tau 0.984 s). The text admits three readings, and
Table 4 carries all three:

- **none**: the condition does not delay a re-entry;
- **v11**: re-entry waits until V_chg falls below 11 V, which is 353 ms after the pin-31 fall from 15.75 V;
- **blank**: re-entry waits until the 1.0 s blanking lapses.

The rule needs an operator or designer ruling. It costs at most 8 % of the parked rate (Table 4).

### 3.3 Per-period budget and the role of R_KA

Table 4 gives the charge-current time per 10.34 s purge period for a window that would otherwise stay open.

Table 4. Charge time per purge period, variant P (out s2, s3; PROVEN_CALC).

| Re-entry rule | Timing | Blocked interval | R_KA fitted: charge s / duty / mean pack current | No R_KA: charge s / duty / mean |
|---|---|---|---|---|
| none | nominal | 199 ms | 10.04 s / 0.971 / 1.214 A | 1.71 s / 0.165 / 0.207 A |
| none | worst + 0.5 s recovery | 748 ms | 9.38 s / 0.907 / 1.134 A | 0 |
| v11 | nominal | 353 ms | 9.89 s / 0.956 / 1.196 A | 1.56 s / 0.150 / 0.188 A |
| blank | nominal | 1000 ms | 9.24 s / 0.894 / 1.117 A | 0.91 s / 0.088 / 0.110 A |
| blank | worst + 0.5 s recovery | 1000 ms | 9.13 s / 0.883 / 1.103 A | 0 |

With R_KA fitted, the purge schedule costs 3-12 % of the charge time. Without R_KA, the Bring-Up of 8.4-11.7 s per
window consumes most or all of the 10.34 s period, so the FC window is worth at most 0.21 A. Ruling 9 (R_KA) therefore
decides the value of FC charging under every variant; the purge schedule does not.

## 4. Variant P: parked charge rate

Variant P charges only with the vehicle parked. Its mean pack current is 1.10-1.21 A with R_KA (1.10-1.21 Ah per parked
hour) and 0-0.21 A without R_KA (Table 4). Charging holds the CC current of I_set = 1.25 A only while V_pack is below the
CV knee; the [DD] section 9.7 entry gate admits windows only below 8.0 V until gate S0-8b, so a parked pack stops
charging at 8.0 V (TODO(verify: Ag105 DS) for the 2S CC-CV knee). A bench-supply window without purges is limited by
`FC_CHG_MAX_MS` 30 s and `FC_CHG_COOLDOWN_MS` 2 s (ino:2633-2634) to 1.168 A mean (out s3).

Variant P delivers 0 Ah per drive cycle, because a drive cycle runs in State 2 throughout, stops included
(ino:7919-7959; [DD] section 9.7).

## 5. Variant D on the drive cycles

### 5.1 Method

The plant demand model is `gen_dp_ems_table.build_demand(loss_map=None)`: F = M_EFF a + F_C sgn v + B_EFF v,
I_trac = max(0, F v) / (ETA_BOOST V_bus), with M_EFF 3.50 kg, F_C 2.00 N, B_EFF 0.534 N s/m and ETA_BOOST 0.85
(hil_plant_sim.py:331-335, 515). Three demand models bound the auxiliary load and the plant error:

- **plant**: traction + 0.09 A (I_AUX_A, hil_plant_sim.py:516);
- **IC1**: traction + 0.15 A ([DD] Table 8);
- **bag-calibrated**: 0.02 A + 1.311 x traction. The factor is a least-squares fit of the Pi-bag cruise totals at
  1.0, 1.5, 2.0 and 2.9 m/s; the per-speed ratios are 1.48, 1.36, 1.45 and 1.24 (MEASURED, out s5). The plant
  under-predicts the rig's traction current by 24-48 %.

A window is admissible where demand + charger bus current is at or below LIM and the purge schedule permits it. A run
of admissible time opens one window, pays the start cost (entry chain + cold start with R_KA + 20-50 ms share shift to
FC-only) and counts only if at least 1.0 s of charge current remains (T_MIN_USEFUL, a CHOICE equal to 2-6 regen captures,
facts_prior s6). The purge schedule is synthetic (period 10.34 s, blocked from T_lead,ruling before the onset to the
re-entry point), swept over 20 phases; the tables give the phase mean. Charge is I_set x charge time (CC).

### 5.2 Results

Table 5 gives the representative cases. "Nominal" is eta 0.88 with the nominal chain; "worst" is eta 0.80 with the worst
chain and the 0.5 s recovery sensitivity. Re-entry rule "none" is shown; rule "blank" lowers every D figure by 2-7 %
(out s4).

Table 5. Variant D and D-s per drive cycle, R_KA fitted, V_pack 7.4 V (out s4; PROVEN_CALC on the plant model).

| Cycle | Length | Standstill | Demand-OK (plant, nominal) | D charge, plant nominal | D, plant worst | D, bag-cal nominal | D, IC1 aux 0.15 at 7.8 V worst | D-s, plant nominal |
|---|---|---|---|---|---|---|---|---|
| 61 s cycle (ems-dp-replay) | 61 s | 10.1 % | 98.4 % | 57.1 s, 19.8 mAh, 1.17 A mean | 25.5 s, 8.9 mAh, 0.52 A | 28.2 s, 9.8 mAh, 0.58 A | 10.0 s, 3.5 mAh, 0.21 A | 5.5 s, 1.9 mAh |
| FTP-75 rig slice (ems-ftp75-*) | 345 s | 20.5 % | 55.6 % | 181.9 s, 63.2 mAh, 0.66 A | 127.2 s, 44.2 mAh, 0.46 A | 176.1 s, 61.1 mAh, 0.64 A | 79.9 s, 27.8 mAh, 0.29 A | 67.1 s, 23.3 mAh |
| ftp75c (ems-ftp75c-*) | 175 s | 21.6 % | 57.2 % | 93.4 s, 32.4 mAh, 0.67 A | 62.2 s, 21.6 mAh, 0.44 A | 87.7 s, 30.5 mAh, 0.63 A | 43.4 s, 15.1 mAh, 0.31 A | 35.7 s, 12.4 mAh |
| UDDS_trimmed_3.5mps | 333 s | 17.6 % | 46.3 % | 144.8 s, 50.3 mAh, 0.54 A | 97.9 s, 34.0 mAh, 0.37 A | 125.6 s, 43.6 mAh, 0.47 A | 67.0 s, 23.3 mAh, 0.25 A | 55.5 s, 19.3 mAh |
| RegenTest_v2_lowspeed | 152 s | 56.4 % | 68.6 % | 98.2 s, 34.1 mAh, 0.81 A | 88.5 s, 30.7 mAh, 0.73 A | 97.4 s, 33.8 mAh, 0.80 A | 84.8 s, 29.5 mAh, 0.70 A | 80.5 s, 28.0 mAh |
| RegenTest_decel_sweep | 183 s | 53.1 % | 63.9 % | 111.0 s, 38.5 mAh, 0.76 A | 101.1 s, 35.1 mAh, 0.69 A | 110.3 s, 38.3 mAh, 0.75 A | 98.7 s, 34.3 mAh, 0.67 A | 91.8 s, 31.9 mAh |

The purge-free fraction of the cycle is 97.0 % nominal and 92.3 % worst with rule "none", and 90.3 % with rule "blank"
(out s4). On every cycle except the 61 s cycle at the plant nominal case, the demand budget removes far more time
than the purge schedule: demand-OK is 46-69 % at the
plant nominal case on five cycles (98.4 % on the 61 s cycle) and falls to 19-64 % in the pessimistic case.

The 61 s cycle shows how narrow the margin is. Its cruise at 1.5 m/s draws 0.31 A of plant traction against an allowance
of 0.330 A (Table 1). The cycle is 98.4 % demand-OK at the plant nominal case and 47.8 % at eta 0.80 or with the
bag-calibrated demand, so its D charge halves (57.1 s to 25.5-28.2 s) on a 0.02-0.08 A change of an ASSUMED or
uncalibrated input.

D-s (standstill only) recovers 5.5-91.8 s per cycle. On UDDS it gives 55.5 s, which agrees with the [DD] OR-O estimate of
the two UDDS stops (20 s and 38 s). Cruise and coast windows (D minus D-s) add 58-115 s on the FTP-75 family and UDDS at
the plant nominal case, and 10-17 s in the pessimistic case (IC1 aux 0.15 A, 7.8 V, worst).

### 5.3 SDP and MPC charge cells

The demand that the EMS designates for charging is a subset of the admissible region. The SDP v7 policy places its
140 charge cells in demand bins 0-2 ([0, 3) W, edges 0.04 x 25 W; `tools/sdp_policies/sdp_policy_v7.json`), that is a
bus total below about 0.19 A, which is inside every Table 1 allowance at 7.4-7.8 V. The plant cycles spend 17.7-26.4 %
of their time below 3 W (out s4). The frontier policy SDP v6 has 0 charge cells, so variant D charges nothing under v6.
The campaign-II DP tables also commanded zero charge stages (CLAUDE.md 2026-09-09 addendum). MPC charge commits are
produced at run time and were not evaluated here.

## 6. Variant D on the recorded Pi sessions

The bags give the measured bus total I_fc + I_batt at 50 Hz, V_batt per sample and the EMS request (`charge_goal` on
`/ems_command`). The analysis applies the synthetic purge schedule to every session (10 phases), because the ruling
excludes further purge measurement; H-20 sessions are flagged by a median V_fc above 9.5 V. Table 6 gives the totals.

Table 6. Variant D on 22 Pi sessions, 2831 s of live Run time (out s5; MEASURED demand, PROVEN_CALC windows).

| Quantity | Nominal | Worst |
|---|---|---|
| D charge time, no V_batt gate | 967 s (34.2 %), 0.427 A mean | 875 s (30.9 %), 0.386 A |
| D with the 8.0 V entry gate | 650 s (23.0 %), 0.287 A mean | 587 s (20.8 %), 0.259 A |
| D-s with the 8.0 V gate | 600 s (21.2 %) | 560 s (19.8 %) |
| D with the 8.0 V gate and `charge_goal` > 0.05 | 127 s (4.5 %), 0.056 A mean, 44.2 mAh in total | 112 s (4.0 %), 0.050 A, 39.0 mAh |
| EMS request time (`charge_goal` > 0.05) | 447 s; 28.5 % of it yields charge current | 447 s; 25.2 % |
| H-20 sessions only (2368 s): D with the 8.0 V gate | 650 s (27.4 %), 0.343 A mean | 587 s (24.8 %), 0.310 A |

Three results stand out:

- The 8.0 V entry gate removes about one third of the D time: 11 of the 22 sessions spent less than half of their live
  time below 8.0 V, and 8 never went below it (out s5, column "Vb<8.0 %").
- Of the D time that passes the gate, 92 % is standstill (600 of 650 s). On the recorded sessions, D adds little to D-s.
- The EMS asked for charge during 447 s. Only 25-29 % of that request time can carry charge current, because the student's
  SDP requested charge in cruise at a demand that the FC-only bus cannot carry. The recorded EMS behaviour would
  therefore yield about 40-45 mAh over 47 minutes of driving (MEASURED request, PROVEN_CALC feasibility).

The bag figures carry the INA253A1 zero error of up to 0.1 A per channel (section 2), which is comparable to the
allowance; the standstill bus total of 0.02 A is a reading, not a proven auxiliary load.

## 7. Braking and traction requests inside a window

### 7.1 Braking

In an FC window pin 30 is LOW, so D-BC-RG cannot feed the charger and EF_EN does not depend on VOK
(EF_EN = FF1.Q AND PUMP_OK AND ((VOK AND p30) OR FCQ), EN_RG = p30 AND ..., [DD] section 6 items 5 and 10). The regen
energy therefore stays on V-MOT. D-MT-EN blocks V-MOT from VBUS (RT1987 reverse comparator -50 mV / 0.5 us,
facts_prior s5); the recorded regen pulses lifted V-MOT to 21.20-21.47 V with REGEN LOW, so V-MOT above VBUS by about
5 V is MEASURED (facts_prior s6). The VESC stops at about 21.35 V for 500 ms; the TL431/BSP170P chopper clamps at 22.13 V
and dissipated about 0 J per recorded event; the node holds 0.13-0.28 J at 0.97 mF (facts_prior s6). This is the same
behaviour as fw v37 today, where REGEN is held LOW (facts_firmware, "Today's effective behaviour").

Braking inside a window therefore needs no window exit for safety. The bus side does not see the regen energy, the BT
boost is behind an open D-BT-EN, and no back-feed path into a disabled TPS61288 opens (UNCONFIRMED until the VESC
behaviour at the V-MOT ceiling is measured, gate S0-R3 in facts_prior s6). The braking energy is lost, as it is today.

If Stage 2 is fitted and the EMS prefers regen capture, OR-7 forbids a direct FC-to-regen transition. The exit to the
bonded state takes 8.7-26.5 ms (out s6), after which the regen arm runs; the pulse rises in 19-47 ms, so the first pulse
is lost in most cases and the cold start of 65-170 ms can at best reach the tail ([DD] section 7.8). The policy cost is
small on the EMS cycles: the plant model shows 0.00 % braking on the 61 s cycle, FTP-75, ftp75c and UDDS (their
decelerations are gentler than coast-down) and 4.2-5.2 % on the two RegenTest cycles, where exiting on braking costs
6.1 s and 9.9 s of FC charge (out s4).

### 7.2 Traction requests mid-window

A D window exits when the demand would exceed the budget. The plant model gives 0.8-7.0 traction exits per cycle
(out s4). In no case did the demand exceed LIM - aux (1.097-1.157 A) within the 38.7-58.2 ms from the exit to BT_BUS
conduction ("capped 0.0" on every row), so no exit needed a torque cap on these profiles. The profiles are smooth
set-point traces; the fw v37 drive controller can step the motor current faster (feedthrough 0.214 A per m/s, [DD]
section 7.8). The exit must therefore be keyed on the commanded motor current before the VESC applies it, so that the
charger input is shed in the same iteration as the command rise. This is a firmware requirement of variant D, not a
measured result. A step that exceeds LIM by more than 0.153 A on one sample before the shed latches `OC_FC`, which is a
safe shutdown but ends the drive.

Variant D also changes the [DD] section 9.7 exit conditions: "any non-zero motor command" and "|v_actual| above the
standstill threshold" become the demand-budget exit, and the State-2 cruise branch that [DD] section 12.4 item 6 compiles
out is needed again. Before BT_BUS drops under traction, the share must move to FC-only; the FC-only selection is
refused for 30 s after every purge-class dip (`UV_FC_PURGE_LOCKOUT_MS`, ino:2256), which on a 10.34 s purge period
refuses it permanently. The predictor permit must therefore replace that lockout for the selector as well as for the
charge path (UNCONFIRMED as a firmware change; not in [DD] section 12.12).

## 8. Collapse rate on an unpredicted purge (context for ruling 2)

With the FC boost lost at the onset and BT_BUS open, the bus falls at I_load / C_VBUS (C_VBUS 35 uF,
hil_electrical.py:456, which reproduces the campaign-G figure of 2.57 V/ms at 0.09 A). Table 7 gives the time to the
12.0 V `LIMIT_V_BUS_MIN`.

Table 7. Bus collapse with the FC source lost (out s6; upper bound on the rate).

| Load | Rate | 15.9 V to 12.0 V | BT_BUS conduction 27.8 ms vs that time |
|---|---|---|---|
| Aux only, 0.09 A | 2.57 V/ms | 1.5 ms | 18 x longer |
| Parked window, charger + aux 1.075 A | 30.7 V/ms | 0.13 ms | 219 x longer |
| In-drive window at LIM, 1.247 A | 35.6 V/ms | 0.11 ms | 254 x longer |

No ride-through is possible inside a window: the bus is gone before any firmware reaction, so an unpredicted purge in
either variant ends in UV_BUS and State 99, as ruling 2 accepts. Whether that collapse is damage-free (the Ag105, the
eFuse and the bonded return on the recovery and the next power-up) is outside this fact sheet. The rate is an upper
bound: it assumes that the FC boost stops delivering at once; the dip slope is not resolved at 50 Hz (BENCH, 1 kHz V_fc).

## 9. Findings

1. **Predictor interface.** The predictor must assert "purge predicted" at least 58.2 ms (BT_BUS conducting) and
   108.3 ms (share shifted, ruling 1) before the onset at the worst chain timings; 38.7 / 58.7 ms nominal. The BT_BUS
   soft-start (27.8 ms) dominates. Because t_D_ON has no maximum, firmware must confirm conduction before the onset and
   treat a late confirmation as an unpredicted purge. (PROVEN_CALC; share shift ESTIMATE; BENCH.)
2. **Re-entry.** Charge current returns 97 ms (P) or 207 ms (D) after the declared purge end with R_KA fitted, unless
   the VCHG-IN entry rule delays it to 353 ms or 1.0 s after the exit; that rule needs a ruling. (PROVEN_CALC.)
3. **R_KA decides FC charging.** With R_KA, the purge schedule costs 3-12 % of the window time and variant P gives
   1.10-1.21 A mean. Without R_KA, the 8.4-11.7 s Bring-Up leaves 0-0.21 A. (PROVEN_CALC on a prior measurement and an
   UNCONFIRMED Bring-Up.)
4. **Variant P** gives 0 Ah per drive cycle by construction and 1.1-1.2 Ah per parked hour with R_KA below 8.0 V.
5. **Variant D is safe in the sense of the rulings and of limited worth.** The demand budget, not the purge schedule,
   limits it: 46-69 % of five cycles (98 % of the 61 s cycle) is demand-OK at the plant nominal case, and 19-64 % in the
   pessimistic case, against a purge-free fraction of 90-97 %. With R_KA it delivers 0.37-0.67 A mean on FTP-75, ftp75c and UDDS at the plant model
   (20-63 mAh per cycle), 0.25-0.31 A in the pessimistic case, of which D-s supplies 12-23 mAh. On the recorded sessions
   it yields 0.29 A mean (8.0 V gate), 92 % of it at standstill, and only 39-44 mAh where the EMS asked for charge.
   (PROVEN_CALC on the plant model; MEASURED demand in the bags.)
6. **The margin is thin.** The allowance (0.06-0.33 A) is the size of the INA253A1 zero error and of the plant-to-rig
   traction error (24-48 %); the 61 s cycle halves its D charge on a 0.02-0.08 A input change. Gate B8 (I_L), the
   2S efficiency and the current-sense offset decide the in-drive value. (BENCH.)
7. **Braking inside a window** is lost to the V-MOT node and the VESC stop, exactly as in fw v37; it needs no exit for
   safety. A Stage-2 policy that exits for regen costs 0 s on the EMS cycles and 6-10 s on the RegenTest cycles.
8. **Variant D firmware consequences:** the exit must be keyed on the commanded motor current; the predictor permit must
   replace `UV_FC_PURGE_LOCKOUT_MS` for the FC-only selection; the [DD] section 9.7 standstill exits and the section 12.4
   item 6 compile-out must be revised. (UNCONFIRMED; not in [DD].)
