# Round 3 review-design loop: BQ25798EVM wiring, carrier and operating design (2026-11-05)

Subject: `docs/charger_bq25798_wiring_design_2026-11-05.md` (the design), `wiring_bq25798.svg`, `carrier_schematic.svg`,
`calc/r3_calc.py`, `calc/make_svgs.py`. Passes 0-3 and the closing pass below are the designer's self-review of revision r0.
**Review round 1** (end of this file) is the independent review: 53 findings (about 45 distinct issues), each checked against the primaries by a
separate verifier, applied in revision r1. Numbers quoted in passes 0-3 are r0 values; the design document and
`calc/r3_calc_out.txt` carry the r1 values.

Each finding has an ID, the evidence that confirmed it, and the change made. Line numbers are not quoted, because the design
was edited after each pass.

## Pass 0: draft inputs re-checked

| Check | Result |
|---|---|
| Round-2 permit-network defect (GATE = H1 OR H2, study §2.3) | Confirmed in `round2/design_BQ25798.md` §3.1; the draft rewrote the network for R6/R7 (design B.1) |
| R7 physics: does D-BC-FC stop feeding the charger when V-MOT > VBUS? | Confirmed from RT1987 DS-00 §17.6 p.16: gate forced off below VFWD (35 mV typ), fast comparator at -50 mV in 0.5 us typ. All typical only, so T-B-12 measures it |
| Purge period source | Found in `docs/reviews/fw36_regen_2026-11-04/README.md` §2 (10.34 s, 100-140 ms, 50 Hz bags). The H-20 brochure gives no interval (pdftotext search). fw v30's "brochure 10 s" is not in the brochure text |
| EVM designators | Fig 4-5 and Fig 4-6 rendered as PNG and read: TP27 REGN, TP33 ILIM_HIZ, TP36 /CE, TP38 STAT, TP48 AGND; J8 pin 1 AGND, 2 SCL, 3 SDA, 4 EV2400 pull-up; R20/JP13, R21/JP14, R23, JP21 on ILIM_HIZ; R42 /CE to PULLUP; JP7 USB_VIN to VAC1 |
| C-D8/C-D10 package | `.brd` package CAPC2012X110 = 0805, not the 1206 the study suggested (design D.1 PM2) |

## Pass 1: safety, loop and sequencing lens

Checklist: every mode in F.2 has a loop barrier and a runaway bound; every transition keeps I-1..I-8; every single fault
lands safe; the firmware cannot defeat a hardware barrier by ordering; Death-5 doctrine kept.

| ID | Finding | Evidence | Disposition |
|---|---|---|---|
| P1-1 | **Purge pre-emption can be delayed up to 250 ms** by the fw v28 selector change dwell, longer than the 100 ms lead | `SHARE_SELECTOR_DWELL_MS = 250` (ino 3466) applies to every selection change | **Fixed:** FR-15 makes the pre-emption BT_BUS close bypass the dwell and every deferral except `busHotPlugUnsafe()`; T-C-06 checks it |
| P1-2 | **Pre-emption during a raised burst** (regen image active in a window) cut the converter with P5 LOW first and let V-MOT run to the VESC cut | F.4 general order: P5 LOW, BT_BUS HIGH | **Fixed:** variant: FC_CHARGE LOW first (GATE = H1q = H1 keeps absorbing; loop-safe because BT_BUS is still LOW and H1 proves V-MOT > VBUS), then BT_BUS HIGH with P5 kept HIGH (F.4, T5) |
| P1-3 | **Charger POR during regen-armed cruise latches a 100 mA clamp** because Q201 holds ILIM_HIZ LOW at the POR read | SLUSDV2C §7.3.4.3: pin read at POR, < 1.08 V -> 100 mA | **Fixed (documented, safe direction):** F.2 POR row; firmware sees REG19 = 0.10 A, flags harvest lost, re-qualifies at the next Idle -> Run; T-B-07 tests whether an EN_HIZ toggle re-reads the pin in Run |
| P1-4 | Governor vs selector escape: the fw v28 raw escape at `SHARE_GOV_I_FC_CEIL_A` 1.25 A would close BT_BUS and drop H2c mid-window | ino 3530 | **Fixed:** FR-14 keeps the 1.20 A arm drop below it and states the coordination |
| P1-5 | Raise/restore could dither on a modulated brake and flood I2C | T3/T4 have no hysteresis | **Fixed:** FR-24 (50 ms hold-off unless V-MOT > 20.0 V) |
| P1-6 | Loop barrier in the concurrent mode | Proof in F.3 from the `.sch` net list (VBT reaches VBUS only through D-BT-EN) and RT1987 §17 p.14 (disabled = isolated) | No defect. R8 residual stated |
| P1-7 | Raised ceiling loading the FC | Blank term `(FCCEIL OR H1)`; abrupt-stop pulse bounded by the inhibit latency | No defect; nuisance OC_FC possibility listed (J.2 item 5) |
| P1-8 | Early purge | UVB + VINDPM shed; firmware BT re-close only at >= 13.5 V (`busHotPlugUnsafe()`); else UV_BUS -> State 99 | No hot-plug path. Outcome measured by T-F-07 |

