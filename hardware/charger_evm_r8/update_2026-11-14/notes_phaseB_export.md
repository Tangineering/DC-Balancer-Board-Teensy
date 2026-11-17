# Phase B, export: the 2026-11-14 fabrication packages and the final checks

## 1. Scope

This note records the export of the 2026-11-14 CR and EIB fabrication packages, the comparison of each package
with the previous package, the renders of both boards and the constraint checks. No board file was edited. The
older packages under `fab/` were not modified.

## 2. Files changed

| File | Change |
|---|---|
| `fab/cr_2026-11-14/` | New package, written by `bash gen/export.sh cr 2026-11-14` and `gen/fab_readme.py cr 2026-11-14 fab/cr_2026-11-13f` |
| `fab/eib_2026-11-14/` | New package, written by `bash gen/export.sh eib 2026-11-14` and `gen/fab_readme.py eib 2026-11-14 fab/eib_2026-11-13c` |
| `cr/constraint_check.md`, `eib/constraint_check.md` | Rewritten by `gen/check_constraints.py` (run from `gen/`, CRLF stripped); the content is byte-identical to the phase A reports |

Note that `fab/eib_2026-11-11/README.md` shows as modified in `git status`. That edit (a REVIEW DOC-8 "Superseded"
banner, file time 02:33:58) predates this export and was made by another phase B agent, not by this step.

Scratch files (scripts, renders, report copies) are in
`C:/Users/ricky/AppData/Local/Temp/claude/update_2026-11-14/phaseB/export/`.

## 3. Export checks

| Check | CR | EIB | Source |
|---|---|---|---|
| ERC | 0 messages | 0 messages | `fab/<board>_2026-11-14/reports/erc.rpt` |
| DRC with schematic parity | 0 violations, 0 unconnected pads, 0 footprint errors | same | `reports/drc.rpt` |
| NPTH copper gate | 6 NPTH holes, pass (nearest copper 0.254 mm at J102, 2.131 mm at MH1-MH4) | 2 NPTH holes, pass | `reports/npth_check.txt` |
| KiKit `fab oshpark` | complete | complete | `reports/kikit_oshpark.log` |
| KiKit `fab jlcpcb` / `fab pcbway` | "invalid literal for int()", no `bom.csv`; `gerbers.zip` and `pos.csv` written | complete | `reports/kikit_*.log` |

The CR KiKit assembly-BOM failure is pre-existing: `fab/cr_2026-11-13f/reports/kikit_jlcpcb.log` and
`kikit_pcbway.log` carry the same error. The package README states it and refers to `assembly/cr-bom.csv`.

## 4. Copper and pour state against git HEAD

`gen/pcbdiff.py HEAD:<board> WT:<board>` gives the following result for both boards:

- CR: 692 / 692 segments, 0 removed, 0 added, 818.7 mm; 420 / 420 vias; zones `GND_L1_fill` and `VCHG_L1`
  (F.Cu) changed in fill only.
- EIB: 332 / 332 segments, 0 removed, 0 added, 500.7 mm; 93 / 93 vias; zones `AGND_L1_pour` (F.Cu) and
  `AGND_L2_pour_1` (B.Cu) changed in fill only.

The footprints reported as "body changed" carry silkscreen, pin-1 dot, field and paste-margin edits only; the
Gerber comparison in section 5 confirms that no pad flash or track changed.

## 5. Gerber and drill comparison with the previous package

Every layer of the export list is present in both packages: CR 4 copper, 2 paste, 2 silkscreen, 2 mask,
Edge.Cuts and the job file; EIB 2 copper and the same other layers. Each file was compared as text (creation-date
lines ignored, `gen/fab_readme.py`) and, for the changed copper and paste layers, geometrically: the G36/G37
regions of each file were unioned and XORed with shapely (`gxor.py` in the scratch folder), and the non-region
content (apertures, flashes, strokes) was compared as text.

### 5.1 CR against `fab/cr_2026-11-13f`

| File | Result | Explanation |
|---|---|---|
| B.Cu, In1.Cu, In2.Cu, F.Mask, B.Mask, F.Paste, B.Paste, Edge.Cuts | identical | F.Paste identical: the D-69 U101 paste windows are unchanged |
| PTH, NPTH and both drill maps | identical | |
| F.Cu | different | Non-region content identical except one `%TA/%TD` attribute pair (one region fewer). Region XOR: 2.698 mm2 added at x 19.900-22.287, y 52.800-54.660 mm; 0.173 mm2 removed at x 19.767-20.152, y 52.627-53.970; 0.030 mm2 removed at x 21.844-22.287, y 52.627-52.800. J1 pad 18 (/VCHG) is at (20.998, 53.296), so every change lies within 1.7 mm of pad 18: the D-75 solid connection replaces the thermal relief. The other textual hunks (x 25-42 mm) are 1 nm vertex re-quantization with no XOR area above 1e-4 mm2. |
| F.Silkscreen, B.Silkscreen | different | Expected: the phase A and silkscreen-agent edits (pin-1 dots, J101 map, W-lead labels, board marking, reference moves) |
| job file | different | Expected: `Finish` None -> ENIG; stack-up colors and materials; outer copper 0.035 -> 0.0432 mm, inner 0.035 -> 0.0175 mm, prepreg 0.48 -> 0.1999 mm "FR408HR 2113" (x2), core 0.48 -> 0.9906 mm "FR408HR", mask 0.01 -> 0.0152 mm "PSR-4000BN" (D-76, `gen/cr_stackup.py`, `notes_cr.md` section 2.6) |

