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
    # A.8 / D-45. W2 x 27.7 -> 27.2 (D-55, review m-1): at the A.8 2.6 mm pitch the 2.3 mm W1 (VCHGOUT) and W2 (GND)
    # pads were 0.307 mm apart and their courtyards overlapped; at 3.1 mm the pad gap is 0.80 mm and the W2 courtyard
    # stays 0.85 mm from W6. route_cr.GND_L1_STAR moves with W2.
    "W1": (30.3, 61.2, 0), "W2": (27.2, 61.2, 0), "W3": (24.3, 45.4, 0), "W4": (24.3, 55.6, 0),
    # eFuse cluster (A.8 per-region table; D-09 shifts of <= 0.80 mm)
    "U101": (41.70, 63.65, 0),
    "C102c": (41.80, 60.27, 0),
    "C102a": (40.95, 57.14, 0),
    "R102": (43.55, 57.76, 0),
    "C102b": (42.125, 53.19, 0),               # y 53.14 -> 53.19 (D-55, review m-5): clears the J101 courtyard
    "D107": (37.90, 56.30, 0),
    "C103": (38.08, 64.88, 0),
    "D103": (33.50, 64.84, 0),
    "J101": (40.60, 46.83, 0),                 # D-10 (kept: bounded by internal regions, not by the outline)
}
# Not fixed any more (D-52): the comparators U102, U103, U119, U120 (r7 band retired; packed in the analog window,
# D-11 re-derived), R175 (r7 tab X; now behind the J-TAP T6 cavity, D-46), W6/W7 (plated through-hole pads at
# 2.54 mm pitch, D-45: the r8 SMT coordinates overlap at the new pitch), the U101 network R101/C101/R103/R104/R105/
# R129/R106s (0603 now, D-44; packed in the +x pocket and the north strip toward their U101 pins, D-55) and J102
# (J-TAP, packed in its own region, D-46).
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
# A.8 / D-13 divider strip. D-55 (review m-3): the W3 keep-out is stretched 0.7 mm toward +x (the union of the
# 1.75 mm circle and its +0.7 mm copy), so the dense fill packing shifts all six dividers +0.7 mm in x. R110 (the
# 0.1 % bottom of the H1 IN+ divider) then sits about 1.48 mm from the W3 18 AWG hand-solder pad instead of 0.78 mm;
# the strip has 0.90 mm of slack at its +x end.
DIV_W3_SHIFT = 0.7
_W3_KO = Point(24.3, 45.4).buffer(1.25 + 0.5)
# The strip left of x 26.13 (the r9 step-5 R109 courtyard edge 25.464 + 0.7 - the 0.03 mm packer margin) is closed
# as well; otherwise an 0603 fits under the circle and lands nearer to W3.
DIV_STRIP = box(23.15, 42.14, 36.50, 45.69).difference(
    unary_union([_W3_KO, Point(24.3 + DIV_W3_SHIFT, 45.4).buffer(1.25 + 0.5), box(24.3, 43.65, 24.3 + DIV_W3_SHIFT,
                                                                                   47.15),
                 box(23.15, 42.14, 25.464 + DIV_W3_SHIFT - 0.03, 45.69)]))
J101_REG = box(37.0, 42.13, 44.5, 51.53)
IN_STRIP = box(36.1, 52.03, 44.55, 61.55)
OUT_STRIP = box(30.8, 62.85, 39.3, 66.64)
# U101 network regions (D-55, review B-1). Until D-55 no region owned the A.8 +x pocket: INTERIOR subtracted it, so
# region_name() returned int_logic and the packer put R101, C101, R103, R104, R105, R129 and R106s across the CHG pin
# column, up to 23 mm from their U101 pins. A.8 keeps the ILIM, dVdT, OVP and IMON nodes within 5 mm of U101 pins
# 7-13 and R106s as near to pin 14 as the courtyard check allows. The A.8 upper bound y 66.64 was the r6 +y edge;
# the plug-on outline (+y edge y 94, D-09 re-derive note) makes the larger pocket below reachable.
# - POCKET: east of the U101 courtyard and above the J1 pad-10 annulus. The bottom y 63.40 keeps every courtyard
#   >= 0.5 mm from pad 10 (pad top y 62.894). Review start value x 44.40-50.50, y 63.40-69.00; widened to x 51.40,
#   y 70.00 (nothing else is placed there). The 5 mm A.8 radius about pins 7-13 (x 43.66) reaches only x ~47.9 at
#   the pocket height, so the near column x 44.40-47.90 holds four 0603 rows (rot 0, 1.60 mm pitch with the packer
#   channel): R104 and R103 (OVP; pin 7), R129 (IMON; pin 13) and R106s (FLT; pin 14), each with pad 1 (the U101
#   node) at -x and pad 2 at +x. C129 (the CHG_IIN filter capacitor) sits east of the column, in the D-20 window,
#   beside R129 pad 2: the CHG_IIN and CHG_EFUSE_FLT lines then leave for J102 east of the CHG pin column.
# - NORTH: the strip over the U101 +y edge (pins 13-18), clear of the VCHGOUT L1 pour (x <= 41.15, y <= 66.64), for
#   R101 (ILIM; pin 10), C101 (dVdT; pin 9) and R105 (IMON to GND), standing (rot 90, pad 1 at -y toward U101).
# Superseded (first D-55 build): R129 and R106s in an east sub-pocket at x >= 46.40 and R101/C101 in the pocket; the
# packer then left R103/R104 or R129 unplaced, or put them more than 5 mm from their pins.
POCKET = box(44.40, 63.40, 51.40, 70.00)
NORTH = box(39.20, 66.90, 44.40, 70.60)
U101_CRT = box(41.70 - 2.59, 63.65 - 2.59, 41.70 + 2.59, 63.65 + 2.59)
W_PADS = unary_union([Point(30.3, 61.2).buffer(1.15 + 0.5), Point(27.2, 61.2).buffer(1.15 + 0.5),
                      Point(24.3, 45.4).buffer(1.25 + 0.5), Point(24.3, 55.6).buffer(1.25 + 0.5)])
