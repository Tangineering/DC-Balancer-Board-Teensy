"""Write fab/<board>_<date>/README.md: which files go to which fab, with the board figures.
Usage: python fab_readme.py <cr|eib> <date> [<reference package dir>]

The DNP section lists the parts that carry the schematic dnp attribute in docs/<board>.net. With a reference
package (for example fab/eib_2026-11-11), the README also records a comparison of every Gerber and Excellon file
against that package, with the creation-date lines ignored, and gives the recorded reason for each file that differs
(REASONS; fix round 2026-11-15, check1 issue 2). Re-run this script after any edit of it: it rewrites only the README,
so no re-export is necessary."""
import json
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
                rows.append((sub + "/" + f, "not in the reference package", ""))
                continue
            la = [x for x in open(a, encoding="utf-8").read().splitlines() if not skip.search(x)]
            lb = [x for x in open(b, encoding="utf-8").read().splitlines() if not skip.search(x)]
            if la == lb:
                rows.append((sub + "/" + f, "identical (%d lines)" % len(lb), ""))
            else:
                why = REASONS.get((os.path.basename(os.path.normpath(ref)), f.split("-", 1)[1]),
                                  "NO RECORDED REASON: investigate before the order")
                rows.append((sub + "/" + f, "DIFFERENT", why))
    return rows


# The recorded reason for each file that differs from the reference package, keyed by (reference package, file name
# without the board prefix). Source: update_2026-11-14/notes_phaseB_export.md section 5 (text and shapely region XOR
# of the Gerbers). A difference with no entry prints "NO RECORDED REASON".
_SILK_CR_B = ("expected: silkscreen edits D-72 to D-78 (pin-1 dots and SMA cathode bars, the J101 map and W-lead labels, "
              "the reference moves, the board marking \"CR r8 2026-11-14\")")
# Phase C fix round (2026-11-15, REVIEW2 issue list): D-85 touched F.Silkscreen only, so only the F row names it.
_SILK_CR = (_SILK_CR_B + " and phase C D-85 (F.Silkscreen only: the "
            "W1 \"VIN1\" and W2 \"GND\" input-pair texts and the W1 reference moved to the W1 side, REVIEW2 R2-INT-0)")
_SILK_EIB = ("expected: silkscreen edits D-72 to D-74 and D-78 (pin-1 dots, the J201 map on F.Silkscreen, the E "
             "landing labels on B.Silkscreen, the reference moves, the board marking \"EIB r8 2026-11-14\") and phase C "
             "D-86 (F.Silkscreen: the E-pad numbers E8, E3, 4, E2, E7, E1, E5, E6 beside the pads; B.Silkscreen: the "
             "E1 label reads \"E1 JP12.1\" and the E2, E7 and E1 labels take 0.6 mm characters and the E8 and E2 labels "
             "move toward +x, so that each keeps 0.80 mm from the bottom references; REVIEW2 R2-INT-7, R2-EIL-0 to "
             "R2-EIL-2)")
REASONS = {
    ("cr_2026-11-13f", "F_Cu.gtl"): "expected: pour fill only. The D-75 solid connection of J1 pin 18 (/VCHG) replaces "
        "its thermal relief: region XOR 2.698 mm2 added and 0.203 mm2 removed, all within 1.7 mm of pad 18. Tracks, "
        "vias and pads are unchanged (update_2026-11-14/notes_phaseB_export.md section 5.1)",
    ("cr_2026-11-13f", "F_Silkscreen.gto"): _SILK_CR,
    ("cr_2026-11-13f", "B_Silkscreen.gbo"): _SILK_CR_B,
    ("cr_2026-11-13f", "job.gbrjob"): "expected: D-76, finish ENIG and the OSH Park stack-up (materials, colours and "
        "thicknesses, section 1 stack-up row)",
    ("eib_2026-11-13c", "F_Cu.gtl"): "expected: pour fill only. D-70 keeps the AGND pour 0.5 mm from the J201 wire pads: "
        "region XOR 20.922 mm2 removed, 0 mm2 added, within 1.0 mm of a J201 pad. Tracks, vias and pads are unchanged "
        "(update_2026-11-14/notes_phaseB_export.md section 5.2)",
    ("eib_2026-11-13c", "B_Cu.gbl"): "expected: pour fill only, D-70 as F.Cu: region XOR 15.911 mm2 removed, 0 mm2 "
        "added, within 1.0 mm of a J201 pad (update_2026-11-14/notes_phaseB_export.md section 5.2)",
    ("eib_2026-11-13c", "F_Paste.gtp"): "expected: D-71, no aperture on the 32 SMD pads of the 14 DNP parts; 94 -> 62 "
        "flashes",
    ("eib_2026-11-13c", "F_Silkscreen.gto"): _SILK_EIB,
    ("eib_2026-11-13c", "B_Silkscreen.gbo"): _SILK_EIB,
    ("eib_2026-11-13c", "job.gbrjob"): "expected: D-76, finish ENIG and the layer colours; the thicknesses are unchanged",
}