## Pass 2: electrical lens against the datasheets

Checklist: every input inside its recommended range; every logic input meets its edge-rate and threshold limits; every
output tolerant of the voltage it sees, powered and unpowered; every value traceable to `r3_calc.py`.

| ID | Finding | Evidence | Disposition |
|---|---|---|---|
| P2-1 | **RC filters (1 kOhm + 1 nF / 4.7 nF) in front of the SN74LVC3G06 inputs violate the input transition limit** | Every SN74LVC sheet used: "Input transition rise or fall rate 10 ns/V max at 3.3 V" (SCES364J, SCES363L, SCES201N, SCES487I, SCES217AA, Recommended Operating Conditions) | **Fixed:** capacitors removed; 1 kOhm series kept; 100 ohm source resistors at the carrier ribbon drivers; glitch immunity re-derived from R252 x Ciss(Q201) and C252: a 1 us release glitch lifts ILIM_HIZ to 0.31 V, below 0.75 V (H.13). Comparator outputs switch in 10 ns typ (SBOS300C §6.10), so no Schmitt buffer is needed |
| P2-2 | **eFuse IMON could overdrive Teensy pin 22**: 39.2 kOhm gave 2.85 V at I_OL max and up to 5.7 V in the 2 x I_OL region | SLVSE94G EC: IMON 25.66-30.14 uA/A, pin range 0-4 V; Teensy pins not 5 V tolerant (spec §3.2) | **Fixed:** R105 27.4 kOhm (0.764 V/A, 1.31 V at 1.72 A) and D102 BAT54 clamp to 3V3 after R129 |
| P2-3 | UVB first draft (105k/10.5k/715k) fell at 13.33 V and its band reached 13.70 V; acceptable but the hysteresis was larger than needed | `r3_calc.py` H.2 | **Fixed:** 100k / 9.88k / 1.10M: fall 13.60 V (13.24-13.96), rise 13.95 V (13.58-14.30); margin 0.16 V to the FC VINDPM floor, tested by T-B-13 |
| P2-4 | eFuse UVLO first draft (30.1k/47.5k) gave 16.7 V, which would keep the EVM dark at a 15.9 V bus | Eq.9/10 | **Fixed:** 1.00M / 86.6k / 49.9k: UVLO 9.99 V, OVP 27.3 V |
| P2-5 | Keep-alive first draft (1.00 kOhm) could hold VCHG at only 3.22 V, below the RT1987 UVLO-rising maximum 3.35 V | `r3_calc.py` H.10 | **Fixed:** 680 ohm: 3.63-4.46 V |
| P2-6 | SN74LVC3G06 outputs see REGN (4.8-5.2 V) when off | SCES364J: VO 0-5.5 V recommended, 6.5 V abs max in any state, Ioff | No defect (0.3 V margin) |
| P2-7 | TLV3012 inputs with V-MOT up to 33 V | IN+ = 3.04 V at 30 V; fail-safe inputs to 5.5 V with 499 kOhm limiting (SBOS300C §9.4.4) | No defect |
| P2-8 | I2C rise time over the 0.30 m ribbon with 10 kOhm pull-ups | t_r about 0.85 us at 100 pF (spec §3.2); 100 kHz limit 1 us | Marginal on paper; T-C-06 measures |

