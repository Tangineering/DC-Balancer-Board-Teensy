# Battery-isolation study: prior-study fact sheet (2026-11-07)

## 1. Scope and sources

This fact sheet extracts, from the earlier charger work, every requirement, ruling, measured number and lesson that
constrains a battery-isolation design which keeps the Silvertel Ag105 as the charger. It adds no new analysis; where it
draws a consequence for the isolation study, the consequence is labelled **IMPLICATION (UNCONFIRMED)**.

Source tags used below:

| Tag | Document |
|---|---|
| [EVAL] | `docs/charger_replacement_evaluation_2026-11-05.md` (round 2 plus the panel and critic rounds; whole file read) |
| [INC] | `docs/reviews/charger_eval_2026-11-05/incident.md` |
| [SPEC] | `docs/reviews/charger_eval_2026-11-05/spec.md` |
| [LOOP] | `docs/reviews/charger_eval_2026-11-05/round2/loop_analysis.md` (sections 0-3 read in full; later sections via [EVAL] section 2) |
| [REGEN] | `docs/reviews/charger_eval_2026-11-05/round2/regen_dynamics.md` (sections 0-3 read in full; sections 4-6 via [EVAL] section 3) |
| [WIRE] | `docs/charger_bq25798_wiring_design_2026-11-05.md` (skimmed: sections 0, B.5, F.4 head, G.3, H.7/H.9/H.10, selected test rows) |
| [RESPIN] | `docs/respin_power_architecture_2026-11-04.md` |
| [RER] | `docs/regen_enable_redesign.md` |

Each primary citation inside these documents (datasheet literature number and page) is repeated here as the prior study
gave it. This fact sheet did not re-open the primaries; a later fact-finding pass must verify any number that a design
decision rests on.

## 2. Requirements carried from the charger study

### 2.1 Hard requirements HR1-HR5

[EVAL] section 1.1 defines HR1-HR5. HR3-HR5 replace the earlier rule R3 ("the bus never feeds the charger in Run").

| ID | Requirement | Pass condition | Prior status [EVAL] 0.2 |
|---|---|---|---|
| HR1 | Regen harvesting (ruling 1) | The charger absorbs the mechanics-limited regen energy of a hard decel with the VESC not tripping: warm response within the section 3.2 tau budget; input >= 23 W at the threshold for a 3 -> 1 m/s, 12 A brake (peak 18.9 W) | UNDETERMINED |
| HR2 | FC charging (ruling 1) | Commanded charging from VBUS in an FC window, within the FC budget (governor 1.25 A, H-20 P_MAX about 1.247 A bus, OC_FC 1.4 A single sample, minus aux and traction), surviving H-20 purges | UNDETERMINED at system level |
| HR3 | No circular loop | No single fault produces a sustained bus -> charger -> pack -> BT boost -> bus current; a bounded single pulse per event is acceptable | PROVEN_CALC, conditional on interlock hardware |
| HR4 | No runaway | Charge and input current bounded by a hardware ceiling plus registers; no unregulated path | PROVEN_CALC (nominal) |
| HR5 | Fail-safe Teensy-commanded hard inhibit | Hard inhibit that defaults to inhibit with the Teensy unpowered, in reset, hung, or with I2C dead; no autonomous charge out of POR or from stored settings | BENCH_GATE |

### 2.2 Interface requirements H1-H12

[EVAL] section 1.1. These were written for a replacement charger on the Ag105 pads. Each row states whether it transfers
to an Ag105-retaining isolation design; the transfer column is an **IMPLICATION (UNCONFIRMED)**.

