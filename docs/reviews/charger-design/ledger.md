# charger-design review ledger (prefix CHG)

Target: docs/charger_bq25798_wiring_design_2026-11-05.md. Re-raise rule: a settled item reopens only with new evidence,
stated explicitly in the run record. Review rounds 1-7 of the design's own review-design loop are recorded in
`docs/reviews/charger_eval_2026-11-05/round3/review_loop.md` and `round4/review_loop.md` and in design section L; they count as
settled for this ledger unless new evidence is stated.

## Active findings

| ID | Status | Finding | Rationale |
|---|---|---|---|
| CHG-R1-01 | accepted (major) - applied r8 | F05-F17 / F06-F17 bridges: EN off only at >= 67.5 mA through U101 FLT (10 mA abs max); "only toward off" false | Recomputed with the design's 40 ohm driver and RT1987 VEN_F; fix R106s 1 kOhm behind F17 plus a bounded FLT-LOW diagnostic (run 001) |
| CHG-R1-02 | accepted (major) - applied r8 | T3 with FR-46 readbacks about 2.30 ms on the 100 kHz fallback vs the 1.5 ms FR-07 deadline | Byte count recomputed; fix write-first / read-back-after exception in G.1 and FR-46 |
| CHG-R1-D01 | accepted (major) - applied r8 | FR-43 flash/SD predicate unreachable in normal Idle (FC_BUS HIGH) and self-contradictory on State 99 | F.2 Idle vector and FR-43 text; fix battery-supported admission and separate flash / SD gates |
| CHG-R1-D04 | accepted (minor) - applied r8 | W1/W2 0.5 uH/m unsourced; thin PTFE gives 34.68 V / 141 A at 290 mm | Two-wire acosh formula; fix specify wire geometry and sweep L' |
| CHG-R1-03 | accepted (minor) - applied r8 | FR-48 Idle probe blocked by the FR-23 I2C gate | Text conflict; FR-48(b) still detects in the first cruise second; fix an explicit FR-23 exception |
| CHG-R1-04 | accepted (minor) - applied r8 | T1 step 8b leaves P5 LOW (fail-safe inhibit) and understates its budget | '123 CLR behaviour; fix split 8b, end-of-T1 P5/CE_DRV check, T-F-03 and T9 coverage |
| CHG-R1-D03 | accepted (minor) - applied r8 | B1 post height conflicts with the >= 5 mm jacket bead | Plan-run geometry; fix a redesigned riser with the full profile in T-F-12 |
| CHG-R1-05 | accepted (minor) - applied r8 | Foot-bond fallback breaks the gated bed and stiffness basis | Stack-up recomputed; fix taller fallback foot from the measured removed stack, repeat PM4 (2d) |
| CHG-R1-D02 | accepted (minor) - applied r8 | FR-12(b) 3 V / 2 s criterion vs 1.65-2.52 s decay below UVLO | RC recomputed; fix separate stuck-path test (12 V / 0.5 s proposed, to verify) |
| CHG-R1-08 | accepted (minor) - applied r8 | T-B-16 duty 30 % vs 0.6 s at 1 Hz = 60 % | Arithmetic; fix one waveform, inter-burst current, T-F-16 synchronised |
| CHG-R1-06 | accepted (minor) - applied r8 | Inverted superseded markers leave old instructions live | Text check; fix one live instruction per location |
| CHG-R1-07 | accepted (minor) - applied r8 | Hand calculations outside the calc outputs | All reproduce; traceability only |
| CHG-R1-A02 | accepted (minor) - applied r8 | TPS26630 datasheet missing from references/Datasheets | Cited values not checkable locally |
| CHG-R1-W01 | accepted (minor) - applied r8 | From B1 to A1 the W5 ribbon and the round-lead trunk overlap in plan; neither the vertical order nor the bundle thickness was stated (raised by the round-4 walkthrough, outside run 001) | H.23(t): W5 stays above the trunk and rests on it; stack top 20.750 mm above the MB (information, D-H) |

r8 application (2026-11-10): every row above is applied in design revision r8 (design 0.3 r8 block, L.8; `round4/work/r8_patches/`; `round4/calc/r7_calc.py` revisions 5-6). The run record `run-001-2026-11-10.md`, section "r8 application", lists the disposition of each ID.