## Pass 3: integration, procedure and test-coverage lens

Checklist: every designator unique across MB, CR, EIB and EVM; every net in the wiring tables appears in the SVGs; every
uncertainty in the text has a test-registry row; the bench order goes off-board first; the CSV and CLAUDE.md texts are
exact.

| ID | Finding | Evidence | Disposition |
|---|---|---|---|
| P3-1 | **Designator collisions**: carrier R1-R8 collided with ruling IDs R1-R9; carrier R21/R23/R29/R40-R42, C1/C2/C5, D2, Q2/Q3, J1/J3/J4, U1/U2 collided with EVM parts of the same names | EVM BOM (SLUUCB5E Table 4-1): R21 127k, R23 100k, R40-R42, Q2/Q3 ACFETs, J3 SYSTEM, J4 VPMID, U1, U2 | **Fixed:** carrier parts renumbered 1xx (U101-U112, R101-R142, C101-C140, D101-D102, J101-J102), EIB parts 2xx (U201, Q201, Q202, R250-R254, C252, J201); doc and SVG generator updated together |
| P3-2 | FR-12 claimed a UVB readback that does not exist | B.3 readback list | **Fixed:** FR-12 states UVB is covered by T-C-03 and T-F-07 |
| P3-3 | `chargerHasPower()` semantics change: pin 38 now reads the board side of the eFuse | B.4 | **Fixed:** FR-23 (V_chg > 10.2 V and EFUSE_FLT HIGH) |
| P3-4 | Teensy pad state during reset unknown (i.MX RT1060 IOMUXC), so the 47 kOhm pull-downs are unproven | study §5.1 TODO | **Fixed:** T-D-01 pass criterion P5, QUAL, FCCEIL <= 0.4 V in reset and boot; fallback 10 kOhm |
| P3-5 | Uncertainties without a test row: MPN ratings marked TODO(verify); the 2N7002K Ciss assumed in H.13; the aux load | design E, H.13, H.12 | **Fixed:** T-A-05 (procurement check), T-A-03 extended (turn-on through R252), T-E-08 extended (aux load) |
| P3-6 | EVM JP7 puts VAC1 on the unused micro-USB J6 | Fig 4-5: JP7 USB_VIN to VAC1/VAC2 | **Fixed in the draft** (EM10) |
| P3-7 | Wiring SVG first render: battery leads crossed the EIB; labels overlapped | rendered PNG | **Fixed:** layout re-routed (generator) |

## Closing pass

Re-read the whole design for consistency with the fixes (designators in every table and both SVGs, the numbers in H against
the calc output, the transitions against the invariants, the registry against every "TODO", "UNVERIFIED", "typical only" and
"not specified" statement in the text). No new defect. Open items are the 61 registry rows of section I; none is a design
defect, each is a number or behaviour no primary document gives, with a pass criterion and a named fallback.

## Summary of design changes made by the loop

1. EIB input capacitors removed; 100 ohm ribbon source resistors added (P2-1).
2. IMON resistor 39.2k -> 27.4k and a BAT54 clamp (P2-2).
3. UVB, eFuse UVLO/OVP and keep-alive resistor values re-solved (P2-3..P2-5).
4. Designators renumbered (P3-1).
5. Pre-emption: selector-dwell bypass (P1-1) and the raised-burst variant (P1-2).
6. Firmware requirements FR-23 and FR-24 added; FR-12, FR-14, FR-15 amended (P1-4, P1-5, P3-2, P3-3).
7. Registry rows T-A-05 added and T-A-03, T-B-07, T-C-06, T-D-01, T-E-08 extended (P1-3, P3-4, P3-5).


