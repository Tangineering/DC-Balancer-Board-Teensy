# Charger retrofit r8: order, design and assembly package (2026-11-17)

This package holds what is needed to order, review and assemble the two boards of the fuel-cell car charger
retrofit: the CR (charge-regulator carrier, 4 layers, plugs onto the MB Ag105 footprint) and the EIB (EVM interface
board, 2 layers). It was built from repository commit `3e5a2bd` on 2026-11-17 11:41 by
`hardware/charger_evm_r8/gen/export_package.py`. The working tree had no uncommitted source changes. The fab files are those of `fab/cr_2026-11-17/` and
`fab/eib_2026-11-17/`; the BOM set is `bom_2026-11-14/`. Nothing in the package has been ordered.

## 1. Folders

| Folder | Content | Use |
|---|---|---|
| `01_order/pcb/` | `cr_oshpark_gerbers.zip`, `eib_oshpark_gerbers.zip` (OSH Park uploads); `*_gerbers_drill_any_fab.zip` (Gerber X2, Excellon PTH and NPTH, drill maps, for any other fab); the fab-package READMEs as PDF | PCB order |
| `01_order/stencil/` | `cr-F_Paste.gtp`, `eib-F_Paste.gtp` | stencil order |
| `01_order/bom/` | the BOM set as CSV and `BOM_README.pdf` | parts order |
| `02_design_reference/` | design overview, lab-update slides, schematics, PCB layer plots, PCB renders, design review guide, design record, layout decisions, the check reports; `3d/` STEP models | design reference |
| `03_assembly/` | assembly guide and reference placement drawing per board, interactive BOMs (`*_ibom.html`, open in a browser), pick-and-place (`*-pos.csv`), fab BOMs, the guide images, the EVM rework guide | assembly at the bench |

Some documents in the package were written for the repository and name repository paths. Their PDFs carry a
"package file map" box at the top, and a link to another document of the package names its package file in
brackets. Table 1 gives the general map.

Table 1. Repository names and package files.

| Repository name | Package file |
|---|---|
| `fab/<board>_2026-11-17/kikit_oshpark/gerbers.zip` | `01_order/pcb/<board>_oshpark_gerbers.zip` |
| `fab/<board>_2026-11-17/<board>_gerbers_drill.zip` | `01_order/pcb/<board>_gerbers_drill_any_fab.zip` |
| `fab/<board>_*/gerbers/<board>-F_Paste.gtp` | `01_order/stencil/<board>-F_Paste.gtp` |
| `bom_2026-11-14/` | `01_order/bom/` |
| `OVERVIEW.md` | `02_design_reference/01_design_overview.pdf` |
| `README.md` (board folder) | `02_design_reference/06_design_review_guide_README.pdf` |
| `docs/charger_bq25798_wiring_design_2026-11-05.md` ("the design document", its sections A to J) | `02_design_reference/07_design_record_charger_bq25798_wiring_design.pdf` |
| `LAYOUT_DECISIONS.md` | `02_design_reference/08_layout_decisions.pdf` |
| `assembly/guide/` | `03_assembly/<board>_assembly_guide.pdf`, `03_assembly/guide_images/` |
| `evm_rework/EVM_REWORK_GUIDE.md` | `03_assembly/EVM_rework_guide.pdf` |

## 2. How to order

1. PCBs at OSH Park: upload `01_order/pcb/cr_oshpark_gerbers.zip` to the 4-layer service (1.6 mm, ENIG), quantity
   6, and `01_order/pcb/eib_oshpark_gerbers.zip` to the 2-layer service, quantity 3 (operator rulings 2026-11-13).
   Section 1 of `cr_fab_package_README.pdf` and `eib_fab_package_README.pdf` gives the board parameters.
2. Stencils at OSH Stencils: one stencil per board design, stainless steel, 4 mil (0.1 mm), frameless, top side
   only, from `01_order/stencil/cr-F_Paste.gtp` and `eib-F_Paste.gtp`.
