"""CR plug-on outline geometry and the H.23 successor checks (D-50 step 4; LAYOUT_DECISIONS D-51, D-52).

Every coordinate is an MB-frame (Eagle board) coordinate, top view, +y up (D-01); KiCad Y = 100 - y.
The MB data come from `references/Scale Car Board PCB 20260625.brd` through `mb_brd.py` (stdlib parser).

Run headless (no KiCad board needed): python cr_geometry.py [<cr projdir>]
  - prints the geometry rows as a markdown table;
  - writes <projdir>/geometry_check.md and <projdir>/geometry_check.json when a projdir is given.
`check_constraints.py cr` appends the same rows to the board measurements, and adds the placed-board rows
(J-TAP run lengths from the placed J102).
"""
import json
import math
import os
import sys

from shapely.affinity import rotate
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_brd as M  # noqa: E402

# ------------------------------------------------------------------ outline (D-39)
X0, X1, Y0, Y1 = 18.584, 67.0, 7.0, 94.0
OUTLINE = [(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)]   # rectangle, no chamfer, no tab, no concave corner (D-39)
P = Polygon(OUTLINE)
X_MID = (X0 + X1) / 2                               # 42.792: the +x half of the CR (D-46 "+x side", D-52)
INSET_MM = 0.5                                      # A.8: every courtyard >= 0.5 mm inside the outline (kept, D-52)
INSET = P.buffer(-INSET_MM, join_style=2)
YOFF = 100.0                                        # D-01: KiCad Y = 100 - y, KiCad Y 6.00-93.00

# ------------------------------------------------------------------ final outline and holes (D-60, route-race R9-02)
# Operator rulings 2026-11-13 (given to the routing session): "trim away the unused area of the board"; "The final
# board outline does not need to be rectangular"; "add holes in the corners for 6-32 screws" (the holes hold a
# 3D-printed support; MB clearance under them is not a criterion); keep a +x key ear (D-41). The D-39 rectangle P
# stays the placement frame; the board is trimmed after routing by gen/trim_cr.py (tools/pcb/corridor_route/
# trim_outline.py with the arguments below), which asserts that the result equals these values.
# D-62 (operator ruling 2026-11-13, route-race R9-04): "Keep the trim rectilinear, or with 30, 45, or 60deg angles.
# Fillets on corners is good though." FINAL_OUTLINE holds the corners before the fillets (edges at 0, 30, 45, 60, 90,
# 120, 135 or 150 degrees; slanted edges >= 2.0 mm); every corner is rounded with a 1.0 mm arc (true Edge.Cuts arcs).
# Superseded (D-60/D-61): the convex 18-vertex hull, 2241.6 mm2, MH2 (54.85, 63.79).
TRIM_ANGLES = (0, 30, 45, 60, 90, 120, 135, 150)
TRIM_MIN_EDGE = 2.0
FILLET = 1.0
FINAL_OUTLINE = [(58.600, 71.043), (55.835, 72.640), (25.266, 72.640), (22.564, 71.079), (18.584, 67.100),
                 (18.584, 28.193), (21.845, 22.545), (47.332, 7.830), (56.928, 7.830), (58.600, 10.726)]
P_CORNERS = Polygon(FINAL_OUTLINE)
P_FINAL = P_CORNERS.buffer(-FILLET, 64, join_style=1).buffer(FILLET, 64, join_style=1)   # every corner convex (D-62)
KEY_EAR = (50.0, 52.0, 58.6, 71.0)                  # +x key ear kept by the trim (operator choice, D-41 key)
TRIM_MARGIN = 1.0                                   # trim margin around the used area (mm)
HOLE_DRILL = 3.70                                   # NPTH, #6 free fit for a 6-32 screw
HOLE_KEEPOUT = 4.0                                  # all-layer copper keep-out radius
HOLE_HEAD = 3.6                                     # screw-head disc radius kept on the board
# trim_outline.py rounds the hull to 0.01 mm and simplifies it with a 0.05 mm tolerance, so the outline may cut up to
# 0.05 mm into the ear and the head discs, and its -x vertices sit at x 18.58 (0.004 mm outside the D-39 edge).
TRIM_TOL = 0.06                                     # 0.05 mm simplify + 0.01 mm rounding of the hole centres
MOUNTING_HOLES = {"MH1": (26.23, 69.04), "MH2": (54.85, 68.79), "MH3": (54.85, 11.43), "MH4": (24.48, 25.18)}
FINAL_INSET = P_FINAL.buffer(-INSET_MM, join_style=2)

