# Round 3 review-design loop: BQ25798EVM wiring, carrier and operating design (2026-11-05)

Subject: `docs/charger_bq25798_wiring_design_2026-11-05.md` (the design), `wiring_bq25798.svg`, `carrier_schematic.svg`,
`calc/r3_calc.py`, `calc/make_svgs.py`. Passes 0-3 and the closing pass below are the designer's self-review of revision r0.
**Review round 1** (end of this file) is the independent review: 53 findings (about 45 distinct issues), each checked against the primaries by a
separate verifier, applied in revision r1. **Review round 2** (after it) produced 44 verified finding keys (one blocker), applied in
revision r2. **Review round 3** (last) produced 34 verified finding keys (no blocker), applied in revision r3. Numbers quoted in
passes 0-3 are r0 values; the design document and `calc/r3_calc_out.txt` carry the r3 values.

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

## Review round 2 (independent reviewers + verifiers) and the r2 dispositions

44 finding keys, all verified real (about 38 distinct issues). Dispositions as in round 1; "Applied (alt.)" is explained in
design section L.2. Every behavioural change has a test-registry entry and, for firmware, a host-test requirement (FR-22).

| # | Key | Sev. | Disposition | Where in r2 |
|---|---|---|---|---|
| 1 | evm-jp14-feed-joint-floating | blocker | Applied (verifier): EVM R21 = 0 ohm link, JP14 shunt out, JP14 pin 1 removed; E2 on JP14 pin 2; section-L r1 rationale corrected | C EM3, A.5 E2, B.6, L.1, T-A-02, T-B-03 |
| 2 | reg14-write-reopens-extilim | major | Applied (verifier amendment): REG14 never written, read-only masked verify every 20 ms and before EN_CHG/QUAL edges, latched trip, token-gated single recovery write; hard converter-off qualified | G.1, FR-03, FR-08e, F.2, F.3, T-B-21, J.2 |
| 3 | efuse-out-schottky-missing-reopen | major | Applied (verifier amendment): two turn-off cases, D103 selection criteria with B340A fallback (DS13005), excursion accepted under SLVSE94G 9.5.1/11, T-C-04 survival, TVS branch deleted, calc label fixed | B.4, H.5, H.15, E, T-A-05, T-A-07, T-C-04, J.1 |
| 4 | w8-unfused-hot-lead | major | Applied (verifier): W8 and PM5 deleted, VCHGIN2 pad removed, fused fallback, layout rule, J.1 entry, T-F-12 | A.2, A.3, A.8, B.4, B.8, D.1, J.1 |
| 5 | fr08-hb-latency-false-trip | major | Applied (verifier amendment): HB_dead, TW_HB_MAX/TW_QQ_MAX from T-C-10, no step-8 mask, H.17 bands widened (C151 too), FR-22 timing tests | B.1, FR-08, FR-22, F.5 T1, H.17, T-C-10 |
| 6 | eib-pin8-backpower-unpowered-outputs | major | Applied (alt., L.2): CE_RB on pin 7 via the ROS pad; readbacks INPUT_PULLDOWN; EIB 3V3 on two conductors + R274 bleed; fault rows and T-C-05 rewritten | A.3, A.4, B.3, B.6, D.2, D.3, FR-01, T-C-05 |
| 7 | cr-3v3-single-tap-backpower | major | Applied (alt., L.2): MB RSDA/RSCL 2.7k (PM9), CR R145/R146 DNP, no pull-up on the CE readback net, carrier-rail detector FR-08f, T-C-07 T6 case | A.2, B.7, D.1, H.15, H.16, FR-08f, T-C-07 |
| 8 | pin8-encoder-net-occupancy | major | Applied (alt.): pin 8 left alone; pin 7 after ROS removal; T-A-01b occupancy test | A.4, D.1 PM10, T-A-01b, J.2 |
| 9 | pin8-tap-on-encoder-net | major | Applied (merged with the above) | as above |
| 10 | preempt-drops-subh1-regen | major | Applied (verifier general rule): P5 stays HIGH in pre-emption/T5/T6, step B branches on H1 rb; T2 residual recorded; T-G-02b/c | F.2, F.4, F.5, FR-22, J.2 |
| 11 | preempt-p5-low-drops-brake-absorption | minor | Applied (merged with the above) | as above |
| 12 | rescue-predicate-checked-before-tdon | major | Applied (verifier): predicate at conduction with a 0.2 V/ms floor (always refuses today), per-tick abort as a test item, SCP gap = fault outcome, sentence deleted, T-F-07 numeric, T-E-06 abort cases | F.4, FR-17, FR-26, H.6, T-E-01, T-E-06, T-F-07 |
| 13 | setpoint-hold-conduction-deadlock | major | Applied (verifier): readiness release, derived T_HOLD_MAX, slew-limited timeout, selector kept disarmed, telemetry | FR-14, F.5 T5, T-F-04b |
| 14 | t2-btbus-open-without-fc-conduction | major | Applied (verifier): live FC survivor, firmware BT-cut predicate, post-drop check, latch owns FC_BUS HIGH, FR-22 T2 matrix, T-C-06 entries | F.5 T2, FR-06, FR-22, T-C-06 |
| 15 | warm-response-pass-criteria-inconsistent | major | Applied (verifier): one budget with t_d, V-MOT peak <= 20.5 V primary, current-source rig, T-E-04 first | F.3, H.7, T-B-09, T-B-10 |
| 16 | telemetry-ems-gaps-reopen | major | Applied (verifier): ADC continuous in Run, I_charge = fresh IBAT, chg_q_mc / chg_e_in_mj counters, T-B-14b | G.1, FR-03, FR-20, H.15, T-B-14b |
| 17 | window-reopen-rule-limits-fc-duty | major | Applied (verifier): mid-interval re-open, single G test with hysteresis, churn bound, unlock exemption, duty restated as an upper bound | F.4, FR-14, FR-15, H.8, T-E-01, T-G-04 |
| 18 | chg-header-strips-10-12 | major | Applied (verifier): TSW-110 + TSW-112 strips | A.2, A.8, E, T-A-05, T-A-06 |
| 19 | carrier-no-buildable-layout-reopen | major | Applied (verifier): 3 x 8 field placed, SMT J101, bottom keep-out, area budget, double-sided 4-layer CR | A.1, A.7, H.18, E, T-A-06 |
| 20 | bom-resistor-mpns-out-of-range | major | Applied (verifier): TNPW0805 for R102/R109/R111/R114; R116 10.0 MOhm, H.2 re-solved | B.2, B.4, E, H.2, calc |
| 21 | evm-tp42-is-scl | major | Applied: TP41; UG text/schematic conflict noted; A.5 jumper positions from Fig 4-1 | C EM25, A.5, T-B-01 |
| 22 | tc04-out-spike-criterion-unattainable | major | Applied (merged with efuse-out-schottky-missing-reopen) | as above |
| 23 | btb-pullup-backdrives-en | minor | Applied: R119 10.0 MOhm (EN 0.15-0.30 V with the bodge open); T-D-01 extended | B.1, B.2, H.3, T-D-01 |
| 24 | h2c-h1-term-not-rgn-qualified | minor | Applied: H1R = H1 AND RGN (U118A) into X and RFC_OFF; T-F-09 REGEN-LOW case | B.1, B.3, B.8, D.3, F.3, T-F-09 |
| 25 | qual-clr-edge-bypasses-gate | minor | Applied: QQF = QQ AND FCCN (U118B); I-5 extended; single-fault row; T-D-13 | B.1, F.3, F.5, T-D-13 |
| 26 | ground-loops-parallel-returns | minor | Applied (alt., L.2): ribbon GND via R273 10 ohm, W7/W6/T7b/T17r CR-end shields, T7 omitted; T-F-11 | A.3, A.4, A.6, B.6, B.8, T-F-11 |
| 27 | evm-agnd-parallel-return | minor | Applied (merged with the above) | as above |
| 28 | run-quiescent-draw-unaccounted-reopen | minor | Applied: TS bias, EIB REGN pull-ups and the unspecified IC IQ lines; 55-78 mW; T-B-04 apportions | H.15, B.5, J.1, T-B-04, calc |
| 29 | evm-power-shunts-unsourced | minor | Applied: JP3/JP5 soldered links, JP4 shunt ordered, R13 + link in the CV drop | C EM11/EM12, E, H.11, calc |
| 30 | ina253-adc-offset-from-charger-return | minor | Applied: T-F-04c | I |
| 31 | t-a-04-criterion-not-datasheet | minor | Applied: SLUSDV2C 6.3 effective totals at 23.6 V | C EM14, T-A-04 |
| 32 | ilim-sense-threshold-above-hiz-vil | minor | Applied: R261 10.0 kOhm, threshold 0.59-0.65 V; T-B-03 ramp | B.6, H.4, D.3, T-B-03, calc |
| 33 | lvc-slow-edges-reset | minor | Applied (alt., L.2): exception stated, T-D-01 20-reset test, Schmitt fallback | B.3, T-D-01 |
| 34 | i2c-bus-recovery-missing | minor | Applied: bus clear in FR-07/G.1; T-D-03 random resets | G.1, FR-07, FR-12, T-D-03 |
| 35 | csv-h2-text-omits-fciok | minor | Applied: row 16 with FCI_OK and H1 AND REGEN | D.3 |
| 36 | csv-row16-omits-fciok | minor | Applied (merged with the above) | D.3 |
| 37 | early-purge-trigger-misattribution | minor | Applied: V_bus < 14.16 V or a V_fc onset required; unexplained permit drop path; T-C-11 | F.4, FR-17, FR-20, T-C-11 |
| 38 | fc-window-budget-vs-h20-pmax | minor | Applied (alt., L.2): stack-power cap in G, T-E-08 sweep to 1.35 A, Pi-commanded ceiling flagged as FR-32 | F.4, G.1, FR-32, H.12, T-E-08 |
| 39 | todo-outside-registry | minor | Applied: each TODO tied to a test (FR-31) | B.4, FR-07, FR-14, FR-31, T-A-05, T-C-06, T-F-04b |
| 40 | evm-input-cap-figure | minor | Applied: 50.4 uF nominal (+ C103 = 51.4 uF) everywhere | B.4, C EM24, H.6, calc |
| 41 | w7-gnd-termination | minor | Applied: twisted triple, GND bonded at the CR pad only, two crimps | A.3, E |
| 42 | p5-name-collision | minor | Applied: tap holes F01-F24; logic net CHG_ARM | A.4, B.3, B.8, SVGs |
| 43 | svg-netlist-designator-gaps | minor | Applied: R260/R261, decoupling designators and U118 in the SVG; R162 named; R160-R162, C124 as DNP lines | B.8, E, make_svgs.py |
| 44 | h15-3v3-load-understated | minor | Applied: 1.82 mA worst static | H.15, A.4 T6, calc |

