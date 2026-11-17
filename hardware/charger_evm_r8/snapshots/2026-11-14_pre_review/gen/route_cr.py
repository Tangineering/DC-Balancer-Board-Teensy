"""CR routing data (Eagle frame). Every pour cites the A.8 row it implements; LAYOUT_DECISIONS.md D-09..D-12."""
from shapely.geometry import box, Point, Polygon
from shapely.ops import unary_union

import layout_cr as L

YOFF = 100.0
# D-29 (amended 2026-11-12) and D-55 (review M-4): the board Default net class is 6/6 mil (0.1524 / 0.1524 mm);
# 0.127 mm stays the board and rule-file minimum, used at local necks only. Superseded: "TRACK = CLEAR = 0.127, 5/5 mil
# (operator ruling 2026-11-11; D-29)".
TRACK = 0.1524
CLEAR = 0.1524
VIA = (0.6, 0.3)       # TOOLCHAIN: 0.3 mm via drill (OSH Park drilled/finished hole TODO)
PASSES = 30
EDGE_BAND = 0.40   # >= the 0.381 mm fab copper-to-edge rule; opens the U101 +y escape channel (D-09)
class _AllRefs:
    """D-12a reversed (D-03 amended 2026-11-12): every reference designator stays on the top silkscreen."""
    def __contains__(self, ref):
        return True


SILK_REFS = _AllRefs()
P = L.P

# --- pre-routing copper ------------------------------------------------------------------------------------
# VCHGIN L3 strap (A.8 IN strip row: C102b VCHGIN pad joins the pad-10 / C102c pour on L3, 2.5 mm wide, <= 8 mm,
# vias at each end) and the pad-10 -> U101 L3 parallel path (D-09).
# D-56 (review r9b N-1, step 2; R9.H25): J1.10 is fed through this strap only, so the pad-10 band is widened toward -y.
# The narrowest section is at the U101 thermal-via column (x 42.80), where the via at (42.80, 62.55) cuts the top.
# Review value y 59.55 (2.596 mm neck); the IPC-2152 baseline check of R9.H25 at 2.41 A and a 10 degC rise asks for
# >= 3.22 mm, so the band starts at y 58.50 (neck about 3.6 mm). Superseded: box(39.15, 60.15, 47.10, 62.75) (D-21,
# D-55) and the review figure box(39.15, 59.55, 47.10, 62.75).
# D-57 (route-race r9 R9-01): the /GND pre-via (42.30, 59.30) of the C102c ground pad needs a strap cut-out, which
# alone leaves a 2.3-2.6 mm section at the trial via sites (below the 3.221 mm R9.H25 requirement). The box(41.95,
# 57.00, 44.00, 58.50) extension gives the current a second path below the cut-out; the board-measured minimum
# section is 4.174 mm at x 42.535 (LAYOUT_DECISIONS D-57). Superseded (D-56): the union without the extension box.
VIN_L3 = unary_union([box(39.15, 51.25, 41.95, 61.45), box(39.15, 58.50, 47.10, 62.75),
                      box(41.95, 57.00, 44.00, 58.50)])
# VCHGOUT inner strap from the D103 cathode via cluster to W1 (A.8 OUT strip row; D-22: the L1 corridor between
# D103 and W1 is 1.5 mm). D-20 (amended 2026-11-12): L4 carries no strap, so the r8 L4 strap moves to L3 (In2.Cu),
# where it does not meet the VCHGIN L3 strap (x >= 39.15). Interim until the D-22 re-derivation at placement (D-52).
VOUT_IN = unary_union([box(29.10, 60.00, 31.50, 62.40), box(29.10, 62.30, 36.90, 64.10)])

