# Phase C fix round (fix1), 2026-11-15

This note records the fix round that followed the phase C checker (`check1`). The checker verdict was PASS_WITH_ISSUES,
with one major issue, five minor issues and one R2 identifier marked NOT_FIXED (R2-SIM-4). No board file changed in this
round. Scratch scripts and backups are in `C:/Users/ricky/AppData/Local/Temp/claude/phaseC/fix1/`.

## 1. Changes

### 1.1 Design document: the T10 proof (b) decay basis (major issue; R2-DOC-5 follow-up)

The checker found that F.5 T10 (doc_fw) gives the 16.0 -> 8.0 V decay as 0.083-4.39 s on the sim 5 basis. However,
T-D-11 and H.21 (doc_hw) still used the 55-181 ms hand estimate. The following edits apply in
`docs/charger_bq25798_wiring_design_2026-11-05.md`:

1. H.21: the live figure is now 0.083-4.39 s (0.083-1.38 s with an EVM draw at or above 0.391 mA; an RT1987 forward
   leak above 98.5 uA holds V_chg above 8.0 V), cited to `sim/efuse_decay/run.py` b_ode_t() through F.5 T10. The
   55-181 ms hand estimate is kept in superseded form, with TODO(recalc: H.21(g) on the sim 5 basis).
2. T-D-11 injection offsets: a fifth offset, t_pred - T_LEAD - (t_dec + 100 ms), is added. Here t_dec is the measured
   16.0 -> 8.0 V decay with proof (d) unavailable, TODO(calibrate: t_dec from the T-C-04 EVM Idle draw). The old
   "180 ms covers the 55-181 ms proof (b) decay" clause is superseded.
3. T-D-11 pass column: T10 completes on proof (b) or (d) when the injection precedes t_pred - T_LEAD by more than the
   decay. At a shorter offset without proof (d), the F.5 T10 step-4 controlled T7 with BT_BUS left open is a pass. An
   uncontrolled State 99 is never a pass. The old "in every case" and "no double-fault State 99" texts are superseded.
4. The r9-26 revision row (section 0.3) names this fix round and this note.

The F.5 T10 row itself was not changed. Its r9-26 paragraph already supersedes its own earlier 55-181 ms sentence.

### 1.2 Design document: J.2 item 26 (b) (minor issue)

The live clause "lies up to 0.69 V below the 22.28 V design clamp" is superseded, because the 22.28 V clamp rests on
the V_rgn premise (J.2 item 81). The restated clause: the OVP minimum, 21.588 V (sim 5 Table 1), lies inside the
21.35-23.10 V onset band (sim 2 sections 5.1 and 5.8.7). The conclusion (a nuisance OVP trip in a hard brake is
possible; T-C-04 step (e); J.2 item 74) is unchanged. J.2 item 74 stays an operator decision.

### 1.3 Sim 2 citations and the README pointer (R2-SIM-4 residue)

1. `sim/chopper/RESULTS.md` section 2.1 now carries the same tag-citation note as the other RESULTS files: line numbers
   refer to tag `charger-r8-pre-review-2026-11-14` (commit 014c745), and the simulated part values are unchanged in the
   current `gen/netlist.py` and `bom_2026-11-14/cr_bom.csv`. Checked: R102 845 kOhm, R103 64.9 kOhm and R104 51.1 kOhm
   are at current `gen/netlist.py` lines 129, 134 and 135 (R102 MPN ERA-6AEB8453V after D-82; the value is unchanged).
2. Section 5.8 now cites "the R102, R103 and R104 entries of `gen/netlist.py`" instead of "lines 124, 129, 130".
3. `README.md` (documents table): "each RESULTS.md section 6" now reads "section 6 (sim 5: section 5)", matching
   `sim/README.md` line 10. Sim 5 section 5 is its conclusion and section 6 its limitations (checked).

### 1.4 Fab package READMEs, section 5 (minor issue)

`gen/fab_readme.py` changes:

1. A new constant `_SILK_CR_B` holds the CR silkscreen reason without D-85. The CR `B_Silkscreen.gbo` row now uses it,
   because D-85 touched F.Silkscreen only. The F row keeps the D-85 clause. The EIB rows are unchanged, because D-86
   touched both silkscreen layers.
2. A paragraph after the comparison table states the reasons for the files outside the Gerber and Excellon set.

Evidence for the paragraph (scratch check against `fab/cr_2026-11-13f` and `fab/eib_2026-11-13c`):

- `diff -rq` lists, outside `gerbers/`, the `.drl` files and the zip: README, assembly BOM, position file and iBOM,
  the `docs/` PDFs, STEP and netlist, the drill-map PDFs and Gerbers, the KiKit outputs and both reports.
  `reports/npth_check.txt` is new.
- Position files: CR 79 rows and EIB 33 rows; every reference, footprint, X, Y, rotation and side is identical. The
  Value field differs on 13 CR rows and 5 EIB rows (for example C110 "100nF 50V X7R" to "100nF 100V X7R").
- Assembly BOM: Value, MPN and Manufacturer differ (for example C101 GRM188R71H223KA01D Murata to C0603C223K5RACTU
  KEMET). The ERC report differs in its date line only.

Both READMEs were regenerated with the pcbnew venv python (the miniforge python lacks `shapely`):
`gen/fab_readme.py cr 2026-11-14 fab/cr_2026-11-13f` and `gen/fab_readme.py eib 2026-11-14 fab/eib_2026-11-13c`.
The diff against the previous READMEs is exactly the B_Silkscreen cell (CR) and the new paragraph (both). Neither zip
contains the README. No Gerber, drill, BOM or position file was regenerated or touched.

### 1.5 EIB title block (R2-EIB-4 item 5; minor issue)

The title blocks were not changed. `eib/eib.kicad_sch` reads rev "r8-capture-1", 2026-11-11, and `cr/cr.kicad_sch`
reads rev "r8-capture-2", 2026-11-12 (`gen/sch.py` line 241). A regeneration would change the package schematic PDFs
and the netlist date lines and needs ERC/DRC parity and a re-export. That cost is not justified for a title-block
string tonight. The residual is now in the HANDOFF.md 2026-11-15 residual list, with the procedure (a `gen/sch.py`
rev/date edit, a schematic-only regeneration, the step 10 checks and the step 11 export).

### 1.6 Companion: superseded quotes (minor issue)

`docs/charger_bq25798_custom_board_2026-11-10.md`: T-B-19, section 8.1 item 14 and L-8 now carry the superseded
"healthy chopper band" text in the form (**Superseded 2026-11-15, review R2-SIM-6, an onset, not a V-MOT ceiling:**
"..."). The old texts were taken from the companion agent's backup
(`phaseC/companion/companion_backup.md`). The r4 revision row now says that this fix round adds the quotes.

## 2. Not done

- The README Table 11.4 / 7.3 cells over 25 words (records agent report) were not split. The checker states that the
  meaning is unchanged, and splitting table cells in the records risks a collision with no gain tonight.
- The F.5 T10 row keeps its earlier "takes about 55-181 ms ... a trip in the last 55-181 ms" sentence, which its own
  r9-26 paragraph supersedes in the same row.

## 3. Verification

- Table rows: every changed table row in the design document and the companion has the same pipe count as before.
- `grep "55-181"` in the design document: every remaining occurrence is a superseded quote, the F.5 T10 history
  sentence or the r9-26 revision row.
- No board (`*.kicad_pcb`, `*.kicad_sch`, `*.net`), BOM CSV, Gerber, drill or forbidden file was edited.