3. Parts: import `01_order/bom/digikey_import.csv` at Digi-Key (BOM Manager) and `01_order/bom/mouser_import.csv`
   at Mouser.
   - The import files order the parts of **one build**: one CR, one EIB, one EVM rework and one MB rework, with
     attrition (`BOM_README.pdf` section 1). Six CR and three EIB PCBs are ordered, but parts for one assembled CR
     and one EIB only; multiply the main lines for more assembled boards.
   - `digikey_optional.csv` holds opt-in lines: alternates (the D103 alternate, the C108 option), spares, and two
     BENCH ONLY test capacitors (4.7 nF and 10 nF C0G) that are never fitted in service.
   - `digikey_skipped.csv` lists the rows that are not in the Digi-Key import: workshop stock; items removed from
     the BOM; the PCBs and stencils (steps 1 and 2); items to buy elsewhere, namely the BQ25798EVM (Texas
     Instruments) and the DOWSIL 3145 RTV (Graco Roberts); items with no identified part yet (heat-shrink tubing and
     two adhesive cable-tie bases); and the machined or cut mechanical parts (B1R wedge, insulating posts, off-CR
     insulating support, EVM plate and clamps, 0.5 mm silicone pads). Order or make each one by its row.

Read these points before ordering:

- `digikey_import.csv` still carries the line `CRCW06032K70FKEA` (10 x 2.70 kOhm, "MB RSDA, MB RSCL"). That MB
  pull-up change (PM9) was withdrawn on 2026-11-16 (D-96). Delete the line before the Digi-Key upload.
- Solder paste (a Type 4 paste is the usual choice for the 0.5 mm pitch of U101) and four 6-32 screws or standoffs
  for the CR holes MH1-MH4 are on no order file; buy them separately.
- The PCB and stencil rows of `cr_bom.csv` and `eib_bom.csv` name the 2026-11-14 packages. The 2026-11-17 files in this
  package supersede them: copper, mask, paste, edge and drill files are identical between the two dates, and only
  the silkscreen differs (D-97). The board marking on the silkscreen reads "r8 2026-11-14" on both, because it
  dates the copper; a 2026-11-17 board has no bottom-side labels of top-side SMD parts.
- Open item, for an operator decision before submission (`11_datasheet_recheck_2026-11-17.pdf` section 1, S2): on
  the CR, 43 plated holes whose unused inner pads are removed (J1, J101, J102, W1, W3, W6, W7 and the U101
  exposed-pad holes) clear the inner-layer pours by 0.2545 mm against the OSH Park minimum of 0.254 mm. The
  operator ruled on 2026-11-13 to assume acceptance at submission (`08_layout_decisions.pdf` section 11 item 3), on
  the record that the pours keep 0.27 mm and that OSH Park says nothing on non-functional pads. Both premises have
  changed: the measured clearance is 0.2545 mm, and the OSH Park 4-layer page now states that suppressed inner
  rings "can lead to surprising defects and yield issues". The option is an inner-layer pour clearance of 0.30 mm
  (a copper change on In1/In2 only, followed by a refill, DRC and re-export).
- OSH Park does not state whether the drill size in the files is the drilled or the finished hole; its FAQ implies
  the finished size, with a tolerance of +/-0.0635 mm maximum (docs.oshpark.com, read 2026-11-17).
- KiKit's JLCPCB and PCBWay presets wrote no assembly `bom.csv` for the CR, so those folders are not in the
  package. For another fab, upload `<board>_gerbers_drill_any_fab.zip`; for an assembly quote, use
  `03_assembly/<board>-bom.csv` and `<board>-pos.csv`.
- The fab-package READMEs end with "Do not order until the operator has reviewed this package and the ordering
  BOM" and refer to fab-rule items marked `TODO(verify)` in the repository folder `tools/pcb/fab_rules/`. Both are
  operator gates. The open operator questions that can change the order (spare U101, C103 value, C108 option, the
  D103 alternate, the SPARE lines) are listed in `08_layout_decisions.pdf` section 1 and in
  `06_design_review_guide_README.pdf`.

## 3. Design reference (`02_design_reference/`)

