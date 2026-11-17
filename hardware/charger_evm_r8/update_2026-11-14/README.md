# Notes index: the 2026-11-14 round (phases A, B and C)

This folder holds the work notes of the 2026-11-14 round on the CR and the EIB. Each note lists the changes of one
agent, the evidence for each change and the items left open. `LAYOUT_DECISIONS.md` D-70 to D-92 record the decisions;
the notes hold the detail behind them. Table 1 lists the notes in the order of the round.

Table 1. Notes of the 2026-11-14 round.

| Phase | Note | Scope | Decisions |
|---|---|---|---|
| A | `notes_cr.md` | CR in-place edits after `REVIEW_2026-11-14.md` | D-72 to D-77 |
| A | `notes_eib.md` | EIB in-place edits after `REVIEW_2026-11-14.md` | D-70 to D-74, D-76 |
| B | `notes_phaseB_fix1.md` | Corrections after the independent check of phase A | D-78 |
| B | `notes_phaseB_silk_cr.md` | CR silkscreen fixes | D-78 |
| B | `notes_phaseB_silk_eib.md` | EIB board marking and reference placement | D-78 |
| B | `notes_phaseB_bom.md` | Netlist fields and the BOM set `bom_2026-11-14/` | D-82, D-83 |
| B | `notes_phaseB_export.md` | First export of `fab/cr_2026-11-14/` and `fab/eib_2026-11-14/` | D-77 |
| B | `notes_phaseB_wiring_doc.md` | Design document revision r9-25 and the firmware rules | D-79 to D-81 |
| B | `notes_phaseB_companion_doc.md` | Companion document revision r3 | none |
| B | `notes_phaseB_records.md` | README, HANDOFF, LAYOUT_DECISIONS and RESPIN records | D-84 |
| C | `notes_phaseC_board.md` | Silkscreen labels, check corrections and the second export | D-85 to D-87, D-90 |
| C | `notes_phaseC_bom.md` | Note fields, `sync_fields.py --add-missing` and the SPARE lines | D-88, D-89 |
| C | `notes_phaseC_sim_chopper.md` | Sim 2 section 5.8: fitted OVP bands, lever (a), U101 body diode | D-91 |
| C | `notes_phaseC_sim_permit.md` | Sim 4 section 5.6a: T2 interruption re-run and H1 latencies | D-91 |
| C | `notes_phaseC_sim_misc.md` | Sims 1, 3 and 5: tFASTTRIP re-run, current-limit dwell, run-log incident | D-91 |
| C | `notes_phaseC_companion.md` | Companion document revision r4 | none |
| C | `notes_phaseC_doc_hw.md` | Design document revision r9-26, hardware sections | none |
| C | `notes_phaseC_doc_fw.md` | Design document revision r9-26, firmware-facing sections | none |
| C | `notes_phaseC_records.md` | README, HANDOFF, LAYOUT_DECISIONS, RESPIN, README figures and this index | D-85 to D-92 (text) |

Phase B notes record two banners on `fab/eib_2026-11-11/README.md` and `bom_2026-11-11/README.md`. The orchestrator
reverted both banners in phase C, because dated packages and BOM folders are not edited (`LAYOUT_DECISIONS.md` D-90).
The phase C notes answer the findings R2-* of the second holistic review; the findings file itself is not in the
repository, and each note quotes the finding IDs that it answers.
