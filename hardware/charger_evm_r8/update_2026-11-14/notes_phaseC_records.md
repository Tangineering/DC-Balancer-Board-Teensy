# Phase C notes: records (README, HANDOFF, LAYOUT_DECISIONS, RESPIN, README figures; 2026-11-15)

## 1. Scope

This note records the phase C changes to the record files of `hardware/charger_evm_r8/`. No board, netlist, BOM,
fab package, design document, `CLAUDE.md`, firmware or IO CSV file was changed by this agent. Every text change is an
exact-match scripted replacement with a count check; superseded text is kept in the (**Superseded 2026-11-15,
reason:** "old text") form. CRLF line endings are kept on every edited file, and every edited table row has the pipe
count of its header (one pre-existing exception at `LAYOUT_DECISIONS.md` Table D-53b, unchanged from HEAD). Backups
and the edit scripts are in the scratch folder `C:/Users/ricky/AppData/Local/Temp/claude/phaseC/records/`.

## 2. Files changed

| File | Change |
|---|---|
| `LAYOUT_DECISIONS.md` | Section 1: new 2026-11-15 status table, counts and a 13-item operator list; the 2026-11-14 table relabelled as history. Section 2: table rows for `--add-missing` and the two phase C scripts; CR step 9 and EIB step 10 added; tool-residual paragraph. D-41, D-67, D-79, D-81 and D-84 amended (superseded form). New D-85 to D-92. Section 9.1 paragraph for D-85 to D-92. P-08 restated for the TCKE1401NM EN pin. Section 11 items 31, 32 and 34 amended; new items 35 to 45 |
| `README.md` | Section 1 (R2-DOC-1 and a 2026-11-15 state paragraph); Tables 2.1 and 2.2; section 2.1 figure note; section 5.3 figure note; Table 6.1 QUAL row; section 6.4 keeper bound; sections 7.1 and 7.4 with the new Table 7.3; section 7.5 row 22; sections 8.1, 8.3, 8.5 and 8.6; sections 9.1 to 9.4 and 9.7; section 11 intro, Table 11.1 strap row, Table 11.2, Table 11.4 rebuilt; Table 12.1 |
| `HANDOFF.md` | Title date; new 2026-11-15 status block; 2026-11-14 heading corrected and the "Records not changed" bullet replaced, with the missing line break; section 1 state rows (EIB, CR netlist, CR fab package, ordering BOM, IO CSV); D-range line; SSQ plating; row-22 interlock bullet; FW-0 bullet; section 3a parts-order list marked superseded; section 4 step 9a and step 11 |
| `RESPIN_HANDOFF_2026-11-13.md` | Section 1 amendment; amendment under Table 2.2 (TCKE1401NM bands with leakage); section 3.1.5 respin choice superseded; section 3.3 step J for both boards; section 3.3.3 step-J residuals |
| `sim/README.md` | One phase C pointer paragraph after the overview (sim_misc owns the rest) |
| `gen/readme_figures.py` | Five strings: U101 "TCKE1401NM + D103", W5 "nine wires (3 x 3 pads, 2 GND)", J-TAP "Micro-Fit mate from workshop stock", R131B and R132 "4.99 kOhm" |
| `figures/fig2_1_block_diagram.{png,svg}`, `figures/fig5_1_permit_gate.{png,svg}` | Regenerated with the miniforge Python; text-overlap check 0 problems on both |
| `update_2026-11-14/README.md` | New notes index |

## 3. Status per finding