**r2 closing pass (designer):**
- `calc/r3_calc.py` re-run (output in `r3_calc_out.txt` / `.json`); every H-table number in the design was re-checked against it
  (UVB 12.89-13.78 / 13.26-14.16 V, U203 0.590-0.652 V, BTB with the bodge open 0.149-0.296 V, Run draw 3.41-4.89 mA = 55-78 mW,
  3V3 1.82 mA, monostables 200-464 ms / 20-46 ms, CV 8.339-8.415 V, rescue sag limit 0.064 / 0.147 V/ms, warm-response budget
  0.41 / 0.99 ms).
- New defect found and fixed in the pass: the r1 A.4 sentence said both pins 7 and 8 were assigned while naming 8 as spare;
  corrected to "pin 7 assigned, pins 2 and 8 spare on encoder nets".
- The H.8 budget labels in the calc no longer mention a P5 LOW step (P5 stays HIGH in the r2 pre-emption).
- Both SVGs regenerated from `calc/make_svgs.py` (pin 7 readback via the ROS pad, F01-F24, U118, R273/R274, W8 removed, R145/R146
  DNP, EM3 0 ohm link, U203 0.59-0.65 V).
- Test-ID cross-check: every T-x ID cited in the design is defined in section I.

## Review round 3 (independent reviewers + verifiers) and the r3 dispositions