The inner layers did not change: VCHG has no inner-layer copper (`notes_cr.md` section 2.5), so the pin-18
connection changes only the F.Cu fill.

### 5.2 EIB against `fab/eib_2026-11-13c`

| File | Result | Explanation |
|---|---|---|
| F.Mask, B.Mask, B.Paste, Edge.Cuts, PTH, NPTH, both drill maps | identical | |
| F.Cu | different | Non-region content identical except two `%TA/%TD` attribute pairs (the F.Cu island split, `notes_eib.md` section 2.1). Region XOR: 20.922 mm2 removed, 0 mm2 added. Every removed component above 1e-4 mm2 lies within 1.0 mm of a J201 pad (pads modelled as 1.8 mm circles at the 3 x 3, 2.54 mm grid around (20.0, 31.0)); the area beyond 0.55 mm is the copper between adjacent pads (0.527 mm2 squares) that the 0.5 mm clearance disconnects. |
| B.Cu | different | Non-region content identical. Region XOR: 15.911 mm2 removed, 0 mm2 added, all within 1.0 mm of a J201 pad (one 0.0006 mm2 sliver beyond). Cause as F.Cu: D-70 / EIL-0, `gen/eib_j201_pour_clearance.py`. |
| F.Paste | different | Expected: 94 -> 62 flashes; the 32 removed flashes are the SMD pads of the DNP set (R258-R265 16, U203 and U204 12, C203 and C204 4); aperture list consolidated. Matches the "62 pads" of the `bom_2026-11-14/eib_bom.csv` stencil row. |
| F.Silkscreen, B.Silkscreen | different | Expected: phase A and silkscreen-agent edits |
| job file | different | Expected: `Finish` None -> ENIG and layer colors; the thicknesses (0.035 mm copper, 1.51 mm FR4, 0.01 mm mask) are unchanged |

No unexpected difference was found on either board.

## 6. OSH Park upload zip

- `fab/cr_2026-11-14/kikit_oshpark/gerbers.zip`: 15 files of board `cr` (4 copper, 2 mask, 2 paste, 2 silk,
  Edge.Cuts, job, drill map, drill report and one drill file `cr.drl`) (`MixedPlating,1,4`), 485 hits = 479 PTH
  + 6 NPTH of `drill/`.
- `fab/eib_2026-11-14/kikit_oshpark/gerbers.zip`: 13 files of board `eib`, of which one drill file `eib.drl`
  (`MixedPlating,1,2`), 112 hits = 110 PTH + 2 NPTH.
- With the X2 attribute lines removed, the KiKit copper, paste, mask and Edge.Cuts files equal the files in
  `gerbers/`. The KiKit silkscreen files differ: `gerbers/` is exported with `--subtract-soldermask` (one `%LPC`
  block), the KiKit OSH Park preset is not. This is the same in `fab/cr_2026-11-13f`. Whether OSH Park clips the
  silkscreen at mask openings: TODO(verify: docs.oshpark.com).

## 7. BOM and position files

Cross-check of `assembly/<board>-bom.csv`, `assembly/<board>-pos.csv`, the board footprint fields (pcbnew) and
`bom_2026-11-14/<board>_bom.csv` (`bomcheck.py` in the scratch folder):

- CR: 82 footprints; 78 package-BOM refs; 78 position rows (all fitted SMD and THT parts; MH1-MH4 have no
  position row); no DNP part. Package BOM MPN, manufacturer and value equal the board fields for every ref. Every
  fitted part with an MPN is in the ordered BOM with the same MPN (J1 is two ordered rows, TSW-110-07-L-S and
  TSW-112-07-L-S, against the board field "TSW-110-07-L-S + TSW-112-07-L-S").
- EIB: 48 footprints; 46 package-BOM refs; 32 position rows; the 14 DNP parts (C203, C204, E4, E6, R258-R265,
  U203, U204) are DNP on the board, flagged DNP in `eib-bom.csv`, absent from `eib-pos.csv` and absent from the
  ordered BOM. MPN, manufacturer and value agree with the board fields.
- Manufacturer spelling differs between the ordered BOM and the board fields on 22 refs (CR 17, EIB 5) ("Murata Electronics" /
  "Murata", "Nexperia USA Inc." / "Nexperia", "Littelfuse Inc." / "Littelfuse", "Panasonic Industry" /
  "Panasonic"). The MPNs agree; the difference is cosmetic.
