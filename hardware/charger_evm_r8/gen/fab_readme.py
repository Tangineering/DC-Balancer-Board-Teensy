"""Write fab/<board>_<date>/README.md: which files go to which fab, with the board figures.
Usage: python fab_readme.py <cr|eib> <date> [<reference package dir>]

The DNP section lists the parts that carry the schematic dnp attribute in docs/<board>.net. With a reference
package (for example fab/eib_2026-11-11), the README also records a comparison of every Gerber and Excellon file
against that package, with the creation-date lines ignored."""
import os
import re
import sys

B, D = sys.argv[1], sys.argv[2]
REF = sys.argv[3] if len(sys.argv) > 3 else None
O = os.path.join("fab", "%s_%s" % (B, D))


def dnp_split():
    """(dnp refs, fitted refs) from the exported netlist; dnp = a (property (name "dnp")) on the component."""
    net = open(os.path.join(O, "docs", "%s.net" % B), encoding="utf-8").read()
    dnp, fit = [], []
    for blk in re.findall(r"\(comp \(ref \"([^\"]+)\"\)(.*?)\(tstamps", net, re.S):
        (dnp if '(property (name "dnp"))' in blk[1] else fit).append(blk[0])
    key = lambda r: (re.sub(r"\d+", "", r), int(re.sub(r"\D", "", r) or 0))
    return sorted(dnp, key=key), sorted(fit, key=key)


def compare(ref):
    """Rows (file, result) for every Gerber/Excellon file of this package against the reference package."""
    skip = re.compile(r"CreationDate|Created by KiCad|; DRILL file \{")
    rows = []
    for sub in ("gerbers", "drill"):
        for f in sorted(os.listdir(os.path.join(O, sub))):
            if f.endswith(".pdf"):
                continue
            a, b = os.path.join(ref, sub, f), os.path.join(O, sub, f)
            if not os.path.isfile(a):
                rows.append((sub + "/" + f, "not in the reference package"))
                continue
            la = [x for x in open(a, encoding="utf-8").read().splitlines() if not skip.search(x)]
            lb = [x for x in open(b, encoding="utf-8").read().splitlines() if not skip.search(x)]
            rows.append((sub + "/" + f, "identical (%d lines)" % len(lb) if la == lb else "DIFFERENT"))
    return rows
drc = open(os.path.join(O, "reports", "drc.rpt"), encoding="utf-8").read()
erc = open(os.path.join(O, "reports", "erc.rpt"), encoding="utf-8").read()
nv = re.search(r"Found (\d+) DRC violations", drc)
nu = re.search(r"Found (\d+) unconnected pads", drc)
ne = re.search(r"ERC messages: (\d+)", erc)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cr_geometry as G  # noqa: E402   (the D-60 outline and holes; the size row is computed, never typed)
_b = G.P_FINAL.bounds
CR_SIZE = ("%d-corner outline with %.1f mm corner fillets, edges at %s degrees (D-62), %.2f x %.2f mm bounding box "
           "(MB frame x %.2f-%.2f, y %.2f-%.2f), %.1f mm2, trimmed after routing inside the D-39 rectangle; four 6-32 "
           "NPTH holes, %.2f mm (MH1-MH4, D-60)" % (
               len(G.FINAL_OUTLINE), G.FILLET, "/".join(str(a) for a in G.TRIM_ANGLES), _b[2] - _b[0], _b[3] - _b[1],
               _b[0], _b[2], _b[1], _b[3], G.P_FINAL.area, G.HOLE_DRILL))
INFO = {
    "cr": dict(name="CR, CHG adapter carrier (plug-on)", layers=4, size=CR_SIZE, thick="1.6 mm",
               copper="1 oz outer / 0.5 oz inner (D-29)", finish="ENIG", qty="5 (E BOM)",
               layers_list="F.Cu (L1, signals and power pours), In1.Cu (L2, solid GND), In2.Cu (L3, signals), "
               "B.Cu (L4, solid GND facing the MB, D-20)"),
    "eib": dict(name="EIB, EVM interface board", layers=2, size="24.0 x 38.0 mm (D-13 / P-05; A.9 states 36.0 x 24.0 mm)",
                thick="1.6 mm", copper="1 oz", finish="ENIG", qty="5 (E BOM; a separate 2-layer order at OSH Park)",
                layers_list="F.Cu, B.Cu (AGND pour)"),
}[B]
DNP, FIT = dnp_split()
# the rule file each board is checked against (cr/cr.kicad_dru is a copy of the OSH Park-only file, D-29, D-55)
RULES = {"cr": "fab_4layer_oshpark_only.kicad_dru", "eib": "fab_2layer_oshpark_pcbway.kicad_dru"}[B]
STATUS = ("**Status: not ordered.** This package awaits operator review before order (dec2-eib decision 1, "
          "2026-11-12).\n\n" if B == "eib" else
          "**Status: not ordered.** This package awaits operator review before order. The fab is OSH Park (operator "
          "ruling 2026-11-12). The routing is D-58; the outline is D-62 and the 6-32 holes are D-60; the GND stitching "
          "and straightened tracks are D-61; the reference designators are D-59 (`cr/silk_refs.md` lists those on F.Fab "
          "only).\n\n")
ASSY = ("\nThe CR needs a hot-air or reflow step for U101 (VQFN-24, A.8 hand assembly row), or a PCB assembly "
        "service.\n" if B == "cr" else "")
