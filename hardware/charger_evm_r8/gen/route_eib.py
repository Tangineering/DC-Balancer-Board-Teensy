"""EIB routing data (EIB frame). A.9 Ground row: AGND pour on the bottom layer joined to E8 only; R273 between
the J201 GND pins (net GND_J) and that pour."""
from shapely.geometry import Point
from shapely.ops import unary_union

import layout_eib as L

YOFF = L.YOFF
TRACK = 0.2
CLEAR = 0.2
PASSES = 60
ROUNDS = 3
SILK_REFS = set()   # J201 keeps its pin-1 mark; E-pad labels are bottom-side board texts (layout_eib.TEXTS)
POWER_LAYERS = []
PRE_VIAS = []
PRE_TRACKS = []


P = L.P


def power_zones():
    return []


def gnd_pours():
    # A.9: AGND pour on the bottom layer, joined to E8; added after routing so the router completes AGND as
    # tracks (a plane present during routing is split by bottom crossings into islands the router cannot see)
    inset = L.P.buffer(-0.45, join_style=2).difference(L.HOLE_KO)
    return [("AGND_L2_pour", inset, "B", "/AGND", 1)]


def stitching():
    return []