# ------------------------------------------------------------------ D-41 stack (heights above the MB top, mm)
SSQ_INSULATOR = 8.51          # SSQ-1xx-01 insulator height (Samtec SSQ TH catalogue; D-41)
TSW_BODY = 2.54               # TSW body (Samtec TSW TH catalogue, dimension B body; D-41)
TSW_POST_C = 5.84             # TSW-1xx-07 post C (Samtec TSW TH catalogue; D-41)
CR_THICK = 1.6                # CR board thickness (D-20 stack-up, 1.6 mm OSH Park 4-layer)
CR_UNDERSIDE = SSQ_INSULATOR + TSW_BODY        # 11.05 mm, hard stop (D-41)
CR_TOP = CR_UNDERSIDE + CR_THICK               # 12.65 mm
ENGAGE_START = CR_UNDERSIDE + TSW_POST_C       # 16.89 mm: pins begin to engage (D-41 rotated-CR key)
TERMINAL_H = 21.70            # TB005-762 terminal blocks J-BL, J-FC, J-BT (mb_mechanical.md Table 3;
#                               TB005-762_CUI.pdf p.2 side view)
TERMINALS = ("J-BL", "J-FC", "J-BT")

# ------------------------------------------------------------------ CHG holes (A.8 table, D-02)
CHG_COL = {"+x": 45.998, "-x": 20.998}
CHG_TABLE = {n: (45.998, 39.084 + 2.54 * (n - 1)) for n in range(1, 11)}
CHG_TABLE.update({11 + k: (20.998, 64.484 - 2.54 * k) for k in range(12)})
CHG_PAD = 1.9                  # CR pad diameter, PLACEHOLDER (A.8 / D-30), TODO(verify: Samtec TSW drawing)
CHG_CENTRE = (33.498, 50.514)  # centre of the two pin columns: (20.998 + 45.998) / 2, (36.544 + 64.484) / 2
CRT = 0.25                     # IPC-7351 nominal courtyard excess on the CR (D-03 amended 2026-11-12)
# TSW bodies on the CR underside (D-41): 2.54 mm wide, 2.54 mm per position, centred on the pin span
TSW_BODIES = {
    "TSW-110 (pins 1-10)": box(45.998 - 1.27, 39.084 - 1.27, 45.998 + 1.27, 61.944 + 1.27),
    "TSW-112 (pins 11-22)": box(20.998 - 1.27, 36.544 - 1.27, 20.998 + 1.27, 64.484 + 1.27),
}

# ------------------------------------------------------------------ J-TAP far ends (A.4 r9-4; D-46)
# J102 pad -> (tap, MB part, MB pad, A.4 maximum run in mm). Pad numbering is the placeholder stock footprint
# (row A = pads 1-5, row B = pads 6-10; netlist.py J102), TODO(verify: Molex 43045 drawing). Cavity map as
# re-mapped in r9-13 (D-46); superseded in r9-13: pad 1 T1, pad 2 T7b, pad 7 T2, pad 8 T17.
JTAP = {
    "1": ("T2", "C-D2", "1", 100.0), "2": ("T17", "J2", "09", 150.0), "3": ("T17r", "J2", "29", 150.0),
    "4": ("T5", "J1", "45", 120.0), "5": ("T13", "J2", "45", 150.0), "6": ("T6", "J1", "29", 120.0),
    "7": ("T1", "C-D6", "1", 150.0), "8": ("T7b", "C-D6", "2", 150.0), "9": ("T16", "J2", "43", 150.0),
    "10": ("T10", "J2", "47", 150.0),
}


def far_end(pad):
    tap, part, mpad, mx = JTAP[pad]
    return tap, M.pad(part, mpad), mx