| ID | Requirement | Pass condition | Transfer to an Ag105-retaining design |
|---|---|---|---|
| H1 | Common ground, high-side sense, no unregulated path | VIN- = VBAT- one node, no shunt or FET in the return | Inverted: the Ag105 senses in Bat-, so an Ag105 design must instead route the pack return through VBat- (pins 14/15) and keep VBat- off GND |
| H2 | Hard charge inhibit while powered | Mechanism exists, covers trickle/pre-charge, latency within the [EVAL] 2.5 allowance (117-194 us at the regen input current) | The Ag105 has no charge-enable pin or register (CLAUDE.md 2026-11-04 addendum); the only proven inhibit is removing input power |
| H3 | Fail-safe (reset / hang / I2C dead / POR) | As HR5 | Applies unchanged to every new switch |
| H4 | Input-voltage threshold for always-powered regen | Settable 18.5-19.5 V at runtime, accuracy known; FC value about 13.5-15 V; draw <= 5-10 mA below threshold; no re-qualification on a dip; warm response per [EVAL] 3.2 | The Ag105 reg 0x02 threshold spans 11-33 V at about 0.088 V/count (CLAUDE.md section 3); warm behaviour unmeasured |
| H5 | FC charging from VBUS 15.9 V | >= 1.5 A at 8.4 V within the FC input budget; CV 8.400 V +/-0.5 % or better; termination | Applies |
| H6 | Voltage ratings / OVP | No OVP drop-out at the 21.4 V measured peak / 22.13 V design clamp; abs max >= 30 V (36 V preferred) | Ag105 abs max 36 V ([SPEC] 2.2, Ag105 DS p.19) |
| H7 | Battery pin through D-BT-SQ | Starts into an open/capacitive VCHG; no lockout; CV error known | Applies; see section 8.1 |
| H8 | Inrush / hot-plug | On the RT1987-ramped node (12 mA/uF with 5.6 nF CSS): peak <= 1.0 A with aux; no electrolytic; no switching during the ramp | Applies to every new switch that closes onto capacitance |
| H9 | I2C / logic / status | 3.3 V open-drain, 100 kHz, no back-powering, status on pin 6 | Already met by the fitted Ag105 |
| H10 | Thermal / efficiency / wiring / mechanical | <= 2 W loss; off-board mount feasible | Applies to the switch board |
| H11 | Availability | In stock today from a primary vendor page | Applies to new parts |
| H12 | Telemetry | Charge current and input V/I readable by the Teensy | Ag105 reg 0x06 (0.011 A/count) reads only the share of current through its internal shunt ([INC] (a)) |

## 3. Operator rulings 1-10 ([EVAL] section 0.1; [WIRE] section 0.1)

1. Regen harvesting AND fuel-cell charging are both hard requirements. A charger that does only one, or catches only the
   tail of regen bursts, fails.
2. Path A (no re-spin) is strongly preferred but must be shown fully feasible before committing.
3. R3 is replaced by "no adverse behaviour": no circular charging loop (bus -> charger -> pack -> BT boost -> bus) and no
   runaway or unregulated charge current. R3 existed only because the Ag105 cannot be stopped from charging while powered.
   It may be relaxed **only if** the charger has a reliable, Teensy-commanded, fail-safe way to prevent charging while
   powered. The operator accepted the always-powered design (REGEN held closed through Run, threshold between the bus
   maximum and the regen clamp, independent backstops).
4. The PCB and battery survived the 11-13 A incident; Stage-0 damage checks are considered passed. A scope-armed bring-up
   before the first charger session remains good practice.
5. An MCU hardware watchdog (Teensy 4.1 WDOG1 / RTWDOG) is required future work and must be recorded in any feasibility
   study.
6. FC charging only in the windows between H-20 purges; a predicted purge interrupts the window so the battery is back
   on the bus before the dip.
7. Regen and FC charging may run concurrently (IO CSV row-31 amendment pending, not made). Mechanism: regen lifts V-MOT
   above VBUS, D-BC-FC is reverse-biased; BT_BUS is open in this mode, so the pack cannot form a loop.
8. The BT-current trip residual is accepted for now: INA253 floor about 0.1 A, residual loop up to about 0.29 A.
9. The 1 kOhm VBT -> VCHG keep-alive resistor is a last resort only (it worsens the energy statistics).
10. Assumed part for Path A: the BQ25798EVM.

Rulings 9 and 10 are specific to the replacement path. Ruling 3's relaxation clause is conditional on a charger-side
inhibit, which the Ag105 lacks, so for an Ag105 design **R3 in its original form ("the bus never feeds the charger")
still stands unless the isolation switch itself supplies the fail-safe inhibit** (IMPLICATION, UNCONFIRMED).

## 4. The 2026-11-04 incident and the Ag105's actual behaviour

### 4.1 Mechanism ([INC] (a); [EVAL] 1.0)

