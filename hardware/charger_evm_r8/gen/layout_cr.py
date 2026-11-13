"""CR placement data on the plug-on outline (D-39; generator step 4 of D-50, LAYOUT_DECISIONS D-51, D-52).

Every coordinate is an Eagle board coordinate (A.2 convention, MB frame, +y up; D-01) taken from
docs/charger_bq25798_wiring_design_2026-11-05.md r9 A.8 / B.8; deviations carry a D-nn tag that LAYOUT_DECISIONS.md
explains. The outline, the MB data and the region geometry come from `cr_geometry.py`.

Retired with the r7 outline (D-39; outline_change_2026-11-12/retired.md section 4): the 11-vertex outline and its
chamfer, the tab X / tab Y regions, the F01-F24 tap grid and low row, the feet FT1/FT2 and the fill hole, the B1R
wedge and the bead spots, the comparator band and its corners, the MB bottom-clearance rule (mb_bottom_clearance,
r7_calc), every bottom-side region and phase (D-17, D-18, D-19, D-32, D-34, D-44), and the RIM_X / LFC_Y constants.
"""
import os
import sys

import pcbnew
from shapely.geometry import Point, box
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cr_geometry as G  # noqa: E402

YOFF = G.YOFF
LAYERS = 4

OUTLINE = G.OUTLINE          # rectangle x 18.584-67, y 7-94 (D-39)
P = G.P
INSET = G.INSET              # A.8: every courtyard >= 0.5 mm inside the outline

# ------------------------------------------------------------------ fixed placements (x, y, rot)
# The power block keeps its A.8 / D-09 coordinates (outline_change_2026-11-12/routing.md 5.1): it lies inside the
# new outline, and the route_cr.py power copper (D-21, D-22, D-23, D-33) is drawn around it. D-09 is re-derived at
# placement (step 5); these are the start values.
FIXED = {
    "J1": (45.998, 39.084, 0),                 # CHG element pin 1 (A.8 table); CR side of the D-41 TSW stack
    "W1": (30.3, 61.2, 0), "W2": (27.7, 61.2, 0), "W3": (24.3, 45.4, 0), "W4": (24.3, 55.6, 0),   # A.8 / D-45
    # eFuse cluster (A.8 per-region table; D-09 shifts of <= 0.80 mm)
    "U101": (41.70, 63.65, 0),
    "C102c": (41.80, 60.27, 0),
    "C102a": (40.95, 57.14, 0),
    "R102": (43.55, 57.76, 0),
    "C102b": (42.125, 53.14, 0),
    "D107": (37.90, 56.30, 0),
    "C103": (38.08, 64.88, 0),
    "D103": (33.50, 64.84, 0),
    "J101": (40.60, 46.83, 0),                 # D-10 (kept: bounded by internal regions, not by the outline)
}
# Not fixed any more (D-52): the comparators U102, U103, U119, U120 (r7 band retired; packed in the analog window,
# D-11 re-derived), R175 (r7 tab X; now behind the J-TAP T6 cavity, D-46), W6/W7 (plated through-hole pads at
# 2.54 mm pitch, D-45: the r8 SMT coordinates overlap at the new pitch), the +x pocket R101/C101/R105/R103 (0603 now,
# D-44; packed toward U101 pins 7-13 by connectivity) and J102 (J-TAP, packed in its own region, D-46).
ORIENT = {
    "U101": ("3", "-y"),       # IN/IN_SYS edge (pins 1-6) facing -y (A.8, r4)
    "C102a": ("1", "+y"),      # VCHGIN pad at the top
    "R102": ("2", "+y"),       # N_UV pad at the top
    "D107": ("1", "+y"),       # cathode at the top
    "C103": ("1", "+y"),       # VCHGOUT pad at the top
    "D103": ("1", "+x"),       # cathode at the +x end
}

BOARD_ONLY = []                # no foot, fill hole or mounting hole on the plug-on CR (D-19, D-42, D-43)
PARK = (75.0, 50.0)            # outside the outline (x > 67): a part the packer cannot place is visible there

# ------------------------------------------------------------------ regions (MB frame)
DIV_STRIP = box(23.15, 42.14, 36.50, 45.69).difference(Point(24.3, 45.4).buffer(1.25 + 0.5))   # A.8 / D-13
J101_REG = box(37.0, 42.13, 44.5, 51.53)
IN_STRIP = box(36.1, 52.03, 44.55, 61.55)
OUT_STRIP = box(30.8, 62.85, 39.3, 66.64)
POCKET = box(44.3, 63.40, 48.2, 66.64)
U101_CRT = box(41.70 - 2.59, 63.65 - 2.59, 41.70 + 2.59, 63.65 + 2.59)
W_PADS = unary_union([Point(30.3, 61.2).buffer(1.15 + 0.5), Point(27.7, 61.2).buffer(1.15 + 0.5),
                      Point(24.3, 45.4).buffer(1.25 + 0.5), Point(24.3, 55.6).buffer(1.25 + 0.5)])