def jtap_region():
    """Plan region where every point of the J102 courtyard meets every straight-line A.4 maximum (a necessary
    condition: the dressed run is longer), restricted to the +x half of the CR (D-46) and the 0.5 mm inset."""
    reg = INSET.intersection(box(X_MID, Y0, X1, Y1))
    for pad in JTAP:
        _, xy, mx = far_end(pad)
        reg = reg.intersection(Point(xy).buffer(mx, 256))
    return reg


# ------------------------------------------------------------------ MB heat and switching sources
def _poly_rim(name):
    """Layer-1 pours of MB signal <name>, grown by half the polygon line width (the copper rim)."""
    out = []
    for q in M.signal_polys(name):
        out.append(Polygon(q["pts"]).buffer(0).buffer(q["width"] / 2, join_style=2))
    return unary_union(out)


def _box(part, layers=(M.L_PLACE, M.L_DOCU, M.L_KEEPOUT)):
    e = M.extent(M.part(part), layers, True, ("wire", "rect", "poly"))
    return box(*e)


def five_v_copper():
    """REG-5V (LM1084, TO-263) keep-out box and the 5V layer-1 pour rim (A.7 thermal band source)."""
    return unary_union([_poly_rim("5V"), _box("REG-5V")])


def boost_boxes():
    """L-FC, L-BT, REG-FC, REG-BT part boxes and the VSW-FC / VSW-BT pour rims (mbparts.md 1.4)."""
    return unary_union([_box(p) for p in ("L-FC", "L-BT", "REG-FC", "REG-BT")]
                       + [_poly_rim("VSW-FC"), _poly_rim("VSW-BT")])


RIM_MM = 10.0       # A.7 thermal band: analog parts >= 10 mm in plan from the MB 5V copper rim (r7 RIM_X 39.53)
#                     TODO(measure: operator, MS4) the heat-source map that re-derives it (D-11)
WIN_Y = (30.8, 66.86)   # D-20 sensitive-part window (preferred, not hard): >= 10 mm from both inductor bodies


def analog_window():
    """D-20 window y 30.8-66.86 inside the inset, less the 10 mm rim around the MB 5V copper (D-11 interim)."""
    return INSET.intersection(box(X0, WIN_Y[0], X1, WIN_Y[1])).difference(five_v_copper().buffer(RIM_MM))


# ------------------------------------------------------------------ rows
def terminal_clearance():
    """Operator ruling (a) of 2026-11-12 (D-51): no part of the CR outline overlaps a power-terminal body in plan.
    Body = the TB005-762 package outline on .brd layer 51 (tDocu) wires, line centrelines (the package body
    12.60 mm across the pin row, -7.90 to +4.70 mm; TB005-762_CUI.pdf section A-A puts the pins 4.70 mm from the
    rear face, mb_mechanical.md 3.1). The silkscreen outer edge (layer 21) and the keep-out (layer 39) are
    reported as well."""
    out = []
    for t in TERMINALS:
        p = M.part(t)
        body = M.extent(p, [M.L_DOCU], False, ("wire",))
        silk = M.extent(p, [M.L_PLACE], True, ("wire",))
        keep = M.extent(p, [M.L_KEEPOUT], False, ("wire",))
        yov = min(body[3], Y1) - max(body[1], Y0)
        out.append(dict(ref=t, package=p["package"], body=body, silk=silk, keep=keep,
                        gap_body=X0 - body[2], gap_silk=X0 - silk[2], gap_keep=X0 - keep[2], y_overlap=yov,
                        plan_overlap=P_FINAL.intersection(box(*body)).area))
    return out


def rotated_key():
    """D-41 key: a CR rotated 180 degrees about the CHG centre lands on the terminal blocks before its pins engage.
    D-60: measured on the final (trimmed) outline."""
    rp = rotate(P_FINAL, 180, origin=CHG_CENTRE)
    hits = [t for t in TERMINALS if rp.intersection(box(*M.extent(M.part(t), [M.L_DOCU], False, ("wire",)))).area
            > 0]
    return rp.bounds, hits