def stackup():
    """The stack-up of the job file as one table cell (D-76; the values are those of the job file, never typed)."""
    j = json.load(open(os.path.join(O, "gerbers", "%s-job.gbrjob" % B), encoding="utf-8"))
    parts = []
    for L in j.get("MaterialStackup", []):
        if L.get("Type") in ("Copper", "Dielectric", "SolderMask") and "Thickness" in L:
            parts.append("%s %.4g mm%s" % (L["Name"], L["Thickness"],
                                           (" " + L["Material"]) if L.get("Material") else ""))
    return "; ".join(parts) + " (`gerbers/%s-job.gbrjob`, D-76)" % B
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
               copper="1 oz outer / 0.5 oz inner (D-29)", finish="ENIG", qty="6 (operator ruling 2026-11-13: \"Use 6\"; OSH Park sells boards in multiples of 3; design document section E asks for 6 (r9-25); superseded note: \"the E BOM asks for 5\")",
               layers_list="F.Cu (L1, signals and power pours), In1.Cu (L2, solid GND), In2.Cu (L3, signals), "
               "B.Cu (L4, solid GND facing the MB, D-20)"),
    "eib": dict(name="EIB, EVM interface board", layers=2, size="24.0 x 38.0 mm (D-25 / P-05; A.9 since r9-25; superseded note: \"A.9 states 36.0 x 24.0 mm\")",
                thick="1.6 mm", copper="1 oz", finish="ENIG", qty="3 (operator ruling 2026-11-13: \"Order 3\"; one OSH Park lot of 3; a separate 2-layer order at OSH Park)",
                layers_list="F.Cu (signals, AGND pour), B.Cu (signals, AGND pour); the two AGND pours stitched by vias (D-63)"),
}[B]
DNP, FIT = dnp_split()
PASTE_DNP = ("Each DNP footprint carries a -2.0 mm solder-paste margin (REVIEW_2026-11-14 EIB-7, "
             "`gen/eib_dnp_paste.py`), so F.Paste and the stencil have no aperture on the DNP pads."
             if B == "eib" else "The paste layer still carries their pads; a paste stencil prints on them.")
