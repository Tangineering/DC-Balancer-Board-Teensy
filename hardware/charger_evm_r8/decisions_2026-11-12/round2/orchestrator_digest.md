## dec2-eib (local_496e36b0) - reported 2026-11-12
1. Fab status: Not ordered; fab/eib_2026-11-11 needs operator review before order.
2. Sense branch: DNP in place. Copper unchanged; regenerate eib-bom.csv / eib-pos.csv with DNP flags. Accepted: R263 unfitted -> R272+R272b double-open leaves /CE floating, latent, T-C-05 metering only.
3. U204 build-time check: Do not fit (fitting needs R262/R263; R263 pulls /CE low in the double-open fault; conflicts with J101.13=GND). T-C-05 metering of R272/R272b is the build check. dec2-gate told.
4. J101/W5: 2x7, pins 11/13 NC. 2x5 rejected. Note: 9 GND adjacent to 10 RFC_OFF -> 9-10 short ~33 mA via R132 100R, above LVC IOL; B.6 :1847 calls it safe - fix.
5. Fallback (iii): re-open as TODO, failed only on E4; lead-length re-check E1/E2/E3/E5/E7; only if MS2 forces fallback.
EIB DNP: U203 U204 C203 C204 R258-R265; E4/E6 leads not fitted. Fitted: U201 U202 Q201-Q203 R250-R257 R266-R271 R273-R276 (split BOM line 18: R274 vs R258/R260/R261) C201 C202 C205 J201 E1 E2 E3 E5 E7 E8. EVM R272/R272b stay.
J101 (CR 2x7): 1 3V3, 2 3V3, 3 GND, 4 STAT, 5 CE_DRV (P5 via R130), 6 KEY, 7 REL_A, 8 REL_B, 9 GND, 10 RFC_OFF, 11 NC, 12 GND, 13 NC, 14 GND. J201.11/.13 end on DNP R265/R264 pads. CR nets deleted: R125, R148, ILIM_SENSE, CE_SENSE.
TODOs: regen EIB BOM/pos + fab README; B.6/B.7/B.8/B.9/H edits per ramifications/eib.md s6-8 (11/13 NC; double-open row = /CE floating latent T-C-05); TODO(verify SLUSDV2C IIN_BIAS_CE direction); TODO(calc) H.4 w/o R258/R259, H.19 w/o R262/R263 load, retire H.20 R264/R265 clause; 9-10 short current vs LVC limits (B.6:1847); fallback (iii) lead re-check conditional on MS2 (A.7/H.23(l)); EM1/EM5 edits; T-B-03 retires; T-C-05/T-C-07/T-C-13 re-scoped.

## dec2-fwrules (local_fe85f5db) - reported 2026-11-12; record: shared notes folder dec2_firmware_rules_2026-11-12.md
1. T_QUAL_MAX 0.46 s latching; FR-04/I-5; independent FR-45 1 kHz backstop from QUAL rise; overrun -> QUAL/P5/REGEN LOW same tick, CHG_QUAL_OVERRUN latch, regen arming refused until Idle. J.1 R3 exception for IQ_VBUS (~3-5 mA typ, no max), bounded per Run entry by T_QUAL_MAX, only by R5 under hang.
2. QUAL LOW, >=1 tick, then P5 HIGH; normative in T1/T9 and I-5; host test on every P5 path.
3a. Pin-34 ISR both edges; falling edge posts T4 at queue head; worker re-reads H1 rb at service. FR-07; safety no longer depends on T-B-07.
3b. T3 requires REGEN rb HIGH; FR-49 refuses FCC HIGH with REGEN LOW outside State 98.
4a. CHG_IIN vs I2C IBUS cross-check: IBUS > 0.2 A -> pin 22 agrees within T-B-14 tol; proof (d) only after lead-alive agreement same charger power cycle else T10 falls back to proof (b) V_chg decay; sustained disagreement latches CHG_IIN_LEAD, refuses FC windows. No Teensy-end pull.
4b. Accept both: open T13 (no brake, harvest lost, safe) and open T16 (reads no fault, r4) = J.1 accepted costs, no new check.
5. CHG_QUAL moves pin 10 -> pin 33. FR-49/T-D-01 NOT extended for pin 5/33 reset levels (operator: RT1987s already block boot-time power flow); QUAL slow-edge point moot. Pin 10 freed. CSV (operator edits), D.3, FR-01, TR s4 prepared rows change.
6. FC-window J, R5 required. fw v37 J retired. New J: stage 1 register commissioning (QUAL, image write/read-back, EN_CHG 0); stage 2 supervised FC-window charge via assertFcChargeEnable() (BT_BUS LOW, REGEN HIGH) with G1-G3 + trip latch re-keyed; all FC-window preconditions incl R5 + T-W-01.
7. Freed pins 10,16,17,21,23: INPUT_PULLDOWN early in setup() + boot read; any HIGH -> non-blocking UNEXPECTED_LEAD flag. Pin 21 keeps this until group 2 decides EWM_OUT_B. Pins 2/7/8 keep FR-01 ruling.
8. New FR-08(b) I2C latch trip: P5 LOW >= 20 ms and regnExpected, REG1C CHG_STAT != not-charging OR IBAT > 50 mA charge dir on 2 consecutive fresh reads -> latch, P5/QUAL/REGEN/FCC LOW detecting tick, T10 in a window. FR-44 stays slow cross-check. Sees SAFETY-2 only while converter released.
R5 (operator): built alongside the rest of the new-charger firmware, in the handoff after PCB design is done. (relevant to dec2-watchdog; not relayed - session waiting on user)
TODOs: edge-posted T4 exempt from 50 ms post-T3 hold-off (recommend exempt); T_QUAL_MAX vs T-B-20; IQ_VBUS max (SLUSDV2C 6.5); 0.2 A threshold/tol (T-B-14); FR-08(b) 50 mA/20 ms vs REG1C latency; G1-G3 re-key for J; pin-33 move through CSV/D.3/FR-01/TR rows.