def chg_rows():
    brd = M.pads_in_order("CHG")
    err = max(math.hypot(brd[n - 1][0] - CHG_TABLE[n][0], brd[n - 1][1] - CHG_TABLE[n][1]) for n in CHG_TABLE)
    pads = unary_union([Point(xy).buffer(CHG_PAD / 2, 64) for xy in CHG_TABLE.values()])
    edge = P_FINAL.exterior.distance(pads)
    bodies = {k: v.buffer(CRT, join_style=2) for k, v in TSW_BODIES.items()}
    inset_ok = {k: FINAL_INSET.buffer(1e-6).contains(v) for k, v in bodies.items()}
    margin = {k: (FINAL_INSET.exterior.distance(v) if inset_ok[k] else -v.difference(FINAL_INSET).area)
              for k, v in bodies.items()}
    return err, edge, inset_ok, margin


def edge_parts():
    """MB parts whose plan box (layers 21/51/39) crosses the outline boundary (information; heights closed by D-51)."""
    out = []
    for name, p in M.load()["parts"].items():
        e = M.extent(p, [M.L_PLACE, M.L_DOCU, M.L_KEEPOUT], True, ("wire", "rect", "poly"))
        if e is None:
            continue
        g = box(*e)
        if g.intersects(P_FINAL) and not P_FINAL.contains(g):
            out.append(name)
    return sorted(out)