# the rule file each board is checked against: <board>/<board>.kicad_dru = the fab rule file of tools/pcb/fab_rules
# (D-29, D-55) plus the board's own rules (REVIEW_2026-11-14 CRL-5)
RULES = {"cr": "fab_4layer_oshpark_only.kicad_dru", "eib": "fab_2layer_oshpark_pcbway.kicad_dru"}[B]
RULE_ROW = {
    "cr": "`cr/cr.kicad_dru` = `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` plus the J1 pin-18 solid zone "
          "connection (REVIEW_2026-11-14 CRL-4). Rule minima: 0.127 mm track and clearance, 0.254 mm hole, 0.1016 mm "
          "annular ring, 0.381 mm copper to edge. Design values: signal tracks 0.1524 mm with 0.1524 mm clearance (net-class "
          "default), power tracks 0.4-0.6 mm, no 0.127 mm track; the F.Cu power and GND pours fill to the 0.127 mm "
          "rule minimum (fab_clearance), not to the 0.2 mm local clearance that the zones declare: /GND to /VCHG, "
          "/VCHGIN and /VCHGOUT 0.127 mm, /VCHGIN to /VCHGOUT 0.150 mm (pcbnew measurement of the filled polygons, "
          "update_2026-11-14/notes_phaseC_board.md; REVIEW2 R2-CRL-2); via 0.6 mm pad / 0.3 mm drill (0.15 mm ring). "
          "Superseded note: \"design values: 0.1524 mm track and clearance (net-class default; 0.127 mm at necks "
          "only)\"",
    "eib": "`eib/eib.kicad_dru` = `tools/pcb/fab_rules/fab_2layer_oshpark_pcbway.kicad_dru` plus the 0.5 mm AGND pour "
           "clearance to the E and J201 pads (`gen/eib_pour_rules.kicad_dru`, D-68, REVIEW_2026-11-14 EIL-0). Rule "
           "minima: 0.1524 mm track and clearance, 0.254 mm hole, 0.15 mm annular ring, 0.381 mm copper to edge",
}[B]
# CRL-5: the U101 exposed-pad through-holes are open on F.Cu (inside the exposed-pad mask opening, D-69)
MASK_ROW = ("both sides; every via tented on both sides. The nine 0.3 mm through-holes of the U101 exposed pad "
            "(footprint pad 25, not vias) lie inside the 2.7 mm exposed-pad mask opening on F.Cu and are open there; "
            "they are tented on B.Mask only (D-69 paste windows keep >= 0.16 mm from the drills)"
            if B == "cr" else "both sides; every via tented on both sides")
STATUS = ("**Status: not ordered.** This package awaits operator review before order (dec2-eib decision 1, "
          "2026-11-12). The routing is D-28; the straightened tracks, the F.Cu AGND pour and the AGND stitching vias "
          "are D-63 (`eib/straighten.md`, `eib/stitch_gaps.md`); the reference designators are D-64, re-placed in D-74 and "
          "D-78 (`eib/silk_refs.md` lists every reference with its layer). J201 is a 3 x 3 grid of plated wire pads for the soldered W5 wires; the FTSH "
          "header and the ribbon are retired, and the area around J201 was re-routed (D-66, `gen/swap_wire9.py`). The "
          "AGND pours keep 0.5 mm from the hand-soldered E lead pads (D-68, rule in `gen/eib_pour_rules.kicad_dru`), and "
          "since D-70 also from the J201 wire pads. The 2026-11-14 round (D-70 to D-78, D-82) adds no paste on the DNP "
          "pads (D-71), pin-1 dots (D-72), the J201 map \"J201 top view\" and the E labels (D-73), the board marking "
          "\"EIB r8 2026-11-14\" (D-74, D-78), the stack-up block (D-76) and the part fields of the ordered BOM "
          "(D-82). Phase C (2026-11-15) adds the E-pad numbers on F.Silkscreen beside the E pads and corrects the "
          "bottom E labels (E1 reads \"E1 JP12.1\"; 0.80 mm from the bottom references) (D-86). "
          "The tracks, vias, pads and zone outlines are those of `fab/eib_2026-11-13c/`; the F.Cu and B.Cu pour "
          "fill differs at J201 (D-70) and F.Paste has no aperture on the DNP pads (D-71), section 6.\n\n"
          if B == "eib" else
          "**Status: not ordered.** This package awaits operator review before order. The fab is OSH Park (operator "
          "ruling 2026-11-12). The routing is D-58; the outline is D-62 and the 6-32 holes are D-60; the GND stitching "
          "and straightened tracks are D-61; the reference designators are D-59, re-placed in D-74 and D-78 "
          "(`cr/silk_refs.md` lists every reference with its layer). After the operator's routing cleanup in KiCad (`547dc11`), the short In2 via pairs were merged onto "
          "F.Cu and three /GND stitching vias at J101 and C129 were deleted (D-65, `gen/via_merge_cr.py`). J101 is a "
          "3 x 3 grid of plated wire pads for the soldered W5 wires; the FTSH header and the ribbon are retired (D-66, "
          "`gen/swap_wire9.py`). U101 is the Toshiba TCKE1401NM on the unchanged footprint, with R101 8.45k, R103 "
          "64.9k and R104 51.1k (D-67). The U101 exposed-pad "
          "paste windows follow the via keep-outs, about 55 % coverage, for a 4 mil stainless OSH Stencils stencil "
          "(D-69). The 2026-11-14 round (D-72 to D-78, D-82) adds pin-1 dots and SMA cathode bars (D-72), the J101 map "
          "\"J101 top view\" and the W-lead labels (D-73), the board marking \"CR r8 2026-11-14\" (D-78), the J1 pin-18 "
          "solid zone connection (D-75), the stack-up block (D-76) and the part fields of the ordered BOM (D-82). Phase C "
          "(2026-11-15) labels the 20 AWG input pair: \"VIN1\" and the W1 reference beside W1 (/VCHGOUT, to EVM J1 "
          "pin 2), \"GND\" beside W2 (/GND, to EVM J1 pin 1) (D-85). The "
          "tracks, vias, pads and zone outlines are those of `fab/cr_2026-11-13f/`; the F.Cu pour fill differs within "
          "1.7 mm of J1 pin 18 (D-75), section 5.\n\n")
