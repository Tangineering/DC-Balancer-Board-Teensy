"""EIB placement data. Frame: EIB board coordinates, mm, top view, origin at the lower-left corner, +y up,
long edges vertical (the EVM lies to the -x side). A.9 / B.6 / B.8 r8; deviations D-13..D-15 in
LAYOUT_DECISIONS.md."""
import pcbnew
from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union

YOFF = 50.0
LAYERS = 2
W, H = 24.0, 38.0                    # D-13: A.9 gives 36.0 x 24.0 mm; 38 mm is the minimum long edge (see log)
OUTLINE = [(0, 0), (W, 0), (W, H), (0, H)]
P = Polygon(OUTLINE)
INSET = P.buffer(-0.5, join_style=2)
HOLES = [(3.5, 3.5), (W - 3.5, H - 3.5)]          # A.9: diagonally opposite corners, 3.5 mm in from both edges
HOLE_KO = unary_union([Point(c).buffer(3.5) for c in HOLES])   # A.9: 7 mm copper-free keep-out each

# A.9 E-pad row, 2.54 mm pitch, top to bottom: E8, -, E3, E4, E2, -, E7, -, E1, -, E5, E6
EX = 2.0
ROW = ["E8", None, "E3", "E4", "E2", None, "E7", None, "E1", None, "E5", "E6"]
ETOP = 36.04
EPOS = {r: (EX, round(ETOP - i * 2.54, 3)) for i, r in enumerate(ROW) if r}

FIXED = {r: (x, y, 0) for r, (x, y) in EPOS.items()}
FIXED.update({
    "J201": (20.00, 19.00, 0),        # opposite long edge (A.9); pin 1 at the top
    "R276": (6.00, EPOS["E1"][1], 0),  # at the E1 pad (A.9 REGN parts, H.23(k)); 3.2 mm centre to centre
    "R275": (6.00, EPOS["E7"][1], 0),  # at the E7 pad end (A.9 E1-E8 pads row)
})
ORIENT = {"R276": ("1", "-x"), "R275": ("1", "-x")}   # pad 1 (REGN_E1 / STAT_E) toward the E pad
BOARD_ONLY = [("H1", "MountingHole_3.2mm_M3_KeepOut7mm", HOLES[0][0], HOLES[0][1], 0, "F"),
              ("H2", "MountingHole_3.2mm_M3_KeepOut7mm", HOLES[1][0], HOLES[1][1], 0, "F")]
PARK = (40.0, 20.0)
# E-pad labels (A.9: identify every E point by net before soldering, T-A-02) and the board marking
TEXTS = [(r, EX + 2.1, EPOS[r][1], pcbnew.B_SilkS, 0.8) for r in EPOS] + [
    ("EIB r8", 12.0, 2.2, pcbnew.F_SilkS, 1.0), ("2026-11-11", 12.0, 0.95, pcbnew.F_SilkS, 0.8)]


def rule_areas():
    return []  # the copper keep-out lives in the hole footprint; the packer region keeps parts out


GRID_BOUNDS = (-1.0, -1.0, W + 1.0, H + 1.0)
REGIONS = {}
PHASES = []
TRIES = 120
PACK_MARGIN = 0.35   # D-14: 0.7 mm routing channel between courtyards (the EIB has area to spare)
PLACED = set()
ANALOG = {"U203", "U204", "R258", "R259", "R260", "R261", "C203", "R262", "R263", "C204"}
REGN_PARTS = {"Q201", "Q202", "Q203", "R252", "R254", "R255", "R257", "R271", "C205"}
_FPS = None


def setup(fps):
    global PHASES
    REGIONS["all"] = INSET.difference(HOLE_KO).difference(box(-1, -1, EX + 1.6, H + 1))
    ics = ["U203", "U204", "U201", "U202", "Q201", "Q202", "Q203"]
    rest = [r for r in fps if r not in FIXED and r not in ics and not r.startswith(("H", "#"))]
    PHASES = [("ICs", "F", ics), ("passives", "F", rest)]


def region_name(ref):
    return "all"


def fill(ref, phase):
    return False


def prio(ref):
    return 2 if ref in ("U203", "U204") else (1 if ref in REGN_PARTS else 0)


def target(ref, fps, fr, pinnet):
    # signal flow (B.6): J201 -> input dividers -> U201/U202 (mid-board) -> Q201-Q203 gates (E pad side);
    # the sense comparators sit at their E pads (A.9 Analog row)
    special = {"U203": (7.5, EPOS["E4"][1] - 1.0), "U204": (7.5, EPOS["E6"][1] + 1.5),
               "Q201": (7.0, EPOS["E3"][1] + 0.5), "Q202": (10.5, EPOS["E3"][1] + 0.5),
               "Q203": (7.0, EPOS["E2"][1] - 1.5), "U201": (13.0, 19.0), "U202": (13.5, 27.0)}
    if ref in special:
        return special[ref]
    pts = []
    fp = fps[ref]
    for p in fp.Pads():
        n = p.GetNetname()
        if not n or n in ("/AGND", "/3V3"):
            continue
        for r, f in fps.items():
            if r == ref or not (r in FIXED or r in PLACED):
                continue
            for q in f.Pads():
                if q.GetNetname() == n:
                    pts.append(fr.e(q.GetPosition()))
    if not pts:
        return (12.0, 19.0)
    return (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))


def rotations(ref):
    return (0, 90) if ref[0] in "RC" else (0, 90, 180, 270)
