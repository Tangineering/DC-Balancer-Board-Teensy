# Phase B notes: companion document (2026-11-14)

## 1. Scope

This note records the update of `docs/charger_bq25798_custom_board_2026-11-10.md` (the custom charger board document,
CCB) to the review of 2026-11-14 (`REVIEW_2026-11-14.md`, cited as [VR]), the CR simulations and the Phase B decisions
of 2026-11-14. The wiring design document was not edited. No board, BOM, netlist, simulation or firmware file was
edited.

## 2. Files changed

| File | Change |
|---|---|
| `docs/charger_bq25798_custom_board_2026-11-10.md` | 36 scripted replacements and three follow-up corrections (72 insertions, 32 deletions in `git diff --stat`); revision r3 |
| `hardware/charger_evm_r8/update_2026-11-14/notes_phaseB_companion_doc.md` | This note (new) |

The edit script and a copy of the pre-edit document are in the scratch folder
`C:/Users/ricky/AppData/Local/Temp/claude/update_2026-11-14/phaseB/companion_doc/` (`apply.py`, `before.md`).

## 3. Changes and evidence

Line numbers are those of the edited document. Superseded text is kept in the form
"(**Superseded 2026-11-14, VR-1, invalid V_rgn / 0.8505 conversion:** "old text")".

### 3.1 VR-1 premise lines ([VR] §4.1 list)

| Pre-edit line | Edited line | Change | Evidence |
|---|---|---|---|
| 24 | 24-29 | Constraint 2 restated: true V-MOT not measured; the 21.2-21.5 V / 21.98-22.28 V figures superseded; 18.2 V reading = 23.4-25.2 V true under the knee sink; healthy chopper 21.35 / 22.12 / 23.10 V; as-built trip 29.3-32.4 V or never; TODO(calibrate: [VRGN] §7.6) | [VR] §4.1 lines 982-994; sim 2 RESULTS §5.1 Table 5.1 (`results_static_iv.csv`), §6 item 1 |
| 577-578 | 582-585 | Keep-out voltage restated: healthy band 21.35-23.10 V; as built up to 29.3-32.4 V or the VESC cut | sim 2 Table 5.1, §6 item 3 |
| 652 | 659-661 | Efficiency gap restated: the chopper holds V-MOT at 21.4-23.1 V above the charger capacity; loss at 20-23.1 V TODO(measure) | sim 2 §5.2 |
| 1189 | 1215 (D2) | Reason (b) restricted to the TPS26630 band 22.61-23.63 V; TCKE1401NM band 22.19 / 23.19 / 24.41 V, 21.59-25.02 V with pin leakage; 18 V VAC_OVP basis restated from VINDPM 18.62-19.38 V and the chopper band; TCKE window 25.02-25.2 V | [WD] r9-20 (line 435); sim 5 RESULTS Table 1, §4.1; [WD] H threshold stack (line 3400); sim 2 Table 5.1 |
| 1204 | 1230-1231 | Table 2.2 lead-in restated to the chopper band | sim 2 Table 5.1 |
| 1242 | 1269, 1272-1274 | Table 2.3 row 22.28 V relabelled as a sweep point; added bullet: the OVP maximum bounds VCHGOUT; TCKE peak at 25.02 V TODO(recalc: [CALC]) | sim 5 Table 1 |
| 1293 | 1323 | Divider tops R309/R311/R314: V-MOT up to 23.10 V healthy, up to 29.3-32.4 V or the VESC cut as built | sim 2 Table 5.1, §6 item 3 |
| 1850 | 1880 | SW1/SW2 basis: 22.28 V no longer a bound; Table 2.3 peak 5.05 A at the OVP maximum; RMS TODO(recalc: [LC] §3) | Table 2.3 of the document |
| 2276 | 2305-2306 | VCHGOUT bound restated to the eFuse OVP maximum (23.63 V TPS26630, 24.41 V TCKE1401NM) | [WD] r9-20; sim 5 Table 1 |
| 2421 | 2451-2453 | As line 652 | sim 2 §5.2 |
| 3463 | 3493-3495 | VAC_OVP 18 V basis restated from VINDPM and the chopper band | [WD] line 3400; sim 2 Table 5.1 |
| 3832 (T-B-19) | 3864 | Points 21.5 V and 22.6 V kept inside the chopper band; r2 basis superseded; a 23.10 V point TODO(operator) | sim 2 Table 5.1 |
| 4844 | 4876-4877 | Measurement item 14 restated | sim 2 Table 5.1 |
| 4899 (L-8) | L-8 row | Measurement range 21.35-23.10 V | sim 2 Table 5.1 |