HDR_PADS = unary_union([box(45.998 - 1.2, 39.084 - 1.2, 45.998 + 1.2, 61.944 + 1.2),
                        box(20.998 - 1.2, 36.544 - 1.2, 20.998 + 1.2, 64.484 + 1.2)])

# fixed power vias of route_cr (VCHGIN C102b/C102c clusters, VCHGOUT under the D103 cathode): no part (D-33)
PRE_VIA_SITES = [(39.45, 52.60), (39.45, 53.40), (39.45, 54.20), (40.35, 51.62), (40.95, 51.62), (39.75, 60.35),
                 (39.75, 61.05), (34.00, 63.35), (34.80, 63.35), (35.60, 63.35), (36.40, 63.35)]
PRE_VIA_KO = unary_union([Point(c).buffer(0.30 + 0.25) for c in PRE_VIA_SITES])
# VCHGOUT L1 corridor from W1 to the D103 cathode below the D103 anode (D-22): no top part
VOUT_BELT = box(29.00, 59.00, 37.30, 64.20)
INTERIOR = (INSET.difference(J101_REG.buffer(0.5, join_style=2))
            .difference(IN_STRIP.buffer(0.5, join_style=2)).difference(OUT_STRIP.buffer(0.5, join_style=2))
            .difference(U101_CRT.buffer(0.5, join_style=2)).difference(POCKET.buffer(0.5, join_style=2))
            .difference(W_PADS).difference(HDR_PADS).difference(DIV_STRIP.buffer(0.01))
            .difference(VOUT_BELT).difference(PRE_VIA_KO))
LOOP = unary_union([OUT_STRIP, U101_CRT, IN_STRIP, POCKET])   # U101 commutation-loop region (A.8, H.23(f))
# Analog window (D-20 window y 30.8-66.86; D-11 interim 10 mm rim to the MB 5V copper, TODO(measure: operator,
# MS4)); 3 mm from the U101 loop region as in r7. Preferred, not hard (D-20): the wide window is the fallback and
# check_constraints lists every analog part outside the strict window as an exemption.
ANALOG_STRICT = INTERIOR.intersection(G.analog_window()).difference(LOOP.buffer(3.0))
ANALOG_WIDE = INTERIOR.intersection(box(G.X0, G.WIN_Y[0], G.X1, G.WIN_Y[1])).difference(LOOP.buffer(3.0))
# J-TAP (D-46): +x half of the CR, every straight-line A.4 maximum met (cr_geometry.jtap_region), clear of the fixed
# power block. Latch finger access: TODO(verify: Molex 43045 header drawing) the latch side; checked at placement.
JTAP_REG = INTERIOR.intersection(G.jtap_region())


def rule_areas():
    """D-20 (amended 2026-11-12): L4 (B.Cu) is a solid GND plane with no signals and no power straps. A rule area
    over the whole outline forbids tracks on B.Cu; pours, pads and vias stay allowed. No footprint rule area: every
    SMT part is on the top (D-44), and the r7 bottom-clearance, feet, B1R and bead-spot areas retire (D-52)."""
    B = pcbnew.B_Cu
    return [("L4_no_tracks", P, [B], dict(tracks=True, vias=False, pads=False, pour=False, fps=False))]


# ------------------------------------------------------------------ packer regions and phases
GRID_BOUNDS = (G.X0 - 0.5, G.Y0 - 0.5, G.X1 + 0.5, G.Y1 + 0.5)

ANALOG_ICS = ["U102", "U103", "U119", "U120", "D104", "D105", "D106"]   # comparators and BAV199 clamps (D-11)
LOGIC_ICS = ["U105", "U106", "U107", "U110", "U118"]                    # the 5-LVC gate (D-47)
DIVIDERS = ["R109", "R111", "R114", "R110", "R112", "R115"]
DECOUPLE = {"C110": "U102", "C111": "U103", "C114": "U105", "C115": "U106", "C116": "U107", "C119": "U110",
            "C126": "U118", "C131": "U119", "C132": "U120"}