def rows():
    r = []

    def row(rule, item, measured, limit, ok):
        r.append(dict(rule=rule, item=item, measured=measured, limit=limit,
                      result="pass" if ok is True else ("FAIL" if ok is False else ok)))

    # H.23(a) successor: the outline
    row("H.23(a) successor: plug-on outline (D-39)", "Edge.Cuts", "4 vertices, %.3f x %.3f mm, area %.2f mm2, "
        "KiCad Y %.2f-%.2f" % (X1 - X0, Y1 - Y0, P.area, YOFF - Y1, YOFF - Y0), "48.416 x 87.000 mm, 4212.19 mm2",
        abs(P.area - 48.416 * 87.0) < 0.01 and len(OUTLINE) == 4)
    row("H.23(a) successor: courtyard inset 0.5 mm (A.8)", "INSET", "%.2f mm2" % INSET.area, "information", "info")
    # D-60 (route-race R9-02): the final outline after routing, inside the D-39 placement frame, and the holes
    convex = abs(P_CORNERS.convex_hull.area - P_CORNERS.area) < 1e-6
    # D-62: every edge direction in TRIM_ANGLES (mod 180, 0.5 deg), every slanted edge >= TRIM_MIN_EDGE
    bad_edges = []
    for k in range(len(FINAL_OUTLINE)):
        (x1_, y1_), (x2_, y2_) = FINAL_OUTLINE[k], FINAL_OUTLINE[(k + 1) % len(FINAL_OUTLINE)]
        ang = math.degrees(math.atan2(y2_ - y1_, x2_ - x1_)) % 180.0
        ln = math.hypot(x2_ - x1_, y2_ - y1_)
        dev = min(min(abs(ang - a_), 180.0 - abs(ang - a_)) for a_ in TRIM_ANGLES)
        if dev > 0.5 or (min(abs(ang - 0), abs(ang - 90), abs(ang - 180)) > 0.5 and ln < TRIM_MIN_EDGE - 1e-6):
            bad_edges.append("%d (%.1f deg, %.2f mm)" % (k, ang, ln))
    row("D-62 final outline (trimmed after routing, %.1f mm fillets), inside the D-39 rectangle" % FILLET,
        "FINAL_OUTLINE", "%d corners, filleted area %.1f mm2 (%.0f %% of D-39), x %.3f-%.3f, y %.2f-%.2f, %s; "
        "edges off the angle set or short: %s" % (
            (len(FINAL_OUTLINE), P_FINAL.area, 100 * P_FINAL.area / P.area) + P_FINAL.bounds[0::2]
            + P_FINAL.bounds[1::2] + ("convex" if convex else "not convex", ", ".join(bad_edges) or "none")),
        "inside the D-39 rectangle; -x edge at x %.3f (D-51); edges at %s deg, slanted >= %.1f mm" % (
            X0, "/".join(str(a_) for a_ in TRIM_ANGLES), TRIM_MIN_EDGE),
        P.buffer(0.01).contains(P_FINAL) and abs(P_FINAL.bounds[0] - X0) < 0.01 and P_FINAL.is_valid and not bad_edges)
    ear = box(*KEY_EAR)
    row("D-60 +x key ear kept (D-41)", "KEY_EAR", "box x %.1f-%.1f, y %.1f-%.1f; %.3f mm2 cut by the corner fillets" % (
        KEY_EAR[0], KEY_EAR[2], KEY_EAR[1], KEY_EAR[3], ear.difference(P_FINAL).area),
        "inside the outline corners (before the D-62 fillets) within the 0.06 mm trim tolerance; the D-41 key row is the "
        "functional check", P_CORNERS.buffer(TRIM_TOL).contains(ear))
    for h, (x, y) in MOUNTING_HOLES.items():
        c = Point(x, y)
        edge = P_FINAL.exterior.distance(c) - HOLE_DRILL / 2
        row("D-60 6-32 mounting hole (NPTH %.2f mm; head disc r %.1f mm on the board; keep-out r %.1f mm)" % (
            HOLE_DRILL, HOLE_HEAD, HOLE_KEEPOUT), h,
            "(%.2f, %.2f); hole edge %.2f mm from the board edge; head disc overhang %.3f mm" % (
                x, y, edge, max(0.0, HOLE_HEAD - P_FINAL.exterior.distance(c))),
            "head disc inside the final outline within the 0.06 mm trim tolerance",
            P_FINAL.buffer(TRIM_TOL + 1e-6).contains(c.buffer(HOLE_HEAD, 64)))
    # operator ruling (a) 2026-11-12: -x terminal clearance
    for t in terminal_clearance():
        ok = t["gap_body"] > 0 and t["plan_overlap"] == 0
        row("D-51 (operator ruling 2026-11-12 (a)): CR -x edge x %.3f clears the terminal body in plan" % X0,
            t["ref"] + " (" + t["package"] + ")",
            "body +x %.3f -> gap %.3f mm; silk outer +x %.3f -> %.3f mm; keep-out +x %.3f -> %.3f mm; "
            "y overlap with the outline %.2f mm" % (t["body"][2], t["gap_body"], t["silk"][2], t["gap_silk"],
                                                   t["keep"][2], t["gap_keep"], t["y_overlap"]),
            "gap > 0 (no plan overlap)", ok)
    bounds, hits = rotated_key()
    row("D-41 key: CR rotated 180 deg about (%.3f, %.3f) lands on the terminals" % CHG_CENTRE, ", ".join(hits),
        "rotated outline x %.3f-%.3f; engagement start %.2f mm, terminal top %.2f mm, margin %.2f mm" % (
            bounds[0], bounds[2], ENGAGE_START, TERMINAL_H, TERMINAL_H - ENGAGE_START),
        "J-BL and J-FC hit (D-41 as amended by D-60; J-BT not needed); engagement start < 21.70 mm",
        {"J-BL", "J-FC"} <= set(hits) and ENGAGE_START < TERMINAL_H)
    # H.23(j) successor: stack heights (D-41), information
    row("H.23(j) successor: D-41 stack heights", "TSW on SSQ", "CR underside %.2f mm, CR top %.2f mm, engagement "
        "start %.2f mm" % (CR_UNDERSIDE, CR_TOP, ENGAGE_START), "underside 11.05 mm (D-41)",
        abs(CR_UNDERSIDE - 11.05) < 1e-9)
    # CHG holes against the outline
    err, edge, inset_ok, margin = chg_rows()
    row("A.8 CHG holes in the .brd = the A.8 table (pin identity, D-02)", "MB CHG package", "max error %.4f mm" % err,
        "0.001 mm", err < 1e-3)
    row("H.23 successor: CHG pad (1.9 mm, PLACEHOLDER) to the outline edge", "J1 pads", "%.3f mm" % edge,
        ">= 0.5 mm (A.8 inset)", edge >= 0.5)
    for k, ok in inset_ok.items():
        row("H.23 successor: TSW body + 0.25 mm courtyard inside the 0.5 mm inset (D-41, D-03)", k,
            "margin %.3f mm" % margin[k], ">= 0", ok)
    # analog window and J-TAP region (information for the region table of layout_cr.py)
    aw = analog_window()
    row("H.23(h) successor: D-20 window y 30.8-66.86 less 10 mm from the MB 5V copper rim (D-11 interim)",
        "analog window", "%.1f mm2, x %.2f-%.2f" % (aw.area, aw.bounds[0], aw.bounds[2]),
        "information; TODO(measure: operator, MS4)", "info")
    jr = jtap_region()
    row("H.23(l) successor: J-TAP region, +x half, every straight-line A.4 maximum met", "J102 region",
        "%.1f mm2, x %.2f-%.2f, y %.2f-%.2f" % ((jr.area,) + jr.bounds[0::2] + jr.bounds[1::2]),
        "non-empty", jr.area > 0)
    for pad in sorted(JTAP, key=int):
        tap, xy, mx = far_end(pad)
        dmin = Point(xy).distance(INSET.intersection(box(X_MID, Y0, X1, Y1)))
        dmax = max(Point(xy).distance(Point(c)) for c in INSET.intersection(box(X_MID, Y0, X1, Y1)).exterior.coords)
        row("H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run)",
            "%s (J102.%s) -> %s.%s (%.3f, %.3f)" % (tap, pad, JTAP[pad][1], JTAP[pad][2], xy[0], xy[1]),
            "%.1f-%.1f mm" % (dmin, dmax), "<= %.0f mm (A.4)" % mx, dmax <= mx)
    ep = edge_parts()
    row("H.23(b) successor: MB parts crossing the outline edge (information; heights closed by D-51)",
        ", ".join(ep), "%d parts" % len(ep), "information", "info")
    return r


