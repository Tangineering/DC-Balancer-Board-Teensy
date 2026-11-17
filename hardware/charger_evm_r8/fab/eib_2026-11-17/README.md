# EIB, EVM interface board: fabrication package (2026-11-17)

**Status: not ordered.** This package awaits operator review before order (dec2-eib decision 1, 2026-11-12). The routing is D-28; the straightened tracks, the F.Cu AGND pour and the AGND stitching vias are D-63 (`eib/straighten.md`, `eib/stitch_gaps.md`); the reference designators are D-64, re-placed in D-74 and D-78 (`eib/silk_refs.md` lists every reference with its layer). J201 is a 3 x 3 grid of plated wire pads for the soldered W5 wires; the FTSH header and the ribbon are retired, and the area around J201 was re-routed (D-66, `gen/swap_wire9.py`). The AGND pours keep 0.5 mm from the hand-soldered E lead pads (D-68, rule in `gen/eib_pour_rules.kicad_dru`), and since D-70 also from the J201 wire pads. The 2026-11-14 round (D-70 to D-78, D-82) adds no paste on the DNP pads (D-71), pin-1 dots (D-72), the J201 map "J201 top view" and the E labels (D-73), the board marking "EIB r8 2026-11-14" (D-74, D-78), the stack-up block (D-76) and the part fields of the ordered BOM (D-82). Phase C (2026-11-15) adds the E-pad numbers on F.Silkscreen beside the E pads and corrects the bottom E labels (E1 reads "E1 JP12.1"; 0.80 mm from the bottom references) (D-86). The tracks, vias, pads and zone outlines are those of `fab/eib_2026-11-13c/`; the F.Cu and B.Cu pour fill differs at J201 (D-70) and F.Paste has no aperture on the DNP pads (D-71), section 6. The 2026-11-17 round changes no copper, mask, paste or drill file: the silkscreen keeps only reference labels that sit at their own parts and puts no label of a top-side SMD part on the bottom; the other parts are shown in the assembly guide `assembly/guide/` (D-97), and the schematic is laid out in functional blocks with operation notes at the comparators and gates (the netlist is unchanged).

## 1. Board