- Loop: bus -> D-MT-EN -> V-MOT -> D-BC-RG -> VCHG-IN -> Ag105 -> VCHG -> D-BT-SQ -> VBT -> (pack, BT boost) -> bus.
- Bus current (I_fc + I_batt) rose near-linearly at about 10.6 A/s to about 11.4 A in 1.02 s (ML0227, 23.70-24.72 s,
  MEASURED). Ag105 reg 0x06 read 0.011-0.033 A throughout.
- Estimated Ag105 output 11-13 A, 4.6-5x its 2.5 A setting, with 15-45 W loss for under 1 s (UNCONFIRMED energy balance).
- Termination was the Ag105 input UVLO (11 V, VLOCK, Ag105 DS p.19) after the bench FC supply dropped out; BT boost
  reached 16.46 A, bus 6.84 V, within about 4 ms. No current limit acted.
- Root cause, UNCONFIRMED by direct measurement but fitting every observation: the Ag105 current sense sits between Bat-
  and Load-/Vin- (Ag105 DS V1.1 Fig. 1 p.3); VBat- (pins 14, 15) "Must NOT be connected directly to the GND pin" (Table 2
  p.4); VLoad- (pins 16, 17) is internally connected to Vin-. The board ties VBat- to GND, so the GND pour parallels the
  shunt and the module has no working output-current limit.
- Refuted alternatives: D-BT-SQ reversed (the .brd shows VIN on VCHG), Ag105 internal short, bench-supply fault, RT1987
  limiting (its SCP runs only during soft-start, RT1987 DS-00 section 17.5).
- Pack resistance from the collapse instant: about 24 mOhm (MEASURED inputs, UNCONFIRMED R).

### 4.2 What the Ag105 can and cannot do (as established by the prior work)

| Property | Fact | Source |
|---|---|---|
| Current sense location | Bat- leg, between Bat- and Load-/Vin- | Ag105 DS Fig. 1 p.3, via [INC] |
| Protections on that sense | Over-current trip at set current + 200 mA (DS p.18); output short and partial-short behaviour (DS p.19); Bring-Up "Battery Detection" (DS p.6). All read the same sense, so all were defeated by the GND tie | [INC] (a) |
| Bring-Up | Output ramped gradually while it monitors current; normal charging only after 10 % of set current is seen (0.25 A at 2.5 A); with no draw it reports battery disconnect and repeats | DS p.6, via [INC] |
| Observed Bring-Up slope | About 0.64 V/s from about 2 V into the open VCHG node; about 11.7 s to pass the 7.67 V pack | ML0227 serial, [INC]; [SPEC] 5 |
| Input UVLO | 11 V (VLOCK) | DS p.19, via [INC] |
| Charge enable | **No charge-enable register or pin**; cannot be stopped from charging while powered | CLAUDE.md 2026-11-04 addendum; ruling 3 rationale |
| MPPT_DISABLE (pin 5) | Active-LOW inhibit of the MPPT loop; semantics during charging `TODO(verify: Silvertel)` | CLAUDE.md sections 3 and 2026-11-04 addendum |
| Input threshold | Reg 0x02, 11-33 V, about 0.088 V/count; EPROM-persistent (it held 12.85 V, below the bus, on the incident board) | CLAUDE.md section 3; [SPEC] 3.1 |
| Defaults without resistors | 4.2 V / 1000 mA; firmware writes reg 0x01 = 0x08 (8.4 V) and reg 0x00 = 0x01 (2500 mA) | CLAUDE.md section 3 |
| Starts from stored settings | Yes: it starts on reset from NV settings; [SPEC] 3.1 classes this as "not acceptable" for a replacement | [SPEC] 3.1 |
| Speed | Slow; 500 ms `AG105_SETTLE_MS` lazy configuration; cold start never catches a regen pulse (section 6) | CLAUDE.md section 3; [REGEN] 0 |
| Abs max input | 36 V | DS p.19, via [SPEC] 2.2 |
| Input capacitance advice | 470 uF across the input for long leads (DS p.6); at 12 mA/uF that is 5.6 A, a Death-5-class hot-plug | [SPEC] 6 |
| Protected packs only | The Ag105 datasheet supports only protected packs | DS p.18, via [SPEC] 0.4 |
| Efficiency, ripple | 0.88 typical (DS p.20); 100 mVp-p output ripple spec (DS p.20) | [INC] (b); [SPEC] 2.2 |
| Telemetry | Reg 0x06 charge current 0.011 A/count; reg 0x07 tracked V_in correctly during the incident | [INC] (a) |

