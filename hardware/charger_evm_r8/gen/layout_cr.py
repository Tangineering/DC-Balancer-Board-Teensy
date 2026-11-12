"""CR placement data. Every coordinate is an Eagle board coordinate (A.2 convention) taken from
docs/charger_bq25798_wiring_design_2026-11-05.md r8 A.7 / A.8 / B.8; deviations carry a D-nn tag that
LAYOUT_DECISIONS.md explains."""
import contextlib
import io
import math
import os
import sys

import pcbnew
from shapely.geometry import Polygon, box, Point, LineString
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
CALC = os.path.normpath(os.path.join(HERE, "..", "..", "..", "docs", "reviews", "charger_eval_2026-11-05", "round4",
                                     "calc"))

YOFF = 100.0
LAYERS = 4

# A.7 r7 outline V1..V11 (counter-clockwise from the -x/-y corner)
OUTLINE = [(17.70, 34.14), (48.70, 34.14), (48.70, 56.30), (65.00, 56.30), (65.00, 68.30), (48.70, 68.30),
           (48.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]
P = Polygon(OUTLINE)
INSET = P.buffer(-0.5, join_style=2)          # A.8: every courtyard >= 0.5 mm inside the outline

# ------------------------------------------------------------------ fixed placements (x, y, rot)
FIXED = {
    "J1": (45.998, 39.084, 0),                 # CHG element pin 1 (A.8 table)
    "W1": (30.3, 61.2, 0), "W2": (27.7, 61.2, 0), "W3": (24.3, 45.4, 0), "W4": (24.3, 55.6, 0),
    "W7": (29.0, 57.5, 0), "W6": (34.0, 57.5, 0),  # pads at 27/29/31 and 33/35 (A.8)
    # tab X tap grid (A.8 r7 assignment)
    "F01": (50.80, 58.94, 0), "F02": (53.34, 58.94, 0), "F13": (55.88, 58.94, 0), "F06": (58.42, 58.94, 0),
    "F14": (60.96, 58.94, 0), "F04": (63.50, 58.94, 0),
    "F05": (55.88, 61.48, 0), "F17": (58.42, 61.48, 0), "F19": (60.96, 61.48, 0), "F23": (63.50, 61.48, 0),
    "F07": (53.34, 64.02, 0), "F12": (55.88, 64.02, 0), "F15": (58.42, 64.02, 0), "F18": (60.96, 64.02, 0),
    "F11": (63.50, 64.02, 0),
    "F03": (50.80, 66.56, 0), "F24": (55.88, 66.56, 0), "F16": (58.42, 66.56, 0), "F21": (60.96, 66.56, 0),
    "F20": (63.50, 66.56, 0),
    # footprint low row y 35.80
    "F08": (26.44, 35.80, 0), "F09": (28.98, 35.80, 0), "F10": (31.52, 35.80, 0), "F22": (41.68, 35.80, 0),
    "R175": (50.80, 62.75, 0),                 # 1206 vertical between R175b (61.48) and R175a (64.02)
    # eFuse cluster (A.8 per-region table; D-09 shifts of <= 0.80 mm: KiCad courtyards and the U101 +y escape channel)
    "U101": (41.70, 63.65, 0),
    "C102c": (41.80, 60.27, 0),
    "C102a": (40.95, 57.14, 0),
    "R102": (43.55, 57.76, 0),
    "C102b": (42.125, 53.14, 0),
    "D107": (37.90, 56.30, 0),
    "C103": (38.08, 64.88, 0),
    "D103": (33.50, 64.84, 0),
    # D-09: R101 in line with U101 pin 10 (y 63.90), C101 reached along y 63.40 from pin 9, R105 below the
    # +y-edge IMON escape; C105 removed (DNP tier 1, D-31)
    "R101": (45.275, 63.90, 0), "C101": (47.225, 63.90, 0),
    "R105": (45.275, 65.06, 0), "R103": (47.225, 65.06, 0),   # R103 takes the freed C105 slot (D-09, D-31)
    "J101": (40.60, 46.83, 0),
    # comparators (footprint low-y band; D-05)
    "U115": (25.165, 40.10, 0), "U119": (29.195, 40.10, 0), "U103": (33.225, 40.10, 0),
    "U102": (37.255, 40.10, 0), "U104": (34.56, 36.60, 0),
    # D-05: U120 and U121 do not fit the band at x <= 39.53; they take the band positions that A.8 makes
    # conditional on the MS4b reading (T-A-08), TODO(verify: T-A-08 MS4b), fallback = footprint interior.
    "U120": (38.61, 36.60, 0), "U121": (41.315, 40.10, 0),
}
# polarity / orientation: (pad, direction of that pad from the part centre)
ORIENT = {
    "R175": ("1", "+y"),       # pad 1 (T6_3V3) = R175a at y 64.02
    "U101": ("3", "-y"),       # IN/IN_SYS edge (pins 1-6) facing -y (A.8, r4)
    "C102a": ("1", "+y"),      # VCHGIN pad at the top
    "R102": ("2", "+y"),       # N_UV pad at the top
    "D107": ("1", "+y"),       # cathode at the top
    "C103": ("1", "+y"),       # VCHGOUT pad at the top
    "D103": ("1", "+x"),       # cathode at the +x end
}

BOARD_ONLY = [
    ("FT2H", "FT2_FillHole_NPTH_1.0mm_KeepOut", 28.00, 73.250, 0, "F"),
    ("FT1M", "FT1_Foot_4.0x1.6mm_BottomMark", 61.72, 66.705, 0, "F"),
    ("FT2M", "FT2_Foot_4.0x4.0mm_BottomMark", 28.00, 73.250, 0, "F"),
]
PARK = (70.0, 50.0)

# ------------------------------------------------------------------ regions
FP_RECT = box(18.2, 34.64, 48.2, 66.64)
BAND = box(23.15, 35.05, 42.43, 41.63)
DIV_STRIP = box(23.15, 42.14, 36.50, 45.69).difference(Point(24.3, 45.4).buffer(1.25 + 0.5))
J101_REG = box(37.0, 42.13, 44.5, 51.53)
IN_STRIP = box(36.1, 52.03, 44.55, 61.55)
OUT_STRIP = box(30.8, 62.85, 39.3, 66.64)
POCKET = box(44.3, 63.40, 48.2, 66.64)
U101_CRT = box(41.70 - 2.59, 63.65 - 2.59, 41.70 + 2.59, 63.65 + 2.59)
W_PADS = unary_union([Point(30.3, 61.2).buffer(1.15 + 0.5), Point(27.7, 61.2).buffer(1.15 + 0.5),
                      Point(24.3, 45.4).buffer(1.25 + 0.5), Point(24.3, 55.6).buffer(1.25 + 0.5),
                      box(26.4 - 0.5, 56.75 - 0.5, 31.6 + 0.5, 58.25 + 0.5), box(32.4 - 0.5, 56.75 - 0.5,
                                                                                 35.6 + 0.5, 58.25 + 0.5)])
HDR_PADS = unary_union([box(45.998 - 1.2, 39.084 - 1.2, 45.998 + 1.2, 61.944 + 1.2),
                        box(20.998 - 1.2, 36.544 - 1.2, 20.998 + 1.2, 64.484 + 1.2)])
B1R = box(23.55, 62.54, 26.05, 67.10)             # r8 B1R wedge footprint (A.8, H.23(s))
SPOTS = unary_union([box(c[0] - 1.5, c[1] - 1.5, c[0] + 1.5, c[1] + 1.5) for c in
                     ((35.00, 47.69), (28.70, 53.42), (35.00, 70.80), (35.00, 73.10))])  # S1, S2, B3, S3
FT2_DISC = Point(28.00, 73.250).buffer(1.0)        # 2.0 mm keep-out disc (B.8 Mechanical)
TAB_X = box(48.70, 56.30, 65.00, 68.30)
TAB_Y = box(17.70, 67.14, 37.56, 76.00)
FT1_KO = box(59.220, 65.405, 64.220, 68.300)       # keep-out + RTV lane (A.8)
FT2_KO = box(25.500, 70.750, 30.500, 75.750)
L_FC_BOX = None  # tab Y "no comparator input / timing node within 10 mm of L-FC" holds by part class (D-06)

# fixed power vias of route_cr (VCHGIN C102b/C102c clusters, VCHGOUT under the D103 cathode): no part on either side
PRE_VIA_SITES = [(39.45, 52.60), (39.45, 53.40), (39.45, 54.20), (40.35, 51.62), (40.95, 51.62), (39.75, 60.35),
                 (39.75, 61.05), (34.00, 63.35), (34.80, 63.35), (35.60, 63.35), (36.40, 63.35)]
PRE_VIA_KO = unary_union([Point(c).buffer(0.30 + 0.25) for c in PRE_VIA_SITES])
# VCHGOUT L1 corridor from W1 to the D103 cathode below the D103 anode (D-22): no top part
VOUT_BELT = box(29.00, 59.00, 37.30, 64.20)
INTERIOR = (FP_RECT.difference(BAND.buffer(0.5, join_style=2)).difference(J101_REG.buffer(0.5, join_style=2))
            .difference(IN_STRIP.buffer(0.5, join_style=2)).difference(OUT_STRIP.buffer(0.5, join_style=2))
            .difference(U101_CRT.buffer(0.5, join_style=2)).difference(POCKET.buffer(0.5, join_style=2))
            .difference(W_PADS).difference(HDR_PADS).difference(DIV_STRIP.buffer(0.01)).difference(B1R)
            .difference(SPOTS).difference(VOUT_BELT).difference(PRE_VIA_KO))
TABY_TOP = TAB_Y.intersection(INSET).difference(FT2_DISC).difference(SPOTS)


def mb_bottom_clearance():
    """Bottom clearance rule (A.7 r7): every CR bottom courtyard >= 1.0 mm in plan from every MB layer-1
    feature that is not GND, and from the MB part boxes under the CR. Geometry from round4/calc/r7_calc.py."""
    sys.path.insert(0, CALC)
    with contextlib.redirect_stdout(io.StringIO()):
        import r7_calc as rc  # noqa: E402
    geoms = []
    for s in rc.NONGND:
        if s["kind"] == "wire":
            g = LineString(s["pts"]).buffer(s["r"])
        elif s["kind"] == "poly":
            g = Polygon(s["pts"]).buffer(0).buffer(s["r"])
        elif s["kind"] == "via":
            g = Point(s["pts"][0]).buffer(s["r"])
        elif s["kind"] == "pad":
            c = s["pts"][0]
            g = box(c[0] - s["r"], c[1] - s["r"], c[0] + s["r"], c[1] + s["r"]) if s.get("square") \
                else Point(c).buffer(s["r"])
        else:
            continue
        if g.distance(P) < 1.5:
            geoms.append(g.buffer(1.0))
    for p in rc.PARTS:
        bx = box(*p["bbox"])
        if bx.distance(P) < 1.5:
            geoms.append(bx.buffer(1.0, join_style=2))
    return unary_union(geoms).intersection(P.buffer(0.2)).simplify(0.01)


_MBK = None


def mbk():
    global _MBK
    if _MBK is None:
        _MBK = mb_bottom_clearance()
    return _MBK


def rule_areas():
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    return [
        ("MB_bottom_clearance", mbk(), [B], dict(fps=True)),
        ("FT1_keepout", FT1_KO, [B], dict(fps=True)),
        ("FT2_keepout", FT2_KO, [B], dict(fps=True)),
        ("B1R_wedge", B1R, [F], dict(fps=True)),
        ("bead_spots", SPOTS, [F], dict(fps=True)),
    ]


# ------------------------------------------------------------------ packer regions and phases
GRID_BOUNDS = (17.0, 33.5, 66.0, 77.0)
RIM_X = 39.53                    # courtyard limit: >= 10 mm from the MB 5V copper rim x 49.53 (A.7 thermal band)
LFC_Y = 66.862                   # 10 mm below the L-FC body edge y 76.862 (H.23(b)/(l) ESTIMATE; A.8 tab Y rule)
BAND_W = box(22.20, 34.64, 25.40, 38.62)   # D-07: band corner left of F08, BAV199 clamps only
BAND_E = box(43.40, 34.64, 44.80, 41.63).union(box(42.80, 34.64, 48.20, 37.85))  # D-07: below the pin-1 post, logic and DNP only
INT_ANY = INTERIOR
LOOP = unary_union([OUT_STRIP, U101_CRT, IN_STRIP, POCKET])   # U101 commutation-loop region (A.8, H.23(f))
INT_ANALOG = INTERIOR.intersection(box(0, 0, RIM_X, 100)).difference(LOOP.buffer(3.0)).union(BAND_W)

INTERIOR_ICS = ["U108", "U109", "U122", "U123", "D108", "D104", "D105", "D106", "U111", "U113"]
TABY_ICS = ["U114", "U110", "U106", "U116", "U118", "U105", "U107"]   # the A.8 tab Y set; U108/U109 interior
ANALOG_ICS = {"D104", "D105", "D106", "D108", "U123"}
TIMING_ICS = {"U111", "U113"}
DIVIDERS = ["R109", "R111", "R114", "R110", "R112", "R115"]
DECOUPLE = {"C110": "U102", "C111": "U103", "C112": "U104", "C113": "U115", "C114": "U105", "C115": "U106",
            "C116": "U107", "C117": "U108", "C118": "U109", "C119": "U110", "C120": "U111", "C121": "U113",
            "C122": "U114", "C123": "U116", "C126": "U118", "C131": "U119", "C132": "U120", "C133": "U121",
            "C134": "U122", "C135": "U123"}
# R103/R104 take the A.8 +x pocket fallback: on the bottom at y >= 63.71, x 44.3-48.2 (D-09)
POCKET_BOT = {"R104"}
TABX_OK = {"R106s", "R121", "R122", "R147", "R135", "R125", "R126", "R127", "R128", "R148", "R130", "R131A",
           "R131B", "R132", "R176", "R177", "R108", "R123", "R124", "R136", "R133", "R107"}
# comparator input, reference, hysteresis, filter and timing passives: not on tab X bottom (A.7 thermal band
# content rule) and not within 10 mm of the L-FC body (A.8 tab Y rule)
ANALOG_BOT = {"C106", "C107", "C108", "C140", "C109", "C127", "C130", "R113", "R116", "R119", "R117", "R118",
              "R120", "R140", "R141", "R142", "R143", "R144", "R160", "R161", "R162", "R163", "R178", "R179",
              "R184", "R185", "R186", "R187", "R188", "R189", "R190", "R191", "C150", "C151", "R150", "R151",
              "R129", "C129", "R105"}
# logic resistors driven by or feeding the tab Y gates (A.8 tab Y bottom content), packed there first
TABY_BOT = {"R130", "R131A", "R131B", "R132", "R124", "R108", "R137", "R176", "R177", "R136", "R123", "R145",
            "R146"}
POWER_NETS = {"/GND", "/3V3", "/VCHGIN", "/VCHGOUT", "/VCHG"}
REGIONS = {}
PHASES = []
TRIES = 150
PACK_MARGIN = 0.08   # routing channel kept around every courtyard (D-15)
# tab Y gates: 0.15 mm so every gate pin has an escape (a 0.08 mm pack sealed U108/U109 inputs, D-15)
PHASE_MARGIN = {}
PLACED = set()
PARK = (70.0, 50.0)

# Routing-study placement variants (round 1, D-34). CR_PLACE_VARIANT unset = the base placement of 5ddc21a.
#   A: the VCHGOUT L4 strap (route_cr.VOUT_IN, D-22 shape unchanged) plus 0.15 mm is a bottom keep-out, so no
#      bottom pad sits inside the strap outline (R147.2 /QUAL was enclosed on three sides; CR1-03).
#   B: A plus the B.Cu tap/divider grid packed at a row pitch of 1.75 mm (each courtyard grown by 0.225 mm):
#      0.80 mm row gaps between 0603 pads and >= 0.9 mm from the R107/R122/R128 column to R129/C129 (CR1-03).
VARIANT = os.environ.get("CR_PLACE_VARIANT", "").upper()
VOUT_L4_KO = unary_union([box(29.10, 60.00, 31.50, 62.40), box(29.10, 62.30, 36.90, 64.10)]).buffer(
    0.15, join_style=2)                        # = route_cr.VOUT_IN (kept equal by check_constraints)
GRID_REPACK = ("C129", "R107", "R122", "R126", "R128", "R129", "R147", "R190", "R191")
CRT_GROW = {r: 0.225 for r in GRID_REPACK} if VARIANT == "B" else {}


def setup(fps):
    global PHASES
    bot = INSET.difference(mbk()).difference(FT1_KO).difference(FT2_KO).difference(PRE_VIA_KO).difference(
        unary_union([Point(30.3, 61.2).buffer(1.15 + 0.5), Point(27.7, 61.2).buffer(1.15 + 0.5),
                     Point(24.3, 45.4).buffer(1.25 + 0.5), Point(24.3, 55.6).buffer(1.25 + 0.5)]))
    if VARIANT != "BASE0":   # D-34: strap keep-out adopted as the default (round 2); BASE0 = the 5ddc21a placement
        bot = bot.difference(VOUT_L4_KO)
    REGIONS.update({
        "taby_logic": TABY_TOP.union(INT_ANY).union(BAND_E),
        "taby_only": TABY_TOP,
        "int_logic": INT_ANY.union(BAND_E),
        "int_analog": INT_ANALOG,
        "div": DIV_STRIP,
        "bot_logic": bot,
        "bot_core": bot.difference(TAB_X),
        "bot_analog": bot.difference(TAB_X).difference(box(0, LFC_Y, 100, 100)),
        "taby_bot": bot.intersection(TAB_Y),
        "pocket_bot": bot.intersection(box(44.3, 63.71, 48.2, 66.64)),
        # A.8 +x pocket row: ILIM/dVdT/OVP/IMON nodes <= 5 mm from pins 7-13 (pin 7 at (43.66, 62.40))
        # D-32: the 5 mm A.8 rule has no free bottom spot after the power-via keep-outs; 6 mm admitted
        "bot_near_u101": bot.difference(TAB_X).intersection(Point(43.66, 62.40).buffer(6.0)),
    })
    top_ics = INTERIOR_ICS + TABY_ICS
    bottom = [r for r, fp in fps.items() if fp.IsFlipped() and r not in FIXED]
    first = [r for r in bottom if r in DECOUPLE or r in ("C125", "R106s")]
    rest = [r for r in bottom if r not in first]
    others_top = [r for r, fp in fps.items() if not fp.IsFlipped() and r not in FIXED and r not in top_ics
                  + DIVIDERS and not r.startswith(("FT", "#"))]
    tyb = [r for r in rest if r in TABY_BOT]
    rest = [r for r in rest if r not in TABY_BOT]
    first = [r for r in first if r not in POCKET_BOT]
    rest = [r for r in rest if r not in POCKET_BOT]
    PHASES = [("tab Y gates", "F", TABY_ICS, "int_logic", "taby_only"),
              ("pocket bottom", "B", sorted(POCKET_BOT), "bot_near_u101"),
              ("top ICs", "F", INTERIOR_ICS + others_top), ("dividers", "F", DIVIDERS),
              ("bottom decouplers", "B", first), ("bottom analog", "B", [r for r in rest if r in ANALOG_BOT]),
              ("tab Y bottom logic", "B", tyb, "bot_logic", "taby_bot"),
              ("bottom passives", "B", [r for r in rest if r not in ANALOG_BOT])]


def region_name(ref):
    if ref in POCKET_BOT:
        return "pocket_bot"
    if ref in DIVIDERS:
        return "div"
    if ref in ANALOG_ICS:
        return "int_analog"
    if ref in TABY_ICS:
        return "taby_logic"
    if ref in INTERIOR_ICS or ref in TIMING_ICS:
        return "int_logic"
    if ref in ANALOG_BOT:
        return "bot_analog"
    if ref in TABX_OK:
        return "bot_logic"
    if ref in DECOUPLE or ref == "C125":
        return "bot_core"
    if _FPS is not None and not _FPS[ref].IsFlipped():
        return "int_logic"
    return "bot_core"


def fill(ref, phase):
    """True: pack bottom-left first (dense) instead of nearest to the connection centroid."""
    return phase.startswith(("tab Y gates", "tab Y bottom logic"))


def prio(ref):
    if ref in DECOUPLE:
        return 2
    if ref in ANALOG_ICS or ref in TIMING_ICS:
        return 1
    return 0


_FPS = None


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
    global _FPS
    _FPS = fps
    fp = fps[ref]
    if ref in DECOUPLE:
        ic = fps[DECOUPLE[ref]]
        if DECOUPLE[ref] in FIXED or DECOUPLE[ref] in PLACED:
            fid = ic.GetFPID().GetLibItemName().wx_str()
            pin = "8" if "DCT" in fid else ("5" if ("SC-70" in fid or "DCK" in fid) else "6")
            for p in ic.Pads():
                if p.GetNumber() == pin:
                    return fr.e(p.GetPosition())
    if ref == "C125":
        return (50.8, 61.0)
    if ref == "R106s":
        return (58.42, 61.48)            # tab X bottom beside F17 (A.8 r8 R106s placement)
    if ref in TABY_ICS:
        return (27.0, 71.0)              # fill tab Y first (A.8 tab Y top content)
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
    if ref.startswith("D1") and ref not in ("D104", "D105", "D106", "D108"):
        return (0, 90)
    return (0, 90, 180, 270)