HDR_PADS = unary_union([box(45.998 - 1.2, 39.084 - 1.2, 45.998 + 1.2, 61.944 + 1.2),
                        box(20.998 - 1.2, 36.544 - 1.2, 20.998 + 1.2, 64.484 + 1.2)])

# fixed power vias of route_cr (VCHGIN C102b/C102c clusters, VCHGOUT under the D103 cathode): no part (D-33)
# D-55 (review M-2): the two C102b-end vias at (40.35 / 40.95, 51.62) overlapped the C102b pad-1 copper after the
# D-09 shift; they are re-sited off the pad and its mask opening, and a sixth C102b-end via is added (A.8 IN strip
# row, "6 vias each end"). The list is the same as route_cr.PRE_VIAS.
# D-56 (review r9b N-1, N-3; R9.H25): a third C102c-end VCHGIN via (39.75, 59.65) and the /GND pre-via under C103
# pad 2 (38.08, 62.90) are added, as in route_cr.PRE_VIAS.
PRE_VIA_SITES = [(39.45, 51.80), (39.45, 52.60), (39.45, 53.40), (39.45, 54.20), (39.45, 55.00), (40.65, 51.40),
                 (39.75, 59.65), (39.75, 60.35), (39.75, 61.05), (34.00, 63.35), (34.80, 63.35), (35.60, 63.35),
                 (36.40, 63.35), (38.08, 62.90), (42.30, 59.30)]   # D-57: C102c GND pre-via (inside IN_STRIP)
