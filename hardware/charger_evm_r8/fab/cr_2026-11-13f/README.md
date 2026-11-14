# CR, CHG adapter carrier (plug-on): fabrication package (2026-11-13f)

**Status: not ordered.** This package awaits operator review before order. The fab is OSH Park (operator ruling 2026-11-12). The routing is D-58; the outline is D-62 and the 6-32 holes are D-60; the GND stitching and straightened tracks are D-61; the reference designators are D-59 (`cr/silk_refs.md` lists those on F.Fab only). After the operator's routing cleanup in KiCad (`547dc11`), the short In2 via pairs were merged onto F.Cu and three /GND stitching vias at J101 and C129 were deleted (D-65, `gen/via_merge_cr.py`). J101 is a 3 x 3 grid of plated wire pads for the soldered W5 wires; the FTSH header and the ribbon are retired (D-66, `gen/swap_wire9.py`). U101 is the Toshiba TCKE1401NM on the unchanged footprint, with R101 8.45k, R103 64.9k and R104 51.1k (D-67); the copper equals the D-66 package `fab/cr_2026-11-13d/`. The U101 exposed-pad paste windows follow the via keep-outs, about 55 % coverage, for a 4 mil stainless OSH Stencils stencil (D-69).

## 1. Board

| Item | Value |
|---|---|
| Layers | 4 (F.Cu (L1, signals and power pours), In1.Cu (L2, solid GND), In2.Cu (L3, signals), B.Cu (L4, solid GND facing the MB, D-20)) |
| Size | 10-corner outline with 1.0 mm corner fillets, edges at 0/30/45/60/90/120/135/150 degrees (D-62), 40.02 x 64.81 mm bounding box (MB frame x 18.58-58.60, y 7.83-72.64), 2327.7 mm2, trimmed after routing inside the D-39 rectangle; four 6-32 NPTH holes, 3.70 mm (MH1-MH4, D-60) |
| Thickness | 1.6 mm |
| Copper | 1 oz outer / 0.5 oz inner (D-29) |
| Surface finish | ENIG |
| Quantity | 6 (operator ruling 2026-11-13: "Use 6"; OSH Park sells boards in multiples of 3; the E BOM asks for 5) |
| Solder mask / silkscreen | both sides; every via tented on both sides |
| Design rules | `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` (0.1524 mm track/space, 0.254 mm minimum hole, 0.15 mm annular ring, 0.381 mm copper to edge) |
| ERC | 0 messages (`reports/erc.rpt`) |
| DRC | 0 violations, 0 unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. Its 4-layer service (1.6 mm, 1 oz outer / 0.5 oz inner clad, ENIG, FR408-HR) matches section 1 (docs.oshpark.com/services/four-layer/, read 2026-11-13). Order quantities come in multiples of 3. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `kikit_pcbway/bom.csv` and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `kikit_jlcpcb/bom.csv` and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `cr_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |

The CR needs a hot-air or reflow step for U101 (TCKE1401NM, VQFN24D, 0.5 mm pitch, A.8 hand assembly row), or a PCB assembly service.

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

The per-unit BOMs and the Digi-Key import file are in `hardware/charger_evm_r8/bom_2026-11-13/`
(`PREORDER_REVIEW.md` there lists the items to settle before each order). The layout
decisions and the open `TODO(verify)` items are in `hardware/charger_evm_r8/LAYOUT_DECISIONS.md`.

## 4. Before you order

1. Read `LAYOUT_DECISIONS.md` section 10 (proposed design changes) and section 11 (open TODO(verify) items).
2. Confirm the copper weight and the fab rule items marked `TODO(verify)` in `tools/pcb/fab_rules`.
3. Do not order until the operator has reviewed this package and the ordering BOM.

## 6. Copper and drill comparison

Every Gerber and Excellon file of this package was compared line by line with `fab/cr_2026-11-13e`,
with the creation-date lines ignored. Result: DIFFERENCES FOUND.

| File | Result |
|---|---|
| `gerbers/cr-B_Cu.gbl` | identical (8780 lines) |
| `gerbers/cr-B_Mask.gbs` | identical (2255 lines) |
| `gerbers/cr-B_Paste.gbp` | identical (13 lines) |
| `gerbers/cr-B_Silkscreen.gbo` | identical (2269 lines) |
| `gerbers/cr-Edge_Cuts.gm1` | identical (86 lines) |
| `gerbers/cr-F_Cu.gtl` | identical (14095 lines) |
| `gerbers/cr-F_Mask.gts` | identical (12519 lines) |
| `gerbers/cr-F_Paste.gtp` | DIFFERENT |
| `gerbers/cr-F_Silkscreen.gto` | identical (17514 lines) |
| `gerbers/cr-In1_Cu.g1` | identical (8497 lines) |
| `gerbers/cr-In2_Cu.g2` | identical (1798 lines) |
| `gerbers/cr-job.gbrjob` | identical (169 lines) |
| `drill/cr-NPTH-drl_map.gbr` | identical (1664 lines) |
| `drill/cr-NPTH.drl` | identical (22 lines) |
| `drill/cr-PTH-drl_map.gbr` | identical (6112 lines) |
| `drill/cr-PTH.drl` | identical (510 lines) |