# comparator input, reference, hysteresis, filter and timing passives: in the analog window (A.7 thermal band
# content rule carried to the D-20 window)
ANALOG_PASSIVES = {"C106", "C107", "C108", "C130", "R113", "R116", "R184", "R185", "R186", "R187", "R188", "R189",
                   "R129", "C129"}
LEADS = ["W6", "W7"]
POWER_NETS = {"/GND", "/3V3", "/VCHGIN", "/VCHGOUT", "/VCHG"}
REGIONS = {}
PHASES = []
TRIES = 150
PACK_MARGIN = 0.08   # routing channel kept around every courtyard (D-15)
# r9 step-5 placement fix: on the 0.25 mm courtyard basis (D-52) an 0805 row (1.89 mm) and an 0603 row (1.44 mm)
# need 3.33 mm of the 3.55 mm divider strip (A.8, D-13). With the 0.08 mm channel on every side of each courtyard
# (4 x 0.08 = 0.32 mm) two rows need 3.65 mm and do not fit, and one row is too long for the strip, so R109 and R112
# were left unplaced. The strip phase uses the packer default 0.03 mm (two rows need 3.45 mm); a deviation from the
# D-15 channel inside the strip only.
PHASE_MARGIN = {"dividers": 0.03}
PLACED = set()
CRT_GROW = {}        # the r7 routing-study variants (D-34) retire with the bottom side
THT_BOTH_SIDES = True   # r9 step-5 fix: through-hole parts are packed against the courtyards of both sides

# ------------------------------------------------------------------ placement variants (r9 step 5)
# LAYOUT_VARIANT selects the packer inputs. "B" (the default since D-54) re-arranges the inputs of the gate-logic and
# comparator cluster for routability (cr/variants_r9/B). "A" is the r9 step-5 baseline (cr/variants_r9/A), kept
# reproducible and not changed by any B entry below. Every fixed coordinate, region rule and constraint of A and B is
# the same. LAYOUT_DECISIONS D-54 selects B on the routability probe.
VARIANT = os.environ.get("LAYOUT_VARIANT", "B").strip().upper()
if VARIANT not in ("A", "B"):
    raise SystemExit("LAYOUT_VARIANT must be A or B, not %r" % VARIANT)
# B: the logic box is the free area below J101 (the J101 region + 0.5 mm starts at y 41.63), left of the J1 +x
# column and outside the -x part of the strict analog window (x < 40.0), so the gate ICs sit between the comparator
# outputs and J101 and leave the window pocket to the comparators and their networks. The strict window reaches
# x ~42 at y 31-41 (its 5V-rim edge is diagonal there); that corner is given to the logic ICs.
B_LOGIC_BOX = INTERIOR.intersection(box(35.0, 16.0, 45.0, 41.6)).difference(
    ANALOG_STRICT.intersection(box(G.X0, G.Y0, 40.0, G.Y1)))
# B: explicit packer targets (MB frame).
# - J102 at the -x end of the +x half, east of the logic box: the tap nets enter the logic box (QUAL_TAP) and the
#   comparator pocket (FCC_TAP, H1_RB, T2C, T1_VMOT) from the +x side, and the T2 run to C-D2 is shorter than in A.
# - The comparators form the lower row of the pocket, west to east U102, U103 (under the dividers that feed them),
#   U120, U119 (U119 drives FCCN into three gate ICs, so it sits next to the logic box).
# - The J101 ribbon resistors stand in one row under J101 in the order R130, R131A, R131B, R132: R130 (pin 5) and
#   R131A (pin 7) reach the -x pad column through the channel outside it, the outer track to the higher pin; R131B
#   (pin 8) and R132 (pin 10) reach the +x column through the channel between the columns, the track next to the
#   pads to the lower pin. U110 (ILIM_REL to R131A and R131B, the two middle positions) sits below the row and U106
#   (CE_DRV to R130, RFC_OFF to R132, the two outer positions) below U110, so the U106 pair can pass outside the
#   U110 pair on each side.
# - The rest of the gate sits below the comparator row: U105 (FCCN in from U119, FCCNN and P5N out) next to U119,
#   U118 (H1, UVB, FCC_ON in from the row) below it, U107 (QUAL from J102, QF to U110) next to the J102 -x column.
B_TARGETS = {
    "J102": (50.5, 26.0),
    "U102": (26.5, 33.0), "U103": (30.1, 33.0), "U120": (33.7, 33.0), "U119": (37.3, 33.0),
    "R130": (37.4, 40.2), "R131A": (38.8, 40.2), "R131B": (40.2, 40.2), "R132": (41.6, 40.2),
    "U110": (42.4, 36.6), "U106": (42.4, 32.3), "U105": (38.0, 28.0), "U107": (42.6, 27.0), "U118": (38.0, 24.2),
    # C125 (10 uF, the 3V3 bulk capacitor; the rail enters through R176/R177 from J101 pins 1 and 2) has no signal
    # net, so A packs it into the bottom-left corner by fill; in B it sits at the centre of its loads.
    "C125": (36.0, 30.0),
}
# B: rotations. J102 rot 90 puts row A (T2C, CHG_IIN, FCC_TAP, H1_RB) on the -x column. A comparator at rot 180
# has IN+ (pin 3) and IN- (pin 4) at the top corners (toward the dividers), OUT (pin 1) at the bottom right
# (toward the logic box) and VCC (pin 6) at the bottom left (its decoupler below it). The ribbon resistors stand
# vertical (rot 90) so their tracks run straight up to J101.
B_ROT = {"J102": (90,), "U102": (180,), "U103": (180,), "U119": (180,), "U120": (180,),
         "R130": (90,), "R131A": (90,), "R131B": (90,), "R132": (90,)}
