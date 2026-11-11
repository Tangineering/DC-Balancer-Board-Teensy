"""CR routing data (Eagle frame). Every pour cites the A.8 row it implements; LAYOUT_DECISIONS.md D-09..D-12."""
from shapely.geometry import box, Point, Polygon
from shapely.ops import unary_union

import layout_cr as L

YOFF = 100.0
TRACK = 0.16
CLEAR = 0.16
VIA = (0.56, 0.26)     # 0.254 mm minimum hole + 2 x 0.15 mm ring (tools/pcb fab rules)
PASSES = 30
SILK_REFS = {"J1", "J101"}
P = L.P

# --- pre-routing copper ------------------------------------------------------------------------------------
# VCHGIN L3 strap (A.8 IN strip row: C102b VCHGIN pad joins the pad-10 / C102c pour on L3, 2.5 mm wide, <= 8 mm,
# vias at each end) and the pad-10 -> U101 L3 parallel path (D-09).
VIN_L3 = unary_union([box(39.15, 51.25, 41.95, 61.45), box(39.15, 60.15, 47.10, 62.75)])
# VCHGOUT L3 / L4 straps from the D103 cathode via cluster to W1 (A.8 OUT strip row; D-10: the L1 corridor between
# D103 and W1 is 1.5 mm, so L3 and L4 carry the W1 leg in parallel).
VOUT_IN = unary_union([box(29.10, 60.00, 31.50, 62.40), box(29.10, 62.30, 36.90, 64.10)])

PRE_VIAS = (
    # VCHGIN: C102b end (left of and below the pad) and the C102c end
    [(39.45, 52.60, "/VCHGIN"), (39.45, 53.40, "/VCHGIN"), (39.45, 54.20, "/VCHGIN"),
     (40.35, 51.62, "/VCHGIN"), (40.95, 51.62, "/VCHGIN"),
     (39.75, 60.35, "/VCHGIN"), (39.75, 61.05, "/VCHGIN")]
    # VCHGOUT: below the D103 cathode
    + [(34.00, 63.35, "/VCHGOUT"), (34.80, 63.35, "/VCHGOUT"), (35.60, 63.35, "/VCHGOUT"),
       (36.40, 63.35, "/VCHGOUT")]
)
PRE_TRACKS = (
    [([(x, 63.35), (x, 64.30)], "/VCHGOUT", 0.5, "F") for x in (34.00, 34.80, 35.60, 36.40)]
    + [([(39.45, 52.60), (39.45, 54.20)], "/VCHGIN", 0.5, "F"), ([(39.45, 53.54), (40.65, 53.54)], "/VCHGIN", 0.6, "F"),
       ([(40.35, 51.62), (40.95, 51.62)], "/VCHGIN", 0.5, "F"), ([(40.65, 51.62), (40.65, 52.50)], "/VCHGIN", 0.5, "F"),
       ([(39.75, 60.35), (39.75, 61.05)], "/VCHGIN", 0.5, "F"), ([(39.75, 60.67), (41.025, 60.67)], "/VCHGIN", 0.5, "F")]
)


def power_zones():
    return [
        ("GND_L2_plane", P.buffer(-0.45, join_style=2), "In1", "/GND", 0),   # A.8 stack-up: L2 solid GND
        ("VCHGIN_L3_strap", VIN_L3, "In2", "/VCHGIN", 3),
        ("VCHGOUT_L3_strap", VOUT_IN, "In2", "/VCHGOUT", 3),
        ("VCHGOUT_L4_strap", VOUT_IN, "B", "/VCHGOUT", 3),
    ]


# --- post-routing pours ------------------------------------------------------------------------------------
VIN_L1 = unary_union([box(36.95, 57.20, 42.35, 61.50), box(40.15, 61.50, 42.65, 62.55),
                      box(42.35, 60.60, 47.05, 61.55), box(44.85, 60.60, 47.05, 62.95),
                      box(42.35, 56.55, 44.45, 57.95)])
VOUT_L1 = unary_union([box(33.30, 62.70, 41.15, 66.64), box(29.10, 60.00, 31.50, 62.40)])
VCHG_L1 = box(19.90, 43.10, 25.65, 47.20)
GND_L1_STAR = unary_union([box(19.90, 53.60, 25.70, 57.90), box(26.20, 59.70, 29.20, 62.70)])


def gnd_pours():
    inset = P.buffer(-0.45, join_style=2)
    return [
        ("VCHGIN_L1", VIN_L1, "F", "/VCHGIN", 3),
        ("VCHGOUT_L1", VOUT_L1, "F", "/VCHGOUT", 3),
        ("VCHG_L1", VCHG_L1, "F", "/VCHG", 3),
        ("GND_L1_star", GND_L1_STAR, "F", "/GND", 2),
        ("GND_L1_fill", inset, "F", "/GND", 1),
        ("GND_L4_pour", inset, "B", "/GND", 1),     # A.8 stack-up: L4 GND pour, stitched <= 5 mm
    ]


def stitching():
    keep = unary_union([L.FT2_DISC.buffer(0.6), L.FT1_KO.buffer(0.0, join_style=2)]).union(
        unary_union([Point(x, y).buffer(1.0) for x, y in [(28.0, 73.25)]]))
    return [("/GND", 2.5, P.buffer(-0.9, join_style=2), keep)]
