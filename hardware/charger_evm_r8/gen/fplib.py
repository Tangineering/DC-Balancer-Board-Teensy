"""Build the project-local footprint library <outdir>/charger_r8_<board>.pretty.

Stock footprints are copied verbatim from KiCad 9.0.9. Custom footprints are written from the design geometry
(A.2/A.8 CHG header and pads, A.9 E pads) or derived from a stock footprint with a recorded change
(LAYOUT_DECISIONS.md). Usage: python fplib.py <board> <outdir>
"""
import math
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fpmap  # noqa: E402
import netlist  # noqa: E402

STOCK = r"C:\Program Files\KiCad\9.0\share\kicad\footprints"


def hdr(name, descr, smd=True, board_only=False, exclude_bom=False):
    attr = "(attr %s%s%s)" % ("smd" if smd else "through_hole", " board_only" if board_only else "",
                              " exclude_from_pos_files exclude_from_bom" if exclude_bom else "")
    return ['(footprint "%s" (version 20241229) (generator "charger_r8_gen") (generator_version "9.0") '
            '(layer "F.Cu") (descr "%s")' % (name, descr),
            '(property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 0.8 0.8) '
            '(thickness 0.15))))',
            '(property "Value" "%s" (at 0 2 0) (layer "F.Fab") (effects (font (size 0.8 0.8) (thickness 0.12))))'
            % name,
            '(property "Footprint" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1))))',
            '(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1))))',
            attr]


def rect(layer, x0, y0, x1, y1, w=0.05):
    return '(fp_rect (start %.4f %.4f) (end %.4f %.4f) (stroke (width %.3f) (type solid)) (fill no) (layer "%s"))' \
        % (x0, y0, x1, y1, w, layer)


def circ(layer, cx, cy, r, w=0.05):
    return '(fp_circle (center %.4f %.4f) (end %.4f %.4f) (stroke (width %.3f) (type solid)) (fill no) ' \
           '(layer "%s"))' % (cx, cy, cx + r, cy, w, layer)


def line(layer, x0, y0, x1, y1, w=0.12):
    return '(fp_line (start %.4f %.4f) (end %.4f %.4f) (stroke (width %.3f) (type solid)) (layer "%s"))' \
        % (x0, y0, x1, y1, w, layer)


def smd_pad(num, x, y, w, h, shape="roundrect", paste=True):
    layers = '"F.Cu" "F.Mask"' + (' "F.Paste"' if paste else "")
    rr = " (roundrect_rratio 0.15)" if shape == "roundrect" else ""
    return '(pad "%s" smd %s (at %.4f %.4f) (size %.4f %.4f) (layers %s)%s)' % (num, shape, x, y, w, h, layers, rr)


def pth_pad(num, x, y, dia, drill, shape="circle", inner_unused_removed=False):
    extra = " (remove_unused_layers yes) (keep_end_layers yes)" if inner_unused_removed else ""
    return '(pad "%s" thru_hole %s (at %.4f %.4f) (size %.4f %.4f) (drill %.4f) (layers "*.Cu" "*.Mask")%s)' % (
        num, shape, x, y, dia, dia, drill, extra)