PRE_VIA_KO = unary_union([Point(c).buffer(0.30 + 0.25) for c in PRE_VIA_SITES])
# VCHGOUT L1 corridor from W1 to the D103 cathode below the D103 anode (D-22): no top part
VOUT_BELT = box(29.00, 59.00, 37.30, 64.20)
INTERIOR = (INSET.difference(J101_REG.buffer(0.5, join_style=2))
            .difference(IN_STRIP.buffer(0.5, join_style=2)).difference(OUT_STRIP.buffer(0.5, join_style=2))
            .difference(U101_CRT.buffer(0.5, join_style=2)).difference(POCKET.buffer(0.5, join_style=2))
            .difference(NORTH.buffer(0.5, join_style=2))
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
# U101 network (D-55, review B-1): the part, the U101 pin its node serves (A.8) and its region. The phase "U101
# network" packs these parts straight after J-TAP, each toward its slot target (the courtyard centre of its row or
# column, MB frame); C129 joins the phase (D-55, D-54 item 7).
U101_NET = {"R101": "10", "C101": "9", "R103": "7", "R104": "7", "R129": "13", "R106s": "14", "R105": "13",
            "C129": None}
U101_NET_REGION = {"R101": "north", "C101": "north", "R105": "north", "R103": "pocket", "R104": "pocket",
                   "R129": "pocket", "R106s": "pocket", "C129": "pocket_win"}
U101_NET_ROT = {"R104": (0,), "R103": (0,), "R129": (0,), "R106s": (0,), "C129": (0,),
                "R101": (90,), "C101": (90,), "R105": (90,)}
# D-56 (review r9b N-4): the R101/C101 slots and the R103/R104 rows are exchanged, so the slot order follows the U101
# pin order (pin 9 N_DVDT before pin 10 N_ILIM; the N_UV row below the N_OV row). This removes the N_DVDT/N_ILIM and
# N_UV/N_OV F.Cu crossings. Row 1 is outside the D-20 window and row 2 inside, so R104 now passes and R103 is the
# listed exemption. R129 and R106s stay (the N_IMON/N_FLT pair is a route-race item). Superseded (D-55): R104 (45.95, 64.20), R103 (45.95, 65.80), R101 (43.60, 68.45), C101 (42.00,
# 68.45).
U101_NET_TARGET = {"R103": (45.95, 64.20), "R104": (45.95, 65.80), "R129": (45.95, 67.40), "R106s": (45.95, 69.00),
                   "C129": (49.05, 65.80), "C101": (43.60, 68.45), "R101": (42.00, 68.45), "R105": (40.40, 68.45)}
# J101 east-channel parts (D-55, review m-4): R177 (J101 pin 2 to the CR 3V3) and R107 (STAT pull-up, J101 pin 4)
# sat east of the CHG column, so J3V3_2 and 3V3 crossed it. They are packed west of the column, under J101, so their
# tracks reach J101 pins 2 and 4 through the channel between J101 and the column. Region: the interior west of the
# column (x <= 44.90) and below the J101 region (y <= 41.63).
J101_EAST = {"R177": "2", "R107": "4"}
J101_EAST_REG = INTERIOR.intersection(box(40.90, G.Y0, 44.90, 41.63))


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
                   }   # R129 and C129 moved to the U101 network (U101_NET, D-55)
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
# B: the CHG_IIN filter joins J102 pad 2 to U101 pin 13 (N_IMON). Superseded by D-55: "In B, R129 may use the whole
# D-20 window (int_analog_wide), so it sits east of the J1 +x column on the J102-U101 path instead of in the
# comparator pocket, and C129 (CHG_IIN to GND) sits at J102 pad 2". Both are U101-network parts now (U101_NET).
B_WIDE_PASSIVES = set()
B_TAP_PASSIVES = set()
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
        "pocket": POCKET,
        "pocket_win": POCKET.intersection(G.analog_window()),
        "north": NORTH,
        "j101_east": J101_EAST_REG,
    })
    named = set(FIXED) | set(ANALOG_ICS) | set(LOGIC_ICS) | set(DIVIDERS) | set(DECOUPLE) | ANALOG_PASSIVES \
        | set(LEADS) | {"J102"} | set(U101_NET) | set(J101_EAST)
    # D-55 (review B-1): the U101 network is packed in its own phase straight after J-TAP, in both variants.
    u101_phase = ("U101 network", "F", [r for r in U101_NET if r in fps])
    j101_east_phase = ("J101 east-channel parts", "F", [r for r in J101_EAST if r in fps])
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
                  u101_phase,
                  ("dividers", "F", [r for r in DIVIDERS if r in fps]),
                  ("comparators", "F", [r for r in B_COMPARATORS if r in fps], "int_analog_wide"),
                  ("comparator decouplers", "F", [r for r in B_COMP_DECOUPLE if r in fps]),
                  ("clamps", "F", [r for r in B_CLAMPS if r in fps], "int_analog_wide"),
                  ("J101 series", "F", [r for r in B_J101_SERIES if r in fps], "int_logic"),
                  j101_east_phase,
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
              u101_phase,
              ("analog ICs", "F", [r for r in ANALOG_ICS if r in fps], "int_analog_wide"),
              ("dividers", "F", [r for r in DIVIDERS if r in fps]),
              ("logic ICs", "F", [r for r in LOGIC_ICS if r in fps]),
              ("decouplers", "F", [r for r in DECOUPLE if r in fps]),
              j101_east_phase,
              ("analog passives", "F", sorted(r for r in ANALOG_PASSIVES if r in fps), "int_analog_wide"),
              ("lead pads", "F", [r for r in LEADS if r in fps]),
              ("other parts", "F", rest)]


def region_name(ref):
    if ref in U101_NET_REGION:      # D-55: the U101 network regions, both variants
        return U101_NET_REGION[ref]
    if ref in J101_EAST:            # D-55: west of the CHG column, under J101
        return "j101_east"
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


def _pad_pos(fps, fr, ref, num):
    for p in fps[ref].Pads():
        if p.GetNumber() == num:
            return fr.e(p.GetPosition())
    return None


def target(ref, fps, fr, pinnet):
    if ref in U101_NET_TARGET:      # D-55: the slot of the part (A.8 <= 5 mm to its U101 pin)
        return U101_NET_TARGET[ref]
    if ref in J101_EAST:            # D-55: the J101 pin the part serves
        return _pad_pos(fps, fr, "J101", J101_EAST[ref])
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
    if ref in U101_NET_ROT:
        return U101_NET_ROT[ref]
    if VARIANT == "B" and ref in B_ROT:
        return B_ROT[ref]
    if ref[0] in "RC":
        return (0, 90)
    if ref.startswith("D1") and ref not in ("D104", "D105", "D106"):
        return (0, 90)
    return (0, 90, 180, 270)