34 finding keys, all verified real (about 31 distinct issues; no blocker). "Applied (alt.)" is explained in design section L.3.
Every behavioural change has a test-registry entry and, for firmware, a host-test requirement (FR-22).

| # | Key | Sev. | Disposition | Where in r3 |
|---|---|---|---|---|
| 1 | t1-ce-check-before-regn | major | Applied (alt.): merged `regnExpected` predicate; T1 step 5 waits for the REGN marker; PG=1 + /CE LOW latches; T_REGN_MAX retry, 3 misses -> CHG_NO_REGN | F.5 T1, I-5, I-6, FR-04, FR-23, B.6, T-B-20, T-D-11 |
| 2 | fr08-powered-predicate-ignores-regn | major | Applied (alt.): same predicate; EN_HIZ shadow + timer restart; stale I2C fails toward the trip after T_REGN_MAX; non-latching charger-unbiased state; FR-08(a) not REGN-gated | FR-08, FR-23, B.6, B.7, T-B-11, T-B-22, T-C-04 |
| 3 | ce-sense-gating-before-regn | major | Applied (alt.): same predicate; FR-08f merged into FR-08(b) (FR-37 retired) | FR-08, FR-37, B.7, F.3, T-C-07 |
| 4 | ce-pullup-link-sense-divider-fails-low | major | Applied (verifier): R272 + R272b on separate joints/links on the EVM; R262/R263 kept | A.5, B.6, C EM2, H.19, T-A-02, T-C-05 |
| 5 | heartbeat-proves-loop-not-monitor | minor | Applied: CHG_HB toggled only by a completed 1 kHz monitor tick (stage mask); watchdog feed likewise | FR-28, G.3, B.1, D.3 row 21, FR-22 |
| 6 | btb-off-stuck-high-undetectable | minor | Applied (alt.): recorded latent; bench proof T-C-12; F.3 and FR-08(c) corrected | F.3, FR-08, T-C-12, J.2 |
| 7 | u203-stuck-held-latent-no-entry-test | minor | Applied: T1 step 6 pin-33 release proof | F.5 T1, FR-04, T-F-03 |
| 8 | early-purge-sag-asserts-h1 | minor (uncert.) | Applied: T3 qualified by V_bus not falling; T8 in I-4; F.4 step 1 restated; T-F-07 extended | F.4, F.5, FR-07, H.19, T-F-07 |
| 9 | t3-t4-fcceil-race | minor | Applied: worker re-asserts FCCEIL LOW before each raising write; T4 step 2 conditional in one critical section | F.5 T3/T4, FR-07, FR-22 |
| 10 | ina253-bt-common-cause | minor | Applied: FR-38 BT-sense plausibility; J.1 item 6 | F.3, FR-38, J.1 |
| 11 | efuse-in-spike-c102-undersized | major | Applied (verifier): C102a/b/c + D107 by default; IN-spike simulation; T-C-04 from 8 V | B.4, A.8, B.8, E, H.5, H.19, T-A-04, T-A-05, T-C-04 |
| 12 | cr-bottom-over-mb-power-traces | major | Applied (alt.): whole footprint controlled; SMT tap pads in place; bottom passives <= 1.0 mm outside the shadow; polyimide; overlay; DMM <= 10 V | A.4, A.7, A.8, PM4, H.18, T-A-06, T-F-12 |
| 13 | input-path-ir-drop-omitted | major | Applied (verifier): R_PATH_RG in the calc; adverse rows re-derived; physical series resistor in the bench rigs; T-F-13 | F.3, H.7, H.19, T-B-09/10/12, T-F-13, J.2 |
| 14 | mb-vchgin-vias-current-rating | minor (uncert.) | Applied: T-F-13 4-wire + thermal camera; via reinforcement as the fail branch | T-F-13 |
| 15 | t18-5v-tap-unprotected | minor | Applied: R172 10 ohm at the CO-5V joint | A.4, PM7, B.8, E, D.4 |
| 16 | btok-selftest-floor-overlap | major | Applied (alt.): FR-12 outcome split; R142 select-on-test | B.2, FR-12, H.3, H.19, E, T-C-03, T-E-10, T-F-02 |
| 17 | u203-threshold-ignores-sense-offset | minor | Applied (alt.): R258 100k -> 10.0k; pin-referred band in the calc | B.6, H.4, E, T-B-03 |
| 18 | csv-pin20-reservation-missing | minor | Applied: CSV row 20 reserved, row 19 note | D.3, D.4 |
| 19 | early-purge-fc-ridethrough-infeasible | major | Applied (verifier): ride-through deleted; State-99 ceiling sizes T_LEAD; step E keeps BT_BUS once closed; hot-standby option recorded | F.4, FR-17, T-E-01, T-F-07, J.1, J.2 |
| 20 | window-ignores-ems-intent-and-termination | major | Applied (verifier): rule (h), chgFull latch, FC_CHG_MAX_MS backstop, override reported | F.4, FR-05, FR-06, FR-20, FR-22, FR-39, T-B-15 |
| 21 | scheduler-unlock-on-load-starves-windows | major (uncert.) | Applied (verifier): model-dependent prediction, no load unlock; T-E-01 traction run; locked fraction in T-G-04 | F.4, FR-15, FR-21, T-E-01, T-G-04 |
| 22 | h1-asserts-on-bus-sag | minor | Applied with early-purge-sag-asserts-h1 (sag branch: FCCEIL LOW + VINDPM 18.2 V, chg_src sag) | F.5 T3, FR-20 |
| 23 | cr-power-pad-coords-on-pin-column | major | Applied (alt.): explicit pad coordinates; U101 at y 64.1; W1/W2 at y 61.2; W6/W7 SMT | A.3, A.7, A.8, T-A-06 |
| 24 | evm-jp13-regn-pin-stray-shunt | major | Applied (verifier): EVM R20 and JP13 pin 1 removed; T-A-02 two-terminal check; T-B-03 powered check | C EM3, A.5, B.6, D.4, T-A-02, T-B-03 |
| 25 | j101-unkeyed-ribbon-reversal | major | Applied (alt.): keyed unshrouded J101 (position 6 omitted, plug), pin-1 marks, T-C-13 | A.3, A.7, B.8, E, T-C-13 |
| 26 | tps26630-pwp-alternate-nonexistent | minor | Applied: fallback deleted | A.8 |
| 27 | todo-outside-registry-reopen | minor | Applied: TODO(calibrate: T-B-14b); FR-31 | FR-20, FR-31 |
| 28 | fr08b-label-collision | minor | Applied: FR-08b..e -> FR-33..36, FR-08f retired as FR-37 | G.2 and every cross-reference in A-K |
| 29 | bav199-clamps-backfeed-cr-rail | minor | Applied: rail residual 0.3-0.45 V stated; T-C-07 < 0.8 V with the bus energised | B.7, F.3, T-C-07 |
| 30 | r256-c252-agnd-landing-unspecified | minor | Applied: across JP21 pins 1-2; AGND meter check | A.5, A.6, C EM5, T-A-02 |
| 31 | evm-j3-j4-live-terminals | minor | Applied: J3/J4 desoldered or insulated | C EM7, T-F-12 |
| 32 | d103-fallback-contradicts-criteria | minor | Applied (alt.): class >= 40 V with IR first; B340A bench-only | B.4, E, T-A-05, J.2 |
| 33 | eib-layout-unbudgeted | minor (uncert.) | Applied: EIB 36 x 24 mm, A.9 layout table, H.18b, T-A-06 | A.1, A.9, H.18b, E, T-A-06 |
| 34 | u117-option-values-missing | minor | Applied (alt.): values + R161 select-on-test | B.2, B.8, E, H.19, T-F-04b |

