"""Generate a KiCad 9 schematic (.kicad_sch) and a project-local symbol library (.kicad_sym) from netlist.py.

Each part becomes one symbol instance at angle 0; each connected pin end carries a local label with its net
name; each intentionally open pin carries a no-connect flag. PWR_FLAG symbols mark the externally supplied
nets so that ERC sees a driver. Usage: python sch.py <board> <outdir>
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netlist  # noqa: E402
import fpmap  # noqa: E402

G = 2.54
NS = uuid.UUID("6b1e0d4c-2f1a-4b8e-9c33-0e5a8c2b7d10")


def uid(*k):
    return str(uuid.uuid5(NS, "/".join(str(x) for x in k)))


# ---------------------------------------------------------------- symbol templates
# Two-pin vertical passives: pin 1 at top.  IC: (left pins, right pins), each (number, name, etype).
PASSIVE2 = {"R": ("R", "~"), "C": ("C", "~")}
IC = {
    "TLV3012": ([("3", "IN+", "input"), ("4", "IN-", "input"), ("5", "REF", "passive"), ("6", "V+", "power_in"),
                 ("2", "V-", "power_in")], [("1", "OUT", "output")]),
    "LVC2G32": ([("1", "1A", "input"), ("2", "1B", "input"), ("5", "2A", "input"), ("6", "2B", "input"),
                 ("8", "VCC", "power_in"), ("4", "GND", "power_in")], [("7", "1Y", "output"), ("3", "2Y", "output")]),
    "LVC2G08": ([("1", "1A", "input"), ("2", "1B", "input"), ("5", "2A", "input"), ("6", "2B", "input"),
                 ("8", "VCC", "power_in"), ("4", "GND", "power_in")], [("7", "1Y", "output"), ("3", "2Y", "output")]),
    "LVC3G04": ([("1", "1A", "input"), ("3", "2A", "input"), ("6", "3A", "input"), ("8", "VCC", "power_in"),
                 ("4", "GND", "power_in")], [("7", "1Y", "output"), ("5", "2Y", "output"), ("2", "3Y", "output")]),
    "LVC3G06": ([("1", "1A", "input"), ("3", "2A", "input"), ("6", "3A", "input"), ("8", "VCC", "power_in"),
                 ("4", "GND", "power_in")], [("7", "1Y", "open_collector"), ("5", "2Y", "open_collector"),
                                             ("2", "3Y", "open_collector")]),
    "LVC1G11": ([("1", "A", "input"), ("3", "B", "input"), ("6", "C", "input"), ("5", "VCC", "power_in"),
                 ("2", "GND", "power_in")], [("4", "Y", "output")]),
    "LVC1G08": ([("1", "A", "input"), ("2", "B", "input"), ("5", "VCC", "power_in"), ("3", "GND", "power_in")],
                [("4", "Y", "output")]),
    "LVC1G14": ([("1", "NC", "passive"), ("2", "A", "input"), ("5", "VCC", "power_in"), ("3", "GND", "power_in")],
                [("4", "Y", "output")]),
    "LVC1G06": ([("1", "NC", "no_connect"), ("2", "A", "input"), ("5", "VCC", "power_in"),
                 ("3", "GND", "power_in")], [("4", "Y", "open_collector")]),
    "LVC1G123": ([("1", "A", "input"), ("2", "B", "input"), ("3", "~{CLR}", "input"), ("8", "VCC", "power_in"),
                  ("4", "GND", "power_in")], [("5", "Q", "output"), ("6", "Cext", "passive"),
                                              ("7", "Rext/Cext", "passive")]),
    "TPS26630": ([("1", "IN", "power_in"), ("2", "IN", "power_in"), ("5", "IN_SYS", "power_in"),
                  ("6", "UVLO", "input"), ("7", "OVP", "input"), ("11", "MODE", "input"), ("12", "~{SHDN}", "input"),
                  ("15", "PGTH", "input"), ("9", "dVdT", "passive"), ("10", "ILIM", "passive"),
                  ("8", "GND", "power_in"), ("25", "PAD", "passive")],
                 [("17", "OUT", "passive"), ("18", "OUT", "passive"), ("3", "B_GATE", "passive"),
                  ("4", "DRV", "passive"), ("13", "IMON", "passive"), ("14", "~{FLT}", "open_collector"),
                  ("16", "PGOOD", "passive")] + [(str(n), "NC", "no_connect") for n in range(19, 25)]),
    "TPS22810": ([("1", "VIN", "passive"), ("3", "EN/UVLO", "passive"), ("4", "CT", "passive"),
                  ("2", "GND", "passive")], [("6", "VOUT", "passive"), ("5", "QOD", "passive")]),
    "BAV199": ([("3", "COM", "passive")], [("2", "K_up", "passive"), ("1", "A_lo", "passive")]),
    "NMOS": ([("1", "G", "passive")], [("3", "D", "passive"), ("2", "S", "passive")]),
    "PMOS": ([("1", "G", "passive")], [("2", "S", "passive"), ("3", "D", "passive")]),
    "D": ([("2", "A", "passive")], [("1", "K", "passive")]),
    "CHG22": ([(str(n), "P%d" % n, "passive") for n in range(1, 11)],
              [(str(n), "P%d" % n, "passive") for n in range(11, 23)]),
    "J2x7K": ([(str(n), str(n), "passive") for n in (1, 3, 5, 7, 9, 11, 13)],
              [(str(n), str(n), "passive") for n in (2, 4, 8, 10, 12, 14)]),
    "J2x7": ([(str(n), str(n), "passive") for n in (1, 3, 5, 7, 9, 11, 13)],
             [(str(n), str(n), "passive") for n in (2, 4, 6, 8, 10, 12, 14)]),
    "TAP": ([], [("1", "1", "passive")]),
    "PAD1": ([], [("1", "1", "passive")]),
    "PAD2": ([], [("1", "1", "passive"), ("2", "2", "passive")]),
    "PAD3": ([], [("1", "1", "passive"), ("2", "2", "passive"), ("3", "3", "passive")]),
    "PWR_FLAG": ([], [("1", "pwr", "power_out")]),
}
REFPREFIX = {"TAP": "F", "PAD1": "W", "PAD2": "W", "PAD3": "W", "PWR_FLAG": "#FLG"}


def font(h=1.27, hide=False, justify=None):
    s = "(effects (font (size %.3f %.3f))" % (h, h)
    if justify:
        s += " (justify %s)" % justify
    if hide:
        s += " (hide yes)"
    return s + ")"


def ic_geom(kind):
    left, right = IC[kind]
    n = max(len(left), len(right), 1)
    w = 15.24 if kind not in ("TAP", "PAD1", "PAD2", "PAD3", "PWR_FLAG", "D") else 5.08
    if kind == "TPS26630":
        w = 20.32
    h = n * G + G
    top = (n * G) / 2.0
    pins = []
    for i, (num, name, et) in enumerate(left):
        y = round((top - G / 2 - i * G) / G) * G if False else top - G / 2 - i * G
        pins.append((num, name, et, -w / 2 - G, y, 0))
    for i, (num, name, et) in enumerate(right):
        y = top - G / 2 - i * G
        pins.append((num, name, et, w / 2 + G, y, 180))
    return w, h, pins


def snap(v):
    return round(v / 1.27) * 1.27


def lib_symbol(kind, libname, full=True):
    name = ("%s:%s" % (libname, kind)) if full else kind
    out = ['(symbol "%s"' % name]
    pinnames_hide = kind in PASSIVE2 or kind in ("TAP", "PAD1", "PWR_FLAG")
    out.append('(pin_names (offset 0.508)%s)' % (" (hide yes)" if pinnames_hide else ""))
    if kind in PASSIVE2 or kind in ("PWR_FLAG",):
        out.append("(pin_numbers (hide yes))")
    out.append("(exclude_from_sim no) (in_bom %s) (on_board %s)" % (("no", "no") if kind == "PWR_FLAG" else
                                                                    ("yes", "yes")))
    pfx = REFPREFIX.get(kind, {"R": "R", "C": "C", "D": "D", "BAV199": "D", "NMOS": "Q", "PMOS": "Q",
                               "CHG22": "J", "J2x7K": "J", "J2x7": "J"}.get(kind, "U"))
    out.append('(property "Reference" "%s" (at 0 0 0) %s)' % (pfx, font()))
    out.append('(property "Value" "%s" (at 0 -2.54 0) %s)' % (kind, font()))
    out.append('(property "Footprint" "" (at 0 0 0) %s)' % font(hide=True))
    out.append('(property "Datasheet" "" (at 0 0 0) %s)' % font(hide=True))
    if kind in PASSIVE2:
        out.append('(symbol "%s_0_1" (rectangle (start -1.016 -2.54) (end 1.016 2.54) (stroke (width 0.254) '
                   '(type default)) (fill (type none))))' % kind if kind == "R" else
                   '(symbol "%s_0_1" (polyline (pts (xy -2.032 0.762) (xy 2.032 0.762)) (stroke (width 0.508) '
                   '(type default)) (fill (type none))) (polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762)) '
                   '(stroke (width 0.508) (type default)) (fill (type none))))' % kind)
        L = 1.27 if kind == "R" else 2.794
        out.append('(symbol "%s_1_1" (pin passive line (at 0 3.81 270) (length %.3f) (name "~" %s) '
                   '(number "1" %s)) (pin passive line (at 0 -3.81 90) (length %.3f) (name "~" %s) '
                   '(number "2" %s)))' % (kind, L, font(), font(), L, font(), font()))
    else:
        w, h, pins = ic_geom(kind)
        out.append('(symbol "%s_0_1" (rectangle (start %.3f %.3f) (end %.3f %.3f) (stroke (width 0.254) '
                   '(type default)) (fill (type background))))' % (kind, -w / 2, h / 2, w / 2, -h / 2))
        ps = []
        for num, nm, et, x, y, ang in pins:
            ps.append('(pin %s line (at %.3f %.3f %d) (length 2.54) (name "%s" %s) (number "%s" %s))'
                      % (et, x, y, ang, nm, font(1.016), num, font(1.016)))
        out.append('(symbol "%s_1_1" %s)' % (kind, " ".join(ps)))
    out.append(")")
    return " ".join(out)


def pin_points(kind):
    """Pin connection points in symbol coordinates (y up)."""
    if kind in PASSIVE2:
        return {"1": (0, 3.81, "top"), "2": (0, -3.81, "bottom")}
    w, h, pins = ic_geom(kind)
    return {num: (x, y, "left" if ang == 0 else "right") for num, nm, et, x, y, ang in pins}


def footprint_name(board, pkg):
    return "charger_r8_%s:%s" % (board, fpmap.FP[pkg][1])


GROUPS_CR = [
    ("CHG header, lead pads and taps", lambda r: r.startswith(("J1", "W", "F"))),
    ("Input bulk, TVS and eFuse U101 (B.4)", lambda r: r in (
        "C102a", "C102b", "C102c", "D107", "U101", "R102", "R103", "R104", "R101", "C101", "C103", "D103", "R105",
        "C105", "R129", "C129", "R106s")),
    ("Comparators (B.2)", lambda r: r.startswith(("U102", "U103", "U104", "U115", "U117", "U119", "U120", "U121"))
     or r in ("R109", "R110", "C106", "R113", "D104", "R111", "R112", "C107", "D105", "R114", "R115", "C108",
              "R116", "D106", "R141", "R142", "R143", "R140", "C140", "R144", "R117", "R118", "C109", "R120",
              "R119", "R160", "R161", "R162", "C127", "R163", "C124", "R137", "R121", "R133", "R122", "R134",
              "R184", "R185", "C130", "R186", "R187", "R188", "R189", "R190", "R191")),
    ("BQ29200 OUT input and permit logic (B.1, B.3)", lambda r: True),
]


def build(board, outdir):
    parts = netlist.BOARDS[board]
    lib = "charger_r8_%s" % board
    kinds = sorted({p[1] for p in parts} | {"PWR_FLAG"})
    os.makedirs(outdir, exist_ok=True)
    # project symbol library
    with open(os.path.join(outdir, lib + ".kicad_sym"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(kicad_symbol_lib (version 20241209) (generator "charger_r8_gen") (generator_version "9.0")\n')
        for k in kinds:
            f.write(lib_symbol(k, lib, full=False) + "\n")
        f.write(")\n")
    root = uid(board, "root")
    items = []
    texts = []
    # flags on externally supplied nets
    flags = {"cr": ["/GND", "/3V3", "/VCHGIN"], "eib": ["/3V3", "/AGND"]}[board]
    flagparts = [("#FLG%02d" % (i + 1), "PWR_FLAG", "PWR_FLAG", None, {"1": n.lstrip("/")}, {})
                 for i, n in enumerate(flags)]
    groups = GROUPS_CR if board == "cr" else [("EVM interface board (B.6, B.8 EIB)", lambda r: True)]
    assigned = {}
    for p in parts + flagparts:
        for gi, (gname, test) in enumerate(groups):
            if test(p[0]):
                assigned.setdefault(gi, []).append(p)
                break
    paper_w, paper_h = (841.0, 594.0) if board == "cr" else (420.0, 297.0)
    y = 30.48
    for gi, (gname, test) in enumerate(groups):
        gparts = assigned.get(gi, [])
        if not gparts:
            continue
        texts.append((gname, 20.32, y - 7.62, 2.54))
        x = 30.48
        rowh = 0
        for p in gparts:
            ref, kind, val, pkg, pins, o = p
            if kind in PASSIVE2:
                cw, ch = 22.86, 17.78
            else:
                w, h, _ = ic_geom(kind)
                cw, ch = w + 40.64, h + 10.16
            if x + cw > paper_w - 20:
                x = 30.48
                y += rowh
                rowh = 0
            cx, cy = snap(x + cw / 2 - (5.08 if kind in PASSIVE2 else 0)), snap(y + ch / 2)
            items.append((p, cx, cy))
            x += cw
            rowh = max(rowh, ch)
        y += rowh + 12.7
    if y > paper_h - 20:
        paper_h = y + 30
    # write schematic
    L = ['(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0") (uuid "%s")' % root,
         '(paper "User" %.1f %.1f)' % (paper_w, paper_h),
         '(title_block (title "%s") (date "2026-11-11") (rev "r8-capture-1") (company "Scale car DC balancer, '
         'board rev 20260622") (comment 1 "Source: docs/charger_bq25798_wiring_design_2026-11-05.md r8, B.8 '
         'pin-level netlist") (comment 2 "Generated by hardware/charger_evm_r8/gen/sch.py; do not hand-edit"))'
         % ({"cr": "CR - CHG adapter carrier (BQ25798EVM path)", "eib": "EIB - EVM interface board"}[board])]
    L.append("(lib_symbols")
    for k in kinds:
        L.append(lib_symbol(k, lib, full=True))
    L.append(")")
    for (txt, tx, ty, ts) in texts:
        L.append('(text "%s" (exclude_from_sim no) (at %.2f %.2f 0) (effects (font (size %.2f %.2f) (bold yes)) '
                 '(justify left bottom)) (uuid "%s"))' % (txt, tx, ty, ts, ts, uid(board, "t", txt)))
    for p, cx, cy in items:
        ref, kind, val, pkg, pins, o = p
        dnp = o.get("dnp", False)
        flag = kind == "PWR_FLAG"
        fpn = "" if flag else footprint_name(board, pkg)
        L.append('(symbol (lib_id "%s:%s") (at %.2f %.2f 0) (unit 1) (exclude_from_sim no) (in_bom %s) '
                 '(on_board %s) (dnp %s) (uuid "%s")' % (lib, kind, cx, cy, "no" if flag else "yes",
                                                         "no" if flag else "yes", "yes" if dnp else "no",
                                                         uid(board, ref)))
        if kind in PASSIVE2:
            L.append('(property "Reference" "%s" (at %.2f %.2f 0) %s)' % (ref, cx + 2.54, cy - 1.27,
                                                                       font(justify="left")))
            L.append('(property "Value" "%s" (at %.2f %.2f 0) %s)' % (val, cx + 2.54, cy + 1.27, font(1.0,
                                                                                                   justify="left")))
        else:
            w, h, _ = ic_geom(kind)
            L.append('(property "Reference" "%s" (at %.2f %.2f 0) %s)' % (ref, cx, cy - h / 2 - 1.27, font()))
            L.append('(property "Value" "%s" (at %.2f %.2f 0) %s)' % (val, cx, cy + h / 2 + 1.27, font(1.0)))
        L.append('(property "Footprint" "%s" (at %.2f %.2f 0) %s)' % (fpn, cx, cy, font(hide=True)))
        L.append('(property "Datasheet" "" (at %.2f %.2f 0) %s)' % (cx, cy, font(hide=True)))
        for fld, key in (("MPN", "mpn"), ("Manufacturer", "mfr"), ("Note", "note")):
            if o.get(key):
                L.append('(property "%s" "%s" (at %.2f %.2f 0) %s)' % (fld, o[key].replace('"', "'"), cx, cy,
                                                                     font(hide=True)))
        if o.get("side") == "B":
            L.append('(property "Side" "bottom" (at %.2f %.2f 0) %s)' % (cx, cy, font(hide=True)))
        pp = pin_points(kind)
        for num in pp:
            L.append('(pin "%s" (uuid "%s"))' % (num, uid(board, ref, "pin", num)))
        L.append('(instances (project "%s" (path "/%s" (reference "%s") (unit 1)))))' % (board, root, ref))
        for num, (px, py, side) in pp.items():
            X, Y = cx + px, cy - py
            net = pins.get(num, "__absent__")
            if net == "__absent__":
                raise SystemExit("%s pin %s missing from netlist" % (ref, num))
            if net is None:
                L.append('(no_connect (at %.2f %.2f) (uuid "%s"))' % (X, Y, uid(board, ref, "nc", num)))
            else:
                ang, just = {"left": (180, "right bottom"), "right": (0, "left bottom"),
                             "top": (90, "left bottom"), "bottom": (270, "right bottom")}[side]
                L.append('(label "%s" (at %.2f %.2f %d) (effects (font (size 1.016 1.016)) (justify %s)) '
                         '(uuid "%s"))' % (net, X, Y, ang, just, uid(board, ref, "lbl", num)))
        extra = set(pins) - set(pp)
        if extra:
            raise SystemExit("%s netlist pins %s not in symbol %s" % (ref, extra, kind))
    L.append('(sheet_instances (path "/" (page "1")))')
    L.append("(embedded_fonts no))")
    with open(os.path.join(outdir, board + ".kicad_sch"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    with open(os.path.join(outdir, "sym-lib-table"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(sym_lib_table (version 7)\n  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.kicad_sym")'
                '(options "")(descr "project-local, generated"))\n)\n' % (lib, lib))
    return len(items)


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