ASSY = ("\nThe CR needs a hot-air or reflow step for U101 (TCKE1401NM, VQFN24D, 0.5 mm pitch, A.8 hand assembly row), or "
        "a PCB assembly service.\n"
        "\nSeven references are on B.Silkscreen, mirrored, over their parts: C102a, C102c, C119, C131, R107, U107 and "
        "U119 (D-78). They can be read only before the CR is plugged onto the MB. J1 pin 18 joins the F.Cu VCHG pour "
        "solidly (D-75), so its joint needs a higher iron setting or a larger tip and a longer dwell than pin 19.\n"
        "\nThe 20 AWG input pair is labelled on F.Silkscreen: W1 carries \"VIN1\" (/VCHGOUT, to EVM J1 pin 2, VIN1) and "
        "W2 carries \"GND\" (/GND, to EVM J1 pin 1) (D-85). A swapped pair shorts the U101 output at the EVM end.\n"
        if B == "cr" else
        "\nThe references of C201, C202, R251, R252, R254, R271, U201 and U202 are on B.Silkscreen, mirrored, over their "
        "parts, and on F.Fab (D-78). They can be read only before the EIB is mounted on its standoffs.\n"
        "\nThe E-pad landing labels (\"E8 TP49\" ... \"E6 DNP\"; E1 reads \"E1 JP12.1\", the square REGN post) are on "
        "B.Silkscreen only (D-73, D-86). The top side carries only the E-pad numbers beside the pads (\"E8\", \"E3\", "
        "\"4\", \"E2\", \"E7\", \"E1\", \"E5\", \"E6\"; D-86). Read the landing labels, or tag each E lead, before the "
        "EIB is mounted on its standoffs.\n")
_qrefs = sorted({r for row in re.findall(r'^"([^"]*)"', open(os.path.join(O, "assembly", "%s-bom.csv" % B),
                                                               encoding="utf-8").read(), re.M)
                   for r in row.split(",") if r.endswith("?")})
if _qrefs:
    ASSY += ("\n`assembly/%s-bom.csv` writes %d references with a \"?\" suffix: %s. The \"?\" is an artefact of the "
             "KiCad BOM export for references with a letter suffix; read %s.\n" % (
                 B, len(_qrefs), ", ".join(_qrefs), ", ".join(r[:-1] for r in _qrefs)))
for _fab in ("jlcpcb", "pcbway"):
    if not os.path.exists(os.path.join(O, "kikit_" + _fab, "bom.csv")):
        ASSY += (f"\nKiKit `fab {_fab} --assembly` wrote no `bom.csv` for this board (`reports/kikit_{_fab}.log`: "
                 f"\"invalid literal for int()\"); its `gerbers.zip` is complete. Use `assembly/{B}-bom.csv` for "
                 f"assembly quotes.\n")


def _asm(fab):
    """Section 2 assembly files of a KiKit preset: its bom.csv only where KiKit wrote one (REVIEW2 R2-DOC-7)."""
    if os.path.exists(os.path.join(O, "kikit_" + fab, "bom.csv")):
        return "`kikit_%s/bom.csv` and `kikit_%s/pos.csv`" % (fab, fab)
    return "`assembly/%s-bom.csv` (KiKit wrote no `bom.csv`) and `kikit_%s/pos.csv`" % (B, fab)


