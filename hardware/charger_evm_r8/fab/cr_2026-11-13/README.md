# CR, CHG adapter carrier (plug-on): fabrication package (2026-11-13)

**Status: not ordered.** This package awaits operator review before order. The fab is OSH Park (operator ruling 2026-11-12). The routing is D-58; the reference designators are D-59, with 18 references on F.Fab only.

## 1. Board

| Item | Value |
|---|---|
| Layers | 4 (F.Cu (L1, signals and power pours), In1.Cu (L2, solid GND), In2.Cu (L3, signals), B.Cu (L4, solid GND facing the MB, D-20)) |
| Size | 48.416 x 87.000 mm rectangle (D-39, MB frame x 18.584-67, y 7-94), 4212.19 mm2, no mounting hole (D-42) |
| Thickness | 1.6 mm |
| Copper | 1 oz outer / 0.5 oz inner (D-29) |
| Surface finish | ENIG |
| Quantity | 5 (E BOM) |
| Solder mask / silkscreen | both sides; every via tented on both sides |
| Design rules | `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` (0.1524 mm track/space, 0.254 mm minimum hole, 0.15 mm annular ring, 0.381 mm copper to edge) |
| ERC | 0 messages (`reports/erc.rpt`) |
| DRC | 0 violations, 0 unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. Its 4-layer service is 1 oz outer / 0.5 oz inner, so a 4-layer order there uses the 1 oz fallback of the Copper row above. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `kikit_pcbway/bom.csv` and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `kikit_jlcpcb/bom.csv` and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `cr_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |

The CR needs a hot-air or reflow step for U101 (VQFN-24, A.8 hand assembly row), or a PCB assembly service.

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

The ordering BOM with vendor rows is `hardware/charger_evm_r8/bom_2026-11-11/ordering_bom.csv`. The layout
decisions and the open `TODO(verify)` items are in `hardware/charger_evm_r8/LAYOUT_DECISIONS.md`.

## 4. Before you order

1. Read `LAYOUT_DECISIONS.md` section 10 (proposed design changes) and section 11 (open TODO(verify) items).
2. Confirm the copper weight and the fab rule items marked `TODO(verify)` in `tools/pcb/fab_rules`.
3. Do not order until the operator has reviewed this package and the ordering BOM.