[INC] (b) concludes that a common-ground charger with high-side or input-side sensing removes the incident's root cause.
The converse holds for the Ag105: **the root cause is removed only if the pack return passes through VBat- and VBat- is
not paralleled by any other path to Vin-/GND** (IMPLICATION, UNCONFIRMED). [INC] "Open measurements" item 1 asks for the
out-of-circuit VBat- to Vin- resistance; Silvertel has not confirmed the shunt location or value (`TODO(verify:
Silvertel)`).

## 5. Board topology facts the isolation design must respect

- **Charger power entry:** only VCHG-IN, behind D-BC-FC (VIN = VBUS, EN pin 31) and D-BC-RG (VIN = V-MOT, EN pin 30).
  With both EN LOW the charger has no power ([SPEC] 0.1).
- **Charger output:** VCHG -> D-BT-SQ (RT1987, VIN = VCHG, VOUT = VBT, EN pin 32) -> VBT = pack positive. D-BT-SQ blocks
  pack -> VCHG (TRCB) ([SPEC] 0.2; [LOOP] 2).
- **Pack negative = GND:** J-BT pin 2, the Ag105 VIN- and VBAT-1/2, REG-BT GND and the BQ29200 VSS are all net GND; the
  board is 2-layer with full GND pours on both layers and 288 GND vias ([INC] (c)).
- **Second pack-negative bond:** J-BL pin 3 (balance-lead negative) is also on GND, 26 mm from J-BT pin 2. If the J-BT
  negative loosens, the whole pack return (up to about 15 A) moves onto the balance lead, a fire hazard ([INC] (c)).
  **IMPLICATION (UNCONFIRMED): any switch or sense element placed only in the J-BT negative is bypassed by the J-BL pin-3
  bond unless that bond is also broken or switched.**
- **The pack can reach VBUS only through D-BT-EN; bus energy reaches the charger only through D-BC-FC, or D-MT-EN then
  D-BC-RG; motor energy reaches the charger only through D-BC-RG** ([LOOP] 2).
- **Teensy supply:** LM1084 (REG-5V) input on VBT, i.e. battery-derived ([LOOP] 2; [SPEC] 1; [RESPIN] option 2).
- **Pack-referenced measurements:** V_batt divider R1-BT 16.2k / R2-BT 10k (gain 1.62 on ground shift) at (31.5, 22.6);
  INA253 SNS-BT on VBUS-BT, output referenced to its own GND pin; BQ29200 cell taps via J-BL ([INC] (c)).
- **BQ29200:** OVP 4.35 V/cell +/-25 mV = 8.70 V pack, delay 2.0-4.0 s with CBLD 0.33 uF (6-12 s/uF, 0-60 C, capacitor
  tolerance excluded), about 3.0 s nominal (SLUSA52C p.5). OUT goes to the orphan net `BAL-NOK`: **no hardware pack-OV
  action exists on the board** ([EVAL] 1.0; [SPEC] 0.4). The [WIRE] r6 design added a carrier term that uses BQ29200 OUT
  to drop /CE (1.6-4.9 s response).
- **Ground-shift amplification in rail ADCs:** CHG 7.87x, BUS 4.64x, FC 2.74x, BT 1.62x; treat V_chg as +/-0.1-0.3 V under
  heavy return current ([INC] (c)).
- **Spare Teensy pins (not in the CSV):** 10 (J1.23/24), 16, 17, 20-23, 33 (J2.47/48), 34 (J2.45/46). Pins 2 and 8 still
  carry RENC pull-ups. Any new use goes into the CSV first ([SPEC] 1; [EVAL] 1.0). WDOG1_B may be routed only to pin 20,
  never pin 19 (SCL) ([EVAL] 5.1; [WIRE] G.3).