### Round-3 closing pass (r3)

- `calc/r3_calc.py` re-run: new section H.19 (R_path, warm budget with R_path, static V-MOT maximum, false-restore guard, eFuse
  IN-spike simulation, /CE pull-up margins, U117 values, R142 select-on-test table, bus-sag H1 crossing); H.4 pin-referred
  U203 band with R258 10.0 kOhm; H.6 inrush with C102a/b/c (0.42 A); H.15 3.51-4.99 mA / 56-80 mW; H.17 QUAL coverage from the
  REGN marker; H.18 bottom area after the MB power-copper shadow; H.18b EIB area.
- MB layer-1 copper under the CR parsed from the `.brd` (A.7); pad coordinates chosen against it and the A.8 hole table.
- FR-08b..e renamed FR-33..36 throughout sections A-K (FR-08f retired as FR-37); sections L.1/L.2 keep the historical names.
- Both SVGs regenerated from `calc/make_svgs.py` (C102a/b/c + D107, R272b, R20/JP13 removal, R256/C252 at JP21, keyed J101,
  SMT tap pads, R258 10.0k, R172, U117 parts, completion-token heartbeat, FR-08(b) in place of FR-08f, J3/J4).
- Test-ID cross-check: every T-x ID cited in the design is defined in section I (new: T-B-22, T-C-12, T-C-13, T-F-13).

## Review round 4 (independent reviewers + verifiers) and the r4 dispositions

32 finding keys, all verified real (about 31 distinct issues; no blocker; i2-vs-preempt-stepb-failure-branch and
preempt-vindpm-failure-blocks-step-d are one defect). "Applied (alt.)" is explained in design section L.4. Every behavioural
change has a test-registry entry and, for firmware, a host-test requirement (FR-22 items (i)-(xiii)).