PRE_VIAS = (
    # VCHGIN: C102b end (left of and below the pad) and the C102c end. D-55 (review M-2): the vias at (40.35 / 40.95,
    # 51.62) overlapped the C102b pad-1 copper by 0.13 mm after the D-09 shift (D-37: no via on an SMD pad or in its
    # mask opening). They are replaced by (39.45, 51.80) on the x 39.45 column and (40.65, 51.40) below the pad; a
    # sixth C102b-end via at (39.45, 55.00) meets the A.8 IN-strip row ("6 vias each end"; D-21 had five). Every via
    # annulus clears the C102b pad plus its 0.0508 mm mask expansion (check_constraints D-37 row).
    [(39.45, 51.80, "/VCHGIN"), (39.45, 52.60, "/VCHGIN"), (39.45, 53.40, "/VCHGIN"), (39.45, 54.20, "/VCHGIN"),
     (39.45, 55.00, "/VCHGIN"), (40.65, 51.40, "/VCHGIN"),
     (39.75, 59.65, "/VCHGIN"), (39.75, 60.35, "/VCHGIN"), (39.75, 61.05, "/VCHGIN")]
    # D-56 (review r9b N-1; R9.H25): the C102c end is the L3-to-L1 transition of the whole J1.10 input current; a
    # third via at (39.75, 59.65) gives it >= 1.5x the 2.41 A basis (two vias: 1.1x, equal sharing assumed).
    # VCHGOUT: below the D103 cathode
    + [(34.00, 63.35, "/VCHGOUT"), (34.80, 63.35, "/VCHGOUT"), (35.60, 63.35, "/VCHGOUT"),
       (36.40, 63.35, "/VCHGOUT")]
    # D-56 (review r9b N-3): /GND pre-via in the VOUT_L1 notch below C103 pad 2, so the C103 ground pad reaches the
    # L2 plane (the island inside VCHGOUT_L1 had no plane-via site). In2 is free there (VOUT_IN x <= 36.90, VIN_L3
    # x >= 39.15). Review trial 4 used y 62.98; y 62.90 adds 0.08 mm to the annulus-to-pad margin.
    + [(38.08, 62.90, "/GND")]
    # D-57 (route-race r9 change request R9-01): /GND pre-via for the C102c ground pad. Every routed /N_UV path from
    # U101.6 to R102.2 cut the pad off the L1 fill, and the In2 strap left no plane-via site in the piece (probe_d56
    # 4.1). The via sits below the pad: annulus-to-pad gaps 0.195 mm to C102c.2, 0.239 mm to C102a.1 and 0.330 mm to
    # R102.2 (pcbnew pad shapes), outside every mask opening (D-37). The VIN_L3 extension restores the strap section.
    + [(42.30, 59.30, "/GND")]
)
PRE_TRACKS = (
    [([(x, 63.35), (x, 64.30)], "/VCHGOUT", 0.5, "F") for x in (34.00, 34.80, 35.60, 36.40)]
    + [([(39.45, 51.80), (39.45, 55.00)], "/VCHGIN", 0.5, "F"), ([(39.45, 53.19), (40.65, 53.19)], "/VCHGIN", 0.6, "F"),
       ([(40.65, 51.40), (40.65, 52.50)], "/VCHGIN", 0.5, "F"),
       ([(39.75, 59.65), (39.75, 61.05)], "/VCHGIN", 0.5, "F"), ([(39.75, 60.67), (41.025, 60.67)], "/VCHGIN", 0.5, "F")]
    # D-57: C102c.2 to its /GND pre-via
    + [([(42.575, 60.27), (42.30, 59.30)], "/GND", 0.4, "F")]
)


def power_zones():
    # Optional sixth field: thermal relief on THT pads (default True). D-56 (R9.H25): the VCHGIN strap joins the J1.10
    # barrel solid; four 0.6 mm thermal spokes (2.4 mm in all) would be narrower than the 3.22 mm IPC-2152 width.
    return [
        ("GND_L2_plane", P.buffer(-0.45, join_style=2), "In1", "/GND", 0),   # A.8 stack-up: L2 solid GND
        ("VCHGIN_L3_strap", VIN_L3, "In2", "/VCHGIN", 3, False),
        ("VCHGOUT_L3_strap", VOUT_IN, "In2", "/VCHGOUT", 3),   # D-20, D-22 (was B.Cu in r8)
    ]


