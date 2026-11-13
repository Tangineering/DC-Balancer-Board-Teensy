"""Write fab/<board>_<date>/README.md: which files go to which fab, with the board figures.
Usage: python fab_readme.py <cr|eib> <date>"""
import os
import re
import sys

B, D = sys.argv[1], sys.argv[2]
O = os.path.join("fab", "%s_%s" % (B, D))
drc = open(os.path.join(O, "reports", "drc.rpt"), encoding="utf-8").read()
erc = open(os.path.join(O, "reports", "erc.rpt"), encoding="utf-8").read()
nv = re.search(r"Found (\d+) DRC violations", drc)
nu = re.search(r"Found (\d+) unconnected pads", drc)
ne = re.search(r"ERC messages: (\d+)", erc)
INFO = {
    "cr": dict(name="CR, CHG adapter carrier (plug-on)", layers=4, size="48.416 x 87.000 mm rectangle (D-39, MB frame "
               "x 18.584-67, y 7-94), 4212.19 mm2, no hole (D-42)", thick="1.6 mm",
               copper="1 oz outer / 0.5 oz inner (D-29)", finish="ENIG", qty="5 (E BOM)",
               layers_list="F.Cu (L1, signals and power pours), In1.Cu (L2, solid GND), In2.Cu (L3, signals), "
               "B.Cu (L4, solid GND facing the MB, D-20)"),
    "eib": dict(name="EIB, EVM interface board", layers=2, size="24.0 x 38.0 mm (D-13 / P-05; A.9 states 36.0 x 24.0 mm)",
                thick="1.6 mm", copper="1 oz", finish="ENIG", qty="5 (E BOM, may share the CR panel)",
                layers_list="F.Cu, B.Cu (AGND pour)"),
}[B]
txt = f"""# {INFO['name']}: fabrication package ({D})

## 1. Board

| Item | Value |
|---|---|
| Layers | {INFO['layers']} ({INFO['layers_list']}) |
| Size | {INFO['size']} |
| Thickness | {INFO['thick']} |
| Copper | {INFO['copper']} |
| Surface finish | {INFO['finish']} |
| Quantity | {INFO['qty']} |
| Solder mask / silkscreen | both sides; every via tented on both sides |
| Design rules | `tools/pcb/fab_rules/fab_{INFO['layers']}layer_oshpark_pcbway.kicad_dru` (0.1524 mm track/space, 0.254 mm minimum hole, 0.15 mm annular ring, 0.381 mm copper to edge) |
| ERC | {ne.group(1) if ne else '?'} messages (`reports/erc.rpt`) |
| DRC | {nv.group(1) if nv else '?'} violations, {nu.group(1) if nu else '?'} unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. Its 4-layer service is 1 oz outer / 0.5 oz inner, so a {INFO['layers']}-layer order there uses the 1 oz fallback of the Copper row above. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `kikit_pcbway/bom.csv` and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `kikit_jlcpcb/bom.csv` and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `{B}_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |

The CR needs a hot-air or reflow step for U101 (VQFN-24, A.8 hand assembly row), or a PCB assembly service.

## 3. Contents

| Folder or file | Content |
|---|---|
| `gerbers/` | Gerber X2: copper, mask, paste, silkscreen, Edge.Cuts, job file |
| `drill/` | Excellon PTH and NPTH files, drill maps (PDF and Gerber X2) |
| `assembly/{B}-pos.csv` | pick-and-place, both sides, mm, DNP parts excluded |
| `assembly/{B}-bom.csv` | grouped BOM with MPN, manufacturer and DNP columns |
| `assembly/{B}_ibom.html` | InteractiveHtmlBom (open in a browser) |
| `docs/{B}-schematic.pdf` | schematic |
| `docs/{B}-pcb.pdf` | one page per copper, silkscreen, fab and mask layer |
| `docs/{B}.step` | 3D model |
| `docs/{B}.net` | netlist exported from the schematic |
| `kikit_*` | KiKit 1.8.1 `fab jlcpcb`, `fab pcbway`, `fab oshpark` outputs |
| `reports/` | ERC, DRC and KiKit logs |

The ordering BOM with vendor rows is `hardware/charger_evm_r8/bom_2026-11-11/ordering_bom.csv`. The layout
decisions and the open `TODO(verify)` items are in `hardware/charger_evm_r8/LAYOUT_DECISIONS.md`.

## 4. Before you order

1. Read `LAYOUT_DECISIONS.md` section 9 (proposed design changes) and section 10 (open items).
2. Confirm the copper weight and the fab rule items marked `TODO(verify)` in `tools/pcb/fab_rules`.
3. Do not order until the operator has reviewed this package and the ordering BOM.
"""
open(os.path.join(O, "README.md"), "w", encoding="utf-8", newline="\n").write(txt)
print("wrote", os.path.join(O, "README.md"))