- **RT1987 facts used everywhere:** VFWD 35 mV, fast reverse comparator -50 mV / 0.5 us, tD_ON 8 ms, tON 1.9 ms at 28 V
  (all typical only, DS-00 p.7, section 17.6); 8 A continuous, 20 A peak for 10 ms at 2 % duty, OTP 140 C (DS-00 p.6);
  R_ON 20 mOhm; SCP 2.5 A start, 250 us timer, 64 ms retry, **disabled after tON** (section 17.5); auto-restart without
  soft-start after a TRCB condition clears (section 17.4 Table 1); UVLO rising 3.0-3.35 V (p.7); EN internal pull-down
  475-985 kOhm plus the 10 kOhm bodge pull-downs, VEN_F >= 0.6 V min, VEN_R <= 1.4 V max (p.7).

## 6. Regen capture numbers ([REGEN] sections 0-3; [EVAL] section 3)

| Quantity | Value | Source |
|---|---|---|
| V-MOT pulse | 15.9 -> 21.20-21.47 V true in 19-47 ms, onset within about 5 ms of `I_cmd` going negative | 9 BLGs + RegenTest_v2 bag |
| VESC stop | At about 21.35 V (mean measured peak); linear decay 14-20 V/s with no regen current; second pulse 0.523-0.562 s later (mean 0.535 s, 8 events) | [REGEN] 0, 1.1 |
| Stop mechanism | VESC over-voltage fault plus `MCCONF_M_FAULT_STOP_TIME` 500 ms (vedderb/bldc `mcconf_default.h` line 546); UNCONFIRMED until M-R0 reads the EDU's `l_max_vin` | [EVAL] 3.1 |
| Burst length | 0.3-0.6 s above bus; the true pulse is 30-50 ms, the tail is node capacitance draining into VESC housekeeping | [EVAL] 3.1; [SPEC] 2.1 B |
| Chopper | TL431/BSP170P, design clamp 22.13 V, R-SHUNT 47 Ohm (about 0.46-0.47 A); dissipated about 0 J per recorded event | [REGEN] 0 |
| Node energy today | C x (134-292) J/F: 0.13-0.28 J at 0.97 mF, 0.54-1.17 J at 4 mF | [REGEN] 0, 1.2 |
| V-MOT capacitance | Board about 0.48 mF (CAL 470 uF + C-D6/C-D7); VESC unmeasured; two weak checks point to about 4 mF; range 0.48 to about 5 mF (M-R1) | [REGEN] 2 |
| Energy available if braking continues | 2 -> 1 m/s: 2.09 J at V-MOT, 1.81 J into the pack (215 mC), 11.1 W peak, 0.30 s; 3 -> 1 m/s: 6.32 J / 5.55 J (661 mC), 18.9 W peak, 0.58 s; 2 -> 1 m/s at 5 A: 2.17 J / 1.83 J over 0.53 s | [REGEN] 0 |
| Capture cliff | 96-99 % if the charger reaches current before V-MOT climbs from Vth to about 21.35 V; else the VESC trips and capture is 6-40 % | [EVAL] 3.2 |
| Warm-response requirement | tau_warm <= 4 ms (10-90 % <= 9 ms) at 0.97 mF; <= 2 ms at board-only C; about 20 ms if 4 mF is confirmed; about 60 ms if the VESC cut-off is raised | [EVAL] 3.2 |
| Cold start | 65-170 ms; never catches the first pulse on this rig | [REGEN] 0 item 6 |
| [WIRE] tightened budget | t_d + tau <= 0.33 ms (0.4 mF) / 0.80 ms (0.97 mF) once the 0.12-0.19 Ohm input-path resistance is counted; criterion V-MOT peak <= 20.5 V | [WIRE] H.7, T-B-09 |
| Levers | Raise VESC `l_max_vin` to about 23-24 V (needs C-D8/C-D10 >= 35 V); add V-MOT capacitance (about 4 ms per mF at Vth 19 V, but about 0.65 A extra D-MT-EN soft-start current per mF) | [EVAL] 3.2 |
| EMS value | 0.2-0.66 C per hard decel = 1.2e-5 to 3.7e-5 SoC on a 5 Ah pack (capacity unverified) | [EVAL] 3.2 |
| Delivered vs commanded | August logs measured about 6 % of a -12 A command delivered; the mapping is uncharacterised | [RER] 3 |
| Decisive gate | S0-R3 / T-E-03: does the VESC keep braking with V-MOT held at 19 V? Decides regen for any charger | [EVAL] 6.1; [WIRE] 0.2 |

