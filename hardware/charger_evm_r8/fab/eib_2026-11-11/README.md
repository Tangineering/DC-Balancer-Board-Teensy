# EIB, EVM interface board: fabrication package (2026-11-11)

## 1. Board

| Item | Value |
|---|---|
| Layers | 2 (F.Cu, B.Cu (AGND pour)) |
| Size | 24.0 x 38.0 mm (D-13 / P-05; A.9 states 36.0 x 24.0 mm) |
| Thickness | 1.6 mm |
| Copper | 1 oz |
| Surface finish | ENIG |
| Quantity | 5 (E BOM, may share the CR panel) |
| Solder mask / silkscreen | both sides; every via tented on both sides |
| Design rules | `tools/pcb/fab_rules/fab_2layer_oshpark_pcbway.kicad_dru` (0.1524 mm track/space, 0.254 mm minimum hole, 0.15 mm annular ring, 0.381 mm copper to edge) |
| ERC | 0 messages (`reports/erc.rpt`) |
| DRC | 0 violations, 0 unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. Its 4-layer service is 1 oz outer / 0.5 oz inner, so a 2-layer order there uses the 1 oz fallback of the Copper row above. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `kikit_pcbway/bom.csv` and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `kikit_jlcpcb/bom.csv` and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `eib_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |

The CR needs a hot-air or reflow step for U101 (VQFN-24, A.8 hand assembly row), or a PCB assembly service.

## 3. Contents

| Folder or file | Content |
|---|---|
| `gerbers/` | Gerber X2: copper, mask, paste, silkscreen, Edge.Cuts, job file |
| `drill/` | Excellon PTH and NPTH files, drill maps (PDF and Gerber X2) |
| `assembly/eib-pos.csv` | pick-and-place, both sides, mm, DNP parts excluded |
| `assembly/eib-bom.csv` | grouped BOM with MPN, manufacturer and DNP columns |
| `assembly/eib_ibom.html` | InteractiveHtmlBom (open in a browser) |
| `docs/eib-schematic.pdf` | schematic |
| `docs/eib-pcb.pdf` | one page per copper, silkscreen, fab and mask layer |
| `docs/eib.step` | 3D model |
| `docs/eib.net` | netlist exported from the schematic |
| `kikit_*` | KiKit 1.8.1 `fab jlcpcb`, `fab pcbway`, `fab oshpark` outputs |
| `reports/` | ERC, DRC and KiKit logs |

The ordering BOM with vendor rows is `hardware/charger_evm_r8/bom_2026-11-11/ordering_bom.csv`. The layout
decisions and the open `TODO(verify)` items are in `hardware/charger_evm_r8/LAYOUT_DECISIONS.md`.

## 4. Before you order

1. Read `LAYOUT_DECISIONS.md` section 9 (proposed design changes) and section 10 (open items).
2. Confirm the copper weight and the fab rule items marked `TODO(verify)` in `tools/pcb/fab_rules`.
3. Do not order until the operator has reviewed this package and the ordering BOM.