def keepout_circle(cx, cy, r, layers, tracks=True, vias=True, pads=True, pour=True, fps=True, n=24):
    pts = " ".join("(xy %.4f %.4f)" % (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
                   for i in range(n))
    al = lambda b: "not_allowed" if b else "allowed"  # noqa: E731
    return ('(zone (net 0) (net_name "") (layers %s) (hatch edge 0.5) (connect_pads (clearance 0)) '
            '(min_thickness 0.25) (filled_areas_thickness no) (keepout (tracks %s) (vias %s) (pads %s) '
            '(copperpour %s) (footprints %s)) (placement (enabled no) (sheetname "")) (fill (thermal_gap 0.5) '
            '(thermal_bridge_width 0.5)) (polygon (pts %s)))'
            % (" ".join('"%s"' % l for l in layers), al(tracks), al(vias), al(pads), al(pour), al(fps), pts))


def model(path):
    return '(model "%s" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))' % path


def write(outdir, name, lines):
    with open(os.path.join(outdir, name + ".kicad_mod"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines + [")"]) + "\n")


# ------------------------------------------------------------------ custom footprints
def chg22(outdir, name):
    """22-hole Ag105 pattern (A.8 table). Origin = pin 1 (45.998, 39.084). KiCad y = -(eagle y - 39.084).
    Pins 1-10 at x 0; pins 11-22 at x -25.000. Drill 1.1 mm plated, pad 1.9 mm (A.8: pad >= 1.9 mm).
    The 2.54 mm header plastic bodies sit on the CR underside (A.8 +x pocket row: the 1x10 body to y 63.21),
    so the body courtyards are on B.CrtYd."""
    L = hdr(name, "Ag105 CHG footprint, 22 header pins (Samtec TSW-110/TSW-112), design r8 A.2/A.8", smd=False)
    pos = {}
    for n in range(1, 11):
        pos[n] = (0.0, -(n - 1) * 2.54)
    for n in range(11, 23):
        ey = 64.484 - (n - 11) * 2.54
        pos[n] = (20.998 - 45.998, -(ey - 39.084))
    for n, (x, y) in pos.items():
        # D-30: 1.9 mm pads on L1/L4 (A.8 pad >= 1.9 mm); not flashed on L2/L3 where the pin has no inner connection
        L.append(pth_pad(str(n), x, y, 1.9, 1.1, "rect" if n in (1, 11) else "circle", inner_unused_removed=True))
    # B side: header bodies 2.54 mm wide (A.8 header strips)
    L.append(rect("B.CrtYd", -1.27 - 0.25, 1.27 + 0.25, 1.27 + 0.25, -(9 * 2.54) - 1.27 - 0.25))
    L.append(rect("B.CrtYd", -25.0 - 1.27 - 0.25, 2.54 + 1.27 + 0.25, -25.0 + 1.27 + 0.25,
                  -(64.484 - 39.084) - 1.27 - 0.25))
    L.append(rect("B.Fab", -1.27, 1.27, 1.27, -(9 * 2.54) - 1.27, 0.1))
    L.append(rect("B.Fab", -26.27, 2.54 + 1.27, -23.73, -(64.484 - 39.084) - 1.27, 0.1))
    # F side courtyard: one circle per pad, pad + 0.10 mm (D-03); the top side between the pins stays usable
    for n, (x, y) in pos.items():
        L.append(circ("F.CrtYd", x, y, 0.95 + 0.10))
    # pin-1 and pin-11 identity marks on both silk layers (T-A-06 step 0)
    for lay in ("F.SilkS", "B.SilkS"):
        L.append('(fp_text user "1" (at 1.9 0 0) (layer "%s") (effects (font (size 0.8 0.8) (thickness 0.15))%s))'
                 % (lay, " (justify mirror)" if lay.startswith("B") else ""))
        L.append('(fp_text user "11" (at -26.9 -25.4 0) (layer "%s") (effects (font (size 0.8 0.8) '
                 '(thickness 0.15))%s))' % (lay, " (justify mirror)" if lay.startswith("B") else ""))
    write(outdir, name, L)


def tap(outdir, name):
    L = hdr(name, "Tap solder pad, top-side SMT 1.5 x 1.5 mm, no hole, no paste (A.4, A.8)")
    L.append(smd_pad("1", 0, 0, 1.5, 1.5, "rect", paste=False))
    L.append(rect("F.CrtYd", -1.0, -1.0, 1.0, 1.0))
    write(outdir, name, L)


def lead_pth(outdir, name, drill, dia):
    L = hdr(name, "Lead pad, %.1f mm plated hole, %.1f mm pad (A.8 W1-W4)" % (drill, dia), smd=False)
    L.append(pth_pad("1", 0, 0, dia, drill))
    r = dia / 2 + 0.10   # D-03 least-density excess; W1-W2 are 2.6 mm apart with 2.3 mm pads (A.8)
    L.append(circ("F.CrtYd", 0, 0, r))
    L.append(circ("B.CrtYd", 0, 0, r))
    write(outdir, name, L)


def lead_smd(outdir, name, n):
    L = hdr(name, "Lead pads, %d x SMT 1.2 x 1.5 mm at 2.0 mm (A.8 W6/W7)" % n)
    x0 = -(n - 1) * 1.0
    for i in range(n):
        L.append(smd_pad(str(i + 1), x0 + 2.0 * i, 0, 1.2, 1.5, "rect", paste=False))
    L.append(rect("F.CrtYd", x0 - 0.85, -1.0, -x0 + 0.85, 1.0))
    L.append(line("F.Fab", x0 - 0.9, 1.1, x0 - 0.9, -1.1))  # pad-1 mark
    write(outdir, name, L)


def epad(outdir, name):
    L = hdr(name, "EIB E lead pad, 1.0 mm plated hole, 1.8 mm pad (A.9)", smd=False)
    L.append(pth_pad("1", 0, 0, 1.8, 1.0))
    L.append(circ("F.CrtYd", 0, 0, 1.15))
    L.append(circ("B.CrtYd", 0, 0, 1.15))
    write(outdir, name, L)


def ft2_hole(outdir, name):
    """FT2 fill hole (B.8 Mechanical r7): 1.0 mm NPTH, 2.0 mm copper and part keep-out disc on the CR top,
    >= 0.5 mm copper pull-back on L2-L4 (a 2.0 mm disc on every copper layer satisfies both)."""
    L = hdr(name, "FT2 fill hole, 1.0 mm NPTH, 2.0 mm keep-out disc (A.8, H.23(i))", smd=False, board_only=True,
            exclude_bom=True)
    L.append('(pad "" np_thru_hole circle (at 0 0) (size 1.0 1.0) (drill 1.0) (layers "*.Cu" "*.Mask"))')
    L.append(keepout_circle(0, 0, 1.0, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], pads=False))
    L.append(circ("B.SilkS", 0, 0, 1.3, 0.15))
    L.append(circ("F.CrtYd", 0, 0, 1.0))
    write(outdir, name, L)