## 7. FC-window problems ([EVAL] 3.4, 0.2; [WIRE] F.4; [INC] (b))

| Item | Fact |
|---|---|
| Purge depth | The H-20 purges to about 1 V (CLAUDE.md fw v30, bench 2026-09-15); Pi bags show about 1.8-2.3 V at 50 Hz and low load |
| Purge timing | Period 10.34 s, duration 100-140 ms (22 Pi bags, +/-20 ms per edge); load dependence unknown |
| Boost input floor | TPS61288 VIN minimum 2.0 V (SLVSFP3C ROC) |
| Bus collapse | With BT_BUS LOW the bus falls at about I_AUX/C_VBUS = 2.57 V/ms (campaign G); UV_BUS latches after a 20 ms dwell inside a 100-200 ms purge |
| Bench evidence | 2026-10-28: UV_FC + UV_BUS latched within seconds of the first window; fw v35 v33b refuses windows on a running stack (ino about 15483-15499) |
| Governor ceiling | 1.25 A |
| H-20 P_MAX | 23.416 W stack = about 1.247 A bus |
| OC_FC | 1.4 A, single sample (`LIMIT_I_FC_MAX`, ino 2090); firmware raw I_fc > 1.20 A arm drop |
| Aux load | About 0.1-0.15 A |
| Budget consequence | With BT_BUS LOW the FC alone carries traction + aux + charger; FC charging is standstill-weighted (about 0.1-0.25 A traction headroom at a 1.0 A charger input) |
| Cold FC close | 70.2 uF x 12 mA/uF = 0.84 A + 0.15 A aux = 0.99 A from an FC-only bus (1 % margin): forbidden |
| Firmware state | `FC_CHARGE_ALLOWED 0` in fw v31-v37 |
| Topology options offered | (a) BT hot standby with a BT_ACTIVE permit; (b) bus hold-up of about 7.5 mF for 0.15 A over 200 ms at <= 4 V sag; (c) windows synchronised to the purge schedule (ruling 6 chose (c)) |
| Watchdog dependence | A Teensy hang inside a window leaves BT_BUS open through the next purge; [WIRE] makes the RTWDOG forced-hang test T-W-01 a precondition of every FC window (target 50 ms against a 100-140 ms purge) |

## 8. The prior rating of "switch both battery legs" and its objections

[RESPIN] section 1 rated option 2, "Switch BOTH battery legs off the PCB while charging", as the **weakest** of four
re-spin options. The objections, verbatim in substance:

1. The bus needs another source during every charge window, which can only be the FC, and the FC purges to about 1 V.
2. The Teensy is powered from the battery regulator (LM1084 off VBT) and would brown out.
3. The pack cannot buffer bus transients.
4. Every regen event costs two switch transitions plus a charger bring-up.
5. The BQ29200, the V_batt divider and the BT current-sense ground references move.

Related constraints from the other documents that bear on the same objections (IMPLICATION, UNCONFIRMED where stated):

- Objection 1 is the [EVAL] HR2 purge blocker in section 7 above; it applies whenever BT_BUS is open, not only when the
  pack is disconnected.
- Objection 4 interacts with the capture cliff: a 0.3-0.6 s burst whose first pulse ends in 19-47 ms leaves no time for a
  switch transition (RT1987 tD_ON 8 ms typical) plus an Ag105 Bring-Up (seconds into an open node).
- [INC] (c): the J-BL pin-3 bond defeats any single-leg switch in the J-BT negative (section 5).
- [RESPIN] option 3 (a regen buffer of about 3.3 mF holding about 0.7 J between 16 V and about 26 V) "pairs with 1 or 2";
  MOT_PWR must never reconnect a drained buffer at full bus (Death-5 class).
- [RESPIN] option 4 (one bidirectional converter) was rated the proper architecture but retires the droop-share platform.

[RESPIN] did not examine isolating only one leg, only the return, only the charger path, or re-routing the pack through
the Ag105's own Bat-/Load- pins. Those options are open in this study.

## 9. Pack facts known