| # | Key | Sev. | Disposition | Where in r4 |
|---|---|---|---|---|
| 1 | hang-fc-window-r5-gates-r1 | major | Applied (verifier): FC windows gated on T-W-01 (window rule (i)); T-W-01 decisive; RTWDOG 50 ms; T-D-02(a) restated; residual on its own J.2 line | 0.1, 0.2, F.2, F.4, FR-05, G.3, T-D-02, T-W-01, J.1, J.2 |
| 2 | hang-fc-window-purge-reclose-death5 | major (uncert.) | Applied (alt.): purge-under-hang removed from the vehicle test; bench T-D-14 with the capture-11 envelope; watchdog below the minimum purge; ARM_OK pull on MOT_PWR not adopted | F.4, G.3, T-D-02, T-D-14, T-W-01, J.2 |
| 3 | i2-vs-preempt-stepb-failure-branch | major | Applied (verifier): I-2 barrier clauses, step D guard at max(A + 2 ms, P5 edge + 1 ms), VINDPM failure not a refusal, soft_layer_missing hold, four FR-22 cases | F.4 steps B/D/E, F.5 I-2, FR-22 (i) |
| 4 | i4-blocks-state99-under-h1 | major | Applied (alt.): I-4(a) inhibit-only signals, I-4(b) named fault paths; REGEN/FCC under H1 only inside a fault path | F.5 I-4, FR-04, FR-08, FR-19, FR-22 (ii) |
| 5 | fr12-idle-selftests-need-motpwr-btbus-low | major | Applied (alt.): part (a) in `busBringupTick()` (P0 floor/BT_OK before BT_BUS HIGH, P0-P2 ratio check); D-MT-EN check kept | F.2 Init, FR-12, FR-22 (iii), T-F-02 |
| 6 | charger-trip-in-window-leaves-bt-bus-open | major | Applied (alt.): T10 (both inputs opened first, no-conversion proof, BT_BUS via the pre-emption path, deadline State 99) | F.2, F.3, F.5 T10, I-2(c), FR-08..FR-36, FR-22 (iv), T-D-11 |
| 7 | hb-selftest-skips-ilim-leg | minor | Applied (alt.): T1 step 8b with a second QUAL pulse | F.5 T1, FR-04, FR-22 (v), T-C-10 |
| 8 | pin35-flt-floats-on-open-tap | minor | Applied (alt.): INPUT_PULLUP + R106 DNP; FLT plausibility checks | A.4, B.4, B.7, B.8, D.3, E, F.3, FR-01, FR-23, T-C-05 |
| 9 | eib-e1-regn-adjacent-to-ilim-feed | minor | Applied: empty pads around E1; bare-EIB isolation check | A.9, T-A-06, SVG |
| 10 | i2-btboff-precondition-unobservable | minor | Applied: I-2 sub-bus clause on EN read-back, turn-off wait, I_BT floor | F.5 I-2 |
| 11 | fallback2-dbtsq-disconnect-claim | minor | Applied: trade-off restated (reverse block lost) | B.5 |
| 12 | d107-tvs-crowbars-vmot-regen | major | Applied (verifier): VBR(min) >= 36 V, VRWM >= 30 V, Vc <= 60 V; C102b 100 V; T-C-04 < 60 V; T-A-05b; J.2 residuals | B.4, A.8, E, H.5, H.20, threshold stack, T-A-05, T-A-05b, T-C-04, J.2 |
| 13 | ov-batt-cv-margin-ignores-adc-error | major | Applied (alt.): interim VREG 8.32 V + calibration T-E-13 / FR-40; CV hold T-F-14; dwell only as noise hardening | G.1, H.11, H.20, FR-40, T-B-15, T-E-13, T-F-14, D.4, J.1 |
| 14 | ilim-clamp-por-adc-error-omitted | minor (uncert.) | Applied: T-B-23; register cap noted | H.5, T-B-23 |
| 15 | r172-0805-short-dissipation | minor | Applied: F101 fuse + R172 33 ohm 1206 | A.4, B.8, D.1 PM7, D.4, E, H.20 |
| 16 | cr-eib-3v3-feed-unprotected-short | major | Applied (alt.): R175 68 ohm 1206, R176/R177 200 ohm 0603, decoupling downstream | A.3, A.4, B.6, B.8, E, H.15, H.20, T-C-07, T-C-13 |
| 17 | ribbon-adjacent-short-ilimrelb-rfcoff | minor | Applied: conductors 9/10 swapped; adjacent-pair table; sweep | A.3, B.1, B.6, B.8, SVG, T-C-05, T-C-07 |
| 18 | tlv3012-ribbon-driver-short-current | minor | Applied: R264/R265 470 ohm | A.4, B.3, B.6, B.8, E, SVG |
| 19 | pin22-adc-keeper-imon-error | minor | Applied: INPUT_DISABLE; T-B-14 step | D.3, FR-01, H.20, T-B-14 |
| 20 | fc-window-raise-ignores-governor-floor | major | Applied (alt.): brake feed-forward 0.90 A (FR-41); figures corrected; floor kept on a tested assumption; false-restore guard as a state predicate | F.2, F.3, F.5 T3, G.1, FR-41, H.7, H.20, T-B-12, T-D-12, T-G-02, T-G-02b, J.2 |
| 21 | purge-lock-tolerance-exceeds-tlead | major | Applied (alt.): asymmetric band, PURGE_EARLY_MAX 55 ms static_assert | F.4, FR-15, H.20, T-E-01 |
| 22 | preempt-btbus-not-owned-through-purge | major | Applied (alt.): FR-15b topology invariant `fcPurgeExposure()`; pre-emption re-closes standing FC-only topologies | F.4, FR-15b, FR-20, FR-22 (ix), T-G-02b, J.2 |
| 23 | fr11-trips-on-concurrent-regen | major | Applied (alt.): one-sided, quiet-interval only | F.3, FR-11, FR-22 (x), T-B-14, T-G-02, J.1 |
| 24 | preempt-vindpm-failure-blocks-step-d | minor | Applied with #3 | F.4, F.5 I-2 |
| 25 | sag-path-no-return-to-raise | minor (uncert.) | Applied: 5 ms re-entry; T-F-07 case | F.4 step 1, F.5 T3, FR-17, T-F-07 |
| 26 | chg-src-misattributes-subh1-regen | minor | Applied: chg_src from V_rgn - V_bus; split counters | FR-20, T-B-14b |
| 27 | efuse-cluster-no-room-at-pad10 | major | Applied (alt.): U101 rotated, 1.27 mm J101/J201 + 0.635 mm cable assembly, region table | A.3, A.7, A.8, A.9, B.6, B.8, D.4, E, H.20, T-A-05, T-A-06, T-C-13 |
| 28 | svg-w5-pin6-legend-gnd | minor | Applied: legend and title | SVGs |
| 29 | bom-26awg-wire-quantity | minor | Applied: >= 5 m, two colours, per-gauge quantities | E, H.20 |
| 30 | w3w4-hole-vs-18awg-silicone | minor | Applied: 1.5 mm holes, insertion check | A.3, A.7, A.8, T-A-06, T-F-12 |
| 31 | evm-jp3-jp5-link-pin-rating | minor (uncert.) | Applied (alt.): links into the plated holes; pin rating + joint temperature as fallback | C EM11/EM12, T-A-02, T-A-05, T-B-16 |
| 32 | pm4-header-solder-sequence-ambiguous | minor | Applied: ordered PM4 | D.1 PM4, T-A-05, T-A-06 |

