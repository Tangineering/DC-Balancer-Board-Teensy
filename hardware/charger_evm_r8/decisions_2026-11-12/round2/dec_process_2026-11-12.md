# Process decisions for the next CR design round (2026-11-12, operator, process session)

Source: DESIGN_STATE_2026-11-12.md section 4 item 7. No repo file edited, nothing committed.
Operator answers are the option labels the operator selected (quoted).

## 1a. r9 audit scope
Operator: "Safety core + reopened L (Recommended)".
= B.1, B.3, B.6, B.7, F.2-F.5, G.2 and G.3, J.1, every reopened section-L disposition (about 18, check_1.json item list),
plus the A.8 adjacent-pair short table re-derived for the new 10-conductor J-TAP pin order (check_1 1.2: T5-T6
common-mode short reproduces the SAFETY-1 release).

## 1b. Audit method
Operator: "Hybrid (Recommended)".
= adversarial-doc-review skill (Codex + finding-verifier + adjudication) on B.1, F.3, F.5, G.3, J.1 and the reopened
L items; a lighter self-review on B.3, B.6, B.7, F.2, F.4, G.2 and the A.8 table. The audit result replaces L.8 as the
certification (new L.9 "Final audit run 002 (r9)").

## 2. H calculations
Operator: "Strip, re-run, retire H.23 (Recommended)".
= remove the deleted parts (U104, U108/U109, U111, U113-U116, U121, U123/D108/R178/R179, T18/F101/R172, EIB
U203/U204/R258-R265, FCCEIL terms) from round3/calc/r3_calc.py and round4/calc/r7_calc.py; re-run both; re-derive
H.4, H.19, H.20, H.22 and any other row whose output changes; mark the r7-outline H.23 rows ((a)-(m), (s)-(u), (w),
the geometry parts of (y)) retired; add a new-outline geometry calc once the new generator exists. Runs BEFORE the
audit so the audit checks the new numbers.

## 3. Stale r7 layout work
Operator: "Move to an archive folder (Recommended)".
= git mv cr/interactive, cr/variants, cr/attempts, cr/*.png (placement and route images), routability_2026-11-12
(and the r7 routing study records) into hardware/charger_evm_r8/archive_r7_outline/ with a README naming the
superseding decision (plug-on outline, 2026-11-12); update citing paths in LAYOUT_DECISIONS, MORNING_REVIEW,
ROUTABILITY_OPTIONS, HANDOFF.

## 4. Routability
Operator: "Place, then full route-race" (NOT the recommended plain board-routing gate).
= no re-measure on the old outline or the reduced netlist; go straight to placement on the new outline, then run the
full route-race skill (reference at >= 4 seeds, diagnosis, tested change requests, design-owner batch).

## 5. Round order and check-ins
Order: (0) wait for the six content sessions (gate, watchdog, fw rules, EIB, assembly, tap connector);
(1) apply all decisions to the design doc and netlist (sch.py, check_constraints.py, layout_cr.py part list,
LAYOUT_DECISIONS retire/re-derive per the reassessment Table 4); (2) strip and re-run the H scripts;
(3) r9 audit; (4) new-outline generator; (5) placement; (6) route-race; (7) DRC and constraint check; (8) fab package.
Check-ins (operator selected all four): after the doc + netlist update (diff summary); after the audit adjudication
(fix approval, netlist frozen afterwards); after placement (images, before routing); before the fab package / order.
5b parallelism, operator: "Generator in parallel, placement after (Recommended)" = step 4 runs during step 3;
placement waits for the frozen netlist.

## Open TODOs
- Archive move and path updates are not done (decision only).
- Exact removed-part list for the H scripts depends on the gate-mapping decision (dec2-gate).
- The reopened-L list must be finalised against the six content decisions before the audit brief is written.
- New-outline geometry calc (H.23 successor) has no owner yet; belongs with the generator step.
- Route-race needs the new region table, side flags and power geometry (reassessment section 8) first.
