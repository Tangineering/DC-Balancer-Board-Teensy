# CR, CHG adapter carrier (plug-on): fabrication package (2026-11-14)

**Status: not ordered.** This package awaits operator review before order. The fab is OSH Park (operator ruling 2026-11-12). The routing is D-58; the outline is D-62 and the 6-32 holes are D-60; the GND stitching and straightened tracks are D-61; the reference designators are D-59, re-placed in D-74 and D-78 (`cr/silk_refs.md` lists every reference with its layer). After the operator's routing cleanup in KiCad (`547dc11`), the short In2 via pairs were merged onto F.Cu and three /GND stitching vias at J101 and C129 were deleted (D-65, `gen/via_merge_cr.py`). J101 is a 3 x 3 grid of plated wire pads for the soldered W5 wires; the FTSH header and the ribbon are retired (D-66, `gen/swap_wire9.py`). U101 is the Toshiba TCKE1401NM on the unchanged footprint, with R101 8.45k, R103 64.9k and R104 51.1k (D-67). The U101 exposed-pad paste windows follow the via keep-outs, about 55 % coverage, for a 4 mil stainless OSH Stencils stencil (D-69). The 2026-11-14 round (D-72 to D-78, D-82) adds pin-1 dots and SMA cathode bars (D-72), the J101 map "J101 top view" and the W-lead labels (D-73), the board marking "CR r8 2026-11-14" (D-78), the J1 pin-18 solid zone connection (D-75), the stack-up block (D-76) and the part fields of the ordered BOM (D-82). Phase C (2026-11-15) labels the 20 AWG input pair: "VIN1" and the W1 reference beside W1 (/VCHGOUT, to EVM J1 pin 2), "GND" beside W2 (/GND, to EVM J1 pin 1) (D-85). The tracks, vias, pads and zone outlines are those of `fab/cr_2026-11-13f/`; the F.Cu pour fill differs within 1.7 mm of J1 pin 18 (D-75), section 5.

## 1. Board