B_COMPARATORS = ["U102", "U103", "U119", "U120"]
B_CLAMPS = ["D104", "D105", "D106"]
B_J101_SERIES = ["R130", "R131A", "R132", "R131B"]
B_COMP_DECOUPLE = ["C110", "C111", "C131", "C132"]
B_LOGIC_DECOUPLE = ["C114", "C115", "C116", "C119", "C126"]
# B: each gate IC is packed in its own phase and its decoupler at once after it, so the next IC cannot take the
# space at the 3V3 pad (with one phase for all five ICs and one for the five decouplers, the decouplers landed
# 2.1-5.7 mm from their 3V3 pads). The order is the J101 end first.
B_LOGIC_ORDER = ["U110", "U106", "U105", "U107", "U118"]
# B: the CHG_IIN filter joins J102 pad 2 to U101 pin 13 (N_IMON). In B, R129 may use the whole D-20 window
# (int_analog_wide), so it sits east of the J1 +x column on the J102-U101 path instead of in the comparator pocket,
# and C129 (CHG_IIN to GND) sits at J102 pad 2. Neither is a comparator-network part, and check_constraints does not
# test them against the strict window.
B_WIDE_PASSIVES = {"R129"}
B_TAP_PASSIVES = {"C129"}
# B: the FCC comparator networks (U119, U120) are packed before the H1/UVB networks (U102, U103), so they keep the
# pocket space next to their comparators at the +x end.
B_FCC_PASSIVES = ["C130", "R184", "R185", "R186", "R187", "R188", "R189"]


def setup(fps):
    global PHASES
    REGIONS.update({
        "jtap": JTAP_REG,
        "int_analog": ANALOG_STRICT,
        "int_analog_wide": ANALOG_WIDE,
        "div": DIV_STRIP,
        "int_logic": INTERIOR,
    })
    named = set(FIXED) | set(ANALOG_ICS) | set(LOGIC_ICS) | set(DIVIDERS) | set(DECOUPLE) | ANALOG_PASSIVES \
        | set(LEADS) | {"J102"}
    if VARIANT == "B":
        named |= set(B_J101_SERIES)   # placed in their own phase in B, never again in "other parts"
    rest = sorted(r for r in fps if r not in named and not r.startswith("#"))
    flipped = sorted(r for r, fp in fps.items() if fp.IsFlipped())
    if flipped:   # D-44: every SMT part on the top; the netlist carries no side="B" since 2026-11-12
        raise SystemExit("bottom-side parts in the netlist (D-44 forbids): %s" % ", ".join(flipped))
    if VARIANT == "B":
        REGIONS["logic_box"] = B_LOGIC_BOX
        # B order: J102 first, then the fixed-size divider strip, then the comparators (explicit targets), each IC
        # group followed at once by its decouplers so the 3V3 pad keeps its neighbour, the BAV199 clamps after the
        # comparators (their centroid then includes the comparator input pins), the ribbon resistors before the
        # gate ICs, and the FCC networks before the H1/UVB networks inside the window.
        PHASES = [("J-TAP", "F", ["J102"]),
                  ("dividers", "F", [r for r in DIVIDERS if r in fps]),
                  ("comparators", "F", [r for r in B_COMPARATORS if r in fps], "int_analog_wide"),
                  ("comparator decouplers", "F", [r for r in B_COMP_DECOUPLE if r in fps]),
                  ("clamps", "F", [r for r in B_CLAMPS if r in fps], "int_analog_wide"),
                  ("J101 series", "F", [r for r in B_J101_SERIES if r in fps], "int_logic"),
                  ] + [ph for ic in B_LOGIC_ORDER if ic in fps for ph in (
                      ("logic IC " + ic, "F", [ic], "int_logic"),
                      ("logic decoupler " + ic, "F", [c for c in B_LOGIC_DECOUPLE if DECOUPLE[c] == ic and c in fps]))
                  ] + [
                  ("FCC passives", "F", [r for r in B_FCC_PASSIVES if r in fps], "int_analog_wide"),
                  ("analog passives", "F", sorted(r for r in ANALOG_PASSIVES if r in fps and r not in B_FCC_PASSIVES),
                   "int_analog_wide"),
                  ("lead pads", "F", [r for r in LEADS if r in fps]),
                  ("other parts", "F", rest)]
        return
    PHASES = [("J-TAP", "F", ["J102"]),
              ("analog ICs", "F", [r for r in ANALOG_ICS if r in fps], "int_analog_wide"),
              ("dividers", "F", [r for r in DIVIDERS if r in fps]),
              ("logic ICs", "F", [r for r in LOGIC_ICS if r in fps]),
              ("decouplers", "F", [r for r in DECOUPLE if r in fps]),
              ("analog passives", "F", sorted(r for r in ANALOG_PASSIVES if r in fps), "int_analog_wide"),
              ("lead pads", "F", [r for r in LEADS if r in fps]),
              ("other parts", "F", rest)]