### 3.2 eFuse OVP / UVLO band (sim 5 (a))

| Location | Change | Evidence |
|---|---|---|
| §1.11.1, new paragraph "Status 2026-11-14 (O-17)" | Records the [WD] r9-20 change of U101 to the TCKE1401NM (R101 8.45 kOhm, R102/R103/R104 845 / 64.9 / 51.1 kOhm), its OVP band 22.19 / 23.19 / 24.41 V (21.59-25.02 V with pin leakage), its UVLO band 9.46-10.14 V (9.06-10.55 V), the 1.02 V excess over 24 V and the 0.18 V margin to 25.2 V, and the overlap with the chopper band; the CCB keeps the TPS26630 basis until O-17 | [WD] r9-20; sim 5 Table 1, §4.1; sim 2 §5.1, §5.2, §6 items 2-4; [VR] §4.2 |
| Table 1.14 criterion 9 | Note: 23.63 V is the TPS26630 maximum; TCKE1401NM 24.41 / 25.02 V exceeds 24 V | sim 5 Table 1 |
| D3 | Note: U101 change and TPS26630 stock (restock 8-Jul-2027); CCB eFuse open, O-17 | [WD] r9-20 |
| Table 2.4 VCHGOUT and PMID rows | TCKE1401NM bounds added | sim 5 Table 1 |
| Ledger row `efuse-ovp-above-bq-rating` | Note: TPS26630 band; TCKE1401NM band | sim 5 Table 1 |
| O-3 | Note: TCKE1401NM window 25.02-25.2 V | sim 5 Table 1, §4.1 |
| New O-17 (heading now O-1 to O-17) | CCB eFuse part; TCKE1401NM bands; criterion 9 and D2 (b) fail by up to 1.02 V; UVLO maximum 0.348 V above the 10.2 V FR-23 / FR-30 threshold; TODO(operator), TODO(recalc: D-67) | [WD] r9-20; sim 5 Table 1, §4.1 |

### 3.3 T-B / T-C test text and decisions (sim 1, sim 4, sim 5, Phase B decisions)

| Location | Change | Evidence |
|---|---|---|
| §1.11.2 item 2 (D303) | Note: CR hard short OUT -3.8 to -7.8 V for 2.9-11.2 us with any SMA Schottky, -20 to -51 V without; 0.8-1.3 V per nH; -1.12 V at zero L and RS; DNP condition not expected to be met; CCB case TODO(calc); leakage VR follows the fitted eFuse OVP maximum, TODO(recalc: D-67) | sim 1 RESULTS rev 2 §5.1 Table 5, §5.2; d103 decision |
| T-C-04 row | Superseded "the reduced-voltage order (8 V, 12 V, then full voltage) is unchanged"; 8 V cannot run (UVLO 9.7-10.1 V TPS26630, 9.06-10.55 V TCKE1401NM); lowest pre-step about 10.6 V; 10.6-12 V already -2.8 to -4.5 V on the CR; step (2) last; 2 Ohm fast-trip substitute (+0.82 to +1.23 V on the CR); CCB values TODO(calc) | sim 1 §5.3, Table 7, §6 items 1-2; sim 5 Table 1; T-K-06 row of the document |
| Deferred-gate table row "T-C-04 at 8 V and 12 V" | Superseded to "at 12 V" | sim 1 §5.3 |
| §4 BOM row "D303 Schottky, D307 TVS" | Note: CR orders STPS2H100A (bom_2026-11-14/cr_bom.csv line 11); MBRA2H100T3G is an operator question (IFSM 130 A vs 75 A; 1.2-1.3 V shallower OUT minimum; longer time below -0.3 V); both fail "VF at 3 A <= 0.5 V"; 130 A / 1 us criterion open | d103 decision and its verifier issues 1-2; sim 1 §5.1, §6 item 3; `update_2026-11-14/notes_phaseB_bom.md` line 15 |
| Netlist row C308 | Note: C108 = 470 pF is a CR assembly option (operator question); lost-T2 peak 0.86 V to 0.49 V; C308 follows the CR ruling | sim 4 RESULTS Table 5.5; t2caps decision; notes_phaseB_bom.md line 17 |
| T-D-04 row | Note: sim 4 ran only a permanent T2 open and one 50 us interruption (1.39 V, up to 28.3 us above 1.0 V at a 10 us skew); an unreviewed scratch re-run shows ILIM_HIZ above VIH with /CE LOW for 10-30 us interruptions; brief-interruption step TODO(verify: formal sim 4 re-run) | sim 4 Table 5.4, §5.6; t2caps decision and verifier issue 1 |
| FR-12 row (§5) | Note: sim 5 recommends FR-12(a2) k = 0.2 with dV_bus >= 2 V and an FR-12(b1) slope test; the CCB follows [WD] G.2 | sim 5 §5 items (b), (c) |