| Item | Value |
|---|---|
| Layers | 4 (F.Cu (L1, signals and power pours), In1.Cu (L2, solid GND), In2.Cu (L3, signals), B.Cu (L4, solid GND facing the MB, D-20)) |
| Size | 10-corner outline with 1.0 mm corner fillets, edges at 0/30/45/60/90/120/135/150 degrees (D-62), 40.02 x 64.81 mm bounding box (MB frame x 18.58-58.60, y 7.83-72.64), 2327.7 mm2, trimmed after routing inside the D-39 rectangle; four 6-32 NPTH holes, 3.70 mm (MH1-MH4, D-60) |
| Thickness | 1.6 mm |
| Copper | 1 oz outer / 0.5 oz inner (D-29) |
| Stack-up (job file) | Top Solder Mask 0.0152 mm PSR-4000BN; F.Cu 0.0432 mm; F.Cu/In1.Cu 0.1999 mm FR408HR 2113; In1.Cu 0.0175 mm; In1.Cu/In2.Cu 0.9906 mm FR408HR; In2.Cu 0.0175 mm; In2.Cu/B.Cu 0.1999 mm FR408HR 2113; B.Cu 0.0432 mm; Bottom Solder Mask 0.0152 mm PSR-4000BN (`gerbers/cr-job.gbrjob`, D-76) |
| Surface finish | ENIG |
| Quantity | 6 (operator ruling 2026-11-13: "Use 6"; OSH Park sells boards in multiples of 3; design document section E asks for 6 (r9-25); superseded note: "the E BOM asks for 5") |
| Solder mask / silkscreen | both sides; every via tented on both sides. The nine 0.3 mm through-holes of the U101 exposed pad (footprint pad 25, not vias) lie inside the 2.7 mm exposed-pad mask opening on F.Cu and are open there; they are tented on B.Mask only (D-69 paste windows keep >= 0.16 mm from the drills) |
| Design rules | `cr/cr.kicad_dru` = `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` plus the J1 pin-18 solid zone connection (REVIEW_2026-11-14 CRL-4). Rule minima: 0.127 mm track and clearance, 0.254 mm hole, 0.1016 mm annular ring, 0.381 mm copper to edge. Design values: signal tracks 0.1524 mm with 0.1524 mm clearance (net-class default), power tracks 0.4-0.6 mm, no 0.127 mm track; the F.Cu power and GND pours fill to the 0.127 mm rule minimum (fab_clearance), not to the 0.2 mm local clearance that the zones declare: /GND to /VCHG, /VCHGIN and /VCHGOUT 0.127 mm, /VCHGIN to /VCHGOUT 0.150 mm (pcbnew measurement of the filled polygons, update_2026-11-14/notes_phaseC_board.md; REVIEW2 R2-CRL-2); via 0.6 mm pad / 0.3 mm drill (0.15 mm ring). Superseded note: "design values: 0.1524 mm track and clearance (net-class default; 0.127 mm at necks only)" |
| ERC | 0 messages (`reports/erc.rpt`) |
| DRC | 0 violations, 0 unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. Its 4-layer service (1.6 mm, 1 oz outer / 0.5 oz inner clad, ENIG, FR408-HR) matches section 1 (docs.oshpark.com/services/four-layer/, read 2026-11-13). Order quantities come in multiples of 3. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `assembly/cr-bom.csv` (KiKit wrote no `bom.csv`) and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `assembly/cr-bom.csv` (KiKit wrote no `bom.csv`) and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `cr_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |

The CR needs a hot-air or reflow step for U101 (TCKE1401NM, VQFN24D, 0.5 mm pitch, A.8 hand assembly row), or a PCB assembly service.

Seven references are on B.Silkscreen, mirrored, over their parts: C102a, C102c, C119, C131, R107, U107 and U119 (D-78). They can be read only before the CR is plugged onto the MB. J1 pin 18 joins the F.Cu VCHG pour solidly (D-75), so its joint needs a higher iron setting or a larger tip and a longer dwell than pin 19.

The 20 AWG input pair is labelled on F.Silkscreen: W1 carries "VIN1" (/VCHGOUT, to EVM J1 pin 2, VIN1) and W2 carries "GND" (/GND, to EVM J1 pin 1) (D-85). A swapped pair shorts the U101 output at the EVM end.

`assembly/cr-bom.csv` writes 6 references with a "?" suffix: C102a?, C102b?, C102c?, R106s?, R131A?, R131B?. The "?" is an artefact of the KiCad BOM export for references with a letter suffix; read C102a, C102b, C102c, R106s, R131A, R131B.

KiKit `fab jlcpcb --assembly` wrote no `bom.csv` for this board (`reports/kikit_jlcpcb.log`: "invalid literal for int()"); its `gerbers.zip` is complete. Use `assembly/cr-bom.csv` for assembly quotes.

KiKit `fab pcbway --assembly` wrote no `bom.csv` for this board (`reports/kikit_pcbway.log`: "invalid literal for int()"); its `gerbers.zip` is complete. Use `assembly/cr-bom.csv` for assembly quotes.

## 3. Contents

| Folder or file | Content |
|---|---|
| `gerbers/` | Gerber X2: copper, mask, paste, silkscreen, Edge.Cuts, job file |
| `drill/` | Excellon PTH and NPTH files, drill maps (PDF and Gerber X2) |
| `assembly/cr-pos.csv` | pick-and-place, both sides, mm, DNP parts excluded |
| `assembly/cr-bom.csv` | grouped BOM with MPN, manufacturer and DNP columns |
| `assembly/cr_ibom.html` | InteractiveHtmlBom (open in a browser); DNP parts left out of the BOM table |
| `docs/cr-schematic.pdf` | schematic |
| `docs/cr-pcb.pdf` | one page per copper, silkscreen, fab and mask layer |
| `docs/cr.step` | 3D model |
| `docs/cr.net` | netlist exported from the schematic |
| `kikit_*` | KiKit 1.8.1 `fab jlcpcb`, `fab pcbway`, `fab oshpark` outputs |
| `reports/` | ERC, DRC and KiKit logs |

The per-unit BOMs and the Digi-Key and Mouser import files are in `hardware/charger_evm_r8/bom_2026-11-14/`
(its `README.md` gives the order instructions and the optional alternate lines). The layout
decisions and the open `TODO(verify)` items are in `hardware/charger_evm_r8/LAYOUT_DECISIONS.md`.

## 4. Before you order

1. Read `LAYOUT_DECISIONS.md` section 10 (proposed design changes) and section 11 (open TODO(verify) items).
2. Confirm the copper weight and the fab rule items marked `TODO(verify)` in `tools/pcb/fab_rules`.
3. Do not order until the operator has reviewed this package and the ordering BOM.

## 5. Copper and drill comparison

Every Gerber and Excellon file of this package was compared line by line with `fab/cr_2026-11-13f`,
with the creation-date lines ignored. Result: DIFFERENCES FOUND, each with the recorded reason below.

| File | Result | Reason |
|---|---|---|
| `gerbers/cr-B_Cu.gbl` | identical (8780 lines) |  |
| `gerbers/cr-B_Mask.gbs` | identical (2255 lines) |  |
| `gerbers/cr-B_Paste.gbp` | identical (13 lines) |  |
| `gerbers/cr-B_Silkscreen.gbo` | DIFFERENT | expected: silkscreen edits D-72 to D-78 (pin-1 dots and SMA cathode bars, the J101 map and W-lead labels, the reference moves, the board marking "CR r8 2026-11-14") |
| `gerbers/cr-Edge_Cuts.gm1` | identical (86 lines) |  |
| `gerbers/cr-F_Cu.gtl` | DIFFERENT | expected: pour fill only. The D-75 solid connection of J1 pin 18 (/VCHG) replaces its thermal relief: region XOR 2.698 mm2 added and 0.203 mm2 removed, all within 1.7 mm of pad 18. Tracks, vias and pads are unchanged (update_2026-11-14/notes_phaseB_export.md section 5.1) |
| `gerbers/cr-F_Mask.gts` | identical (12519 lines) |  |
| `gerbers/cr-F_Paste.gtp` | identical (498 lines) |  |
| `gerbers/cr-F_Silkscreen.gto` | DIFFERENT | expected: silkscreen edits D-72 to D-78 (pin-1 dots and SMA cathode bars, the J101 map and W-lead labels, the reference moves, the board marking "CR r8 2026-11-14") and phase C D-85 (F.Silkscreen only: the W1 "VIN1" and W2 "GND" input-pair texts and the W1 reference moved to the W1 side, REVIEW2 R2-INT-0) |
| `gerbers/cr-In1_Cu.g1` | identical (8497 lines) |  |
| `gerbers/cr-In2_Cu.g2` | identical (1798 lines) |  |
| `gerbers/cr-job.gbrjob` | DIFFERENT | expected: D-76, finish ENIG and the OSH Park stack-up (materials, colours and thicknesses, section 1 stack-up row) |
| `drill/cr-NPTH-drl_map.gbr` | identical (1664 lines) |  |
| `drill/cr-NPTH.drl` | identical (22 lines) |  |
| `drill/cr-PTH-drl_map.gbr` | identical (6112 lines) |  |
| `drill/cr-PTH.drl` | identical (510 lines) |  |

The other files of this package also differ from the reference package; they are not compared line by line. D-82
set the Value, MPN and Manufacturer fields to the ordered BOM (CR: for example C110 50 V to 100 V and C102b X7S to
X7R; EIB: for example C201 50 V to 100 V). The assembly BOM therefore differs in those three fields, and the position
file differs in the Value field only; every reference, footprint, position, rotation and side is identical. The iBOM, the schematic, PCB and STEP files of `docs/`, the netlist, the drill-map PDFs, the KiKit outputs
and the DRC and ERC reports are regenerated from the same boards and carry the same field, silkscreen and pour-fill
changes, or only new creation dates. `reports/npth_check.txt` is new in this package.