def foot_mark(outdir, name, w, h, tick):
    """Bottom silkscreen outline of a bonded foot body (PM4 (2c) placement guide, A.7/A.8)."""
    L = hdr(name, "Foot body %.1f x %.1f mm bottom silkscreen guide (A.8)" % (w, h), smd=True, board_only=True,
            exclude_bom=True)
    L.append(rect("B.SilkS", -w / 2, -h / 2, w / 2, h / 2, 0.15))
    if tick:  # long-axis tick (FT1, long axis along x)
        L.append(line("B.SilkS", -w / 2 - 0.6, 0, -w / 2 - 0.1, 0, 0.15))
        L.append(line("B.SilkS", w / 2 + 0.1, 0, w / 2 + 0.6, 0, 0.15))
    write(outdir, name, L)


def m3(outdir, name):
    """M3 mounting hole with a 7 mm copper-free keep-out (A.9). Plain NPTH 3.2 mm."""
    L = hdr(name, "M3 hole 3.2 mm NPTH, 7.0 mm copper-free keep-out (A.9)", smd=False, board_only=True,
            exclude_bom=True)
    L.append('(pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask"))')
    L.append(keepout_circle(0, 0, 3.5, ["F.Cu", "B.Cu"], fps=False, pads=False))
    L.append(circ("F.CrtYd", 0, 0, 3.5))
    L.append(circ("F.Fab", 0, 0, 3.5, 0.12))
    write(outdir, name, L)


def stock_text(lib, name):
    with open(os.path.join(STOCK, lib + ".pretty", name + ".kicad_mod"), encoding="utf-8") as f:
        return f.read()


def _load(lib, stock, name):
    from kiutils.footprint import Footprint
    fp = Footprint.from_file(os.path.join(STOCK, lib + ".pretty", stock + ".kicad_mod"))
    fp.entryName = name
    return fp


def _strip_silk(fp):
    """D-12: small passives and ICs carry no silkscreen on this dense board; their outline and pin-1 mark stay on
    F.Fab (fab drawing, InteractiveHtmlBom)."""
    fp.graphicItems = [g for g in fp.graphicItems if getattr(g, "layer", "") not in ("F.SilkS", "B.SilkS")]
    for prop in getattr(fp, "properties", []) or []:
        pass


def _set_courtyard(fp, x0, y0, x1, y1):
    from kiutils.items.fpitems import FpRect
    from kiutils.items.common import Position, Stroke
    fp.graphicItems = [g for g in fp.graphicItems if getattr(g, "layer", "") != "F.CrtYd"]
    fp.graphicItems.append(FpRect(start=Position(X=x0, Y=y0), end=Position(X=x1, Y=y1), layer="F.CrtYd",
                                  stroke=Stroke(width=0.05, type="solid")))


def _extent(fp, with_fab=True):
    xs, ys = [], []
    for pad in fp.pads:
        if pad.type not in ("smd", "thru_hole"):
            continue
        px, py = pad.position.X, pad.position.Y
        sx, sy = pad.size.X, pad.size.Y
        if (pad.position.angle or 0) % 180 != 0:
            sx, sy = sy, sx
        xs += [px - sx / 2, px + sx / 2]
        ys += [py - sy / 2, py + sy / 2]
    if with_fab:
        for g in fp.graphicItems:
            if getattr(g, "layer", "") == "F.Fab" and hasattr(g, "start") and hasattr(g, "end"):
                xs += [g.start.X, g.end.X]
                ys += [g.start.Y, g.end.Y]
    return min(xs), min(ys), max(xs), max(ys)