### 3.4 Records

| Location | Change |
|---|---|
| Status line | revision r3 (2026-11-14) |
| Table 0.9 | New row r3 |
| Table 9.1 | New keys [SIM1], [SIM2], [SIM4], [SIM5], [VR], [VRGN] |

## 4. Items not changed, with reason

- The R130/R131A decision (keep 100 Ohm) concerns the CR/EIB W5 wire-pad grids. The CCB has no J101/J201, ribbon or W5
  wires, so no CCB text changes. The STAT-to-CE_DRV short of the CCB ledger rows (lines 4679, 4687 before the edit)
  keeps its R475 basis.
- Sim 3 (comparators) reproduces the [WD] H1/UVB bands. Its findings (H1 fall 17.843 V against VINDPM_STAGE1 17.84 V,
  VR-4 0.08 not needed, T-E-07 0.36 V p-p) act on [WD] H.1 and T-E-07, which the CCB inherits unchanged.
- The 23.6 V DC-bias and leakage basis of C511/C512/C529-C531 (O-1, Table 2.2) and of D303 is kept: it is valid for
  the TPS26630. For the TCKE1401NM option, O-17 marks every 23.63 V figure TODO(recalc: D-67).
- The test points at 21.5 V in T-K-06, T-K-09 and T-K-10 are kept: they lie inside the healthy chopper band.
- The 19 TPS26630 mentions are kept: [VR] §6 (line 1312) records the CCB as an unpursued study design, so the eFuse part
  change is an operator question (O-17), not an edit.

## 5. Open items

1. O-17: the CCB eFuse part (TPS26630 or TCKE1401NM). TODO(operator).
2. The true V-MOT on a hard brake: TODO(calibrate: `docs/vrgn_measurement_error_2026-11-05.md` §7.6).
3. The CCB hard-short case with 5-20 nH of OUT copper and the 2 Ohm substitute short on the CCB: TODO(calc).
4. The Table 2.3 peak and the SW1/SW2 RMS current at 25.02 V for the TCKE1401NM option: TODO(recalc).
5. A T-B-19 point at the 23.10 V band maximum: TODO(operator).
6. The brief T2 interruption result rests on an unreviewed scratch re-run: TODO(verify: formal sim 4 re-run).
7. The edited document was not re-reviewed. Sentence-length compliance was checked by eye on the new prose only; table
   cells keep the established long-cell style of the document.

## Fix round 1 (2026-11-15, check1 issue 10)

C308 row: the C108 = 470 pF peak reduction (0.86 V to 0.49 V, [SIM4] Table 5.5) is stated for a permanent T2 open
only; a 10 us T2 interruption stays at 1.25-1.48 V ([WD] J.2 item 77). Details: `notes_phaseB_fix1.md` section 3.8.