def area_booking(pretty):
    """H.23(e) successor: top-side courtyard booking of the CR part list (netlist.py, D-47) with the CR footprint
    library at the 0.25 mm basis (D-03 amended, D-44, D-52). Courtyard area = the F.CrtYd rectangle, or the sum of
    the F.CrtYd circles (CHG pads). DNP parts are counted (none on the CR). Returns (total, per-part dict)."""
    import fpmap
    import netlist
    from kiutils.footprint import Footprint
    per = {}
    for p in netlist.BOARDS["cr"]:
        ref, key = p[0], p[3]
        name = fpmap.fp("cr", key)[1]
        fp = Footprint.from_file(os.path.join(pretty, name + ".kicad_mod"))
        xs, ys, circ = [], [], 0.0
        for g in fp.graphicItems:
            if getattr(g, "layer", "") != "F.CrtYd":
                continue
            if hasattr(g, "center"):
                circ += math.pi * math.hypot(g.end.X - g.center.X, g.end.Y - g.center.Y) ** 2
            else:
                xs += [g.start.X, g.end.X]
                ys += [g.start.Y, g.end.Y]
        per[ref] = circ + ((max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0.0)
    return sum(per.values()), per


def table(rs):
    lines = ["| Rule (design row) | Item | Measured | Limit | Result |", "|---|---|---|---|---|"]
    lines += ["| %s | %s | %s | %s | %s |" % (x["rule"], x["item"], x["measured"], x["limit"], x["result"])
              for x in rs]
    return "\n".join(lines)


if __name__ == "__main__":
    rs = rows()
    if len(sys.argv) > 2:   # <projdir> <generated CR .pretty dir>: add the H.23(e) successor booking row
        tot, per = area_booking(sys.argv[2])
        big = ", ".join("%s %.1f" % kv for kv in sorted(per.items(), key=lambda kv: -kv[1])[:5])
        rs.append(dict(rule="H.23(e) successor: top-side courtyard booking, %d parts, 0.25 mm basis (D-44, D-52)"
                       % len(per), item="largest: " + big + " mm2",
                       measured="%.1f of %.1f mm2 = %.1f %%" % (tot, INSET.area, 100 * tot / INSET.area),
                       limit="<= 75 % (A.8 booking target)", result="pass" if tot <= 0.75 * INSET.area else "FAIL"))
    txt = table(rs)
    print(txt)
    if len(sys.argv) > 1:
        out = sys.argv[1]
        with open(os.path.join(out, "geometry_check.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# CR plug-on outline: geometry checks (gen/cr_geometry.py; D-51, D-52)\n\n"
                    "Source: `references/Scale Car Board PCB 20260625.brd` (MB frame, mm). Generated; do not "
                    "edit.\n\n" + txt + "\n")
        with open(os.path.join(out, "geometry_check.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(dict(rows=rs, terminals=terminal_clearance()), f, indent=1)