- `assembly/cr-bom.csv` writes six references with a "?" suffix: C102a?, C102b?, C102c?, R106s?, R131A?, R131B?
  (KiCad BOM export of references with a letter suffix). This is pre-existing (six in `fab/cr_2026-11-13f`).

## 8. Package README review

Correct in both READMEs: board marking ("CR r8 2026-11-14" D-78, "EIB r8 2026-11-14" D-74/D-78), quantity (CR 6,
EIB 3, with the operator rulings), ENIG, ERC/DRC counts, the stencil notes (CR: U101 exposed-pad windows about
55 %, 4 mil OSH Stencils, D-69; EIB: -2.0 mm paste margin, no aperture on the DNP pads), the B.Silkscreen
reference lists, the pin-18 soldering note and the KiKit version (1.8.1, `kikit --version`).

Stale or incomplete text (`gen/fab_readme.py` was not edited in this step):

1. CR status paragraph: "the copper equals the D-66 package `fab/cr_2026-11-13d/`". F.Cu now differs in the
   J1 pin-18 fill (D-75, section 5.1). The closing clause "the copper traces are those of `fab/cr_2026-11-13f/`"
   is correct.
2. Both READMEs: the comparison section reads "DIFFERENCES FOUND" without an explanation per file. Section 5 of
   this note gives the explanation.
3. Neither section 1 table has a stack-up row. The CR copper row gives 1 oz / 0.5 oz and the OSH Park row names
   FR408-HR, but the dielectric thicknesses (0.1999 mm prepreg x2, 0.9906 mm core) and the 0.0432 mm finished
   outer copper exist only in the job file. The EIB table gives no dielectric value (job file: 1.51 mm FR4).
4. The ordered BOM `bom_2026-11-14/` PCB rows: CR "copper as D-66/D-69" omits the D-75 F.Cu fill change; EIB
   "copper as D-68" omits the D-70 J201 pour clearance. Both rows carry "TODO(verify: package exported)", which
   this export closes.

## 9. Renders and silkscreen inspection

`kicad-cli pcb render` (2400 px, high quality) of both sides of both boards: `cr_top.png`, `cr_bottom.png`,
`eib_top.png`, `eib_bottom.png` in the scratch folder. All references and labels are legible. The J201 map on the
EIB and the J101 map on the CR were checked against the pad numbers and nets of the board (pcbnew): every cell
matches the pad at that position. Observations (none is a DRC item):

- CR top: "J101 top view" and the vertical "SCL" (W7) label nearly touch; "R176" sits against the top of
  "C108"; "R115" is close to the J101 pin-1 bar; the J101 map is placed beside the J1 right-hand column, not
  beside J101, so a reader can associate its cells with J1.
- CR top: the "U106" text crosses a tented via. CR bottom: "C102c" and the vertical "C102a" nearly touch.
- EIB top: "R263" is close to "J201 top view"; a tented via lies under "r8" of the board marking.
- EIB bottom: tented vias lie under "E7 TP38", "E2 JP14" and "E8 TP49"; "R254" and "R271" are close.

## 10. Constraint checks

`gen/check_constraints.py <board> ../<board>` from `gen/`:

| Board | Pre-review (git HEAD) | Now | Difference |
|---|---|---|---|
| CR | 129 table rows, 109 "pass", 0 FAIL | 129 rows, 109 "pass", 0 FAIL | Six D-56 F.Cu escape rows (U101.6, .7, .10, .13, .14, R102.2): free area 0.13 mm2 smaller (for example 1055.09 -> 1054.96 mm2), verdicts unchanged; cause: the pin-18 VCHG fill |
| EIB | 9 rows, 5 "pass", 0 FAIL | same | A.9 outline row reference text "D-13: 38 x 24" -> "D-25: 24.0 x 38.0" (script edit of phase A); verdict unchanged |

No new FAIL and no lost pass row. The reports written equal the phase A reports byte for byte.

## 11. Open items

1. Correct the README text of section 8 items 1 to 3 in `gen/fab_readme.py` and re-run it (no re-export needed).
2. Update the ordered-BOM PCB rows (section 8 item 4) through `gen/bom_split.py`.
3. TODO(verify: docs.oshpark.com): silkscreen clipping at mask openings for the unsubtracted KiKit silkscreen.
4. Decide whether the silkscreen observations of section 9 need a further silkscreen pass.
5. The KiKit JLCPCB/PCBWay CR assembly BOM failure and the "?" reference suffixes in `cr-bom.csv` are pre-existing.

## 12. Fix round 1 (2026-11-15, check1 issues 2 and 13)

Section 11 items 1 and 2 are closed. `gen/fab_readme.py` now prints a reason for every file that differs from the
reference package (from section 5 of this note), deletes the stale "copper equals `fab/cr_2026-11-13d/`" clause, adds
a stack-up row read from the job file (section 8 item 3) and notes the six "?" reference suffixes of
`assembly/cr-bom.csv`. Both READMEs were rewritten with `gen/fab_readme.py <board> 2026-11-14 <reference>`; no
re-export was run, and no Gerber changed. Details: `notes_phaseB_fix1.md` sections 3.3 and 3.9.