def region_name(ref):
    if VARIANT == "B":
        if ref in LOGIC_ICS:
            return "logic_box"
        if ref in B_WIDE_PASSIVES:
            return "int_analog_wide"
        if ref in B_J101_SERIES or ref in B_COMP_DECOUPLE or ref in B_TAP_PASSIVES:
            # the ribbon resistors straddle the window edge under J101; a comparator decoupler sits below the VCC
            # pad of its comparator, under the window bottom (no D-20 rule binds a decoupler)
            return "int_logic"
    if ref == "J102":
        return "jtap"
    if ref in DIVIDERS:
        return "div"
    if ref in ANALOG_ICS or ref in ANALOG_PASSIVES:
        return "int_analog"
    if ref in DECOUPLE and DECOUPLE[ref] in ANALOG_ICS:
        return "int_analog_wide"
    return "int_logic"


def fill(ref, phase):
    """True: pack bottom-left first (dense) instead of nearest to the connection centroid.
    Used for the divider strip only (r9 step-5 placement fix): the strip is 3.55 mm high, so it holds the six
    dividers only as two dense rows; centroid-nearest packing centred R111/R114 in the strip and left R109 and
    R112 unplaced (parked off the board)."""
    return phase.startswith("dividers")


def prio(ref):
    if ref in DECOUPLE:
        return 2
    if ref in ANALOG_ICS:
        return 1
    return 0


def _pads_of_net(net, fps, fr, exclude):
    pts = []
    for r, fp in fps.items():
        if r == exclude or not (r in FIXED or r in PLACED):
            continue
        for p in fp.Pads():
            if p.GetNetname() == net:
                pts.append(fr.e(p.GetPosition()))
    return pts


def target(ref, fps, fr, pinnet):
    if VARIANT == "B" and ref in B_TARGETS:
        return B_TARGETS[ref]
    fp = fps[ref]
    if ref in DECOUPLE:
        ic = fps[DECOUPLE[ref]]
        if DECOUPLE[ref] in FIXED or DECOUPLE[ref] in PLACED:
            for p in ic.Pads():                 # the supply pad of the IC, found by net (no pin-number table)
                if p.GetNetname() == "/3V3":
                    return fr.e(p.GetPosition())
    if ref == "J102":
        # D-46: keep the T2 run short to C-D2 (x 67.4-69.7, y 69.9): target the point of the region nearest C-D2.1
        from shapely.ops import nearest_points
        return nearest_points(JTAP_REG, Point(G.far_end("7")[1]))[0].coords[0]
    pts = []
    for p in fp.Pads():
        n = p.GetNetname()
        if n and n not in POWER_NETS:
            pts += _pads_of_net(n, fps, fr, ref)
    if not pts:
        return None
    return (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))


def rotations(ref):
    if VARIANT == "B" and ref in B_ROT:
        return B_ROT[ref]
    if ref[0] in "RC":
        return (0, 90)
    if ref.startswith("D1") and ref not in ("D104", "D105", "D106"):
        return (0, 90)
    return (0, 90, 180, 270)