## dec2-assembly (local_4bb8bc06) - reported 2026-11-12; record side-session-notes/local_5715d977-.../dec2_parts_assembly_2026-11-12.md
1. All SMT top, no fallback. One stencil/reflow; bottom = THT bodies + L4 GND; R104 to top; D-17/D-18/D-19/D-32 retire. If placement does not fit -> escalate to operator.
2a. Six 0402 -> 0603: R101 CRCW06038K06FKEA; R103 TNPW060366K5BEEA; R104 TNPW060349K9BEEA (top); R105 CRCW060327K4FKEA; R106s CRCW06031K00FKEA; C101 GRM188R71H223KA01D TODO(verify Murata).
2b. Single gates to DBV; one-section-used multi parts -> 1G DBV; 2+ sections stay DCT 0.65. Conditional on dec2-gate. Under 5-pkg mapping: U107 -> SN74LVC1G11DBVR; U106 -> SN74LVC1G32DBVR; U105 3G04 DCT w/ SAFETY-1 else SN74LVC1G04DBVR; U110/U118 stay DCT.
3a. C105, R145, R146 stay removed (no footprints).
3b. Retire B.5 (U112, C152, D101, R_KA); KEEP T-B-09 (H1*UVB release keeps regen-armed cruise); fail branch -> fallback 2 (fused MB link) or later keep-alive redesign; rewrite H.7.
3c. R134 stays removed (pull-down would make open T5 read FC charge proven off).
3d. Retire U117, R160-R163, C127, C124; no gate input reserved; FR-14(e) -> if T-F-04b fails, restrict FC windows to standstill/coast.
4. Refdes on silk (D-12a reversed); D-03 courtyard 0.10 -> 0.25 mm IPC nominal; regen footprints.
TODOs: DBV vs DCK/DCT pinouts (B.8 pin by pin); Murata C101; silk text size vs OSH Park mins; recompute area booking; edit D-03, D-12a, D-31 (none re-admitted), retire D-32/D-17-19; delete B.5, PM7 T18 part, DD:2131 keep-alive build line; rewrite FR-14(e), T-B-09/H.7; finalise logic list after dec2-gate.