# --- post-routing pours ------------------------------------------------------------------------------------
# D-55 (review M-3): the r9 step-5 pour reached J1 pad 10 only through the neck between the C102c GND pad (top y
# 60.745) and U101 pins 6/7, which is narrower than two 0.2 mm zone clearances plus the 0.2 mm minimum width, so the
# pad-10 spokes landed on an isolated island and pad 10 hung on the L3 strap alone. The pour now also covers the area
# east of C102c and above the R102 N_UV pad (x 42.35-44.85, y 57.95-62.10), which joins the R102 pad-1 piece through
# the corridor between R102 and the J1 +x column (x 44.45-44.85, 0.40 mm wide), and a ring around pad 10 (x 43.90-
# 48.20, y 60.55-63.60), free since D-55 moved R103/R104 into the pocket. The pad-10 spokes then land on the main
# pour. Superseded: "box(42.35, 60.60, 47.05, 61.55), box(44.85, 60.60, 47.05, 62.95)".
# D-56 (review r9b N-1, N-2): the D-55 extension sealed U101 pins 6, 7 and 9 and R102 pad 2 on F.Cu and enclosed the
# C102c GND pad. VIN_L1 returns to the D-54 main body with no copper at pad 10; box(42.35, 60.60, 43.10, 61.55) joins
# U101 pin 5 to the main pour. J1.10 is fed through VIN_L3 alone (R9.H25). Superseded (D-55, M-3): the boxes
# box(42.35, 57.95, 44.85, 62.10) and box(43.90, 60.55, 48.20, 63.60).
VIN_L1 = unary_union([box(36.95, 57.20, 42.35, 61.50), box(40.15, 61.50, 42.65, 62.55),
                      box(42.35, 60.60, 43.10, 61.55), box(42.35, 56.55, 44.45, 57.95)])
# D-56 (review r9b N-3): notch below C103 pad 2 for the /GND pre-via (38.08, 62.90); the L1 pour narrows from 3.94 mm
# to about 3.2 mm over 1.4 mm, with the VOUT_IN L3 strap in parallel (D-22).
VOUT_L1 = unary_union([box(33.30, 62.70, 41.15, 66.64), box(29.10, 60.00, 36.80, 63.80)]).difference(
    box(37.40, 62.60, 38.80, 63.40))   # D-22: W1 corridor
VCHG_L1 = box(19.90, 43.10, 25.65, 47.20)
# W2 piece moves -0.5 mm in x with W2 (D-55, review m-1); superseded: box(26.20, 59.70, 29.20, 62.70)
GND_L1_STAR = unary_union([box(19.90, 53.60, 25.70, 57.90), box(25.70, 59.70, 28.70, 62.70)])

# Route-race input (D-55, review m-8; data only, no generator script reads it): guide corridors for the divider-top
# nets T1_VMOT (J102 pad 7) and T2C (J102 pad 1). Their straight lines to the divider strip cross the gate ICs and the
# comparator row; the corridors take them south of J102 along the free -y band, then up the -x side below the J1
# pins 11-22 column, clear of the logic box (A.8 Analog: logic tracks >= 2 mm from the divider tops). The last leg
# into the divider strip is left to the router. MB frame, boxes.
GUIDE_CORRIDORS = {
    "/T1_VMOT": [box(19.60, 7.90, 56.00, 15.80), box(19.60, 7.90, 23.00, 34.90)],
    "/T2C": [box(19.60, 7.90, 56.00, 15.80), box(19.60, 7.90, 23.00, 34.90)],
}


def gnd_pours():
    inset = P.buffer(-0.45, join_style=2)
    return [
        ("VCHGIN_L1", VIN_L1, "F", "/VCHGIN", 3),
        ("VCHGOUT_L1", VOUT_L1, "F", "/VCHGOUT", 3),
        ("VCHG_L1", VCHG_L1, "F", "/VCHG", 3),
        ("GND_L1_star", GND_L1_STAR, "F", "/GND", 2),
        ("GND_L1_fill", inset, "F", "/GND", 1),
        ("GND_L4_pour", inset, "B", "/GND", 1),     # D-20: L4 solid GND facing the MB, stitched to L2 <= 5 mm
    ]


def stitching():
    # D-20: L2-L4 GND stitching at 2.5 mm grid (<= 5 mm pitch). The r7 FT1/FT2 and fill-hole keep-outs retire with
    # the feet (D-19, D-52); no mounting hole exists (D-42).
    keep = Point(-100.0, -100.0).buffer(0.1)   # empty keep-out placeholder outside the board
    return [("/GND", 2.5, P.buffer(-0.9, join_style=2), keep)]
