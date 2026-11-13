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
PHASE_MARGIN = {}
PLACED = set()
CRT_GROW = {}        # the r7 routing-study variants (D-34) retire with the bottom side


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
    rest = sorted(r for r in fps if r not in named and not r.startswith("#"))
    flipped = sorted(r for r, fp in fps.items() if fp.IsFlipped())
    if flipped:   # D-44: every SMT part on the top; the netlist carries no side="B" since 2026-11-12
        raise SystemExit("bottom-side parts in the netlist (D-44 forbids): %s" % ", ".join(flipped))
    PHASES = [("J-TAP", "F", ["J102"]),
              ("analog ICs", "F", [r for r in ANALOG_ICS if r in fps], "int_analog_wide"),
              ("dividers", "F", [r for r in DIVIDERS if r in fps]),
              ("logic ICs", "F", [r for r in LOGIC_ICS if r in fps]),
              ("decouplers", "F", [r for r in DECOUPLE if r in fps]),
              ("analog passives", "F", sorted(r for r in ANALOG_PASSIVES if r in fps), "int_analog_wide"),
              ("lead pads", "F", [r for r in LEADS if r in fps]),
              ("other parts", "F", rest)]


def region_name(ref):
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
    """True: pack bottom-left first (dense) instead of nearest to the connection centroid. Not used (D-52)."""
    return False


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
    if ref[0] in "RC":
        return (0, 90)
    if ref.startswith("D1") and ref not in ("D104", "D105", "D106"):
        return (0, 90)
    return (0, 90, 180, 270)