| Item | Value |
|---|---|
| Layers | 2 (F.Cu (signals, AGND pour), B.Cu (signals, AGND pour); the two AGND pours stitched by vias (D-63)) |
| Size | 24.0 x 38.0 mm (D-25 / P-05; A.9 since r9-25; superseded note: "A.9 states 36.0 x 24.0 mm") |
| Thickness | 1.6 mm |
| Copper | 1 oz |
| Stack-up (job file) | Top Solder Mask 0.01 mm; F.Cu 0.035 mm; F.Cu/B.Cu 1.51 mm FR4; B.Cu 0.035 mm; Bottom Solder Mask 0.01 mm (`gerbers/eib-job.gbrjob`, D-76) |
| Surface finish | ENIG |
| Quantity | 3 (operator ruling 2026-11-13: "Order 3"; one OSH Park lot of 3; a separate 2-layer order at OSH Park) |
| Solder mask / silkscreen | both sides; every via tented on both sides |
| Design rules | `eib/eib.kicad_dru` = `tools/pcb/fab_rules/fab_2layer_oshpark_pcbway.kicad_dru` plus the 0.5 mm AGND pour clearance to the E and J201 pads (`gen/eib_pour_rules.kicad_dru`, D-68, REVIEW_2026-11-14 EIL-0). Rule minima: 0.1524 mm track and clearance, 0.254 mm hole, 0.15 mm annular ring, 0.381 mm copper to edge |
| ERC | 0 messages (`reports/erc.rpt`) |
| DRC | 0 violations, 0 unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. Order quantities come in multiples of 3. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `kikit_pcbway/bom.csv` and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `kikit_jlcpcb/bom.csv` and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `eib_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |

The silkscreen labels only the parts whose reference sits at the part. The other 14 top-side SMD parts are shown, with reference and value, on the pages of `assembly/guide/` (`assembly/guide/README.md` lists each part and its page; D-97). No label of a top-side SMD part is on the bottom.

The E-pad landing labels ("E8 TP49" ... "E6 DNP"; E1 reads "E1 JP12.1", the square REGN post) are on B.Silkscreen only (D-73, D-86). The top side carries only the E-pad numbers beside the pads ("E8", "E3", "4", "E2", "E7", "E1", "E5", "E6"; D-86). Read the landing labels, or tag each E lead, before the EIB is mounted on its standoffs.

## 3. Contents

| Folder or file | Content |
|---|---|
| `gerbers/` | Gerber X2: copper, mask, paste, silkscreen, Edge.Cuts, job file |
| `drill/` | Excellon PTH and NPTH files, drill maps (PDF and Gerber X2) |
| `assembly/eib-pos.csv` | pick-and-place, both sides, mm, DNP parts excluded |
| `assembly/eib-bom.csv` | grouped BOM with MPN, manufacturer and DNP columns |
| `assembly/eib_ibom.html` | InteractiveHtmlBom (open in a browser); DNP parts left out of the BOM table |
| `assembly/guide/` | assembly guide (D-97): rendered top views that mark the parts without a silkscreen label at the part, with `README.md` (part, status, page) |
| `docs/eib-schematic.pdf` | schematic, laid out in functional blocks |
| `docs/eib-pcb.pdf` | one page per copper, silkscreen, fab and mask layer |
| `docs/eib.step` | 3D model |
| `docs/eib.net` | netlist exported from the schematic |
| `kikit_*` | KiKit 1.8.1 `fab jlcpcb`, `fab pcbway`, `fab oshpark` outputs |
| `reports/` | ERC, DRC and KiKit logs |

The per-unit BOMs and the Digi-Key and Mouser import files are in `hardware/charger_evm_r8/bom_2026-11-14/`
(its `README.md` gives the order instructions and the optional alternate lines). The layout
decisions and the open `TODO(verify)` items are in `hardware/charger_evm_r8/LAYOUT_DECISIONS.md`.

## 4. Before you order

1. Read `LAYOUT_DECISIONS.md` section 10 (proposed design changes) and section 11 (open TODO(verify) items).
2. Confirm the copper weight and the fab rule items marked `TODO(verify)` in `tools/pcb/fab_rules`.
3. Do not order until the operator has reviewed this package and the ordering BOM.
4. Do not fit the DNP parts of section 5.

## 5. DNP set

The parts below carry the KiCad DNP attribute in the schematic and on the board; on the board they also carry
"exclude from position files". The DNP attribute drives every assembly output of this package:
`assembly/eib-pos.csv` and the KiKit `pos.csv` files omit the parts, `assembly/eib-bom.csv` lists them on
separate rows with the `DNP` column set, the KiKit `bom.csv` files omit them, `assembly/eib_ibom.html` leaves
them out of its BOM table, and `docs/eib-pcb.pdf` crosses them out on the fab layers. The footprints stay on the board, so
the copper and mask layers still carry their pads. Each DNP footprint carries a -2.0 mm solder-paste margin (REVIEW_2026-11-14 EIB-7, `gen/eib_dnp_paste.py`), so F.Paste and the stencil have no aperture on the DNP pads.

| Item | Parts |
|---|---|
| DNP (14) | C203, C204, E4, E6, R258, R259, R260, R261, R262, R263, R264, R265, U203, U204 |
| Fitted (32) | C201, C202, C205, E1, E2, E3, E5, E7, E8, J201, Q201, Q202, Q203, R250, R251, R252, R253, R254, R255, R257, R266, R267, R268, R269, R270, R271, R273, R274, R275, R276, U201, U202 |

The EIB DNP set is operator decision dec2-eib (`decisions_2026-11-12/round2/dec2_eib_2026-11-12.md`, D-49). E4
(ILIM sense) and E6 (/CE sense) are lead pads: their leads are not built and the pads stay unconnected. Since D-66,
R265.2 and R264.2 are not connected (J201.11 and J201.13 no longer exist).

## 6. Copper and drill comparison

Every Gerber and Excellon file of this package was compared line by line with `fab/eib_2026-11-14`,
with the creation-date lines ignored. Result: DIFFERENCES FOUND, each with the recorded reason below.

| File | Result | Reason |
|---|---|---|
| `gerbers/eib-B_Cu.gbl` | identical (3097 lines) |  |
| `gerbers/eib-B_Mask.gbs` | identical (957 lines) |  |
| `gerbers/eib-B_Paste.gbp` | identical (13 lines) |  |
| `gerbers/eib-B_Silkscreen.gbo` | DIFFERENT | expected: D-97, the 8 bottom reference texts of top-side SMD parts (C201, C202, R251, R252, R254, R271, U201, U202) removed; only the eight E landing labels remain |
| `gerbers/eib-Edge_Cuts.gm1` | identical (24 lines) |  |
| `gerbers/eib-F_Cu.gtl` | identical (5529 lines) |  |
| `gerbers/eib-F_Mask.gts` | identical (6093 lines) |  |
| `gerbers/eib-F_Paste.gtp` | identical (169 lines) |  |
| `gerbers/eib-F_Silkscreen.gto` | DIFFERENT | expected: D-97, the Q202 reference (MARGINAL) moved to F.Fab |
| `gerbers/eib-job.gbrjob` | identical (131 lines) |  |
| `drill/eib-NPTH-drl_map.gbr` | identical (920 lines) |  |
| `drill/eib-NPTH.drl` | identical (15 lines) |  |
| `drill/eib-PTH-drl_map.gbr` | identical (1855 lines) |  |
| `drill/eib-PTH.drl` | identical (126 lines) |  |

The other files of this package also differ from the reference package; they are not compared line by line. D-82
set the Value, MPN and Manufacturer fields to the ordered BOM (CR: for example C110 50 V to 100 V and C102b X7S to
X7R; EIB: for example C201 50 V to 100 V). The assembly BOM therefore differs in those three fields, and the position
file differs in the Value field only; every reference, footprint, position, rotation and side is identical. The iBOM, the schematic, PCB and STEP files of `docs/`, the netlist, the drill-map PDFs, the KiKit outputs
and the DRC and ERC reports are regenerated from the same boards and carry the same field, silkscreen and pour-fill
changes, or only new creation dates. `reports/npth_check.txt` is new in this package.