### Round-4 closing pass (r4)

- `calc/r3_calc.py` re-run: new section H.20 (integrated pre-raise race at IINDPM 0.30 / 0.90 A and 18.9 / 23 W, race-derived
  floor, false-restore excursion, PURGE_EARLY_MAX, OV_BATT error budget with VREG 8.40 / 8.32 V, D107 class margins, 3V3 limiter
  rails and short currents, R264/R265 short current, pin-22 keeper error, T18 fuse/resistor, 26 AWG quantity, RTWDOG vs purge,
  eFuse IN-side area); VREG 8.32 V encoding 0x0340.
- Both SVGs regenerated from `calc/make_svgs.py` (W5 legend pin 6 = KEY, 9 GND / 10 RFC_OFF, 1.27 mm ribbon, R175-R177,
  R264/R265 470 ohm, R106 DNP, F101 + R172 33 ohm, D107 33A class, C102b 100 V, E-pad order, carrier title r4).
- Test-ID cross-check: every T-x ID cited in the design is defined in section I (new: T-A-05b, T-B-23, T-D-14, T-E-13, T-F-14);
  FR cross-check: new FR-15b, FR-40, FR-41.

## Review round 5 (independent reviewers + verifiers) and the r5 dispositions

24 finding keys, all verified real (about 20 distinct issues; no blocker). Duplicates: rt1987-ovp-otp-restart-contradiction =
rt1987-ovp-latch-vs-autorestart-contradiction; ribbon-4-5-stat-sink-abs-max = ribbon-adjacent-short-stat-cedrv. Overlapping
clusters: the three brake feed-forward keys (#1, #12, #13) and the two flash/watchdog keys (#3, #14). "Applied (alt.)" is explained
in design section L.5. Every behavioural change has a test-registry entry and, for firmware, a host-test requirement (FR-22 items
(xiv)-(xix)).

| # | Key | Sev. | Disposition | Where in r5 |
|---|---|---|---|---|
| 1 | ff-brake-edge-clears-peakhold-on-ripple | major | Applied (alt.): magnitude-qualified FF (I_ff 1.0 A, same tick), peak-hold kept, ACK-gated reversal hold, reversal headroom | 0.3 r5-1, F.2, F.3 items 1-5, F.5 T3, G.1, FR-41, FR-22 (xiv), H.21, T-B-24, T-F-04b, T-G-02d, J.2 27/32 |
| 2 | preempt-deadline-outside-completion-token | major | Applied (alt.): FR-42 backstop with frozen deadlines, the shared function, a stage-mask term | F.3 table, F.4, F.5 I-4, FR-28, FR-42, H.21, T-C-14, J.2 34 |
| 3 | rtwdog-50ms-vs-blocking-flash-ops | major (uncert.) | Applied (alt.) with #14: FR-43 gate + bracket, watchdog windowed on the heartbeat, never State 99 | FR-07, FR-27, FR-43, G.3, H.21, T-C-06, T-C-09, T-W-01, T-W-02, J.2 33 |
| 4 | t10-fr08b-proof-relies-on-slow-decay | minor | Applied: proof (c) for FR-08(b); decay time quantified; the wrong sentence corrected | F.2, F.5 I-2, T10, FR-22 (xvii), H.21, T-D-11 |
| 5 | rt1987-ovp-otp-restart-contradiction | minor (uncert.) | Applied: FR-30/T9 restart-mode independent; T-A-05b extended | B.4, F.3 table, F.5 T9, FR-30, H.20, T-A-05b, J.2 28, K |
| 6 | fallback2-pack-unfused-on-w3-and-bridge-rating | major | Applied (alt.): one fused link C-D12 -> C-D11; T-A-05c pack DCIR | B.5, D.1 PM8, E, H.21, T-A-05, T-A-05c, T-B-09, T-B-16, T-F-12, J.2 36 |
| 7 | rt1987-ovp-latch-vs-autorestart-contradiction | minor (uncert.) | Applied with #5 | as #5 |
| 8 | imon-vchg-ground-offset-under-charge-current | minor (uncert.) | Applied: A.6 bullet, FR-11 threshold, T-F-15 with the Kelvin fallback | A.6, B.4, FR-11, H.21, T-F-15, J.2 35 |
| 9 | ichg-upper-tolerance-omitted-in-ratings | minor | Applied: 3.21 A in A.3, EM12, H.11, H.14, T-B-16 | A.3, C EM12, H.11, H.14, T-B-16 |
| 10 | ribbon-4-5-stat-sink-abs-max | major | Applied (R275 at the E7 end); short list complete; FR-44 | A.3, A.9, B.6, B.8, D.3 row 6, D.4, E, FR-44, H.15, H.21, T-C-05, T-C-07, T-C-13, SVG |
| 11 | eib-e6-e7-ce-stat-bridge | minor | Applied: empty positions around E7; isolation check | A.9, T-A-06, SVG |
| 12 | gov-cmd-proxy-abs-closes-window-on-brake | major | Applied (alt.) with #1: traction-only duty-weighted proxy, narrow BRAKE precedence, peak-hold not cleared on exit | F.4, G.1, FR-14(a), FR-41, T-F-04b, T-G-02 |
| 13 | ff-iindpm-step-overlaps-traction-ocfc | major (uncert.) | Applied (alt.) with #1: measurement-gated ramp, brake command unmodified, T-B-24 | F.3, FR-41, H.21(b), T-B-24, T-F-04b |
| 14 | flash-commit-stalls-hb-and-wdt-in-run | major | Applied (alt.) with #3 | as #3 |
| 15 | purge-fc-only-ridethrough-bag-evidence | major (uncert.) | Applied (verifier): load-dependent battery rescue, step-2 traction clamp, provisional sag constant, T_LEAD from P(rescue fails \| load) | F.4, FR-26, H.6, H.8, H.21, T-E-01, T-F-07, J.1 7, J.2 7 |
| 16 | efuse-cluster-no-room-at-pad10-reopen | major | Applied (alt.): courtyard-checked table, W1/W2 moved, SMA D103/D107, loop-inductance rules, 0402 pocket | A.3, A.7, A.8, B.4, B.8, E, H.18, H.20, H.21(k), T-A-05, T-A-06, SVG |
| 17 | pm4-header-solder-sequence-ambiguous-reopen | major | Applied: PM4 step 2b with recorded heights | D.1 PM4, T-F-12 |
| 18 | ribbon-adjacent-short-stat-cedrv | major | Applied (alt.): R275 instead of R130 = 1 k | as #10 |
| 19 | j101-mated-socket-envelope | minor (uncert.) | Applied: socket dims in T-A-05, mated dry fit in T-A-06, cable exit defined, fail branch | A.3, A.7, T-A-05, T-A-06, J.2 31 |
| 20 | evm-jp17-stray-shunt | minor | Applied: JP17 pin 2 removed; T-A-02 check | C EM1, D.4, T-A-02, SVG |
| 21 | b8-netlist-omits-cr-holes-pads | minor | Applied (alt.): rows and pinouts added; BAV199 pinning TODO(verify) (download refused) | B.8, K, T-A-05, J.2 37 |
| 22 | bom-polyimide-adhesive-unspecified | minor | Applied (alt.): sheet and RTV specified and on the BOM; cut-outs, not a drape | A.7, D.1 PM4, E |
| 23 | cr-end-strain-relief-anchor | minor | Applied (option 2): adhesive + chassis tie within 30 mm, pull check | A.3, E, T-F-12 |
| 24 | layout-table-dimension-gaps | minor | Applied: E-row span stated; W1/W2 pad 2.3 mm | A.8, A.9 |

### Round-5 closing pass (r5)

- `calc/r3_calc.py` re-run: new section H.21 (feed-forward threshold bounds, the measurement-gated ramp simulation, the reversal
  headroom, the backstop timing, the flash-stall vs watchdog figures, the rescue load bound, the T10 decay time, R275 short
  currents, the IMON offset sensitivity, the fallback-2 fault current and fuse sizing, the courtyard check of the CR high-y band
  with loop-inductance estimates); H.11 and H.14 at the ICHG upper bound; H.15 R107 through R275 (3V3 1.79 mA); H.18 re-booked
  (~963 mm²); H.18b with R275 (65 %).
- Both SVGs regenerated from `calc/make_svgs.py` (titles r5, W1/W2 coordinates, D107/D103 SMA, R275 in the STAT path, the
  12-position E-pad row, JP17 pin 2 in the EVM mod list).
- Test-ID cross-check: every T-x ID cited in the design is defined in section I (new: T-A-05c, T-B-24, T-C-14, T-F-15, T-G-02d,
  T-W-02); FR cross-check: new FR-42, FR-43, FR-44; FR-41 rewritten.

## Review round 6 (independent reviewers + verifiers) and the r6 dispositions

16 finding keys, all verified real (16 distinct issues; no blocker). "Applied (alt.)" is explained in design section L.6. Every
behavioural change has a test-registry entry and, for firmware, a host-test requirement (FR-22 items (xx)-(xxix)).

| # | Key | Sev. | Disposition | Where in r6 |
|---|---|---|---|---|
| 1 | vreg-corruption-no-fixed-pack-ovp | major | Applied (alt.): BQ29200 OUT tap T22 -> R178/D108/R179 -> U123 Schmitt -> OVN; U122 ARM_OK' = ARM_OK AND OVN into U114; FR-46 read-back, FR-47 latch; FR-40 corrected | 0.2, A.1, A.4, A.8, B.1, B.3, B.7, B.8, D.1 PM11, D.4, E, F.2, F.3, FR-40/46/47, H.22(a)(b), T-A-01c, T-B-25, T-F-17, J.1 11, J.2 39, SVG |
| 2 | dbtsq-short-unfused-pack-on-vchg | minor | Applied (alt.): F.3 row, FR-48 detection in Idle and in cruise; no baseline fuse | B.5, F.2, F.3, FR-12, FR-48, T-D-15, J.2 40 |
| 3 | cr-and-mb-battery-path-copper-sized-below-ichg | major (uncert.; verifier: minor) | Applied (verifier): 3.21 A basis, 2.0 mm 1 oz fallback, pin ratings, T-A-06c before PM4, PM4 steps 1a/1b, T-F-16 | A.8, D.1 PM4, E, H.22(c), T-A-05, T-A-06, T-A-06c, T-B-16, T-F-16, J.2 45 |
| 4 | tc04-in-spike-criterion-omits-mb-vchgin-ratings | major (uncert.) | Applied (verifier): three-point T-C-04 step 2, MB-end pass limits, D107 restated, H.5 MB-end row, damping fail branch | B.4, H.5, H.22(d), T-C-04 |
| 5 | imon-bypass-cap-against-datasheet | minor | Applied: C105 DNP; IMON calibration at 0.3/0.6/0.9/1.7 A; FR-11 band from it | A.8, B.4, B.8, E, FR-11, H.5, T-B-14, J.2 43, SVG |
| 6 | fcc-rgn-lvc-threshold-vs-rt1987-en-band | major | Applied (alt.): U119 FCC_OFF, U120 FCC_ON, U121 RGN_ON; R187 3.30 MOhm, R134 DNP; CSV rows 27/29/30/31/32; FR-01/FR-49 | A.4, B.1, B.2, B.3, B.7, B.8, D.2, D.3, E, F.3, FR-01, FR-49, H.22(h), T-C-12, T-D-01, SVG |
| 7 | pin38-39-adc-overvoltage-on-vmot-excursion | minor (uncert.) | Applied (alt.): injection recomputed (14-52 uA), FR-49 over-range rule, BAV199 fallback, bench-Teensy test | H (ratings), H.22(e), FR-49, T-C-15, J.2 41 |
| 8 | loop-budget-5ms-breaks-1ms-tick-deadlines | major | Applied (verifier): FR-45 timer domain, FR-07/FR-27/FR-28 restated, t_exec 4.0 ms, T-C-09 rows | F.4, F.5, G.1, FR-07/14/27/28/41/42/45, H.8, H.20, H.21, H.22(f), T-C-09, J.2 38 |
| 9 | purge-fc-only-ridethrough-bag-evidence-reopen | major | Applied (verifier): SAG_FLOOR noise floor, evaluation instant defined, rescue compiled out until measured, T-F-07b | 0.2, F.4, FR-26, H.6, H.21, H.22(g), T-E-01, T-F-07, T-F-07b, J.1 7, J.2 7 |
| 10 | chg-src-misattributes-subh1-regen-reopen | major | Applied (verifier): braking gate, learned offset + slope, `chg_q_mixed_mc`, `uncal` | FR-20, FR-22, H.22(j), T-B-12, T-E-05b, J.2 44 |
| 11 | ff-headroom-admission-contradicts-single-g-test | major | Applied (Option A, verifier refinements) | F.3 item 5, F.4, FR-14(a), FR-41(viii), H.21, T-G-02d, T-G-04, J.2 32 |
| 12 | ff-reversal-hold-unattainable-at-100khz | minor | Applied (both options combined) | G.1, FR-20, FR-41(vii), H.22(f), J.2 42 |
| 13 | cr-coordinate-convention-mirror-ambiguity | major | Applied (verifier) + `calc/pin_identity_check.py`; chamfer at the pin-11 corner | A.2, A.7, A.8, D.1 PM0, T-A-06, SVG |
| 14 | eib-e-lead-max-lengths-geometrically-infeasible | minor | Applied (alt.): re-ordered row, maxima from the rendered Fig 4-1, per-lead classes and pass/fail | A.5, A.7, A.9, H.22(i), T-A-02, T-A-06, SVG |
| 15 | t-a-05-stale-j101-region-dims | minor | Applied | T-A-05 |
| 16 | a6-w2-not-beside-star-pads | minor | Applied: W2 -> pads 14/15 pour rule; T-A-06 check | A.6, A.8, T-A-06 |

### Round-6 closing pass (r6)

- `calc/r3_calc.py` re-run: new section H.22 (VREG corruption by single-bit address errors, the BQ29200 input stage levels and
  delay, IPC-2221 copper and the MB VBT path resistance, the MB end of the eFuse IN spike in both models, the pin 38/39 injection,
  the timer-domain timing, the rescue predicate cases, the FCC_OFF/FCC_ON/RGN_ON thresholds and open-tap levels, the EIB lead
  lengths from the rendered Fig 4-1, the `chg_src` difference-channel error, the CR area re-book); H.8 lead table re-cut (t_exec
  from T_TICK_MAX, margin 17.6 ms); H.20/H.21 timing rows re-derived (T_HANDOFF_MAX 27.4 ms, T_BACKSTOP >= 77.4 ms, EN edge
  t_pred - 80.0 ms; PURGE_EARLY_MAX unchanged at 55 ms).
- `calc/pin_identity_check.py` added and run: the 22 CHG pads reproduce the A.8 table; column centre y 50.514.
- Both SVGs regenerated from `calc/make_svgs.py` (titles r6, U119-U123 and the OVN term, T22, C105 DNP, the r6 E-pad order, the
  outline-chamfer note).
- Test-ID cross-check: every T-x ID cited is defined in section I (new: T-A-01c, T-A-06c, T-B-25, T-F-17, T-C-15, T-D-15, T-E-05b,
  T-F-07b, T-F-16); FR cross-check: new FR-45 to FR-49; FR-01/03/07/11/12/14/20/22/26/27/28/40/41 amended.