def vqfn24(outdir, name):
    """Derived from stock Texas_RGE0024H_VQFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm_ThermalVias (TI RGE0024H land,
    lib_verification_2026-11-11.md row 1): the 3 x 3 thermal vias drilled 0.30 mm with a 0.55 mm land (A.8: >= 9
    vias of 0.3 mm, SLVSE94G section 11) on a 0.61 mm land (0.155 mm ring >= fab 0.15 mm), numbered 25 (EP net), and the courtyard at the IPC-7351 least-density
    excess (0.10 mm beyond the pad toes) instead of 0.25 mm (D-03)."""
    from kiutils.items.common import Position
    fp = _load("Package_DFN_QFN", "Texas_RGE0024H_VQFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm_ThermalVias", name)
    for pad in fp.pads:
        if pad.type == "smd" and pad.number == "25":
            pad.solderMaskMargin = 0.0   # EP 0.20 mm from the pin toes: 0.149 mm web with the 0.0508 mm pin expansion
        if pad.type == "thru_hole":
            pad.number = "25"
            pad.size = Position(X=0.61, Y=0.61)
            pad.drill.diameter = 0.3
    x0, y0, x1, y1 = _extent(fp, with_fab=False)
    c = round(max(-x0, -y0, x1, y1) + 0.10, 3)
    _set_courtyard(fp, -c, -c, c, c)
    _strip_silk(fp)
    fp.to_file(os.path.join(outdir, name + ".kicad_mod"))


def ssop_ti(outdir, name):
    """Stock SSOP-8_2.95x2.8mm_P0.65mm with the pads moved to the TI DCT0008A land: 1.1 x 0.4 mm pads on a 3.8 mm
    centre span (lib_verification_2026-11-11.md row 3); courtyard 0.10 mm beyond pads and body (D-03)."""
    from kiutils.items.common import Position
    fp = _load("Package_SO", "SSOP-8_2.95x2.8mm_P0.65mm", name)
    for pad in fp.pads:
        if pad.type == "smd":
            pad.position.X = 1.9 if pad.position.X > 0 else -1.9
            rotated = (pad.position.angle or 0) % 180 != 0
            pad.size = Position(X=0.4, Y=1.1) if rotated else Position(X=1.1, Y=0.4)
    x0, y0, x1, y1 = _extent(fp)
    _set_courtyard(fp, round(x0 - 0.1, 3), round(y0 - 0.1, 3), round(x1 + 0.1, 3), round(y1 + 0.1, 3))
    _strip_silk(fp)
    fp.to_file(os.path.join(outdir, name + ".kicad_mod"))


def tight(outdir, name, lib, stock):
    """Stock footprint with the courtyard redrawn at 0.10 mm beyond the union of the pads and the F.Fab body
    (IPC-7351 least-density courtyard excess; D-03). Pads, silk, fab and 3D model unchanged."""
    fp = _load(lib, stock, name)
    x0, y0, x1, y1 = _extent(fp)
    _set_courtyard(fp, round(x0 - 0.1, 3), round(y0 - 0.1, 3), round(x1 + 0.1, 3), round(y1 + 0.1, 3))
    _strip_silk(fp)
    fp.to_file(os.path.join(outdir, name + ".kicad_mod"))