## dec2-process (local_799bab0c) - reported 2026-11-12; record shared notes dec_process_2026-11-12.md
1a Audit scope: safety core + reopened L: B.1, B.3, B.6, B.7, F.2-F.5, G.2/G.3, J.1, every reopened L; plus A.8 adjacent-pair short table re-derived for new 10-conductor J-TAP order (check_1 s1.2 T5-T6 hole).
1b Method: hybrid - adversarial-doc-review on B.1, F.3, F.5, G.3, J.1, reopened L; self-review rest. Result = L.9 (audit run 002) replaces L.8.
2 H calcs: strip deleted parts from r3_calc.py / r7_calc.py, re-run, re-derive H.4/H.19/H.20/H.22 + any changed row; retire H.23 r7-outline geometry; new-outline geometry calc once generator exists. BEFORE audit.
3 Stale layout: git mv cr/interactive, cr/variants, cr/attempts, cr/*.png, routability_2026-11-12 -> hardware/charger_evm_r8/archive_r7_outline/ + README; update citing paths in LAYOUT_DECISIONS, MORNING_REVIEW, ROUTABILITY_OPTIONS, HANDOFF.
4 Routability: place, then FULL route-race (operator overrode the plain board-routing recommendation); no re-measure first.
5 Order: (1) decisions -> doc + netlist (sch.py, check_constraints, layout_cr list, LAYOUT_DECISIONS per reassessment Table 4); (2) H strip/re-run; (3) r9 audit; (4) new-outline generator IN PARALLEL with (3); (5) placement; (6) route-race; (7) DRC/constraints; (8) fab package.
CHECK-INS (operator): after doc+netlist update; after audit adjudication (netlist frozen after); after placement; before fab/order.
TODOs: archive move; H removed-part list depends on dec2-gate mapping; finalise reopened-L list vs six content decisions before audit brief; H.23 successor calc belongs with generator step; route-race needs region table, side flags, power geometry (reassessment s8).

## dec2-watchdog (local_45dc9315) - reported 2026-11-12; record notes folder dec2_hang_defence_2026-11-12.md
D2-1 R5 scope: all charger arming - QUAL, every P5 rise, every FC window require R5 build flag; Run disarmed does not. T-W-01 splits: T-W-01a (bench hangs w/o purge: QUAL HIGH, regen-armed brake, P5 HIGH, legit stalls) gates qual + regen; full T-W-01 (+T-D-14 purge emulator) gates FC windows. No charging of any kind until R5 fw + T-W-01a. Edits: R5 row, FR-04, FR-05, G.3 r4, crit path item 10, F.4 rule (i).
D2-2 No WDOG1_B tap; taps stay 10. G.3 DD:3023 -> R5 is the only hang defence.
D2-3 rtwdogShort = mainState 2 OR P5/QUAL/FC_CHARGE/REGEN HIGH (cmd or rb). FR-43 "NOT chgHbRunning" -> "NOT rtwdogShort" both predicates; FR-27 keep 5 ms vs t_WDT; FR-28 feed token only; FR-42/T-W-01 wording follows.
D2-4 BQ WD: 0.5 s + STOP_WD_CHG=1 w/ read-back in FR-03 image. T-B-08 settles: STOP_WD_CHG Fig 7-32 R-0h vs Table 7-20 RW; EN_CHG on expiry Table 7-20 vs 7-25; VREG on expiry Table 7-15 vs p.25 (8.4 V). T-B-08 measures 0.5 s tol. Fallback WATCHDOG=00 if expiry neither clears EN_CHG nor keeps VREG 8.32. Charger WD never a barrier. Read WD_STAT at reconnect, re-image.
D2-4b Pack OV during hang: accept without condition; J.2 residual up to ~51 ms charging with BQ-only OV (VBAT_OVP 8.57-8.82 V). FR-49/T-W-01 reset check of pins 5/10 declined. TODO(verify IMXRT1060RM) keeper vs 47k pull-down. NOTE MINE: QUAL moved to pin 33 (fwrules #5) - the "pins 5/10" wording must read pins 5/33 when applied.
D2-5 Pin 21 left free; freed-pin rule (group 3); edit G.3 DD:3021; IO CSV row 21 (operator).
TODOs: R5 fw + T-W-01a/T-W-01 (critical path for all charging); T-B-08 bench; pin keeper strength; confirm rtwdogShort false in State 99 phase 3 so sdOpAllowed admits SD close.

## dec2-gate (local_b4741544) - reported 2026-11-12; record C:\Users\ricky\AppData\Roaming\Claude\side-session-notes\local_5715d977-f614-4d80-acef-08440851bd11\permit_gate_decisions_2026-11-12.md
1. Agreement term adopted: FCCP = FCC_ON AND NOT FCC_OFF (U105 sec1 + U118B).
2. gate.md 5-LVC mapping: U105, U106, U107, U110, U118. Inventory mapping and all-DBV rejected.
3. CE_DRV buffered via U106A (CHG_ARM OR GND), push-pull into R130; R108 stays 47k.
4a. Gate outputs stuck HIGH / ILIM_REL CM: accept + J.1 + T-C-01/T-C-05 truth-table sweep every build. No readback tap.
4b. QUAL stuck HIGH: accept + J.1 + pin-order rule T6-T10 + host test SPI never claims pin 10 CS0 [NOTE MINE: QUAL now pin 33 per fwrules #5 -> host test re-target: pin 33 never claimed / pin 10 freed; 4b+4c two-latent loop recorded.]
4c. /CE stuck LOW: accept residual; rely on firmware current/switch-state measurement. No hw sense, no build /CE check. U204 DNP (confirmed by dec2-eib).
5. T5, T6, T10 pairwise non-adjacent (opposite-row counts; diagonals recommended); GND guards not mandatory.
Gate intent: P5N=U105 s2; FCCNN=U105 s1; H1U=U118A (H1*UVB); FCCP=U118B (FCC_ON*FCCNN); QF=U107 (QUAL*FCCN*P5N); GATE=U110A (H1U+FCCP); ILIM_REL=U110B (GATE+QF) -> R131A/B -> J101.7/.8; RFC_OFF=U106B (FCCN+H1U) -> R132 -> J101.10; CE_DRV=U106A (CHG_ARM+GND) -> R130 -> J101.5. Spare: U105 s3 only.
Re-derive: 4-5 ribbon-short row with push-pull CE_DRV; r5 U201 1A >= 2.72 V with U106A driver; T-D-01 scope point + Schmitt fallback move to U106A input.
Packages: gate says 4 DCT + 1 DCK (U107 1G11). Assembly rule "single gates to DBV" -> U107 SN74LVC1G11DBVR; U106 now uses BOTH sections so stays DCT (assembly's U106->1G32 DBV is void); U105 uses 2 sections -> stays 3G04 DCT. Reconcile: U107 DBV.
Fwrules suggestions (not decided): on FR-47(a) P5 drop also write EN_CHG=0 and verify current falls; CHG_IIN plausibility vs expected gate state.
TODOs: J.1 entries 4a/4b/4c + pair; build sweep defn for 6 gate inputs; T5 node short covered only by pin order (check_3 fw backstop not selected).

## dec2-tapconn (local_4d02c3dc) - reported 2026-11-12; record side-session-notes/local_5715d977-.../tap_connector_2026-11-12/dec_tap_connector_2026-11-12.md (+order.py, enum25.py)
Molex Micro-Fit 3.0 2x5 THT, hand-soldered last; cable assembly 2147581101 (far ends: operator's generic .100" crimps, no TSW). Tools: DuPont crimper only. Placement: design owner. Pin order accepted conditional on dec2-gate.
Cavity map (cols 1-5; physical pin numbers TODO verify Molex 43045/43025):
 row A: T1 T7b T17r T5 T13
 row B: T6 T2 T17 T16 T10
Polarization REQUIRED (180 flip puts T6 on T10). Every 2x5 keeps sev-2 pairs T13-T5, T13-T10 (MCU reset + brake: U102 lifts FC_CHARGE EN ~3.0 V via R126 vs 10k bodge, or QUAL); readback catches outside reset; T-F-12 before power-up. T17r-T17 false proof(d) inherent.
Empty cavity guards better than GND (R175 at CR end).
Open-lead: fail safe T1 T2 T5 T10 T6(reconfirm); undetected T13, T16 (accepted fwrules 4b), T17 (fwrules 4a cross-check).
NOTE MINE: gate rule "T5/T6/T10 pairwise non-adjacent, opposite-row counts, diagonals recommended" - map has T5 (A4) diagonal to T10 (B5); orthogonal rule met, recommended-diagonal not. Flag at check-in. Also "pins 10 and 31 reset states" -> QUAL now pin 33.
TODOs: verify 2147581101 specs + mating 43045 header P/N, orientation, pegs; wire gauge vs R170/R171 joints C-D6/C-D2; twist pairs; TSW-101 BOM row shrinks; placement +x side, T2 short to C-D2 (y 69.9), within A.4 maxima, latch access, PM step unplug before lifting CR, THT tails in 11.05 mm gap; T-F-12 -> cavity check, keep R175 bypass check; update DD A.4, A.8, H.23(g), E BOM, LAYOUT_DECISIONS D-05, D-08, D-31.