for _fab in ("jlcpcb", "pcbway"):
    if not os.path.exists(os.path.join(O, "kikit_" + _fab, "bom.csv")):
        ASSY += (f"\nKiKit `fab {_fab} --assembly` wrote no `bom.csv` for this board (`reports/kikit_{_fab}.log`: "
                 f"\"invalid literal for int()\"); its `gerbers.zip` is complete. Use `assembly/{B}-bom.csv` for "
                 f"assembly quotes.\n")
txt = f"""# {INFO['name']}: fabrication package ({D})

{STATUS}## 1. Board

| Item | Value |
|---|---|
| Layers | {INFO['layers']} ({INFO['layers_list']}) |
| Size | {INFO['size']} |
| Thickness | {INFO['thick']} |
| Copper | {INFO['copper']} |
| Surface finish | {INFO['finish']} |
| Quantity | {INFO['qty']} |
| Solder mask / silkscreen | both sides; every via tented on both sides |
| Design rules | `tools/pcb/fab_rules/{RULES}` (0.1524 mm track/space, 0.254 mm minimum hole, 0.15 mm annular ring, 0.381 mm copper to edge) |
| ERC | {ne.group(1) if ne else '?'} messages (`reports/erc.rpt`) |
| DRC | {nv.group(1) if nv else '?'} violations, {nu.group(1) if nu else '?'} unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. {"Its 4-layer service (1.6 mm, 1 oz outer / 0.5 oz inner clad, ENIG, FR408-HR) matches section 1 (docs.oshpark.com/services/four-layer/, read 2026-11-13). " if B == "cr" else ""}Order quantities come in multiples of 3. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also `kikit_pcbway/bom.csv` and `kikit_pcbway/pos.csv` | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also `kikit_jlcpcb/bom.csv` and `kikit_jlcpcb/pos.csv` | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
| Any other fab | `{B}_gerbers_drill.zip` (Gerber X2 layers, Excellon PTH and NPTH, drill maps) | Same files as `gerbers/` and `drill/`. |
{ASSY}
## 3. Contents

| Folder or file | Content |
|---|---|
| `gerbers/` | Gerber X2: copper, mask, paste, silkscreen, Edge.Cuts, job file |
| `drill/` | Excellon PTH and NPTH files, drill maps (PDF and Gerber X2) |
| `assembly/{B}-pos.csv` | pick-and-place, both sides, mm, DNP parts excluded |
| `assembly/{B}-bom.csv` | grouped BOM with MPN, manufacturer and DNP columns |
| `assembly/{B}_ibom.html` | InteractiveHtmlBom (open in a browser); DNP parts left out of the BOM table |
| `docs/{B}-schematic.pdf` | schematic |
| `docs/{B}-pcb.pdf` | one page per copper, silkscreen, fab and mask layer |
| `docs/{B}.step` | 3D model |
| `docs/{B}.net` | netlist exported from the schematic |
| `kikit_*` | KiKit 1.8.1 `fab jlcpcb`, `fab pcbway`, `fab oshpark` outputs |
| `reports/` | ERC, DRC and KiKit logs |

The ordering BOM with vendor rows is `hardware/charger_evm_r8/bom_2026-11-11/ordering_bom.csv`. The layout
decisions and the open `TODO(verify)` items are in `hardware/charger_evm_r8/LAYOUT_DECISIONS.md`.

## 4. Before you order

1. Read `LAYOUT_DECISIONS.md` section 10 (proposed design changes) and section 11 (open TODO(verify) items).
2. Confirm the copper weight and the fab rule items marked `TODO(verify)` in `tools/pcb/fab_rules`.
3. Do not order until the operator has reviewed this package and the ordering BOM.
"""
if DNP:
    txt += "4. Do not fit the DNP parts of section 5.\n"
    txt += f"""
## 5. DNP set

The parts below carry the KiCad DNP attribute in the schematic and on the board; on the board they also carry
"exclude from position files". The DNP attribute drives every assembly output of this package:
`assembly/{B}-pos.csv` and the KiKit `pos.csv` files omit the parts, `assembly/{B}-bom.csv` lists them on
separate rows with the `DNP` column set, the KiKit `bom.csv` files omit them, `assembly/{B}_ibom.html` leaves
them out of its BOM table, and `docs/{B}-pcb.pdf` crosses them out on the fab layers. The footprints stay on the board, so
the copper, mask and paste layers still carry their pads; a paste stencil prints on the empty DNP pads.

| Item | Parts |
|---|---|
| DNP ({len(DNP)}) | {', '.join(DNP)} |
| Fitted ({len(FIT)}) | {', '.join(FIT)} |
"""
    if B == "eib":
        txt += """
The EIB DNP set is operator decision dec2-eib (`decisions_2026-11-12/round2/dec2_eib_2026-11-12.md`, D-49). E4
(ILIM sense) and E6 (/CE sense) are lead pads: their leads are not built and the pads stay unconnected. J201.11
and J201.13 end on the empty R265 and R264 pads.
"""
if REF:
    rows = compare(REF)
    same = all(r[1].startswith("identical") for r in rows)
    txt += f"""
## 6. Copper and drill comparison

Every Gerber and Excellon file of this package was compared line by line with `{REF.replace(os.sep, '/')}`,
with the creation-date lines ignored. Result: {'all files identical' if same else 'DIFFERENCES FOUND'}.

| File | Result |
|---|---|
""" + "".join("| `%s` | %s |\n" % r for r in rows)
open(os.path.join(O, "README.md"), "w", encoding="utf-8", newline="\n").write(txt)
print("wrote", os.path.join(O, "README.md"))
