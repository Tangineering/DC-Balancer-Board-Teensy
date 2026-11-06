# BQ25798EVM in place of the Ag105: wiring, carrier and operating design (board rev 20260622), round 3 r2

**Status (2026-11-06, revision r2 after review round 2; r1 after review round 1).** Design document, not built. Nothing has been ordered,
desoldered or flashed. fw v37 rev 2 stays on the bench board (`AG105_VBATN_ISOLATED 0`, no regen charging). This file is
the **single source of truth** for Path A with the BQ25798EVM. Where it disagrees with
`docs/reviews/charger_eval_2026-11-05/round2/design_BQ25798.md` (the round-2 designer's record), this file wins. It does not
replace the decision record `docs/charger_replacement_evaluation_2026-11-05.md`. It implements that study's chosen part
under the operator's 2026-11-05 rulings R1-R9 below.

Supporting files (all under `docs/reviews/charger_eval_2026-11-05/round3/`):

| File | Content |
|---|---|
| `wiring_bq25798.svg` | Wiring diagram: motherboard, carrier, EVM interface board, EVM, every lead and tap |
| `carrier_schematic.svg` | Schematic of the carrier and the EVM interface board (net labels; pin numbers in section B.8) |
| `calc/r3_calc.py` (+ `r3_calc_out.txt`, `r3_calc_out.json`) | Every number in section H, stdlib Python, sources in the header |
| `calc/make_svgs.py` | Generator for the two SVGs (edit the generator, not the SVGs) |
| `review_loop.md` | The review-design loop: round-3 self-review passes and the round-1 and round-2 independent reviews with dispositions |

## 0. Rulings applied, verdict, and what changed

### 0.1 Operator rulings (2026-11-05)

| ID | Ruling | Where it lands |
|---|---|---|
| R1 | Regen harvesting and FC charging are both hard requirements | F, H.7, H.8 |
| R2 | Path A on the current board with the BQ25798EVM | whole document |
| R3' | No circular charging loop (bus -> charger -> pack -> BT boost -> bus) and no runaway. The charger may stay powered through Run only with a fail-safe Teensy-commanded hard inhibit plus a hardware comparator backstop | B.1, B.6, F.3 |
| R4 | PCB and pack survived 2026-11-04 | D (no damage repair) |
| R5 | MCU hardware watchdog is required future work; no unattended charger session until its forced-hang test passes | G.3, T-W-01 |
| R6 | FC charging only in windows between H-20 purges. A predicted purge interrupts the window so the battery is back on the bus before the dip | F.4, H.8 |
| R7 | Regen and FC charging may run concurrently (IO CSV row 31 to be amended) | F.2, F.3, D.3 |
| R8 | The BT-current trip residual (INA253 floor ~0.1 A, residual loop up to ~0.29 A) is accepted for now | J.1 |
| R9 | The VBT->VCHG keep-alive is last resort. Design without it, give the test that decides it and any lower-drain alternative | B.5, H.9-H.10, H.15, T-B-09 |

### 0.2 Verdict

**On paper the design is feasible. No datasheet fact blocks it. The circular loop is impossible by construction in every
mode, with any single fault (section F.3), except the R8 residual, which the operator has accepted.** The hard inhibit no
longer depends on a live MCU: a hardware heartbeat monostable drops /CE and holds ILIM_HIZ within TW_HB_MAX of a Teensy
hang (20-46 ms widened band, H.17, set by T-C-10), and the Run-entry qualification window is time-limited in hardware (B.1,
U111). Every inhibit node is observed at the far end, on the EVM pin itself (B.6). The ILIM_HIZ hard converter-off depends
on EN_EXTILIM = 1, which firmware never writes and verifies every 20 ms (G.1); whether HIZ survives EN_EXTILIM = 0 is open
until T-B-21.

The design is not yet *proven*, because some of the numbers that decide whether regen is captured come from no primary
document. Each one is in the test registry (section I) with a pass criterion and a named design change if it fails. The
decisive tests are:

1. **T-E-03** (VESC over-voltage behaviour with V-MOT held at 19 V): decides regen for any charger on this rig.
2. **T-B-09** (keep-alive decision, R9): VCHG decays below the RT1987 UVLO and the BQ25798 battery-short threshold within
   0.17-0.78 s of cruise (H.9). Whether a burst then restarts fast enough is not in any datasheet. The pass criterion is the
   V-MOT peak (<= 20.5 V) with a current source into the measured C_VMOT (T-E-04 first); the regen-armed budget for dead time
   plus response is only 0.41-0.99 ms (H.7). The analysis says a keep-alive is **likely needed for regen in the regen-armed
   cruise mode**, and **not needed** for FC charging or for regen inside an FC window. The design carries a Run-gated
   keep-alive as a do-not-populate option (B.5) that draws nothing when parked.
3. **T-B-06 / T-B-10 / T-B-12** (inhibit latency, warm response, VINDPM reload after a raise): none is specified by TI.
4. **T-B-19 / T-E-11** (charge current 3.10 A accepted by the pack, and the efficiency at 19 V in): the regen capability
   margin rests on them (H.7).
5. **T-E-01 / T-E-12 / T-E-06** (purge statistics at 1 kHz and under window load; BT boost output against the FC-only bus;
   RT1987 hand-off delay): they size the pre-emption lead and decide whether the battery picks up a purge in time.
6. **T-F-08** (BT_BUS close transient from an FC-only bus): decides lever 3(i) or 3(ii) in F.4 before any FC window runs
   with traction load.
7. **T-B-21** (does ILIM_HIZ < 0.75 V still stop switching with EN_EXTILIM = 0?) and **T-A-01b** (is the pin-7 tap free of
   the encoder nets?): they decide whether the hard converter-off is register-independent and whether the /CE readback pin
   is clean.

### 0.3 What changed

Round 3 r0 against the round-2 record (kept for history):

| # | Change | Reason |
|---|---|---|
| 1 | Permit network rewritten for R6/R7 (B.1) | R7 lets REGEN stay closed in an FC window |
| 2 | Concurrent regen + FC mode with a firmware-raised, hardware-blanked input ceiling (F.2) | R7; a static FC ceiling would trip the VESC on the 3 -> 1 m/s brake (H.7) |
| 3 | Purge scheduler and pre-emption (F.4); bus-sag comparator UVB | R6 |
| 4 | FC windows open warm from REGEN (no cold FC close) | R7 |
| 5 | No M8 keep-alive in the baseline; Run-gated keep-alive option | R9 |
| 6 | eFuse TI TPS26630RGER | study condition 7 |
| 7 | Carrier in the vacated CHG footprint | removes six bodge wires at the pads |
| 8-11 | SN74LVC3G06 open-drain stages from REGN; BQ25798 trickle and 2.5 V/cell findings; JP7 removal; C-D8/C-D10 are 0805 | datasheet findings |

**Round 3 r1 (this revision), from the 53 verified findings of review round 1** (about 45 distinct issues; several were raised twice under different keys) (the per-finding log is in
`round3/review_loop.md`, "Review round 1"; disagreements are in section L of this document):

| # | Change | Finding keys |
|---|---|---|
| r1-1 | **Purge pre-emption, early purge and Run exit re-ordered:** P5 LOW, then FC_CHARGE and FCCEIL LOW in one tick, then VINDPM 19.0 V read back, then BT_BUS HIGH. New invariant **I-9: the FC_CHARGE and BT_BUS EN nets are never HIGH together**; the existing single-sample `FAULT_SWITCH_CONFLICT` stays as the backstop | preempt-fcc-btb-overlap, preempt-switch-conflict-latch |
| r1-2 | **ILIM_HIZ release now needs two healthy switches in series:** EVM R21 removed, JP14 opened; an EIB P-MOSFET Q203 feeds the release current from REGN through R255, and Q201 still holds the pin down from a separate driver (U202) on its own ribbon conductor. A broken lead, an open resistor or a dead driver now leaves the converter in HIZ | eib-wireoff-releases-converter |
| r1-3 | **Far-end readbacks on the EVM pins:** ILIM_HIZ through a comparator (U203) on a separate sense joint, re-sourcing pin 33; /CE through a comparator (U204) to pin 8 | readback-misses-evm-side, eib-wireoff-releases-converter |
| r1-4 | **Hardware heartbeat:** CHG_HB (pin 21) retriggers a monostable U113; /CE drive and ILIM release are both ANDed with it. A Teensy hang inhibits charging and stops the converter within 30-40 ms in every mode | p5-static-arm-hang |
| r1-5 | **QUAL is a hardware one-shot (U111, SN74LVC1G123, ~0.3-0.4 s) cleared by P5;** firmware raises QUAL only after EN_CHG = 0 is written and read back | qual-window-single-barrier |
| r1-6 | **BTB sensed by a comparator (U115) at 0.39-0.44 V**, below the RT1987 VEN_F minimum 0.6 V, failing to "BT may be on" | btb-sense-threshold-gap, permit-tap-failsafe-and-en-threshold |
| r1-7 | **Every input on a removable conductor fails safe:** pull-downs on every EIB driver input, BTB and T8 pull-ups, RGN/FCC pull-downs, H1q gated by UVB so a lost VBUS tap drops the regen permit, Kelvin T9 backed by R143 | open-input-failsafe, comparator-divider-open-faults, btok-sense-wire-open |
| r1-8 | **H2c = FCC . BTB_OFF . BT_OK . FCI_OK . ((UVB . FCCEIL) + H1)**: a bus sag no longer cuts a raised regen burst | uvb-blocks-raised-regen |
| r1-9 | **FR-08 trips only in the dangerous direction**; the safe direction is a non-latching window shed | fr08-uvb-unobservable |
| r1-10 | **Regen image ICHG 3.10 A (0x0136)**; capability = min(input limit, ICHG limit), restated in H.7; CV-taper regen derate (FR-25) | regen-capability-ichg-bound, regen-capability-ignores-ichg |
| r1-11 | **T3 raise is level-sensitive and staged** (IINDPM, ICHG, then VINDPM 18.2 V, ratcheted to 19.0 V); FR-24 hold-off deleted; T4 restore re-keyed on charger state; false-restore guard | raise-vindpm-unload-transient, restore-threshold-vindpm-band |
| r1-12 | **FR-07 normative:** pin-34 interrupt, one non-blocking I2C engine, transaction cap, EEPROM commit deferred in windows, 2.7 kOhm extra pull-ups and 400 kHz; I2C goes straight to EVM J8 on its own cable W7 | raise-latency-i2c-budget, t3-latency-blocking-i2c, eib-mounting-and-tp-placement |
| r1-13 | **BT_BUS close transient quantified** (H.6) and the RT1987 enabled-but-blocking state analysed; pre-emption readiness no longer requires battery current before the purge; purge-rescue predicate with a 12.0 V floor bounded by the RT1987 SCP envelope | btbus-reclose-inrush-unquantified, preempt-bt-trcb-conduction, early-purge-refusal-band |
| r1-14 | **eFuse output Schottky D103 + C103 1 uF; OVP re-selected to 23.1 V (22.6-23.6 V)**; IMON clamp diode removed (R129 10 kOhm + C129) | efuse-out-schottky-missing, efuse-ovp-above-bq-rating, imon-clamp-leakage |
| r1-15 | **ILIM bands recomputed with leakage**; EVM R23 replaced by 49.9 kOhm to halve the leakage error | ilim-band-leakage-omitted |
| r1-16 | **FC-window traction margin:** window admission bound on the commanded current, an upstream setpoint hold, a peak-hold governor, optional hardware FC-current shed (U117, DNP) | ocfc-margin-traction-transient-fc-window |
| r1-17 | **Divider tops protected:** 10.0 kOhm series resistors (R170/R171) at the V-MOT and VBUS solder joints; BAV199 input clamps | t1-t2-unprotected-power-taps, comparator-divider-open-faults |
| r1-18 | **Buildability:** pin-level netlist (B.8), layout constraints with the 22 hole coordinates (A.8), KiCad capture gate PM0 + T-A-06, fabricated EIB on chassis standoffs, kitted BOM, copper weight, second VIN+ link W8 | carrier-no-buildable-layout, eib-mounting-and-tp-placement, bom-mpns-incomplete, carrier-copper-unspecified |
| r1-19 | EVM JP30 removed; EM IDs unique; carrier designators renumbered into 1xx (no collision with MB RB1/RB2); stale designators fixed; tap returns terminated | evm-c43-25v-vbus-ldo, evm-c43-25v-on-input, duplicate-em-ids, rb2-designator-collides-with-mb, stale-designators-*, tap-twisted-gnd-unterminated |
| r1-20 | Telemetry v5 fields for the new modes; BT_BUS ownership in windows; FC-window POR flag; standby draw line; pin 34 / WDOG1_B rule; registry pass/fail for every row; T9 to the SNS-BT ground | telemetry-ems-gaps, t2-bt-bus-ownership, fc-window-por-latches-fc-clamp, run-quiescent-draw-unaccounted, pin34-wdog1b-pad, registry-missing-pass-fail, btok-kelvin-* |

**Round 3 r2 (this revision), from the verified findings of review round 2** (44 finding keys, about 38 distinct issues; the
per-finding log is in `round3/review_loop.md`, "Review round 2"; dispositions that differ from the finding are in section L):

| # | Change | Finding keys |
|---|---|---|
| r2-1 | **EVM ILIM feed joint fixed (blocker):** EVM R21 is now a 0 ohm link (not removed), the JP14 shunt stays out and JP14 pin 1 (REGN) is removed, so E2 on JP14 pin 2 reaches ILIM_HIZ | evm-jp14-feed-joint-floating |
| r2-2 | **REG14 never written:** read-only masked verify every 20 ms and before every EN_CHG/QUAL edge; a mismatch drops P5 and latches a trip; one token-gated corrective write is the only recovery; T-B-21 tests whether HIZ survives EN_EXTILIM = 0 | reg14-write-reopens-extilim |
| r2-3 | **Pre-emption, T2, T5 and T6 keep P5 HIGH:** FC_CHARGE and FCCEIL drop together, the regen soft layer is written, then BT_BUS closes; a brake in progress (above or below H1) keeps being absorbed. P5 LOW only on the VINDPM-write failure branch, T1, T7, T8 and trips. I-1 rewritten | preempt-p5-low-drops-brake-absorption, preempt-drops-subh1-regen |
| r2-4 | **T2 needs a live FC survivor** before BT_BUS opens: selector disarmed, FC_BUS re-closed through the guarded release, unblanked, FC_REG HIGH, BT current <= 0.5 A; post-drop V_bus check; the window latch owns FC_BUS HIGH too | t2-btbus-open-without-fc-conduction |
| r2-5 | **Early-purge rescue predicate evaluated at conduction**, with a 0.2 V/ms sag floor: at the H.8 sag rates it always refuses (H.6), so an early purge rides through on the FC or ends in State 99; an SCP gap is a fault outcome; "never a hot-plug" deleted; early-purge classification needs V_bus < 14.16 V or a V_fc onset | rescue-predicate-checked-before-tdon, early-purge-trigger-misattribution |
| r2-6 | **Setpoint hold released on the readiness predicate** (no I_batt condition), derived timeout T_HOLD_MAX, slew-limited release on timeout | setpoint-hold-conduction-deadlock |
| r2-7 | **Window rules:** windows re-open mid-interval (schedule locked, T_LEAD + T_WIN_MIN before t_pred); one admission/close test G with hysteresis, in stack power against the H-20 P_MAX; churn bound; duty restated as an upper bound | window-reopen-rule-limits-fc-duty, fc-window-budget-vs-h20-pmax |
| r2-8 | **FR-08 uses HB_dead and TW_QQ_MAX** from T-C-10; monostable bands widened for X7R tempco and DC bias (H.17); no mask in the T1 self-test | fr08-hb-latency-false-trip |
| r2-9 | **/CE readback moved to pin 7** (MB ROS removed, tap on its pin-7 pad; no pull-up on that net); pin 8 and RENC2 left on the encoder net; readbacks `INPUT_PULLDOWN`; EIB 3V3 on two ribbon conductors with a 10 kOhm bleed; I2C pull-ups moved to the MB (RSDA/RSCL 2.7 kOhm, CR R145/R146 DNP), so no external source back-powers the carrier rail | eib-pin8-backpower-unpowered-outputs, cr-3v3-single-tap-backpower, pin8-encoder-net-occupancy, pin8-tap-on-encoder-net |
| r2-10 | **Permit logic:** H1 term in H2c and RFC_OFF qualified by RGN; the QUAL one-shot only acts with FCC LOW (ILIM_PRE = GATE OR (QQ AND FCCN)); one added SN74LVC2G08 (U118); R119 10.0 MOhm; U203 threshold 0.59-0.65 V (below VIL_ILIM_HIZ 0.75 V) | h2c-h1-term-not-rgn-qualified, qual-clr-edge-bypasses-gate, btb-pullup-backdrives-en, ilim-sense-threshold-above-hiz-vil |
| r2-11 | **eFuse output:** D103 sized for the hard short; OUT below -0.3 V in a hard short accepted under SLVSE94G §9.5.1 pending TI E2E; T-C-04 records and checks survival; TVS branch deleted; D103 chosen by IR at 23.6 V/60 C in T-A-05 | efuse-out-schottky-missing-reopen, tc04-out-spike-criterion-unattainable |
| r2-12 | **W8 deleted** (no unfused flying lead on the unprotected VCHG-IN segment); J.1 entry | w8-unfused-hot-lead |
| r2-13 | **Single-point grounds:** ribbon GND through R273 10 ohm, W7 a twisted triple with GND at the CR end only, T7 omitted, T7b/T17r CR-end shields; T-F-11 measures signal-ground currents; T-F-04c the INA253 FC offset | ground-loops-parallel-returns, evm-agnd-parallel-return, ina253-adc-offset-from-charger-return, w7-gnd-termination |
| r2-14 | **Telemetry:** BQ25798 ADC continuous whenever the charger is powered in Run (IBAT/IBUS, 12 ms scan); pack-side charge counter and charger-input energy counter | telemetry-ems-gaps-reopen |
| r2-15 | **Buildability:** 10-pin and 12-pin header strips; 3 x 8 tap field placed between the columns; SMT J101; bottom keep-out; area budget (H.18, double-sided); four divider tops moved to TNPW0805; R116 10.0 MOhm; designators added | chg-header-strips-10-12, carrier-no-buildable-layout-reopen, bom-resistor-mpns-out-of-range, svg-netlist-designator-gaps, p5-name-collision (tap holes renamed F01-F24) |
| r2-16 | **Standby and 3V3 budgets recomputed:** Run draw 3.4-4.9 mA, 55-78 mW; 3V3 1.82 mA | run-quiescent-draw-unaccounted-reopen, h15-3v3-load-understated |
| r2-17 | **Smaller fixes:** TP41 not TP42; JP3/JP5 soldered links (R13 in the CV drop); EVM input 50.4 uF; T-A-04 criterion from §6.3; CSV row 16 with FCI_OK and H1 . RGN; I2C bus clear; LVC slow-edge exception with a test; every TODO tied to a test | evm-tp42-is-scl, evm-power-shunts-unsourced, evm-input-cap-figure, t-a-04-criterion-not-datasheet, csv-h2-text-omits-fciok, csv-row16-omits-fciok, i2c-bus-recovery-missing, lvc-slow-edges-reset, todo-outside-registry, warm-response-pass-criteria-inconsistent |

### 0.4 Review-design loop

Round 3 r0 was self-reviewed in three passes (safety, electrical, integration). Round 1 of the independent review then
produced 53 findings (about 45 distinct issues), each verified against the primaries by a second agent. All were found real.
All are applied: most as written or as amended by their verifier, ten with a different implementation, which section L
explains. Round 2 produced 44 verified findings (one blocker); all are applied (r2 table above), the differing
implementations are in section L, and the r2 closing pass re-ran `calc/r3_calc.py`, regenerated both SVGs and re-checked the
test-ID cross-references.
The closing consistency pass of r1 re-ran `calc/r3_calc.py`, regenerated both SVGs, checked every designator against the
EVM BOM and the MB part list, and checked that every test ID cited is defined in section I. What remains open is in
section I.

## A. Block diagram and wiring

### A.1 Assemblies

| Tag | Assembly | Notes |
|---|---|---|
| MB | Motherboard rev 20260622 with the Ag105 (`CHG`) removed | No trace cuts. Two divider-tap joints with series resistors R170/R171 (V-MOT, VBUS), one Kelvin tap at SNS-BT, two 0805 capacitor swaps, ROS removed (pin-7 tap), RSDA/RSCL changed to 2.7 kOhm |
| CR | **CHG adapter carrier**, new 4-layer PCB, 31.0 x 33.0 mm, 2 oz outer / 1 oz inner copper, double-sided placement outside a bottom keep-out (A.7, H.18), 22 header pins (one 1x10 and one 1x12 strip) on the Ag105 footprint, 2.54 mm plastic body | eFuse, four comparators, permit logic, two monostables, tap solder field F01-F24; keep-alive and FC-current-shed footprints DNP |
| EIB | **EVM interface board**, fabricated 2-layer PCB, 30 x 22 mm, on two M3 nylon standoffs on the chassis just off the EVM's right edge (beside TP33/TP49/TP38) | U201 SN74LVC3G06, U202 SN74LVC1G06, U203/U204 TLV3012B, Q201-Q203, release and FC-leg resistors, R273 10 ohm ground link, R274 10 kOhm 3V3 bleed |
| EVM | TI BQ25798EVM (BMS034A/B-003), SLUUCB5E | Off-board on M3 nylon standoffs on the chassis, >= 20 mm from the LM1084 side of MB, leads <= 0.30 m |

```
              VBUS tap (C-D2, R171)  V-MOT tap (C-D6, R170)    J1/J2 Teensy breakout taps (EN nets, 3V3, BT-CURR, pins
                     |                    |                     10/16/17/21/22/23/33/34/35), pin 7 at the ROS pad, Kelvin at SNS-BT
                     v                    v                                  |
  MB  D-BC-FC --+    +--------------------+----------------------------------+
  (VBUS)        |    |                                                       |
  D-BC-RG ------+--> VCHG-IN --(CHG pad 10 pin)-------> CR: eFuse U101 (+D103) --W1/W2 20 AWG pair--> EVM J1 VIN1/GND
  (V-MOT)            pin 38 divider                       | H1, UVB, BT_OK, BTB comparators; permit logic; QUAL one-shot; heartbeat
                                                          |--W5 14-way ribbon (2x 3V3, STAT, CE_DRV, ILIM_REL_A/B, RFC_OFF, ILIM/CE sense)--> EIB --> EVM TP27/TP33/TP36/TP38/TP49, JP14 pin 2, JP17, JP21
                                                          |--W7 twisted triple (SCL, GND shield, SDA)--> EVM J8 pins 2/3
  D-BT-SQ <-------- VCHG <--(CHG pads 18/19)------------- CR <--W3/W4 18 AWG pair-- EVM J5 BATTERY/GND
  (to VBT pack)
  Teensy 5 (CHG_ARM) / 6 (STAT) / 18-19 (I2C) reach CR through CHG pads 11 / 3 / 8-7.
```

The full drawing is `round3/wiring_bq25798.svg`.

### A.2 Carrier header pins (the 22 Ag105 holes)

Pad coordinates and nets: `references/Scale_Car_Board_20260624.sch`, `.brd` 20260625 (element CHG at (47.498, 34.544) mm,
R180; 2.54 mm pitch, one column of 10 pins (1-10) and one column of 12 pins (11-22), 25.00 mm apart, 1.1 mm drill). Pin numbers are the Ag105 pin numbers; board coordinates are in
A.8.

| CHG pin (pad) | MB net | CR net | Function on CR |
|---|---|---|---|
| 10 (VIN+) | VCHG-IN (D-BC-FC/D-BC-RG VOUT, C-D8, C-D10, R1-CHG to pin 38) | `VCHGIN` | eFuse U101 IN/IN_SYS; UVLO/OVP divider top. The only input path (W8 deleted in r2: the segment has no current limit in Run, J.1) |
| 4 (VIN-) | GND | `GND` | **Power star point** (input return) |
| 14, 15 (VBAT-1/2) | GND | `GND` | **Power star point** (battery return), both pins |
| 18, 19 (VBAT+1/2) | VCHG (C-D11, D-BT-SQ VIN) | `VCHG` | Battery lead W3; keep-alive option output |
| 8 (SDA) | SDA, Teensy 18, RSDA (10 kOhm as built, **2.7 kOhm after PM9**) to 3V3 | `SDA` | W7; CR R145 footprint DNP (pull-ups live on the MB 3V3 side only, so the CR rail is never fed through I2C) |
| 7 (SCL) | SCL, Teensy 19, RSCL (10 kOhm as built, **2.7 kOhm after PM9**) to 3V3 | `SCL` | W7; CR R146 footprint DNP |
| 3 (STAT) | CHRG-STAT, Teensy 6 | `STAT` | R107 10 kOhm pull-up to 3V3; ribbon W5 pin 4 |
| 11 (MPPTD) | MPPT-DISABLE, Teensy 5 | `CHG_ARM` (logic net, written "P5" in the equations) | R108 47 kOhm pull-down; logic input to U105 and U114 |
| 13 (THERM) | N$34 -> J-NTC pin 1 | `TS_EXT` | Lead W6 to EVM J7 pin 1, only if a pack NTC is fitted (T-E-09) |
| 1, 2, 5, 6, 9, 12, 16, 17, 20, 21, 22 | unconnected on MB | none | Mechanical anchors only (soldered) |

### A.3 Power and signal leads (CR <-> EVM, CR <-> EIB, MB <-> CR)

| ID | From | To | Net | Wire | Max length | Routing / termination |
|---|---|---|---|---|---|---|
| W1 | CR pad `VCHGOUT` (eFuse OUT, beside D103/C103) | EVM **J1 pin 2 (VIN1)** | charger input | 20 AWG, PTFE or silicone, red | 0.30 m | Twisted with W2, >= 1 twist / 25 mm. CR end soldered into a 1.3 mm plated hole + cable tie; EVM end 0.5 mm² ferrule in the J1 screw terminal (ED120/2DS, UG BOM p.22) |
| W2 | CR pad `GND` (beside pad 4) | EVM **J1 pin 1 (GND)** | input return | 20 AWG, black | 0.30 m | As W1 |
| W3 | CR pad `VCHG` (beside pads 18/19) | EVM **J5 pin 1 (BATTERY)** | charger output | 18 AWG, red/white | 0.30 m | Twisted with W4; 0.75 mm² ferrules; J5 is ED120/3DS |
| W4 | CR pad `GND` (beside pads 14/15) | EVM **J5 pin 3 (GND)** | battery return | 18 AWG, black | 0.30 m | As W3. J5 pin 2 (EXT_BATP) stays empty (JP9 2-3, EM9) |
| W5 | CR **J101** (2x7 SMT vertical, 2.54 mm) | EIB **J201** (2x7 shrouded) | signal bundle | 14-way 28 AWG IDC flat ribbon, 1.27 mm pitch | 0.30 m | **1 3V3 (B), 2 3V3 (A)**, 3 GND, 4 STAT, 5 CE_DRV, 6 GND, 7 ILIM_REL_A, 8 ILIM_REL_B, 9 RFC_OFF, 10 GND, 11 ILIM_SENSE, 12 GND, 13 CE_SENSE, 14 GND. The five GND conductors are bonded to the CR plane at J101; at J201 they join and reach EIB AGND only through **R273 10 ohm** (single DC ground of the EIB = E8/TP49, A.6). Lay it along W1/W2, not across the EVM inductor L2 |
| W6 | CR pad `TS_EXT` + `GND` | EVM **J7 pin 1 (EXT_TS)** | thermistor | 26 AWG twisted pair; second conductor bonded at the CR end only (shield), cut back and insulated at J7; J7 pin 2 empty | 0.30 m | **Only if** an NTC is fitted at J-NTC (T-E-09); then EVM JP18 removed (EM18) |
| W7 | CR pads `SCL`, `GND`, `SDA` (beside pads 7/8) | EVM **J8 pins 2 (SCL), 3 (SDA)** | I2C | 3-conductor 28 AWG twisted triple SCL-GND-SDA; Molex KK 254 housing 22-01-3047 with two crimps 08-50-0114 at J8 pins 2/3 | 0.30 m | **GND conductor bonded at the CR pad only**, cut back and insulated at the J8 end (shield; J8 pins 1 and 4 empty), so I2C rides the power-return offset (<= ~20 mV at 3.1 A, H.11) and adds no parallel ground path (finding ground-loops-parallel-returns, w7-gnd-termination). Separate from W5 so the far-corner J8 is reached directly |
| W8 | - | - | - | **do not populate (r2)** | - | Deleted: it was an unfused flying lead on the VCHG-IN segment that has no current limit in Run (B.4, J.1). Conditional fallback only if T-A-05 rates the pad-10 pin below 3 A and no better pin exists: 20 AWG from C-D8 pad 1 to a re-added CR pad, with a ~3 A fast fuse within 10 mm of C-D8 (fuse I2t checked against the eFuse 202 ms limit dwell at 2.41 A, T-A-05), sleeved, tied away from the board edge |

Currents: W1/W2 carry at most the eFuse limit (2.41 A for <= 202 ms, H.5) and normally <= 1.76 A (the regen ILIM clamp
maximum, H.4). W3/W4 carry <= 3.1 A (regen-image ICHG). Drops and losses in H.11.

### A.4 Taps from CR to MB (CR tap solder field F01-F24, 1.0 mm plated holes in a 3 x 8 grid, 2.54 mm, with a cable-tie slot)

All 26 AWG unless stated. Lengths from the `.brd` coordinates (CR centre about (33.5, 50.5) mm; J1 at (85.9, 62.0), J2 at
(108.7, 62.0), C-D2 at (68.6, 69.9), C-D6 at (97.8, 17.9), SNS-BT at (55.1, 23.6) mm). J1/J2 are Amphenol 87606-324LF
**female** Dubox receptacles (MB BOM; 2 x 24, two positions per Teensy pin). Position map derived from the Teensy 4.1 pin
order and checked against the nets the `.sch` gives for J1.07/08 (pin 2, net ENC_A with RENC1), J1.19/20 (pin 8, net ENC_B
with RENC2), J1.17/18 (net ENC-EN, the far side of ROS); **T-A-01** confirms every position used here and **T-A-01b** the
pin-7 tap. Pin 7 has no J1/J2 position: its net N$21 is only Teensy pin 7 and ROS pad 2 (`.sch`), so T20 lands on the ROS pad
after ROS is removed (PM10). A tap ends in a single 0.64 mm square male pin (Samtec TSW-101-07-G-S cut
header pin, wire soldered and heat-shrunk) pushed into the second position of the pair; if T-A-01 finds a position
unusable, solder the tap to the pin's second position on the MB pad.

| ID | CR field | MB point | Net (Teensy pin) | CR use | Length | Notes |
|---|---|---|---|---|---|---|
| T1 | F01 | **C-D6 pad 1** (V-MOT) through **R170 10.0 kOhm 0.1 % 0805** soldered at the joint | V-MOT | H1 IN+ divider top (R109) | 0.15 m | The tap wire carries only a high-impedance signal; twisted with T7b |
| T7b | F02 | **C-D6 pad 2** (GND) | GND | shield of the T1 pair, **bonded at the CR end only** (insulated at C-D6) | 0.15 m | Twisted with T1; carries no return current (A.6) |
| T2 | F03 | **C-D2 pad 1** (VBUS) through **R171 10.0 kOhm 0.1 % 0805** at the joint | VBUS | H1 IN- (R111) and UVB (R114) divider tops; one wire for both (B.2) | 0.10 m | A lost T2 drops UVB and with it H1q |
| T3 | F04 | J1.39 | D-BT-EN net (28, BT_BUS_ENABLE) | `BTB` into U115 IN- via R120 10 kOhm; R119 1.00 MOhm pull-up | 0.12 m | |
| T4 | F05 | J1.43 | D-BC-RG net (30, REGEN_ENABLE) | `RGN` logic input via R121 1 kOhm; R133 100 kOhm pull-down; KA option enable | 0.12 m | |
| T5 | F06 | J1.45 | D-BC-FC net (31, FC_CHARGE_ENABLE) | `FCC` logic input via R122 1 kOhm; R134 100 kOhm pull-down | 0.12 m | |
| T6 | F07 | J1.29 | 3V3 | CR + EIB logic supply (the only source of that rail) | 0.12 m | <= 1.82 mA (H.15); no other conductor feeds the rail (r2: I2C pull-ups on the MB, CE_RB on a pull-up-free pin) |
| - | F08 | - | - | spare (T7 to J1.01 omitted in r2: the CR plane is bonded to MB GND at CHG pads 4/14/15; a logic-return wire would parallel the power returns) | - | - |
| T8 | F09 | J2.31 | BT-CURR (41, BT_CURRENT, INA253 BT out) | U104 IN- via R140 10 kOhm; R144 1.00 MOhm pull-up on the CR side | 0.15 m | Twisted with T9 |
| T9 | F10 | **SNS-BT GND / REF1 pad** (or its nearest via; T-A-01) | GND, Kelvin | U104 reference divider bottom (R142); R143 100 ohm to the CR plane as backup | 0.12 m | Not to J2.03 (finding btok-kelvin); twisted with T8 |
| T10 | F11 | J1.23 | pin 10 -> `CHG_QUAL` | U111 B input via R147 1 kOhm, R123 47 kOhm pull-down | 0.12 m | |
| T11 | F12 | J2.19 | pin 17 -> `CHG_FCCEIL` | logic input, R124 47 kOhm pull-down | 0.15 m | |
| T12 | F13 | J2.47 | pin 33 <- `CHG_ILIM_RB` (far-end ILIM_HIZ sense, U203) | readback, R125 1 kOhm | 0.15 m | |
| T13 | F14 | J2.45 | pin 34 <- `CHG_H1_RB` | readback, R126 1 kOhm | 0.15 m | pin 34 must stay GPIO (G.3); `INPUT_PULLDOWN` |
| T14 | F15 | J2.21 | pin 16 <- `CHG_H2_RB` (H2c) | readback, R127 1 kOhm | 0.15 m | |
| T15 | F16 | J2.07 | pin 23 <- `CHG_BTOK_RB` | readback, R128 1 kOhm | 0.15 m | |
| T16 | F17 | J2.43 | pin 35 <- `CHG_EFUSE_FLT` | readback, R106 10 kOhm pull-up on CR | 0.15 m | |
| T17 | F18 | J2.09 | pin 22 (A8) <- `CHG_IIN` | eFuse IMON via R129 10 kOhm, C129 1 nF at the pin side | 0.15 m | Twisted with T17r |
| T17r | F19 | J2.29 | GND | shield of the T17 pair, **bonded at the CR end only** (insulated at J2.29) | 0.15 m | Twisted with T17 |
| T20 | F20 | **MB ROS pad 2** (net N$21, Teensy pin 7; ROS removed, PM10) | pin 7 <- `CHG_CE_RB` (far-end /CE sense, U204) | via **CR R148 1.00 kOhm** (+ EIB R264 100 ohm); Teensy `INPUT_PULLDOWN` | 0.10 m | No pull-up on this net, so a dead U204 or an open conductor reads LOW = "/CE LOW" (announces itself through FR-08(b)); pin 8 / RENC2 / the encoder net are untouched |
| T21 | F21 | J2.11 | pin 21 -> `CHG_HB` (heartbeat) | U113 B input via R135 1 kOhm, R136 100 kOhm pull-down | 0.15 m | |
| T18 | F22 | **CO-5V pad 1** (+5 V) | 5V (battery-derived, LM1084) | keep-alive option source | 0.05 m | **Fit only if T-B-09 fails** |
| T19 | F23 | J2.33 | pin 40 FC_CURRENT (INA253 FC out) | U117 option input | 0.15 m | **Fit only with the U117 option** (FR-14 fail branch) |
| - | F24 | J1.07 (pin 2) | spare | - | - | Optional `PURGE_SENSE` (T-E-02) **only if pin 2 passes T-A-01b** (J1.07 is the ENC_A net with RENC1) |

Teensy pins 5, 6, 18, 19 need no tap: they reach CR through CHG pads 11, 3, 8, 7. Pin 20 stays free for the MCU watchdog
WDOG1_B (G.3). **Pin 8 is not used (r2):** its net ENC_B still carries RENC2 and, after the 2026-08-16 reroute and the fitted
74HC14 (both unrecorded as to wiring), possibly the live encoder-B signal; a push-pull U204 output there could fight it and
back-power the EIB through RENC2 (findings pin8-tap-on-encoder-net, eib-pin8-backpower-unpowered-outputs). **Pin 7 is used
instead** through the ROS pad: removing ROS isolates pin 7 from the retired ENC-EN net whatever that net now carries. Pin 2
(ENC_A, RENC1) stays free unless T-A-01b clears it. With pins 7 and 8 assigned, the only spare Teensy pins are 2 and 8, both on
encoder nets (recorded, J.2).

### A.5 EIB wiring to the EVM (28 AWG Kynar; EIB on the chassis beside the EVM's right edge)

Positions from SLUUCB5E Fig 4-1 (top layer, silkscreen) scaled from the J8 2.54 mm pitch (about 8.9 px/mm): TP33 on the
right edge, TP49 about 16 mm from it, TP38 about 13 mm, TP36 bottom-centre about 42 mm, TP27 top-left of centre about 53 mm.
**JP13/JP14/JP21** sit top-right in a row under the "ILIM_HIZ SET" legend (500mA / 1.5A / EN HIZ), just left of TP33 and above
TP38; **JP17** ("CHARGE ENABLE") is centre-bottom, right of TP28 (SYS) and directly above TP36 (/CE) and TP35 (TS). **T-A-02**
confirms each by net and records every final length.

| ID | EIB point | EVM point | Net | Max length | Notes |
|---|---|---|---|---|---|
| E1 | `REGN` | **TP27** (or the JP12 REGN pin, whichever T-A-02 finds shorter) | REGN | 65 mm | Supply for the Q201-Q203 gate pull-ups only; EIB 100 nF local |
| E2 | `ILIM_FEED` (R255 output) | **JP14 pin 2** (on ILIM_HIZ through EVM R21 = 0 ohm; JP14 shunt out, JP14 pin 1 removed, EM3) | release current | 60 mm | Lead off = no release current = HIZ |
| E3 | `ILIM_HOLD` (Q201 drain, R257 bottom via Q202) | **TP33** | ILIM_HIZ hold-down and FC leg | 20 mm | Shortest lead (high-impedance node); away from SW and L2 |
| E4 | `ILIM_SNS` (U203 input via R258) | **JP21 pin on the ILIM_HIZ side** (JP21 open) | far-end sense | 60 mm | Separate joint from E2/E3, so a detached control joint is seen |
| E5 | `nCE_DRV` (U201 1Y) | **TP36** | /CE drive | 50 mm | Static logic level |
| E6 | `nCE_SNS` (U204 input via R262) | **JP17 pin on the /CE side** (JP17 removed, EM1) | far-end sense | 60 mm | Separate joint from E5 |
| E7 | `STAT` | **TP38** | STAT | 30 mm | To ribbon pin 4 |
| E8 | `AGND` | **TP49** (AGND) | ground for the stages | 25 mm | TP49 replaces TP48 (TP48 is ~88 mm away in the far corner) |

Parts fitted on the EVM itself (not on the EIB): **R256 200 kOhm** from the TP33 pad to the nearest AGND point, **C252
2.2 nF C0G** across the same pads, and **R272 47 kOhm** from the /CE pad of the vacated R42 footprint to a REGN point with a
<= 10 mm Kynar link (so /CE keeps its pull-up if E5 comes off). Identify every point by net with a meter before soldering
(T-A-02).

### A.6 Ground scheme (single-point bonding, r2)

- **Power star:** CR GND plane, tied to MB GND at CHG pads 4 (VIN-) and 14/15 (VBAT-). W2 and W4 return to pads beside them.
  The BQ25798EVM joins PGND and AGND at net-tie NT1 (SLUUCB5E Fig 4-5, next to C41/AGND) and senses current high-side only (R2,
  R13 and internal RSNS; study §1.1 H1), so VIN- = VBAT- is the requirement R-GND and is met. The pack negative is PCB ground
  by design (operator, 2026-11-04).
- **Logic return:** the CR plane itself, bonded to MB GND at CHG pads 4/14/15 (T7 omitted in r2). The divider bottoms of H1 and
  UVB are on the CR plane. T7b and T17r are shields bonded at the CR end only, so no tap wire carries motor or charger return
  current. A plane offset delta shifts the H1
  trip by only about 0.07 x delta (both inputs see it), so 10 mV costs 0.7 mV.
- **Kelvin for BT_OK:** the INA253 BT output is 6-34 mV at the threshold, so a few mV of offset matters. The INA253 output is
  referenced to its own GND/REF1/REF2 pins at SNS-BT (`.sch` net GND includes SNS-BT.GND, .REF1, .REF2). The U104 reference
  divider bottom (R142) therefore returns to the **T9 wire landed on the SNS-BT GND/REF1 pad**, twisted with T8. R143 (100
  ohm) ties R142's bottom to the CR plane, so an open T9 shifts the trip only to about 22 mV instead of floating it; with T9
  intact the plane offset couples with a ratio of about 2e-4. T-E-10 measures the residual offset under load.
- **EIB and EVM: one DC ground each, no parallel return (r2).** The EIB's DC ground is E8 at TP49 (EVM AGND). The five ribbon
  GND conductors (3, 6, 10, 12, 14) are bonded to the CR plane at J101 and reach EIB AGND only through R273 10 ohm: the EIB
  supply and signal returns (<= ~1 mA, H.15) drop <= 10 mV across it, while the share of the 1.4-1.6 A net EVM ground current
  that would otherwise cross the EVM AGND copper, E8 and the ribbon (finding estimate 0.1-0.3 A through 25-40 mOhm) falls below
  ~2 mA (10 ohm against W2 || W4 ~4 mOhm). W7's GND conductor is bonded at the CR end only (J8 pin 1 empty) and W6's likewise, so
  I2C and TS reference the EVM through the power returns: offset <= ~20 mV at 3.1 A (H.11), against the BQ25798 0.4 V VIL margin
  and the TS divider ratio. TI asks that ILIM and TS ground terminals stay away from high-current returns (SLUUCB5E layout note
  7); R256/C252 sit on the TP33/AGND pads, away from PGND. **T-F-11** measures the residual signal-ground currents (pass < 20 mA
  DC in any signal-ground conductor, < 2 mV AGND-PGND).

### A.7 Mechanical

- CR outline 31.0 x 33.0 mm stays inside the CHG silkscreen (32.0 x 34.8 mm). It is pulled 0.5 mm in on the OP-FC side,
  which still overlaps the outline by 0.3 mm (`spec.md` §7). The 2.54 mm header body clears D-BT-SQ, C-D11, C-D12, C-DC11,
  C-DC12 under the footprint (<= 1.10 mm).
- **Bottom keep-out:** board x 24.5-36.0 mm, y 48.5-53.5 mm (D-BT-SQ (29.7, 50.0), C-D11 (26.2, 50.3), C-D12 (34.3, 50.0),
  C-DC11 (34.0, 52.3), C-DC12 (27.9, 52.6), plus 0.5 mm): no bottom-side part and no through-hole tail longer than 0.5 mm after
  flush cutting. Elsewhere, bottom-side part height + tail <= 2.04 mm (2.54 mm body - 0.5 mm clearance).
- **Area (H.18):** the courtyard estimate (~960 mm²) exceeds the top-side free area (~880 mm²), so the CR is **double-sided**
  outside the keep-out and **4-layer** (L2 GND plane kept intact under the bottom-side parts). U101 with D103/C103 stays on the
  top side.
- Neighbours: CO-5V 0.1 mm right, LM1084 1.8 mm right (4.83 mm tall), J-NTC/J-BL left. CR parts are low-power (eFuse <= 0.17
  W, H.14).
- **CR pad placement (checked against the A.8 hole table, r2):**
  - **Tap field F01-F24: 3 x 8 at 2.54 mm, 1.0 mm plated holes**, centres x = 23.90 + k x 2.54 mm (k = 0..7), y = 35.30 / 37.84
    / 40.38 mm; pad envelope x 22.95-42.65, y 34.35-41.33. It sits between the pin columns (clear interior x 21.95-45.05 mm)
    with >= 1.0 mm to the pin-22 pad and >= 2.4 mm to the pin-1 pad. 2.54 mm pitch is kept because the 0.64 mm TSW-101 tap pins
    need a 1.0-1.1 mm drill (Ag105 p.21: 1.1 +- 0.05 mm for 0.64 mm pins).
  - **J101: SMT vertical 2x7, 2.54 mm** (pins on the top side only), lengthwise along y in the strip x 37-44 mm, y about 43-62
    mm. If T-A-05 shows the chosen header body is longer than the ~24.5 mm of free y, J101 becomes a right-angle part at the
    high-y edge (overhang rule below).
  - Battery pads (`VCHG` beside pins 18/19, `GND` beside 14/15) at board x about 21.0 mm; input pads (`VCHGOUT`, `GND` beside
    pin 4) at x about 46.0 mm. The W7 pads beside pins 7/8. Every courtyard >= 0.5 mm from the 31 x 33 mm outline.
  - **Overhang**, only if the capture needs it: low-y edge over C4A/B-BT (1210, 1.35 mm) or high-y edge over OP-FC (SOIC, ~1.75
    mm, UNVERIFIED), no bottom-side parts in the overhang; never on the J-NTC/J-BL side or over LM1084/CO-5V (T-A-06 measures
    the heights).
- EVM: 4 M3 nylon standoffs in the corner holes (stock bumpons H1-H4 removed; hole diameter checked in T-A-02), 10 mm tall,
  on the chassis; J2 terminal block removed (EM7); cable-tie W1-W7 to the chassis at 0.10 m intervals.
- EIB: two M3 x 10 mm nylon standoffs on the chassis, 5-15 mm off the EVM's right edge, at the height of TP33/TP49.

### A.8 CR layout constraints (for the KiCad capture, PM0)

Hole positions (board coordinates in mm, from the `.brd` element CHG at (47.498, 34.544), R180; pad x/y in the package are
rotated 180 degrees). Drill 1.1 mm, plated, pad >= 1.9 mm.

| Pin | Name | x | y | Pin | Name | x | y |
|---|---|---|---|---|---|---|---|
| 1 | VSEL | 45.998 | 39.084 | 12 | MPPTSEL | 20.998 | 61.944 |
| 2 | CSEL | 45.998 | 41.624 | 13 | THERM | 20.998 | 59.404 |
| 3 | STAT | 45.998 | 44.164 | 14 | VBAT-1 | 20.998 | 56.864 |
| 4 | VIN- | 45.998 | 46.704 | 15 | VBAT-2 | 20.998 | 54.324 |
| 5 | NC1 | 45.998 | 49.244 | 16 | VLOAD-1 | 20.998 | 51.784 |
| 6 | NC2 | 45.998 | 51.784 | 17 | VLOAD-2 | 20.998 | 49.244 |
| 7 | SCL | 45.998 | 54.324 | 18 | VBAT+1 | 20.998 | 46.704 |
| 8 | SDA | 45.998 | 56.864 | 19 | VBAT+2 | 20.998 | 44.164 |
| 9 | NC3 | 45.998 | 59.404 | 20 | LDIS | 20.998 | 41.624 |
| 10 | VIN+ | 45.998 | 61.944 | 21 | VLOAD+1 | 20.998 | 39.084 |
| 11 | MPPTD | 20.998 | 64.484 | 22 | VLOAD+2 | 20.998 | 36.544 |

- **Header strips:** one 1x10 single-row strip in the x 45.998 column (pins 1-10, y 39.084-61.944) and one 1x12 in the
  x 20.998 column (pins 11-22, y 36.544-64.484). The 10-pin column starts one pitch in from the 12-pin column's ends, so the two
  strips are never one aligned 2-row body; each sits on its own column.
- **Copper:** 2 oz (70 um) outer layers, 1 oz inner (4-layer, L2 GND). `VCHGIN`, `VCHGOUT`, `VCHG` and the GND star as pours >= 2.5 mm wide (>= 1.5 mm on 1
  oz if 2 oz is unavailable; IPC-2152 sizing for 2.41 A at 10 C rise is the check, TODO(verify: IPC-2152 chart) in T-A-06).
  GND poured on the bottom layer, stitched at <= 5 mm.
- **U101 thermal pad:** >= 9 vias, 0.3 mm, to the bottom GND pour (SLVSE94G §11 layout example).
- **D103 and C103** within 3 mm of U101 OUT (pins 17/18) and GND, via cluster to the bottom pour (SLVSE94G §11).
- **Header-pin current:** the single 0.64 mm pin at pad 10 carries the full input current (<= 2.41 A, the eFuse I_OL); its
  rating is checked in T-A-05 (>= 3 A required). **VCHG-IN copper from the pad-10 pin to U101 IN/IN_SYS <= 5 mm, solder-masked on
  both sides, no exposed test pad**; the R102 divider top taps at U101 IN_SYS (finding w8-unfused-hot-lead).
- **Analog:** U102-U104 and their dividers away from the U101 OUT/D103 loop; the 0805 divider tops R102/R109/R111/R114 at
  least 2 mm from any logic trace; U104 divider bottom routed to the F10 (T9) hole and to R143 only.
- Hand assembly: the VQFN-24 eFuse needs hot air or reflow. Alternative package if that is not available: TPS26630PWPR
  (HTSSOP-24; second pin column of SLVSE94G Table 5-1), with B.8 re-mapped.

## B. Carrier and EVM interface board

### B.1 Permit logic (R6/R7, review round 1)

Inputs (3.3 V logic; EN nets from the RT1987 enable lines, comparators, Teensy):

| Name | Source | HIGH means | Level if its source or conductor dies |
|---|---|---|---|
| `H1` | U102 TLV3012B: V-MOT > 1.089 x VBUS + 0.30 V hysteresis | regen: the bus cannot feed V-MOT | LOW (POR <= 1.9 ms, unpowered: output sinks, SBOS300C §9.4.5). T1 open: R110 pulls IN+ low -> LOW. T2 open: IN- -> 0 -> **HIGH**, covered by UVB (below) |
| `UVB` | U103 TLV3012B: VBUS > 13.35 V (fall) / 13.71 V (rise), nominal | bus healthy | LOW. T2 open -> LOW |
| `BT_OK` | U104 TLV3012B: INA253 BT out < 19.75 mV (I_BT < 0.06-0.34 A) | the pack is not feeding the bus | LOW. T8 open: R144 pulls IN- to 3.3 V -> LOW |
| `BTB_OFF` | U115 TLV3012B: D-BT-EN net < REF/3 (0.39-0.44 V) | the RT1987 is guaranteed off (EN < VEN_F min 0.6 V) | LOW (POR, unpowered). T3 open: R119 pulls IN- to 3.3 V -> LOW |
| `FCC`, `RGN` | EN nets of D-BC-FC (31), D-BC-RG (30) | switch commanded on | LOW (10 kOhm bodge pull-downs + RT1987 REN_PD; tap open: R134/R133 100 kOhm on the CR side) |
| `P5` | Teensy 5 `CHG_ARM` (via CHG pad 11) | firmware has armed after a verified image | LOW (R108 47 kOhm) |
| `QUAL` | Teensy 10 `CHG_QUAL` (one-shot trigger) | input-qualification request | LOW (R123 47 kOhm) |
| `FCCEIL` | Teensy 17 `CHG_FCCEIL` | the IINDPM/ICHG registers hold FC-window values, read back | LOW (R124 47 kOhm) = "not confirmed" |
| `HB` | Teensy 21 `CHG_HB` (heartbeat, toggled once per `loop()`) | - | no edges (R136 100 kOhm pull-down) -> ARM_OK falls after tw |
| `FCI_OK` | U117 option (FC current < 1.30 A), else R137 0 ohm to 3V3 | FC channel inside its OC margin | option fitted: LOW when unpowered |

Sequential elements (SN74LVC1G123, SCES586E: Schmitt-trigger A/B inputs, glitch-free power-up reset with Q LOW, Ioff):

- **U111 QUAL one-shot:** B = QUAL (rising edge), A = GND, CLR = P5N, Rext/Cext = R150 100 kOhm / C150 3.3 uF:
  **QQ** is HIGH for tw = 0.30-0.40 s (H.17, TODO(calibrate: T-C-10)) after a QUAL rising edge, cleared at once while P5 is
  HIGH. A QUAL pin frozen HIGH by a hang makes no new edge, so QQ ends by itself. CLR also triggers on its own rising edge
  if B is HIGH (SCES586E pin table), so firmware keeps QUAL LOW whenever P5 changes (I-5).
- **U113 heartbeat monostable:** B = HB (rising edge), A = GND, CLR tied to 3V3, Rext/Cext = R151 100 kOhm / C151 330 nF:
  **ARM_OK** stays HIGH while rising edges arrive within tw = 30-40 ms (retriggerable; H.17).

Equations:

```
UF       = UVB AND FCCEIL                                              U116A
X        = UF OR H1                                                    U106A
W        = FCCN AND UVB                                                U116B
H1q      = H1 AND RGN AND W          (= H1 . RGN . /FCC . UVB)         U109     regen path; C7 qualifier; lost T2 drops it
Y1       = BT_OK AND X AND FCI_OK                                      U107
H2c      = FCC AND BTB_OFF AND Y1    (= FCC . BTB_OFF . BT_OK . FCI_OK . ((UVB . FCCEIL) + H1))   U108
GATE     = H1q OR H2c                                                  U110A
ILIM_PRE = GATE OR QQ                                                  U110B
ILIM_REL = ILIM_PRE AND ARM_OK   -> W5 pins 7 (A) and 8 (B) -> EIB U201 ch2 -> Q203 (feed) and U202 -> Q201 (hold) -> ILIM_HIZ
CE_DRV   = P5 AND ARM_OK         -> W5 pin 5 -> EIB U201 ch1 -> /CE                          U114A / U114B
RFC_OFF  = FCCN OR H1            -> W5 pin 9 -> EIB U201 ch3 -> Q202 -> R257 (FC leg)        U106B
```

What each term does:
- `BTB_OFF AND BT_OK` in H2c is the **loop barrier for every mode with FCC = 1** (F.3). BTB_OFF is an analog threshold below
  the RT1987's own turn-off level, so no EN level that can leave D-BT-EN conducting reads as "off".
- `H1q` is the loop barrier for regen with the pack on the bus. `UVB` in H1q makes a lost VBUS tap (which forces H1 HIGH)
  drop the permit: UVB's divider hangs on the same T2 wire. Cost: no regen harvest while VBUS < 13.4 V, which in Run is a
  fault state anyway.
- `(UVB AND FCCEIL) OR H1` in H2c: UVB sheds the charger in microseconds if the FC-only bus sags (early purge, traction
  overload, FC boost dropout), **except** while H1 proves V-MOT > 1.089 x VBUS, i.e. D-BC-FC and D-MT-EN are reverse-biased and
  the FC is not loaded. A sag during a raised burst therefore no longer cuts the converter mid-brake.
- The **ceiling blank:** in an FC window, if firmware has raised the registers to the regen values (FCCEIL LOW) and V-MOT falls
  back toward VBUS (H1 = 0), H2c = 0 and the converter stops until firmware has restored the FC values and confirms with FCCEIL
  HIGH.
- `QQ` releases ILIM_HIZ for the ADC qualification read only while the charge inhibit is on (CLR = P5N) and only for tw.
- `ARM_OK` qualifies both the charge enable and the converter release: no heartbeat, no charging and no switching.
- `RFC_OFF` keeps the FC clamp (0.65-0.95 A, H.4) in hardware whenever FCC = 1 and H1 = 0. It acts at any charger POR, and at
  run time **if** the BQ25798 re-reads the pin continuously (T-B-07; SLUSDV2C §7.3.4.3 says "at POR", the pin table says
  "lower of pin and register").

Truth table (X = don't care; ARM_OK = 1 and FCI_OK = 1 unless a row says otherwise; QQ shown as the one-shot output):

| FCC | RGN | BTB_OFF | H1 | BT_OK | UVB | FCCEIL | P5 | QQ | GATE | ILIM_REL | /CE | RFC_OFF | Meaning |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | X | X | X | X | X | 0 | 0 | 0 | 0 | HIGH | 1 | Idle / Init: everything off |
| 0 | 1 | X | 0 | X | X | X | 0 | 1 (<= tw) | 0 | **1** | HIGH | 1 | Run-entry qualification: pin released, charge inhibited (/CE HIGH and EN_CHG = 0 written first), time-limited |
| 0 | 1 | X | 0 | X | X | X | 1 | 0 (cleared) | 0 | 0 | LOW | 1 | firmware fault (QUAL with P5): **still converter-off** |
| 0 | 1 | 0 | 0 | X | 1 | X | 1 | 0 | 0 | 0 | LOW | 1 | regen armed, cruise: converter off |
| 0 | 1 | 0 | 1 | X | 1 | X | 1 | 0 | 1 | 1 | LOW | 1 | regen burst: converter on |
| 0 | 1 | X | 1 | X | 0 | X | 1 | 0 | 0 | 0 | LOW | 1 | regen with the bus below UVB (or T2 lost): **off** |
| 1 | X | 0 | X | X | X | X | X | 0 | 0 | 0 | P5 | H1 | BT may be on the bus with FCC: **forced off** (loop barrier) |
| 1 | X | 1 | X | 0 | X | X | X | 0 | 0 | 0 | P5 | H1 | pack current seen: off |
| 1 | X | 1 | 0 | 1 | 0 | X | X | 0 | 0 | 0 | P5 | 0 | bus sag, no brake: off |
| 1 | X | 1 | 0 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | LOW | 0 | FC window charging, FC clamp in hardware |
| 1 | 1 | 1 | 1 | 1 | X | X | 1 | 0 | 1 | 1 | LOW | 1 | brake inside an FC window: converter on, regen clamp (even if UVB = 0) |
| 1 | X | 1 | 0 | 1 | 1 | 0 | X | 0 | 0 | 0 | P5 | 0 | **ceiling blank** (raised registers, V-MOT back near VBUS) |
| X | X | X | X | X | X | X | X | X | X | 0 | HIGH | X | **ARM_OK = 0** (heartbeat lost): charge inhibited, converter held, in every mode |

### B.2 Comparators (values from `calc/r3_calc.py`)

| Ref | Function | Part | Network |
|---|---|---|---|
| U102 | **H1** | TLV3012BIDBVR (push-pull, POR, fail-safe inputs, SBOS300C) | IN+ = V-MOT via R170 10.0 kOhm (MB joint) + R109 487 kOhm / R110 56.2 kOhm (all 0.1 %), C106 470 pF, D104 BAV199 clamp to 3V3/GND; IN- = node T2C via R111 442 kOhm / R112 56.2 kOhm (0.1 %), C107 470 pF, D105 BAV199; R113 6.49 MOhm OUT -> IN+; REF unused (open); C110 100 nF on V+ |
| U103 | **UVB** | TLV3012BIDBVR | IN+ = node T2C via R114 1.00 MOhm / R115 104 kOhm (0.1 %), C108 1 nF (tau 94 us), D106 BAV199; R116 11.0 MOhm OUT -> IN+; IN- = own REF (1.223-1.260 V at 25 C, 100 ppm/C max, SBOS300C §6.9); C111 100 nF |
| U104 | **BT_OK** | TLV3012BIDBVR | IN+ = own REF via R141 61.9 kOhm / R142 1.00 kOhm to the T9 Kelvin (19.75 mV); R143 100 ohm from R142's bottom to the CR plane; IN- = BT-CURR via R140 10 kOhm + C140 10 nF (tau 100 us); R144 1.00 MOhm from the T8 side of R140 to 3V3; C112 100 nF |
| U115 | **BTB_OFF** | TLV3012BIDBVR | IN+ = own REF / 3 via R117 20.0 kOhm / R118 10.0 kOhm (C109 100 nF on the tap); IN- = D-BT-EN net (T3) via R120 10.0 kOhm, R119 1.00 MOhm to 3V3; C113 100 nF |
| U117 (DNP) | FCI_OK option | TLV3012BIDBVR | IN- = FC_CURRENT (T19) via 10 kOhm; IN+ = REF divider at 130 mV (1.30 A at 0.1 V/A); output replaces R137 into U107. Fitted only if T-F-04b fails |

Node T2C is the CR end of the single VBUS tap (T2 through R171). The H1 and UVB dividers load it together, so the two are
solved as one network in `r3_calc.py` H.1/H.2 (including the coupling through R116 when UVB switches).

- **H1 trips** (worst case: 0.1 % dividers, Vos +-9 mV, VHYS 2-8 mV, CMRR 54 dB, both UVB states): rise 17.31 V / fall 17.01 V
  nominal at VBUS 15.9 V (ratio 1.089, hysteresis 0.30 V); fall >= 16.81 V (guard 0.91 V over VBUS); at VBUS 16.39 V fall
  17.34-17.76 V and rise <= 18.05 V; at VBUS 15.2 V (loaded FC-only bus) fall >= 16.05 V (guard 0.85 V).
- **UVB trips:** fall 13.35 V nominal (band 12.91-13.80 V), rise 13.71 V (band 13.26-14.14 V), including REF drift over 0-45 C
  and the CMRR term. The fall band sits 0.33 V below the FC VINDPM floor (14.5 V - 2.6 % = 14.12 V, T-B-13) and the rise band
  1.06 V below the loaded FC-only bus (assumed >= 15.2 V, T-E-08).
- **BT_OK trip:** 19.75 mV nominal; 6.0-33.5 mV worst case = 0.06-0.34 A of BT boost forward current. The INA253A1
  zero-current floor can reach 10 mV (SLOS954A §7.5), so a false "not OK" at zero current is possible (safe: FC window
  refused; T-E-10).
- **BTB_OFF threshold:** 0.39-0.44 V worst case (REF tolerance, drift, Vos, hysteresis), 0.16 V below VEN_F min 0.6 V
  (RT1987 DS-00 EC p.7). With pin 28 driven LOW the input sits at 33 mV; with the Teensy in reset (EN net held only by the
  10 kOhm bodge pull-down) at 64 mV; with pin 28 accidentally `INPUT_PULLUP` the EN net reaches about 1.02 V, which may keep
  D-BT-EN on, and U115 reads it as "may be on" (permit removed). U105's third inverter is spare, input tied to GND.
- **Input protection:** an open divider bottom (R110, R112 or R115) would put up to 22 V on a comparator input through about
  0.5-1 MOhm. The BAV199 pairs (D104-D106) clamp each input to 3V3 + one diode (36 uA at 22 V) and keep it inside the TLV3012
  7 V absolute maximum, which TI says must be enforced externally beyond (V+) (SBOS300C §6.1 note 2). BAV199 leakage
  (nA class at 25 C) on the 50-90 kOhm divider nodes shifts the trips by < 1 mV; T-A-07 measures it hot.
- **Tap faults:** R170/R171 at the MB joints make every tap wire a 10 kOhm-sourced signal: a tap shorted to GND draws 2.2 mA
  (48 mW in an 0805) instead of shorting the V-MOT node or the bus.

### B.3 Logic parts (all VCC = 3V3 via T6, 100 nF each; SN74LVC: VIH 2.0 V / VIL 0.8 V at 3.0-3.6 V, Ioff)

| Ref | Part | Function | Inputs -> output |
|---|---|---|---|
| U105 | SN74LVC3G04DCTR (SCES363L) | inverters | FCC -> FCCN; P5 -> P5N; third section spare, input to GND |
| U106 | SN74LVC2G32DCTR (SCES201N), gate A | OR | UF, H1 -> X |
| U106 | gate B | OR | FCCN, H1 -> RFC_OFF |
| U107 | SN74LVC1G11DCKR (SCES487I) | 3-AND | BT_OK, X, FCI_OK -> Y1 |
| U108 | SN74LVC1G11DCKR | 3-AND | FCC, BTB_OFF, Y1 -> **H2c** |
| U109 | SN74LVC1G11DCKR | 3-AND | H1, RGN, W -> **H1q** |
| U110 | SN74LVC2G32DCTR, gate A | OR | H1q, H2c -> GATE |
| U110 | gate B | OR | GATE, QQ -> ILIM_PRE |
| U111 | SN74LVC1G123DCTR (SCES586E) | monostable | QUAL (B), CLR = P5N -> **QQ** |
| U113 | SN74LVC1G123DCTR | monostable | HB (B), CLR = 3V3 -> **ARM_OK** |
| U114 | SN74LVC2G08DCTR (SCES198N), gate A | AND | P5, ARM_OK -> **CE_DRV** |
| U114 | gate B | AND | ILIM_PRE, ARM_OK -> **ILIM_REL** |
| U116 | SN74LVC2G08DCTR, gate A | AND | UVB, FCCEIL -> UF |
| U116 | gate B | AND | FCCN, UVB -> W |

Readbacks to Teensy: H1 -> pin 34 (R126 1 kOhm), H2c -> pin 16 (R127), BT_OK -> pin 23 (R128); the far-end ILIM_HIZ sense
U203 -> pin 33 (EIB R265 100 ohm + CR R125 1 kOhm) and the far-end /CE sense U204 -> pin 8 (EIB R264 100 ohm only). Ribbon
drivers: CE_DRV (R130), ILIM_REL_A (R131A), ILIM_REL_B (R131B) and RFC_OFF (R132) leave CR through 100 ohm series resistors to
damp the 0.30 m flat cable. **Every plain SN74LVC input sees a CMOS-speed edge** (<= 10 ns/V required by every SN74LVC
datasheet used here, Recommended Operating Conditions): no RC filter sits in front of a plain logic input. The two RC-timed
nodes are the SN74LVC1G123 Rext/Cext pins, which are designed for it, and its A/B inputs are Schmitt inputs. TLV3012B
push-pull outputs switch in 10 ns typ (SBOS300C §6.10).

### B.4 eFuse (VCHG-IN protection)

| Ref | Part / value | Connection | Basis (SLVSE94G) |
|---|---|---|---|
| U101 | **TPS26630RGER** (VQFN-24, 4 x 4 mm; 60 V, 31 mOhm, 1x active limit, adjustable OVP cutoff) | IN (1, 2), IN_SYS (5) <- VCHGIN; OUT (17, 18) -> VCHGOUT | Device comparison table p.2; IN_SYS shorted to IN when no blocking FET (Table 5-1) |
| R101 | 8.06 kOhm 1 % | ILIM (10) -> GND | I_OL = 18/R(kOhm) = 2.23 A (Eq.5); 2.05-2.41 A with the +-8 % spread from the EC table |
| R102 / R103 / R104 | 845 kOhm / 66.5 kOhm / 49.9 kOhm, **0.1 %** | IN_SYS - UVLO (6) - OVP (7) - GND | Eq.9/10: UVLO 9.91 V rising (9.70-10.13 V); **OVP 23.12 V (22.61-23.63 V)**: 0.33 V above the 22.28 V design clamp, 0.37 V below the BQ25798 recommended VBUS maximum 24 V (SLUSDV2C §6.3) and below its VBUS_OVP 25.2-26.2 V |
| C101 | 22 nF X7R | dVdT (9) -> GND | >= 10 nF required (§6.3); ramp 7.3 ms at 15.9 V (Eq.2), 2.19 V/ms, 0.11 A into the EVM's 51.2 uF |
| C102 | 100 nF 50 V X7R | IN -> GND | >= 0.1 uF on IN (§6.3) |
| C103 | 1.0 uF 50 V X7R 0805 | OUT -> GND, within 3 mm of pins 17/18 | >= 0.1 uF on OUT (§6.3); slows the turn-off edge so D103 takes the lead current |
| D103 | 40 V, 3 A Schottky, SMA (candidate Diodes Inc. B340A-13-F, TODO(verify) Vf <= 0.45 V at 3 A, IFSM >= 75 A, leakage) | cathode VCHGOUT, anode CR power GND, within 3 mm of pins 17/18 and the exposed pad | §9.5.1 and §11: Schottky across OUT and GND to absorb the negative spike when the FET interrupts current into an inductive output. The 0.30 m lead (about 0.15 uH, estimate) would ring OUT to -1.9 V at 4.8 A with C103 alone and to about -7.7 V at 20 A (H.5); OUT absolute minimum -0.3 V (§6.1) |
| R105, C105 | 27.4 kOhm 1 %, 10 nF | IMON (13) -> GND | IMON 27.9 uA/A (25.66-30.14) -> 0.764 V/A; 1.31 V at 1.72 A; <= 1.99 V while current-regulated at I_OL |
| R129, C129 | 10.0 kOhm 1 %, 1 nF | IMON node -> pin 22 (T17); C129 at the pin side | Replaces the r0 BAT54 clamp (D102 deleted: its leakage read as 37 mA per uA, finding imon-clamp-leakage). In the <= 4.5 us fast-trip window IMON can reach 3.96 V; R129/C129 (tau 10 us) pass at most 1.44 V to the pin. Above I_OL the current is regulated, so IMON never exceeds 1.99 V for longer |
| R106 | 10 kOhm to 3V3 | FLT (14, open drain) -> pin 35 | FLT LOW on overload, OVP, UVLO, TSD. Behaviour below 4.5 V IN is unspecified: T-C-04 |
| MODE (11) | open | latch-off | Table 8-1: latch reset by SHDN cycle, UVLO low-to-high or IN_SYS power cycle; VCHG-IN goes to 0 V in every Idle, so each Run entry resets it |
| SHDN (12) | open (internal 2.48-3.3 V) | enabled | EC "LOW IQ SHUTDOWN" |
| PGTH (15), PGOOD (16) | both to GND | fast-recovery feature off, PGOOD unused (tying it LOW is allowed) | §8.3.2 |
| B_GATE (3), DRV (4) | open | no blocking FET (the RT1987s already block reverse) | Table 5-1 |
| N.C. (19-24) | open | - | Table 5-1 |

Fault behaviour: overload above I_OL is regulated at I_OL for 129-202 ms (tCL_PLIM), then latch; above 2 x I_OL (4.1-4.8 A)
the fast-trip turns the FET off in 2.2-4.5 us; a hot short above I_SCP (45 A) in 1 us (§6.6). D103 clamps OUT on each of
these turn-offs and on the OVP shutoff. The limit sits above the 1.76 A regen clamp maximum (margin 0.30 A) and above OC_FC
(1.4 A), so in an FC window a charger-side short latches OC_FC (State 99) first: a firmware stop, not a boost death. A short
of the board node VCHG-IN itself (C-D8/C-D10) is upstream of the eFuse and is covered only by the RT1987 start-up SCP
(DS-00 §17.5).

### B.5 Keep-alive option (R9; **do not populate in the baseline**)

Fit only if T-B-09 fails. Source: battery-derived 5 V rail at CO-5V (T18).

| Ref | Part | Connection | Basis |
|---|---|---|---|
| U112 | TPS22810DBVR load switch (2.7-18 V, IQ 62-80 uA on, 0.5-2.3 uA off, SLVSDH0C §7.5) | VIN <- 5V_KA; EN/UVLO <- `RGN` (D-BC-RG EN net, 3.3 V; VENR 1.13-1.3 V); CT C152 2.2 nF (DNP); QOD open | EN thresholds §7.5 |
| D101 | BAT54HT1G (30 V 0.2 A Schottky) | U112 VOUT -> anode; cathode -> R_KA | blocks VCHG -> 5 V when VCHG > 5 V (charging) |
| R_KA | 680 ohm 0.25 W 1206 | D101 -> `VCHG` | VCHG held at 3.63-4.46 V (H.10): above the RT1987 UVLO-rising maximum 3.35 V and VBAT_SHORTZ 2.25 V, below the 7.4 V pack floor |

Drain 0.65-1.28 mA plus 0.06-0.08 mA **only while REGEN is closed (Run)**; 0.5-2.3 uA parked. The round-2 M8 (1 kOhm from VBT,
always on) drew 1.2-1.7 mA continuously (29-41 mAh/day). The Run-time standby draw of the always-powered regen design itself is
2.6-3.8 mA from the bus (42-60 mW, H.15), which the energy statistics must carry whether or not the keep-alive is fitted.
**Second fallback:** bridge D-BT-SQ (0 ohm across VIN-VOUT under the footprint, before fitting CR). The pack then sits on the
BQ25798 BAT pin. Parked drain is the BQ25798 battery-only quiescent, 17-24 uA with ADC off (IQ_BAT_ON) or 11-16 uA in ship mode
(IQ_BAT_OFF), SLUSDV2C EC p.8, but the hardware pack disconnect is lost and a charger power-stage short becomes a bus -> pack
path bounded only by the eFuse.

### B.6 EVM interface board (EIB)

| Ref | Part / value | Connection | Function |
|---|---|---|---|
| U201 | **SN74LVC3G06DCTR** (triple inverter, open drain; VO 0-5.5 V recommended, 6.5 V abs max in any state; Ioff; SCES364J) | VCC = 3V3 (ribbon pin 2); C201 100 nF | Outputs float when VCC = 0 |
| ch1 | 1A = CE_DRV (ribbon 5) via R250 1 kOhm, R267 47 kOhm to AGND | 1Y -> E5 -> /CE (TP36) | CE_DRV HIGH -> /CE LOW (charge allowed); else R272 pulls /CE to REGN |
| R272 | 47 kOhm 1 % | on the EVM: /CE pad of the vacated R42 footprint -> REGN | replaces EVM R42 (to PULLUP); survives an E5 lead-off; /CE VIH 1.3 V, abs max 6 V (SLUSDV2C EC p.16, §6.1). /CE HIGH >= 4.22 V at REGN 4.8 V with U201 Ioff (10 uA) and the U204 divider load |
| ch2 | 2A = ILIM_REL_A (ribbon 7) via R251 1 kOhm, R268 47 kOhm to AGND | 2Y -> Q203 gate | ILIM_REL_A HIGH -> gate pulled LOW -> Q203 on -> release current flows |
| Q203 | BSS84-class P-MOSFET, SOT-23 (candidate onsemi BSS84LT1G; |VGS(th)| max <= 2.0 V, T-A-03) | S -> REGN (E1), D -> R255, G -> R271 47 kOhm to S | off unless 2Y sinks its gate |
| R255 | 48.7 kOhm 1 % | Q203 drain -> E2 -> JP14 ILIM-side pin | release feed (replaces EVM R21) |
| U202 | **SN74LVC1G06DCKR** (single inverter, open drain, SCES295AB) | VCC = 3V3; C202 100 nF; A = ILIM_REL_B (ribbon 8) via R266 1 kOhm, R270 47 kOhm to AGND | separate driver on its own conductor for the hold-down |
| Q201 | 2N7002K (SOT-23) | D -> E3 -> TP33 (ILIM_HIZ), S -> AGND, G -> R252 47 kOhm to REGN; U202 Y sinks the gate | holds ILIM_HIZ < 0.75 V (converter off, REGN on, SLUSDV2C §7.3.4.3) unless ILIM_REL_B is HIGH |
| ch3 | 3A = RFC_OFF (ribbon 9) via R253 1 kOhm, R269 47 kOhm to AGND | 3Y -> Q202 gate | RFC_OFF HIGH -> Q202 off -> regen clamp |
| Q202 | 2N7002K | D -> R257 -> E3 (ILIM_HIZ), S -> AGND, G -> R254 47 kOhm to REGN | R257 in parallel with EVM R23 = FC clamp |
| R257 | 59.0 kOhm 1 % | ILIM_HIZ -> Q202 drain | FC leg |
| U203 | TLV3012BIDBVR | IN+ = E4 (JP21 ILIM-side pin) via R258 100 kOhm, R259 10.0 MOhm to 3V3 on the comparator side; IN- = own REF x R261/(R260+R261) (R260 10.0 kOhm, R261 26.1 kOhm): 0.86-0.93 V; C203 100 nF | **far-end ILIM_HIZ sense**, output via R265 100 ohm -> ribbon 11 -> CR R125 -> pin 33 (HIGH = released) |
| U204 | TLV3012BIDBVR | IN+ = E6 (JP17 /CE-side pin) via R262 1.00 MOhm, R263 1.00 MOhm to AGND (/CE / 2); IN- = own REF (1.22-1.26 V): /CE threshold about 2.5 V; C204 100 nF | **far-end /CE sense**, output via R264 100 ohm -> ribbon 13 -> CR -> T20 -> pin 8 (HIGH = /CE HIGH = inhibited) |
| - | wire | E7 TP38 STAT -> ribbon 4 | STAT to Teensy 6 via CR R107 pull-up |
| J201 | 2x7 shrouded 2.54 mm | ribbon W5 | - |

EVM side (EM list C): EVM R21 removed, JP14 shunt removed, JP13/JP21 open, **EVM R23 replaced by 49.9 kOhm 1 %**, R256 200 kOhm
and C252 2.2 nF fitted at TP33, R272 47 kOhm fitted at the R42 site to REGN.

ILIM levels (H.4, including +-1.5 uA pin leakage, 1 uA FET leakage and the sense pull-up): **regen clamp 1.33-1.76 A** (pin
2.06-2.40 V), **FC clamp (Q202 on) 0.65-0.95 A** (pin 1.52-1.76 V), **held <= 0.11 V** with Q203 off even if Q201 has failed
open (<= 0.57 V if EVM R23 has also failed open: R256 alone). The U203 threshold (0.86-0.93 V) sits between the held level and the lowest released level.

Single faults on the EIB/EVM side (all inhibit nodes now observed at the EVM pin):

| Fault | Converter | Detected by |
|---|---|---|
| E2 (feed) lead off, R255 open, Q203 open, U201 2Y stuck open, ribbon 7 open (R268 pulls 2A LOW) | stays in HIZ (no release current) | U203 reads held while GATE expected: non-latching "permit stuck LOW" (FR-08) |
| Q201 open, R252 open (gate floats, may turn off), U202 stuck open, ribbon 8 open | held by Q203 off (no feed) | latent until Q203 also fails; T-C-05 at every build (J.2) |
| Q203 drain-source short, U201 2Y stuck sinking | held by Q201 | latent until Q201 also fails; T-C-05 (J.2) |
| Q201 drain-source short | permanent HIZ (safe) | U203 stuck LOW while released expected |
| E3 lead off | Q203 off still leaves no feed (HIZ); FC leg lost -> regen clamp in FC windows | FC clamp loss not visible to U203; bounded by the FC image register, FR-09 and OC_FC (H.12) |
| E4 sense lead off, U203 dead | none | R259 pulls IN+ to 3.3 V -> reads released (dangerous direction) -> trip latch when GATE expected 0. U203 unpowered sinks -> reads held -> stuck-LOW flag |
| EVM R23 open | held by Q201 and by Q203 off; R256 alone keeps the pin <= 0.57 V (H.4) | released level rises (bottom = R256 only), so REG19 at qualification reads far above the regen band -> T1 refuses to arm; R23 also checked power-off in T-A-02 |
| E5 lead off, U201 1Y stuck open, ribbon 5 open (R267 pulls 1A LOW) | /CE pulled HIGH by R272 (inhibit) | U204 reads /CE HIGH while P5 armed: stuck-inhibit flag |
| U201 1Y stuck sinking | /CE stuck LOW (charge allowed) | U204 reads /CE LOW while P5 LOW -> trip latch (FR-08) and the T1 entry check refuses QUAL |
| E6 sense lead off, U204 dead | none | R263 pulls IN+ to 0 / unpowered output sinks -> reads /CE LOW -> trip latch whenever P5 is LOW (dangerous direction, announces itself) |
| 3V3 lost on the EIB | all open-drain outputs float: /CE HIGH (R272), Q201 on (R252), Q203 off (R271), Q202 on (R254): HIZ + FC clamp | U203/U204 unpowered sink: pin 33 LOW, pin 8 LOW (/CE LOW reading) -> mismatch while P5 LOW -> flagged |

REGN exists whenever the converter can run (SLUSDV2C §7.3.4.1), so the stages are biased exactly when they are needed. While
REGN is absent (charger unpowered) /CE and ILIM_HIZ read 0 V; FR-08 evaluates the far-end senses only when the charger is
powered (V_chg > 10.2 V for > 200 ms, i.e. after REGN has come up 150 ms after VBUS valid, SLUSDV2C §7.3.4 step 5).
2N7002K and BSS84 thresholds, on-resistance, Ciss and off-state leakage at 2-3 V are not in the library: T-A-03.

### B.7 Power-up and reset states of every node

| Condition | P5 | QUAL / QQ | FCCEIL | HB / ARM_OK | H1, UVB, BT_OK, BTB_OFF | GATE | ILIM_HIZ | /CE | Charger |
|---|---|---|---|---|---|---|---|---|---|
| Teensy unpowered / pack disconnected | - | - | - | - | unpowered (LOW) | - | (EVM unpowered) | - | no input power: every RT1987 EN LOW |
| Teensy reset / boot (pins high-Z) | LOW (R108) | LOW / 0 | LOW | no edges / 0 after tw | valid | 0 (RGN = FCC = 0) | LOW if REGN up | HIGH | unpowered (REGEN/FCC EN pull-downs) |
| Monostable power-up | any | QQ = 0 (glitch-free reset, SCES586E) | any | ARM_OK = 0 until the first HB edge | - | - | held | HIGH | - |
| Comparator POR (<= 1.9 ms) | any | any | any | any | LOW | H2c = 0, H1q = 0 | follows QQ AND ARM_OK | P5 AND ARM_OK | inhibited |
| CR 3V3 lost while armed | (Teensy may still drive) | - | - | - | unpowered | logic unpowered | LOW (Q201 via REGN, Q203 off) | HIGH (R272) | off, FC clamp |
| Charger POR (input glitch) | as before | as before | as before | running | valid | per mode | per mode | per P5 | EN_CHG = 1, ICHG default, IINDPM = pin clamp at that instant, VINDPM = VBUS0 - 1.4 V; firmware re-images (G.2) |
| Teensy hang (pins frozen) | frozen | frozen QUAL: QQ ends after tw | frozen | **no edges: ARM_OK = 0 within 30-40 ms** | valid | hardware | **held** | **HIGH** | inhibited and converter off in every mode; BT_BUS stays where it was (residual, R5) |

### B.8 Pin-level netlist (CR and EIB; the source for the KiCad capture, PM0 / T-A-06)

Pin numbers from the datasheet pin tables: TLV3012 DBV (SBOS300C Table 5-1: 1 OUT, 2 V-, 3 IN+, 4 IN-, 5 REF, 6 V+);
SN74LVC3G04/3G06 DCT (SCES363L/SCES364J: 1 1A, 2 3Y, 3 2A, 4 GND, 5 2Y, 6 3A, 7 1Y, 8 VCC); SN74LVC2G32/2G08 DCT
(SCES201N/SCES198N: 1 1A, 2 1B, 3 2Y, 4 GND, 5 2A, 6 2B, 7 1Y, 8 VCC); SN74LVC1G11 DCK (SCES487I: 1 A, 2 GND, 3 B, 4 Y, 5 VCC,
6 C); SN74LVC1G123 DCT (SCES586E: 1 A, 2 B, 3 CLR, 4 GND, 5 Q, 6 Cext, 7 Rext/Cext, 8 VCC); SN74LVC1G06 DCK (SCES295AB: 1 NC,
2 A, 3 GND, 4 Y, 5 VCC); TPS26630 RGE (SLVSE94G Table 5-1, VQFN column); SOT-23 MOSFETs 1 G, 2 S, 3 D (TODO(verify) against
the chosen MPN datasheets, T-A-05). No gate input is left floating: every unused input is tied to GND or VCC.

**Carrier (CR):**

| Ref | Pin -> net |
|---|---|
| U101 TPS26630RGER | 1, 2 IN -> VCHGIN; 3 B_GATE nc; 4 DRV nc; 5 IN_SYS -> VCHGIN; 6 UVLO -> N_UV; 7 OVP -> N_OV; 8 GND -> GND; 9 dVdT -> C101; 10 ILIM -> R101; 11 MODE nc; 12 SHDN nc; 13 IMON -> N_IMON; 14 FLT -> CHG_EFUSE_FLT; 15 PGTH -> GND; 16 PGOOD -> GND; 17, 18 OUT -> VCHGOUT; 19-24 nc; PAD -> GND (>= 9 vias) |
| R102 / R103 / R104 | VCHGIN - N_UV / N_UV - N_OV / N_OV - GND |
| R101, C101, C102 | ILIM - GND; dVdT - GND; VCHGIN - GND |
| C103, D103 | VCHGOUT - GND; D103 K -> VCHGOUT, A -> GND |
| R105, C105 / R129 / C129 | N_IMON - GND (both) / N_IMON - CHG_IIN (P18) / CHG_IIN - GND |
| R106 | CHG_EFUSE_FLT - 3V3; CHG_EFUSE_FLT -> P17 |
| U102 (H1) | 1 OUT -> H1; 2 V- -> GND; 3 IN+ -> N_H1P; 4 IN- -> N_H1M; 5 REF nc; 6 V+ -> 3V3 (C110) |
| R109 / R110 / C106 / R113 / D104 | P1 - N_H1P / N_H1P - GND / N_H1P - GND / H1 - N_H1P / D104 3 -> N_H1P, 1 -> GND, 2 -> 3V3 |
| R111 / R112 / C107 / D105 | T2C (P3) - N_H1M / N_H1M - GND / N_H1M - GND / as D104 on N_H1M |
| U103 (UVB) | 1 OUT -> UVB; 2 -> GND; 3 IN+ -> N_UVP; 4 IN- -> REF103; 5 REF -> REF103; 6 -> 3V3 (C111) |
| R114 / R115 / C108 / R116 / D106 | T2C - N_UVP / N_UVP - GND / N_UVP - GND / UVB - N_UVP / as D104 on N_UVP |
| U104 (BT_OK) | 1 OUT -> BT_OK; 2 -> GND; 3 IN+ -> N_BTP; 4 IN- -> N_BTM; 5 REF -> REF104; 6 -> 3V3 (C112) |
| R141 / R142 / R143 | REF104 - N_BTP / N_BTP - KELVIN (P10) / KELVIN - GND |
| R140 / C140 / R144 | P9 (BT_CURR) - N_BTM / N_BTM - GND / P9 - 3V3 |
| U115 (BTB_OFF) | 1 OUT -> BTB_OFF; 2 -> GND; 3 IN+ -> N_BBP; 4 IN- -> N_BBM; 5 REF -> REF115; 6 -> 3V3 (C113) |
| R117 / R118 / C109 | REF115 - N_BBP / N_BBP - GND / N_BBP - GND |
| R120 / R119 | P4 (BTB) - N_BBM / N_BBM - 3V3 |
| U117 (DNP) | as U102 with IN- -> P23 via 10 kOhm, IN+ -> REF divider (R160/R161 DNP), OUT -> FCI_OK; R137 0 ohm FCI_OK - 3V3 fitted when U117 is not |
| R121 / R133 | P5 (RGN tap) - RGN / RGN - GND |
| R122 / R134 | P6 (FCC tap) - FCC / FCC - GND |
| R108 | P5_NET (CHG pad 11) - GND |
| R147 / R123 | P11 (QUAL) - QUAL / QUAL - GND |
| R124 | FCCEIL (P12) - GND |
| R135 / R136 | P21 (HB) - HB / HB - GND |
| U105 SN74LVC3G04 | 1 1A <- FCC; 7 1Y -> FCCN; 3 2A <- P5_NET; 5 2Y -> P5N; 6 3A -> GND; 2 3Y nc; 4 GND; 8 VCC (C114) |
| U106 SN74LVC2G32 | 1 1A <- UF; 2 1B <- H1; 7 1Y -> X; 5 2A <- FCCN; 6 2B <- H1; 3 2Y -> RFC_OFF; 4 GND; 8 VCC (C115) |
| U107 SN74LVC1G11 | 1 A <- BT_OK; 3 B <- X; 6 C <- FCI_OK; 4 Y -> Y1; 2 GND; 5 VCC (C116) |
| U108 SN74LVC1G11 | 1 A <- FCC; 3 B <- BTB_OFF; 6 C <- Y1; 4 Y -> H2C; 2 GND; 5 VCC (C117) |
| U109 SN74LVC1G11 | 1 A <- H1; 3 B <- RGN; 6 C <- W; 4 Y -> H1Q; 2 GND; 5 VCC (C118) |
| U110 SN74LVC2G32 | 1 1A <- H1Q; 2 1B <- H2C; 7 1Y -> GATE; 5 2A <- GATE; 6 2B <- QQ; 3 2Y -> ILIM_PRE; 4 GND; 8 VCC (C119) |
| U111 SN74LVC1G123 | 1 A -> GND; 2 B <- QUAL; 3 CLR <- P5N; 5 Q -> QQ; 6 Cext - C150 - 7; 7 Rext/Cext - R150 - 3V3; 4 GND; 8 VCC (C120) |
| U113 SN74LVC1G123 | 1 A -> GND; 2 B <- HB; 3 CLR -> 3V3; 5 Q -> ARM_OK; 6 Cext - C151 - 7; 7 Rext/Cext - R151 - 3V3; 4 GND; 8 VCC (C121) |
| U114 SN74LVC2G08 | 1 1A <- P5_NET; 2 1B <- ARM_OK; 7 1Y -> CE_DRV; 5 2A <- ILIM_PRE; 6 2B <- ARM_OK; 3 2Y -> ILIM_REL; 4 GND; 8 VCC (C122) |
| U116 SN74LVC2G08 | 1 1A <- UVB; 2 1B <- FCCEIL; 7 1Y -> UF; 5 2A <- FCCN; 6 2B <- UVB; 3 2Y -> W; 4 GND; 8 VCC (C123) |
| Readbacks | R126 H1 - P14; R127 H2C - P15; R128 BT_OK - P16; R125 J101.11 (ILIM_SENSE) - P13; J101.13 (CE_SENSE) - P20 direct |
| Ribbon drivers | R130 CE_DRV - J101.5; R131A ILIM_REL - J101.7; R131B ILIM_REL - J101.8; R132 RFC_OFF - J101.9 |
| J101 (2x7) | 1, 3, 6, 10, 12, 14 GND; 2 3V3; 4 STAT; 5 CE_DRV; 7 ILIM_REL_A; 8 ILIM_REL_B; 9 RFC_OFF; 11 ILIM_SENSE; 13 CE_SENSE |
| CHG pins | 10 -> VCHGIN (+ VCHGIN2 pad for W8); 4, 14, 15 -> GND; 18, 19 -> VCHG; 3 -> STAT (R107 to 3V3, J101.4); 11 -> P5_NET; 8 -> SDA (R145 to 3V3, W7); 7 -> SCL (R146 to 3V3, W7); 13 -> TS_EXT (W6); others anchors |
| Tap field | P1 T1, P2 T7b, P3 T2 (= T2C), P4 T3, P5 T4, P6 T5, P7 3V3, P8 GND, P9 T8, P10 T9 KELVIN, P11 T10, P12 T11, P13 T12, P14 T13, P15 T14, P16 T15, P17 T16, P18 T17, P19 T17r GND, P20 T20, P21 T21, P22 T18 (DNP), P23 T19 (DNP), P24 spare |
| Keep-alive (DNP) | U112 TPS22810: VIN <- P22, EN/UVLO <- RGN, CT -> C152, VOUT -> D101 A; D101 K -> R_KA -> VCHG |
| Decoupling | C110-C123 100 nF X7R 0603 at each VCC/V+ pin as listed; C124 (U117, DNP); C125 10 uF 10 V X7R 0805 bulk on 3V3 at P7 |

**EIB:**

| Ref | Pin -> net |
|---|---|
| U201 SN74LVC3G06 | 1 1A <- N_CEIN; 7 1Y -> nCE_DRV (E5); 3 2A <- N_RAIN; 5 2Y -> Q203_G; 6 3A <- N_RFIN; 2 3Y -> Q202_G; 4 GND -> AGND; 8 VCC -> 3V3 (C201) |
| R250 / R267 | J201.5 - N_CEIN / N_CEIN - AGND |
| R251 / R268 | J201.7 - N_RAIN / N_RAIN - AGND |
| R253 / R269 | J201.9 - N_RFIN / N_RFIN - AGND |
| U202 SN74LVC1G06 | 1 NC; 2 A <- N_RBIN; 4 Y -> Q201_G; 3 GND; 5 VCC -> 3V3 (C202) |
| R266 / R270 | J201.8 - N_RBIN / N_RBIN - AGND |
| Q203 BSS84 | 1 G -> Q203_G; 2 S -> REGN (E1); 3 D -> R255 -> ILIM_FEED (E2); R271 Q203_G - REGN |
| Q201 2N7002K | 1 G -> Q201_G; 2 S -> AGND; 3 D -> ILIM_HOLD (E3); R252 Q201_G - REGN |
| Q202 2N7002K | 1 G -> Q202_G; 2 S -> AGND; 3 D -> R257 -> ILIM_HOLD (E3); R254 Q202_G - REGN |
| U203 TLV3012B | 1 OUT -> R265 -> J201.11; 2 -> AGND; 3 IN+ -> N_ISP; 4 IN- -> N_ISM; 5 REF -> REF203; 6 -> 3V3 (C203) |
| R258 / R259 / R260 / R261 | E4 (ILIM_SNS) - N_ISP / N_ISP - 3V3 / REF203 - N_ISM / N_ISM - AGND |
| U204 TLV3012B | 1 OUT -> R264 -> J201.13; 2 -> AGND; 3 IN+ -> N_CSP; 4 IN- -> REF204; 5 REF -> REF204; 6 -> 3V3 (C204) |
| R262 / R263 | E6 (nCE_SNS) - N_CSP / N_CSP - AGND |
| J201 (2x7) | as J101; 4 STAT <- E7 (TP38); GND pins -> AGND -> E8 (TP49) |
| Local | C205 100 nF REGN - AGND at Q203 source |

### B.9 What the carrier and the EIB need from the firmware

The hardware above needs four firmware behaviours, specified in G.2: the heartbeat toggled once per `loop()` (FR-28), QUAL
raised only after EN_CHG = 0 is verified (FR-04), the two far-end senses compared in the dangerous direction (FR-08), and
FC_CHARGE/BT_BUS never HIGH together (FR-06, I-9).

## C. EVM modification list (BQ25798EVM BMS034A/B-003, SLUUCB5E Table 1-3, Fig 4-5/4-6, BOM Table 4-1)

Make every change **before the first power-up**. Never move a PROG jumper with power applied. Parts on the EVM are written
"EVM Rnn" elsewhere in this document.

| ID | Item | Stock | Change | Reason / evidence |
|---|---|---|---|---|
| EM1 | JP17 | installed (/CE to GND) | **remove the shunt**; its /CE-side header pin becomes the U204 sense joint (E6) | Stock EVM charges at POR (SLUSDV2C Table 7-9 p.41). /CE now driven by EIB ch1 |
| EM2 | R42 (10.0 kOhm, /CE -> PULLUP) | fitted | **remove**; fit **R272 47 kOhm** from the /CE pad of the vacated footprint to a REGN point (<= 10 mm Kynar) | /CE pull-up to REGN that survives an E5 lead-off (B.6) |
| EM3 | R21 (127 kOhm, REGN -> JP14 -> ILIM_HIZ) | 127 kOhm | **remove R21; remove the JP14 shunt**; JP13 and JP21 open; JP14's ILIM-side pin becomes the feed joint (E2), JP21's ILIM-side pin the sense joint (E4) | Release current now comes only through EIB Q203 + R255 (B.6, finding eib-wireoff-releases-converter) |
| EM4 | R23 (100 kOhm, ILIM_HIZ -> GND) | 100 kOhm | **replace with 49.9 kOhm 1 % 0603** (measure the removed part and the new one, T-A-02) | Halves the leakage error of the clamps (H.4) |
| EM5 | TP33 pad | - | **add R256 200 kOhm 1 % and C252 2.2 nF C0G** from the TP33 pad to the nearest AGND point (0603, tacked on the pad) | R23-open guard (H.4) and release-glitch filter (H.13) |
| EM6 | R39, R40 (10.0 kOhm SCL/SDA -> PULLUP) | fitted | **remove** | The board's RSCL/RSDA 10 kOhm and CR R145/R146 2.7 kOhm to Teensy 3V3 are the only pull-ups; no back-powering (spec §3.2) |
| EM7 | J2 terminal block | fitted | **remove (desolder) or insulate** | Live at VCHG-IN through JP4 |
| EM8 | JP32 (STAT LED) | installed | **remove** | STAT swings only to Teensy 3V3 via CR R107 |
| EM9 | JP9 | 2 to J5 pin 1 | **2-3 (BATP at the BAT pin)** | CV sensed at the IC; never floating |
| EM10 | JP1, JP2 | 1-2 (ACDRV to FETs) | **2-3 (GND)** | No input FETs; EN_ACDRV locks at 0 (SLUSDV2C Table 7-29) |
| EM11 | JP3, JP4 | not installed | **install both** | VAC1/VAC2 tied to VBUS; VAC2 must not float with ACFET2/RBFET2 absent (SLUSDV2C Table 5-1 p.5, §7.3.5.2) |
| EM12 | JP5 | not installed | **install** | BAT to BATTERY bypass (ship FET Q5 bypassed) |
| EM13 | JP8 | 2-3 | **1-2** | SLUUCB5E Table 1-3: JP8 1-2 with JP5 when ship mode is not used |
| EM14 | C11, C12 (VBUS), C29, C30, C31 (PMID) | 10 uF 25 V X5R 0805 (C2012X5R1E106K125AB) | **10 uF >= 35 V, 0805** (candidate Murata GRM21BR6YA106KE43L, 35 V X5R; effective capacitance at 21 V from the DC-bias curve, T-A-04) | VCHG-IN reaches 21.2-21.5 V measured, design clamp 21.98-22.28 V; eFuse OVP now <= 23.63 V |
| EM15 | JP30 | installed (PULLUP LDO U2 fed from VBUS via D11/R35 and from BAT via D12) | **remove the shunt** | The PULLUP rail has no load left (R39, R40, R42, JP32 gone; /INT unused; TS fed from REGN via JP12). Removing it de-energises U2 and C43/C44 (0.1 uF 25 V, which would otherwise see VCHG-IN minus one diode) and stops the D12 drain from VCHG. If /INT is ever used, pull it to Teensy 3V3, not to PULLUP |
| EM16 | JP6, JP10, JP11 | installed | **remove** | No D+/D-; AUTO_INDET_EN written 0 (G.1) |
| EM17 | JP7 | USB_VIN to VAC1 | **remove** | Otherwise J6 (micro-USB VBUS pin) is live at VCHG-IN |
| EM18 | TS: JP18 / J7 | JP18 installed | **if a pack NTC is fitted (T-E-09): remove JP18, wire J7 (W6). Otherwise keep JP18**; JP12 stays installed ("must remain connected"); JP15, JP16, JP19, JP20 open | Table 1-3; never rely on TS_IGNORE (reset by WD, Table 7-34) |
| EM19 | JP24 | installed (2S, 1.5 MHz) | **keep**; JP22, JP23, JP25-JP29 open | POR VREG 8.4 V 2S (Table 7-2). EVM R29 is 6.04 kOhm in Fig 4-6 but 6.20 kOhm in the BOM: read back CELL = 1h, PWM_FREQ = 0 (T-B-01) |
| EM20 | JP31, JP33 | open | keep open | no EV2400/USB2ANY pull-ups |
| EM21 | RSNUB1/CSNUB1 (no footprint) | - | not fitted | The UG note applies to hot-plugging adapters > 15 V; here VCHG-IN is ramped by the RT1987 (12 V/ms) and the eFuse dVdT (2.2 V/ms) |
| EM22 | S1 (QON) | - | do not press | ship/reset |
| EM23 | Bumpons H1-H4 | fitted | remove; M3 nylon standoffs (hole diameter checked, T-A-02) | mounting |
| EM24 | **No input capacitor** of any kind added | - | - | Death-5 class; EVM input is 50.2 uF ceramic only, no electrolytic (UG BOM; C25, C33/C34 DNP) |
| EM25 | Bring-up procedure | - | skip the SLUUCB5E step that checks TP42 (PULLUP) for 3.3 V; instead confirm TP42 < 0.1 V with VCHG-IN at 18.5 V (T-B-01) | JP30 out |

## D. Motherboard modification list

### D.1 Rework

| ID | Change | Procedure / check |
|---|---|---|
| PM0 | **Capture CR and EIB in KiCad from B.8**, run ERC/DRC, generate Gerbers and drill files (pick-and-place optional: hand assembly) | Gate before PM4: T-A-06 (netlist diff against B.8 = zero; 1:1 print of the hole pattern over the bare CHG footprint) |
| PM1 | **Remove the Ag105 (CHG)** | Pack unplugged at J-BT, all supplies off, VBUS/V-MOT discharged (< 1 V on C-D2 and CAL). Desolder all 22 pins (1.1 mm holes) with a vacuum station; protect CO-5V (0.1 mm away) and OP-FC with Kapton. Inspect D-BT-SQ, C-D11, C-D12, C-DC11, C-DC12 under the footprint. **Do it only after the T-B and T-C gates pass on the bench** (study condition 13) |
| PM2 | **Replace C-D8 and C-D10** (GRM21BZ71E106KE15L, 10 uF 25 V, **0805 footprint CAPC2012**) with 10 uF >= 35 V 0805 (candidate GRM21BR6YA106KE43L; T-A-04) | Inrush in H.6 uses 20 uF nominal; a lower effective value only lowers the inrush |
| PM3 | **Fit R170 and R171** (10.0 kOhm 0.1 % 0805): one end soldered to C-D6 pad 1 (R170) and C-D2 pad 1 (R171), the T1/T2 wires soldered to the free ends, Kapton over each | Every divider tap is then high-impedance at the source |
| PM4 | **Fit CR** on the 22 holes: header pins through, 2.54 mm spacer, solder all 22 from the bottom | Continuity: CR VCHGIN to C-D8, CR VCHG to C-D11, CR GND to J1.01 |
| PM5 | **W8**: 20 AWG from C-D8 pad 1 to CR pad `VCHGIN2` | Second VIN+ path |
| PM6 | **Taps** per A.4: T1/T2 to R170/R171, T7b to C-D6 pad 2, T9 to the SNS-BT GND/REF1 pad (or nearest via), the rest into J1/J2 with single male pins | T-A-01 first |
| PM7 | **T18 (keep-alive) only if T-B-09 fails**; T19 only with the U117 option; else leave the DNP parts unpopulated | - |
| PM8 | **No trace cuts.** No change to D-BT-SQ in the baseline. Bridging D-BT-SQ is fallback 2 only (B.5). C-DC4 (D-BT-EN soft-start) stays 5.6 nF unless the operator rules lever 3(i) (F.4) | - |

### D.2 Firmware-visible pin changes

Pin 5 changes meaning (MPPT_DISABLE LOW = Ag105 MPPT inhibited -> CHG_ARM LOW = BQ25798 charge inhibited); both are LOW =
safe, so the boot level in `setup()` stays LOW. Pin 6 polarity inverts (Ag105 HIGH = charging -> BQ25798 LOW = charging,
SLUSDV2C Table 7-11). Pin 8 becomes an input from the carrier (RENC2 still pulls it up); pin 21 becomes the heartbeat output.
**The EVM must not be connected until the CSV is amended and firmware with the new pin map is flashed** (fw v37 State 98 `4`
toggles pin 5 raw; study §2.8).

### D.3 IO CSV amendments (`references/Scale Car Teensy IO - IO.csv`; the CSV is authoritative, amend it first)

Replace rows 5, 6, 31; add rows 8, 10, 16, 17, 21, 22, 23, 33, 34, 35 (exact text):

```
5,Output,Digital,Charger arm (BQ25798 /CE through the CHG carrier),CHG_ARM,"HIGH = charging allowed (carrier ANDs it with the heartbeat; EIB U201 pulls /CE LOW). LOW or high-Z = inhibited (47 kOhm pull-down on the carrier). Was MPPT_DISABLE (Ag105 removed)"
6,Input,Digital,Charger status (BQ25798 STAT),CHARGER_STAT,"Open drain: LOW = charging, HIGH = complete/disabled/HIZ, 1 Hz blink = fault (SLUSDV2C Table 7-11). 10 kOhm pull-up to 3V3 on the carrier"
8,Input,Digital,Charger /CE far-end readback,CHG_CE_RB,"HIGH = /CE HIGH at the EVM pin (charging inhibited). From a comparator on the EIB; RENC2 pull-up on the MB stays. Valid only while the charger is powered"
10,Output,Digital,Charger input-qualification trigger,CHG_QUAL,"Rising edge starts a 0.30-0.40 s hardware one-shot that releases ILIM_HIZ; cleared while CHG_ARM is HIGH. Raise only after EN_CHG = 0 is read back. 47 kOhm pull-down"
16,Input,Digital,Charger FC-window permit readback,CHG_H2_RB,"H2c = FC_CHARGE AND BTB_OFF AND BT_OK AND ((UVB AND CHG_FCCEIL) OR H1)"
17,Output,Digital,Charger FC ceiling confirmed,CHG_FCCEIL,"HIGH only while the BQ25798 IINDPM/ICHG registers hold verified FC-window values. LOW blanks the converter in an FC window whenever V-MOT is not above 1.089 x VBUS. 47 kOhm pull-down"
21,Output,Digital,Charger heartbeat,CHG_HB,"Toggle once per loop() after detectFaults() and the interlock monitor, never from an ISR. No rising edge for 30-40 ms drops the charge enable and holds ILIM_HIZ in hardware. 100 kOhm pull-down"
22,Input,Analog,Charger input current (eFuse IMON),CHG_IIN,"TPS26630 IMON 27.9 uA/A into 27.4 kOhm = 0.764 V/A; 10 kOhm + 1 nF to the pin"
23,Input,Digital,BT boost current below the FC-window threshold,CHG_BTOK_RB,"HIGH = INA253 BT output below 19.75 mV (about 0.2 A)"
31,Output,Digital,Fuel cell charging enable,FC_CHARGE_ENABLE,"Allow Vbus (fuel cell) to flow to the battery charger. BT_BUS_ENABLE *must* be off before this is turned on, and the two are never on together. REGEN_ENABLE MAY stay on (operator ruling 2026-11-05, R7); requires the BQ25798 carrier permit logic"
33,Input,Digital,Charger ILIM_HIZ far-end readback,CHG_ILIM_RB,"HIGH = ILIM_HIZ above 0.86-0.93 V at the EVM pin (converter released). From a comparator on the EIB; a broken sense wire reads HIGH"
34,Input,Digital,V-MOT above bus comparator readback,CHG_H1_RB,"HIGH = V-MOT > 1.089 x VBUS (+0.30 V hysteresis). Pad GPIO_B1_13: keep it GPIO, never WDOG1_B (ALT0)"
35,Input,Digital,Charger input eFuse fault,CHG_EFUSE_FLT,"Open drain, LOW = fault; 10 kOhm pull-up on the carrier"
```

Conditional row, only if T-E-02 adopts a purge-valve tap: `2,Input,Digital,H-20 purge valve sense,PURGE_SENSE,"Optocoupler from the H-20 purge-valve drive; LOW = valve open"`.

### D.4 CLAUDE.md bodge record (add under the never-rotated hardware records once built)

```
### Hardware bodge record (20XX-XX-XX): Ag105 removed, BQ25798EVM fitted through the CHG carrier

- The Silvertel Ag105 (`CHG`) is desoldered. A carrier PCB (eFuse TPS26630 + output Schottky, comparators H1/UVB/BT_OK/BTB_OFF,
  permit logic, QUAL one-shot and heartbeat monostables) is soldered into the 22 CHG holes; a TI BQ25798EVM sits off-board on
  <= 0.30 m leads (input 20 AWG pair, battery 18 AWG pair, I2C 4-way to EVM J8, 14-way ribbon to a chassis-mounted EVM
  interface board that drives /CE and ILIM_HIZ from REGN and senses both at the EVM pins).
- C-D8 and C-D10 are 10 uF >= 35 V 0805 (were 25 V GRM21BZ71E106KE15L).
- Bodge parts and wires: R170/R171 10.0 kOhm at C-D6 pad 1 (V-MOT) and C-D2 pad 1 (VBUS) feeding the carrier dividers; a
  Kelvin wire from the SNS-BT GND/REF1 pad; W8 20 AWG from C-D8 pad 1 to the carrier; taps into the J1/J2 breakout for the EN
  nets of pins 28/30/31, 3V3, GND, BT-CURR and pins 8/10/16/17/21/22/23/33/34/35.
- EVM mods per docs/charger_bq25798_wiring_design_2026-11-05.md section C (JP17, R42, R21, R39, R40, JP32, JP7, JP30, JP14
  shunt removed; R23 49.9k; R256/C252 at TP33; R272 47k /CE -> REGN; JP1/JP2 2-3, JP3/JP4/JP5 in, JP8 1-2, JP9 2-3; input
  caps >= 35 V; J2 removed).
- Keep-alive: [not fitted | fitted: TPS22810 + BAT54 + 680 ohm from the 5 V rail, enabled by the REGEN net] (decided by T-B-09).
- IO CSV rows 5, 6, 8, 10, 16, 17, 21, 22, 23, 31, 33, 34, 35 amended in lockstep. Any rework that removes the carrier must
  revert firmware, CSV and tests together.
```

## E. Bill of materials

Stock: TI store inventory endpoint, plain curl, 2026-11-05 22:00 UTC (TI parts only). **Every MPN below is a candidate that
T-A-05 checks against its manufacturer datasheet before ordering** (rating, tolerance, TCR, package, pinout); non-TI stock and
all non-EVM prices are not verified, and the cost column is a budget allowance.

| Ref | Qty (+spare) | Part | MPN (candidate) | Package | Source | Unit cost |
|---|---|---|---|---|---|---|
| EVM | 2 | BQ25798 evaluation module | BQ25798EVM | - | https://www.ti.com/tool/BQ25798EVM (162 in stock) | USD 156.45 (verified) |
| U101 | 1 (+1) | eFuse 60 V, 1x limit, adj. OVP | TPS26630RGER | VQFN-24 4x4 | https://www.ti.com/product/TPS2663 (40) | allowance USD 4 |
| U102-U104, U115, U203, U204 | 6 (+2); U117 DNP 1 | comparator + 1.242 V ref, push-pull, POR | TLV3012BIDBVR | SOT-23-6 | https://www.ti.com/product/TLV3012 (27 694) | USD 1 |
| U105 | 1 (+1) | triple inverter | SN74LVC3G04DCTR | SSOP-8 | https://www.ti.com/product/SN74LVC3G04 | USD 0.5 |
| U106, U110 | 2 (+1) | dual OR | SN74LVC2G32DCTR | SSOP-8 | https://www.ti.com/product/SN74LVC2G32 | USD 0.5 |
| U107-U109 | 3 (+1) | 3-input AND | SN74LVC1G11DCKR | SC70-6 | https://www.ti.com/product/SN74LVC1G11 | USD 0.5 |
| U111, U113 | 2 (+1) | retriggerable monostable, Schmitt inputs | SN74LVC1G123DCTR | SSOP-8 | https://www.ti.com/product/SN74LVC1G123 | USD 0.6 |
| U114, U116 | 2 (+1) | dual AND | SN74LVC2G08DCTR | SSOP-8 | https://www.ti.com/product/SN74LVC2G08 | USD 0.5 |
| U201 | 1 (+1) | triple open-drain inverter | SN74LVC3G06DCTR | SSOP-8 | https://www.ti.com/product/SN74LVC3G06 | USD 0.5 |
| U202 | 1 (+1) | single open-drain inverter | SN74LVC1G06DCKR | SC70-5 | https://www.ti.com/product/SN74LVC1G06 | USD 0.3 |
| U112 (DNP) | 1 | load switch 18 V | TPS22810DBVR | SOT-23-6 | https://www.ti.com/product/TPS22810 | USD 1 |
| Q201, Q202 | 2 (+3) | N-MOSFET 60 V logic level | onsemi 2N7002KT1G | SOT-23 | distributor | USD 0.2 |
| Q203 | 1 (+2) | P-MOSFET 50 V, |VGS(th)| <= 2.0 V | onsemi BSS84LT1G | SOT-23 | distributor | USD 0.2 |
| D103 | 1 (+1) | Schottky 40 V 3 A | Diodes Inc. B340A-13-F | SMA | distributor | USD 0.4 |
| D104-D106 | 3 (+2) | low-leakage diode pair | Nexperia BAV199,215 | SOT-23 | distributor | USD 0.2 |
| D101 (DNP) | 1 | Schottky 30 V 0.2 A | onsemi BAT54HT1G | SOD-323 | distributor | USD 0.2 |
| R109 | 1 | 487 kOhm 0.1 % 25 ppm | Vishay TNPW0603487KBEEA | 0603 | distributor | USD 0.5 |
| R111 | 1 | 442 kOhm 0.1 % | TNPW0603442KBEEA | 0603 | | USD 0.5 |
| R110, R112 | 2 | 56.2 kOhm 0.1 % | TNPW060356K2BEEA | 0603 | | USD 0.5 |
| R114 | 1 | 1.00 MOhm 0.1 % | TNPW06031M00BEEA | 0603 | | USD 0.5 |
| R115 | 1 | 104 kOhm 0.1 % | TNPW0603104KBEEA | 0603 | | USD 0.5 |
| R102, R103, R104 | 1 + 1 + 1 | 845 k, 66.5 k, 49.9 k 0.1 % | TNPW0603845KBEEA, TNPW060366K5BEEA, TNPW060349K9BEEA | 0603 | | USD 0.5 |
| R170, R171 | 2 (+2) | 10.0 kOhm 0.1 % (MB joints) | TNPW080510K0BEEA | 0805 | | USD 0.5 |
| R113, R116 | 1 + 1 | 6.49 MOhm, 11.0 MOhm 1 % | Vishay CRCW06036M49FKEA, CRCW060311M0FKEA | 0603 | | - |
| R117, R118, R260, R261 | 1 each | 20.0 k, 10.0 k, 10.0 k, 26.1 k 1 % | CRCW060320K0FKEA, CRCW060310K0FKEA (x2), CRCW060326K1FKEA | 0603 | | - |
| R141, R142, R143 | 1 each | 61.9 k, 1.00 k, 100 ohm 1 % | CRCW060361K9FKEA, CRCW06031K00FKEA, CRCW0603100RFKEA | 0603 | | - |
| R101, R105 | 1 + 1 | 8.06 k, 27.4 k 1 % | CRCW06038K06FKEA, CRCW060327K4FKEA | 0603 | | - |
| R106, R107, R120, R129, R140 | 5 | 10.0 kOhm 1 % | CRCW060310K0FKEA | 0603 | | - |
| R108, R123, R124, R252, R254, R267-R271 | 10 | 47.0 kOhm 1 % | CRCW060347K0FKEA | 0603 | | - |
| R121, R122, R125-R128, R135, R147, R250, R251, R253, R266 | 12 | 1.00 kOhm 1 % | CRCW06031K00FKEA | 0603 | | - |
| R130, R131A, R131B, R132, R264, R265 | 6 | 100 ohm 1 % | CRCW0603100RFKEA | 0603 | | - |
| R133, R134, R136, R150, R151, R258 | 6 | 100 kOhm 1 % | CRCW0603100KFKEA | 0603 | | - |
| R119, R144, R262, R263 | 4 | 1.00 MOhm 1 % | CRCW06031M00FKEA | 0603 | | - |
| R259 | 1 | 10.0 MOhm 1 % | CRCW060310M0FKEA | 0603 | | - |
| R145, R146 | 2 | 2.70 kOhm 1 % | CRCW06032K70FKEA | 0603 | | - |
| R255, R257 | 1 + 1 | 48.7 k, 59.0 k 1 % | CRCW060348K7FKEA, CRCW060359K0FKEA | 0603 | | - |
| R137 | 1 | 0 ohm (FCI_OK link; omit if U117 fitted) | CRCW06030000Z0EA | 0603 | | - |
| EVM R23, R256, R272 | 1 + 1 + 1 | 49.9 k, 200 k, 47.0 k 1 % | CRCW060349K9FKEA, CRCW0603200KFKEA, CRCW060347K0FKEA | 0603 | | - |
| R_KA, U117 R160/R161 (DNP) | - | 680 ohm 0.25 W; REF divider for 130 mV | CRCW1206680RFKEA; values set if T-F-04b fails | 1206 / 0603 | | - |
| C109, C110-C123, C201-C205 | 20 (+5) | 100 nF 50 V X7R | Murata GRM188R71H104KA93D | 0603 | | - |
| C102 | 1 | 100 nF 50 V X7R | GRM188R71H104KA93D | 0603 | | - |
| C103 | 1 | 1.0 uF 50 V X7R | GRM21BR71H105KA12L | 0805 | | - |
| C125 | 1 | 10 uF 10 V X7R | GRM21BR71A106KE51L | 0805 | | - |
| C101 | 1 | 22 nF 50 V X7R | GRM188R71H223KA01D | 0603 | | - |
| C105, C140 | 2 | 10 nF 50 V X7R | GRM188R71H103KA01D | 0603 | | - |
| C106, C107 | 2 | 470 pF 50 V C0G | GRM1885C1H471JA01D | 0603 | | - |
| C108, C129 | 2 | 1.0 nF 50 V C0G | GRM1885C1H102JA01D | 0603 | | - |
| C252 (on EVM) | 1 | 2.2 nF 50 V C0G | GRM1885C1H222JA01D | 0603 | | - |
| C150 | 1 | 3.3 uF 16 V X7R (timing; DC bias at 3.3 V small) | GRM21BR71C335KA73L | 0805 | | - |
| C151 | 1 | 330 nF 16 V X7R | GRM188R71C334KA01D | 0603 | | - |
| C152 (DNP) | 1 | 2.2 nF (U112 CT) | GRM1885C1H222JA01D | 0603 | | - |
| C (MB) | 2 (+2) | 10 uF 35 V X5R | GRM21BR6YA106KE43L | 0805 | | USD 0.5 |
| C (EVM) | 5 (+3) | 10 uF 35 V X5R | GRM21BR6YA106KE43L | 0805 | | USD 0.5 |
| CR PCB | 5 | 31.0 x 33.0 mm, 2-layer, 1.6 mm, 2 oz, ENIG | from PM0 Gerbers | - | any PCB service | allowance USD 40 |
| EIB PCB | 5 | 30 x 22 mm, 2-layer, 1 oz, ENIG | from PM0 Gerbers (same panel) | - | any PCB service | (in CR panel) |
| J101, J201 | 2 (+1) | 2x7 shrouded header 2.54 mm | 3M N2514-6002-RB | TH | distributor | - |
| W5 | 1 (+1) | 14-way IDC sockets + 28 AWG 1.27 mm ribbon | 3M 89114-0101 (x2) + 3M 3365/14 | - | distributor | - |
| W7 mate | 1 | Molex KK 254 4-pos housing + crimps | 22-01-3047 + 08-50-0114 (crimp range checked vs 28 AWG, T-A-05) | - | distributor | - |
| Tap pins | 20 (+10) | single 0.64 mm male header pin, wire soldered, heat-shrink | Samtec TSW-101-07-G-S | TH | distributor | - |
| CHG header pins | 22 + spacer | 0.64 mm square pins, 2.54 mm plastic spacer | Samtec TSW-111-07-G-D (cut to the two 11-pin rows) | TH | distributor | - |
| Wire | 1 m each | 20 AWG red/black, 18 AWG red/black (PTFE/silicone), 26 AWG, 28 AWG Kynar, 4-way 28 AWG | - | - | - | - |
| Hardware | - | M3 x 10 mm nylon standoffs x 6 (+ screws), ferrules 0.5/0.75 mm², heat-shrink, Kapton, cable ties | - | - | - | - |

**Cost:** EVMs USD 312.90 (2 x 156.45, verified TI store price). Carrier, EIB, parts, wire and hardware: budget allowance
USD 90-120 (not verified). **Total about USD 405-435.** The study's parallel BQ25773EVM hedge (USD 199.00) is outside this
design and stays a study recommendation.

## F. Operating modes, transitions, R6/R7 design

### F.1 Images (registers, G.1) and symbols

- **Regen image:** VINDPM 19.0 V, IINDPM 1.70 A (clamped by the pin to 1.33-1.76 A), **ICHG 3.10 A** (conditional on T-E-11
  and T-B-19; 2.50 A until then, with the H.7 margin stated for both), EN_CHG 1.
- **Raised image (inside an FC window, T3):** IINDPM 1.70 A, ICHG 3.10 A, VINDPM_STAGE1 **18.2 V**, ratcheted to 19.0 V once
  V-MOT is above it (T3).
- **FC image:** VINDPM 14.5 V, IINDPM = governor value <= 0.90 A, ICHG 1.60 A, EN_CHG 1.
- Switch vector: FC_REG, BT_REG, FC_BUS, BT_BUS, MOT_PWR, REGEN, FC_CHARGE, BT_SEQ.
- Hardware qualifiers present in every armed row: ARM_OK (heartbeat), FCI_OK (= 1 unless U117 is fitted).

### F.2 Mode table

| Mode | Switches | P5 / QUAL / FCCEIL | Image | GATE in hardware | Ceiling | Loop impossible because | Runaway bounded by |
|---|---|---|---|---|---|---|---|
| Init (State 0) | staged bring-up; REGEN 0, FCC 0 | 0/0/0 | none (charger unpowered) | 0 | - | no charger input power (D-BC-RG, D-BC-FC off) | - |
| Idle (State 1) | 1 1 1 1 1 0 0 1 | 0/0/0; HB stopped | none | 0 | - | no input power | - |
| Run entry (qualification) | 1 1 1 1 1 **1** 0 1 | 0 / **one-shot** / 0; HB running | EN_CHG 0 and REG11 0 written and read back **before** QUAL; then static image | 0; ILIM released by QQ only for tw (0.30-0.40 s) | regen clamp read by the IC | **two barriers:** /CE HIGH (P5 LOW, and P5 AND ARM_OK) **and** EN_CHG = 0 (SLUSDV2C §7.3.9.1 needs both /CE LOW and EN_CHG 1); the window ends in hardware | input = IQ_VBUS 3-5 mA |
| **Run cruise, regen armed** | 1 1 1 1 1 1 0 1 | 1/0/0 | regen | H1q = 0 -> ILIM held | - | H1 = 0 holds ILIM_HIZ (hard converter-off, two switches); VINDPM 18.62-19.38 V soft layer above the 16.39 V bus maximum | converter off |
| **Regen burst** | as cruise | 1/0/0 | regen | H1q = 1 (needs H1, RGN, NOT FCC, UVB) | 1.33-1.76 A; ICHG 3.10 A | D-MT-EN reverse-biased while V-MOT > VBUS (RT1987 §17.6); H1 releases only then | self-limited by regen; clamp; IBUS_OCP |
| Run cruise, battery-only selection | 1 1 0 1 1 1 0 1 | 1/0/0 | regen | H1q | - | H1 | as above |
| Run cruise, FC-only selection outside a window | 1 1 1 0 1 1 0 1 | 1/0/0 | regen | H1q | - | no BT on the bus | as above |
| **FC window (R6), concurrent-ready (R7)** | 1 1 1 **0** 1 **1** **1** 1 | 1/0/**1** | FC | H2c = 1 | FC: 0.90 A register (0.65-0.95 A pin clamp if re-read) | BT_BUS EN LOW: D-BT-EN "completely isolates VIN and VOUT when disabled" (RT1987 §17 p.14); H2c needs BTB_OFF (EN < 0.44 V) and BT_OK (I_BT < 0.06-0.34 A); I-9 forbids FCC with BTB | IINDPM 0.90 A; UVB; firmware raw I_fc > 1.20 A arm drop; OC_FC 1.4 A |
| Brake in FC window, V-MOT below H1 rise | as FC window | 1/0/1 | FC | H2c = 1 | 0.90 A from V-MOT | as FC window | as FC window; the FC stops feeding (F.3) |
| **Brake in FC window, H1 = 1 (raised)** | as FC window | 1/0/**0** | **raised** (written within 1.5 ms, T3) | H2c = 1 via H1 (UVB not needed) | 1.33-1.76 A | as FC window; FC cannot feed while V-MOT > VBUS | regen self-limit; clamp |
| Raised, V-MOT falls back (H1 -> 0) before restore | as FC window | 1/0/0 | raised | **blank: H2c = 0** | - | as FC window | converter off until FC image restored (FCCEIL 1) |
| Purge pre-emption (F.4) | FC window -> regen armed | 1 -> 0 / 0 / 1 -> 0 (raised variant: P5 stays 1) | FC -> regen | **FCC LOW forces H2c = 0 at once**; GATE = H1q | - | FCC drops before BT_BUS rises (I-9); BT_BUS closes only after VINDPM 19.0 V is read back (I-2) | - |
| Finish (State 3) | -> Idle vector | 0/0/0 | EN_CHG 0 written | 0 | - | P5 LOW first, then FCC LOW, then BT_BUS, then REGEN LOW (T6) | - |
| State 98 | operator keys through the gated sequencer | via sequencer | per test | hardware | per mode | H1q/H2c and ARM_OK act regardless of keys; raw pin-5 key removed | as above |
| State 99 | phased teardown | **0/0/0 in phase 0, HB stopped** | EN_CHG 0 (best effort) | 0 | - | all charger paths opened after the inhibit | - |
| Teensy reset | all EN LOW (10 kOhm pull-downs) | LOW (pull-downs); no HB | - | 0 | - | no input power | - |
| **Teensy hang** | frozen | frozen; **no HB edges** | frozen | **ARM_OK = 0 within 30-40 ms**: ILIM held, /CE HIGH | - | MCU-independent: monostable + H1q/H2c | charging and switching stop in every mode. Residual: BT_BUS stays as it was; in an FC window the FC carries aux + traction through the next purge (UVB/VINDPM shed nothing more because the charger is already off); the bus minimum at that purge is the R5 exposure (T-D-02) |
| I2C dead | any | QUAL never raised (no ACK) or dropped on the first NACK after an ACK; firmware holds P5 0 | unknown | hardware | - | **QUAL dropped at the 100 ms ACK timeout; the hardware one-shot ends QQ within tw in any case; thereafter ILIM_REL = GATE; /CE HIGH** | no charge |
| Teensy hang inside QUAL | frozen, QUAL HIGH | frozen | POR or partial image | QQ ends after tw (no new edge); ARM_OK falls in 30-40 ms anyway | - | /CE HIGH (P5 LOW, ARM_OK 0) and ILIM held after <= 40 ms | no charge |
| Charger POR (input dip) | any | P5 dropped by firmware at the next poll (<= 20 ms; the charger cannot switch for >= 180 ms after POR, SLUSDV2C §7.3.4 steps 5-8) | defaults: VINDPM = VBUS0 - 1.4 V | hardware | the pin is read at POR: regen-armed cruise has ILIM_HIZ held, so the clamp latches at **100 mA** (< 1.08 V, §7.3.4.3; harvest lost, safe); FC window: FC clamp (FCC 1, H1 0, Q202 on, GATE 1) | regen-armed: H1q; FC window: H2c | FC window: 0.65-0.95 A without relying on ICHG. Firmware sees REG19 below the regen band, sets **harvest-lost / regen-reduced** (telemetry), and re-qualifies at the next safe point (FR-30) |

### F.3 R7: concurrency, RT1987 ORing and the loop proof

**What the RT1987 datasheet says (DS-00 §17.6 p.16, EC p.7):** an enabled RT1987 regulates VIN - VOUT = VFWD (35 mV typ) while
I x RON < VFWD; "if VIN decreases (or VOUT increases) such that VIN - VOUT falls to less than VFWD, the ideal diode gate drive
will force the internal MOSFET off"; a fast comparator trips within tFRC (0.5 us typ) at VIN - VOUT < VFRC (-50 mV typ). All
three figures are typical only.

D-BC-FC (VIN = VBUS) and D-BC-RG (VIN = V-MOT) both drive VCHG-IN. In an FC window with MOT_PWR closed, D-MT-EN also feeds V-MOT
from VBUS, so the FC reaches the charger by two paths. When regen lifts V-MOT above VBUS:
1. D-MT-EN sees VIN - VOUT < 0 and blocks VBUS -> V-MOT;
2. VCHG-IN follows V-MOT (less the D-BC-RG drop); once VCHG-IN > VBUS - 35 mV, D-BC-FC's gate is forced off, and at -50 mV the
   fast comparator turns it off within about 0.5 us;
3. from then on the charger draws only from V-MOT, i.e. from the motor.

**The operator's understanding is correct**, with two qualifications: the cut-off happens within tens of mV of VBUS, not at a
margin, and every figure is typical only. T-B-12 measures the FC current into the charger as a function of V-MOT - VBUS.

**Consequence: the FC-window ceiling must rise during strong braking.** The FC image cannot balance the 3 -> 1 m/s, 12 A brake
(18.9 W peak): its input limit is 11.2 W and its ICHG limit 12.0 W worst case (H.7), so V-MOT would climb to the VESC cut
(21.35 V). The 2 -> 1 m/s brake (11.1 W) is marginal on the FC image (+0.8 %). So **H1 and the T3 raise cover both brakes:**
when H1 is HIGH with the FC image active, firmware writes the raised image (FCCEIL LOW first, from the pin-34 interrupt). With a
1.5 ms worst-case latency (FR-07), V-MOT rises at most to 18.5 V at 0.4 mF before the raise (18.0 V at 0.97 mF); the 3 ms
r0 budget would give 19.75 V. Once raised, VINDPM holds V-MOT at 18.2 V (stage 1) and then 19.0 V, and the input capability
(20.8 W stage 1, 21.8 W at 19.0 V, H.7) covers 18.9 W.

**The unload transient of the raise (T-B-12):** VINDPM written above the present V-MOT makes the charger cut its draw while its
VINDPM loop settles, so V-MOT climbs at the full regen current (2.6 V/ms at 0.4 mF). The r0 single block (VINDPM 19.0 V before
IINDPM) left 1.97 V = 0.74 ms of headroom for the loop to reload; the staged r1 raise (IINDPM, ICHG, then VINDPM 18.2 V, whose
-2 % minimum clears the H1 fall maximum 17.76 V so H1 never drops while holding) leaves 2.79 V = 1.06 ms at 0.4 mF and 2.58 ms
at 0.97 mF. The BQ25798 VINDPM loop response is not specified; T-B-12 measures the V-MOT peak with a current source into
0.4/0.97 mF, and T-B-10's limit is tightened to the derived 1 ms.

**Why the raised ceiling cannot load the FC:** it is applied only while H1 = 1, i.e. V-MOT > 1.089 x VBUS, where D-BC-FC and
D-MT-EN are reverse-biased. If V-MOT falls back (H1 -> 0) before firmware restores the FC image, the blank (`(UVB AND FCCEIL)
OR H1` = 0) stops the converter in hardware. The normal end of a burst is slow: VINDPM holds V-MOT while regen fades, then V-MOT
decays at 14-20 V/s (VESC housekeeping, regen_dynamics §1.1). The only fast case is an abrupt VESC stop with the raised image
active: V-MOT falls at up to 4.4 V/ms (1.76 A into 0.4 mF), H1 falls, the blank removes the converter within the inhibit
latency, and the FC carries at most one pulse of <= 1.76 A for that latency (H.13 allowance 157-173 us at 1.80 A before
D-MT-EN conducts; T-B-06 measures the latency). A pulse that coincides with a 1 kHz OC_FC sample can latch OC_FC: a nuisance
State 99, safe (J.2 item 5).

**Loop impossibility in the concurrent mode (proof).** A circular charging loop needs pack energy to reach the charger input.
From the `.sch` net list, the pack (VBT) connects to: REG-BT/L-BT/SNS-BT (-> VOUT-BT -> SNS-BT -> VBUS-BT -> **D-BT-EN** -> VBUS),
the LM1084 (-> 5 V logic only), BAL BQ29200 (cell taps only) and D-BT-SQ (VCHG -> VBT only, TRCB blocks VBT -> VCHG). The only
pack -> VBUS element is therefore D-BT-EN, including the TPS61288 body-diode passthrough, which also flows through SNS-BT and
D-BT-EN. In the concurrent mode BT_BUS is LOW, and a disabled RT1987 "completely isolates VIN and VOUT" (DS-00 §17 p.14). The
charger input energy is then FC energy (VBUS via D-BC-FC, or VBUS -> D-MT-EN -> V-MOT -> D-BC-RG) or motor energy (V-MOT via
D-BC-RG); neither contains pack energy, so no loop exists whatever REGEN, FCC, H1 or the registers do. Hardware enforcement:
H2c needs **BTB_OFF** (the D-BT-EN EN net below 0.39-0.44 V, under the RT1987's own VEN_F minimum 0.6 V, so no EN level that can
leave D-BT-EN conducting reads as off) **and** BT_OK (measured BT boost current < 0.06-0.34 A). Firmware enforcement: I-9 (the
FCC and BTB EN nets are never HIGH together; the BT_BUS setter refuses while FCC is HIGH and the FCC setter refuses while BTB is
HIGH), backed by the existing single-sample `FAULT_SWITCH_CONFLICT`. **Residual (R8, accepted):** a shorted D-BT-EN passing less
than the BT_OK threshold (and less than the firmware floor + margin trip, about 0.12 A) sustains a loop bounded by that current
for the window duration. During a brake in the window the FC path is reverse-biased, so a shorted D-BT-EN cannot feed the
charger through D-BC-FC while V-MOT > VBUS; the C7 qualifier (`NOT FCC` in H1q) keeps H1 from bypassing H2c.

**Single-fault table, additions for round 3** (round-2 study §2.7 rows still apply; EIB-side faults in B.6):

| Fault | Outcome |
|---|---|
| FCCEIL stuck HIGH (firmware bug) while the raised image is active | H2c ignores H1; at H1 fall the converter keeps the regen clamp from the FC bus: <= 1.76 A + aux. Firmware cross-check (FR-09) compares the IINDPM readback with FCCEIL every poll and trips; OC_FC latches at 1.4 A. Bounded, no loop (BT_BUS LOW) |
| FCCEIL stuck LOW | Converter blanked whenever H1 = 0 in a window: FC charging lost, regen still absorbed. Safe |
| UVB stuck HIGH | No fast load shed on bus sag; VINDPM 14.5 V still sheds (loop speed unknown); fw UV_BUS dwell. **Latent until a real sag:** FR-08d trips if V_bus (pin 26) < 13.1 V for > 1 ms with H2c rb HIGH in a window; bench T-C-03 / T-D-04. There is no UVB readback pin |
| UVB stuck LOW | No FC windows, no regen (H1q needs UVB): firmware sees H1 rb HIGH with the far-end ILIM sense held for > 1 s and flags it. Safe |
| T2 (VBUS tap) open | H1 forced HIGH; UVB LOW. Regen-armed: H1q = 0 (UVB), converter held. FC window: H2c = 1 through H1 with RFC_OFF = 1 (regen clamp), but the FC image register (0.90 A) bounds the draw; FR-08 H1 plausibility (H1 HIGH while calibrated V_rgn < V_bus) trips in <= 5 ms; OC_FC 1.4 A backstop. No loop (BT_BUS LOW) |
| Divider bottom open (R110, R112, R115) | Input clamped by D104-D106 below 7 V. R110 open: H1 stuck HIGH (as T2 open in a window, UVB valid: H1q = 1 in regen-armed with V-MOT = VBUS -> converter released with VINDPM 19.0 V above the bus: soft layer only); FR-08 H1 plausibility trips in <= 5 ms (T-D-04). R112 open: H1 stuck LOW (no regen, safe). R115 open: UVB stuck HIGH (row above) |
| BT_OK stuck HIGH | H2c relies on BTB_OFF alone; firmware I_BT trip (floor + margin) remains; FR-08c flags it whenever pin 41 reads > 0.40 A for 5 ms with BT_OK rb HIGH; R8 residual grows to the INA-trip level until then |
| BTB_OFF stuck HIGH (U115 output) | H2c relies on BT_OK and I-9; FR-08 checks BTB_OFF via H2c rb: H2c rb HIGH while BT_BUS is commanded HIGH -> trip |
| eFuse short (FET fails closed) | Loses the charger-short bound; RT1987s and firmware remain; detected only by a T-C-04-type test (J.2) |
| Heartbeat monostable stuck HIGH (U113) | Hang protection lost; R5 future watchdog only. Run-entry self-test (T1 step 8) catches it every Run entry |
| Teensy reset during a concurrent burst | REGEN/FCC/MOT_PWR EN pull-downs open all paths; V-MOT isolated with the VESC still braking, rises to the VESC OV cut, regen stops (as today's rig). Safe, harvest lost |

### F.4 R6: purge scheduler and pre-emption

**Prediction source.** The H-20 controller purges on its own timer. The 22 Pi bags show a period of **10.34 s**, a depth to
about 1.8-2.3 V and a duration of 100-140 ms (`docs/reviews/fw36_regen_2026-11-04/README.md` §2; 50 Hz data at low FC load, so
+-20 ms per edge). The brochure (`references/H20-Small-Stacks-Brochure.pdf`) gives no purge interval. Whether the interval
depends on stack load is unknown, and an FC window roughly doubles the stack power: T-E-01 measures >= 20 intervals at window
load. fw v30 already detects a purge-class dip on FC_VOLTAGE (pin 24) at 1 kHz (`docs/fw30_fc_purge_uv.md` §5). The scheduler
(FR-15):
1. timestamps each purge onset as the first 1 kHz sample with V_fc below `PURGE_DETECT_V` (6.0 V, between the loaded knee about
   7.8 V and the purge floor, TODO(calibrate: T-E-01)) after a fall of more than 1 V within 20 ms;
2. predicts the next onset as last onset + median of the last 5 intervals (per load bin if T-E-01 shows load dependence);
3. declares the schedule **locked** after 3 consecutive intervals within +-`PURGE_JITTER_MAX` (100 ms, TODO(calibrate: T-E-01))
   of their median, and unlocks on any interval outside it, a missed prediction, or a stack-load change of more than ~0.3 A
   (TODO(calibrate: T-E-01));
4. optionally uses the purge-valve tap (T-E-02) as the onset source instead of V_fc.

**Window rules.** A window opens only (a) with the schedule locked, (b) within 1 s after a purge has ended (V_fc back above
`V_FC_ARM_THRESH` 7.0 V for 200 ms), so the next purge is about 9-10 s away, (c) with the admission bound of FR-14 met (the
commanded motor current, bus-referred, plus aux plus IINDPM plus margin <= 1.30 A, and no pending v_setpoint increase), (d)
with no regen burst in progress, and (e) with T-E-12's readiness margin known. It closes at `t_pred - T_LEAD`, or earlier on
governor exit, a traction-demand increase (the setpoint hold of FR-14), operator, or Run exit. This replaces the fw v30 30 s
FC-only lockout for FC windows (which "in practice refuses charge windows outright" on a running stack, study §3.4); the
lockout stays in force for share-loop FC-only selections outside windows.

**Lead time (H.8):**

| Item | Allowance |
|---|---|
| Firmware tick + P5 LOW + FC_CHARGE/FCCEIL LOW (one tick) | 1.0 ms |
| VINDPM 19.0 V write + read-back (100 kHz worst) | 0.8 ms |
| Charger shed settle before BT_BUS (bus recovery) | 2.0 ms |
| RT1987 D-BT-EN tD_ON (8 ms typ, no max given) | 16.0 ms (2x) |
| Soft-start to the pre-biased bus (tON/0.8 at 16 V) | 1.4 ms |
| Readiness check (EN high, FCC read-back LOW, P5, optional VBUS-BT ADC) | 1.0 ms |
| Purge onset jitter (unmeasured; 3 x the 20 ms bag resolution) | 60.0 ms |
| Margin | 17.8 ms |
| **T_LEAD** | **100 ms** |

Window closed per cycle: 100 ms lead + 100-140 ms purge + 230 ms recovery and re-open = 430-470 ms of 10.34 s: **FC-charge duty
95.5-95.8 % of FC-window time**. T-E-01 replaces the jitter line by 3 sigma of the measured onset jitter; T-E-06 replaces the
tD_ON line (if tD_ON,max exceeds 16 ms, T_LEAD grows by the excess).

**What the BT_BUS close achieves before the purge (RT1987 two-state analysis).** With the charger shed, the FC-only bus rises
toward the FC boost's aux-load point, and D-BT-EN sees VIN - VOUT = V0_bt - V_bus. The only measured BT-node data is
bench-supply: dV0 = +0.05 V with the FC side high, envelope +-0.10 V (`controller_design/system_model.md`), so
VIN - VOUT ≈ -0.05 + 0.3 x 0.12 + 0.035 ≈ +0.02 V nominal and about -0.03 V at the envelope edge. Three cases:
- **VIN - VOUT < VFRC (-50 mV) at enable:** the RT1987 does not turn on (TRCB, DS-00 §17.4) and "auto-restarts without
  soft-start at fault removal" (Table 1); whether tD_ON repeats on that restart is not stated. Design rule: avoid it,
  V0_bt - V_bus(FC-only, aux, P5 LOW) >= -20 mV, measured in **T-E-12**; fallback: raise V0_bt by 0.1-0.2 V with the BT
  TPS61288 FB divider (inside the share loop's +-0.40 V dV0 budget, re-run CAL-1).
- **-50 mV to +35 mV:** enabled, soft-start completes, the gate servo holds the MOSFET off (VIN - VOUT < VFWD, §17.6). At the
  purge the bus falls and the servo opens the gate: the hand-off happens through the ideal-diode ORing, with no tD_ON. The servo
  response "accommodates relatively slow changes" and is unspecified: **T-E-06** measures the crossing-to-conduction delay
  (pass <= 0.5 ms, about 0.1-1.3 V of sag at 0.2-2.6 V/ms).
- **> +35 mV:** D-BT-EN conducts during its soft-start: an inrush pulse (H.6) of C_eff x 12 V/ms + I_load, clamped at ISCP
  8.5 A, for delta/12 V/ms (25 us at 0.3 V), which a 1 kHz OC_BT sample (3.0 A, single sample, ino 7430) can catch with a
  probability of roughly the pulse width per ms (2.5-4 % at 0.3 V).

**Lever for the inrush amplitude (operator ruling, open; T-F-08 decides whether it is needed):** (i) raise C-DC4 to 68 nF
(slew 0.95 V/ms, peak <= 0.96 A + load at 0.97 mF, no SCP; but tON 13.5 ms, so T_LEAD, `RT1987_T_D_ON_MS` and the
static_assert'ed blanking family must be re-derived and early-purge recovery becomes too slow); or (ii) give OC_BT a
persistence requirement (2 consecutive samples) only in a window from the BT_BUS EN edge + tD_ON,min to tD_ON,max + tON + 1 ms,
justified by the RT1987's own SCP covering a true short inside soft-start (§17.5). The same transient already exists on every
share-loop/selector BT re-entry; that class is equally unquantified today.

**Pre-emption sequence (canonical, loop-safe).** At `t_pred - T_LEAD`:

| # | Action | Effect / timing |
|---|---|---|
| 1 | P5 LOW | /CE HIGH (charge off) |
| 2 | FC_CHARGE LOW and FCCEIL LOW in the same tick | **FCC net LOW -> H2c = 0 in gate delays**; GATE = H1q; the up-to-0.90 A charger load leaves the FC-only bus; VCHG-IN stays warm through REGEN; I-7 holds before any value is raised |
| 3 | Write VINDPM 19.0 V and read it back (<= 0.8 ms) | **must precede step 5** (I-2). On NACK or read-back failure: still go on to step 5 (the purge has priority; P5 LOW and GATE = H1q hold), set `chg_flags.soft_layer_missing` and keep P5 LOW until a verified image is in place |
| 4 | Wait >= 2 ms after step 2 (bus recovery) | shrinks the BT close transient (H.6) |
| 5 | BT_BUS HIGH through the pre-emption path: bypasses `SHARE_SELECTOR_DWELL_MS` and every deferral except the rescue predicate (FR-26) | the BT_BUS setter refuses while FCC reads HIGH (I-9) |
| 6 | Readiness: EN HIGH for >= tD_ON,max (T-E-06) + tON + 5 ms; FCC read-back LOW; optional VBUS-BT - VBUS >= -20 mV | **no requirement that I_batt rises before the purge** (see the two-state analysis); if readiness is missed by `t_pred - 40 ms`, abandon windows until the next lock and ride the purge on the FC (FC_BUS is never opened by a pre-emption), log it |
| 7 | Write the rest of the regen image (IINDPM 1.70 A, ICHG 3.10 A), read back | regen harvest available during the purge |
| 8 | P5 HIGH (after the I-3 read-back) | regen armed through the purge |

At the purge onset FR-16 records: the delay from the V_fc onset (or V_bus < V0_bt - 35 mV) to I_batt > floor, the V_bus
minimum, and the margin from step 6 to the onset.

**Raised-burst variant** (FCCEIL LOW, raised image verified, H1 = 1 at `t_pred - T_LEAD`): skip steps 1 and 3 (P5 stays HIGH;
the raised image already has VINDPM >= 18.2 V, above the 16.39 V bus maximum); do step 2 (FCC LOW: GATE = H1q = H1 . RGN . UVB
keeps the converter absorbing on the raised image; loop-safe because BT_BUS is still LOW and H1 proves V-MOT > VBUS), then
steps 4-7. **This is the only exception to I-1** (P5 stays HIGH while FCC and BT_BUS change). If H1 falls during the variant,
GATE drops to 0 by itself. If UVB falls during the variant (an early purge in the same 10 ms), H1q drops and the converter is
cut mid-brake: V-MOT climbs to the VESC cut (safe; J.2 item 14).

Re-open after the purge: the T2 sequence (F.5), warm (VCHG-IN held by REGEN), 10-20 ms.

**If a purge arrives early** (FR-17; trigger: the V_fc onset, or an H2c readback fall while FCC, BTB, BT_OK rb, FCCEIL and H1 rb
are unchanged, which can only be UVB):
1. The bus sags. The charger's VINDPM (14.12-14.88 V) cuts its input as the bus passes 14.5 V (loop speed unspecified), and UVB
   cuts the converter in hardware at 12.91-13.80 V within about 10 us + the inhibit latency, unless H1 holds it on during a
   brake.
2. Firmware (1 kHz): P5 LOW; FC_CHARGE LOW and FCCEIL LOW (sheds the charger's load from the sagging bus); **no VINDPM write
   on this path** (I-2 exception: P5 LOW, GATE = H1q and I-3 cover it; the 19.0 V write follows immediately after step 3);
   then
3. BT_BUS HIGH **if `purgeRescueOk()`** (FR-26): `uvBusArmed` and BT_REG HIGH and no fault latched and V_bus >= max(12.0 V =
   LIMIT_V_BUS_MIN, V_BT_est - dV_SCP), where dV_SCP is the RT1987 SCP no-trip bound (60 % of the 250 us timer at ISCP 8.5 A):
   1.11 V at C_VMOT 0.97 mF, 2.56 V at 0.4 mF (H.6), re-derived once T-E-04 measures C_VMOT, and V_BT_est is the T-E-12
   value (16.0 V nominal). Below the floor the close is refused.
4. Outcomes, all recorded by T-F-07: **(a)** re-close and ride through; **(b)** refusal and ride through on the FC (the bus
   stays above 12.0 V); **(c)** UV_BUS dwell (20 ms below 12.0 V) -> State 99; **(d)** RT1987 SCP cut on the rescue close (a
   64 ms gap in I_batt), then (a) or (c). A rescue close in progress when the bus falls through 12 V races the 20 ms dwell.
   **Never a discharged-node hot-plug:** the rescue only closes a charged, sagging bus onto the regulating BT boost inside the
   RT1987's own SCP envelope.
5. The scheduler unlocks and needs 3 new intervals before the next window.

The firmware currently contradicts itself on whether closing onto a sagging node is dangerous (`busHotPlugUnsafe()` comment,
ino ~13035: root cause retired, "cheap defense"; fw v24 backoff comment, ino ~15380: "has already destroyed boosts"). FR-26 keeps
`busHotPlugUnsafe()` at every other call site and applies the rescue predicate only to the FR-15/FR-17 closes; resolving the
contradiction is an operator item (J.2 item 15).

### F.5 Transitions (ordered; invariants first)

Invariants:
- **I-1** P5 is LOW across every switch change that touches BT_BUS, REGEN or FCC. **Only exception:** the raised-burst
  pre-emption variant (P5 stays HIGH, FCC drops before BT_BUS closes, GATE = H1q proves V-MOT > VBUS).
- **I-2** VINDPM >= 18.2 V is written and read back before BT_BUS closes; a sub-bus VINDPM (14.5 V) is written only while
  BT_BUS is confirmed off (EN LOW, BTB_OFF via H2c precondition, I_BT at floor for 5 ms). REGEN may be HIGH (R7). **Exception:**
  T8 (early purge), where P5 LOW, GATE = H1q and I-3 cover it until the 19.0 V write that follows the close.
- **I-3** P5 rises only after a read-back of the full masked image and REG19 ICO_ILIM in the current charger power cycle.
- **I-4** No mode transition starts while H1 = 1, except the raise (T3) and the purge pre-emption (priority).
- **I-5** QUAL rises only with P5 LOW, after EN_CHG = 0 and REG11 = 0 are read back, and is LOW whenever P5 changes. Firmware
  drops it on any NACK after the first ACK, any read-back mismatch, no ACK within 100 ms of REGEN closing, PG_STAT = 1 + 50 ms,
  or 400 ms after REGEN closes, whichever is first (TODO(calibrate: T-B-20)). The hardware one-shot ends QQ after 0.30-0.40 s
  in any case.
- **I-6** Poor-source recovery: PG_STAT still 0 300 ms after REGEN closes, or POORSRC_FLAG -> keep P5 LOW, force a retry
  (EN_HIZ 1 -> 0), harvest-lost flag (SLUSDV2C §7.3.4.2 p.27: otherwise retry every 7 minutes).
- **I-7** FCCEIL is HIGH only while the IINDPM and ICHG read-backs equal the FC-image values; it is driven LOW **before** any
  write that raises them.
- **I-8** No FC window opens unless the purge schedule is locked and the window ends at least T_LEAD before the predicted onset.
- **I-9 (new)** The FC_CHARGE and BT_BUS EN nets are never HIGH at the same time: the BT_BUS setter refuses while FCC is HIGH,
  the FCC setter refuses while BT_BUS is HIGH; the single-sample `FAULT_SWITCH_CONFLICT` (ino 7413-7418) stays as the backstop.

| ID | Transition | Steps | Budget |
|---|---|---|---|
| T1 | **Idle -> Run (regen armed)** | 0) MOT_PWR 1, V-MOT charged, H1 rb 0, boot self-test passed (FR-12); HB running. 1) P5 0, FCCEIL 0, QUAL 0. 2) REGEN 1: D-BC-RG tD_ON 8 ms + ramp in ~1.3 ms; eFuse UVLO at ~9.9 V, +1.83 ms delay, 7.3 ms ramp: EVM VBUS valid at ~18 ms. 3) Poll for ACK from +20 ms (SLUSDV2C §7.3.4 step 4); no ACK by +100 ms -> REGEN 0, retry later. 4) On the first ACK: write **REG0F = 0x02 (EN_CHG 0) first**, then REG11 = 0x00; read both back. 5) Check /CE sense HIGH with P5 LOW for 2 ms (FR-08); then QUAL 0 -> 1 (one-shot). 6) Wait PG_STAT = 1 (I-6); QUAL 0 at PG_STAT + 50 ms (I-5). 7) Poll REG05 until the auto VINDPM is stable 2 x 20 ms; write REG10 (WD 0.5 s), the static image and the regen image with EN_CHG still 0; verify image + REG19 in [1.30, 1.80] A. 8) Heartbeat self-test with EN_CHG 0: P5 1 -> /CE sense LOW within 1 ms; pause HB for 2 x tw,max -> /CE sense HIGH and ILIM sense held; resume HB. 9) Write REG0F = 0x22 (EN_CHG 1), read back; P5 stays 1 | arm ~0.35-0.45 s after REGEN; +0.5-2 s if the REG11 write misses the D+/D- window |
| T2 | **Regen armed -> FC window** | 0) I-8 and FR-14 admission OK, H1 rb 0 (defer <= 1 s). 1) P5 0. 2) BT_BUS 0 through the charge-window latch (FR-06; the latch owns BT_BUS for the whole window and the selector's gate release is suppressed); wait for the RT1987 turn-off (T-E-06) and I_BT at floor for 5 ms. 3) Write FC image: IINDPM, ICHG, then VINDPM 14.5 V last; read back. 4) FCCEIL 1. 5) FC_CHARGE 1 (warm: VCHG-IN already at V-MOT ~ VBUS - 35 mV; tD_ON 8 ms; the setter refuses while BTB is HIGH). 6) P5 1: H2c -> converter on | 10-20 ms + turn-off verification |
| T3 | **Raise (level-sensitive)**: FC image active (FCCEIL HIGH) **and** H1 rb HIGH, from the pin-34 rising-edge interrupt or the first 1 kHz tick that sees the state | 1) ISR: FCCEIL 0 (H1 = 1, so no blank) and post the raise. 2) Write REG06-07 IINDPM 1.70 A. 3) Write REG03-05: ICHG 3.10 A, VINDPM 18.2 V; read back. 4) Ratchet VINDPM to 19.0 V only when calibrated V_rgn > 19.0 x 1.02 + 0.19 V. No hold-off (FR-24 deleted). **False-restore guard:** V_rgn > 19.57 V with the FC image and H1 = 1 -> forced raise + fault key | edge to write complete <= 1.5 ms (FR-07): 0.5 ms at 400 kHz, 1.35 ms at 100 kHz with the 0.5 ms transaction cap |
| T4 | **Restore (burst over inside a window)** | Trigger: (a) H1 rb = 0 (the blank already holds the converter off), or (b) IBUS ADC < 0.1 A **and** VINDPM_STAT = 0 **and** IINDPM_STAT = 0 **and** calibrated V_rgn < 18.2 V, for 2 consecutive fresh IBUS conversions (40-170 ms with the slot-10 channel mask, G.1). Never on V_rgn alone. No T4 within 50 ms of a T3. 1) Write IINDPM (governor) and ICHG 1.60 A, read back. 2) FCCEIL 1. 3) Write VINDPM 14.5 V, read back | ~3 ms; if H1 fell first the blank holds the converter off meanwhile |
| T5 | **FC window -> regen armed** (purge pre-emption, governor exit, traction demand, operator) | F.4 canonical steps 1-8, or the raised-burst variant | time-critical part ~4 ms + RT1987 8-16 ms; the selector dwell is bypassed (FR-15) |
| T6 | **Run exit / Finish** | 1) P5 0. 2) If in a window: FC_CHARGE 0 + FCCEIL 0, VINDPM 19.0 V read back, >= 2 ms, BT_BUS 1 through the guarded path. 3) EN_CHG 0 write. 4) REGEN 0 (keep-alive, if fitted, follows). 5) QUAL 0; HB stopped last | - |
| T7 | **State 99** | phase 0: P5 0, QUAL 0, FCCEIL 0, HB stopped (hardware then holds) before any switch moves; then the existing teardown; delete the fw v37 "drain VBUS / V-MOT into the charger" phases and the REGEN-HIGH-with-MOT_PWR-LOW pattern (study §2.8) | - |
| T8 | **Early purge** | F.4 "If a purge arrives early" | - |
| T9 | **Re-qualify after a POR clamp latch** (FR-30) | At the next point with no burst and no window: P5 0, FCC LOW, QUAL edge (T1 steps 4-9) if T-B-07 shows an EN_HIZ toggle re-reads the pin; otherwise at the next Idle -> Run | - |

## G. Registers and firmware requirements

### G.1 BQ25798 register map in use (I2C 0x6B, 400 kHz with the R145/R146 pull-ups, 100 kHz fallback; SLUSDV2C §7.3.14 p.53, register tables §7.5)

Byte order of 16-bit fields: bits 15:8 at the lower offset (Fig 7-27 p.60). Self-check at the first read: REG01:02 = 0x03 0x48
(840 x 10 mV = 8.40 V, the 2S POR value).

**Never write:** REG0A (CELL; a CELL write resets VREG/ICHG/VSYSMIN to that cell count's defaults, §7.3.2 p.25), REG16
(VAC1_PD_EN would put a 60 ohm sink on VCHG-IN), REG09 bit 6 REG_RST (always 0), REG0B-REG0D and REG47 (OTG/backup).

**Static image** (written after every POR, i.e. at every Run entry without a keep-alive; verified continuously):

| Reg | Value | Decode | Reset by | Source |
|---|---|---|---|---|
| 0x0F | **0x02 first** (EN_CHG 0) at every POR; 0x22 armed | EN_AUTO_IBATDIS 0 (bit 7), EN_CHG (bit 5), EN_ICO 0, EN_HIZ 0, EN_TERM 1 (bit 1), EN_BACKUP 0 | EN_CHG by WD (Table 7-25; conflicts with REG09 STOP_WD_CHG, T-B-08) | Table 7-25 p.70 |
| 0x11 | **0x00** (before D+/D- starts) | AUTO_INDET_EN 0, FORCE_INDET 0, HVDCP off | WATCHDOG (-> 1) | Table 7-27 p.73; §7.3.4.5 |
| 0x10 | **0x81**; kick = 0x89 | VBUS_BACKUP 2h (unused), VAC_OVP 0h (26 V), WD_RST, WATCHDOG 1h = 0.5 s | REG_RST | Table 7-26 p.72 |
| 0x00 | 0x04 | VSYSMIN 3.5 V | REG_RST | Table 7-14 p.59 |
| 0x01:02 | 0x03 0x48 | VREG 8.400 V; verify <= 840 | REG_RST (WD per §7.3.2 text: benign) | Table 7-15 p.60 |
| 0x03:04 | mode | ICHG, 10 mA/LSB | WATCHDOG, REG_RST | Table 7-16 p.61 |
| 0x05 | mode | VINDPM, 100 mV/LSB | plug-in only (not REG_RST, not WD) | Table 7-17 p.62 |
| 0x06:07 | mode | IINDPM, 10 mA/LSB, clamped by the ILIM pin (EN_EXTILIM 1) | REG_RST, D+/D- | Table 7-18 p.63 |
| 0x08 | 0x03 | VBAT_LOWV 0h (15 % of VREG), IPRECHG 120 mA | REG_RST, WD | Table 7-19 p.64 |
| 0x09 | 0x25 | REG_RST 0, STOP_WD_CHG 1, ITERM 200 mA | WD (ITERM) | Table 7-20 p.65 (writability: T-B-08) |
| 0x0E | 0x3D | timers (POR) | WD, REG_RST | Table 7-24 p.69 |
| 0x12 | 0x04 | DIS_LDO 1 (bit 2), EN_OTG 0 | WD | Table 7-28 p.75 |
| 0x13 | 0x01 | ACDRV off, PWM_FREQ 0 (1.5 MHz), STAT enabled, EN_IBUS_OCP 1 | REG_RST, WD | Table 7-29 pp.76-77 |
| 0x14 | 0x16 | EN_IINDPM 1, **EN_EXTILIM 1** (read every pass) | EN_IINDPM by WD | Table 7-30 pp.78-79 |
| 0x15 | 0xAA | EN_MPPT 0 | REG_RST | Table 7-31 p.80 |
| 0x18 | 0x54 | TS active (TS_IGNORE 0); JEITA current settings at 100 % or TS fixed through JP18 (EM18) | WD | Table 7-34 p.83 |
| 0x2E-0x30 | **one-shot / off in regen-armed cruise**; continuous 13-bit only in bursts and windows | IBUS, IBAT, VBUS, VBAT, TS, TDIE | ADC_EN by WD | Tables 7-55..7-57; lowers the Run standby draw (H.15) |

**Mode images:**

| Field | Regen image | Raised image (T3) | FC image | Encoded |
|---|---|---|---|---|
| VINDPM REG05 | 19.0 V | 18.2 V -> 19.0 V (ratchet) | 14.5 V | 0xBE / 0xB6 / 0x91 |
| IINDPM REG06:07 | 1.70 A | 1.70 A | governor, <= 0.90 A | 0x00AA / 0x00AA / <= 0x005A |
| ICHG REG03:04 | **3.10 A** (2.50 A = 0x00FA until T-E-11/T-B-19 pass) | 3.10 A | 1.60 A | 0x0136 / 0x0136 / 0x00A0 |
| REG0F | 0x22 | 0x22 | 0x22 | - |

The FC IINDPM governor (FR-14): `min(0.90, 1.20 - I_aux,meas - I_trac,peak - I_ripple - margin)` A, rewritten at 50 Hz with
read-back, where I_trac,peak is a 2 s peak-hold of the 1 kHz traction current (bus side) and I_ripple the measured once-per-rev
allowance (T-F-04b sets it and the margin); the window closes below 0.30 A (study §3.4). I_aux,meas is the FC bus-side current
at window entry minus the charger IBUS ADC reading.

**I2C engine and poll schedule** (FR-07): one interrupt-driven LPI2C engine owns the bus; no blocking `Wire` call anywhere. 20 ms
frame: slot 0 status REG1B-21; slot 5 critical verify REG00-0A (split into transactions of <= 0.35 ms at 400 kHz / 0.5 ms at
100 kHz); slot 10 ADC REG31-36 + REG41; slot 15 WD kick + extended verify in parts. A pending raise is inserted at the next
transaction boundary; a read in flight may be aborted (NACK + STOP) and retried, a write never is (16-bit fields REG03:04 and
REG06:07 must not be left half-written).

**POR / WD detection:** WD_STAT, any masked mismatch, VBUS_PRESENT or PG change, POORSRC_FLAG -> P5 LOW first, then REG0F =
0x02, rewrite, verify, re-arm through T1 steps 7-9 (or T2 step 3 onward in a window).

### G.2 Firmware requirements (not code edits; for the orchestrated firmware round)

| ID | Requirement |
|---|---|
| FR-01 | Pin map from the amended CSV (D.3); `CHG_ARM`, `CHG_QUAL`, `CHG_FCCEIL`, `CHG_HB` driven LOW early in `setup()`; readback pins (8, 16, 23, 33, 34, 35) `INPUT`; `CHARGER_STAT` `INPUT` (pull-up on CR). Pin 28 is never configured `INPUT_PULLUP` (host test) |
| FR-02 | Remove the Ag105 driver (`pollAg105()`, `initAg105Charger()`, `ag105IsReady()`, reg-0x02 ratchet, `N` key, GENSTAT latch, `AG105_ADDR`); `AG105_VBATN_ISOLATED` -> `CHG_RETURN_VERIFIED` |
| FR-03 | BQ25798 driver: static and mode images (G.1), masked verify, never-write list enforced in the write function, byte-order self-check, POR/WD re-image starting with REG0F = 0x02; ADC one-shot/off in regen-armed cruise |
| FR-04 | Mode manager `chargerModeTick()`: non-blocking step machine for T1-T9; invariants I-1..I-9 asserted; QUAL only after EN_CHG = 0 is read back; the QUAL exits of I-5 |
| FR-05 | `chargingControl()`: regen arming independent of `charge_goal`; FC windows only through the scheduler (FR-15) and the admission/governor (FR-14); `FC_CHARGE_ALLOWED` re-enabled only with the carrier present (FR-12) |
| FR-06 | `assertFcChargeEnable()` keeps the BT_BUS-off guard and **stops forcing REGEN LOW** (R7). **The charge-window latch owns BT_BUS for the whole window**: the fw v28 selector's gate release (0.25 A) is suppressed while the latch holds (the charger's ~0.9 A would otherwise push the filtered total over the gate and re-close BT_BUS); pre-emption and window close hand ownership back through T5/T6. I-9 enforced in both setters |
| FR-07 | **Raise latency (normative):** pin-34 rising-edge ISR drives FCCEIL LOW and posts the raise; one interrupt-driven LPI2C engine (single owner, no blocking `Wire`); longest transaction <= 0.35 ms at 400 kHz or 0.5 ms at 100 kHz; reads abortable at a byte boundary, writes never; the encoder EEPROM commit (`encDirCommitTick()`) deferred while FC_CHARGE and REGEN are both HIGH; edge to write complete <= 1.5 ms. TODO(verify: PJRC teensy4/eeprom.c) whether flash operations mask interrupts; if they do not, the deferral can be relaxed |
| FR-08 | **1 kHz interlock monitor, dangerous direction only (latching):** (a) ILIM sense (pin 33) HIGH while expected_max = 0 for > 2 ms, where expected_max = (H1 rb . RGN . /FCC) + (FCC . /BTB . BT_OK rb . (FCCEIL + H1 rb)) + QQ_est, all ANDed with HB running (UVB assumed 1, which only widens the expectation); (b) /CE sense (pin 8) LOW while P5 is LOW or HB is stopped, for > 1 ms; (c) H2c rb HIGH while its expected maximum is 0 for > 5 ms (this also catches BTB_OFF stuck HIGH); (d) H1 rb vs calibrated V_rgn/V_bus (H1 HIGH while V_rgn < 1.03 x V_bus, needs T-E-05); (a) and (b) evaluated only while the charger is powered (V_chg > 10.2 V for > 200 ms) -> trip latch, P5 LOW, REGEN LOW, FCC LOW. **Safe direction (readback LOW while expected HIGH):** non-latching window shed through the F.4 path, counted; "permit stuck LOW" fault only if it persists > 1 s with V_bus > 14.5 V |
| FR-08b | Slow backstop: STAT steady LOW > 600 ms (excludes the 1 Hz fault blink) while GATE expected 0 and QQ 0 -> trip (usable only if T-B-18 shows STAT goes HIGH with the pin forced below 0.75 V); CHG_IIN > 0.6 A (bottom of the specified IMON range) over 20 ms while GATE 0 -> trip; IBUS ADC > 0.10 A at the poll while GATE 0 -> trip |
| FR-08c | BT_OK cross-check: BT_OK rb HIGH while pin 41 reads > 0.40 A for 5 ms -> carrier-fault flag, FC windows refused |
| FR-08d | UVB plausibility: inside a window, V_bus (pin 26) < 13.1 V for > 1 ms with H2c rb HIGH -> trip (UVB stuck HIGH) |
| FR-09 | FCCEIL consistency: every poll, (IINDPM rb > FC value or ICHG rb > 1.60 A) with FCCEIL HIGH -> trip latch; FCCEIL never HIGH with REGEN low |
| FR-10 | I_BT trip: BT channel above the boot-measured floor + margin (about 0.12 A at the datasheet floor) for 20 ms while BT_BUS is commanded LOW -> trip (study §2.3) |
| FR-11 | FC-window power balance: CHG_IIN (pin 22) x V_chg plus modelled aux vs I_fc x V_bus; mismatch above the T-B-14 threshold (+-50 mA DC equivalent at the IMON point) for 100 ms -> trip; also cross-checks the BQ25798 IBUS ADC |
| FR-12 | Boot self-test (each boot, Idle): FCC = REGEN = 0 -> V_chg decays below 3 V within 2 s (shorted D-BC-FC/D-BC-RG); V_rgn does not track VBUS with MOT_PWR LOW (shorted D-MT-EN); H1 rb 0; BT_OK rb 1 with BT_BUS LOW and the INA253 BT floor stored; H2c rb 0; I2C to 0x6B NACK (charger unpowered). CHG_EFUSE_FLT is **not** checked while V_chg < 10.2 V (its state below the 4.5 V IN_SYS minimum is unspecified, T-C-04). Any failure -> carrier-absent flag, FC windows and regen arming refused. The heartbeat and far-end senses are self-tested at every Run entry (T1 steps 5 and 8), because they need REGN |
| FR-13 | Port the fw v37 rev 2 `J` guards: G1 (bench session) 1.0 A / 5 ms; G1-Run (an armed burst must not raise I_fc + I_batt by > 0.3 A over the pre-burst value); G2 with P_chg_in = CHG_IIN x V_chg; G3 = REG20/21 and timer faults; reboot-only trip latch; `FAULT_SWITCH_CONFLICT` in all builds: **FC_CHARGE + BT_BUS stays a latched conflict; only FC_CHARGE + REGEN becomes legal** (the term `digitalRead(BT_BUS_ENABLE) || digitalRead(REGEN_ENABLE)` at ino 7413-7418 becomes `digitalRead(BT_BUS_ENABLE)`) |
| FR-14 | **FC-window traction margin:** (a) admission: open or keep a window only while |I_cmd| x V_mot/V_bus / eta (duty proxy, TODO(calibrate)) + I_aux + IINDPM + margin <= 1.30 A and no v_setpoint increase is pending; (b) **setpoint hold upstream of the drive controller**: a v_setpoint increase that arrives in a window is held at the old value until T5 has closed the window and BT conduction is verified (the drive law and its gains are untouched, as with the drive-cycle profiles); (c) governor input = peak-hold traction + ripple allowance (G.1); (d) firmware raw I_fc > 1.20 A -> P5 LOW the same tick, which precedes the fw v28 selector's raw escape at `SHARE_GOV_I_FC_CEIL_A` 1.25 A (ino 3530); (e) if T-F-04b fails: fit U117 (hardware FC-current shed into H2c) or restrict windows to standstill/coast |
| FR-15 | Purge scheduler (F.4): onset detector, median interval (per load bin if needed), lock/unlock, window rules; replaces the 30 s FC-only lockout for FC windows only. **The pre-emption BT_BUS close bypasses `SHARE_SELECTOR_DWELL_MS` 250 ms (ino 3466) and any other deferral except FR-26 / `busHotPlugUnsafe()`**; at most one such commutation per purge period |
| FR-16 | Telemetry of the pre-emption margin per purge (readiness to onset), the hand-off delay (onset to I_batt > floor), the V_bus minimum, and every early purge |
| FR-17 | Early purge (T8): trigger on the V_fc onset or an H2c rb fall with FCC, BTB, BT_OK rb, FCCEIL and H1 rb unchanged; P5 LOW, FCC LOW + FCCEIL LOW, BT_BUS HIGH if FR-26; then VINDPM 19.0 V |
| FR-18 | State 98: remove raw `4`; new `J` = FC-window bench session (BT_BUS 0, REGEN 1 or 0, FCC 1) with G1-G3 and the trip latch; new `V` = image, readbacks (incl. far-end senses), REG19, ADC, CHG_IIN, scheduler state; `5` routed through T2 |
| FR-19 | State 99 per T7 |
| FR-20 | Telemetry v5 through the `protocol-bump` procedure with the Pi bridge in lockstep (study §5.3, plus: `chg_ctrl` bits ARM, HB, ILIM rb (far end), CE rb (far end), H1 rb, H2c rb, BT_OK rb, QUAL, FCCEIL, FC mode; `chg_flags` eFuse FLT, trip latch, WD seen, pre-emption active, raised image, schedule locked, **harvest-lost / clamp-latched**, soft-layer-missing, regen-reduced (CV derate); **`chg_src`** (regen / FC / both, from H1 rb during charge and FCC); `chg_iin_ma` uint16 from CHG_IIN; **early-purge and UVB-shed counters** (uint8 each); **time-to-next-purge** (uint16 ms) and **last pre-emption margin** (int16 ms); checksum span recomputed); BLG v10 by its own procedure |
| FR-21 | HIL plant: charger model with the regen/raised/FC images, the H1/H2c/UVB/blank logic, the heartbeat and one-shot, the scheduler and purge dips; EMS charge economics re-derived (study §5.5); the 42-60 mW Run standby draw in the energy statistics |
| FR-22 | Host-native tests for every invariant (including **FCC and BT_BUS never HIGH on the same tick on every T2/T5/T6/T8 path, and no ERR_SWITCH_CONFLICT on any of them**), the B.1 truth table and the two monostables (as a firmware model), the scheduler, the staged raise and FCCEIL, the restore triggers, the boot self-test, the never-write list, pin 28 never `INPUT_PULLUP`, and pin 34's IOMUX staying GPIO |
| FR-23 | `chargerHasPower()` becomes V_chg (pin 38, board side of the eFuse) > 10.2 V for > 1 ms **and then** CHG_EFUSE_FLT HIGH; I2C to 0x6B is attempted only then |
| FR-24 | (deleted in r1: the raise has no hold-off; the restore has the 50 ms hysteresis of T4) |
| FR-25 | **Regen derate near CV:** whenever the charger is in CV (CHG_STAT CV) or IBAT ADC is below the ICHG image by > 30 %, or V_BT exceeds the voltage at which ICHG_max x (1 - 6.5 %) x V / 0.93 falls below the expected brake power, lower the VESC regen current limit (or disarm regen in favour of the VESC-cut levers, T-E-03); `chg_flags.regen_reduced` |
| FR-26 | `purgeRescueOk()` (F.4): `uvBusArmed && BT_REG HIGH && !faultLatched && V_bus >= max(LIMIT_V_BUS_MIN, V_BT_est - dV_SCP(C_VMOT))`; used only by the FR-15 and FR-17 closes |
| FR-27 | Teensy loop-time budget while armed: no single `loop()` iteration > tw_min / 4 (7.5 ms with tw >= 30 ms; T-C-09 measures it); SD drain chunks stay <= 512 B; the EEPROM commit is deferred while P5 is HIGH |
| FR-28 | **Heartbeat:** toggle `CHG_HB` exactly once per `loop()`, after `detectFaults()` and the interlock monitor, never from an ISR or IntervalTimer; run it from T1 step 0 until T6/T7; stop it on the trip latch |
| FR-29 | Pin 34 (pad GPIO_B1_13, ALT0 = WDOG1_B) stays GPIO (ALT5); the R5 watchdog uses WDOG1_B on pin 20 only (AD_B1_10 ALT1); host test on the IOMUX setting |
| FR-30 | FC-window POR: on REG19 ICO_ILIM below the regen band, set `chg_flags.clamp_latched` and re-qualify through T9 |

### G.3 MCU hardware watchdog (R5, required future work)

Specification unchanged from the study §5.1 (RTWDOG 100 ms, WDOG1 1.0 s, feed once per `loop()` after `detectFaults()` and the
interlock monitor, ERR_MCU_WDT latched and acknowledged before Run). **WDOG1_B is routed only to pin 20 (AD_B1_10, ALT1); never
to pin 19 (SCL, AD_B1_00 ALT4) or pin 34 (B1_13 ALT0, now CHG_H1_RB, where it would drive against the U102 output)** (IMXRT1060RM
Rev 3 §11.6.104 and the AD_B1_00/AD_B1_10 mux tables). Pin 21 now carries CHG_HB, so the EWM_OUT_B option (AD_B1_11 = pin 21
ALT1) is given up. The hardware heartbeat (B.1) already inhibits charging on a hang; R5 is still required because a hang in an
FC window leaves BT_BUS open through the next purge, and because a hardware BT re-close on a hang without the hot-plug check
would break the Death-5 doctrine. **No unattended charger session until T-W-01 passes.**

## H. Quantitative checks (from `calc/r3_calc.py`, output in `calc/r3_calc_out.txt`)

| # | Check | Result | Verdict |
|---|---|---|---|
| H.1 | H1 guard over VBUS (fall trip min - VBUS), VBUS 15.2-19.5 V, shared-T2 network, both UVB states | 0.85-1.20 V; hysteresis 0.30 V; ratio 1.089 | pass; ripple limit T-E-07 |
| H.1 | H1 rise max vs regen VINDPM min | 18.05 V vs 18.62 V: 0.57 V | absorption never chatters H1 |
| H.1 | H1 fall max vs VINDPM_STAGE1 min | 17.76 V vs 17.84 V (18.2 V - 2 %) | the staged raise never drops H1 |
| H.1 | V-MOT ripple that would chatter H1 (0.25 V min hysteresis through the 23.5 us filter) | 0.39 V p-p at 8 kHz, 0.78 V at 20 kHz, 1.14 V at 30 kHz | T-E-07 |
| H.1 | Tap fault | tap shorted to GND: 2.2 mA through R170/R171 (48 mW); open divider bottom: input clamped by BAV199 (36 uA at 22 V) | pass |
| H.2 | UVB fall band vs FC VINDPM floor, incl. REF drift 0-45 C and CMRR | 12.91-13.80 V vs 14.12 V: 0.33 V (r0 basis gave 0.16 V without drift) | pass on paper; T-B-13, T-C-03 at 0/60 C |
| H.2 | UVB rise band vs loaded FC-only bus | <= 14.14 V vs >= 15.2 V assumed: 1.06 V | T-E-08 |
| H.3 | BT_OK trip (incl. REF drift) | 6.0-33.5 mV = 0.06-0.34 A (INA floor up to 0.1 A) | R8 residual; false-inhibit possible, safe (T-E-10) |
| H.3 | BTB_OFF threshold vs RT1987 VEN_F min | 0.39-0.44 V vs 0.6 V: 0.16 V; Teensy reset 64 mV, driven LOW 33 mV | pass |
| H.4 | ILIM clamps incl. +-1.5 uA pin leakage, 1 uA FET leakage, sense pull-up | regen 1.33-1.76 A (nominal 1.57 A); FC 0.65-0.95 A (nominal 0.80 A); held <= 0.11 V (<= 0.57 V with EVM R23 open) | pass |
| H.4 | ILIM sense threshold | 0.86-0.93 V, between held 0.11 V and released min 1.52 V | pass |
| H.5 | eFuse limit vs regen clamp max | 2.05-2.41 A vs 1.76 A: 0.30 A margin | pass |
| H.5 | eFuse UVLO / OVP | 9.70-10.13 V / **22.61-23.63 V**; design clamp 22.28 V (0.33 V below the band), BQ25798 recommended VBUS max 24 V (0.37 V above) | pass |
| H.5 | eFuse OUT turn-off spike | 0.15 uH lead: -1.9 V at 4.8 A and -7.7 V at 20 A with C103 alone; OUT abs min -0.3 V | **D103 required** (fitted); T-C-04 |
| H.5 | IMON scaling | 0.764 V/A (0.703-0.826); 1.31 V at 1.72 A; <= 1.99 V at I_OL; fast-trip transient passed to pin 22 <= 1.44 V | pass, no clamp diode |
| H.6 | Inrush, Run-entry REGEN close | 0.24 A (board 20 uF at 12 V/ms) + 0.11 A (EVM behind the eFuse dVdT) | pass (H8 1.0 A budget) |
| H.6 | Inrush, FC_CHARGE close in Run | warm, ~70 mV delta, ~5 uC | negligible |
| H.6 | **BT_BUS close onto an FC-only bus** (C_eff = 40 uF + C_VMOT 0.4-0.97 mF; 12 V/ms) | I_pk 5.4-6.3 A (0.4 mF) or 8.5 A clamped (0.97 mF), width delta/12 V/ms: 4-7 us at 0.05 V, 25-41 us at 0.3 V; SCP trip (64 ms retry) at >= 2.4 V delta with 0.97 mF; P(OC_BT sample in the pulse) ~ width per ms | **open: T-F-08 decides lever 3(i)/(ii)** |
| H.6 | SCP no-trip rescue bound | delta < 1.11 V (0.97 mF) / 2.56 V (0.4 mF) at 1 A load | FR-26 floor |
| H.6 | Lever 3(i) C-DC4 68 nF | slew 0.95 V/ms, peak 0.96 A + load, tON 13.5 ms | operator ruling |
| H.7 | **Absorption capability = min(input limit, ICHG limit)**, pack 7.40 V, eta_max 0.93, ICHG -6.5 % | regen image ICHG 2.50 A: 18.8 W (-0.5 % vs 18.9 W); **ICHG 3.10 A: 21.8 W (+15.4 %)**; raised stage 1: 20.8 W (+9.9 %); FC image: 11.2 W | pass at 3.10 A; T-B-19, T-E-11 |
| H.7 | ICHG needed | 2.51 A for 18.9 W; 3.05 A for the HR1 23 W condition | 3.10 A chosen |
| H.7 | 8.40 V pack, ICHG 3.10 A | demand 30.0 W = 1.61 A at 18.62 V: ILIM clamp binds (<= 1.76 A < eFuse 2.05 A) | pass |
| H.7 | CV taper near full | capability -> ~0 W | FR-25 derate |
| H.7 | 3 -> 1 m/s brake (18.9 W) on the static FC image | input-limited balance at 23.9 V; ICHG-limited 12.0 W | **raise required** |
| H.7 | V-MOT before the raise lands | 1.5 ms worst: 18.5 V (0.4 mF), 18.0 V (0.97 mF); 3 ms: 19.75 V | pass |
| H.7 | Unload headroom after the raise | staged (18.2 V): 2.79 V = 1.06 ms (0.4 mF) / 2.58 ms (0.97 mF); r0 unstaged 0.74 ms | T-B-12 |
| H.8 | Pre-emption lead and FC duty | T_LEAD 100 ms; duty 95.5-95.8 % of FC-window time | T-E-01, T-E-06 |
| H.8 | Hand-off sag | 0.2 V/ms (aux, MOT_PWR closed, ESTIMATE) to 2.57 V/ms (HIL 40 uF model): 0.5 ms costs 0.1-1.3 V | T-E-01, T-E-06 |
| H.9 | VCHG decay without keep-alive | below RT1987 UVLO in 0.17-0.66 s, below VBAT_SHORT in 0.20-0.78 s | keep-alive decision T-B-09 |
| H.10 | Keep-alive option | VCHG 3.63-4.46 V; 0.7-1.4 mA in Run only; 0 parked | fallback |
| H.11 | Leads | input pair 20 mOhm (36 mV, 65 mW at 1.80 A); battery pair 12.6 mOhm (39 mV, 121 mW at 3.10 A); eFuse 34-95 mV, 62-172 mW | pass |
| H.11 | CV at termination (0.2 A) | pack 8.341-8.417 V; 8.278-8.354 V at 3.10 A | below OV_BATT 8.5 V |
| H.12 | FC-window bus load (standstill) | FC image 0.99-1.05 A; after a charger POR in the window <= 1.10 A; if the FC image were lost 1.84-1.90 A | FCCEIL blank + FR-09 + OC_FC cover the last row |
| H.12 | Cruise headroom to OC_FC | governor holds total <= 1.10 A: 0.30 A for traction steps and ripple | FR-14; T-F-04b |
| H.13 | Inhibit-latency allowance (H1 fall -> D-MT-EN conduction; deductions 24 us divider RC, 15 us comparator, 7 us Q201 gate at 47 kOhm) | 360-392 us at 0.90 A; 246-269 us at 1.25 A; 157-173 us at 1.80 A | T-B-06 (<= 150 us covers all) |
| H.13 | Glitch immunity of the ILIM release path (two switches, C252 2.2 nF) | 0.1 us / 1 us release glitch lifts ILIM_HIZ to 0.28 / 0.32 V | below the 0.75 V HIZ threshold |
| H.14 | Thermal | BQ25798 0.93 W at 1.6 A FC (dT 41 C JEDEC); **2.58 W in 3.1 A regen bursts (dT 114 C JEDEC steady state)** <= 0.6 s; eFuse <= 0.17 W | bursts only; T-B-16 at 3.1 A (TREG fold-back would cut capability) |
| H.15 | **Run standby draw** (eFuse IQ, D-BC-RG IQ, CHG_VOLTAGE divider, UVLO string, BQ25798 converter-off ADC-off, D103 leakage) | 2.6-3.8 mA x 16 V = 42-60 mW for all of Run | energy statistics carry it (FR-21); T-B-04, T-A-07 |
| H.15 | 3V3 load of CR + EIB | <= 0.93 mA | < 2 mA budget |
| H.16 | I2C with R145/R146 2.7 kOhm (2.13 kOhm net) | Cb max 167 pF for 300 ns (Fm); estimate 75 pF -> tr 135 ns; sink 1.36 mA | 400 kHz, T-C-06 |
| H.16 | T3 raise transfer time | 0.21 ms at 400 kHz; 0.85 ms at 100 kHz | FR-07 |
| H.17 | Monostables | QUAL one-shot 0.30-0.40 s (R150 100 kOhm, C150 3.3 uF); heartbeat 30-40 ms (R151 100 kOhm, C151 330 nF); K at 100 kOhm from SCES586E Fig 5-6 | T-C-10, T-B-20 |
| - | Voltage ratings | VCHG-IN parts >= 35 V; eFuse 60 V; BQ25798 30 V abs max, VBUS_OVP >= 25.2 V; TLV3012 inputs clamped below 7 V; SN74LVC3G06 outputs <= 5.2 V (REGN) vs 5.5 V | pass |
| - | Regen threshold stack (VBUS steady max 16.39 V < H1 fall min 17.34 V < H1 rise max 18.05 V < VINDPM min 18.62 V < VINDPM max 19.38 V < VESC cut 21.35 V < clamp 21.98 V < eFuse OVP 22.61 V < BQ VBUS recommended max 24 V < BQ abs max 30 V) | monotone | pass |

## I. Uncertainty and test registry

Bench order: **T-A** parts and incoming checks, **T-B** EVM standalone, **T-C** carrier + EIB + bench Teensy on emulated
supplies, **T-D** bench failure injection, **T-E** measurements on the vehicle with the existing hardware (no new parts; may run
in parallel with T-A..T-D at any time, but listed here as board tests), **T-F** board integration, **T-G** regen and FC on the
road, **T-W** MCU watchdog. Equipment codes: PSU1 (>= 24 V 3 A, current-limited), PSU2 (second supply or electronic load with a
16 -> 21 V step < 1 ms, or a current-source mode), BATSIM (2S pack or 4-quadrant source), RT-SI (RT1987 stand-in: a spare RT1987
on perfboard with 5.6 nF CSS, or an MB channel), SCOPE (4 ch, >= 100 MHz), CP (current probe >= 20 A), DMM, LA (logic
analyser), LCR, HG (heat gun / thermal chamber), THERM (thermocouple).

| ID | Question | Why it matters | Test (equipment, setup, steps, measurement) | Pass / fail | If it fails |
|---|---|---|---|---|---|
| T-A-01 | MB J1/J2 positions used (J1.01/.19/.23/.29/.39/.43/.45, J2.07/.09/.11/.19/.21/.29/.31/.33/.43/.45/.47) and their nets; do they accept 0.64 mm pins; RENC1/RENC2 fitted values (4.7 or 2.2 kOhm); ROS state after the 2026-08-16 bodge; SNS-BT GND/REF1 pad or nearest via for T9 | Tap method; pin 8 readback level; Kelvin T9 | DMM continuity J1/J2 to Teensy pins with the Teensy removed; insert a pin; measure RENC1/2 in circuit; locate SNS-BT pin 'GND'/'REF1' copper | every position = the A.4 net; pins seat; RENC2 measured; T9 landing identified | Solder taps to the second position of each pair; re-map; if RENC2 > 4.7 kOhm keep T20 direct (no change) |
| T-A-02 | EVM as received: TP27/TP33/TP36/TP38/TP49 nets; JP12 REGN pin; the ILIM-side pins of JP14 and JP21; the /CE-side pin of JP17; R21/R23/R29 values; J8 pinout; corner-hole diameter; TP49-to-PGND resistance; final E1-E8 lengths | Mods land on the right nets; R23-open fault coverage | DMM: each point to IC pins per Fig 4-5/4-6; measure R21, R23 (stock and replacement) power off; M3 rod through a corner hole; ruler for E1-E8 | as Fig 4-5/4-6; new R23 49.9 kOhm +-1 %; holes pass M3; E-leads within A.5 | Recompute R255/R257 with `r3_calc.py`; M2.5 or adhesive standoffs; longer E-leads acceptable for E1/E5 (static) |
| T-A-03 | 2N7002K and BSS84: VGS(th), on-state at |VGS| 4.8 V, off-state drain leakage at 2-3 V (allowance 1 uA in H.4), turn-on/off through 47 kOhm (Ciss assumed 50 pF in H.13) | EIB Q201-Q203 hold-down and feed; leakage folded into the clamps | Curve tracer or PSU + 100 kOhm load: VDS vs VGS 0-5 V; nA-meter at VDS 3 V gate off; scope gate/drain on a populated EIB after the driver releases | 2N7002K ON (VDS < 50 mV at 50 uA) at 4.8 V, OFF (< 1 uA) at 0.5 V; BSS84 ON at VGS -4.8 V (VDS < 50 mV at 100 uA), OFF at 0 V (< 1 uA); gate recovery < 10 us | Another logic-level part with specified VGS(th) max <= 2.5 V and IDSS; recompute H.4/H.13 |
| T-A-04 | Effective capacitance of the 35 V 0805 replacements at 16-21 V | Inrush numbers (H.6), EVM input filter | LCR with DC bias at 0, 16, 21 V, or ramp current in T-F-03 | >= 3 uF each at 21 V | If lower: no inrush change (it falls); check EVM input ripple at 1.7 A (T-B-16); choose a 50 V 0805 if ripple > 200 mV p-p |
| T-A-05 | Procurement check of **every** BOM line (rating, tolerance, TCR, package, pinout, crimp range vs AWG, header-pin current rating >= 3 A for pad 10) | A wrong part silently breaks a margin | Read each manufacturer datasheet before ordering; tick each E row | every row matches its column | Pick an alternative that meets the column; no design change |
| T-A-06 | KiCad capture of CR and EIB matches B.8; hole pattern matches the MB; copper meets A.8 | Fabrication gate (PM0) | Netlist export diff against B.8; 1:1 print of the drill layer over the vacated CHG footprint (or the bare board); IPC-2152 check of the pour widths for 2.41 A | zero netlist differences; all 22 holes concentric within 0.2 mm; pours >= A.8 | Fix the capture; re-run |
| T-A-07 | Leakage of BAV199 (at 1-3 V reverse) and D103 (at 21 V reverse), 25 C and 60 C | Comparator trip shift (B.2); R9 energy budget (H.15) | nA-meter / SMU; HG | BAV199 < 50 nA at 60 C; D103 < 0.1 mA at 60 C | BAV199: lower-leakage pair (e.g. BAS416 class); D103: higher-voltage lower-leakage Schottky |
| T-B-01 | First power: does the EVM qualify with VAC_OVP at its POR value and VAC1/VAC2 tied to VBUS? Part, CELL, PWM_FREQ, as-booted ICHG; TP42 (PULLUP) dark | Run entry depends on first qualification | PSU1 via the eFuse board to J1 at 16 V then 21 V, BATSIM 7.6 V on J5; I2C from the bench Teensy: REG48, REG01:02, REG0A, REG13, REG03:04, REG1B-REG21; DMM TP42 | PG_STAT 1, VAC1 OVP flags 0, CELL 1h, 0x0348, PWM_FREQ 0; TP42 < 0.1 V | VAC_OVP needs a pre-power path: fit the keep-alive option; TP42 live: check JP30/U2 |
| T-B-02 | Can REG0F and REG11 be written between 20 ms and D+/D- start, and does REG11 = 0 skip detection? | Arm latency; QUAL order | Scope VBUS valid, LA on I2C; write REG0F then REG11 at ACK; measure PG to switching | detection skipped; both writes ACKed before PG_STAT | Accept 0.5-2 s arm latency; FC windows unaffected |
| T-B-03 | /CE and ILIM_HIZ levels via the EIB: every input state, 3V3 removed, REGN logged | Fail-safe | DMM/scope at TP36/TP33/JP21 with REGN up | /CE >= 3.0 V when not armed; Q201/Q202/Q203 gates >= 3.5 V from their pull-ups; ILIM <= 0.25 V held; 2.06-2.40 V released (regen), 1.52-1.76 V (FC); U203/U204 outputs follow | Fix EIB; re-run |
| T-B-04 | **Total VCHG-IN draw** at bus voltage (eFuse + BQ25798 + divider + D103), inhibited, released, ADC off / continuous | Run standby draw (H.15), R9 | PSU1 at 15.9 and 18.5 V into CR pad 10 with the CR and EVM fitted on a bench MB stand-in; ammeter in series; record mW at 16 V | inhibited <= 4 mA total (<= 1 mA BQ25798 share); released <= 6 mA; IBAT 0 +- 10 mA | Accept up to 10 mA with the energy statistics updated; else /CE-only cruise |
| T-B-05 | VINDPM retention over 1000 ILIM/CE cycles and a 12 V dip | Chosen-part reason 1 | Script via LA/Teensy | REG05 unchanged, PG kept, no EN_HIZ | Re-write VINDPM after every cycle (firmware) |
| T-B-06 | Inhibit latency: ILIM_HIZ LOW -> IBUS < 10 %; /CE HIGH -> IBUS < 10 % | Loop proof bound (H.13) and the FC pulse after the blank | PSU1 stiff 19.5 V, BATSIM 7.6 V, 1.25 and 1.76 A input; scope IBUS (CP) and the EIB input | ILIM path <= 150 us; both paths <= 1 ms | Bounded pulse per event; accept by ruling or lower the regen clamp (R255) |
| T-B-07 | Is ILIM_HIZ sampled once (POR) or continuously? Does an EN_HIZ 1 -> 0 toggle re-read it? IINDPM accuracy at 15.8 V and 19 V. **POR inside an FC window** (FCC 1, H1 0, Q202 on) | R_FC bound outside a POR; recovery from a POR clamp latch in Run (FR-30/T9) | Qualify with Q202 off, then switch Q202 while charging; qualify with ILIM held, then toggle EN_HIZ with it released; force a POR with Q202 on; read REG19, measure IBUS | Record behaviour; IINDPM within -12 %/+0 % | If once: FC bound = register + FCCEIL + FR-09 (designed); FC-window POR then costs regen until the next Idle (FR-30); if accuracy worse: rescale clamps |
| T-B-08 | Charger watchdog: STOP_WD_CHG writable; EN_CHG after expiry (Table 7-25 vs REG09 conflict); VREG/ICHG after expiry | Whether the charger WD can be cited at all | Charge at 1.6 A, stop kicking | stops in 0.4-1.0 s; EN_CHG reads 0 | Do not cite the charger WD (the heartbeat and R5 carry hangs) |
| T-B-09 | **Keep-alive decision (R9):** VCHG decay in HIZ with a real RT1987 at D-BT-SQ; restart time from HIZ release at VCHG 0 / 1 / 2.4 / 3.6 V; does the RT1987 repeat tD_ON on UVLO recovery with EN high? Does the BQ25798 run its 1.5 s trickle timer on HIZ exit below 2.25 V (SLUSDV2C §7.3.9.2)? BQ25798 BAT draw in HIZ | Regen capture in regen-armed cruise | PSU2 at 18.5 V stepping to 20 V at release, RT-SI from VCHG to BATSIM 7.8 V, scope VCHG, pack current (CP), ILIM_HIZ; 10 s cruise state then release | **Pass (no keep-alive):** pack current >= 90 % of the ICHG-limited value within 4 ms of release from fully decayed VCHG | Fit the B.5 keep-alive; repeat: pass if VCHG >= 3.5 V throughout and the same 4 ms; if that fails, bridge D-BT-SQ (fallback 2) |
| T-B-10 | Warm response tau at the chosen keep-alive configuration; BATOVP triangle | Regen cliff (study §3.2) | PSU2 step 18.5 -> 20 V, and ramp 17.5 -> 20 V at 285 V/s from ILIM release; log BATOVP_FLAG, CHG_STAT | tau63 <= 1.0 ms at 0.4 mF (re-derived from T-E-04 as (21.35 - VINDPM_STAGE1 max) x C_VMOT / I_regen); no BATOVP cycling | VESC cut-off raise (study §3.2 levers) or FC windows restricted to gentle decels |
| T-B-11 | Poor-source recovery | Avoids the 7-minute retry | Series resistor so VBUS sags below VPOORSRC during qualification | POORSRC/EN_HIZ seen; firmware retry re-qualifies <= 1 s | Fix FR-04 |
| T-B-12 | **Concurrent mode and the raise on the bench:** FC current into the charger vs V-MOT - VBUS through two RT1987s; raise latency; blank; FC pulse; **unload transient of the staged raise** | R7 behaviour (F.3), H.7 headroom | PSU1 1.4 A-limited as "VBUS" via RT-SI #1 (D-BC-FC); RT-SI #2 + 0.4 mF (then 0.97 mF) as V-MOT fed by PSU2 as a ~1.1 A current source; charger running on the FC image with V-MOT at the H1 rise point; execute the real T3 and, as the control, the r0 single block | FC current < 10 mA once V-MOT > VBUS + 0.1 V; raise <= 1.5 ms; V-MOT peak <= 20.5 V for the staged T3; FC pulse <= 1.76 A for <= the T-B-06 latency on an abrupt PSU2 drop | Staged T3 > 20.5 V: windows only at standstill/gentle decels (2 -> 1 m/s needs no raise), or the VESC cut raise; raise > 1.5 ms: fix FR-07 |
| T-B-13 | VINDPM accuracy at 14.5 V, 18.2 V and 19.0 V | UVB margin 0.33 V; regen stack; stage 1 | PSU1 slow ramp down with a load on SYS/BAT; find the regulation point | 14.12-14.88 V; 17.84-18.56 V; 18.62-19.38 V | Move UVB lower (R115) or VINDPM_FC higher; recompute |
| T-B-14 | ADC accuracy (IBUS, IBAT, VBUS) and IMON accuracy, **incl. the IMON offset below 0.6 A at 25 C and 60 C** | FR-11 threshold, FR-08b, EMS accounting | DC and 50 ms pulses vs shunt/DMM, 0-2.4 A; HG on the CR | IBUS and IMON within +-50 mA DC over 0.3-1.8 A; zero-current offset < 10 mA at 60 C | Set FR-11's threshold from the data; widen it or disable the IMON term if > +-100 mA |
| T-B-15 | CV/termination through the RT1987 into the pack | Overcharge bound | Full charge into BATSIM via RT-SI | pack 8.27-8.42 V; EN_CHG cleared at CHG_STAT 7h | Lower VREG by 1 LSB |
| T-B-16 | Thermal | Off-board mount; 3.1 A bursts | 30 min 1.6 A FC + 5 min of 0.6 s 3.1 A bursts at 1 Hz duty 30 % | TDIE < 100 C, TREG_STAT 0 | Forced air / ICHG 2.5 A (accept the H.7 margin at 2.5 A only with FR-25 active) |
| T-B-17 | Does an unpowered BQ25798 clamp SDA/SCL? | I2C bus health in Idle | EVM unpowered, Teensy + CR pull-ups on: measure line HIGH and current | >= 3.0 V, < 50 uA | Series 100 ohm in W7 + firmware ignores NACK in Idle; or a bus switch |
| T-B-18 | STAT and CHG_STAT with the ILIM pin forced below 0.75 V (switching stopped, REGN on), vs EN_HIZ, vs VINDPM-limited at 0 A | Whether FR-08b's STAT term is usable | Force via Q201; read STAT pin and REG1C | Record; STAT HIGH when forced | Drop the STAT term from FR-08b |
| T-B-19 | **ICHG accuracy and efficiency at 2.5 / 3.1 A**, VBUS 18.6-19.4 V, VBAT 7.4 V and 8.2 V; CV case near 8.3 V | H.7 capability (eta_max 0.93 and -6.5 % assumed) | PSU1 19.0 V, BATSIM 7.40 V and 8.2 V, regen image; 2 s holds; power analyser in/out | P_in >= 20.8 W at 7.4 V with ICHG 3.10 A; REG19/IBAT consistent with ICHG | Record HR1 as unmet at low SoC; FR-25 limits brake current below the capability; never leave H.7 reading pass |
| T-B-20 | Instant of the ILIM ADC read (PG_STAT edge) after VBUS valid | QUAL one-shot length and the 400 ms firmware bound | Scope VBUS (EVM), PG via REG1B polling at 1 ms, ILIM_HIZ; release ILIM briefly at swept delays and read REG19 | read instant known +-10 ms; inside the one-shot | Change C150; adjust the I-5 bound |
| T-C-01 | Carrier truth table, monostables and power-up states (B.1, B.7), **incl. tap-open cases** | Hardware logic correctness | LA on all inputs/outputs; drive FCC/RGN/P5/QUAL/FCCEIL/HB from a bench Teensy, H1/UVB/BT_OK/BTB from supplies; all 2^9 combinational states with ARM_OK = 1, then ARM_OK = 0; QUAL and HB timing | exact match; QQ <= tw and cleared by P5; ARM_OK drops tw after the last HB edge | Fix CR |
| T-C-01b | BTB_OFF vs RT1987 conduction | Loop barrier threshold | Drive the T3 input with a slow 0-3.3 V triangle (~1 V/s) with an RT-SI EN in parallel, its VIN/VOUT monitored | H2c rb LOW whenever EN >= 0.45 V; the RT-SI never conducts while H2c rb is HIGH | Lower the U115 threshold (R117/R118) |
| T-C-01c | U115 POR and unpowered | Fail-safe | Hold U115 V+ at 0 V, then ramp through POR with BTB = 0 V | H2c LOW until POR completes (<= 1.9 ms) and while unpowered | Fix |
| T-C-02 | H1 trip points and slow-ramp delay at real slew (3-4.4 V/ms falling, 287 V/s rising); CMRR at 3.3 V; both UVB states | Loop barrier accuracy | Two PSUs on T1/T2 inputs (through R170/R171); sweep at VBUS 15.2/15.9/16.4/19.5 V | within H.1 worst case; delay <= 15 us | Re-trim R113/dividers |
| T-C-03 | UVB and BT_OK thresholds at 0 C and 60 C ambient; Kelvin and R143 effect | FC window shed and permit | Sweep; BT_OK with a mV source referenced to T9 and a 10 mV plane offset injected; T9 lifted | UVB per H.2 bands; BT_OK 6-34 mV, offset sensitivity < 1 mV; T9 open -> trip 15-30 mV | Re-trim R115 or R141/R142 |
| T-C-04 | eFuse: I_OL, fast-trip, UVLO/OVP, dVdT, latch and reset by UVLO, IMON gain; **OUT spike with the real 0.30 m W1/W2 lead**; **FLT vs a slow VCHG-IN ramp** | Fault bound; D103; FR-12/FR-23 | PSU1 + electronic load; (1) soft short 4.1-4.8 A, (2) hard short through a low-Rds MOSFET at the EVM J1 end, (3) OVP trip at 1.7 A; scope OUT at U101 pins (>= 100 MHz, ground spring); ramp VCHG-IN 0 -> 12 V -> 0 with R106 fitted, log pin 35 | 2.05-2.41 A; trip 2.2-4.5 us above 4.1-4.8 A; UVLO 9.7-10.1 V; **OVP 22.6-23.6 V**; latch reset by UVLO; **OUT >= -0.3 V in all three events**; FLT HIGH whenever IN > 10.2 V and no fault | OUT below -0.3 V: SMB 5 A D103 or a 22-33 V TVS across OUT; FLT LOW below 4.5 V: FR-12/FR-23 already gate on V_chg (no change) |
| T-C-05 | **EIB single faults, one at a time, charger converting** | B.6 fault table | Open E1-E8 each, each W5 conductor, R255, R252, R271, R272, Q201 drain; short Q203 D-S; short Q201 D-S; lift E4 and E6 sense joints; remove EIB 3V3 | converter stops or charging stops within 1 ms, and firmware flags the fault (FR-08) for every element, except Q201 D-S short (safe-held, no flag) and Q201-open / Q203-short (held by the other switch; flagged only by this test) | Fix EIB |
| T-C-06 | Firmware sequences T1-T9 on emulated supplies; I2C at 400 kHz | Invariants, timing | LA on all pins + I2C; scope SDA/SCL | I-1..I-9 hold; **FCC/BTB EN overlap = 0 and zero ERR_SWITCH_CONFLICT over 100 pre-emptions, 10 early purges, 10 Run exits from a window**; VINDPM 19.0 V read-back always precedes the BT_BUS rising edge (except T8); **H1 edge injected mid-transaction of the longest poll read, during a 512 B SD write and a file close, and with a forced EEPROM commit (confirm it is deferred): edge to FCCEIL LOW and to the last raise ACK <= 1.5 ms**; tr <= 300 ns at 400 kHz (<= 1000 ns at 100 kHz), Cb recorded | Fix firmware; 100 kHz fallback if tr fails |
| T-C-07 | Every removable conductor open, logic powered | Open-input fail-safe (finding open-input-failsafe) | Open each W5 conductor and taps T2, T3, T4, T5, T8, T9, T10, T11, T21 in turn | /CE >= VIH; ILIM_HIZ < 0.75 V; H2c rb = 0; H1q (GATE) = 0 with T2 open; BT_OK rb = 0 with T8 open; BT_OK trip 15-30 mV equivalent with T9 open; ARM_OK falls with T21 open | Fix |
| T-C-08 | Effect of the T8 pull-up R144 on BT-CURR (pin 41 and MDAC-BT IOUT1 share the net) | INA253 output, droop | Measure pin 41 zero-current reading and the MDAC-BT droop output with and without R144 | shift < 1 mV | 10 MOhm instead (open-tap detection then relies on BT_OK's 33 mV margin; re-check T-C-07) |
| T-C-09 | Maximum `loop()` period over a full Run with charger traffic, SD logging and a forced EEPROM commit | Heartbeat tw sizing (FR-27) | Toggle a spare pin per loop; LA histogram over 30 min | max period <= 7.5 ms while P5 HIGH | Larger C151 (tw up to 100 ms, re-check the H.8 lead) or fix the blocking call |
| T-C-10 | Monostable pulse widths | QUAL window, hang reaction | Scope Q of U111/U113 at 0 C, 25 C, 60 C | QQ 0.30-0.40 s and covering the T-B-20 read instant; ARM_OK drop 30-40 ms | Change C150/C151 |
| T-D-01 | Teensy held in reset (and during boot to `setup()`) with REGEN/BT_BUS emulated HIGH; pad keeper state unknown (i.MX RT1060 IOMUXC) | Fail-safe | Bench loop rig (study S3); DMM/scope on P5, QUAL, FCCEIL, HB | IBAT 0; /CE HIGH; P5, QUAL, FCCEIL <= 0.4 V; no HB edges | Lower R108/R123/R124 (and R136) to 10 kOhm |
| T-D-02 | **Teensy hang with P5 HIGH** in (a) an FC window, (b) regen-armed cruise, (c) mid-burst | Hang (R3' inhibit independent of a live MCU) | Hang key | /CE > 1.3 V and IBAT < 10 mA within tw (<= 40 ms) in all three; (c) V-MOT reaches the VESC cut and regen stops (safe); (a) record the bus minimum at the next purge | Fix CR (heartbeat path); bus minimum below 12 V in (a): R5 priority raised, no FC windows without T-W-01 |
| T-D-03 | **I2C dead and hang inside QUAL** | QUAL single-barrier window | (1) SDA held LOW from REGEN close; (2) Teensy frozen in a debugger with QUAL HIGH and TP36 (E5) lifted | P5 never rises; IBAT 0; ILIM_HIZ < 0.75 V within tw of the QUAL edge | Fix FR-03/FR-04 or the one-shot |
| T-D-04 | Comparator faults: unpowered, output stuck LOW, H1 forced HIGH with V-MOT = VBUS; **R110 open, R112 open, R115 open, T2 open** | Single faults | Jumpers / lifted parts | inputs stay < 7 V (clamps); T2 open drops GATE in regen-armed; IBAT 0 or IBUS <= 5 mA (VINDPM soft layer) and FR-08(d) trip <= 6 ms | Fix |
| T-D-05 | REG05 written 14.0 V while regen-armed, V-MOT = VBUS | Stale soft layer | Firmware fault key | IBAT 0 (H1), disarm <= 20 ms | Fix |
| T-D-06 | QUAL and P5 both HIGH, H1 0, VINDPM auto (below bus), BT_BUS closed; TP36 lifted | Critic C3; QQ cleared by P5 | Fault key | ILIM stays LOW; IBAT 0 | Fix CR |
| T-D-07 | **D-BT-EN shorted in an FC window** (bench loop rig, sub-threshold and above-threshold current) | R8 residual size | Bypass RT-SI "D-BT-EN" with a resistor giving 0.05 / 0.15 / 0.4 A | >= 0.34 A: BT_OK drops the permit; below: FR-10/FR-11 thresholds recorded | Residual stays accepted (R8); record |
| T-D-08 | Brake during an FC window with D-BT-EN shorted | C7 qualifier | As T-D-07 plus V-MOT step | no sustained pack current into the charger | Fix CR |
| T-D-09 | FCCEIL stuck HIGH with the raised image active; abrupt V-MOT drop | Blank / FR-09 | Fault key | FR-09 trip; FC pulse <= 1.86 A for <= 2 ms | Fix |
| T-D-10 | Charger input short and input-to-output short downstream of the eFuse, regen-armed and in an FC window | eFuse bound | Low-R MOSFET short | eFuse limits in us; no boost damage; OC_FC in an FC window acceptable | Re-select the eFuse limit |
| T-D-11 | **EIB-side faults in two named modes** (regen-armed cruise with VINDPM above the source; FC-window ceiling blank) | Far-end readbacks | One at a time: E3 lifted; Q201 removed; R252 removed; U202 Y held LOW; E5 lifted; U201 1Y held LOW; R272 removed | far-end sense mismatch trips (dangerous direction) within 3 ms where the fault releases a barrier; zero sustained IBAT/IBUS; QUAL entry refused with /CE stuck LOW | Fix FR-08/EIB |
| T-D-12 | **False restore during a held brake** | T3 level-sensitive, false-restore guard | Fault key forces a T4 while H1 = 1 at VINDPM | re-raise within 1.5 ms of the first tick; V-MOT peak <= 20.5 V at the T-E-04 capacitance; fault key logged | Fix FR-04/FR-07 |
| T-E-01 | **Purge statistics at 1 kHz:** period, onset jitter (sigma), duration, onset slew, V_fc floor, V_bus FC-only at aux load and at a 1 A load; **>= 20 consecutive intervals at window load (FC 1.0-1.2 A bus-equivalent) and step changes between aux and window load**; bus fall rate with MOT_PWR closed and open | T_LEAD, scheduler, load dependence, hand-off sag | State 98 `K` log on the running H-20 for 10 min two-source, then window-load runs with an electronic load on VBUS (operator present) (fw30 §7) | Design holds if 3 sigma jitter <= 60 ms, the window-load interval differs from the low-load median by < PURGE_JITTER_MAX, and the bus stays >= 13.5 V at aux load | Raise T_LEAD (duty falls ~1 % per 100 ms); per-load-bin prediction or re-learn after load changes; bus < 13.5 V at aux: windows only at standstill with traction 0 |
| T-E-02 | Can the purge-valve drive be tapped, and is it earlier/cleaner than V_fc? | Better onset source | Scope the H-20 controller valve leads vs V_fc | valve edge precedes the V_fc fall | Use V_fc only |
| T-E-03 | **VESC over-voltage behaviour; braking with V-MOT held at 19 V** | Regen at all (study S0-R0/R3) | VESC Tool readout; CV electronic load 19 V 1.3 A on V-MOT; 2 -> 1 m/s decel | braking continues >= 0.25 s with V-MOT at 19 V | Raise `l_max_vin` (<= 23 V with 35 V caps; the eFuse OVP band 22.6-23.6 V then needs re-selection); else regen ends for Path A |
| T-E-04 | V-MOT capacitance | tau budget, raise headroom, rescue floor | decay with a known load, or LCR with the VESC unpowered | known to +-20 % | Recompute H.6/H.7 and FR-26 |
| T-E-05 | V_rgn calibration near 21 V | FR-08(d), T3 ratchet, T4 | Scope true V-MOT vs pin 39 | ratio known to < 1 % | FR-08(d) and the T3/T4 thresholds use a wider band |
| T-E-06 | RT1987 on the board: tD_ON spread on D-BT-EN (20 closures); D-BC-FC turn-off time (EN LOW to body-diode only) vs D-BT-EN tD_ON min; **hand-off delay from the servo-off and TRCB states**: enable D-BT-EN with VIN - VOUT at +20, 0, -40 mV and at -100, -300 mV, then pull VOUT down at 2.5 V/ms; do tD_ON, soft-start or the SCP timer re-run on TRCB release? | T_LEAD; I-9 at conduction level; R6 hand-off | Scope EN, VOUT, CP on the RT1987 output; bench supply as "FC bus" | tD_ON max <= 16 ms; D-BC-FC off >= 1 ms before D-BT-EN can conduct; **crossing-to-conduction <= 0.5 ms in both states** | tD_ON > 16 ms: raise T_LEAD by the excess; servo state fails: the purge needs a pre-onset battery path that does not depend on the RT1987 (design change); TRCB state only: T-E-12 rule mandatory |
| T-E-07 | V-MOT ripple at the H1 tap (frequency, p-p) in cruise and regen | H1 chatter | Scope at C-D6, 20 MHz BW | below the H.1 limits | Larger C106/C107 (slows H1; recompute H.13) |
| T-E-08 | FC-only bus droop vs load; the aux load (0.09-0.15 A assumed) | VINDPM_FC and UVB margins; governor budget | State 98, BT_BUS off, electronic load 0-1.2 A on VBUS (bench supply as FC); FC current with the load off = aux | V_bus >= 15.2 V at 1.05 A; aux recorded | Lower VINDPM_FC/UVB together |
| T-E-09 | Is an NTC fitted at J-NTC? Type and B value | TS wiring | Inspect; measure R at 25 C | 10 kOhm B 3435 or absent | Keep JP18 if absent; else adapt the EVM TS divider |
| T-E-10 | INA253 BT floor on this board; **V(SNS-BT GND - T9 landing) and BT-CURR with BT_BUS LOW during a concurrent regen burst at 3.1 A charge and during BT boost operation at 3 A** | BT_OK false inhibit / false permit | DMM at pin 41 with BT_BUS off; DMM/scope between the SNS-BT GND pad and the T9 landing under each load | floor < 10 mV; ground offset < 2 mV | Move T9 to a better pad; else raise R142 / lower R141 within R8 |
| T-E-11 | Pack maximum charge current and protection (label/datasheet) | ICHG 3.10 A allowed? | Read the pack label/datasheet | >= 3.1 A charge | ICHG 2.50 A with FR-25 limiting brake current (H.7 margin -0.5 % at 7.4 V) |
| T-E-12 | **BT boost output (VBUS-BT, ahead of D-BT-EN) minus VBUS, FC-only at aux load with P5 LOW**, over SoC 7.4-8.4 V and stack temperature | TRCB at enable (F.4); purge-rescue floor | DMM between the D-BT-EN VIN and VOUT pads, State 98 FC-only selection, charger shed | V0_bt - V_bus >= -20 mV and <= +0.3 V everywhere | Raise V0_bt 0.1-0.2 V with the BT TPS61288 FB divider (re-run CAL-1); optional VBUS-BT divider to a free ADC |
| T-F-01 | After Ag105 removal: D-BT-SQ blocks (VCHG ~0 V with BT_SEQ HIGH into 1 kOhm), C-D8/C-D10 replaced, VCHG-IN isolation, R170/R171 values | Board readiness | DMM | VCHG < 0.1 V; isolation; 10.0 kOhm +-0.1 % | Repair before CR |
| T-F-02 | Boot self-test FR-12 passes every boot | Carrier present | 20 boots | 20/20 | Fix |
| T-F-03 | Run entry + regen-armed cruise 60 s; Run-entry inrush; T1 heartbeat self-test | No bus disturbance | Scope VCHG-IN, V-MOT, I_fc, I_batt | IBAT 0 +- 20 mA; I_fc/I_batt unchanged +- 50 mA; inrush <= 0.4 A; T1 step 8 passes | Fix |
| T-F-04 | FC windows at standstill, 20 cycles (warm FCC close) | HR2 | Scope I_fc, V_bus | I_fc peak < 1.2 A; no OC_FC/UV_BUS; charge 1.3-1.6 A | Lower the governor |
| T-F-04b | **FC windows in cruise** at 1.0/1.5/2.0 m/s, a 0 -> 2 m/s step and a 1.0 -> 2.0 m/s step issued inside an open window | OC_FC margin (H.12) | `K` log of I_fc at 1 kHz; record P5 sheds and the window-close-to-conduction time | max single I_fc sample <= 1.30 A; zero OC_FC; the setpoint hold released only after BT conduction | Fit U117 (FR-14e) and repeat; else windows only at standstill/coast with |I_cmd| below the admission bound |
| T-F-05 | Switching noise: spurious H1/H2c/UVB/BT_OK/BTB_OFF/sense transitions | False permits | 10 min full regen and full FC current; LA on readbacks | zero spurious transitions; no false trips | Filters / layout |
| T-F-06 | FC windows on a running H-20 with pre-emption, 30 min | R6 | `K` log + scope; FR-16 records | zero UV_BUS/UV_FC; I_batt > floor within 0.5 ms of V_bus falling 50 mV below its pre-onset value; V_bus min >= 14.5 V through every purge | Raise T_LEAD; T-E-06/T-E-12 fallbacks |
| T-F-07 | Early purge (pre-emption disabled once, operator present) | R6 failure mode | As T-F-06, log V_bus(t), I_batt peak, V_fc onset at 1 kHz | no discharged-node hot-plug; outcome recorded as (a) re-close and ride-through, (b) refusal and ride-through, (c) State 99 or (d) SCP gap then (a)/(c); never a boost fault | Raise VINDPM_FC / UVB, standstill-only windows, or lever 3 |
| T-F-08 | **BT_BUS close transient from an FC-only bus** | H.6; lever 3 decision | Current probe in series with D-BT-EN VOUT, plus V_bus, V-MOT, pin 41; closes from an FC-only bus loaded 0.15/0.5/1.05 A at deltas 0.1/0.3/0.8/1.5/2.4 V (bench supply as the FC), known C_VMOT; 50 closes per point | Record I_pk, width, any 64 ms retry, EN-to-conduction delay, OC_BT trips. Pass for lever 3(i): I_pk < 3.0 A, no SCP, delay within T_LEAD; for 3(ii): no SCP at the deltas FR-26 admits, no OC_BT latch | If C_eff x 12 V/ms > 3 A at the minimum C_VMOT, lever 3 is mandatory before any FC window runs with traction load |
| T-F-09 | **Early purge during a 3 -> 1 m/s brake inside an FC window** | uvb-blocks-raised-regen fix | Inject the early purge (bench FC emulator) mid-brake | no VESC cut; no FC current into the charger (D-BC-FC current < 10 mA) | Fix CR (H2c term) |
| T-G-01 | Regen decels, regen-armed (2 -> 1 and 3 -> 1 m/s, 12 A), at mid SoC and near CV (8.3 V) | HR1; FR-25 | Vehicle on the ground; scope V-MOT, pack current | V-MOT 18.7-19.5 V; no VESC cut; >= 80 % of the T-E-03-predicted energy; near CV the derate acts and no cut occurs | Keep-alive / VESC cut levers; FR-25 tuning |
| T-G-02 | Regen decels inside FC windows, **incl. a modulated brake held at VINDPM > 100 ms and dithered around the H1/VINDPM gap** | R7 | As T-G-01 in a window | raise <= 1.5 ms; zero restores while VINDPM_STAT = 1; V-MOT peak <= 20.5 V; no OC_FC | Faster raise path; FR-04 restore triggers |
| T-G-03 | Abrupt VESC stop mid-burst, both modes | Bounded pulse | `setCurrent(0)` mid-burst | pulse <= I_in x (latency - allowance); count OC_FC trips | Accept (J.2) |
| T-G-04 | Drive cycle with steep decels and FC windows | System | EMS run, 30 min | no trips; I_charge per event; standby draw logged | Any trip: classify by FR-16/telemetry, fix the responsible mechanism, repeat; stop the session on any loop or hot-plug indication |
| T-W-01 | MCU watchdog (R5, future): hang in Run, mid-burst, mid-window | Unattended operation | Hang key | reset <= 100 ms; every EN < 0.6 V within 1 ms; ERR_MCU_WDT reported; WDOG1_B on pin 20 only | No unattended sessions |

## J. Residual risks and known limitations

### J.1 Accepted

1. **R8 (accepted 2026-11-05):** in an FC window with D-BT-EN shorted, a loop below the BT_OK threshold (0.06-0.34 A worst case;
   the INA253A1 floor can reach 0.1 A, SLOS954A §7.5) and below the firmware trip (floor + margin, about 0.12 A) is not stopped
   in hardware for the window duration. FR-11 (power balance) may catch it, depending on T-B-14.
2. Keep-alive drain if T-B-09 fails: 0.7-1.4 mA in Run only (B.5), or the bridge fallback.
3. **Run standby draw of the always-powered regen design: 42-60 mW for all of Run** (H.15), about 10x the keep-alive option.
   It is the price of R3' with an always-powered charger and must appear in the energy statistics (FR-21).

### J.2 Open, ranked

1. **VESC cut-off limits regen whatever the charger** (T-E-03).
2. **Warm response and restart from a decayed VCHG** are unspecified (T-B-09, T-B-10): a cliff, not a slope.
3. **VINDPM reload after the raise** unspecified (T-B-12); staged raise leaves 1.06 ms at 0.4 mF.
4. **Inhibit latency** unspecified (T-B-06): bounded pulse per event, never sustained.
5. **Abrupt VESC stop with the raised image active in an FC window** can produce one FC pulse of <= 1.76 A for the inhibit
   latency, which may latch OC_FC (nuisance State 99).
6. **Purge timing** from 50 Hz data at low load only (T-E-01); the early-purge outcomes are bounded (T-F-07).
7. **RT1987 hand-off from the servo-off / TRCB state** unspecified (T-E-06, T-E-12).
8. **BT_BUS close transient** (H.6): up to 8.5 A for tens of us; OC_BT single sample may catch it; lever 3 is an operator
   ruling (T-F-08).
9. **Dual-switch ILIM release has no per-channel diagnostic in service:** a single latent Q201-open or Q203-short is held by
   the other switch and only T-C-05 finds it; repeat T-C-05 at every rebuild and every 6 months of use.
10. **ILIM pin sampling** (T-B-07): if sampled only at POR, the run-time FC bound is the register plus FCCEIL plus FR-09, not
    hardware; a POR in a window costs regen until re-qualification (FR-30).
11. **Charger watchdog** contradictions in SLUSDV2C (T-B-08); the heartbeat inhibits charging on a hang, but BT_BUS stays open
    in a window through the next purge until R5 exists.
12. **ADC/IMON accuracy** unspecified for transients (T-B-14).
13. **A board-side short of VCHG-IN** (upstream of the eFuse) is covered only by the RT1987 start-up SCP; after tON an enabled
    RT1987 has no current limit (DS-00 §17.5).
14. **Early purge inside the 10 ms of a raised-burst pre-emption:** UVB drops H1q and the converter is cut mid-brake; V-MOT
    reaches the VESC cut (safe, harvest lost).
15. **Firmware contradiction on closing onto a sagging node** (ino ~13035 vs ~15380): operator item; FR-26 confines the rescue
    predicate to the purge closes.
16. **Hand-built carrier/EIB** reliability (VQFN-24 by hot air); T-A-06, T-C and T-F gates.
17. FC charging in cruise is budget-limited (governor, P_MAX, OC_FC), not charger-limited; EMS models must use the governor.

## K. Sources

- Board: `references/Scale_Car_Board_20260624.sch`, `references/Scale Car Board PCB 20260625.brd`,
  `references/Scale Car Design PCB BOM 20260622.csv`, `references/Scale Car Teensy IO - IO.csv`,
  `teensy_controller/teensy_controller.ino` (fw v37 rev 2: `LIMIT_I_FC_MAX` 1.4 A, `LIMIT_V_BUS_MIN` 12.0 V,
  `V_BUS_CHARGED_THRESH`, `busHotPlugUnsafe()`, `FAULT_SWITCH_CONFLICT` at 7413-7418, OC_BT at 7430, `SHARE_SELECTOR_DWELL_MS`).
- TI SLUSDV2C BQ25798 (§6.3, §6.5 EC; §7.3.4 power-up steps; §7.3.4.2 poor source; §7.3.4.3 ILIM_HIZ; §7.3.9.1-7.3.9.2 charging
  profile; Table 7-11 STAT; §7.5 registers). TI SLUUCB5E BQ2579xEVM (Table 1-2, Table 1-3, Fig 4-1, Fig 4-5, Fig 4-6 viewed as
  rendered PNG, Table 4-1 BOM).
- Richtek RT1987 DS-00 (EC p.7-8; §17, §17.1, §17.3, §17.4 Table 1, §17.5, §17.6).
- TI SLVSE94G TPS2663x (§4 comparison, Table 5-1, §6.1, §6.3, §6.5, §6.6, §8.3.1, §8.3.3, §8.3.7, Table 8-1, §9.2.2, §9.5.1, §11).
- TI SBOS300C TLV3011/3012 (§6.1, §6.9 B-grade EC, §6.10, §9.4.4-9.4.5). TI SCES364J SN74LVC3G06, SCES363L SN74LVC3G04,
  SCES201N SN74LVC2G32, SCES198N SN74LVC2G08, SCES487I SN74LVC1G11, SCES586E SN74LVC1G123, SCES295AB SN74LVC1G06, SCES217AA
  SN74LVC1G08 (r0). TI SLVSDH0C TPS22810.
- TI SLOS954A INA253 (repo copy), §7.5. NXP IMXRT1060RM Rev 3 §11.6 (pad mux for GPIO_B1_13, AD_B1_00, AD_B1_10, AD_B1_11).
- `docs/charger_replacement_evaluation_2026-11-05.md` (study), `docs/reviews/charger_eval_2026-11-05/spec.md`,
  `round2/loop_analysis.md`, `round2/regen_dynamics.md`, `round2/dossier_BQ25798.md`, `round2/design_BQ25798.md`.
- `docs/fw30_fc_purge_uv.md`; `docs/reviews/fw36_regen_2026-11-04/README.md` §2 (purge statistics from the Pi bags);
  `controller_design/system_model.md` (dV0 bench data); `references/H20-Small-Stacks-Brochure.pdf` (no purge interval given).
- Stock: TI store inventory endpoint, plain curl, 2026-11-05 22:00 UTC.

## L. Review log (round 1: dispositions that differ from the finding as written)

All 53 findings were verified real; the full per-finding table is in `round3/review_loop.md`. These are the places where the
design keeps a different implementation from the one the finding or its verifier proposed, and why:

| Finding | Proposed | Applied instead | Why |
|---|---|---|---|
| eib-wireoff-releases-converter | P-MOSFET high side of EVM R21, fed from REGN | EVM R21 removed; Q203 + R255 on the EIB feed the release current to the JP14 ILIM-side pin | EVM R21's top is hard-wired to REGN on the EVM; a PMOS between R21 and ILIM_HIZ would have its source on a 50 kOhm node (VGS only about -2.2 V). Moving the resistor behind the switch gives a clean REGN-referenced gate drive and makes a lead-off fail to HIZ |
| ilim-band-leakage-omitted | fold leakage in; re-centre if needed | also **replaced EVM R23 100 kOhm with 49.9 kOhm** and scaled R255/R257 | halves the leakage error; the r0 values with leakage gave 1.23-1.82 A and an FC POR clamp up to 1.04 A |
| eib-wireoff / open-input (R256 at TP33) | 1 MOhm at TP33 | **200 kOhm** | with worst-case leakage (2.8 uA) 1 MOhm alone would sit at 2.8 V, above the 0.75 V HIZ threshold; 200 kOhm holds <= 0.57 V |
| readback-misses-evm-side (/CE sense) | SN74LVC1G17/1G14 Schmitt buffer | **TLV3012B with a 1 MOhm / 1 MOhm divider** | pA inputs do not load the 47 kOhm /CE pull-up (an LVC input may draw 5 uA), and a broken sense wire or dead comparator reads "/CE LOW", the dangerous direction, so it announces itself at the next P5-LOW check |
| open-input-failsafe (BTB pull-up) | 100 kOhm pull-up on the LVC side of R120 | **1 MOhm on the U115 comparator input** | BTB is now sensed by a comparator with pA inputs, so 1 MOhm gives a defined open-tap level, and the reset-state EN net stays at 32 mV instead of 0.30 V |
| readback-misses-evm-side (I2C) | 14-way ribbon carrying I2C to the EIB | I2C on its own 4-way cable W7 straight to EVM J8 | J8 is in the far corner of the EVM from the EIB position (finding eib-mounting); routing I2C through the EIB would double the run |
| carrier-no-buildable-layout | Gerbers and pick-and-place in the document | pin-level netlist (B.8), layout constraints and hole table (A.8), PM0 KiCad capture gate checked by T-A-06 | no CAD tool is available in this session; the document is the capture source and the gate prevents assembly before a checked fabrication package exists |
| ocfc-margin-traction-transient-fc-window (a3) | hardware FC-current shed comparator | footprint provided, **DNP** (U117), fitted if T-F-04b fails | the verifier rated it optional; the firmware admission bound, setpoint hold and peak-hold governor are the primary fix |
| t1-t2-unprotected-power-taps | 10 kOhm at each joint, counted in the divider top | done; the single T2 wire feeds both H1 and UVB, so the shared R171 is solved as one network and R111/R115 re-trimmed | two VBUS wires would let a lost H1 tap leave UVB valid and defeat the UVB term in H1q |
| btok-kelvin (two findings) | move T9 to SNS-BT, or keep J2.03 and measure | both: T9 to the SNS-BT GND/REF1 pad **and** R143 100 ohm to the CR plane | R143 keeps the trip defined if T9 opens |