| Item | Value | Status / source |
|---|---|---|
| Configuration | 2S | Project baseline |
| Chemistry | LiPo (Li-ion polymer), 4.2 V/cell charge | [WIRE] T-A-05c text ("a 2S LiPo"); CV 8.400 V; no pack datasheet |
| Operating window | 7.4-8.4 V (2026-07-10 system decision); fw v30 `LIMIT_V_BATT_MIN` 7.4 V, `LIMIT_V_BATT_MAX` 8.5 V | CLAUDE.md |
| Capacity | 5 Ah (`BATT_CAPACITY_AH` 5.0, `tools/hil_electrical.py:975`) | **UNVERIFIED** |
| Maximum charge current | Unknown; decides whether ICHG > 2.5 A is allowed | **missing primary** ([EVAL] 8.2) |
| Protection board (PCM) | Unknown; the Ag105 supports protected packs only | **missing primary** |
| NTC | Unknown whether fitted at J-NTC | Open ([SPEC] 8 item 5) |
| Pack datasheet | **Missing** | [EVAL] 8.2, first row |
| DCIR | About 24 mOhm board-ADC estimate at the incident collapse (UNCONFIRMED); [WIRE] H.21 uses 10-60 mOhm, prospective fault current 120-420 A | [INC] (a); [WIRE] H.21 |
| Peak discharge seen | 16.46 A (BT boost, incident); up to about 15 A pack return in normal service | [INC] |
| Per-channel current | <= about 3 A/channel in vehicle service | CLAUDE.md RC-BT bodge record |
| Board OV detector | BQ29200 4.35 V/cell = 8.70 V, 2.0-4.0 s, OUT orphaned | Section 5 |

## 10. Lessons from the BQ25798 design that an Ag105-retaining design must also respect

1. **D-BT-SQ open-node behaviour.** D-BT-SQ hides the pack from the charger: the charger output sees only C-D11 (10 uF)
   until it exceeds VBT + about 35 mV; the RT1987 is supplied from its own VIN (VCHG), so it becomes active only above
   UVLO 3.0-3.35 V; whether a second tD_ON follows UVLO recovery with EN high is unknown ([SPEC] 3.4; [EVAL] S0-M3).
   Without a keep-alive, VCHG decays below the RT1987 UVLO in 0.17-0.66 s and below VBAT_SHORT in 0.20-0.78 s of cruise
   ([WIRE] H.9). The CV loop regulates VCHG, so the pack ends 35-50 mV low ([SPEC] 2.2).
2. **D-BT-SQ disposition.** BT_SEQUENCE_ENABLE is never turned off (IO CSV row 32), so D-BT-SQ never disconnects a
   forward fault; it provides only the reverse block. Bridging or removing it turns VCHG, C-D11, pins 18/19 and every
   downstream lead into pack-fed nets bounded only by a fuse; a 0 Ohm bridge is forbidden, and the fused link (>= 5 A,
   >= 16 V DC, interrupting rating >= the measured prospective pack current) is fallback 2 only ([WIRE] B.5). A shorted
   D-BT-SQ produces the same exposure with no fuse; [WIRE] FR-48 detects it rather than fusing it.
3. **Keep-alive.** The 1 kOhm VBT -> VCHG keep-alive draws 1.2-1.7 mA continuously (29-41 mAh/day) and is last resort
   (ruling 9); the [WIRE] option is a Run-gated TPS22810 + BAT54 + 680 Ohm from the 5 V rail, 0.7-1.4 mA in Run only,
   holding VCHG at 3.63-4.46 V ([WIRE] B.5, H.10).
4. **Hot-plug and inrush (Death-5 class).** RT1987 slew 12.0 V/ms with CSS 5.6 nF, inrush = C x 12 mA/uF; no bulk
   electrolytic on any switched node; D-MT-EN soft-starts V-MOT at 0.65 A/mF with CSS 100 nF, reaching the 2.5 A
   ramp-start clamp at 3.87 mF; RT1987 current limiting is disabled after tON, so a re-close after a TRCB trip is a hard
   close; MOT_PWR must never re-close at full bus onto a drained node (`assertMotPwrEnable()` / `motPwrHotPlugUnsafe()`)
   ([SPEC] 6; [REGEN] 2; [EVAL] 2.4; CLAUDE.md section 2).
5. **CSS as a bodge.** Fitting 100 nF CSS on D-BC-RG/D-BC-FC (0.645 V/ms, about 0.15 A) is the same rework class as an
   existing bodge and would be a never-rotated record ([EVAL] condition 10).