txt = f"""# {INFO['name']}: fabrication package ({D})

{STATUS}## 1. Board

| Item | Value |
|---|---|
| Layers | {INFO['layers']} ({INFO['layers_list']}) |
| Size | {INFO['size']} |
| Thickness | {INFO['thick']} |
| Copper | {INFO['copper']} |
| Stack-up (job file) | {stackup()} |
| Surface finish | {INFO['finish']} |
| Quantity | {INFO['qty']} |
| Solder mask / silkscreen | {MASK_ROW} |
| Design rules | {RULE_ROW} |
| ERC | {ne.group(1) if ne else '?'} messages (`reports/erc.rpt`) |
| DRC | {nv.group(1) if nv else '?'} violations, {nu.group(1) if nu else '?'} unconnected pads, schematic parity checked (`reports/drc.rpt`) |

## 2. Which files to send

| Fab | Upload | Notes |
|---|---|---|
| OSH Park | `kikit_oshpark/gerbers.zip` | OSH Park makes bare boards only. {"Its 4-layer service (1.6 mm, 1 oz outer / 0.5 oz inner clad, ENIG, FR408-HR) matches section 1 (docs.oshpark.com/services/four-layer/, read 2026-11-13). " if B == "cr" else ""}Order quantities come in multiples of 3. |
| PCBWay | `kikit_pcbway/gerbers.zip`; for assembly also {_asm("pcbway")} | Select the layer count, thickness, copper weight and finish of section 1 in the order form. |
| JLCPCB | `kikit_jlcpcb/gerbers.zip`; for assembly also {_asm("jlcpcb")} | The BOM has no LCSC part numbers; JLCPCB assembly needs them matched by hand (KiKit ran with `--missingWarn`). |
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

The per-unit BOMs and the Digi-Key and Mouser import files are in `hardware/charger_evm_r8/bom_2026-11-14/`
(its `README.md` gives the order instructions and the optional alternate lines). The layout
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
the copper and mask layers still carry their pads. {PASTE_DNP}

| Item | Parts |
|---|---|
| DNP ({len(DNP)}) | {', '.join(DNP)} |
| Fitted ({len(FIT)}) | {', '.join(FIT)} |
"""
    if B == "eib":
        txt += """
The EIB DNP set is operator decision dec2-eib (`decisions_2026-11-12/round2/dec2_eib_2026-11-12.md`, D-49). E4
(ILIM sense) and E6 (/CE sense) are lead pads: their leads are not built and the pads stay unconnected. Since D-66,
R265.2 and R264.2 are not connected (J201.11 and J201.13 no longer exist).
"""
if REF:
    rows = compare(REF)
    same = all(r[1].startswith("identical") for r in rows)
    txt += f"""
## {6 if DNP else 5}. Copper and drill comparison

Every Gerber and Excellon file of this package was compared line by line with `{REF.replace(os.sep, '/')}`,
with the creation-date lines ignored. Result: {'all files identical' if same else 'DIFFERENCES FOUND'}{
     '' if same else (', each with the recorded reason below' if all(r[2] and not r[2].startswith('NO RECORDED')
                                                                      for r in rows if r[1] == 'DIFFERENT')
                      else '; at least one difference has NO RECORDED REASON')}.

| File | Result | Reason |
|---|---|---|
""" + "".join("| `%s` | %s | %s |\n" % r for r in rows)
    # Phase C fix round (2026-11-15, REVIEW2 issue list): the reason for the files outside the Gerber and Excellon set.
    txt += """
The other files of this package also differ from the reference package; they are not compared line by line. D-82
set the Value, MPN and Manufacturer fields to the ordered BOM (CR: for example C110 50 V to 100 V and C102b X7S to
X7R; EIB: for example C201 50 V to 100 V). The assembly BOM therefore differs in those three fields, and the position
file differs in the Value field only; every reference, footprint, position, rotation and side is identical. The iBOM, the schematic, PCB and STEP files of `docs/`, the netlist, the drill-map PDFs, the KiKit outputs
and the DRC and ERC reports are regenerated from the same boards and carry the same field, silkscreen and pour-fill
changes, or only new creation dates. `reports/npth_check.txt` is new in this package.
"""
open(os.path.join(O, "README.md"), "w", encoding="utf-8", newline="\n").write(txt)
print("wrote", os.path.join(O, "README.md"))