| File | Content |
|---|---|
| `01_design_overview.pdf` | condensed design summary for readers new to the project |
| `02_lab_update_slides_charger_path_redesign.pdf` | lab-update slide deck on the CR and EIB charger path redesign |
| `03_cr_schematic.pdf`, `03_eib_schematic.pdf` | schematics in functional blocks, with the operation of each comparator and gate noted at the part |
| `04_cr_pcb_layers.pdf`, `04_eib_pcb_layers.pdf` | reference placement drawing, then one page per layer, each named, scaled to the page |
| `05_pcb_renders.pdf` | 3D renders, top, bottom and isometric |
| `06_design_review_guide_README.pdf` | the full design review guide of the board folder |
| `07_design_record_charger_bq25798_wiring_design.pdf` | the authoritative design record; it governs where documents disagree |
| `08_layout_decisions.pdf` | the layout decision log (D-numbers) and the open items |
| `09_bom_check_2026-11-17.pdf`, `10_footprint_check_2026-11-17.pdf`, `11_datasheet_recheck_2026-11-17.pdf` | the pre-order BOM, datasheet and land-pattern checks, and the re-check against the local datasheets with the OSH Park hole rules |
| `3d/cr.step`, `3d/eib.step` | STEP models |

## 4. Assembly reference (`03_assembly/`)

Sequence for each board (design D-44: every SMT part on the top side, one stencil, one reflow; through-hole parts
hand-soldered last):

1. Print paste with the board's stencil.
2. Place every top-side SMD part. Use the silkscreen, the guide pages of `<board>_assembly_guide.pdf` and the
   interactive BOM `<board>_ibom.html`; `<board>_placement_refs.pdf` shows every reference designator at its part.
3. Reflow once. The CR needs reflow or hot air for U101 (TCKE1401NM, VQFN-24, 0.5 mm pitch).
4. Hand-solder the through-hole parts: CR J1 (Samtec TSW strips), the wire pads, and J102 last. CR J1 pin 18 joins
   the VCHG pour solidly, so it needs more heat and dwell than pin 19.
5. Wire the leads. CR W1 ("VIN1") and W2 ("GND") form the 20 AWG input pair to EVM J1; a swapped pair shorts the
   U101 output at the EVM end.

Notes:

- The silkscreen labels only the parts whose reference sits at the part; no label of a top-side SMD part is on the
  bottom (D-97). The guide pages tag every other top-side SMD part with its reference and value; the part table is
  at the end of each assembly guide (also `guide_images/<board>_guide_README.md`).
- The CR has no DNP parts. The EIB DNP set (14 parts: C203, C204, E4, E6, R258-R265, U203, U204) is in
  `eib_fab_package_README.pdf` section 5; the interactive BOMs leave the DNP parts out of their tables.
- In `<board>-bom.csv` the references C102a, C102b, C102c, R106s, R131A and R131B are written without the "?" that
  the KiCad BOM export adds.
