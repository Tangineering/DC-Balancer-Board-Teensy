# Supporting files: custom BQ25798 charger board (2026-11-10)

This folder holds the supporting files of `docs/charger_bq25798_custom_board_2026-11-10.md` (the design document). The
design document defines the custom charger board (CCB), one board in the 22 Ag105 (CHG) holes of the MB rev 20260622. It is
a design document only: nothing is ordered, no firmware is changed and no KiCad capture is made.

## 1. Files

| File | Content | Cited in the design document as |
|---|---|---|
| `bom.csv` | Machine-readable BOM: 103 part lines plus the PCB line (review run 001 fixes applied). Columns include `class_IC` (I, S or M) and `carried_over_from_round3_refdes` | Section 4, [BOMGEN] |
| `make_bom.py` | Generator of the BOM and of the cost roll-up. It writes `bom.csv` and `bom_cost.json` | [BOMGEN] |
| `bom_cost.json` | Cost roll-up for builds 1, 2, 4 and 5 (option P nets the stencil once) (verified, round-3 allowance and new allowance classes; unpriced placement counts) | §4.5 |
| `ti_prices.json` | TI store prices of 2026-11-10, 1-99 tier, parsed from the TI part-details pages | [TI-PD] |
| `schematic_blocks.txt` | Figure 1.10, the block diagram of the CCB, as a separate text file | §1.10.1 |
| `mech_parse.py` | Parser of `references/Scale Car Board PCB 20260625.brd` (EAGLE XML): CHG pads, neighbours, MB copper under the footprint, foot spots | [MECH] |
| `mech_parse_out.txt`, `mech_parse_out.json` | Output of `mech_parse.py` | [MECH] |
| `digest_mechanics.md` | Mechanical facts extracted from the parse: pad table, neighbours, J-BL envelope, MB copper, foot spots, overhang ranking | [MECH] |
| `digest_ti.md` | Transcribed facts of SLUSDV2C (BQ25798 data sheet) and SLUUCB5E (EVM user guide): pin table, EVM designators, layer reading, rev-C changes | [TID] |
| `digest_study_reviews.md` | Operator rulings, requirements HR1-HR5, the round 1-6 finding table with tags, gate D-2 and the mechanical unknowns | [STUDY] |
| `layout_calc.py`, `layout_calc_out.txt` | Layout arithmetic: conductor widths, vias, losses, lumped thermal model, area budget, pin heating | [LC] |
| `sch_calc.py`, `sch_calc_out.txt` | Schematic arithmetic: inductor ripple and peak, VCHGOUT capacitance, inrush, PMID ripple current, header-pin currents | [CALC] |
| `make_ledger.py`, `ledger_table.md` | Generator of the 203-key review-finding ledger and its output | §7.A, [LEDG] |
| `tida_layout_parse.py` | Parser of the TIDA-050047 Altium outputs (`references/TI_BQ25798_design_files/TIDA-050047/altium_TIDM752/REV_A1`): layer stack and placements from the `.PcbDoc` text records, U1 pads, mask and paste openings, vias and pours from the Gerbers (gerbonara), drill sizes, the `.RUL` rule export and the schematic pin records. Positions are in the cell coordinates of §3.4. Run: `python -I tida_layout_parse.py <REV_A1 folder> [<png folder>]`; the optional second argument writes layer renders | [TLP], §3.4.6-3.4.8 |
| `tida_layout_parse_out.txt` | Output of `tida_layout_parse.py` (run without renders) | [TLP] |
| `pre_assembly_critique.md` | Critique of the section drafts before assembly, with the fixes applied. Items 22 and 23 became open items B-11 and A-2 of the design document | - |

## 2. Notes

1. The scripts and digests name the section drafts from which the design document was assembled. The drafts map to the
   design document as follows: `sec_mechanics.md` to §1.1-1.9; `sec_schematic.md` to §1.10-1.13 and section 2 (draft
   sections 1, 3, 5 and 10 to §1.10-1.13; draft sections 2, 4, 6, 7, 8 and 9 to §2.1-2.6; draft section 11 to §8.3.1);
   `sec_layout.md` to section 3; `sec_bom.md` to section 4; `sec_firmware_io.md` to section 5; `sec_tests.md` to section
   6; `sec_compare.md` to section 7.
2. The scripts and digests carry absolute paths of the working directory in which they were run. They are kept as a
   record of the calculations; re-running them needs those paths changed.
3. `bom.csv` and `make_bom.py` book 21 tap pins (open item B-11 is closed). In `bom.csv` the copper stacks are named ST1 and ST2,
   as in §3.1.3 of the design document.
4. TI reference material for the power stage (SLUSDV2C, SLUUCB5E and the TIDA-050047 reference design) is held in
   `references/TI_BQ25798_design_files/`, not in this folder.
5. `tida_layout_parse.py` reads the TIDA-050047 files as data only. It needs `gerbonara` (1.6.3 in the miniforge
   environment used) and, for the renders, `matplotlib`. The renders are not kept in this folder.

## Adversarial review (2026-11-10)

| File | Content |
|---|---|
| `ledger.md` | Review ledger, prefix CCB: 22 round-1 findings and 9 counter-review positions, all accepted; proposed registry row for `docs/reviews/README.md` |
| `run-001-2026-11-10.md` | Run record: the Codex deviation, round-1 findings verbatim, verifier verdicts, round-2 counter-review, adjudication table |