| ID | Status | Where and evidence |
|---|---|---|
| R2-PWR-1, R2-DOC-3 | FIXED | D-67 bands restated with pin leakage (21.588-25.019 V OVP rising, 19.899-22.927 V falling, 9.055-10.548 V UVLO; sim 5 Table 1, sim 2 section 5.8); the 0.06 V sentence superseded by +0.348 V above 10.2 V; the 0.692 V / 1.019 V / 0.181 V margins computed from those bands. P-08 restated: EN open permitted, 0 V guaranteed margin (TCKE1401NM Table 10.2: VENUP 2.0-4.6 V against VEN_ON 2.0 V) |
| R2-DOC-14 | FIXED | D-79 J.1 item 5 sentence superseded; RESPIN section 3.1.5 respin choice superseded; README section 11 numbering stated ("README item n" in running text; Record columns name LAYOUT_DECISIONS items) and Table 11.4 Record cells prefixed "LAYOUT_DECISIONS item" |
| R2-DOC-0 (S2) | FIXED | README Table 11.4, HANDOFF status bullet, LAYOUT_DECISIONS section 1 list and section 11 items 35-44 now carry J.2 items 74 (rule before the Mouser order; lever (a) R103 68.1 kOhm / R104 47.5 kOhm: OVP rising 23.256-26.863 V, falling 21.439-24.614 V, UVLO 9.092-10.571 V; 0.66 V above 26.2 V; structural), 77 (option table J.2-1 from sim 4 Table 5.4d), 78, 82, 83, 84 (spare U101), 85, FW-0, FR-50, FR-51 and the opt-in SPARE lines |
| R2-DOC-1 | FIXED (README part) | README section 1 says r9-25 reconciled section E and r9-26 corrected its rows; old text superseded. The BOM README part was fixed by the bom agent |
| R2-DOC-2 | FIXED | HANDOFF heading, "Records not changed" bullet (residual list moved to the 2026-11-15 block), line break before the 2026-11-13 heading, section 3a list marked superseded by README Tables 11.2 and 11.4 |
| R2-DOC-6 | FIXED | Generator strings changed from `gen/netlist.py` lines 243-244 and `cr/cr.net` (R131B, R132 "4.99k 1%"); figures regenerated and inspected (D-92) |
| R2-DOC-7 (records part) | FIXED | No banner added to any older package. README sections 9.3, 9.4 and Table 12.1 name the current packages and list every older package as superseded; the four "once exported; until then" pointers superseded. The `gen/fab_readme.py` part was fixed by the board agent |
| R2-DOC-12 | RECORDED (open item) | README Table 11.1 strap row amended with the 2.77 A figures (10.2 C, 11.9 C; J1.10 perimeter 3.456 mm against 4.234 mm) and the 190 ms transient argument; reopened as Table 11.4 row and LAYOUT_DECISIONS section 11 item 40 (design J.2 item 82). LAYOUT item 2 itself is not edited; item 40 states that it reopens item 2 for the TCKE1401NM |
| R2-DOC-13 (README part) | FIXED | README section 7.1 amendment and new Table 7.3 (FR-01 CHG_IIN gate and INPUT_DISABLE, FR-12(a2) and (b1), V_chg for V_rgn, G.1 ADC masks, FR-02, FR-28, FR-50, FR-51); FR range FR-01 to FR-51. The QUAL row of Table 6.1 follows doc_fw (R2-FW-6) |
| R2-FW-6 (README part) | FIXED | README Table 6.1: QUAL raised at the first VBUS_PRESENT_STAT = 1, dropped at PG_STAT + 50 ms (FR-04) |
| R2-FW-10 (HANDOFF part) | FIXED | HANDOFF interlock bullet and section 1 IO CSV row name row 22 as the one pending CSV edit; README sections 7.5 and 9.7 likewise |
| R2-CRT-3 | RECORDED | D-90 and the notes index record that the orchestrator reverted the phase B banners on `fab/eib_2026-11-11/README.md` and `bom_2026-11-11/README.md` (`git diff` shows no change to either file) and that the banners on `DESIGN_STATE_2026-11-12.md` and `MORNING_REVIEW_2026-11-13.md` stay |
| R2-INT-4 (records instances) | FIXED | README Table 2.2 and section 8.1, HANDOFF mating-stack line: SSQ -G-S; D-41 amended |

## 4. New decision entries

D-85 (CR input-pair labels), D-86 (EIB E-pad identification) and D-87 (check and record corrections) follow the
board agent's drafts (`notes_phaseC_board.md` section 9) with regeneration and reversal bullets added. D-88 (netlist
Note fields; new date-stripped `cr/cr.net` sha256 `37ef45c1f4e43f35a7f57e51ff9c4c20eede1fd6acf164b62c121e09eed94e36`,
computed here with `grep -v "(date"`, the Table D-53b method, which reproduces the `014c745` value `65c7d980...`;
`gen/netlist.py` sha256 `2efe2225...`), D-89 (BOM set with SPARE lines), D-90 (packages written again; older
packages not edited; R2-CRT-3), D-91 (simulation re-runs that change recorded numbers: sims 1, 2, 4, the sim 3 log
and the sim 5 4.021 s figure) and D-92 (README figures).

## 5. Verification

- Every scripted replacement matched exactly once (README 41, LAYOUT_DECISIONS 17, HANDOFF 18, RESPIN 6, sim README 1).
- Constraint counts were read from `cr/constraint_check.md` and `eib/constraint_check.md` (CR 129 rows: 107 pass, 1
  pass with listed exceptions, 3 exemption, 18 information; EIB 6 pass, 2 information). DRC dates read from
  `cr/drc.rpt` and `eib/drc.rpt`.
- Lever (a), FR-50, FR-51 and J.2 items 74-85 were read from the design document as revised in r9-26 (lines
  4148-4262 and FR-50/FR-51 rows), not only from the agent summaries.
- `file` reports CRLF on all four record files after the edits (one `sed -i` on HANDOFF stripped CR; the file was
  re-normalized to CRLF with Python).

## 6. Left open and why

- LAYOUT_DECISIONS section 11 item 2 keeps its closure text; the reopening for 2.77 A is item 40, because item 2 is
  the record of an operator ruling.
- The older-package banners (R2-DOC-7) are not added, by rule.
- Every operator decision (J.2 items 74, 76-79, 82-85; FW-0; FR-50; FR-51; D103; R130/R131A; C106-C108; the W5 grid
  reorder; the SPARE lines) stays open; only the evidence and wording were sharpened.
- Style: several inserted table cells (README Table 11.4, Table 7.3) exceed 25 words per sentence in the question
  column; they quote the design-document J.2 wording.

## Addendum (phase C fix round, 2026-11-15)

HANDOFF.md residual list adds the schematic title blocks; README.md documents row pointer fixed. See `notes_phaseC_fix1.md`.