- The EVM modifications (EM items) are in `EVM_rework_guide.pdf`. Section C of the design record
  (`07_design_record_charger_bq25798_wiring_design.pdf`) defines them and governs where the two differ. The EVM
  user guide is TI SLUUCB5 (https://www.ti.com/lit/pdf/sluucb5), not included.

## Appendix A: file list

| File | Size |
|---|---|
| `01_order/bom/BOM_README.pdf` | 301 kB |
| `01_order/bom/cr_bom.csv` | 39 kB |
| `01_order/bom/digikey_import.csv` | 9 kB |
| `01_order/bom/digikey_optional.csv` | 2 kB |
| `01_order/bom/digikey_skipped.csv` | 3 kB |
| `01_order/bom/eib_bom.csv` | 9 kB |
| `01_order/bom/mouser_import.csv` | 1 kB |
| `01_order/bom/system_bom.csv` | 18 kB |
| `01_order/pcb/cr_fab_package_README.pdf` | 165 kB |
| `01_order/pcb/cr_gerbers_drill_any_fab.zip` | 417 kB |
| `01_order/pcb/cr_oshpark_gerbers.zip` | 318 kB |
| `01_order/pcb/eib_fab_package_README.pdf` | 162 kB |
| `01_order/pcb/eib_gerbers_drill_any_fab.zip` | 172 kB |
| `01_order/pcb/eib_oshpark_gerbers.zip` | 125 kB |
| `01_order/stencil/cr-F_Paste.gtp` | 17 kB |
| `01_order/stencil/eib-F_Paste.gtp` | 4 kB |
| `02_design_reference/01_design_overview.pdf` | 921 kB |
| `02_design_reference/02_lab_update_slides_charger_path_redesign.pdf` | 2183 kB |
| `02_design_reference/03_cr_schematic.pdf` | 528 kB |
| `02_design_reference/03_eib_schematic.pdf` | 282 kB |
| `02_design_reference/04_cr_pcb_layers.pdf` | 1756 kB |
| `02_design_reference/04_eib_pcb_layers.pdf` | 474 kB |
| `02_design_reference/05_pcb_renders.pdf` | 4399 kB |
| `02_design_reference/06_design_review_guide_README.pdf` | 3282 kB |
| `02_design_reference/07_design_record_charger_bq25798_wiring_design.pdf` | 8052 kB |
| `02_design_reference/08_layout_decisions.pdf` | 2123 kB |
| `02_design_reference/09_bom_check_2026-11-17.pdf` | 275 kB |
| `02_design_reference/10_footprint_check_2026-11-17.pdf` | 257 kB |
| `02_design_reference/11_datasheet_recheck_2026-11-17.pdf` | 450 kB |
| `02_design_reference/3d/cr.step` | 1448 kB |
| `02_design_reference/3d/eib.step` | 745 kB |
| `03_assembly/EVM_rework_guide.pdf` | 10343 kB |
| `03_assembly/cr-bom.csv` | 5 kB |
| `03_assembly/cr-pos.csv` | 7 kB |
| `03_assembly/cr_assembly_guide.pdf` | 2204 kB |
| `03_assembly/cr_ibom.html` | 343 kB |
| `03_assembly/cr_placement_refs.pdf` | 127 kB |
| `03_assembly/eib-bom.csv` | 3 kB |
| `03_assembly/eib-pos.csv` | 3 kB |
| `03_assembly/eib_assembly_guide.pdf` | 826 kB |
| `03_assembly/eib_ibom.html` | 286 kB |
| `03_assembly/eib_placement_refs.pdf` | 89 kB |
| `03_assembly/guide_images/cr_guide_1.png` | 359 kB |
| `03_assembly/guide_images/cr_guide_2.png` | 350 kB |
| `03_assembly/guide_images/cr_guide_3.png` | 348 kB |
| `03_assembly/guide_images/cr_guide_4.png` | 337 kB |
| `03_assembly/guide_images/cr_guide_5.png` | 308 kB |
| `03_assembly/guide_images/cr_guide_6.png` | 288 kB |
| `03_assembly/guide_images/cr_guide_README.md` | 6 kB |
| `03_assembly/guide_images/cr_overview.png` | 278 kB |
| `03_assembly/guide_images/eib_guide_1.png` | 214 kB |
| `03_assembly/guide_images/eib_guide_2.png` | 206 kB |
| `03_assembly/guide_images/eib_guide_3.png` | 191 kB |
| `03_assembly/guide_images/eib_guide_README.md` | 3 kB |
| `03_assembly/guide_images/eib_overview.png` | 180 kB |

## Appendix C: render notes

- OVERVIEW.md: 2 identifiers render fewer times than in the source (e.g. charger_bq25798_wiring_design_2026, fig2_1_block_diagram)
- README.md: 4 identifiers render fewer times than in the source (e.g. fig2_1_block_diagram, fig5_1_permit_gate, cr_routed_2026, 3d_iso)
- charger_bq25798_wiring_design_2026-11-05.md: 1 identifiers render fewer times than in the source (e.g. static_assert)
- charger_bq25798_wiring_design_2026-11-05.md: 7 literal '**' in the rendered text (nested bold in the source)
- DATASHEET_RECHECK_2026-11-17.md: 2 literal '**' in the rendered text (nested bold in the source)
- EVM_REWORK_GUIDE.md: 17 identifiers render fewer times than in the source (e.g. fig01_legend, fig02_top_overview, fig03_bottom_overview, fig04_schematic_ilim_ce, fig05_schematic_page1, fig06_left_jumpers_top)