6. **Fail-safe defaults.** Every new switch must default OFF with the Teensy unpowered, in reset or hung: driven early in
   `setup()`, plus a hardware pull-down (the 10 kOhm EN bodge resistors; a <= 47 kOhm pull-down to beat any pad keeper;
   Teensy 4.1 reset pad state `TODO(verify: PJRC/NXP)`) ([SPEC] 3.1; [EVAL] 2.7).
7. **MCU hardware watchdog.** RTWDOG (WDOG3, 32 kHz; 100 ms in [EVAL] 5.1, 50 ms target in [WIRE] G.3) plus WDOG1 at
   1.0 s; fed only after `detectFaults()` and the 1 kHz interlock complete; reset cause from SRC_SRSR; ERR_MCU_WDT latched
   and acknowledged before Run; known blocking paths (EEPROM commit up to about 1.2 s with interrupts masked, SdFat close,
   I2C slots) must be moved out of watchdog-armed states (IMXRT1060RM Rev 3, chapters 21, 57, 58). Absent in fw v37 rev 2.
8. **A hardware ceiling, not a register default.** The loop is bounded only by the charger's limit, so the ceiling must be
   set in hardware ([INC] summary item 1); for the Ag105 that ceiling exists only if its Bat- sense is in the return path.
9. **An independent overcurrent cut** on any charger-path node is needed because a shorted power-stage FET is a path no
   controller-level inhibit can open; a plain fuse clears in ms at 2-10x rating and is too slow ([EVAL] condition 7).
10. **Firmware guards to port:** fw v37 rev 2 `J` guards G1 (I_fc + I_batt > 1.0 A / 5 ms), G2 (unaccounted bus power
    > 3 W / 20 ms), G3 (GENSTAT 5/6/7), the reboot-only trip latch and `AG105_VBATN_ISOLATED`; `FAULT_SWITCH_CONFLICT`
    is compiled out of BENCH_TEST builds (ino about 7413-7419); the bus-fed `J` session closes loop L-R by construction
    ([EVAL] 2.8).
11. **INA253 floor.** The A1 zero-current output can sit up to 10 mV = 0.1 A above ground (SLOS954A section 7.5); a 50 mA
    current trip is not achievable ([EVAL] 2.3).
12. **A voltage-threshold layer alone is soft.** The prior study proved that a charger input threshold cannot be the
    interlock because TI parts reset it at POR; the physical barrier was the H1 comparator across D-MT-EN (V-MOT >
    1.067 x VBUS, 0.1 % dividers mandatory) ([LOOP] 0; [EVAL] 2.1-2.2). The Ag105's EPROM threshold persists across POR,
    which removes that particular objection but held 12.85 V (below the bus) on the incident board (IMPLICATION,
    UNCONFIRMED).
13. **Regen-gate behaviour.** [RER] proposes decoupling REGEN from `charge_goal` and gating it on an estimated regen power
    (arm 3.0 W, release 1.0 W, dwells 40 / 200 / 500 ms, <= 20 transitions/min) to prevent chatter; each Ag105 power edge
    restarts the 500 ms settle ([RER] 5-6).

## 11. Prior conclusions that frame this study

- The prior verdict on replacing the Ag105 was **UNDETERMINED**: Path A credible but not shown fully feasible; HR1 rests
  on unmeasured VESC behaviour and charger warm response; HR2 is blocked at system level by purges and the FC budget for
  any charger ([EVAL] 0.2).
- The round-3 BQ25798 design needs two custom PCBs, 11 EVM modifications and about USD 505-540 of parts; its six-round
  review did not converge (verified findings 53 -> 16) and is not audited ([EVAL] 0.1a).
- The decisive unknowns that are charger-independent, and so carry over unchanged to an Ag105-retaining isolation design:
  S0-R3 / T-E-03 (VESC braking with V-MOT held), M-R1 (V-MOT capacitance), M-R2 (V_rgn scale near 21 V; reads 0.85x
  true), the purge statistics T-E-01, and the MCU watchdog T-W-01.
- What the prior study did not examine: keeping the Ag105 and repairing its sense path by moving the pack return onto
  VBat-, isolating the pack only during charge windows, or switching the balance-lead negative.
