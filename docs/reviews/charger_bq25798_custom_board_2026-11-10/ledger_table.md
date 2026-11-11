| Rnd | # | Key | Severity | Tag | Path A-C status | Reason (source) |
|---|---|---|---|---|---|---|
| 1 | 1 | `preempt-fcc-btb-overlap` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 2 | `eib-wireoff-releases-converter` | major | b,c | **CLOSED** | No lead can lift; the two-switch release Q403 + Q401 is kept, and a cracked on-board trace reads LOW through R467-R470 ([SCH] 6.1, 6.2) |
| 1 | 3 | `qual-window-single-barrier` | major | d,e | **KEPT** | The QUAL one-shot carries over as U311 (BQ25798-specific) ([SCH] 5.1) |
| 1 | 4 | `p5-static-arm-hang` | major | d,f | **KEPT** | Heartbeat monostable U313 and ARM_OK carry over ([SCH] 5.1); T-K-09 step 3 re-proves them with the converter switching |
| 1 | 5 | `permit-tap-failsafe-and-en-threshold` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 6 | `comparator-divider-open-faults` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 7 | `uvb-blocks-raised-regen` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 1 | 8 | `btok-sense-wire-open` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 9 | `regen-capability-ichg-bound` | major | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 1 | 10 | `btbus-reclose-inrush-unquantified` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 11 | `efuse-out-schottky-missing` | major | a,d | **CHANGED** | D303 loses its main case (far-end short on 0.3 m leads) but stays fitted; fit or DNP and its leakage beside the LM1084 are open ([SCH] 3.2 item 2, O-12) |
| 1 | 12 | `ocfc-margin-traction-transient-fc-window` | major (uncert.) | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 13 | `ilim-band-leakage-omitted` | minor | e,c | **CHANGED** | R523 49.9 kOhm stays as a BOM choice; the H.4 band is re-derived with on-board leakage ([SCH] O-11) |
| 1 | 14 | `evm-c43-25v-vbus-ldo` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 1 | 15 | `btok-kelvin-wrong-reference` | minor (uncert.) | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 16 | `run-quiescent-draw-unaccounted` | minor | e,d | **CHANGED** | The 55-78 mW Run budget is re-booked for the merged rail and the deleted series parts (TODO(calc), T-K-05) |
| 1 | 17 | `efuse-ovp-above-bq-rating` | minor | d,e | **KEPT** | eFuse OVP 22.61-23.63 V stays and is now the only input OV device in front of U501, since the ACFET pair is omitted ([SCH] 2.1 D2) |
| 1 | 18 | `carrier-copper-unspecified` | minor | d-mech | **CHANGED** | Stack moves from 2 oz outer to 1 oz outer (B1) or 2 oz inner (B2), because the RQM land pattern has 0.2 mm gaps; current capacity moves to width ([LAY] 3.1.3). Digest CB: N |
| 1 | 19 | `btb-sense-threshold-gap` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 20 | `open-input-failsafe` | major | b,d | **CHANGED** | No removable conductor inside the charger chain; R467-R470 stay for cracked traces and joints on a moving vehicle ([SCH] 6.1). Tap inputs keep their biases |
| 1 | 21 | `readback-misses-evm-side` | major | b | **CLOSED** | U403/U404 sense the U501 ILIM_HIZ and /CE pins on their own traces ([SCH] 6.1; [LAY] 3.6.2 item 2) |
| 1 | 22 | `raise-latency-i2c-budget` | major | a,f | **CHANGED** | FR-07 caps stay; the on-board bus (no W7) can only add margin ([FW] 5.2 FR-07, 5.3 item 1) |
| 1 | 23 | `latent-comparator-faults` | minor | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 24 | `uvb-ref-drift-margin` | minor (uncert.) | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 1 | 25 | `imon-clamp-leakage` | minor (uncert.) | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 1 | 26 | `btok-kelvin-reference` | minor (uncert.) | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 27 | `efuse-flt-unpowered-state` | minor (uncert.) | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 28 | `tb03-ce-pass-criterion` | minor | c,e | **KEPT** | R472/R472b 47.0 kOhm and the /CE >= 3.0 V criterion are unchanged ([SCH] 6.1; T-K-10). Digest CB: P |
| 1 | 29 | `stale-designators-in-fixes` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 1 | 30 | `pin34-wdog1b-pad` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 31 | `preempt-switch-conflict-latch` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 32 | `preempt-bt-trcb-conduction` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 33 | `early-purge-refusal-band` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 34 | `restore-threshold-vindpm-band` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 1 | 35 | `regen-capability-ignores-ichg` | major (uncert.) | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 1 | 36 | `fr08-uvb-unobservable` | major | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 37 | `raise-vindpm-unload-transient` | major (uncert.) | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 1 | 38 | `purge-interval-load-dependence` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 39 | `fc-window-por-latches-fc-clamp` | minor (uncert.) | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 1 | 40 | `t3-latency-blocking-i2c` | minor | a,f | **CHANGED** | As raise-latency-i2c-budget |
| 1 | 41 | `t2-bt-bus-ownership` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 42 | `telemetry-ems-gaps` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 1 | 43 | `carrier-no-buildable-layout` | major | d-mech,doc | **CHANGED** | Re-opened: the CCB books 1532 mm2 against 1514 mm2 usable (101 %); the remedies reach 78-86 % ([LAY] 3.2.3). Digest CB: N |
| 1 | 44 | `eib-mounting-and-tp-placement` | major | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1) |
| 1 | 45 | `stale-designators-collide-with-evm` | major | c,doc | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 1 | 46 | `evm-c43-25v-on-input` | major | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 1 | 47 | `bom-mpns-incomplete` | major | doc | **KEPT** | Re-opened on the CCB BOM: C511/C512/C529-C531, socket strips, adhesive and the snubber have candidate or no MPNs ([BOM] 3.3) |
| 1 | 48 | `rb2-designator-collides-with-mb` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 1 | 49 | `duplicate-em-ids` | minor | c,doc | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 1 | 50 | `tap-twisted-gnd-unterminated` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 51 | `registry-missing-pass-fail` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 1 | 52 | `t1-t2-unprotected-power-taps` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 1 | 53 | `doc-svg-number-mismatches` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 1 | `evm-jp14-feed-joint-floating` | blocker | c | **CLOSED** | No R21, JP13 or JP14 footprint; rule 4.2.1 allows only Q403 + R455 between REGN and ILIM_HIZ ([SCH] 7.2 EM3) |
| 2 | 2 | `reg14-write-reopens-extilim` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 2 | 3 | `efuse-out-schottky-missing-reopen` | major | a,d | **CHANGED** | As efuse-out-schottky-missing; T-C-04 runs again on the CCB ([SCH] O-12) |
| 2 | 4 | `w8-unfused-hot-lead` | major | a | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB ([SCH] 5.2 item 3) |
| 2 | 5 | `fr08-hb-latency-false-trip` | major | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 6 | `eib-pin8-backpower-unpowered-outputs` | major | b,g | **CHANGED** | No separate EIB rail; the BAV199 back-feed into the merged rail remains and R474 holds it at 0.3-0.45 V ([SCH] 6.1) |
| 2 | 7 | `cr-3v3-single-tap-backpower` | major | b,c,g | **KEPT** | The CCB rail is still fed from one tap T6 through R375; I2C still runs on the MB pull-ups RSDA/RSCL 2.7 kOhm (PM9), R345/R346 DNP ([SCH] 7.2 EM6). Digest CB: P |
| 2 | 8 | `pin8-encoder-net-occupancy` | major | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 2 | 9 | `pin8-tap-on-encoder-net` | major | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 2 | 10 | `preempt-drops-subh1-regen` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 11 | `preempt-p5-low-drops-brake-absorption` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 12 | `rescue-predicate-checked-before-tdon` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 13 | `setpoint-hold-conduction-deadlock` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 14 | `t2-btbus-open-without-fc-conduction` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 15 | `warm-response-pass-criteria-inconsistent` | major | e,doc | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 2 | 16 | `telemetry-ems-gaps-reopen` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 2 | 17 | `window-reopen-rule-limits-fc-duty` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 18 | `chg-header-strips-10-12` | major | d-mech | **KEPT** | The CCB uses the same 1x10 + 1x12 strips; option K adds matching socket strips ([MCH] 1.3.4) |
| 2 | 19 | `carrier-no-buildable-layout-reopen` | major | d-mech | **CHANGED** | As carrier-no-buildable-layout; the courtyard DRC of the capture is the gate ([LAY] L-1) |
| 2 | 20 | `bom-resistor-mpns-out-of-range` | major | doc,d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 2 | 21 | `evm-tp42-is-scl` | major | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 2 | 22 | `tc04-out-spike-criterion-unattainable` | major | a,d | **CHANGED** | The OUT loop inductance falls to the copper value; the T-C-04 OUT criterion is re-derived for the CCB ([SCH] 3.2 item 2) |
| 2 | 23 | `btb-pullup-backdrives-en` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 2 | 24 | `h2c-h1-term-not-rgn-qualified` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 2 | 25 | `qual-clr-edge-bypasses-gate` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 2 | 26 | `ground-loops-parallel-returns` | minor | a,b | **CHANGED** | The lead and ribbon returns are gone, but the CCB plane joins pads 4 and 14/15 in parallel with the MB GND pour, and the split depends on the MB copper ([SCH] 10.1; [SCH] 10.2 item 5; [SCH] 10.3). T-F-11 is re-scoped to the one-plane partition; T-K-17 measures the pin 4/14/15 currents. Tap shields stay bonded at the board end. Digest CB: Y |
| 2 | 27 | `evm-agnd-parallel-return` | minor | a,b,c | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB ([SCH] 5.2 item 3) |
| 2 | 28 | `run-quiescent-draw-unaccounted-reopen` | minor | e,b,d | **CHANGED** | As run-quiescent-draw-unaccounted |
| 2 | 29 | `evm-power-shunts-unsourced` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 2 | 30 | `ina253-adc-offset-from-charger-return` | minor | a,g | **CHANGED** | The return moves from W2 to pads 4/14/15; the MB-GND drop that shifts the ADC remains (T-F-04c, T-F-15) |
| 2 | 31 | `t-a-04-criterion-not-datasheet` | minor | c,doc | **CHANGED** | T-A-04 now checks the CCB's own 50 V X7R parts against the SLUSDV2C effective-capacitance minima at 23.6 V ([SCH] O-1; [BOM] B-4). Digest CB: Y |
| 2 | 32 | `ilim-sense-threshold-above-hiz-vil` | minor | b | **KEPT** | U403 keeps the 0.587-0.650 V threshold below VIL_ILIM_HIZ 0.75 V ([SCH] 6.1). Digest CB: P |
| 2 | 33 | `lvc-slow-edges-reset` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 2 | 34 | `i2c-bus-recovery-missing` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 35 | `csv-h2-text-omits-fciok` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 36 | `csv-row16-omits-fciok` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 37 | `early-purge-trigger-misattribution` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 38 | `fc-window-budget-vs-h20-pmax` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 2 | 39 | `todo-outside-registry` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 40 | `evm-input-cap-figure` | minor | c,e | **CHANGED** | The VCHGOUT ceramic total is the CCB's own, 51.3 uF nominal; the no-electrolytic rule stays ([SCH] 7.2 EM24) |
| 2 | 41 | `w7-gnd-termination` | minor | a | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB ([SCH] 5.2 item 3) |
| 2 | 42 | `p5-name-collision` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 43 | `svg-netlist-designator-gaps` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 44 | `h15-3v3-load-understated` | minor | d | **CHANGED** | The 1.82 mA EIB share and the CR load merge onto R375; the logic quiescent budget is re-computed (T-K-05 TODO(calc)) |
| 3 | 1 | `t1-ce-check-before-regn` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 3 | 2 | `fr08-powered-predicate-ignores-regn` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 3 | 3 | `ce-sense-gating-before-regn` | major | e,b | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 3 | 4 | `ce-pullup-link-sense-divider-fails-low` | major | c,b | **CHANGED** | Links L1/L2 disappear; R472/R472b keep separate pads and vias ([SCH] rule 4.2.3; [LAY] 3.6.2 item 3) |
| 3 | 5 | `heartbeat-proves-loop-not-monitor` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 3 | 6 | `btb-off-stuck-high-undetectable` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 3 | 7 | `u203-stuck-held-latent-no-entry-test` | minor | b | **KEPT** | U403 is kept, so its stuck-held latent fault and the T1 step-6 pin-33 proof remain ([SCH] 6.1). Digest CB: P |
| 3 | 8 | `early-purge-sag-asserts-h1` | minor (uncert.) | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 3 | 9 | `t3-t4-fcceil-race` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 3 | 10 | `ina253-bt-common-cause` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 3 | 11 | `efuse-in-spike-c102-undersized` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 3 | 12 | `cr-bottom-over-mb-power-traces` | major | d-mech,g | **KEPT** | Flush tails, no underside parts over MB power copper + 1 mm, polyimide sheet; L4 must now also shield the switch nodes ([MCH] 1.3.5, 1.5; [LAY] 3.1.1) |
| 3 | 13 | `input-path-ir-drop-omitted` | major | a,c | **CHANGED** | R_PATH_RG loses W1/W2, EVM R2 and JP3; the CCB value is TODO(calc: H.19); tests keep 0.19 ohm as a bound ([SCH] 3.2 item 3; [TST] G4) |
| 3 | 14 | `mb-vchgin-vias-current-rating` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 3 | 15 | `t18-5v-tap-unprotected` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 3 | 16 | `btok-selftest-floor-overlap` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 3 | 17 | `u203-threshold-ignores-sense-offset` | minor | b | **CHANGED** | U403 threshold re-derived for the CCB divider values ([FW] 5.4 row 33) |
| 3 | 18 | `csv-pin20-reservation-missing` | minor | doc,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 3 | 19 | `early-purge-fc-ridethrough-infeasible` | major | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 3 | 20 | `window-ignores-ems-intent-and-termination` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 3 | 21 | `scheduler-unlock-on-load-starves-windows` | major (uncert.) | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 3 | 22 | `h1-asserts-on-bus-sag` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 3 | 23 | `cr-power-pad-coords-on-pin-column` | major | a,d-mech | **CLOSED** | The W1/W2 power-lead pads are deleted; pad 10 and pins 18/19 connect by copper ([SCH] 5.2 item 3; [LAY] 3.3.3). Digest CB: P |
| 3 | 24 | `evm-jp13-regn-pin-stray-shunt` | major | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 3 | 25 | `j101-unkeyed-ribbon-reversal` | major | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1) |
| 3 | 26 | `tps26630-pwp-alternate-nonexistent` | minor | d | **KEPT** | Resolved in round 3; the CCB uses the same TPS26630RGER ([BOM] 2) |
| 3 | 27 | `todo-outside-registry-reopen` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 3 | 28 | `fr08b-label-collision` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 3 | 29 | `bav199-clamps-backfeed-cr-rail` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 3 | 30 | `r256-c252-agnd-landing-unspecified` | minor | c,b | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 3 | 31 | `evm-j3-j4-live-terminals` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 3 | 32 | `d103-fallback-contradicts-criteria` | minor | d | **CHANGED** | D303 criteria stay; whether D303 is fitted at all is re-opened ([SCH] O-12). Digest CB: N |
| 3 | 33 | `eib-layout-unbudgeted` | minor (uncert.) | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1) |
| 3 | 34 | `u117-option-values-missing` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1) |
| 4 | 1 | `hang-fc-window-r5-gates-r1` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 2 | `hang-fc-window-purge-reclose-death5` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 4 | 3 | `i2-vs-preempt-stepb-failure-branch` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 4 | `i4-blocks-state99-under-h1` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 5 | `fr12-idle-selftests-need-motpwr-btbus-low` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 6 | `charger-trip-in-window-leaves-bt-bus-open` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 7 | `hb-selftest-skips-ilim-leg` | minor | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 8 | `pin35-flt-floats-on-open-tap` | minor | g,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 9 | `eib-e1-regn-adjacent-to-ilim-feed` | minor | b | **CLOSED** | No E-pad row; the successor is [LAY] 3.6.2 item 4 (no part between REGN and ILIM_HIZ except Q403 + R455) |
| 4 | 10 | `i2-btboff-precondition-unobservable` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 11 | `fallback2-dbtsq-disconnect-claim` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 4 | 12 | `d107-tvs-crowbars-vmot-regen` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 4 | 13 | `ov-batt-cv-margin-ignores-adc-error` | major | e,g | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 4 | 14 | `ilim-clamp-por-adc-error-omitted` | minor (uncert.) | e | **KEPT** | T-B-23 stays; T-K-10 gates it because the POR ADC samples the ILIM_HIZ pin under switching |
| 4 | 15 | `r172-0805-short-dissipation` | minor | g,d | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 4 | 16 | `cr-eib-3v3-feed-unprotected-short` | major | b,d | **CLOSED** | No CR-to-EIB 3V3 feed exists; the ex-EIB stages share the one rail behind R375 ([SCH] 5.2 item 2). Digest CB: P |
| 4 | 17 | `ribbon-adjacent-short-ilimrelb-rfcoff` | minor | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1) |
| 4 | 18 | `tlv3012-ribbon-driver-short-current` | minor | b | **CHANGED** | R264/R265 deleted; the off-board conductor is now the tap wire F13/F20, and a short to GND draws 3.18-3.30 mA through R325/R348 1.00 kOhm alone, inside the TLV3012B 10 mA limit ([SCH] 6.1). Digest CB: Y |
| 4 | 19 | `pin22-adc-keeper-imon-error` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 20 | `fc-window-raise-ignores-governor-floor` | major | f,e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 4 | 21 | `purge-lock-tolerance-exceeds-tlead` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 22 | `preempt-btbus-not-owned-through-purge` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 23 | `fr11-trips-on-concurrent-regen` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 24 | `preempt-vindpm-failure-blocks-step-d` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 25 | `sag-path-no-return-to-raise` | minor (uncert.) | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 26 | `chg-src-misattributes-subh1-regen` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 4 | 27 | `efuse-cluster-no-room-at-pad10` | major | d-mech | **CHANGED** | The eFuse cluster now competes with the power stage; utilisation is 101 % as drawn ([LAY] 3.2.3, L-1) |
| 4 | 28 | `svg-w5-pin6-legend-gnd` | minor | doc,b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1) |
| 4 | 29 | `bom-26awg-wire-quantity` | minor | a,doc | **CHANGED** | The lead wire disappears; the wire line shrinks to the taps only ([BOM] 4.4). Digest CB: Y |
| 4 | 30 | `w3w4-hole-vs-18awg-silicone` | minor | a | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB ([SCH] 5.2 item 3) |
| 4 | 31 | `evm-jp3-jp5-link-pin-rating` | minor (uncert.) | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 4 | 32 | `pm4-header-solder-sequence-ambiguous` | minor | d-mech | **CHANGED** | Option K (socket strips in the MB) and the bonded feet replace the PM4 solder sequence; seat heights move to T-K-04 ([MCH] 1.3.4, 1.4). Digest CB: N |
| 5 | 1 | `ff-brake-edge-clears-peakhold-on-ripple` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 5 | 2 | `preempt-deadline-outside-completion-token` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 5 | 3 | `rtwdog-50ms-vs-blocking-flash-ops` | major (uncert.) | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 5 | 4 | `t10-fr08b-proof-relies-on-slow-decay` | minor | f,e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 5 | 5 | `rt1987-ovp-otp-restart-contradiction` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 5 | 6 | `fallback2-pack-unfused-on-w3-and-bridge-rating` | major | a,g | **CHANGED** | W3 is gone; the fallback-2 fused MB link C-D12 -> C-D11 remains, with VCHG now on CCB copper |
| 5 | 7 | `rt1987-ovp-latch-vs-autorestart-contradiction` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 5 | 8 | `imon-vchg-ground-offset-under-charge-current` | minor (uncert.) | a,g | **KEPT** | IMON (pin 22) and V_chg (pin 38) still ride the MB-GND drop; T-F-15 still applies ([SCH] 10.4 item 2). Digest CB: P |
| 5 | 9 | `ichg-upper-tolerance-omitted-in-ratings` | minor | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 5 | 10 | `ribbon-4-5-stat-sink-abs-max` | major | b | **CHANGED** | No ribbon; the on-CCB causes are a STAT-to-CE_DRV or STAT-to-3V3 trace or solder-bridge short (FR-22, T-C-05) and a pin-6 OUTPUT HIGH firmware fault. R475 1.00 kOhm is kept and holds the STAT sink to 3.06-3.30 mA against the 6 mA abs max; 41 mA without it ([SCH] 6.1). Digest CB: Y |
| 5 | 11 | `eib-e6-e7-ce-stat-bridge` | minor | b | **CHANGED** | The lead bridge is gone; an adjacent-trace or solder-bridge short between the pin-6 and CE nets replaces it as an FR-22 case ([FW] 5.3 FR-22). Digest CB: Y |
| 5 | 12 | `gov-cmd-proxy-abs-closes-window-on-brake` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 5 | 13 | `ff-iindpm-step-overlaps-traction-ocfc` | major (uncert.) | f,e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1) |
| 5 | 14 | `flash-commit-stalls-hb-and-wdt-in-run` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 5 | 15 | `purge-fc-only-ridethrough-bag-evidence` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4) |
| 5 | 16 | `efuse-cluster-no-room-at-pad10-reopen` | major | d-mech | **CHANGED** | As efuse-cluster-no-room-at-pad10; the congested region is x 33-41, y 56-67 ([LAY] 3.2.3) |
| 5 | 17 | `pm4-header-solder-sequence-ambiguous-reopen` | major | d-mech,a | **CHANGED** | As pm4-header-solder-sequence-ambiguous |
| 5 | 18 | `ribbon-adjacent-short-stat-cedrv` | major | b | **CHANGED** | As ribbon-4-5-stat-sink-abs-max; the pin-6-to-CE_DRV short case is kept in FR-22 and T-C-05 ([SCH] 6.1). Digest CB: Y |
| 5 | 19 | `j101-mated-socket-envelope` | minor (uncert.) | b | **CLOSED** | No J101; the option-K socket envelope is the new item N-24 (T-K-04) |
| 5 | 20 | `evm-jp17-stray-shunt` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint ([SCH] 7.2) |
| 5 | 21 | `b8-netlist-omits-cr-holes-pads` | minor | doc,d | **CHANGED** | A new pin-level netlist replaces B.8 ([SCH] 8); BAV199 and SOT-23 pinnings are still TODO(verify) ([SCH] O-9). Digest CB: N |
| 5 | 22 | `bom-polyimide-adhesive-unspecified` | minor | d-mech | **KEPT** | Header and MB-interface mechanics; any board in the 22 holes inherits them ([MCH] 1.3) |
| 5 | 23 | `cr-end-strain-relief-anchor` | minor | a | **CHANGED** | W1-W4 strain relief disappears; tap-lead strain relief within 30 mm stays ([MCH] 1.7.2 item 4) |
| 5 | 24 | `layout-table-dimension-gaps` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 6 | 1 | `vreg-corruption-no-fixed-pack-ovp` | major | d,e,g | **KEPT** | The BQ29200 OUT -> U323 -> OVN term and ARM_OK' (U322) carry over; tap T22 and PM11 stay ([SCH] 5.1) |
| 6 | 2 | `dbtsq-short-unfused-pack-on-vchg` | minor | g | **KEPT** | D-BT-SQ stays on the MB; a short still puts the pack on VCHG, now on CCB copper; FR-48 stays |
| 6 | 3 | `cr-and-mb-battery-path-copper-sized-below-ichg` | major (uncert.; verifier minor) | d-mech,g | **CHANGED** | CCB side re-sized: >= 2.5 mm pours at 1 oz, >= 5 vias of 0.3 mm per transition ([LAY] 3.1.4-3.1.5). The MB VBT part stays (T-A-06c, T-F-16). Digest CB: N |
| 6 | 4 | `tc04-in-spike-criterion-omits-mb-vchgin-ratings` | major (uncert.) | d,g | **KEPT** | The eFuse IN side (C302a/b/c, D307) and the MB VCHG-IN end are unchanged; the three-point T-C-04 scope stays ([SCH] 3.1) |
| 6 | 5 | `imon-bypass-cap-against-datasheet` | minor | d | **KEPT** | C305 stays DNP on the same eFuse network ([SCH] 3.1; [BOM] 1.1) |
| 6 | 6 | `fcc-rgn-lvc-threshold-vs-rt1987-en-band` | major | d,g | **KEPT** | Comparators U319-U321 (FCC_OFF, FCC_ON, RGN_ON) carry over on the same MB EN taps ([SCH] 5.1) |
| 6 | 7 | `pin38-39-adc-overvoltage-on-vmot-excursion` | minor (uncert.) | g | **KEPT** | Pins 38/39 sense the same MB nodes; FR-49 stays ([FW] 5.2) |
| 6 | 8 | `loop-budget-5ms-breaks-1ms-tick-deadlines` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 6 | 9 | `purge-fc-only-ridethrough-bag-evidence-reopen` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 6 | 10 | `chg-src-misattributes-subh1-regen-reopen` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 6 | 11 | `ff-headroom-admission-contradicts-single-g-test` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation ([FW] 5.3) |
| 6 | 12 | `ff-reversal-hold-unattainable-at-100khz` | minor | f,a | **CHANGED** | The 100 kHz fallback is less likely without W7; the SCL rise time on the CCB decides it (TODO(measure), [FW] 5.3 item 1) |
| 6 | 13 | `cr-coordinate-convention-mirror-ambiguity` | major | d-mech | **CHANGED** | The tab removes the CR pin-11 chamfer corner; the marker moves to (38.90, 76.40) and pin_identity_check.py must run again ([MCH] 1.8; [TST] OT-7). Digest CB: N |
| 6 | 14 | `eib-e-lead-max-lengths-geometrically-infeasible` | minor | b,a | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1) |
| 6 | 15 | `t-a-05-stale-j101-region-dims` | minor | b,doc | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1) |
| 6 | 16 | `a6-w2-not-beside-star-pads` | minor | a | **CHANGED** | No W2; the battery return reaches pads 14/15 through the plane, in parallel with the MB GND pour, as ground-loops-parallel-returns ([SCH] 10.2 item 2; [SCH] 10.3). Digest CB: Y |