## Review round 1 (independent reviewers + verifiers) and the r1 dispositions

53 findings, all verified real. "Applied" means applied as the finding or its verifier's better_fix proposed;
"Applied (alt.)" means the intent is met with a different implementation, explained in design section L. Every behavioural
change has a test-registry entry (design section I) and, for firmware, a host-test requirement (FR-22).

| # | Key | Sev. | Disposition | Where in r1 |
|---|---|---|---|---|
| 1 | preempt-fcc-btb-overlap | major | Applied (verifier order: P5, FCC+FCCEIL, VINDPM read-back before BT_BUS, BT_BUS, verify, P5); I-9; I-1/I-2 reworded; T6 fixed | F.4, F.5, FR-06/13/22, T-C-06, T-E-06 |
| 2 | eib-wireoff-releases-converter | major | Applied (alt.): two series switches (Q203 feed + Q201 hold, separate drivers), JP14 out, EVM R21 removed, R272 at R42 site, input pull-downs, far-end ILIM sense on pin 33 | B.6, C EM2-EM5, T-C-05 |
| 3 | qual-window-single-barrier | major | Applied: EN_CHG 0 + REG11 written first, QUAL exits, U111 SN74LVC1G123 one-shot cleared by P5N; F.2 I2C-dead row corrected; hang-in-QUAL row | B.1, F.2, F.5 I-5/T1, T-D-03, T-B-20 |
| 4 | p5-static-arm-hang | major | Applied: dedicated pin 21 heartbeat into U113; CE_DRV and ILIM_REL both ANDed with ARM_OK; Run-entry self-test; residual BT_BUS exposure recorded | B.1, F.2, FR-27/28, G.3, T-D-02, T-C-09 |
| 5 | permit-tap-failsafe-and-en-threshold | minor | Applied via U115 comparator + pull-ups/pull-downs | B.1, B.2, T-C-01b |
| 6 | comparator-divider-open-faults | minor | Applied: H1q gated by UVB, BAV199 clamps, FR-08d, F.3 row corrected | B.1, B.2, F.3, T-D-04 |
| 7 | uvb-blocks-raised-regen | minor | Applied: H2c = ... ((UVB . FCCEIL) + H1) | B.1, T-F-09 |
| 8 | btok-sense-wire-open | minor | Applied (1 MOhm, per the open-input verifier) | B.2, T-C-07, T-C-08 |
| 9 | regen-capability-ichg-bound | major | Applied: H.7 as min(), buck ICHG -6.5 %, eta_max 0.93, ICHG 3.10 A | F.1, G.1, H.7, T-B-19, T-E-11 |
| 10 | btbus-reclose-inrush-unquantified | major (uncert.) | Applied: H.6 transient, lever 3(i)/(ii) as operator ruling, FR-26 SCP-bounded rescue floor, T-F-08 | F.4, H.6, J.2 |
| 11 | efuse-out-schottky-missing | major | Applied: D103 3 A Schottky + C103 1 uF, T-C-04 three events, T-A-07 leakage | B.4, A.8 |
| 12 | ocfc-margin-traction-transient-fc-window | major (uncert.) | Applied: admission bound, upstream setpoint hold, peak-hold governor; U117 shed as DNP option; T-F-04b | FR-14, G.1, B.2 |
| 13 | ilim-band-leakage-omitted | minor | Applied (alt.: EVM R23 -> 49.9 kOhm as well) | H.4 |
| 14 | evm-c43-25v-vbus-ldo | minor | Applied: JP30 removed | C EM15 |
| 15 | btok-kelvin-wrong-reference | minor (uncert.) | Applied: T9 to SNS-BT GND/REF1, T-E-10 rewritten | A.4, A.6 |
| 16 | run-quiescent-draw-unaccounted | minor | Applied: H.15 line, ADC one-shot in cruise, T-B-04 total draw | H.15, G.1, J.1 |
| 17 | efuse-ovp-above-bq-rating | minor | Applied: OVP 23.12 V (22.61-23.63 V), 0.1 % divider | B.4, H.5, T-C-04 |
| 18 | carrier-copper-unspecified | minor | Applied: 2 oz, pour widths, vias, W8 second VIN+ link | A.3, A.8 |
| 19 | btb-sense-threshold-gap | major | Applied (verifier's inverted-input variant: BTB_OFF, POR-safe) | B.1, B.2, T-C-01b/c |
| 20 | open-input-failsafe | major | Applied (alt. for BTB: 1 MOhm at the comparator input); T2 via UVB in H1q; T9 via R143 | B.1, B.2, B.6, T-C-07 |
| 21 | readback-misses-evm-side | major | Applied (alt. /CE sense comparator; I2C on W7): pin 33 re-sourced, pin 8 /CE sense, FR-08b backstop, T-D-11, T-B-18 | B.6, FR-08/08b |
| 22 | raise-latency-i2c-budget | major | Applied: FR-07 normative, 2.7 kOhm pull-ups, 400 kHz, EEPROM deferral, worst-phase T-C-06 | FR-07, G.1, H.16 |
| 23 | latent-comparator-faults | minor | Applied: FR-08c (BT_OK vs pin 41), UVB latent statement + FR-08d, F.3 corrected | F.3, FR-08c/d |
| 24 | uvb-ref-drift-margin | minor (uncert.) | Applied: drift + CMRR in r3_calc; UVB re-trimmed (R115 104 kOhm), margin 0.33 V; T-C-03 at 0/60 C | B.2, H.2 |
| 25 | imon-clamp-leakage | minor (uncert.) | Applied: D102 removed, R129 10 kOhm + C129 1 nF; T-B-14 offset at 60 C | B.4, H.5 |
| 26 | btok-kelvin-reference | minor (uncert.) | Applied together with #15 plus R143 | A.6, T-E-10 |
| 27 | efuse-flt-unpowered-state | minor (uncert.) | Applied: FR-12 no longer checks FLT below 10.2 V; FR-23 order; T-C-04 ramp | FR-12, FR-23 |
| 28 | tb03-ce-pass-criterion | minor | Applied: /CE >= 3.0 V, gates >= 3.5 V; pull-ups 47 kOhm | T-B-03, B.6 |
| 29 | stale-designators-in-fixes | minor | Applied (R108/R123/R124, R141/R142, C252, Q201/Q202 in calc) | I, calc |
| 30 | pin34-wdog1b-pad | minor | Applied: WDOG1_B on pin 20 only, CSV note, host test | G.3, D.3, FR-29 |
| 31 | preempt-switch-conflict-latch | major | Applied with #1 (FR-13 term change stated) | F.4, FR-13 |
| 32 | preempt-bt-trcb-conduction | major (uncert.) | Applied per the verifier (two-state analysis; readiness without battery current; T-E-12; no "step BT share up") | F.4, T-E-06, T-E-12, T-F-06 |
| 33 | early-purge-refusal-band | major | Applied: purgeRescueOk() (12.0 V floor bounded by the SCP envelope), four outcomes, contradiction flagged | F.4, FR-26, T-F-07 |
| 34 | restore-threshold-vindpm-band | major | Applied: T3 level-sensitive, FR-24 deleted, T4 on charger state, false-restore guard, T-D-12 | F.5, T-G-02 |
| 35 | regen-capability-ignores-ichg | major (uncert.) | Applied with #9; FC-image row corrected; FR-25 CV derate | H.7, FR-25 |
| 36 | fr08-uvb-unobservable | major | Applied: dangerous-direction-only FR-08; FR-17 keyed on an H2c fall with other inputs unchanged | FR-08, FR-17 |
| 37 | raise-vindpm-unload-transient | major (uncert.) | Applied: staged T3 (IINDPM, ICHG, VINDPM 18.2 V, ratchet), T-B-12 current-source test, T-B-10 limit 1 ms | F.3, F.5, H.7 |
| 38 | purge-interval-load-dependence | minor (uncert.) | Applied: T-E-01 >= 20 intervals at window load; scheduler load bins / unlock on load change | F.4, T-E-01 |
| 39 | fc-window-por-latches-fc-clamp | minor (uncert.) | Applied: FR-30 flag + T9 re-qualify; T-B-07 FC-window POR | F.2, F.5 |
| 40 | t3-latency-blocking-i2c | minor | Applied with #22 | FR-07 |
| 41 | t2-bt-bus-ownership | minor | Applied: latch owns BT_BUS, selector gate release suppressed | FR-06, F.5 T2 |
| 42 | telemetry-ems-gaps | minor | Applied: chg_src, harvest-lost, counters, time-to-purge, margin | FR-20 |
| 43 | carrier-no-buildable-layout | major | Applied (alt.: B.8 + A.8 + PM0 gate, no Gerbers in-session) | B.8, A.8, D PM0, T-A-06 |
| 44 | eib-mounting-and-tp-placement | major | Applied: fabricated EIB on chassis, TP49, per-wire lengths, T-A-02 | A.1, A.5, A.7 |
| 45 | stale-designators-collide-with-evm | major | Applied; closing grep of bare EVM-range designators run (only rulings R1-R9, critic C3/C7 and explicit EVM parts remain) | I, calc, SVG |
| 46 | evm-c43-25v-on-input | major | Applied with #14 (EM25 bring-up note) | C |
| 47 | bom-mpns-incomplete | major | Applied: every line has a candidate MPN and quantity; decoupling designated; CT added; J102 replaced by a solder field; tap pins named; T-A-05 covers every line | E |
| 48 | rb2-designator-collides-with-mb | minor | Applied: carrier network R109-R119, C106-C109 | B.2, B.8 |
| 49 | duplicate-em-ids | minor | Applied: EM1-EM25 unique | C |
| 50 | tap-twisted-gnd-unterminated | minor | Applied: T7b at C-D6 pad 2, T17r at J2.29 | A.4 |
| 51 | registry-missing-pass-fail | minor | Applied: T-B-14, T-E-06, T-D-02, T-G-04 have pass/fail and actions | I |
| 52 | t1-t2-unprotected-power-taps | minor | Applied: R170/R171 at the joints; shared-T2 network solved | A.4, B.2, H.1 |
| 53 | doc-svg-number-mismatches | minor | Applied: bus max 16.39 V everywhere, SHDN 2.48-3.3 V, no EIB filters, NT1 Fig 4-5, pad placement restated | A.6, A.7, F.2 |

(Several issues were raised twice under different keys, e.g. #1/#31, #9/#35, #14/#46, #15/#26, #22/#40, #29/#45; about 45 distinct issues.)

### Round-1 closing pass (r1)

- `calc/r3_calc.py` re-run after every value change; the design's section H, B and F numbers were copied from
  `calc/r3_calc_out.txt` (H1 ratio 1.089, UVB fall 12.91-13.80 V, ILIM regen 1.33-1.76 A / FC 0.65-0.95 A, OVP 22.61-23.63 V,
  capability 21.8 W at ICHG 3.10 A, VINDPM_STAGE1 18.2 V, T_LEAD 100 ms, standby 42-60 mW).
- Both SVGs regenerated from `calc/make_svgs.py` (the generator carries the r1 netlist).
- Every test ID cited in the design is defined in section I (scripted check).
- No bare designator in the EVM range remains except ruling IDs (R1-R9), critic IDs (C3, C7) and EVM parts named in the EM table
  or with an "EVM" prefix.
- New defects found in the closing pass and fixed: R256 1 MOhm would not hold ILIM_HIZ below 0.75 V with worst-case leakage if
  EVM R23 opened (changed to 200 kOhm, clamps re-centred); C252 raised to 2.2 nF after the lower-impedance ILIM network made the
  1 us glitch reach 0.63 V; UVB fall nominal re-trimmed after the drift terms made the first r1 values overlap the FC VINDPM
  floor; H1 ratio re-trimmed (R111 442 kOhm) after the shared R171 load lowered it to 1.066.