def ftsh(outdir, name, drop6):
    """Samtec FTSH-107-01-x-DV 2 x 7 1.27 mm SMT, from the Samtec recommended footprint
    (lib_verification_2026-11-11.md section 4): pads 2.79 x 0.74 mm, row centre distance 4.07 mm, body
    3.43 x 9.02 mm maximum. Courtyard = max(pad toes, body) + 0.10 mm (D-03). Position 6 omitted when drop6
    (B.8 J101: 6 omitted, key)."""
    L = hdr(name, "Samtec FTSH-107-01-x-DV, 2x07 1.27 mm SMT vertical%s" % (", position 6 removed" if drop6 else ""))
    for n in range(1, 15):
        if drop6 and n == 6:
            continue
        x = -2.035 if n % 2 else 2.035
        y = -3.81 + ((n - 1) // 2) * 1.27
        L.append(smd_pad(str(n), x, y, 2.79, 0.74, "rect"))
    cx = 2.035 + 2.79 / 2 + 0.10
    cy = max(3.81 + 0.37, 9.02 / 2) + 0.10
    L.append(rect("F.CrtYd", -cx, -cy, cx, cy))
    L.append(rect("F.Fab", -1.715, -4.51, 1.715, 4.51, 0.1))
    L.append(line("F.SilkS", -1.7, -4.75, 1.7, -4.75, 0.12))   # body ends, clear of the pads (pad ends +-4.18)
    L.append(line("F.SilkS", -1.7, 4.75, 1.7, 4.75, 0.12))
    L.append(line("F.SilkS", -3.0, -4.85, -2.2, -4.85, 0.15))  # pin-1 mark above pad 1
    write(outdir, name, L)


CUSTOM = {
    "R0402": lambda o, n: tight(o, n, "Resistor_SMD", "R_0402_1005Metric"),
    "R0603": lambda o, n: tight(o, n, "Resistor_SMD", "R_0603_1608Metric"),
    "R0805": lambda o, n: tight(o, n, "Resistor_SMD", "R_0805_2012Metric"),
    "R1206": lambda o, n: tight(o, n, "Resistor_SMD", "R_1206_3216Metric"),
    "C0402": lambda o, n: tight(o, n, "Capacitor_SMD", "C_0402_1005Metric"),
    "C0603": lambda o, n: tight(o, n, "Capacitor_SMD", "C_0603_1608Metric"),
    "C0805": lambda o, n: tight(o, n, "Capacitor_SMD", "C_0805_2012Metric"),
    "C1206": lambda o, n: tight(o, n, "Capacitor_SMD", "C_1206_3216Metric"),
    "C1210": lambda o, n: tight(o, n, "Capacitor_SMD", "C_1210_3225Metric"),
    "SMA": lambda o, n: tight(o, n, "Diode_SMD", "D_SMA"),
    "SOD-323": lambda o, n: tight(o, n, "Diode_SMD", "D_SOD-323"),
    "SOT-23-6": lambda o, n: tight(o, n, "Package_TO_SOT_SMD", "SOT-23-6"),
    "SOT-23": lambda o, n: tight(o, n, "Package_TO_SOT_SMD", "SOT-23"),
    "SC70-5": lambda o, n: tight(o, n, "Package_TO_SOT_SMD", "Texas_R-PDSO-G5_DCK-5"),
    "SC70-6": lambda o, n: tight(o, n, "Package_TO_SOT_SMD", "SOT-363_SC-70-6"),
    "SSOP-8": ssop_ti,

    "CHG22": chg22, "TAP_1.5": tap,
    "WPTH_1.3": lambda o, n: lead_pth(o, n, 1.3, 2.3), "WPTH_1.5": lambda o, n: lead_pth(o, n, 1.5, 2.5),
    "WSMD_2": lambda o, n: lead_smd(o, n, 2), "WSMD_3": lambda o, n: lead_smd(o, n, 3),
    "EPTH_1.0": epad, "FT2_HOLE": ft2_hole,
    "FT1_MARK": lambda o, n: foot_mark(o, n, 4.0, 1.6, True), "FT2_MARK": lambda o, n: foot_mark(o, n, 4.0, 4.0, False),
    "M3": m3, "VQFN24": vqfn24,
    "J2x7_NOPIN6": lambda o, n: ftsh(o, n, True), "J2x7_EIB": lambda o, n: ftsh(o, n, False),
}
EXTRA = {"cr": ["FT2_HOLE", "FT1_MARK", "FT2_MARK"], "eib": ["M3"]}


def build(board, outdir):
    lib = "charger_r8_%s" % board
    pdir = os.path.join(outdir, lib + ".pretty")
    if os.path.isdir(pdir):
        shutil.rmtree(pdir)
    os.makedirs(pdir)
    pkgs = sorted({p[3] for p in netlist.BOARDS[board]} | set(EXTRA[board]))
    for k in pkgs:
        src, name = fpmap.FP[k]
        if src.startswith("stock:"):
            shutil.copy(os.path.join(STOCK, src[6:] + ".pretty", name + ".kicad_mod"), pdir)
        else:
            CUSTOM[k](pdir, name)
    with open(os.path.join(outdir, "fp-lib-table"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(fp_lib_table (version 7)\n  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.pretty")'
                '(options "")(descr "project-local, generated"))\n)\n' % (lib, lib))
    return len(pkgs)


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
