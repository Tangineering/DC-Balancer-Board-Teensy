# EIB, EVM interface board: fabrication package (2026-11-13)

**Status: not ordered.** This package awaits operator review before order (dec2-eib decision 1, 2026-11-12).

## 1. Board

| Item | Value |
|---|---|
| Layers | 2 (F.Cu, B.Cu (AGND pour)) |
| Size | 24.0 x 38.0 mm (D-13 / P-05; A.9 states 36.0 x 24.0 mm) |
| Thickness | 1.6 mm |
| Copper | 1 oz |
| Surface finish | ENIG |
| Quantity | 5 (E BOM; a separate 2-layer order at OSH Park) |
| Solder mask / silkscreen | both sides; every via tented on both sides |
| Design rules | `tools/pcb/fab_rules/fab_2layer_oshpark_pcbway.kicad_dru` (0.1524 mm track/space, 0.254 mm minimum hole, 0.15 mm annular ring, 0.381 mm copper to edge) |
| ERC | 0 messages (`reports/erc.rpt`) |
| DRC | 0 violations, 0 unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. Order quantities come in multiples of 3. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `kikit_pcbway/bom.csv` and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `kikit_jlcpcb/bom.csv` and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `eib_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |

## 3. Contents

| Folder or file | Content |
|---|---|
| `gerbers/` | Gerber X2: copper, mask, paste, silkscreen, Edge.Cuts, job file |
| `drill/` | Excellon PTH and NPTH files, drill maps (PDF and Gerber X2) |
| `assembly/eib-pos.csv` | pick-and-place, both sides, mm, DNP parts excluded |
| `assembly/eib-bom.csv` | grouped BOM with MPN, manufacturer and DNP columns |
| `assembly/eib_ibom.html` | InteractiveHtmlBom (open in a browser); DNP parts left out of the BOM table |
| `docs/eib-schematic.pdf` | schematic |
| `docs/eib-pcb.pdf` | one page per copper, silkscreen, fab and mask layer |
| `docs/eib.step` | 3D model |
| `docs/eib.net` | netlist exported from the schematic |
| `kikit_*` | KiKit 1.8.1 `fab jlcpcb`, `fab pcbway`, `fab oshpark` outputs |
| `reports/` | ERC, DRC and KiKit logs |

The ordering BOM with vendor rows is `hardware/charger_evm_r8/bom_2026-11-11/ordering_bom.csv`. The layout
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
the copper, mask and paste layers still carry their pads; a paste stencil prints on the empty DNP pads.

| Item | Parts |
|---|---|
| DNP (14) | C203, C204, E4, E6, R258, R259, R260, R261, R262, R263, R264, R265, U203, U204 |
| Fitted (32) | C201, C202, C205, E1, E2, E3, E5, E7, E8, J201, Q201, Q202, Q203, R250, R251, R252, R253, R254, R255, R257, R266, R267, R268, R269, R270, R271, R273, R274, R275, R276, U201, U202 |

The EIB DNP set is operator decision dec2-eib (`decisions_2026-11-12/round2/dec2_eib_2026-11-12.md`, D-49). E4
(ILIM sense) and E6 (/CE sense) are lead pads: their leads are not built and the pads stay unconnected. J201.11
and J201.13 end on the empty R265 and R264 pads.

## 6. Copper and drill comparison

Every Gerber and Excellon file of this package was compared line by line with `fab/eib_2026-11-11`,
with the creation-date lines ignored. Result: all files identical.

| File | Result |
|---|---|
| `gerbers/eib-B_Cu.gbl` | identical (2454 lines) |
| `gerbers/eib-B_Mask.gbs` | identical (645 lines) |
| `gerbers/eib-B_Paste.gbp` | identical (13 lines) |
| `gerbers/eib-B_Silkscreen.gbo` | identical (913 lines) |
| `gerbers/eib-Edge_Cuts.gm1` | identical (24 lines) |
| `gerbers/eib-F_Cu.gtl` | identical (1402 lines) |
| `gerbers/eib-F_Mask.gts` | identical (6117 lines) |
| `gerbers/eib-F_Paste.gtp` | identical (253 lines) |
| `gerbers/eib-F_Silkscreen.gto` | identical (6415 lines) |
| `gerbers/eib-job.gbrjob` | identical (126 lines) |
| `drill/eib-NPTH-drl_map.gbr` | identical (920 lines) |
| `drill/eib-NPTH.drl` | identical (15 lines) |
| `drill/eib-PTH-drl_map.gbr` | identical (1631 lines) |
| `drill/eib-PTH.drl` | identical (76 lines) |
