#!/usr/bin/env python3
"""Round 4 (r7) H.23 calculation for the BQ25798EVM wiring design: the CHG carrier (CR) on the r7 outline.

Section H.23 of the r7 design quotes every r7 number from the output of this script. Sections H.23(a)..(m) follow
round4/work/r7_design_basis.md section 5; section H.23(c2) is added (MB via stop-mask census from the fab Gerbers).

Run (stdlib only, like round3/calc/r3_calc.py):
    /c/Users/ricky/miniforge3/python.exe -I r7_calc.py
Outputs (written by this script, beside it): r7_calc_out.txt (the printed report) and r7_calc_out.json.

Coordinates: Eagle .brd board coordinates, mm, top view, origin at the MB origin, +x right, +y UP (design A.2). EVM
points use the EVM frame of round4/work/evm_geometry.md section 2.3 (origin at the lower-left EVM corner, top view).

Sources (the tag in each input comment names one):
  BRD   references/Scale Car Board PCB 20260625.brd, read through round4/calc/mb_neighbours.py (element_records) and
        directly (signals: layer-1 wires and polygons with their outline widths, vias; design rules).
  GBR   references/PCB Manufacturing Files/soldermask_top.gbr, soldermask_bottom.gbr (MB fab output).
  DOC   docs/charger_bq25798_wiring_design_2026-11-05.md r6 (sections named per input).
  BASIS round4/work/r7_design_basis.md (the r7 decisions).
  EVMG  round4/work/evm_geometry.md (Tables 1, 2, 6) and round4/work/evm_calc/evm_geom_out.txt (vector EVM points).
  MBM   round4/work/mb_mechanical.md (equations 2 and 3, Table 7) and round4/work/mb_pinload.py (pin-group model).
  STK   round4/work/stackup_area.md and round4/calc/stackup_area.py (strict area basis, courtyard bookings).
  MIN   round4/work/proposal_minimal.md and round4/work/minimal_calc/*.py (the adopted proposal; its numbers are
        compared, never copied).
  EIBM  round4/work/eib_merge_calc.py (E1/C205 loop-inductance model) and round4/work/eib_merge_failsafe.md Table 9.
  AWG   standard annealed-copper AWG resistance table at 20 C (as in eib_merge_calc.py): 18 AWG 20.95, 20 AWG 33.31,
        26 AWG 133.9, 28 AWG 212.9 mOhm/m; it reproduces DOC H.11 (checked in H.23(l)).
Inputs that no source gives are marked ASSUMPTION; unknowns are marked TODO(measure: ...) or TODO(verify: ...).
Every resonance and pin-load figure is an ORDER-OF-MAGNITUDE estimate.

Revision 2 (after the independent check round4/work/r7_check/ and BASIS section 10):
  E1 the square MB CHG header pads are squares in every plan clearance (eff()); E2 per-net copper area = the union of
  the net's shapes; E3 a shape that touches the r7 outline reports the part that lies outside it; E4 the r6 tap lengths
  of T22/T8/T9 use their r6 pads; E5 the W5 terminal label. A1 foot size and position by placement tolerance
  (foot_search); A2 T18 moved to the footprint residual row and the tab X assignment rerun; A3 the adopted allocation
  case; A4 the open-ended USB corridor fallbacks (i)-(iii) and the skin-effect bound on the E1/C205 Q.

Revision 3 (BASIS section 11): B1 FT1 at the exact max-min centre y (off the 0.02 mm grid) and the FT1 fallback sheet
  cut-out check; B2 FT2 at the largest lever with t >= 0.25 mm, no edge lane, the 1.0 mm fill hole and its CR-top
  keep-out disc (booked in the top area); B3 T18/F22 on the low row, the REG-5V distance of the common path end and the
  post-beside check; B5 the chassis room of fallback (i) from the most negative lead point plus a bend allowance; B6
  per-net copper areas stated to +-0.3 mm2 and the unrounded r3 bottom set 435.25 mm2.

Review-7 revision (round4/work/r7_review7_dispositions.md D-F1..D-F5, D-F7):
  D-F1 H.23(i): 0.05 mm transfer-tape bond, h_f = 2.19 mm, block +0/-0.05 mm, the vertical tolerance budget of t_bed
  (worst case, RSS, Monte-Carlo against the PM4 (2d) 0.15 / 0.45 mm gate), the T-A-09 pull options and the recommended
  pull, the feet effect, the tab Y grip in line with FT2 (x 28.00), Gent-scaled propped f1; H.23(h) 'crossing' labels.
  D-F2/D-F3 H.23(l): the designed W-lead dressing path (trunk, tab Y, MB tie bases A1/A2), its 2 mm hazard, 10 mm
  switched-conductor and 1.5 mm rework-point clearances, a raster proof of the best achievable switched clearance,
  anchors and spans <= 30 mm, MB parts and untented non-GND vias under each lead, route rule on the new path for the
  reference placement and fallback (i), W1/W2 fixed 0.30 m +- 10 mm with the r3 in_spike hard-short rows, W5 fixed
  cable minimum fit, W5 routed off the W3/W4 USB channel. D-F4 H.23(g): tab X assignment with adjacency exclusions,
  adjacency check, adjacent-pad short table, dressed lengths on the legal gap path, residual LM1084/post checks (T8).
  D-F5 H.23(e2): per-region top booking; H.23(f): comparator band vs the MB BT boost and the 5V copper, divider strip.
  D-F7 H.23(m): sheet trims clear MB pads as well as bodies.

Revision 4 (agreement with the r7 design text after the review-7 fix round; D-H operator statement 2026-11-10: no
maximum height for the MB and its PCBs; decision: the 10 mm switched-conductor rule is a 3-D distance):
  H.23(e2) B3 and S3 booked as one union spot; U108/U109 to the interior by the gate loop; the flexible passives stay on
  the bottom (the whole-side H.23(e) booking is the reason); the band U on its exact area; the gates-alone figures
  computed; the decoupler-on-top and U108-kept sensitivities. H.23(g) T8 lane with a >= 0.5 mm jacket-to-pad gap on
  the CR (the low-edge lane is shown infeasible; an upper lane over the residual row); computed consequences of the
  open pairs F05-F12 and F07-F12 and of the residual pairs; the extended exclusion set run as a candidate. H.23(i) the
  adopted 0.4 N T-A-09 pull with its stress ratio on the tip-load and the distributed-load basis. H.23(j) the stack
  top as information only (D-H). H.23(k) the A.5 E1 route through one bend. H.23(l) spacer beads S1/S2 off the J101
  region and the W6/W7 pad exclusion; the last span to the chassis tie (maximum tie distance past the MB +y edge per
  group with a 2 mm margin; the west-group MB tie-base search); the 3-D switched-conductor heights per lead; the
  polyimide strip with the via pad radius and the W5 elevated-run vias; W1/W2 and W5 labelled fixed length. H.23(m)
  relief holes enlarged to clear the pad corners by 0.5 mm (merge check) and enlarged cut-outs.

Revision 5 (r8 of the design; charger-design audit run 001, docs/reviews/charger-design/run-001-2026-11-10.md, ledger
CHG-R1-01..08, D01..D04, W01, A02): every section above is unchanged and prints the same lines; H.23(n)-(w) are added:
  H.23(n) R106s FLT series resistor: bridge-current bound with resistor and supply tolerances against the 10 mA FLT
  absolute maximum (tps2663.pdf SLVSE94G sec 6.1), EN level, FLT readback level = R(FLT) drop + pull-up drop (sec 6.5),
  FR-23 diagnostic dwell vs tCL_PLIM (sec 6.6). H.23(o) T3 I2C transaction schedule at 100/400 kHz (bits per byte with
  ACK, START/Sr/STOP, t_BUF, the FR-07 cap), write-first / read-back-after. H.23(p) W1/W2 L' = (mu0/pi) acosh(s/2a) over
  conductor, insulation OD and twist pitch, the recommended wire, the unchanged in_spike model, the plan-rule OD limit.
  H.23(q) pin-38 decay below UVLO and the proposed 12 V / 0.5 s criterion across initial voltage and eFuse states.
  H.23(r) foot-bond fallback height and gate re-run, FT2 repair access. H.23(s) B1 riser B1R (machined wedge) and the CR-end
  strain relief over the full 3-D profile. H.23(t) W5 / trunk vertical stacking. H.23(u) EVM-to-CR distances E1-E8.
  H.23(v) E8 pickup with / without R276. H.23(w) the closing-pass hand figures.

Revision 6 (r8 integration): every section above is unchanged and prints the same lines; H.23(x) is added: the figures
  that the r8 FR and test text derives from H.23(n), (o) and (q) (FR-12(b2) timeout basis, the four field reads in sum,
  the T1 step-8 increment, the T-C-05c pad pull-up current).

Revision 7 (r8 verification round): H.23(y) is added after H.23(x). Every line printed by revisions 4-6 keeps its position
  and its numbers; three lines change wording only: the H.23(p) model line states that the helix factor is evaluated at OD
  max (as the code always did), and the H.23(q) input, r7 and worst-case lines and its summary row label IQ(ON) 1.38 mA as
  the TYPICAL value (tps2663.pdf sec 6.5 gives no minimum). H.23(y): (1) the F17-F15 node level with FLT asserted and
  U108 HIGH; (2) the T3 FIFO case and the FR-07 queue-priority bound; (3) the W1/W2 lead current when the FET opens and
  the helix factor at OD min; (4) the B1R lateral support of the trunk; (5) W5 / trunk figures at the T-F-12 points;
  (6) the C205/TP27 sweep over the E1 build range 70.8-90 mm; (7) the T1 increment with the step-8c pre-edge read.
"""
import json
import math
import os
import random
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mb_neighbours as mbn  # noqa: E402

REPO = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
BRD_PATH = mbn.DEF_BRD
GBR_DIR = os.path.join(REPO, "references", "PCB Manufacturing Files")
OUT_TXT = os.path.join(HERE, "r7_calc_out.txt")
OUT_JSON = os.path.join(HERE, "r7_calc_out.json")

LINES = []
RJ = {}          # JSON results by section
SUMMARY = []     # (key, value, source)


def out(s=""):
    print(s)
    LINES.append(s)


def head(s):
    out("")
    out("=" * 118)
    out(s)
    out("=" * 118)


def summ(key, value, src):
    SUMMARY.append((key, value, src))


def f2(v):
    return round(float(v), 3)


# ======================================================================================================================
# 0. Geometry helpers (stdlib)
# ======================================================================================================================
def dpt_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _onseg(a, b, c):
    return (min(a[0], b[0]) - 1e-12 <= c[0] <= max(a[0], b[0]) + 1e-12 and
            min(a[1], b[1]) - 1e-12 <= c[1] <= max(a[1], b[1]) + 1e-12)


def seg_x(p1, p2, p3, p4):
    d1, d2 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    d3, d4 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    if abs(d1) < 1e-12 and _onseg(p3, p4, p1):
        return True
    if abs(d2) < 1e-12 and _onseg(p3, p4, p2):
        return True
    if abs(d3) < 1e-12 and _onseg(p1, p2, p3):
        return True
    if abs(d4) < 1e-12 and _onseg(p1, p2, p4):
        return True
    return False


def dseg_seg(a, b, c, d):
    if seg_x(a, b, c, d):
        return 0.0
    return min(dpt_seg(a[0], a[1], c[0], c[1], d[0], d[1]), dpt_seg(b[0], b[1], c[0], c[1], d[0], d[1]),
               dpt_seg(c[0], c[1], a[0], a[1], b[0], b[1]), dpt_seg(d[0], d[1], a[0], a[1], b[0], b[1]))


def pip(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def edges(poly):
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def rpoly(r):
    x0, y0, x1, y1 = r
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def area_poly(poly):
    s = 0.0
    for (a, b) in edges(poly):
        s += a[0] * b[1] - b[0] * a[1]
    return 0.5 * s


def shape_segs(sh):
    p = sh["pts"]
    if sh["closed"]:
        return edges(p)
    if len(p) == 1:
        return [(p[0], p[0])]
    return [(p[i], p[i + 1]) for i in range(len(p) - 1)]


def eff(sh):
    """Geometry used for every plan distance. An MB CHG header pad (shape="square" in the .brd) is its square
    (closed box, r = 0; the pad corners are not rounded in the model), not a disc. Other shapes are unchanged."""
    if not sh.get("square"):
        return sh
    q = sh.get("_sq")
    if q is None:
        c, h = sh["pts"][0], sh["r"]
        q = {k: v for k, v in sh.items() if k != "_sq"}
        q.update(kind="sqpad", square=False, closed=True, r=0.0,
                 pts=rpoly((c[0] - h, c[1] - h, c[0] + h, c[1] + h)))
        q["bb"] = (c[0] - h, c[1] - h, c[0] + h, c[1] + h)
        sh["_sq"] = q
    return q


def geom_dist(sh, region):
    """Plan distance between the shape's geometric primitive (centreline / vertex path / box) and a closed region;
    0.0 if they overlap. The rim (sh['r']) is NOT subtracted here. A square MB CHG pad is taken as its square."""
    sh = eff(sh)
    pts = sh["pts"]
    if any(pip(p[0], p[1], region) for p in pts):
        return 0.0
    if sh["closed"] and any(pip(q[0], q[1], pts) for q in region):
        return 0.0
    segs = shape_segs(sh)
    best = 1e9
    for s in segs:
        for e in edges(region):
            d = dseg_seg(s[0], s[1], e[0], e[1])
            if d < best:
                best = d
                if best == 0.0:
                    return 0.0
    return best


def clearance(sh, region):
    """Signed plan clearance of the shape's rim to the region (negative: the rim overlaps the region)."""
    return geom_dist(sh, region) - eff(sh)["r"]


def dist_to_seg_shape(sh, a, b):
    """Rim clearance between a shape and a single segment a-b (a named outline edge)."""
    sh = eff(sh)
    best = 1e9
    if sh["closed"] and (pip(a[0], a[1], sh["pts"]) or pip(b[0], b[1], sh["pts"])):
        return -sh["r"]
    for s in shape_segs(sh):
        best = min(best, dseg_seg(s[0], s[1], a, b))
    return best - sh["r"]


def rect_dist(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def rect_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def dim_mm(s):
    s = s.strip()
    if s.endswith("mil"):
        return float(s[:-3]) * 0.0254
    if s.endswith("mm"):
        return float(s[:-2])
    return float(s)


# ======================================================================================================================
# 1. Raster grid (bytearray masks) for the area work of H.23(c)(d)(e)(h)
# ======================================================================================================================
class Grid:
    def __init__(self, x0, y0, x1, y1, res):
        self.x0, self.y0, self.res = x0, y0, res
        self.nx = int(math.ceil((x1 - x0) / res - 1e-6))
        self.ny = int(math.ceil((y1 - y0) / res - 1e-6))
        self.N = self.nx * self.ny
        self.cell = res * res

    def new(self):
        return bytearray(self.N)

    def cx(self, i):
        return self.x0 + (i + 0.5) * self.res

    def cy(self, j):
        return self.y0 + (j + 0.5) * self.res

    def irange(self, xa, xb):
        i0 = max(0, int(math.ceil((xa - self.x0) / self.res - 0.5 - 1e-9)))
        i1 = min(self.nx - 1, int(math.floor((xb - self.x0) / self.res - 0.5 + 1e-9)))
        return i0, i1

    def jrange(self, ya, yb):
        j0 = max(0, int(math.ceil((ya - self.y0) / self.res - 0.5 - 1e-9)))
        j1 = min(self.ny - 1, int(math.floor((yb - self.y0) / self.res - 0.5 + 1e-9)))
        return j0, j1

    def mark_rect(self, m, x0, y0, x1, y1, v=1):
        i0, i1 = self.irange(x0, x1)
        j0, j1 = self.jrange(y0, y1)
        if i1 < i0 or j1 < j0:
            return
        row = bytes([v]) * (i1 - i0 + 1)
        for j in range(j0, j1 + 1):
            k = j * self.nx
            m[k + i0:k + i1 + 1] = row

    def mark_disk(self, m, cx, cy, r):
        i0, i1 = self.irange(cx - r, cx + r)
        j0, j1 = self.jrange(cy - r, cy + r)
        r2 = r * r
        for j in range(j0, j1 + 1):
            y = self.cy(j)
            k = j * self.nx
            for i in range(i0, i1 + 1):
                x = self.cx(i)
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                    m[k + i] = 1

    def mark_seg(self, m, a, b, r):
        ax, ay = a
        bx, by = b
        i0, i1 = self.irange(min(ax, bx) - r, max(ax, bx) + r)
        j0, j1 = self.jrange(min(ay, by) - r, max(ay, by) + r)
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        r2 = r * r
        for j in range(j0, j1 + 1):
            y = self.cy(j)
            k = j * self.nx
            for i in range(i0, i1 + 1):
                x = self.cx(i)
                if l2 > 0:
                    t = ((x - ax) * dx + (y - ay) * dy) / l2
                    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
                    qx, qy = ax + t * dx - x, ay + t * dy - y
                else:
                    qx, qy = ax - x, ay - y
                if qx * qx + qy * qy <= r2:
                    m[k + i] = 1

    def mark_poly(self, m, pts, r):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        j0, j1 = self.jrange(min(ys), max(ys))
        es = edges(pts)
        for j in range(j0, j1 + 1):
            y = self.cy(j)
            xi = []
            for (p, q) in es:
                if (p[1] > y) != (q[1] > y):
                    xi.append(p[0] + (y - p[1]) * (q[0] - p[0]) / (q[1] - p[1]))
            xi.sort()
            for t in range(0, len(xi) - 1, 2):
                i0, i1 = self.irange(xi[t], xi[t + 1])
                if i1 >= i0:
                    k = j * self.nx
                    m[k + i0:k + i1 + 1] = b"\x01" * (i1 - i0 + 1)
        if r > 0:
            for (p, q) in es:
                self.mark_seg(m, p, q, r)

    def mark_shape(self, m, sh, grow):
        r = sh["r"] + grow
        if sh["kind"] in ("box", "sqpad"):
            x0, y0 = sh["pts"][0]
            x1, y1 = sh["pts"][2]
            self.mark_rect(m, x0 - grow, y0 - grow, x1 + grow, y1 + grow)
        elif sh["kind"] == "poly":
            self.mark_poly(m, sh["pts"], r)
        elif sh["kind"] == "via" or sh["kind"] == "pad":
            if sh.get("square"):
                c = sh["pts"][0]
                h = sh["r"]
                # square pad: box plus grow (rounded corners ignored: conservative)
                self.mark_rect(m, c[0] - h - grow, c[1] - h - grow, c[0] + h + grow, c[1] + h + grow)
            else:
                c = sh["pts"][0]
                self.mark_disk(m, c[0], c[1], r)
        else:
            for (p, q) in shape_segs(sh):
                self.mark_seg(m, p, q, r)


def mask_and_not(a, b):
    return bytearray(x & (1 - y) for x, y in zip(a, b))


def mask_or(a, b):
    return bytearray(x | y for x, y in zip(a, b))


def mask_and(a, b):
    return bytearray(x & y for x, y in zip(a, b))


def count(m):
    return m.count(1)


# ======================================================================================================================
# 2. Board data (BRD)
# ======================================================================================================================
BOARD = ET.parse(BRD_PATH).getroot().find("drawing/board")
ELS = {e["name"]: e for e in mbn.element_records(BOARD)}
MB_OUTLINE = (0.0, 0.0, 131.064, 98.044)          # BRD layer 20 (mb_neighbours_out.txt)

DR = {p.get("name"): p.get("value") for p in BOARD.find("designrules").findall("param")}
VIA_DRILL_SET = set()
VIAS, WIRES1, POLYS1 = [], [], []
for sig in BOARD.find("signals"):
    net = sig.get("name")
    for g in sig:
        if g.tag == "via":
            VIAS.append(dict(net=net, x=float(g.get("x")), y=float(g.get("y")), drill=float(g.get("drill")),
                             dia_attr=float(g.get("diameter") or 0.0), alwaysstop=g.get("alwaysstop")))
            VIA_DRILL_SET.add(float(g.get("drill")))
        elif g.tag == "wire" and g.get("layer") == "1":
            if g.get("curve"):
                raise SystemExit("curved L1 wire found; this script assumes straight wires (net %s)" % net)
            WIRES1.append(dict(net=net, a=(float(g.get("x1")), float(g.get("y1"))),
                               b=(float(g.get("x2")), float(g.get("y2"))), w=float(g.get("width"))))
        elif g.tag == "polygon" and g.get("layer") == "1":
            pts = [(float(v.get("x")), float(v.get("y"))) for v in g.findall("vertex")]
            if any(v.get("curve") for v in g.findall("vertex")):
                raise SystemExit("curved polygon vertex found (net %s)" % net)
            POLYS1.append(dict(net=net, pts=pts, w=float(g.get("width"))))

# Via outer (pad) diameter from the BRD design rules: restring = clamp(rvViaOuter x drill, rlMinViaOuter, rlMaxViaOuter);
# the larger of that and the via 'diameter' attribute applies.
RV = float(DR["rvViaOuter"])
RLMIN, RLMAX = dim_mm(DR["rlMinViaOuter"]), dim_mm(DR["rlMaxViaOuter"])
STOPFRAME = dim_mm(DR["mlMinStopFrame"])


def via_dia(v):
    rs = min(max(RV * v["drill"], RLMIN), RLMAX)
    return max(v["drill"] + 2 * rs, v["dia_attr"])


VIA_D = sorted({round(via_dia(v), 4) for v in VIAS})
# TH pad outer diameter (MB CHG header holes) from rvPadTop / rlMinPadTop / rlMaxPadTop (BRD).
RVP = float(DR["rvPadTop"])
RLPMIN, RLPMAX = dim_mm(DR["rlMinPadTop"]), dim_mm(DR["rlMaxPadTop"])

CONTACT = {}
for sig in BOARD.find("signals"):
    for c in sig.findall("contactref"):
        CONTACT[(c.get("element"), c.get("pad"))] = sig.get("name")

# Packages (for part bodies)
PKGS = {}
for lib in BOARD.find("libraries"):
    pr = lib.find("packages")
    if pr is None:
        continue
    for p in pr:
        PKGS[(lib.get("name"), p.get("name"))] = p
ELEM_XML = {e.get("name"): e for e in BOARD.find("elements")}


def body_box(name):
    """Part body box: layers 21 (tPlace) and 51 (tDocu) straight wires and rectangles, transformed to the board;
    curved wires, circles and polygons are pin-1 markers and are excluded. Falls back to the mb_neighbours box."""
    e = ELEM_XML[name]
    pk = PKGS.get((e.get("library"), e.get("package")))
    ex, ey, rot = float(e.get("x")), float(e.get("y")), e.get("rot", "R0")
    pts = []
    if pk is not None:
        for g in pk:
            if g.get("layer") not in ("21", "51"):
                continue
            if g.tag == "wire" and not g.get("curve"):
                pts += [mbn.xf(float(g.get("x1")), float(g.get("y1")), ex, ey, rot),
                        mbn.xf(float(g.get("x2")), float(g.get("y2")), ex, ey, rot)]
            elif g.tag == "rectangle":
                x1, y1, x2, y2 = (float(g.get(k)) for k in ("x1", "y1", "x2", "y2"))
                pts += [mbn.xf(x, y, ex, ey, rot) for (x, y) in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
    b = mbn.bbox(pts)
    return b if b else ELS[name]["bbox"]


def pad_rects(name):
    """Copper pad boxes of a part (smd dx x dy rotated; through-hole pads as the BRD diameter square), board frame."""
    e = ELEM_XML[name]
    pk = PKGS.get((e.get("library"), e.get("package")))
    ex, ey, rot = float(e.get("x")), float(e.get("y")), e.get("rot", "R0")
    out_ = []
    if pk is None:
        return out_
    for g in pk:
        if g.tag == "smd":
            px, py = float(g.get("x")), float(g.get("y"))
            dx, dy = float(g.get("dx")), float(g.get("dy"))
            la = math.radians(mbn.rot_of(g.get("rot", "R0"))[1])
            cs = [mbn.xf(px + sx * dx * math.cos(la) - sy * dy * math.sin(la),
                         py + sx * dx * math.sin(la) + sy * dy * math.cos(la), ex, ey, rot)
                  for sx in (-0.5, 0.5) for sy in (-0.5, 0.5)]
            out_.append((g.get("name"), mbn.bbox(cs)))
        elif g.tag == "pad":
            dr = float(g.get("drill"))
            dia = float(g.get("diameter") or 0) or (dr + 0.8)
            c = mbn.xf(float(g.get("x")), float(g.get("y")), ex, ey, rot)
            out_.append((g.get("name"), [c[0] - dia / 2, c[1] - dia / 2, c[0] + dia / 2, c[1] + dia / 2]))
    return out_


# ---------------------------------------------------------------------------------------------------------------------
# Shape lists
# ---------------------------------------------------------------------------------------------------------------------
VIA_R = None


def build_shapes():
    global VIA_R
    sh = []
    for w in WIRES1:
        sh.append(dict(kind="wire", net=w["net"], pts=[w["a"], w["b"]], closed=False, r=w["w"] / 2,
                       label="%s L1 trace w%.3f (%.2f,%.2f)-(%.2f,%.2f)" % (w["net"], w["w"], w["a"][0], w["a"][1],
                                                                            w["b"][0], w["b"][1])))
    for p in POLYS1:
        xs = [q[0] for q in p["pts"]]
        ys = [q[1] for q in p["pts"]]
        sh.append(dict(kind="poly", net=p["net"], pts=p["pts"], closed=True, r=p["w"] / 2,
                       label="%s L1 polygon w%.3f bbox (%.2f,%.2f)-(%.2f,%.2f)" % (p["net"], p["w"], min(xs), min(ys),
                                                                                  max(xs), max(ys))))
    for v in VIAS:
        d = via_dia(v)
        sh.append(dict(kind="via", net=v["net"], pts=[(v["x"], v["y"])], closed=False, r=d / 2,
                       label="%s via (%.3f,%.3f) pad %.4f" % (v["net"], v["x"], v["y"], d)))
    VIA_R = max(via_dia(v) for v in VIAS) / 2
    # MB CHG header pads (layer-1 copper of the removed Ag105 footprint; the CR header pins solder into them)
    e = ELEM_XML["CHG"]
    pk = PKGS[(e.get("library"), e.get("package"))]
    ex, ey, rot = float(e.get("x")), float(e.get("y")), e.get("rot", "R0")
    for g in pk:
        if g.tag == "pad":
            dr = float(g.get("drill"))
            rs = min(max(RVP * dr, RLPMIN), RLPMAX)
            dia = max(dr + 2 * rs, float(g.get("diameter") or 0.0))
            c = mbn.xf(float(g.get("x")), float(g.get("y")), ex, ey, rot)
            net = CONTACT.get(("CHG", g.get("name")), "(unconnected)")
            sh.append(dict(kind="pad", net=net, pts=[c], closed=False, r=dia / 2, square=g.get("shape") == "square",
                           label="CHG pad %s %s (%.3f,%.3f) %.3f mm %s" % (g.get("name"), net, c[0], c[1], dia,
                                                                         g.get("shape") or "round")))
    return sh


SHAPES = build_shapes()
for _s in SHAPES:
    _s["bb"] = mbn.bbox(_s["pts"])
# Non-GND = every layer-1 feature whose net is not GND; the unconnected CHG anchor pads (no net) count as non-GND
# (bottom clearance rule: "every MB layer-1 feature that is not GND").
NONGND = [s for s in SHAPES if s["net"] != "GND"]
PARTS = []
for n, e in ELS.items():
    if n == "CHG":
        continue
    b = e["bbox"]
    PARTS.append(dict(kind="box", net="-", name=n, pts=rpoly(b), closed=True, r=0.0, bbox=b,
                      label="%s box (%.2f,%.2f)-(%.2f,%.2f)" % (n, b[0], b[1], b[2], b[3])))

# L-FC: .brd silkscreen body 12.6 mm in y (layer 21, centre-line) and the Eaton listing body 13.8 x 12.9 x 5.0 mm
# (mb_mechanical.md Table 3; TODO(verify: Eaton HCM1A1305V3 drawing)). ASSUMPTION: the 12.9 mm body is centred on the
# footprint origin (the centre of the pad pair), as the 12.6 mm silkscreen is.
LFC_EL = ELEM_XML["L-FC"]
LFC_C = (float(LFC_EL.get("x")), float(LFC_EL.get("y")))
LFC_SILK = body_box("L-FC")
LFC_EATON = (LFC_C[0] - 13.8 / 2, LFC_C[1] - 12.9 / 2, LFC_C[0] + 13.8 / 2, LFC_C[1] + 12.9 / 2)

# ======================================================================================================================
# 3. r7 outline (BASIS section 1 and D1)
# ======================================================================================================================
R6 = (17.70, 34.14, 48.70, 67.14)                 # DOC A.7 r3/r6 CR rectangle
TAB_X = (48.70, 56.30, 65.00, 68.30)              # BASIS tab X
TAB_Y = (17.70, 67.14, 37.56, 76.00)              # BASIS tab Y (trimmed)
CHAMFER = 1.0                                     # BASIS D1: 1.0 mm x 45 deg at (17.70, 76.00)
OUTLINE = [(17.70, 34.14), (48.70, 34.14), (48.70, 56.30), (65.00, 56.30), (65.00, 68.30), (48.70, 68.30),
           (48.70, 67.14), (37.56, 67.14), (37.56, 76.00), (17.70 + CHAMFER, 76.00), (17.70, 76.00 - CHAMFER)]
EDGE_NAMES = ["r6 low-y edge y 34.14", "r6 +x edge x 48.70 (below tab X)", "tab X low edge y 56.30",
              "tab X right edge x 65.00", "tab X top edge y 68.30", "tab X left step x 48.70 (y 67.14-68.30)",
              "r6 top edge remainder y 67.14 (x 37.56-48.70)", "tab Y right edge x 37.56", "tab Y top edge y 76.00",
              "chamfer (18.70,76.00)-(17.70,75.00)", "left edge x 17.70"]
CY = 0.5                                          # DOC A.7: every courtyard >= 0.5 mm from the outline
PIN_A = [(20.998, 36.544 + 2.54 * k) for k in range(12)]   # DOC A.8 pins 22..11
PIN_B = [(45.998, 39.084 + 2.54 * k) for k in range(10)]   # DOC A.8 pins 1..10
PINS = PIN_A + PIN_B
W_PADS = {"W1 VCHGOUT": (30.3, 61.2, 2.3), "W2 GND": (27.7, 61.2, 2.3), "W3 VCHG": (24.3, 45.4, 2.5),
          "W4 GND": (24.3, 55.6, 2.5)}            # DOC A.8 (centre x, y, pad diameter)
TAB_X_EDGES = {k: (OUTLINE[i], OUTLINE[(i + 1) % 11]) for i, k in enumerate(EDGE_NAMES) if k.startswith("tab X")}
TAB_Y_EDGES = {k: (OUTLINE[i], OUTLINE[(i + 1) % 11]) for i, k in enumerate(EDGE_NAMES)
               if k.startswith("tab Y") or k.startswith("chamfer")}
TAB_Y_EDGES["left edge x 17.70 (tab Y part, y 67.14-75.00)"] = ((17.70, 75.00), (17.70, 67.14))
TAB_X_POLY = rpoly(TAB_X)
TAB_Y_POLY = [(17.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]


def sec_a():
    head("H.23(a) r7 outline: vertices, areas, chamfer, bounding box")
    out("Sources: r6 rectangle DOC A.7; tab X, tab Y and the relocated chamfer BASIS D1 / section 1.")
    out("vertex  x       y       corner")
    conc = []
    n = len(OUTLINE)
    for i, v in enumerate(OUTLINE):
        a, b = OUTLINE[i - 1], OUTLINE[(i + 1) % n]
        z = (v[0] - a[0]) * (b[1] - v[1]) - (v[1] - a[1]) * (b[0] - v[0])
        kind = "convex" if z > 0 else "concave"
        if z < 0:
            conc.append(v)
        out("  V%-3d %7.2f %7.2f  %s" % (i + 1, v[0], v[1], kind))
    a_r6 = (R6[2] - R6[0]) * (R6[3] - R6[1])
    a_x = (TAB_X[2] - TAB_X[0]) * (TAB_X[3] - TAB_X[1])
    a_y = (TAB_Y[2] - TAB_Y[0]) * (TAB_Y[3] - TAB_Y[1])
    a_ch = CHAMFER * CHAMFER / 2
    a_tot = area_poly(OUTLINE)
    bb = mbn.bbox(OUTLINE)
    out("areas: r6 rectangle %.2f + tab X %.2f + tab Y %.2f - chamfer %.2f = %.2f mm2 (shoelace %.2f mm2)"
        % (a_r6, a_x, a_y, a_ch, a_r6 + a_x + a_y - a_ch, a_tot))
    out("added by the tabs: %.2f mm2 gross (minimal proposal: tab Y 206.3 mm2, total 1424.9 mm2; r7 trim -%.2f mm2)"
        % (a_x + a_y - a_ch, 1424.9 - a_tot))
    out("bounding box x %.2f-%.2f, y %.2f-%.2f = %.2f x %.2f mm (minimal: 47.30 x 42.37 mm)"
        % (bb[0], bb[2], bb[1], bb[3], bb[2] - bb[0], bb[3] - bb[1]))
    out("concave corners (fab router radius, TODO(verify: MS8 minimum inside-corner radius)): %s"
        % ", ".join("(%.2f, %.2f)" % c for c in conc))
    out("chamfer: the only chamfered corner, 1.0 mm x 45 deg at the tab Y -x/+y corner (17.70, 76.00); the r6 chamfer "
        "corner (17.70, 67.14) is now a point on the straight left edge x 17.70")
    RJ["a"] = dict(vertices=OUTLINE, area_r6=a_r6, area_tab_x=a_x, area_tab_y=a_y, chamfer=a_ch, area_total=a_tot,
                   bbox=bb, concave=conc)
    summ("r7 outline gross area", "%.2f mm2 (r6 1023.00 + tab X %.2f + tab Y %.2f - chamfer %.2f)"
         % (a_tot, a_x, a_y, a_ch), "H.23(a)")
    summ("r7 outline bounding box", "x 17.70-65.00, y 34.14-76.00 = %.2f x %.2f mm" % (bb[2] - bb[0], bb[3] - bb[1]),
         "H.23(a)")


# ======================================================================================================================
# H.23(b) plan clearances of the tabs
# ======================================================================================================================
def outside_part(sh, edges_named):
    """For a shape whose centreline / box touches or crosses the r7 outline: the part that lies OUTSIDE the outline
    and its rim clearance to the named free tab edges. Returns None when the shape lies wholly inside the outline.
    Wires are clipped exactly against the outline; a closed shape with a vertex outside is taken whole (conservative)."""
    sh = eff(sh)
    if sh["kind"] == "wire":
        a, b = sh["pts"]
        ts = [0.0, 1.0]
        dx, dy = b[0] - a[0], b[1] - a[1]
        for (p, q) in edges(OUTLINE):
            ex, ey = q[0] - p[0], q[1] - p[1]
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            t = ((p[0] - a[0]) * ey - (p[1] - a[1]) * ex) / den
            u = ((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / den
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                ts.append(t)
        ts = sorted(set(round(t, 12) for t in ts))
        subs = []
        for t0, t1 in zip(ts[:-1], ts[1:]):
            if t1 - t0 < 1e-9:
                continue
            tm = 0.5 * (t0 + t1)
            if not pip(a[0] + tm * dx, a[1] + tm * dy, OUTLINE):
                subs.append(((a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)))
        if not subs:
            return None
        best = None
        for (p, q) in subs:
            for en, (e0, e1) in edges_named.items():
                d = dseg_seg(p, q, e0, e1) - sh["r"]
                if best is None or d < best[0]:
                    best = (d, en, (p, q))
        p, q = best[2]
        return best[0], "(%.2f,%.2f)-(%.2f,%.2f)" % (p[0], p[1], q[0], q[1]), best[1]
    if sh["closed"]:
        if all(pip(v[0], v[1], OUTLINE) for v in sh["pts"]):
            return None
        best = min(((dist_to_seg_shape(sh, e0, e1), en) for en, (e0, e1) in edges_named.items()), key=lambda z: z[0])
        return best[0], "whole shape (a vertex lies outside)", best[1]
    c = sh["pts"][0]
    if pip(c[0], c[1], OUTLINE):
        return None
    best = min(((dist_to_seg_shape(sh, e0, e1), en) for en, (e0, e1) in edges_named.items()), key=lambda z: z[0])
    return best[0], "whole shape", best[1]


def tab_features(region, edges_named, within=5.0):
    rows = []
    feats = []
    for p in PARTS:
        feats.append(("part box", p))
    feats.append(("L-FC body (silkscreen 12.6 mm)", dict(kind="box", net="-", name="L-FC silk", pts=rpoly(LFC_SILK),
                                                         closed=True, r=0.0, label="L-FC silkscreen body (%.3f,%.3f)-"
                                                         "(%.3f,%.3f)" % tuple(LFC_SILK))))
    feats.append(("L-FC body (Eaton 12.9 mm, centred)", dict(kind="box", net="-", name="L-FC Eaton", pts=rpoly(LFC_EATON),
                                                             closed=True, r=0.0, label="L-FC Eaton body (%.3f,%.3f)-"
                                                             "(%.3f,%.3f)" % tuple(LFC_EATON))))
    for s in NONGND:
        feats.append(("non-GND copper rim", s))
    rb = mbn.bbox(region)
    for kind, sh in feats:
        sh = eff(sh)
        sb = sh.get("bb") or mbn.bbox(sh["pts"])
        if rect_dist(sb, rb) > within + sh["r"] + 0.01:
            continue
        g = geom_dist(sh, region)
        if g - sh["r"] > within:
            continue
        best = None
        for en, (a, b) in edges_named.items():
            d = dist_to_seg_shape(sh, a, b)
            if best is None or d < best[0]:
                best = (d, en)
        body_c = None
        if kind == "part box":
            bb = body_box(sh["name"])
            body_c = min(dist_to_seg_shape(dict(kind="box", pts=rpoly(bb), closed=True, r=0.0), a, b)
                         for a, b in edges_named.values())
        if g == 0.0:
            status, c = "UNDER the tab", g - sh["r"]
        elif geom_dist(sh, OUTLINE) == 0.0:
            op = outside_part(sh, edges_named)
            if op is None:
                status, c = "under the CR r6 part (wholly inside the r7 outline; distance to the free tab edges)", \
                    best[0]
            else:
                c = op[0]
                best = (op[0], op[2])
                status = ("RIM OVERLAPS the tab edge" if c < 0 else ("FLAG < 0.5 mm" if c < 0.5 else "ok")) + \
                    " (part outside the r7 outline: %s; the rest lies under the CR r6 part)" % op[1]
        else:
            c = best[0]
            status = "RIM OVERLAPS the tab edge" if c < 0 else ("FLAG < 0.5 mm" if c < 0.5 else "ok")
            if kind == "part box" and c < 0.5 and body_c is not None and body_c >= 0.5:
                status = "box < 0.5 mm only (body %.3f mm)" % body_c
        rows.append(dict(kind=kind, label=sh["label"], net=sh.get("net"), clearance=c, edge=best[1],
                         edge_clear=best[0], status=status, body=body_c))
    rows.sort(key=lambda r: r["clearance"])
    return rows


def sec_b():
    head("H.23(b) plan clearance of every tab edge/corner to MB part boxes and non-GND copper rims within 5 mm")
    out("Part box = mb_neighbours.element_records bbox (pads + layers 21/22/39/40/51/52; BRD). Copper rim: a trace by "
        "w/2 around its centreline, a polygon by w/2 beyond its vertex path (outline width from the BRD), a via by its "
        "pad radius %.4f mm (drill %.2f + 2 x clamp(rvViaOuter %.2f x drill, rlMinViaOuter %.4f, rlMaxViaOuter %.4f); "
        "BRD design rules; confirmed by the %.4f mm stop-mask flashes = pad + 2 x mlMinStopFrame %.4f in GBR, H.23(c2)), "
        "an MB CHG header pad (shape=\"square\" in the BRD) by its square of side %s mm (drill + 2 x clamp(rvPadTop x "
        "drill, rlMinPadTop, rlMaxPadTop); the pad corners are not rounded in the model)."
        % (VIA_R, sorted(VIA_DRILL_SET)[0], RV, RLMIN, RLMAX, 2 * VIA_R + 2 * STOPFRAME, STOPFRAME,
           "/".join(sorted({"%.3f" % (2 * s["r"]) for s in SHAPES if s["kind"] == "pad" and s.get("square")}))))
    out("Clearance = plan distance from the feature (rim) to the nearest free edge of the tab; < 0: the rim reaches over "
        "that edge. 'UNDER the tab' = the centreline/box overlaps the tab (content in H.23(c)); 'under the CR r6 part "
        "(wholly inside the r7 outline)' = the feature lies under the r6 rectangle beside the tab root, and the "
        "distance to the free tab edges is shown for information. When such a feature also runs OUTSIDE the r7 "
        "outline, the clearance and the status refer to the part outside the outline (wires clipped exactly against "
        "the outline). For part boxes the body clearance (layers 21 + 51 straight outlines, markers excluded) is given "
        "too. GND copper is the board-wide pour and is not listed.")
    res = {}
    for tname, region, en in (("tab X", TAB_X_POLY, TAB_X_EDGES), ("tab Y", TAB_Y_POLY, TAB_Y_EDGES)):
        rows = tab_features(region, en)
        out("")
        out("--- %s %s; free edges: %s" % (tname, [tuple(round(v, 2) for v in p) for p in region], list(en)))
        out("  %-34s %-72s %9s %7s  %-42s %s" % ("feature class", "feature", "clear mm", "body", "nearest free edge",
                                               "status"))
        for r in rows:
            out("  %-34s %-72s %9.3f %7s  %-42s %s" % (r["kind"], r["label"][:72], r["clearance"],
                                                       "%.3f" % r["body"] if r["body"] is not None else "-",
                                                       r["edge"][:42], r["status"]))
        res[tname] = rows
    # L-FC both bodies against the tab Y top edge
    g_silk = LFC_SILK[1] - TAB_Y[3]
    g_eat = LFC_EATON[1] - TAB_Y[3]
    out("")
    out("L-FC against the tab Y top edge y %.2f: silkscreen body y0 %.3f -> %.3f mm; Eaton 12.9 mm body centred on the "
        "footprint origin (%.3f, %.3f) -> y0 %.3f -> %.3f mm (ASSUMPTION: centred; TODO(verify: Eaton HCM1A1305V3 "
        "drawing); MS3 caliper). At the untrimmed y 76.51: %.3f / %.3f mm."
        % (TAB_Y[3], LFC_SILK[1], g_silk, LFC_C[0], LFC_C[1], LFC_EATON[1], g_eat, LFC_SILK[1] - 76.51,
           LFC_EATON[1] - 76.51))
    summ("L-FC to tab Y top edge", "%.3f mm (12.6 mm silkscreen) / %.3f mm (12.9 mm Eaton body, centred ASSUMPTION)"
         % (g_silk, g_eat), "H.23(b)")
    # Named rework points (BASIS D1)
    pts = {"R171/T2 joint on C-D2 pad 1": ("pad", ELS["C-D2"]["pads"][0]),
           "RENC2": ("box", ELS["RENC2"]["bbox"]), "BAL pad 8": ("pad", [p for p in ELS["BAL"]["pads"] if p[0] == "8"][0]),
           "RB1A": ("box", ELS["RB1A"]["bbox"]), "CBL2": ("box", ELS["CBL2"]["bbox"]),
           "CO-5V": ("box", ELS["CO-5V"]["bbox"]), "T18 point (CO-5V pad 1)": ("pad", ELS["CO-5V"]["pads"][0]),
           "ROP1-FC": ("box", ELS["ROP1-FC"]["bbox"]), "ROP2-FC": ("box", ELS["ROP2-FC"]["bbox"])}
    out("")
    out("Named rework points (BASIS D1) against both tabs (plan distance, box or pad centre; > 0 = not covered):")
    rw = {}
    for k, (t, v) in pts.items():
        if t == "pad":
            box = (v[1], v[2], v[1], v[2])
        else:
            box = v
        dx_ = rect_dist(box, TAB_X)
        dy_ = rect_dist(box, TAB_Y)
        rw[k] = (dx_, dy_)
        out("  %-30s tab X %7.3f mm   tab Y %7.3f mm   %s" % (k, dx_, dy_,
                                                              "covered" if min(dx_, dy_) == 0 else "not covered"))
    # MB parts under either tab
    under = [p["name"] for p in PARTS if rect_overlap(p["bbox"], TAB_X) or rect_overlap(p["bbox"], TAB_Y)]
    out("MB part boxes overlapping a tab rectangle: %s" % (under if under else "none"))
    RJ["b"] = dict(rows={k: [dict((kk, (f2(vv) if isinstance(vv, float) else vv)) for kk, vv in r.items()) for r in v]
                         for k, v in res.items()}, lfc_silk_gap=g_silk, lfc_eaton_gap=g_eat, rework=rw,
                   parts_under=under)
    flags = [(t, r["label"], round(r["clearance"], 3)) for t in res for r in res[t] if r["clearance"] < 0.5]
    RJ["b"]["flags_lt_0p5"] = flags
    summ("MB parts under either tab", "none" if not under else ", ".join(under), "H.23(b)")
    for r in res["tab Y"]:
        if r["kind"] == "part box" and r["label"].startswith("ROP1-FC"):
            summ("ROP1-FC box to tab Y right edge", "%.3f mm" % r["clearance"], "H.23(b)")
        if r["kind"] == "part box" and r["label"].startswith("OP-FC"):
            summ("OP-FC box to tab Y", "%.3f mm" % r["clearance"], "H.23(b)")
    for r in res["tab X"]:
        if r["kind"] == "part box" and r["label"].startswith("REG-5V"):
            summ("REG-5V box to tab X low edge", "%.3f mm" % r["clearance"], "H.23(b)")
    for t in res:
        fl = ["%s: %.3f%s" % (r["label"].split(" box")[0] if r["kind"] == "part box" else r["label"][:44],
                              r["clearance"], " (part outside the r7 outline, to the %s)" % r["edge"]
                              if "part outside the r7 outline" in r["status"] else "")
              for r in res[t] if (r["clearance"] < 0.5 and r["status"].startswith(("FLAG < 0.5 mm",
                                                                                   "RIM OVERLAPS the tab edge")))
              or r["status"].startswith("box < 0.5")]
        summ("%s items < 0.5 mm outside the tab" % t, "; ".join(fl) if fl else "none", "H.23(b)")
    return res


# ======================================================================================================================
# H.23(c) MB content under each tab; H.23(c2) via stop-mask census (GBR)
# ======================================================================================================================
def gerber_flashes(path):
    txt = open(path).read()
    aps = {int(m.group(1)): (m.group(2), m.group(3)) for m in re.finditer(r"%ADD(\d+)([A-Z0-9]+),([^*]*)\*%", txt)}
    cur, fl = None, []
    for tok in txt.split("*"):
        tok = tok.strip()
        m = re.match(r"^(?:G54)?D(\d+)$", tok)
        if m and int(m.group(1)) >= 10:
            cur = int(m.group(1))
            continue
        m = re.match(r"^X(-?\d+)Y(-?\d+)D03$", tok)
        if m:
            fl.append((int(m.group(1)) / 1e4, int(m.group(2)) / 1e4, aps.get(cur)))
    return fl


def via_mask_census():
    res = {}
    for side, fn in (("top", "soldermask_top.gbr"), ("bottom", "soldermask_bottom.gbr")):
        p = os.path.join(GBR_DIR, fn)
        if not os.path.exists(p):
            res[side] = None
            continue
        fl = gerber_flashes(p)
        idx = {}
        for (x, y, ap) in fl:
            idx.setdefault((round(x, 2), round(y, 2)), []).append(ap)
        hit, apsz = 0, {}
        for v in VIAS:
            k = (round(v["x"], 2), round(v["y"], 2))
            if k in idx:
                hit += 1
                for ap in idx[k]:
                    apsz[str(ap)] = apsz.get(str(ap), 0) + 1
        res[side] = dict(vias=len(VIAS), with_opening=hit, apertures=apsz)
    return res


MASK = None


AREA_PREC = 0.3       # BASIS section 11 B6: per-net copper areas are stated to +-0.3 mm2 (raster bias)


def sec_c(grid_res=0.02):
    global MASK
    head("H.23(c) MB content under each tab (parts, layer-1 copper by net with areas, vias)")
    MASK = via_mask_census()
    res = {}
    for tname, rect, region in (("tab X", TAB_X, TAB_X_POLY), ("tab Y", TAB_Y, TAB_Y_POLY)):
        G = Grid(rect[0], rect[1], rect[2], rect[3], grid_res)
        reg = G.new()
        G.mark_poly(reg, region, 0.0)
        a_reg = count(reg) * G.cell
        parts = [p["name"] for p in PARTS if rect_overlap(p["bbox"], rect)]
        nets = {}
        netmask = {}
        for s in NONGND:
            sb = eff(s)["bb"]
            if rect_dist(sb, rect) > eff(s)["r"]:
                continue
            m = G.new()
            G.mark_shape(m, s, 0.0)
            mi = mask_and(m, reg)
            a = count(mi) * G.cell
            if a <= 0:
                continue
            # per-net copper area = the UNION of the net's shapes (overlapping traces/vias counted once)
            netmask[s["net"]] = mi if s["net"] not in netmask else mask_or(netmask[s["net"]], mi)
            L = 0.0
            if s["kind"] == "wire":
                (ax, ay), (bx, by) = s["pts"]
                n = max(2, int(math.hypot(bx - ax, by - ay) / 0.01))
                for i in range(n):
                    t = (i + 0.5) / n
                    if pip(ax + t * (bx - ax), ay + t * (by - ay), region):
                        L += math.hypot(bx - ax, by - ay) / n
            e = nets.setdefault(s["net"], dict(area=0.0, trace_len=0.0, kinds=set(), shape_sum=0.0))
            e["shape_sum"] += a
            e["trace_len"] += L
            e["kinds"].add(s["kind"])
        allm = G.new()
        for k, mk in netmask.items():
            nets[k]["area"] = count(mk) * G.cell
            allm = mask_or(allm, mk)
        a_union = count(allm) * G.cell
        vias = []
        for v in VIAS:
            r = via_dia(v) / 2
            g = 0.0 if pip(v["x"], v["y"], region) else min(dpt_seg(v["x"], v["y"], a[0], a[1], b[0], b[1])
                                                            for a, b in edges(region))
            if g - r < 0 or pip(v["x"], v["y"], region):
                vias.append((v["net"], f2(v["x"]), f2(v["y"]), "centre inside" if pip(v["x"], v["y"], region)
                             else "rim only (centre %.3f mm outside)" % g))
        out("")
        out("--- %s: region area %.2f mm2 (raster %.3f mm)" % (tname, a_reg, grid_res))
        out("  MB part boxes overlapping: %s" % (parts if parts else "none"))
        tot = a_union
        ssum = 0.0
        for k in sorted(nets):
            e = nets[k]
            ssum += e["area"]
            out("  net %-14s copper rim area inside %6.2f +- %.1f mm2 (union of the net's shapes; per-shape sum %.2f); "
                "trace length inside %5.1f mm; %s" % (k, e["area"], AREA_PREC, e["shape_sum"], e["trace_len"],
                                                       "/".join(sorted(e["kinds"]))))
        out("  non-GND copper under the tab: %.2f mm2 = the union over all non-GND nets (sum of the per-net unions "
            "%.2f mm2; the difference is copper shared by two nets, expected 0); each net's area is the union of its "
            "traces, vias and pads (cells counted once). The rest is the board-wide GND pour (isolation gaps not "
            "modelled)" % (tot, ssum))
        if nets:
            out("  precision (BASIS section 11 B6): each per-net area is stated to +-%.1f mm2 (raster bias of the %.3f mm "
                "cell-centre count along the copper edges: about half a cell times the edge length, e.g. 0.01 mm x "
                "~35 mm of edge for a 17 mm trace); the per-net digits above are the raster result, not its accuracy"
                % (AREA_PREC, grid_res))
        out("  vias whose pad overlaps the tab (%d): %s" % (len(vias), vias))
        ng = [v for v in vias if v[0] != "GND"]
        out("  of which non-GND: %d %s" % (len(ng), ng))
        res[tname] = dict(area=a_reg, parts=parts, nets={k: dict(area=f2(v["area"]), area_prec=AREA_PREC,
                                                                 trace_len=f2(v["trace_len"]))
                                                            for k, v in nets.items()}, non_gnd_area=tot, vias=vias)
    head("H.23(c2) MB via stop-mask census (GBR soldermask_top.gbr / soldermask_bottom.gbr against the BRD vias)")
    al = sum(1 for v in VIAS if v["alwaysstop"] == "yes")
    out("BRD: %d vias, drill %s mm, pad %s mm; %d of them carry alwaysstop=\"yes\" (Eagle: stop mask regardless of "
        "mlViaStopLimit %s)" % (len(VIAS), sorted(VIA_DRILL_SET), VIA_D, al, DR.get("mlViaStopLimit")))
    for side in ("top", "bottom"):
        c = MASK.get(side)
        if c is None:
            out("  %s: Gerber not found" % side)
        else:
            out("  %s stop mask: %d of %d vias have a flash at the via centre; apertures %s"
                % (side, c["with_opening"], c["vias"], c["apertures"]))
    out("Finding: the MB vias are NOT tented. round4/work/mb_mechanical.md 4.1 ('all tented', from mlViaStopLimit) and "
        "DOC A.7 ('16 tented GND vias') read only the design rule; the per-via alwaysstop flag overrides it and the fab "
        "Gerber shows an opening at every via. Under the CR the exposed via rings are covered by the polyimide sheet "
        "(kept, BASIS D4); the bottom clearance rule already keeps 1.0 mm from every non-GND via rim.")
    RJ["c"] = res
    RJ["c2"] = dict(mask=MASK, alwaysstop=al, via_pad_mm=VIA_D)
    summ("MB vias tented?", "no: %d/%d vias have a top stop-mask opening (%.4f mm) in soldermask_top.gbr"
         % (MASK["top"]["with_opening"], MASK["top"]["vias"], 2 * VIA_R + 2 * STOPFRAME), "H.23(c2)")
    for t in res:
        summ("non-GND MB copper under %s" % t, "%.2f mm2 (%s; per-net areas +-%.1f mm2, raster bias); %d vias (%d "
             "non-GND)" % (res[t]["non_gnd_area"], ", ".join(sorted(res[t]["nets"])) or "none", AREA_PREC,
                           len(res[t]["vias"]), len([v for v in res[t]["vias"] if v[0] != "GND"])), "H.23(c)")
    return res


# ======================================================================================================================
# H.23(i, part 1) foot spots (needed by H.23(d))
# ======================================================================================================================
FOOT = 4.0          # BASIS D3: 4 x 4 mm foot body
FOOT_CU = 1.0       # BASIS D3: no non-GND MB copper rim within 1.0 mm of the foot body
FOOT_KO = 0.5       # bottom keep-out margin around the foot body (A.7 courtyard convention; ASSUMPTION)


NEAR_FOOT = [s for s in NONGND if rect_dist(s["bb"], (TAB_X[0] - 5, TAB_Y[1] - 15, TAB_X[2] + 5, TAB_Y[3] + 5)) < 1.0
             or rect_dist(s["bb"], (TAB_Y[0] - 5, TAB_Y[1] - 5, TAB_Y[2] + 5, TAB_Y[3] + 5)) < 1.0]
VIAS_NEAR = [v for v in VIAS if rect_dist((v["x"], v["y"], v["x"], v["y"]),
                                          (TAB_Y[0] - 5, TAB_X[1] - 5, TAB_X[2] + 5, TAB_Y[3] + 5)) < 1.0]


def foot_eval(cx, cy, w=FOOT, h=FOOT):
    body = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    reg = rpoly(body)
    via_under = []
    for v in VIAS_NEAR:
        r = via_dia(v) / 2
        d = rect_dist((v["x"], v["y"], v["x"], v["y"]), body)
        if d < r:
            via_under.append((v["net"], f2(v["x"]), f2(v["y"])))
    cmin, cwho = 1e9, None
    for s in NEAR_FOOT:
        if rect_dist(s["bb"], body) > s["r"] + 3.0:
            continue
        c = clearance(s, reg)
        if c < cmin:
            cmin, cwho = c, s["label"]
    pmin, pwho = 1e9, None
    for p in PARTS:
        d = rect_dist(p["bbox"], body)
        if d < pmin:
            pmin, pwho = d, p["name"]
    return dict(centre=(cx, cy), body=body, vias=via_under, cu_clear=cmin, cu_who=cwho, part_clear=pmin, part=pwho,
                w=w, h=h)


FEET = None
TIP_X = 60.0         # tip zone: centre x >= 60.0 (lever >= 14.0 mm from the x 45.998 pin column, 74 % of the tab length)
# ---- BASIS section 10 A1: foot size and position by placement tolerance -------------------------------------------
FOOT_WS = [round(3.0 + 0.1 * k, 1) for k in range(11)]       # body width (x) 3.0-4.0 mm, 0.1 mm steps (A1)
FOOT_HS = [round(1.4 + 0.1 * k, 1) for k in range(27)]       # body height (y) 1.4-4.0 mm, 0.1 mm steps (A1)
TOL_REQ = 0.25       # A1: placement tolerance >= +-0.25 mm in x and in y against the full D3 rule
FRES = 0.02          # raster / centre grid, mm (A1: centres on a 0.02 mm grid)
FOOT_TAB = {"FT1": dict(rect=TAB_X, lim=(0, TAB_X[0]), tab="tab X",
                        lim_txt="body inside the tab X rectangle (x >= 48.70; the tab root is interior)"),
            "FT2": dict(rect=TAB_Y, lim=(1, TAB_Y[1]), tab="tab Y",
                        lim_txt="body inside the tab Y rectangle (y >= 67.14; the tab root is interior)")}
OLD_FT1 = (62.00, 66.70, 4.0, 2.0)     # r7 first run FT1 (4.0 x 2.0 mm), kept as a labelled alternative
OLD_FT2 = (27.63, 73.50, 4.0, 4.0)     # r7 first run FT2 (4 x 4 mm at the far edge), kept as a labelled alternative
RELAX44 = (62.50, 61.40, 4.0, 4.0)     # relaxed 4 x 4 mm FT1 spot over masked signal traces (operator option only)


def d_rect_pt(R, x, y):
    dx = max(R[0] - x, x - R[2], 0.0)
    dy = max(R[1] - y, y - R[3], 0.0)
    return math.hypot(dx, dy)


def _in_rect(R, p):
    return R[0] < p[0] < R[2] and R[1] < p[1] < R[3]


def d_rect_seg(R, a, b):
    """Exact plan distance between an axis-aligned rectangle and a segment (0 if they meet)."""
    if _in_rect(R, a) or _in_rect(R, b):
        return 0.0
    c = rpoly(R)
    for e0, e1 in edges(c):
        if seg_x(a, b, e0, e1):
            return 0.0
    return min(d_rect_pt(R, a[0], a[1]), d_rect_pt(R, b[0], b[1]),
               min(dpt_seg(q[0], q[1], a[0], a[1], b[0], b[1]) for q in c))


def d_rect_shape(R, s):
    """Exact rim clearance between a rectangle and a copper shape (square CHG pads as squares)."""
    s = eff(s)
    k = s["kind"]
    if k in ("box", "sqpad"):
        return rect_dist(R, (s["pts"][0][0], s["pts"][0][1], s["pts"][2][0], s["pts"][2][1])) - s["r"]
    if k in ("via", "pad"):
        c = s["pts"][0]
        return d_rect_pt(R, c[0], c[1]) - s["r"]
    if k == "poly":
        pts = s["pts"]
        if rect_dist(R, s["bb"]) - s["r"] > 50.0:
            return 1e9
        if any(_in_rect(R, p) for p in pts) or any(pip(q[0], q[1], pts) for q in rpoly(R)):
            return -s["r"]
        return min(d_rect_seg(R, a, b) for a, b in edges(pts)) - s["r"]
    return min(d_rect_seg(R, a, b) for a, b in shape_segs(s)) - s["r"]


def foot_feats(rect, m=FOOT_CU + 1.0):
    """Features that can bind a foot body inside the tab rectangle (the body never leaves the rectangle)."""
    big = (rect[0] - m, rect[1] - m, rect[2] + m, rect[3] + m)
    cu = [s for s in NONGND if rect_dist(eff(s)["bb"], big) <= eff(s)["r"] + 1e-9]
    parts = [p for p in PARTS if rect_dist(p["bbox"], big) <= 1e-9]
    vias = [(v["x"], v["y"], via_dia(v) / 2, v["net"]) for v in VIAS if d_rect_pt(big, v["x"], v["y"]) <= 1.0]
    return cu, parts, vias


def foot_margin(R, ff, lim, who=False):
    """Smallest margin of body rectangle R against the full BASIS D3 rule (>= 0: the rule is met):
    body >= 0.5 mm inside the r7 outline and inside the tab rectangle; no MB via pad (any net) under the body;
    every non-GND MB layer-1 copper rim >= 1.0 mm; every MB part box >= 1.0 mm. who=False returns at the first
    violation (sign only)."""
    best, bw = 1e9, None
    if not all(pip(q[0], q[1], OUTLINE) for q in rpoly(R)):
        return -1.0, "outside the r7 outline"
    d = R[lim[0]] - lim[1]
    if d < best:
        best, bw = d, "tab root line"
        if best < 0 and not who:
            return best, bw
    for (a, b) in edges(OUTLINE):
        d = d_rect_seg(R, a, b) - CY
        if d < best:
            best, bw = d, "r7 outline edge (0.5 mm)"
            if best < 0 and not who:
                return best, bw
    cu, parts, vias = ff
    for (x, y, r, net) in vias:
        d = d_rect_pt(R, x, y) - r
        if d < best:
            best, bw = d, "%s via pad (%.3f,%.3f) under the body" % (net, x, y)
            if best < 0 and not who:
                return best, bw
    for p in parts:
        d = rect_dist(R, p["bbox"]) - FOOT_CU
        if d < best:
            best, bw = d, "%s part box (1.0 mm)" % p["name"]
            if best < 0 and not who:
                return best, bw
    for s in cu:
        d = d_rect_shape(R, s) - FOOT_CU
        if d < best:
            best, bw = d, "%s (1.0 mm)" % s["label"]
            if best < 0 and not who:
                return best, bw
    return best, bw


def _grown(c, w, h, tx, ty):
    return (c[0] - w / 2 - tx, c[1] - h / 2 - ty, c[0] + w / 2 + tx, c[1] + h / 2 + ty)


def _bis(ok, lo, hi, n=16):
    """Largest v in [lo, hi] with ok(v) True, given ok(lo) True and ok monotone (True below, False above)."""
    if ok(hi):
        return hi
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def tbox_exact(c, w, h, ff, lim, n=16):
    """Placement tolerance t: the body moved by any (dx, dy) in [-t, t] x [-t, t] meets the rule. The union of the
    moved bodies is the body grown by t on every side, so t = the largest growth that still meets the rule.
    Negative t = the body itself fails (|t| = the shrink needed)."""
    def ok(t):
        return foot_margin(_grown(c, w, h, t, t), ff, lim)[0] >= 0.0
    lo = -min(w, h) / 2 + 0.05
    if not ok(lo):
        return lo
    return _bis(ok, lo, 4.5, n)


def gold_y(c, w, h, ff, lim, half=0.05, n=40):
    """Exact max-min centre y at a fixed centre x (BASIS section 11 B1): t(y) near the optimum is the minimum of
    distance terms that are linear in y, so a golden-section search on the continuous y (not the 0.02 mm grid) finds
    the y where the binding features below and above the grown body are equidistant. Returns (y, t)."""
    def f(y):
        return tbox_exact((c[0], y), w, h, ff, lim, n=26)
    a, b = c[1] - half, c[1] + half
    g = (math.sqrt(5.0) - 1.0) / 2.0
    y1, y2 = b - g * (b - a), a + g * (b - a)
    f1, f2v = f(y1), f(y2)
    for _ in range(n):
        if f1 < f2v:
            a, y1, f1 = y1, y2, f2v
            y2 = a + g * (b - a)
            f2v = f(y2)
        else:
            b, y2, f2v = y2, y1, f1
            y1 = b - g * (b - a)
            f1 = f(y1)
    y = 0.5 * (a + b)
    ty = f(y)
    if ty < f(c[1]) - 1e-6:          # plateau or non-concave case: keep the grid centre
        return c[1], f(c[1])
    return y, ty


def txty_exact(c, w, h, t, ff, lim):
    """tx: largest x half-range of moves while the y half-range is t (= tbox); ty likewise. min(tx, ty) = t."""
    tx = _bis(lambda v: foot_margin(_grown(c, w, h, v, t), ff, lim)[0] >= 0.0, t, 20.0)
    ty = _bis(lambda v: foot_margin(_grown(c, w, h, t, v), ff, lim)[0] >= 0.0, t, 20.0)
    return tx, ty


def side_slack(c, w, h, ff, lim):
    """One-sided slacks: how far the body can move in +x, -x, +y, -y alone and still meet the rule."""
    res = {}
    for nm, k in (("+x", 2), ("-x", 0), ("+y", 3), ("-y", 1)):
        def ok(v, k=k):
            R = list(_grown(c, w, h, 0.0, 0.0))
            R[k] += v if k >= 2 else -v
            return foot_margin(tuple(R), ff, lim)[0] >= 0.0
        res[nm] = _bis(ok, 0.0, 20.0) if ok(0.0) else None
    return res


def _snap(v):
    return round(round(v / FRES) * FRES, 2)


def foot_raster(spec, ff):
    """Raster stage: blocked cells (0.02 mm) = the rule's forbidden region for the body; per level k (half-height
    rows), the largest free symmetric half-width over all centres. Returns the per-level maxima and their cells."""
    rect, lim = spec["rect"], spec["lim"]
    G = Grid(rect[0], rect[1], rect[2], rect[3], FRES)
    blk = G.new()
    cu, parts, vias = ff
    for s in cu:
        G.mark_shape(blk, s, FOOT_CU)
    for p in parts:
        G.mark_poly(blk, p["pts"], FOOT_CU)
    for (x, y, r, net) in vias:
        G.mark_disk(blk, x, y, r)
    ins = region_masks(G, OUTLINE, CY)
    blk = bytearray(1 if (b or not i) else 0 for b, i in zip(blk, ins))
    nx, ny = G.nx, G.ny
    M = []
    for j in range(ny):
        row = blk[j * nx:(j + 1) * nx]
        d = [0] * nx
        last = -1
        for i in range(nx):
            if row[i]:
                last = i
            d[i] = i - last
        nxt = nx
        for i in range(nx - 1, -1, -1):
            if row[i]:
                nxt = i
            v = nxt - i
            if v < d[i]:
                d[i] = v
        M.append(d)
    itip = max(0, int(math.ceil((TIP_X - G.x0) / FRES - 0.5 - 1e-9))) if spec["tab"] == "tab X" else None
    xmid = 0.5 * (rect[0] + rect[2])
    Z = [0] * nx
    levels = []
    lev = M
    k = 0
    while True:
        gm, cell, gmt, cellt = 0, None, 0, None
        for j, row in enumerate(lev):
            m = max(row)
            if m > 0 and m >= gm:
                # ties: largest x for FT1 (tip side), nearest the tab mid-x for FT2
                if spec["tab"] == "tab X":
                    i = nx - 1 - row[::-1].index(m)
                else:
                    i = min((ii for ii in range(nx) if row[ii] == m), key=lambda ii: abs(G.cx(ii) - xmid))
                if m > gm or cell is None or (spec["tab"] == "tab X" and i > cell[0]):
                    gm, cell = m, (i, j)
            if itip is not None:
                rt = row[itip:]
                mt = max(rt) if rt else 0
                if mt > 0 and mt >= gmt:
                    i = itip + len(rt) - 1 - rt[::-1].index(mt)
                    if mt > gmt or cellt is None or i > cellt[0]:
                        gmt, cellt = mt, (i, j)
        levels.append((k, gm, cell, gmt, cellt))
        if gm == 0:
            break
        if k == 0:
            nl = [list(map(min, lev[j - 1] if j > 0 else Z, lev[j], lev[j + 1] if j < ny - 1 else Z))
                  for j in range(ny)]
        else:
            nl = [list(map(min, lev[j - 1] if j > 0 else Z, lev[j + 1] if j < ny - 1 else Z)) for j in range(ny)]
        lev = nl
        k += 1
    return G, levels


def raster_t(G, levels, w, h, tip=False):
    """Raster estimate of the best tolerance t for a w x h body: free half-height (k + 0.5) res at level k, free
    half-width (G - 0.5) res (half-cell convention; error about +-0.01-0.02 mm). Returns (t, centre)."""
    best = (-9.0, None)
    for (k, gm, cell, gmt, cellt) in levels:
        g, c = (gmt, cellt) if tip else (gm, cell)
        if not g or c is None:
            continue
        t = min((k + 0.5) * FRES - h / 2, (g - 0.5) * FRES - w / 2)
        if t > best[0] + 1e-12:
            best = (t, (G.cx(c[0]), G.cy(c[1])))
    return best


def refine_foot(c0, w, h, ff, lim, tie, xmin=None):
    """Exact stage: hill-climb on the 0.02 mm centre grid to the largest exact t, then resolve a plateau of equal t
    along x (tie rule) and along y (centred)."""
    cache = {}

    def f(p):
        if xmin is not None and p[0] < xmin - 1e-9:
            return -9.0
        if p not in cache:
            cache[p] = tbox_exact(p, w, h, ff, lim)
        return cache[p]
    c = (_snap(c0[0]), _snap(c0[1]))
    if xmin is not None and c[0] < xmin:
        c = (_snap(xmin + FRES / 2), c[1])
    t = f(c)
    for step in (0.32, 0.16, 0.08, 0.04, 0.02):
        moved = True
        while moved:
            moved = False
            for dx in (-step, 0.0, step):
                for dy in (-step, 0.0, step):
                    if dx == 0.0 and dy == 0.0:
                        continue
                    p = (_snap(c[0] + dx), _snap(c[1] + dy))
                    tp = f(p)
                    if tp > t + 1e-5:
                        c, t, moved = p, tp, True
    if t < -1.0:
        return dict(c=c, t=t)
    eps = 2e-4

    def ends(axis):
        lo_e = []
        for sgn in (1, -1):
            a, b = 0.0, 0.02
            # expand until the plateau ends (t drops), then bisect
            while b < 25.0:
                p = (_snap(c[0] + sgn * b), c[1]) if axis == 0 else (c[0], _snap(c[1] + sgn * b))
                if f(p) < t - eps:
                    break
                a, b = b, b * 2
            for _ in range(10):
                mval = _snap(0.5 * (a + b)) if b - a > 2 * FRES else None
                if mval is None or mval <= a or mval >= b:
                    break
                p = (_snap(c[0] + sgn * mval), c[1]) if axis == 0 else (c[0], _snap(c[1] + sgn * mval))
                if f(p) >= t - eps:
                    a = mval
                else:
                    b = mval
            lo_e.append(a)
        return lo_e[1], lo_e[0]          # extent below, extent above the current centre
    dn, up = ends(0)
    if tie == "maxx":
        c = (_snap(c[0] + up), c[1])
    else:
        c = (_snap(c[0] + (up - dn) / 2), c[1])
    dn, up = ends(1)
    c = (c[0], _snap(c[1] + (up - dn) / 2))
    # BASIS section 11 B1: the exact max-min centre y (continuous), not the 0.02 mm grid centre
    yx, tx_ = gold_y(c, w, h, ff, lim)
    # the larger t can shorten the x plateau: with the 'maxx' tie, step back in x while that raises t (the plateau end
    # at the exact y), then re-centre y
    cx = c[0]
    while tie == "maxx":
        if xmin is not None and cx - FRES < xmin - 1e-9:
            break
        yb, tb = gold_y((_snap(cx - FRES), c[1]), w, h, ff, lim)
        if tb <= tx_ + 1e-5:
            break
        cx, yx, tx_ = _snap(cx - FRES), yb, tb
    return dict(c=(cx, yx), t=tx_, c_grid=c, t_grid=f(c))


def foot_search(nm):
    """A1: for every body size, the centre that maximises min(tx, ty) and its tolerances; adopted = the largest bed
    area with tx, ty >= 0.25 mm (ties: larger centre x for FT1, centred for FT2)."""
    spec = FOOT_TAB[nm]
    ff = foot_feats(spec["rect"])
    lim = spec["lim"]
    G, levels = foot_raster(spec, ff)
    tip = nm == "FT1"
    table = {}
    for h in FOOT_HS:
        for w in FOOT_WS:
            t, c = raster_t(G, levels, w, h)
            tt, ct = raster_t(G, levels, w, h, tip=True) if tip else (None, None)
            table[(w, h)] = dict(t=t, c=c, t_tip=tt, c_tip=ct)
    tie = "maxx" if nm == "FT1" else "mid"
    order = sorted(table, key=lambda s: (-round(s[0] * s[1], 4), -s[0]))
    exact = {}
    adopted, a_area = None, None
    for s in order:
        area = round(s[0] * s[1], 4)
        if a_area is not None and area < a_area - 1e-9:
            break
        r = table[s]
        if r["t"] < TOL_REQ - 0.05 and not (tip and r["t_tip"] is not None and r["t_tip"] >= TOL_REQ - 0.05):
            continue
        w, h = s
        ex = refine_foot(r["c"], w, h, ff, lim, tie)
        ext = None
        if tip:
            if ex["c"][0] >= TIP_X:
                ext = ex
            elif r["t_tip"] is not None and r["c_tip"] is not None and r["t_tip"] > -1.0:
                ext = refine_foot(r["c_tip"], w, h, ff, lim, tie, xmin=TIP_X)
        e = dict(w=w, h=h, area=area, best=ex, tip=ext)
        exact[s] = e
        pick = ext if (ext is not None and ext["t"] >= TOL_REQ) else ex
        if pick["t"] >= TOL_REQ:
            e["pick"] = pick
            if adopted is None:
                adopted, a_area = e, area
            else:
                key_new = (pick["c"][0], w) if tip else (-abs(pick["c"][0] - 0.5 * (spec["rect"][0] +
                                                                                     spec["rect"][2])), w)
                p0 = adopted["pick"]
                key_old = (p0["c"][0], adopted["w"]) if tip else (-abs(p0["c"][0] - 0.5 * (spec["rect"][0] +
                                                                                          spec["rect"][2])),
                                                                     adopted["w"])
                if key_new > key_old:
                    adopted = e
    note = None
    if adopted is None:
        # A1 fallback: no size reaches 0.25 mm in both axes -> the size with the largest min(tx, ty)
        s = max(table, key=lambda z: (table[z]["t"], z[0] * z[1]))
        ex = refine_foot(table[s]["c"], s[0], s[1], ff, lim, tie)
        adopted = dict(w=s[0], h=s[1], area=round(s[0] * s[1], 4), best=ex, tip=None, pick=ex)
        exact[s] = adopted
        note = "no size reaches %.2f mm in both axes; adopted the size with the largest min(tx, ty)" % TOL_REQ
    for e in exact.values():
        for key in ("best", "tip", "pick"):
            p = e.get(key)
            if p is not None and "tx" not in p:
                p["tx"], p["ty"] = txty_exact(p["c"], e["w"], e["h"], p["t"], ff, lim)
                p["bind"] = foot_margin(_grown(p["c"], e["w"], e["h"], p["t"] + 1e-3, p["t"] + 1e-3), ff, lim,
                                        who=True)[1]
    pk = adopted["pick"]
    fe = foot_eval(pk["c"][0], pk["c"][1], adopted["w"], adopted["h"])
    fe.update(c_grid=pk.get("c_grid", pk["c"]), t_grid=pk.get("t_grid", pk["t"]))
    fe.update(t=pk["t"], tx=pk["tx"], ty=pk["ty"], bind=pk["bind"], zone=("tip zone (x >= %.1f)" % TIP_X if
                                                                          pk["c"][0] >= TIP_X else
                                                                          "root side (x < %.1f)" % TIP_X)
              if tip else "-", note=note, area=adopted["area"])
    return dict(table=table, exact=exact, adopted=fe, ff=ff, lim=lim, G=G)


def foot_alt(nm, spec_t):
    """Tolerances of a fixed foot (the first-run spots and the relaxed 4 x 4 spot)."""
    F = FOOT_TAB[nm]
    ff = foot_feats(F["rect"])
    cx, cy, w, h = spec_t
    fe = foot_eval(cx, cy, w, h)
    m, who = foot_margin(_grown((cx, cy), w, h, 0.0, 0.0), ff, F["lim"], who=True)
    fe["rule_margin"], fe["rule_who"] = m, who
    if m >= 0.0:
        t = tbox_exact((cx, cy), w, h, ff, F["lim"])
        tx, ty = txty_exact((cx, cy), w, h, t, ff, F["lim"])
        fe.update(t=t, tx=tx, ty=ty, slack=side_slack((cx, cy), w, h, ff, F["lim"]))
    else:
        fe.update(t=None, tx=None, ty=None, slack=None)
    return fe


PIN11_Y = 64.484      # DOC A.8: the 1x12 column pin 11 row (tab Y cantilever clamp line, mb_pinload.py)
FILL_D = 1.0          # BASIS section 11 B2: FT2 RTV fill hole, 1.0 mm NPTH through tab Y at the foot centre
FILL_KO = 0.5         # BASIS section 11 B2: CR-top copper and part keep-out ring around the fill hole (0.5 mm)


def foot_far(nm, mm):
    """BASIS section 11 B2: the body of the max-min result moved along +y (away from the pin-11 row) to the largest y
    whose exact placement tolerance is still >= TOL_REQ; centre x held at the max-min centre x. y on a 0.001 mm grid
    (round half to nearest; accepted when t >= TOL_REQ - 1e-6, the bisection resolution)."""
    F = FOOT_TAB[nm]
    ff = foot_feats(F["rect"])
    lim = F["lim"]
    w, h = mm["w"], mm["h"]
    x = mm["centre"][0]

    def tb(y):
        return tbox_exact((x, y), w, h, ff, lim, n=26)
    y = _bis(lambda v: tb(v) >= TOL_REQ, mm["centre"][1], F["rect"][3] - h / 2, n=34)
    y = round(y, 3)
    while tb(y) < TOL_REQ - 1e-6:
        y = round(y - 0.001, 3)
    fe = foot_eval(x, y, w, h)
    t = tb(y)
    tx, ty = txty_exact((x, y), w, h, t, ff, lim)
    bind = foot_margin(_grown((x, y), w, h, t + 1e-3, t + 1e-3), ff, lim, who=True)[1]
    fe.update(t=t, tx=tx, ty=ty, bind=bind, zone="-", note=None, area=round(w * h, 4),
              slack=side_slack((x, y), w, h, ff, lim))
    return fe


def scan_tab_x(w, h, step=0.1):
    x0, x1 = TAB_X[0] + w / 2, TAB_X[2] - CY - w / 2
    y0, y1 = TAB_X[1] + CY + h / 2, TAB_X[3] - CY - h / 2
    out_ = []
    nx = int(math.floor((x1 - x0) / step + 1e-9))
    ny = int(math.floor((y1 - y0) / step + 1e-9))
    for i in range(nx + 1):
        for j in range(ny + 1):
            out_.append(foot_eval(round(x0 + i * step, 3), round(y0 + j * step, 3), w, h))
    return out_


def find_feet():
    global FEET
    if FEET is not None:
        return FEET
    # 1. the BASIS D3 size (4 x 4) over the whole of tab X, by copper-clearance threshold
    cand = scan_tab_x(FOOT, FOOT)
    feas = {}
    for thr in (1.0, 0.75, 0.5, 0.25, 0.0):
        feas[thr] = [c for c in cand if not c["vias"] and c["cu_clear"] >= thr]
    tip = [c for c in cand if not c["vias"] and c["centre"][0] >= TIP_X]
    best_tip44 = max(tip, key=lambda c: (round(c["cu_clear"], 3), c["centre"][0])) if tip else None
    start = foot_eval(62.7, 61.26)
    # 2. BASIS section 10 A1: size and position by placement tolerance (supersedes the first-run size list)
    srch = {nm: foot_search(nm) for nm in ("FT1", "FT2")}
    ft1, ft2_mm = srch["FT1"]["adopted"], srch["FT2"]["adopted"]
    # BASIS section 11 B2: FT2 = the 4 x 4 body at the largest lever (distance from the pin-11 row y 64.484) whose
    # placement tolerance is still >= 0.25 mm; centre x = the A1 max-min centre x of tab Y
    ft2 = foot_far("FT2", ft2_mm)
    rule = ("A1 (BASIS sections 10/11 B1): the largest bed area (width 3.0-4.0 x height 1.4-4.0 mm, 0.1 mm steps) whose "
            "placement tolerance is >= +-%.2f mm in x and in y against the full D3 rule, centred at the exact max-min "
            "centre; FT1 = %.1f (x) x %.1f (y) mm, %s%s" % (TOL_REQ, ft1["w"], ft1["h"], ft1["zone"],
                                                            ("; " + ft1["note"]) if ft1.get("note") else ""))
    rule2 = ("BASIS section 11 B2 (A1 restated for FT2): the largest lever (distance from the pin-11 row y %.3f) subject "
             "to t >= %.2f mm; FT2 = %.1f (x) x %.1f (y) mm at centre x %.2f (the A1 max-min centre x of tab Y)"
             % (PIN11_Y, TOL_REQ, ft2["w"], ft2["h"], ft2["centre"][0]))
    alts = dict(old_ft1=foot_alt("FT1", OLD_FT1), relax44=foot_alt("FT1", RELAX44), old_ft2=foot_alt("FT2", OLD_FT2),
                ft2_mid=foot_alt("FT2", (ft2_mm["centre"][0], ft2_mm["centre"][1], ft2_mm["w"], ft2_mm["h"])))
    FEET = dict(ft1=ft1, ft2=ft2, ft2_mm=ft2_mm, rule=rule, rule2=rule2, feas={k: len(v) for k, v in feas.items()},
                feas_maxx={k: (max(v, key=lambda c: c["centre"][0])["centre"] if v else None) for k, v in feas.items()},
                start=start, best_tip44=best_tip44, ncand=len(cand), search=srch, alts=alts)
    return FEET


def foot_keepouts():
    F = find_feet()
    ko = []
    for name, f, tab in (("FT1", F["ft1"], TAB_X), ("FT2", F["ft2"], TAB_Y)):
        b = f["body"]
        k = (b[0] - FOOT_KO, b[1] - FOOT_KO, b[2] + FOOT_KO, b[3] + FOOT_KO)
        # RTV access lane from the keep-out to the nearest free tab edge (syringe from the tab edge, BASIS D3;
        # ASSUMPTION: lane width = keep-out width)
        opts = [(tab[2] - k[2], (k[2], k[1], tab[2], k[3])), (tab[3] - k[3], (k[0], k[3], k[2], tab[3]))]
        if name == "FT1":
            opts.append((k[1] - tab[1], (k[0], tab[1], k[2], k[1])))
        else:
            opts.append((k[0] - tab[0], (tab[0], k[1], k[0], k[3])))
        dmin, lane = min(opts, key=lambda o: o[0])
        if name == "FT2":
            # BASIS section 11 B2: FT2 is bedded through the fill hole at the foot centre; its keep-out has no edge
            # lane (the +y lane would lie behind the L-FC body)
            lane = None
        ko.append((name, k, lane if dmin > 1e-9 else None))
    return ko


def fill_hole():
    """BASIS section 11 B2: the FT2 fill hole (centre, diameter) and its CR-top keep-out disc."""
    c = find_feet()["ft2"]["centre"]
    return dict(c=c, d=FILL_D, ko_r=FILL_D / 2 + FILL_KO)


# ======================================================================================================================
# H.23(d)(e) bottom clearance rule area and the area booking
# ======================================================================================================================
GRID = Grid(17.70, 34.14, 65.00, 76.60, 0.05)
KL = (20.998 - 0.95 - 0.5, 36.544 - 0.95 - 0.5, 20.998 + 0.95 + 0.5, 64.484 + 0.95 + 0.5)   # STK 2.2 / stackup_area.py
KR = (45.998 - 0.95 - 0.5, 39.084 - 0.95 - 0.5, 45.998 + 0.95 + 0.5, 61.944 + 0.95 + 0.5)
HB_L = (20.998 - 1.27 - 0.5, 36.544 - 1.27 - 0.5, 20.998 + 1.27 + 0.5, 64.484 + 1.27 + 0.5)  # MIN footprint underside
HB_R = (45.998 - 1.27 - 0.5, 39.084 - 1.27 - 0.5, 45.998 + 1.27 + 0.5, 61.944 + 1.27 + 0.5)  # (body 2.54 ASSUMED centred)
R3_KO = (24.5, 48.5, 36.0, 53.5)                   # DOC A.7 named bottom keep-out (retired in r7)


def region_masks(G, outline, inset):
    inside = G.new()
    G.mark_poly(inside, outline, 0.0)
    marg = G.new()
    for (a, b) in edges(outline):
        G.mark_seg(marg, a, b, inset)
    return mask_and_not(inside, marg)


def part_split(G, m):
    fp = tx = ty = 0
    nx = G.nx
    for k, v in enumerate(m):
        if not v:
            continue
        x = G.x0 + (k % nx + 0.5) * G.res
        y = G.y0 + (k // nx + 0.5) * G.res
        if x > R6[2]:
            tx += 1
        elif y > R6[3]:
            ty += 1
        else:
            fp += 1
    c = G.cell
    return fp * c, tx * c, ty * c


def copper_mask(G, grow, poly_rim=True, via_r=None, include_chg_pads=True, rect_filter=None):
    m = G.new()
    xb = (G.x0 - 3, G.y0 - 3, G.x0 + G.nx * G.res + 3, G.y0 + G.ny * G.res + 3)
    for s in NONGND:
        if s["kind"] == "pad" and not include_chg_pads:
            continue
        if rect_dist(s["bb"], xb) > s["r"] + grow:
            continue
        if s["kind"] == "poly" and not poly_rim:
            G.mark_poly(m, s["pts"], grow)
            continue
        if s["kind"] == "via" and via_r is not None:
            c = s["pts"][0]
            G.mark_disk(m, c[0], c[1], via_r + grow)
            continue
        G.mark_shape(m, s, grow)
    return m


def parts_mask(G, grow, region_rect=None):
    m = G.new()
    for p in PARTS:
        b = p["bbox"]
        if region_rect is not None and not rect_overlap((b[0] - grow, b[1] - grow, b[2] + grow, b[3] + grow),
                                                        region_rect):
            continue
        G.mark_rect(m, b[0] - grow, b[1] - grow, b[2] + grow, b[3] + grow)
    return m


def fixed_bottom_excl(G):
    m = G.new()
    G.mark_rect(m, *HB_L)
    G.mark_rect(m, *HB_R)
    for (x, y, d) in W_PADS.values():
        G.mark_disk(m, x, y, d / 2 + 0.5)
    return m


AREA = {}


def sec_d():
    head("H.23(d) bottom clearance rule area on the footprint, tab X and tab Y (minus header bodies, W1-W4 pads, foot "
         "keep-outs)")
    G = GRID
    out("Raster %.2f mm over x %.2f-%.2f, y %.2f-%.2f. Courtyard region = r7 outline inset %.1f mm on the free edges "
        "(DOC A.7); the tab roots are interior. Exclusions (MIN r7_footprint_underside.py basis): header bodies 2.54 mm "
        "wide centred on the columns + 0.5 mm (ASSUMPTION, as MIN), W1-W4 pads + 0.5 mm (DOC A.8), MB part boxes + 1.0 mm "
        "and every non-GND MB layer-1 copper rim + 1.0 mm (BASIS bottom clearance rule), foot keep-outs."
        % (G.res, G.x0, G.x0 + G.nx * G.res, G.y0, G.y0 + G.ny * G.res, CY))
    fixed = fixed_bottom_excl(G)
    # ---- minimal-proposal replica (MIN numbers 383.9 / 57.0 / 177.9 = 618.9 mm2)
    reg_min = G.new()
    G.mark_rect(reg_min, 18.20, 34.64, 48.20, 66.64)
    G.mark_rect(reg_min, 48.70, 56.80, 64.50, 67.80)
    G.mark_rect(reg_min, 18.20, 67.14, 39.22, 76.01)
    r3ko = G.new()
    G.mark_rect(r3ko, *R3_KO)
    cu_min = copper_mask(G, 1.0, poly_rim=False, via_r=0.35 / 2 + 0.25, include_chg_pads=False)
    pm = parts_mask(G, 1.0)
    # MIN applied the r3 keep-out and the header/W exclusions on the footprint only
    fp_only = G.new()
    G.mark_rect(fp_only, 17.70, 34.14, 48.70, 67.14)
    ex0_fp = mask_and(mask_or(fixed, r3ko), fp_only)
    ex0 = mask_or(ex0_fp, mask_or(cu_min, pm))
    s0 = part_split(G, mask_and_not(reg_min, ex0))
    # ---- step 1: copper rims on polygons and the BRD via pad (0.7564 mm), CHG pads included
    cu_r7 = copper_mask(G, 1.0)
    ex1 = mask_or(ex0_fp, mask_or(cu_r7, pm))
    s1 = part_split(G, mask_and_not(reg_min, ex1))
    # ---- step 2: retire the named r3 keep-out rectangle (the rule covers it)
    ex2 = mask_or(mask_and(fixed, fp_only), mask_or(cu_r7, pm))
    s2 = part_split(G, mask_and_not(reg_min, ex2))
    # ---- step 3: trimmed tab Y with the relocated chamfer (still the minimal-style rectangles)
    reg3 = G.new()
    G.mark_rect(reg3, 18.20, 34.64, 48.20, 66.64)
    G.mark_rect(reg3, 48.70, 56.80, 64.50, 67.80)
    G.mark_rect(reg3, 18.20, 67.14, 37.06, 75.50)
    chm = G.new()
    G.mark_poly(chm, [(17.70, 76.00 - CHAMFER - CY * math.sqrt(2)), (17.70 + CHAMFER + CY * math.sqrt(2), 76.00),
                      (17.70, 76.00)], 0.0)
    reg3 = mask_and_not(reg3, chm)
    s3 = part_split(G, mask_and_not(reg3, ex2))
    # ---- step 4: the r7 inset region (root strips recovered; concave corners rounded by the inset)
    reg7 = region_masks(G, OUTLINE, CY)
    s4 = part_split(G, mask_and_not(reg7, ex2))
    # ---- step 5: foot keep-outs (+ RTV access lanes)
    ko = foot_keepouts()
    kom = G.new()
    for (n, k, lane) in ko:
        G.mark_rect(kom, *k)
        if lane:
            G.mark_rect(kom, *lane)
    ex5 = mask_or(ex2, kom)
    bottom = mask_and_not(reg7, ex5)
    s5 = part_split(G, bottom)
    ko_area = count(mask_and(reg7, mask_and_not(kom, ex2))) * G.cell
    rows = [("MIN replica (r6 courtyard rects, tab Y to 39.72/76.51, polygons without rim, via r 0.425, r3 keep-out)",
             s0),
            ("+ copper rims (polygon w/2, via pad %.4f mm, MB CHG pads)" % (2 * VIA_R), s1),
            ("+ named r3 keep-out x 24.5-36.0, y 48.5-53.5 retired (bottom clearance rule covers it)", s2),
            ("+ tab Y trimmed to x 37.56 / y 76.00, chamfer relocated", s3),
            ("+ r7 inset region (tab-root strips recovered)", s4),
            ("- FT1/FT2 keep-outs (body + %.1f mm), FT1 RTV lane (FT2: fill hole, no lane) = r7 bottom area" % FOOT_KO,
             s5)]
    out("")
    out("  %-104s %8s %8s %8s %8s" % ("step", "footpr.", "tab X", "tab Y", "total"))
    for lab, s in rows:
        out("  %-104s %8.1f %8.1f %8.1f %8.1f" % (lab, s[0], s[1], s[2], sum(s)))
    out("  MIN (proposal Table 7): footprint 383.9 + tab X 57.0 + tab Y 177.9 = 618.9 mm2")
    out("  foot keep-outs remove %.1f mm2 that the rule had left free; keep-outs %s"
        % (ko_area, [(n, tuple(round(v, 2) for v in k), tuple(round(v, 2) for v in lane) if lane else None)
                     for n, k, lane in ko]))
    # non-GND CHG pad contribution
    cu_nopad = copper_mask(G, 1.0, include_chg_pads=False)
    s_nopad = part_split(G, mask_and_not(reg7, mask_or(mask_or(mask_and(fixed, fp_only), mask_or(cu_nopad, pm)), kom)))
    out("  of which the 1.0 mm rule around the non-GND MB CHG header pads (outside the header-body keep-out) removes "
        "%.1f mm2" % (sum(s_nopad) - sum(s5)))
    AREA.update(dict(bottom=s5, steps=rows, reg7=reg7, fixed=fixed, ex=ex5, ko=ko))
    RJ["d"] = dict(steps=[(lab, [f2(v) for v in s], f2(sum(s))) for lab, s in rows], bottom_split=[f2(v) for v in s5],
                   bottom_total=f2(sum(s5)), foot_keepouts=[(n, k, lane) for n, k, lane in ko])
    summ("bottom clearance rule area (r7)", "%.1f mm2 = footprint %.1f + tab X %.1f + tab Y %.1f (MIN 618.9)"
         % (sum(s5), s5[0], s5[1], s5[2]), "H.23(d)")
    return s5


# Area booking inputs (STK section 3 / stackup_area_out.txt): demand 1128 + 60 pours = 1188 mm2; DNP 87; r3 bottom set
# 435.25 mm2 = stackup_area.py bot_r3 unrounded (BASIS section 11 B6; stackup_area_out.txt prints it as 435).
DEMAND_ALL, DNP_AREA, R3_BOTTOM = 1188.0, 87.0, 435.25
FORBIDDEN = 19.3                                   # MIN 5.2: R106, R134, R145, R146, C105 footprints
CY_0805, CY_0603, CY_1206 = 3.4 * 1.8, 3.0 * 1.45, 4.75 * 2.3     # DOC A.8 courtyards
# r7 allocation: parts that move from the r3 bottom set to the top (BASIS D5/D6). DOC B.2 networks; packages per
# stackup_area.py (R109/R111/R114 0805, the rest 0603); side in r3 = bottom (stackup_area.py default).
MOVE_CORE = {"R109": "0805", "R110": "0603", "R111": "0805", "R112": "0603", "R114": "0805", "R115": "0603",
             "C106": "0603", "C107": "0603", "C108": "0603", "C140": "0603"}
MOVE_EXT = {"R141": "0603", "R142": "0603", "R117": "0603", "R118": "0603", "C109": "0603", "R184": "0603",
            "R185": "0603", "C130": "0603", "R188": "0603", "R189": "0603", "R190": "0603", "R191": "0603"}
MOVE_R175 = {"R175": "1206"}
# BASIS section 10 A3 (adopted): R175 and the six 0.1 % divider resistors move to the top; C106-C108, C140 stay bottom
MOVE_ADOPT = {"R175": "1206", "R109": "0805", "R110": "0603", "R111": "0805", "R112": "0603", "R114": "0805",
              "R115": "0603"}
U_TARGET = 0.75


def booked(d):
    return sum({"0805": CY_0805, "0603": CY_0603, "1206": CY_1206}[v] for v in d.values())


def sec_e():
    head("H.23(e) area booking on the strict basis of stackup_area.md (top usable, top U, bottom U, single-sided U)")
    G = GRID
    reg7 = AREA["reg7"]
    # top usable: inset region minus the two column keep-outs (pads 1.9 mm + 0.5 mm, STK 2.2), the dead strips that no
    # courtyard fits (left of the 1x12 column over its length; right of the 1x10 column below tab X) and the chamfer
    # clearance (nothing within 1.5 mm of the chamfer corner, DOC A.7 rule moved with the chamfer)
    tk = G.new()
    G.mark_rect(tk, *KL)
    G.mark_rect(tk, *KR)
    G.mark_rect(tk, 18.20, 34.64, KL[0], KL[3])                    # left dead strip x 18.20-19.548, to the kL top
    G.mark_rect(tk, KR[2], 37.634, 48.20, TAB_X[1])               # right dead strip x 47.448-48.20, below tab X
    G.mark_disk(tk, 17.70, 76.00, 1.5)
    top_nofill = sum(part_split(G, mask_and_not(reg7, tk)))
    # BASIS section 11 B2: the CR-top copper and part keep-out disc around the FT2 fill hole (hole + 0.5 mm ring)
    fh = fill_hole()
    G.mark_disk(tk, fh["c"][0], fh["c"][1], fh["ko_r"])
    top = mask_and_not(reg7, tk)
    AREA["top"] = top
    ts = part_split(G, top)
    top_tot = sum(ts)
    fill_top = top_nofill - top_tot
    # r6 strict check with the same raster method
    reg6 = G.new()
    G.mark_rect(reg6, 18.20, 34.64, 48.20, 66.64)
    t6 = G.new()
    G.mark_rect(t6, *KL)
    G.mark_rect(t6, *KR)
    G.mark_rect(t6, 18.20, 34.64, KL[0], 66.64)
    G.mark_rect(t6, KR[2], KR[1], 48.20, KR[3])
    G.mark_disk(t6, 17.70, 67.14, 1.5)
    top6 = count(mask_and_not(reg6, t6)) * G.cell
    out("Top usable (strict basis): r7 %.1f mm2 = footprint %.1f + tab X %.1f + tab Y %.1f; same raster method on the r6 "
        "footprint %.1f mm2 (STK 732, chamfer as a 1.5 mm disk here)" % (top_tot, ts[0], ts[1], ts[2], top6))
    out("  FT2 fill-hole keep-out (BASIS section 11 B2): %.1f mm hole + %.1f mm copper/part ring = %.1f mm disc at "
        "(%.2f, %.3f) on the CR top, booked as top area: %.2f mm2 (raster; exact pi x %.1f^2 = %.2f mm2); top usable "
        "without it %.1f mm2" % (fh["d"], FILL_KO, 2 * fh["ko_r"], fh["c"][0], fh["c"][1], fill_top, fh["ko_r"],
                                 math.pi * fh["ko_r"] ** 2, top_nofill))
    out("  MIN top usable 1096.6 mm2 (732 + tab X 173.8 + tab Y 185.9 + root strip 4.9): difference %.1f mm2"
        % (top_tot - 1096.6))
    bottom = sum(AREA["bottom"])
    mv_core, mv_ext, mv_r175 = booked(MOVE_CORE), booked(MOVE_EXT), booked(MOVE_R175)
    out("Demand (STK 3): %.0f mm2 incl. 60 mm2 of pours; r3 bottom set %.2f mm2 (stackup_area.py bot_r3, unrounded; "
        "top %.2f); DNP footprints %.0f mm2; forbidden-part footprints %.1f mm2 (MIN 5.2)"
        % (DEMAND_ALL, R3_BOTTOM, DEMAND_ALL - R3_BOTTOM, DNP_AREA,
                                                          FORBIDDEN))
    out("r7 allocation moves from the r3 bottom set to the top (BASIS D5/D6; courtyards DOC A.8, packages stackup_area.py). "
        "The comparators U102-U104, U115, U119-U121 (SOT-23-6, 10 mm2 each) are already top-side in the r3 booking "
        "(stackup_area.py side 'top'), so only their passives move; ASSUMPTION on which passives the BASIS wording "
        "covers, two readings:")
    out("  core = the 0.1 %% dividers and the comparator input filter capacitors %s = %.2f mm2"
        % (sorted(MOVE_CORE), mv_core))
    out("  extended = core + the reference / REF-3 / FCC_ON / RGN_ON dividers and tap capacitors %s = +%.2f mm2"
        % (sorted(MOVE_EXT), mv_ext))
    out("  R175 1206 (tab X top beside F07, BASIS D6; r3 bottom in stackup_area.py) = %.2f mm2" % mv_r175)
    mv_adopt = booked(MOVE_ADOPT)
    out("  r7 adopted (BASIS section 10 A3) = R175 + the six 0.1 %% divider resistors %s = %.2f mm2; C106, C107, C108, "
        "C140 stay on the bottom" % (sorted(k for k in MOVE_ADOPT if k != "R175"), mv_adopt))
    cases = [("r3 bottom set kept", 0.0), ("r7 allocation, core + R175", mv_core + mv_r175),
             ("r7 allocation, extended + R175", mv_core + mv_ext + mv_r175),
             ("r7 adopted (A3)", mv_adopt)]
    out("")
    out("  %-36s %10s %10s %10s %10s" % ("case", "top mm2", "top U", "bottom mm2", "bottom U"))
    rows = []
    for lab, mv in cases:
        tdem = DEMAND_ALL - R3_BOTTOM + mv
        bdem = R3_BOTTOM - mv
        rows.append((lab, tdem, tdem / top_tot, bdem, bdem / bottom))
        out("  %-36s %10.1f %9.1f%% %10.1f %9.1f%%" % (lab, tdem, 100 * tdem / top_tot, bdem, 100 * bdem / bottom))
    out("  (U to two decimals: %s)" % "; ".join("%s top %.2f %% / bottom %.2f %%" % (r[0], 100 * r[2], 100 * r[4])
                                                for r in rows))
    ad = rows[-1]
    ad_pass = ad[2] <= U_TARGET and ad[4] <= U_TARGET
    extra = None
    if not ad_pass:
        # smallest additional move that passes: single parts, then pairs, from the parts that stay bottom
        pool = dict((k, v) for k, v in list(MOVE_CORE.items()) + list(MOVE_EXT.items()) if k not in MOVE_ADOPT)
        cy = {"0805": CY_0805, "0603": CY_0603, "1206": CY_1206}
        best = None
        keys = sorted(pool)
        combos = [(k,) for k in keys] + [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]]
        for cmb in combos:
            add = sum(cy[pool[k]] for k in cmb)
            sign = 1.0 if ad[4] > U_TARGET else -1.0
            tdem, bdem = ad[1] + sign * add, ad[3] - sign * add
            if tdem / top_tot <= U_TARGET and bdem / bottom <= U_TARGET and (best is None or add < best[0]):
                best = (add, cmb, tdem / top_tot, bdem / bottom)
        extra = best
    out("  r7 adopted case against the <= %.0f %% target on each side (bottom area after the ADOPTED foot keep-outs, "
        "%.1f mm2): top %.2f %% %s, bottom %.2f %% %s -> %s%s"
        % (100 * U_TARGET, bottom, 100 * ad[2], "pass" if ad[2] <= U_TARGET else "FAIL", 100 * ad[4],
           "pass" if ad[4] <= U_TARGET else "FAIL", "PASSES" if ad_pass else "FAILS",
           "" if ad_pass else ("; smallest additional move that passes: %s (%.2f mm2) -> top %.2f %%, bottom %.2f %%"
                               % (", ".join(extra[1]), extra[0], 100 * extra[2], 100 * extra[3]) if extra
                               else "; no single or paired move from the bottom set passes")))
    xb = ((R3_BOTTOM * top_tot) - (DEMAND_ALL - R3_BOTTOM) * bottom) / (top_tot + bottom)
    out("  balanced split (equal U both sides): move %.1f mm2 from the r3 bottom set to the top -> %.1f %% each side"
        % (xb, 100 * (DEMAND_ALL - R3_BOTTOM + xb) / top_tot))
    out("  MIN: top U 68.7 %, bottom U 70.3 % (435 of 618.9, MIN's rounded r3 bottom set); target <= 75 % each side "
        "(BASIS D6)")
    ss = [("all footprints", DEMAND_ALL), ("forbidden-part footprints deleted", DEMAND_ALL - FORBIDDEN),
          ("all DNP footprints removed", DEMAND_ALL - DNP_AREA)]
    out("Single-sided U (every part on the top):")
    for lab, d in ss:
        out("  %-36s %.1f %%  (MIN %s)" % (lab, 100 * d / top_tot, {"all footprints": "108.3",
                                                                     "forbidden-part footprints deleted": "106.6",
                                                                     "all DNP footprints removed": "100.4"}[lab]))
    tf_grid = (5 * 2.54 + 1.5 + 0.5) * (3 * 2.54 + 1.5 + 0.5)
    tf_res = (2 * 2.54 + 1.5 + 0.5) * (1.5 + 0.5) + (1.5 + 0.5) ** 2
    tf = tf_grid + tf_res
    out("Sensitivity: the r7 tap field courtyards (pad envelope + 0.25 mm) book %.1f mm2 = the 6 x 4 grid envelope "
        "%.1f mm2 (20 pads + R175 + 2 spares after A2; the envelope does not depend on the pad count) + the residual "
        "pads F08-F10 (one row) and F22 (T18, A2) %.1f mm2, against the 168.0 mm2 of STK (21 x 8 mm): %+.1f mm2 of top "
        "demand" % (tf, tf_grid, tf_res, tf - 168.0))
    RJ["e"] = dict(top_usable=f2(top_tot), top_split=[f2(v) for v in ts], top6=f2(top6), bottom=f2(bottom),
                   r3_bottom=R3_BOTTOM, fill_hole_top_keepout=f2(fill_top), top_usable_without_fill=f2(top_nofill),
                   move_core=f2(mv_core), move_ext=f2(mv_ext), move_r175=f2(mv_r175),
                   cases=[(r[0], f2(r[1]), f2(r[2]), f2(r[3]), f2(r[4])) for r in rows],
                   single_sided=[(lab, f2(d / top_tot)) for lab, d in ss], tapfield_booking=f2(tf),
                   move_adopt=f2(mv_adopt), adopted=dict(parts=MOVE_ADOPT, top_mm2=f2(ad[1]), top_U=round(100 * ad[2], 2),
                                                         bottom_mm2=f2(ad[3]), bottom_U=round(100 * ad[4], 2),
                                                         passes=ad_pass, extra=extra))
    summ("top usable (strict)", "%.1f mm2 after the FT2 fill-hole keep-out disc (%.2f mm2; %.1f without it) (MIN "
         "1096.6)" % (top_tot, fill_top, top_nofill), "H.23(e)")
    summ("bottom area used for U", "%.1f mm2 (H.23(d), after the foot keep-outs)" % bottom, "H.23(e)")
    for r in rows:
        summ("top U / bottom U, %s" % r[0], "%.2f %% / %.2f %% (top %.1f / bottom %.1f mm2)"
             % (100 * r[2], 100 * r[4], r[1], r[3]), "H.23(e)")
    summ("r7 adopted allocation (A3)", "R175 + R109, R110, R111, R112, R114, R115 to the top (%.2f mm2); C106, C107, "
         "C108, C140 stay bottom: top %.2f %% (%.1f mm2), bottom %.2f %% (%.1f of %.1f mm2): %s the <= 75 %% target"
         % (mv_adopt, 100 * ad[2], ad[1], 100 * ad[4], ad[3], bottom, "PASSES" if ad_pass else "FAILS"), "H.23(e)")
    summ("balanced split", "move %.1f mm2 from the r3 bottom set to the top -> %.1f %% each side"
         % (xb, 100 * (DEMAND_ALL - R3_BOTTOM + xb) / top_tot), "H.23(e)")
    summ("single-sided U", "%.1f %% (all footprints) .. %.1f %% (DNP removed)" % (100 * ss[0][1] / top_tot,
                                                                              100 * ss[2][1] / top_tot), "H.23(e)")
    return top_tot


# ======================================================================================================================
# H.23(f) farthest outline point from the commutation-loop region
# ======================================================================================================================
LOOP = [(36.1, 52.03, 44.55, 61.55), (30.8, 62.85, 39.3, 66.64), (39.3, 61.6, 44.3, 66.6)]   # MIN loop_distance()


# ======================================================================================================================
# H.23(e2) per-region booking (r7 review 7, D-F5)
# ======================================================================================================================
# Courtyard bookings per package: stackup_area.py CY (DOC A.8 IPC-7351 nominal + 0.25 mm; R3 H.18 for the ICs)
CY_PKG = {"0402": 1.9 * 1.0, "0603": 3.0 * 1.45, "0805": 3.4 * 1.8, "1206": 4.75 * 2.3, "SOT-23-6": 10.0,
          "SSOP-8": 15.0, "SC70-6": 7.0, "SC70-5": 7.0, "SOT-23": 10.0, "SOD-323": 3.4 * 1.8}
BAND_RECT = (23.15, 35.05, 42.43, 41.63)           # BASIS D5: footprint low-y band (the freed r6 tap-field area)
J101_REG = (37.0, 42.13, 44.5, 51.53)              # DOC A.8 r5 J101 region
HIGHY = [(36.1, 52.03, 44.55, 61.55), (30.8, 62.85, 39.3, 66.64), (39.3, 61.6, 44.3, 66.6),
         (44.3, 63.40, 48.2, 66.64)]               # DOC A.8: IN strip, OUT strip, U101 courtyard, +x pocket
W67_PADS = [(27.0, 57.5), (29.0, 57.5), (31.0, 57.5), (33.0, 57.5), (35.0, 57.5)]   # DOC A.8 SMT 1.2 x 1.5 mm
REGION_GAP = 0.5                                   # DOC A.8: >= 0.5 mm between regions
ANCHOR_FP = 3.0                                    # mm square CR footprint of an RTV anchor bead / W5 spacer bead
#                                                    (ASSUMPTION; TODO(measure: PM4 dry fit))
TABY_PULLS = 0                                     # tab Y gate pull-downs / series resistors: not enumerated here
EXTRA = {}


def sec_e2():
    head("H.23(e2) per-region booking of the top side (r7 review 7, D-F5): footprint low-y band, footprint interior, "
         "tab X, tab Y; target <= 75 % per region")
    G = GRID
    top = AREA["top"]
    bottom = mask_and_not(AREA["reg7"], AREA["ex"])
    fp = G.new()
    G.mark_rect(fp, *R6)
    band = G.new()
    G.mark_rect(band, *BAND_RECT)
    other = G.new()                                   # interior exclusions (DOC A.8 regions + 0.5 mm, W pads + 0.5 mm)
    G.mark_rect(other, BAND_RECT[0] - REGION_GAP, BAND_RECT[1] - REGION_GAP, BAND_RECT[2] + REGION_GAP,
                BAND_RECT[3] + REGION_GAP)
    G.mark_rect(other, J101_REG[0] - REGION_GAP, J101_REG[1] - REGION_GAP, J101_REG[2] + REGION_GAP,
                J101_REG[3] + REGION_GAP)
    for r in HIGHY:
        G.mark_rect(other, r[0] - REGION_GAP, r[1] - REGION_GAP, r[2] + REGION_GAP, r[3] + REGION_GAP)
    for (x, y, d) in W_PADS.values():
        G.mark_disk(other, x, y, d / 2 + 0.5)
    for (x, y) in W67_PADS:
        G.mark_rect(other, x - 0.6 - 0.5, y - 0.75 - 0.5, x + 0.6 + 0.5, y + 0.75 + 0.5)
    G.mark_rect(other, 18.0, 34.0, 23.15 - REGION_GAP, 41.63 + REGION_GAP)    # beside the band, outside it (left)
    interior = mask_and_not(mask_and(top, fp), other)
    bandm = mask_and(top, band)
    tabx = G.new()
    G.mark_rect(tabx, R6[2], 0, 100, 100)
    tabxm = mask_and(top, tabx)
    taby = G.new()
    G.mark_rect(taby, 0, R6[3], R6[2], 100)
    tabym = mask_and(top, taby)
    tabyb = mask_and(bottom, taby)
    A = {"band": count(bandm) * G.cell, "interior": count(interior) * G.cell, "tab X": count(tabxm) * G.cell,
         "tab Y": count(tabym) * G.cell, "tab Y bottom": count(tabyb) * G.cell}
    out("Regions (top side, strict usable mask of H.23(e)): footprint low-y band x %.2f-%.2f, y %.2f-%.2f = %.1f mm2; "
        "footprint interior = the footprint top outside the band, the J101 region, the IN/OUT strips, the U101 "
        "courtyard and the +x pocket (each + %.1f mm), the W1-W4 pads (+ 0.5 mm) and the W6/W7 pads (+ 0.5 mm) = %.1f "
        "mm2; tab X top = %.1f mm2; tab Y top = %.1f mm2 (after the FT2 fill-hole disc); tab Y bottom (bottom clearance "
        "rule, H.23(d)) = %.1f mm2." % (BAND_RECT[0], BAND_RECT[2], BAND_RECT[1], BAND_RECT[3], A["band"], REGION_GAP,
                                        A["interior"], A["tab X"], A["tab Y"], A["tab Y bottom"]))
    cy = CY_PKG
    tf_res = (2 * PITCH + PAD + 0.5) * (PAD + 0.5) + (PAD + 0.5) ** 2      # H.23(e): F08-F10 row + F22
    # revision 4: the band is a rectangle inside the strict usable mask; its U uses the exact area (raster in brackets)
    band_exact = (BAND_RECT[2] - BAND_RECT[0]) * (BAND_RECT[3] - BAND_RECT[1])
    A["band (raster)"] = A["band"]
    A["band"] = band_exact
    # revision 4: B3 and S3 are booked as the union of their two 3 x 3 mm spots at their H.23(l) positions
    b3, s3 = WP["B3"], WP["S3"]
    ov_b3s3 = max(0.0, ANCHOR_FP - abs(b3[0] - s3[0])) * max(0.0, ANCHOR_FP - abs(b3[1] - s3[1]))
    u_b3s3 = 2 * ANCHOR_FP ** 2 - ov_b3s3
    out("  band area exact %.2f mm2 (raster %.1f mm2; U below on the exact area). B3 (%.2f, %.2f) and S3 (%.2f, %.2f) lie "
        "%.2f mm apart: their %.1f x %.1f mm spots overlap by %.2f mm2 and book %.2f mm2 as one union spot (revision 4; "
        "the r7 review-7 calc booked one 9.00 mm2 spot)"
        % (band_exact, A["band (raster)"], b3[0], b3[1], s3[0], s3[1], math.hypot(b3[0] - s3[0], b3[1] - s3[1]),
           ANCHOR_FP, ANCHOR_FP, ov_b3s3, u_b3s3))
    book = {
        "band": [("U102 H1", cy["SOT-23-6"]), ("U103 UVB", cy["SOT-23-6"]), ("U104 BT_OK", cy["SOT-23-6"]),
                 ("U115 BTB_OFF", cy["SOT-23-6"]), ("U119 FCC_OFF", cy["SOT-23-6"]), ("U120 FCC_ON", cy["SOT-23-6"]),
                 ("U121 RGN_ON", cy["SOT-23-6"]), ("residual pads F08-F10 + F22 (H.23(e) booking)", tf_res)],
        "interior": [("R109 0805 0.1 %", cy["0805"]), ("R110 0603 0.1 %", cy["0603"]), ("R111 0805 0.1 %", cy["0805"]),
                     ("R112 0603 0.1 %", cy["0603"]), ("R114 0805 0.1 %", cy["0805"]), ("R115 0603 0.1 %", cy["0603"]),
                     ("D104 BAV199", cy["SOT-23"]), ("D105 BAV199", cy["SOT-23"]), ("D106 BAV199", cy["SOT-23"]),
                     ("U123 SC70-5", cy["SC70-5"]), ("D108 BAV199", cy["SOT-23"]), ("U122 SC70-5", cy["SC70-5"]),
                     ("U111 monostable SSOP-8", cy["SSOP-8"]), ("U113 monostable SSOP-8", cy["SSOP-8"]),
                     ("U112 DNP SOT-23-6", cy["SOT-23-6"]), ("U117 DNP SOT-23-6", cy["SOT-23-6"]),
                     ("D101 DNP SOD-323", cy["SOD-323"]),
                     ("W trunk RTV bead B1 (H.23(l))", ANCHOR_FP ** 2), ("W5 spacer bead S1 (H.23(l))", ANCHOR_FP ** 2),
                     ("W5 spacer bead S2 (H.23(l))", ANCHOR_FP ** 2)],
        "tab X": [("20 tap pads, pad + 0.25 mm courtyard (2.0 x 2.0)", 20 * (PAD + 0.5) ** 2), ("R175 1206", cy["1206"])],
        "tab Y": [("U105 SSOP-8", cy["SSOP-8"]), ("U106 SSOP-8", cy["SSOP-8"]), ("U110 SSOP-8", cy["SSOP-8"]),
                  ("U114 SSOP-8", cy["SSOP-8"]), ("U116 SSOP-8", cy["SSOP-8"]), ("U118 SSOP-8", cy["SSOP-8"]),
                  ("U107 SC70-6", cy["SC70-6"]), ("U108 SC70-6", cy["SC70-6"]), ("U109 SC70-6", cy["SC70-6"]),
                  ("W bundle RTV bead B3 + W5 spacer S3 (union spot, H.23(l))", u_b3s3)],
        "tab Y bottom": [("decoupler %s 0603" % c, cy["0603"]) for c in ("C114", "C115", "C116", "C117", "C118", "C119",
                                                                        "C122", "C123", "C126")],
    }
    # flexible parts (r3 bottom set): to the top where the region booking passes, else directly underneath on the bottom
    # tab Y over the target: the SC70-6 gates (driven logic) move to the interior one at a time while both pass
    gates_y0 = sum(v for n, v in book["tab Y"] if n.startswith("U"))
    tabY_U108 = None
    gate_moves = []
    for g in ("U109 SC70-6", "U108 SC70-6", "U107 SC70-6"):
        if g.startswith("U108"):
            tabY_U108 = sum(v for _, v in book["tab Y"])            # U109 moved, U108 still on tab Y
        sy = sum(v for _, v in book["tab Y"])
        if sy / A["tab Y"] <= U_TARGET:
            break
        a = dict(book["tab Y"])[g]
        if (sum(v for _, v in book["interior"]) + a) / A["interior"] <= U_TARGET:
            book["tab Y"] = [z for z in book["tab Y"] if z[0] != g]
            book["interior"].append((g + " (moved from tab Y, driven logic)", a))
            gate_moves.append(g.split()[0])
    flex = [("interior", "R178 0603", cy["0603"]), ("interior", "R179 0603", cy["0603"]),
            ("interior", "C135 0603 (U123)", cy["0603"]), ("interior", "C134 0603 (U122)", cy["0603"]),
            ("interior", "C120 0603 (U111)", cy["0603"]), ("interior", "C121 0603 (U113)", cy["0603"])] + \
           [("band", "%s 0603 (%s)" % (c, u), cy["0603"]) for c, u in
            (("C110", "U102"), ("C111", "U103"), ("C112", "U104"), ("C113", "U115"), ("C131", "U119"),
             ("C132", "U120"), ("C133", "U121"))]
    # revision 4: the flexible passives stay on the bottom directly underneath their IC. Moving the ones whose region
    # would still pass (the review-7 calc did) raises the WHOLE-SIDE top booking of H.23(e) above the 75 % target.
    moved, stayed, would = [], [], []
    for reg, nm, a in flex:
        if (sum(v for _, v in book[reg]) + sum(z[2] for z in would if z[1] == reg) + a) / A[reg] <= U_TARGET:
            would.append((nm, reg, a))
        stayed.append((nm, a))
    res = {}
    for rg in ("band", "interior", "tab X", "tab Y", "tab Y bottom"):
        s = sum(v for _, v in book[rg])
        res[rg] = (s, s / A[rg])
        out("  %-13s %6.1f of %6.1f mm2 = %5.1f %% %s; parts: %s" % (rg, s, A[rg], 100 * s / A[rg],
                                                                     "pass" if s / A[rg] <= U_TARGET else "FAIL",
                                                                     ", ".join("%s %.2f" % (n, v) for n, v in book[rg])))
    gates_y1 = sum(v for n, v in book["tab Y"] if n.startswith("U"))
    out("  tab Y re-allocation: the nine LVC gates alone book %.1f mm2 = %.1f %% of tab Y top; after the move of %s to the "
        "interior (driven logic; the interior booking passes) the seven remaining gates book %.1f mm2 = %.1f %%, and "
        "with the B3/S3 union spot %.1f mm2 = %.2f %%; with U108 kept on tab Y (U109 moved only) %s"
        % (gates_y0, 100 * gates_y0 / A["tab Y"], ", ".join(gate_moves) or "none", gates_y1,
           100 * gates_y1 / A["tab Y"], res["tab Y"][0], 100 * res["tab Y"][1],
           ("%.1f mm2 = %.2f %% (FAIL)" % (tabY_U108, 100 * tabY_U108 / A["tab Y"])) if tabY_U108 else "-"))
    n_taby_g = sum(1 for n, _ in book["tab Y"] if n.startswith("U"))
    dec_top = res["tab Y"][0] + n_taby_g * cy["0603"]
    dec_top8 = (tabY_U108 + (n_taby_g + 1) * cy["0603"]) if tabY_U108 else None
    out("  sensitivity, the gate decouplers on the tab Y top instead of underneath: adopted (%d gates) %.1f mm2 = %.1f %% "
        "(FAIL)%s; the design's 97.7 %% figure is not reproduced by either case"
        % (n_taby_g, dec_top, 100 * dec_top / A["tab Y"],
           ("; with U108 kept (%d gates) %.1f mm2 = %.1f %% (FAIL)" % (n_taby_g + 1, dec_top8,
                                                                     100 * dec_top8 / A["tab Y"]))
           if dec_top8 else ""))
    mv = 0.0
    mv_all = sum(a for _, _, a in flex)
    e_top, e_tot = RJ["e"]["adopted"]["top_mm2"], RJ["e"]["top_usable"]
    out("  flexible passives (r3 bottom set) stay on the bottom directly underneath their IC: %s. Region bookings alone "
        "would admit %s on the top, but all seven region-admissible passives (%s, %.2f mm2) on the top raise the H.23(e) "
        "whole-side top booking from %.1f to %.1f mm2 = %.1f %% of %.1f mm2 (FAIL against 75 %%), so none moves "
        "(revision 4; the r7 review-7 calc moved them)"
        % (", ".join(n for n, _ in stayed), ", ".join("%s -> %s" % (n.split()[0], rg) for n, rg, _ in would) or "none",
           ", ".join(n.split()[0] for n, _, _ in would), sum(a for _, _, a in would), e_top,
           e_top + sum(a for _, _, a in would), 100 * (e_top + sum(a for _, _, a in would)) / e_tot, e_tot))
    out("  all %d flexible passives on the top: %.1f mm2 = %.1f %% (information)" % (len(flex), e_top + mv_all,
                                                                               100 * (e_top + mv_all) / e_tot))
    out("  effect on the H.23(e) whole-side booking: %.2f mm2 move from the bottom to the top" % mv)
    out("  tab X sensitivity: booked as the 6 x 4 grid envelope (pads + inter-row dressing gaps) 141.4 mm2 = %.1f %% of "
        "%.1f mm2; the pad-courtyard booking above is the basis (the gaps carry the dressed wires, not parts)."
        % (100 * 141.4 / A["tab X"], A["tab X"]))
    out("  tab Y bottom also carries the gate pull-downs and series resistors (not enumerated here; T-A-06 DRC is the "
        "gate); the decoupler booking above leaves %.1f mm2 (%.1f %% of the region) for them at the 75 %% target."
        % (U_TARGET * A["tab Y bottom"] - res["tab Y bottom"][0],
           100 * (U_TARGET * A["tab Y bottom"] - res["tab Y bottom"][0]) / A["tab Y bottom"]))
    # ---- the divider strip: the interior cells next to the band that hold the six dividers at <= 75 %
    divs = sum(v for n, v in book["interior"] if n.startswith("R1") and "0.1 %" in n)
    need = divs / U_TARGET
    acc, cells = 0.0, []
    for j in range(G.ny):
        if G.cy(j) < BAND_RECT[3]:
            continue
        row = [i for i in range(G.nx) if interior[j * G.nx + i] and BAND_RECT[0] <= G.cx(i) <= BAND_RECT[2]]
        cells += [(G.cx(i), G.cy(j)) for i in row]
        acc += len(row) * G.cell
        if acc >= need:
            break
    strip = (min(c[0] for c in cells) - G.res / 2, min(c[1] for c in cells) - G.res / 2,
             max(c[0] for c in cells) + G.res / 2, max(c[1] for c in cells) + G.res / 2)
    d_loop_strip = min(min(rect_dist((c[0], c[1], c[0], c[1]), r) for r in LOOP) for c in cells)
    d_int = min((min(rect_dist((G.cx(k % G.nx), G.cy(k // G.nx), G.cx(k % G.nx), G.cy(k // G.nx)), r) for r in LOOP),
                 G.cx(k % G.nx), G.cy(k // G.nx)) for k in range(G.N) if interior[k])
    out("  divider strip (D-F5: the six 0.1 %% dividers in the interior directly beside the band, %.2f mm2 booked at "
        "<= 75 %% -> %.1f mm2): x %.2f-%.2f, y %.2f-%.2f; distance to the U101 commutation-loop region (H.23(f)) "
        "%.2f mm; the interior's loop-facing corner (%.2f, %.2f) lies %.2f mm from the loop region (the A.8 region "
        "gap), so the dividers stay in the strip and not at that corner" % (divs, need, strip[0], strip[2], strip[1],
                                                                            strip[3], d_loop_strip, d_int[1], d_int[2],
                                                                            d_int[0]))
    EXTRA["e2"] = dict(strip=strip, d_loop_strip=d_loop_strip, d_int=d_int)
    RJ["e2"] = dict(areas={k: f2(v) for k, v in A.items()},
                    regions={rg: dict(sum=f2(res[rg][0]), U=round(100 * res[rg][1], 2), parts=[(n, f2(v)) for n, v in
                                                                                             book[rg]])
                             for rg in res},
                    moved_to_top=[(n, rg, f2(a)) for n, rg, a in moved], stay_bottom=[n for n, _ in stayed],
                    divider_strip=strip, divider_strip_to_loop=f2(d_loop_strip), interior_corner_to_loop=f2(d_int[0]))
    summ("per-region top booking (D-F5)", "; ".join("%s %.1f/%.1f mm2 = %.1f %%" % (rg, res[rg][0], A[rg], 100 * res[rg][1])
                                                   for rg in res) + "; target <= 75 %%: %s"
         % ("all pass" if all(v[1] <= U_TARGET for v in res.values())
            else "FAIL in " + ", ".join(rg for rg in res if res[rg][1] > U_TARGET)), "H.23(e2)")
    summ("flexible parts (D-F5)", "to the top: %s; bottom: %s; whole-side effect %.2f mm2 bottom -> top"
         % (", ".join("%s (%s)" % (n.split()[0], rg) for n, rg, _ in moved) or "none",
            ", ".join(n.split()[0] for n, _ in stayed) or "none", mv), "H.23(e2)")
    summ("divider strip (D-F5)", "x %.2f-%.2f, y %.2f-%.2f; %.2f mm from the U101 loop region (interior corner %.2f mm)"
         % (strip[0], strip[2], strip[1], strip[3], d_loop_strip, d_int[0]), "H.23(e2)")
    return res


def sec_f():
    head("H.23(f) farthest point of the r7 outline from the U101 commutation-loop region")
    out("Loop region (MIN r7_minimal_calc.loop_distance, from DOC A.8): IN strip x 36.1-44.55, y 52.03-61.55; OUT strip "
        "x 30.8-39.3, y 62.85-66.64; U101 courtyard x 39.3-44.3, y 61.6-66.6.")

    def d(p):
        return min(rect_dist((p[0], p[1], p[0], p[1]), r) for r in LOOP)
    pts = list(OUTLINE)
    for (a, b) in edges(OUTLINE):
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05))
        pts += [(a[0] + (b[0] - a[0]) * t / n, a[1] + (b[1] - a[1]) * t / n) for t in range(n + 1)]
    x = 17.70
    while x <= 65.0:
        y = 34.14
        while y <= 76.0:
            if pip(x, y, OUTLINE):
                pts.append((x, y))
            y += 0.25
        x += 0.25
    far = max(pts, key=d)
    n365 = sum(1 for p in pts if d(p) >= 36.5)
    out("farthest point (%.2f, %.2f) at %.2f mm; points >= 36.5 mm (2-layer parity separation, STK 5.2): %d"
        % (far[0], far[1], d(far), n365))
    band = (23.15, 35.05, 42.43, 41.63)
    reg5 = ELS["REG-5V"]["bbox"]
    out("footprint low-y band x 23.15-42.43, y 35.05-41.63 (comparator area, BASIS D5): %.2f mm from the loop band "
        "(y >= 52.03); %.2f-%.2f mm from the LM1084 box (x %.2f)" % (52.03 - band[3], reg5[0] - band[2],
                                                                     reg5[0] - band[0], reg5[0]))
    # ---- r7 review 7 (D-F5): MB aggressors of the comparator band; the interior's loop-facing edge
    bpoly = rpoly(band)
    agg = []
    for nm in ("REG-BT", "C4A-BT", "C4B-BT", "C4C-BT", "L-BT"):
        agg.append(("%s box" % nm, rect_dist(ELS[nm]["bbox"], band)))
    for net in ("VOUT-BT", "VSW-BT"):
        dd = min(clearance(s, bpoly) for s in SHAPES if s["net"] == net)
        agg.append(("%s copper rim" % net, dd))
    loop_bt = min(v for k, v in agg if not k.startswith("L-BT") and not k.startswith("VSW"))
    d5 = d5v_rect(band)
    cross = sorted({s["net"] for s in SHAPES if s["net"] in ("VCHG-IN", "VBT", "VCHG") and clearance(s, bpoly) <= 0.0})
    out("comparator band against the MB BT boost (TPS61288 REG-BT; output commutation loop = REG-BT VOUT pins -> "
        "C4A/C4B/C4C-BT -> PGND, with the VOUT-BT pour; input side L-BT and VSW-BT): %s; output-loop minimum %.2f mm"
        % ("; ".join("%s %.2f mm" % z for z in agg), loop_bt))
    out("comparator band against the MB 5V layer-1 copper rim (H.23(h) basis): %.2f mm (the LM1084 box distance above "
        "is %.2f mm); MB layer-1 nets under the band: %s (TODO(measure: T-C-16 extension, D-F5))" % (d5, reg5[0] - band[2],
                                                                                              ", ".join(cross) or "none"))
    e2 = EXTRA.get("e2")
    if e2:
        out("footprint interior (H.23(e2)): loop-facing corner (%.2f, %.2f) %.2f mm from the loop region (the A.8 0.5 mm "
            "region gap); divider strip x %.2f-%.2f, y %.2f-%.2f at %.2f mm from the loop region (r7 band: 10.40 mm)"
            % (e2["d_int"][1], e2["d_int"][2], e2["d_int"][0], e2["strip"][0], e2["strip"][2], e2["strip"][1],
               e2["strip"][3], e2["d_loop_strip"]))
        summ("divider strip / interior to the U101 loop", "%.2f mm / %.2f mm (band 10.40 mm)"
             % (e2["d_loop_strip"], e2["d_int"][0]), "H.23(f)")
    summ("comparator band to the MB BT boost / 5V copper", "output loop (REG-BT, C4x-BT, VOUT-BT) %.2f mm; L-BT %.2f mm; "
         "VSW-BT %.2f mm; 5V copper rim %.2f mm; layer-1 nets crossing under it: %s"
         % (loop_bt, dict(agg)["L-BT box"], dict(agg)["VSW-BT copper rim"], d5, ", ".join(cross) or "none"), "H.23(f)")
    RJ["f"] = dict(far=far, dist=d(far), n365=n365, band_aggressors={k: f2(v) for k, v in agg}, band_5v=f2(d5),
                   band_bt_output_loop=f2(loop_bt), nets_under_band=cross)
    summ("farthest outline point from the U101 loop", "(%.2f, %.2f) at %.2f mm vs 36.5 mm 2-layer parity (none reaches)"
         % (far[0], far[1], d(far)), "H.23(f)")


# ======================================================================================================================
# H.23(g) tap field on tab X
# ======================================================================================================================
def pad_xy(el, pad):
    for p in ELS[el]["pads"]:
        if p[0] == pad:
            return (p[1], p[2])
    raise KeyError((el, pad))


# A.4 taps -> MB points. BRD pad positions (the authoritative geometry); mb_mech_calc.py TAPS in brackets where they
# differ. T9: the SNS-BT GND-net pad nearest the CR (pad 15) - ASSUMPTION for the "GND/REF1 pad", TODO(verify: SLOS954A
# INA253 pinout, T-A-01).
TAPS = {
    "T1": ("F01", "C-D6 pad 1 (V-MOT)", pad_xy("C-D6", "1"), (97.79, 19.80)),
    "T7b": ("F02", "C-D6 pad 2 (GND, shield)", pad_xy("C-D6", "2"), (97.79, 19.80)),
    "T2": ("F03", "C-D2 pad 1 (VBUS)", pad_xy("C-D2", "1"), (67.705, 69.85)),
    "T3": ("F04", "J1.39 (D-BT-EN)", pad_xy("J1", "39"), None),
    "T4": ("F05", "J1.43 (D-BC-RG)", pad_xy("J1", "43"), None),
    "T5": ("F06", "J1.45 (D-BC-FC)", pad_xy("J1", "45"), None),
    "T6": ("F07", "J1.29 (3V3)", pad_xy("J1", "29"), None),
    "T22": ("F08", "BAL pad 8 (BAL-NOK)", pad_xy("BAL", "8"), (25.86, 30.44)),
    "T8": ("F09", "J2.31 (BT-CURR)", pad_xy("J2", "31"), None),
    "T9": ("F10", "SNS-BT pad 15 (GND, Kelvin)", pad_xy("SNS-BT", "15"), (55.118, 23.622)),
    "T10": ("F11", "J1.23 (pin 10)", pad_xy("J1", "23"), None),
    "T11": ("F12", "J2.19 (pin 17)", pad_xy("J2", "19"), None),
    "T12": ("F13", "J2.47 (pin 33)", pad_xy("J2", "47"), None),
    "T13": ("F14", "J2.45 (pin 34)", pad_xy("J2", "45"), None),
    "T14": ("F15", "J2.21 (pin 16)", pad_xy("J2", "21"), None),
    "T15": ("F16", "J2.07 (pin 23)", pad_xy("J2", "07") if any(p[0] == "07" for p in ELS["J2"]["pads"])
            else pad_xy("J2", "7"), None),
    "T16": ("F17", "J2.43 (pin 35)", pad_xy("J2", "43"), None),
    "T17": ("F18", "J2.09 (pin 22, IMON)", pad_xy("J2", "09") if any(p[0] == "09" for p in ELS["J2"]["pads"])
            else pad_xy("J2", "9"), None),
    "T17r": ("F19", "J2.29 (GND, shield)", pad_xy("J2", "29"), None),
    "T20": ("F20", "ROS pad 2 (pin 7)", pad_xy("ROS", "2"), (81.534, 69.797)),
    "T21": ("F21", "J2.11 (pin 21)", pad_xy("J2", "11"), None),
    "T18": ("F22", "CO-5V pad 1 (option)", pad_xy("CO-5V", "1"), None),
    "T19": ("F23", "J2.33 (option)", pad_xy("J2", "33"), None),
    "F24": ("F24", "J1.07 (spare, option)", pad_xy("J1", "07"), None),
}
SUM20 = ["T1", "T2", "T3", "T4", "T5", "T6", "T22", "T8", "T9", "T10", "T11", "T12", "T13", "T14", "T15", "T16", "T17",
         "T17r", "T20", "T21"]                    # the 20-tap sum of mb_mech_calc / MIN (T7b follows T1)
R6_FIELD_C = (32.79, 38.34)                       # mb_mech_calc TAPFIELD_R3 (centre of the r6 field, DOC A.7)
RESID = {"T22": (round(23.90 + 2.54 * 1, 3), 35.80), "T8": (round(23.90 + 2.54 * 2, 3), 35.80),
         "T9": (round(23.90 + 2.54 * 3, 3), 35.80)}                      # DOC A.7 r6 field positions k = 1-3
# BASIS section 10 A2: T18 (F22) leaves tab X for the residual row. Candidates: r6 grid positions on the low row
# y 35.80 at k = 4..7 and on rows y 38.34 / 40.88 at k = 7 (task list); k = 1-3 on the low row are F08-F10.
T18_CAND = ([((round(23.90 + 2.54 * k, 3), 35.80), "low row y 35.80, k %d" % k) for k in range(4, 8)] +
            [((round(23.90 + 2.54 * 7, 3), yy), "row y %.2f, k 7" % yy) for yy in (38.34, 40.88)])
POST = 0.64                                        # header post, 0.64 mm square (Samtec F-226 TSW, 0.025 in)
J101_BOX = (37.0, 42.13, 44.5, 51.53)              # BASIS D7: J101 x 37.0-44.5, y 42.13-51.53 (CR footprint)
TAPS_X_R7 = ["T1", "T7b", "T2", "T3", "T4", "T5", "T6", "T10", "T11", "T12", "T13", "T14", "T15", "T16", "T17",
             "T17r", "T20", "T21", "T19", "F24"]           # tab X pads after A2 (T18 moved off tab X)
# r7 review 7 (D-F4): adjacency classes (DOC A.4 rows)
GND_TAPS = {"T7b", "T17r", "T9"}
EN_TAPS = {"T3", "T4", "T5"}
PP_TAPS = {"T10", "T11", "T21"}                    # revision 4: push-pull Teensy outputs without an EN net (DOC A.8)
# revision 4: inputs of the computed adjacent-pad consequences (H.23(g), item F05-F12 / F07-F12 / residual row)
R_DRV = 40.0          # ohm per i.MX RT1062 output driver, ASSUMPTION (DOC A.8 short table; TODO(verify: i.MX RT1062
#                       datasheet, pad output impedance and current rating))
V_IO = 3.3            # V, Teensy 3V3 / GPIO high level
R_EN_BODGE = 10e3     # ohm, EN-to-GND bodge resistor on every RT1987 EN net (CLAUDE.md section 2)
VEN_R_MAX, VEN_F_MIN = 1.4, 0.6     # V, RT1987_DS-00.pdf EC table: EN rising threshold max, falling threshold min
BQ_IOL = (30e-6, 85e-6)             # A, BQ29200_TI.pdf SLUSA52C EC: OUT low-level current at OUT 0.05 V
BQ_IOH_MIN, BQ_IOH_SC = 100e-6, 8e-3   # A, same table: OUT high-level current at 1.75 V (min), short-circuit at 0 V
BQ_VOUT = (6.0, 9.5)                # V, same table: OUT drive voltage at VDD 10 V, IOH 0 (min, max)
INA_GAIN = 0.1                      # V/A, INA253A1 (CLAUDE.md section 5, K_sns)
INA_IOUT_FIG = 7e-3                 # A, INA253A1IPWR.pdf Figure 14 covers 0-7 mA of output current only
T8_PAD_GAP = 0.5                    # mm, revision 4: T8 jacket edge to any other residual pad edge
PIN_TAPS = {"T3", "T4", "T5", "T10", "T11", "T12", "T13", "T14", "T15", "T16", "T17", "T19", "T20", "T21", "F24", "T8"}
TAP_NET = {   # tap: (net / function, class) from DOC A.4 and B.2
    "T1": ("V-MOT via R170 10 kOhm (H1 divider top)", "HV"), "T7b": ("GND, T1 shield", "GND"),
    "T2": ("VBUS via R171 10 kOhm (H1/UVB divider tops)", "HV"),
    "T3": ("D-BT-EN, pin 28 BT_BUS_ENABLE", "EN"), "T4": ("D-BC-RG EN, pin 30 REGEN_ENABLE", "EN"),
    "T5": ("D-BC-FC EN, pin 31 FC_CHARGE_ENABLE", "EN"), "T6": ("Teensy 3V3 (R175 feed)", "3V3T"),
    "T10": ("pin 10 CHG_QUAL out", "OUT"), "T11": ("pin 17 CHG_FCCEIL out", "OUT"),
    "T12": ("pin 33 ILIM_RB in", "IN"), "T13": ("pin 34 H1_RB in", "IN"), "T14": ("pin 16 H2_RB in", "IN"),
    "T15": ("pin 23 BTOK_RB in", "IN"), "T16": ("pin 35 EFUSE_FLT in (pad pull-up)", "IN"),
    "T17": ("pin 22 IIN (IMON) analog in", "AIN"), "T17r": ("GND, T17 shield", "GND"),
    "T19": ("pin 40 FC_CURRENT (option)", "AIN"), "T20": ("pin 7 CE_RB in", "IN"), "T21": ("pin 21 CHG_HB out", "OUT"),
    "F24": ("pin 2 spare (ENC_A net, option)", "IN"),
    "R175a": ("R175 pad, Teensy 3V3 side (F07)", "3V3T"), "R175b": ("R175 pad, CR 3V3 rail", "3V3R"),
    "T22": ("BAL-NOK (BQ29200 OUT)", "BAL"), "T8": ("pin 41 BT-CURR analog (INA253 BT out)", "AIN"),
    "T9": ("GND Kelvin (SNS-BT pad 15)", "GND"), "T18": ("5V via F101/R172 (option)", "5V"),
}


def short_effect(a, b):
    """Consequence, detector and verdict of a solder bridge between two orthogonally adjacent pads (D-F4)."""
    if a is None or b is None:
        return "spare position (no pad): no bridge", "-", "-"
    ca, cb = TAP_NET[a][1], TAP_NET[b][1]
    k = frozenset((ca, cb)) if ca != cb else frozenset((ca,))
    pins = ("EN", "OUT", "IN", "AIN")
    tf = "T-F-12 tap-to-tap DMM (D-F4)"
    if {a, b} == {"T10", "T21"}:
        return "heartbeat couples into the U111 QUAL trigger (hardware time limit lost)", tf, "FORBIDDEN (D-F4)"
    if ca == cb == "GND":
        return "same net", "-", "ok"
    if k == frozenset(("HV", "GND")):
        return "divider top to GND through the 10 kOhm MB-end resistor (<= 2.0 mA at 19.7 V): H1/UVB read 0 (trip " \
               "state)", "comparator state at power-up (T-C-02); " + tf, "accepted"
    if k == frozenset(("HV",)):
        return "V-MOT tied to VBUS through 20 kOhm: H1 compares the mean", "H1 never asserts (T-C-02); " + tf, "accepted"
    if "HV" in k and (k & {"3V3T", "3V3R"}):
        return "V-MOT/VBUS into the 3V3 rail through 10 kOhm (<= 2.0 mA back-feed)", tf, "accepted"
    if "HV" in k and (k & set(pins)):
        return "1.3-2.0 mA through 10 kOhm into an i.MX pin clamp (unrated)", tf, "FORBIDDEN (D-F4)"
    if "HV" in k:
        return "HV divider top tied to a CR node", tf, "accepted"
    if ca == cb == "EN":
        return "two RT1987 EN outputs contend (~1.65 V > VEN_R max 1.4 V): both switches may conduct", \
               "U119 FCC_OFF / FR-08 (not proven for this fault); " + tf, "FORBIDDEN (D-F4)"
    if k == frozenset(("EN", "GND")):
        return "EN held LOW: switch forced OFF (safe); ~40 mA pin contention when commanded HIGH (ASSUMED 40 ohm)", \
               "EN comparator (U115/U119-U121) disagrees with the command: FR-08; " + tf, "accepted"
    if k == frozenset(("EN", "3V3T")):
        return "EN forced HIGH from the Teensy 3V3: switch ON regardless of the command", tf, "FORBIDDEN (D-F4)"
    if k == frozenset(("EN", "3V3R")):
        return "EN pulled to the CR rail through R175 68 ohm: switch ON", "FR-08 readback; " + tf, "accepted"
    if k == frozenset(("3V3T", "GND")):
        return "Teensy 3V3 to GND with R175 bypassed: brown-out", tf, "FORBIDDEN (D-F4)"
    if k == frozenset(("3V3R", "GND")):
        return "CR rail to GND, held to 48.5 mA by R175 (designed, r4)", "CR logic dead: FR-08; " + tf, "accepted"
    if k == frozenset(("3V3T", "3V3R")):
        return "R175 bypassed: a later CR-side short is not current-limited", tf, "accepted"
    if ca in pins and cb in pins:
        return "two Teensy pins tied: contention if both are outputs, otherwise the input follows the other net", \
               "readback plausibility (FR-08/FR-44); " + tf, "accepted"
    if (ca in pins and cb == "GND") or (cb in pins and ca == "GND"):
        return "pin held LOW: output contention or a readback stuck LOW", "readback plausibility; " + tf, "accepted"
    if (ca in pins and cb in ("3V3T", "3V3R")) or (cb in pins and ca in ("3V3T", "3V3R")):
        return "pin held HIGH: output contention or a readback stuck HIGH", "readback plausibility; " + tf, "accepted"
    if k == frozenset(("BAL", "AIN")):
        return "BAL-NOK level on pin 41 and U104 IN-: false BT_OK state", "T-A-01c; " + tf, "accepted"
    if k == frozenset(("AIN", "GND")):
        return "BT-CURR reads 0 A: U104 BT_OK reads 'no current'", "T-C-03; " + tf, "accepted"
    return "%s to %s" % (TAP_NET[a][0], TAP_NET[b][0]), tf, "accepted"


PAD = 1.5                                          # DOC A.4: SMT pads 1.5 x 1.5 mm
PITCH = 2.54
CY_PAD = 0.25                                      # pad courtyard = pad + 0.25 mm (DOC A.8 courtyard convention)
FIVEV_GAP = 2.0                                    # task: field low edge >= 2.0 mm from the 5V copper rim
FIELD = None


_FIVEV = None


def five_v_shapes():
    global _FIVEV
    if _FIVEV is None:
        _FIVEV = [s for s in SHAPES if s["net"] == "5V" and s["kind"] in ("wire", "poly", "via")
                  and rect_dist(s["bb"], TAB_X) < 20.0]
    return _FIVEV


def d5v(x, y):
    best = 1e9
    for s in five_v_shapes():
        if s["kind"] == "poly":
            if pip(x, y, s["pts"]):
                return -s["r"]
            d = min(dpt_seg(x, y, a[0], a[1], b[0], b[1]) for a, b in edges(s["pts"])) - s["r"]
        elif s["kind"] == "via":
            c = s["pts"][0]
            d = math.hypot(x - c[0], y - c[1]) - s["r"]
        else:
            (a, b) = s["pts"]
            d = dpt_seg(x, y, a[0], a[1], b[0], b[1]) - s["r"]
        best = min(best, d)
    return best


def d5v_rect(rect):
    """Plan distance from a rectangle to the 5V L1 copper rim."""
    best = 1e9
    for s in five_v_shapes():
        best = min(best, clearance(s, rpoly(rect)))
    return best


def hungarian(cost):
    n, m = len(cost), len(cost[0])
    INF = float("inf")
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    ans = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            ans[p[j] - 1] = j - 1
    return ans


def sec_g():
    global FIELD
    head("H.23(g) tap field on tab X: 6 x 4 grid at 2.54 mm, 20 pads (F01-F07, F11-F21, F23, F24) + R175; residual "
         "F08-F10 and F22 (T18, A2) on the footprint")
    # placement: pad courtyard >= 0.5 mm inside the tab X free edges; low pad edge >= 2.0 mm from the 5V rim; pushed to
    # the +x limit (the destinations lie at +x)
    lim_x1 = TAB_X[2] - CY - CY_PAD - PAD / 2               # rightmost pad centre
    lim_y4 = TAB_X[3] - CY - CY_PAD - PAD / 2               # top-row pad centre
    # low edge: find the smallest y1 so that the pad envelope low edge keeps >= 2.0 mm from the 5V rim
    x6 = round(lim_x1, 3)
    x1c = x6 - 5 * PITCH
    y1 = TAB_X[1] + CY + CY_PAD + PAD / 2
    while True:
        env = (x1c - PAD / 2, y1 - PAD / 2, x6 + PAD / 2, y1 - PAD / 2 + 1e-6)
        if d5v_rect(env) >= FIVEV_GAP - 1e-9:
            break
        y1 += 0.001
    y1_min = y1
    y1_max = lim_y4 - 3 * PITCH
    y1 = round((y1_min + y1_max) / 2, 2)
    xs = [round(x1c + PITCH * i, 3) for i in range(6)]
    ys = [round(y1 + PITCH * j, 3) for j in range(4)]
    env = (xs[0] - PAD / 2, ys[0] - PAD / 2, xs[-1] + PAD / 2, ys[-1] + PAD / 2)
    cyd = (env[0] - CY_PAD, env[1] - CY_PAD, env[2] + CY_PAD, env[3] + CY_PAD)
    out("Placement: pad courtyard = pad + %.2f mm (DOC A.8 convention, ASSUMPTION for SMT tap pads) >= %.1f mm inside "
        "the tab X free edges; field pushed to the +x limit; low pad edge >= %.1f mm from the 5V copper rim; the free y "
        "band of the lowest row is %.3f-%.3f, the field takes its middle." % (CY_PAD, CY, FIVEV_GAP, y1_min, y1_max))
    out("  pad centres x %s, y %s" % (xs, ys))
    out("  pad envelope x %.3f-%.3f, y %.3f-%.3f; courtyard x %.3f-%.3f, y %.3f-%.3f; margins to the outline: right "
        "%.3f, top %.3f, low %.3f mm" % (env[0], env[2], env[1], env[3], cyd[0], cyd[2], cyd[1], cyd[3],
                                          TAB_X[2] - cyd[2], TAB_X[3] - cyd[3], cyd[1] - TAB_X[1]))
    out("  low pad edge to the 5V copper rim: %.3f mm (rule >= %.1f); MIN field (y 57.80) %.3f mm"
        % (d5v_rect((env[0], env[1], env[2], env[1] + 1e-6)), FIVEV_GAP,
           d5v_rect((49.98, 57.05, 64.18, 57.05 + 1e-6))))
    # R175 (1206) vertical in column 1 on two vertically adjacent grid positions (DOC A.4: R175 at F07); F07 adjacent.
    pos = [(c, r) for r in range(4) for c in range(6)]
    taps_r6x = TAPS_X_R7 + ["T18"]          # the first-run tab X set (21 pads, T18 on tab X), for the change report

    def L(tap, c, r):
        d = TAPS[tap][2]
        return math.hypot(xs[c] - d[0], ys[r] - d[1])

    def adj(p, q):
        return abs(p[0] - q[0]) + abs(p[1] - q[1]) == 1

    def assign(taps_x):
        best = None
        for r0 in range(3):
            r175 = [(0, r0), (0, r0 + 1)]
            free = [p for p in pos if p not in r175]
            big = 1e6
            cost = []
            for t in taps_x:
                row = []
                for p in free:
                    c = L(t, *p)
                    if t == "T6" and not any(adj(p, q) for q in r175):
                        c += big
                    row.append(c)
                cost.append(row)
            asg = hungarian(cost)
            place = {t: free[asg[i]] for i, t in enumerate(taps_x)}

            def total(pl):
                return sum(L(t, *pl[t]) for t in taps_x)
            base = total(place)
            # pair repair: T1/T7b and T17/T17r on adjacent positions (DOC A.4 twisted pairs; MIN 5.5)
            for (a, b) in (("T1", "T7b"), ("T17", "T17r")):
                if adj(place[a], place[b]):
                    continue
                occ = {v: k for k, v in place.items()}
                cand = []
                for mover, anchor in ((b, a), (a, b)):
                    for q in free:
                        if not adj(q, place[anchor]) or q == place[mover]:
                            continue
                        pl = dict(place)
                        other = occ.get(q)
                        pl[mover] = q
                        if other is not None:
                            if other in ("T6",) and not any(adj(place[mover], z) for z in r175):
                                continue
                            pl[other] = place[mover]
                        cand.append((total(pl), pl))
                place = min(cand, key=lambda z: z[0])[1]
            tot = total(place)
            if best is None or tot < best[0]:
                best = (tot, place, r175, base)
        return best
    tot0, place0, r1750, base0 = assign(taps_r6x)
    totR2, placeR2, r175R2, baseR2 = assign(TAPS_X_R7)          # the r7 rev-2 (published) assignment, length only

    # ---- r7 review 7 (D-F4): adjacency exclusions; constrained local search (swaps and moves into spares)
    def violations(pl, r175c, ext=False):
        v = []
        nb = {}
        for t, p in pl.items():
            nb[t] = [u for u, q in pl.items() if u != t and adj(p, q)]
        for a, b in (("T1", "T7b"), ("T17", "T17r")):
            if not adj(pl[a], pl[b]):
                v.append("%s/%s not adjacent" % (a, b))
        if not any(adj(pl["T6"], z) for z in r175c):
            v.append("T6 not beside R175")
        bad6 = [u for u in nb["T6"] if u in GND_TAPS or u in EN_TAPS]
        if bad6:
            v.append("T6 beside %s" % "/".join(sorted(bad6)))
        for a in EN_TAPS:
            for b in nb[a]:
                if b in EN_TAPS and a < b:
                    v.append("%s beside %s (EN-EN)" % (a, b))
        if "T21" in nb["T10"]:
            v.append("T10 beside T21")
        for a in ("T1", "T2"):
            bad = [u for u in nb[a] if u in PIN_TAPS]
            if bad:
                v.append("%s beside raw Teensy-pin pad(s) %s" % (a, "/".join(sorted(bad))))
        if ext:      # revision 4 candidate (A.8 proposed closure): no EN tap and no F07 beside a push-pull pad
            for a in sorted(EN_TAPS | {"T6"}):
                bad = [u for u in nb[a] if u in PP_TAPS]
                if bad:
                    v.append("%s beside push-pull pad(s) %s" % (a, "/".join(sorted(bad))))
        return v

    def lsum(pl):
        return sum(L(t, *pl[t]) for t in pl)

    def search(taps_x, ext=False):
        rng = random.Random(11)
        best = None
        for r0 in range(3):
            r175c = [(0, r0), (0, r0 + 1)]
            free = [p for p in pos if p not in r175c]
            starts = [dict(placeR2) if r175R2 == r175c else None]
            for _ in range(24):
                cells = list(free)
                rng.shuffle(cells)
                starts.append({t: cells[i] for i, t in enumerate(taps_x)})
            for st in starts:
                if st is None:
                    continue
                pl = dict(st)

                def cost(p_):
                    return lsum(p_) + 1000.0 * len(violations(p_, r175c, ext))
                c0 = cost(pl)
                improved = True
                while improved:
                    improved = False
                    occ = {v_: k_ for k_, v_ in pl.items()}
                    bestm = None
                    for i_, a in enumerate(taps_x):
                        for q in free:
                            if q == pl[a]:
                                continue
                            p2 = dict(pl)
                            b = occ.get(q)
                            p2[a] = q
                            if b is not None:
                                p2[b] = pl[a]
                            c = cost(p2)
                            if c < c0 - 1e-9 and (bestm is None or c < bestm[0]):
                                bestm = (c, p2)
                    if bestm is not None:
                        c0, pl = bestm
                        improved = True
                if best is None or c0 < best[0] - 1e-9:
                    best = (c0, pl, r175c)
        return best
    _, place, r175 = search(TAPS_X_R7)
    _, place_ext, r175_ext = search(TAPS_X_R7, ext=True)          # revision 4: candidate, not adopted
    tot, base = lsum(place), totR2
    viol_new = violations(place, r175)
    viol_r2 = violations(placeR2, r175R2)
    spare = [p for p in pos if p not in place.values() and p not in r175]
    spare0 = [p for p in pos if p not in place0.values() and p not in r1750]
    # ---- A2: T18 pad position on the footprint residual row
    reg5 = ELS["REG-5V"]["bbox"]

    def crosses(p, d):
        return any(seg_x(p, d, a, b) for a, b in edges(rpoly(reg5))) or pip(p[0], p[1], rpoly(reg5))
    t18d = TAPS["T18"][2]
    d_end_reg5 = d_rect_pt(reg5, t18d[0], t18d[1])          # every candidate path ends at CO-5V pad 1
    t18rows = []
    for p, lab in T18_CAND:
        Lt = math.hypot(p[0] - t18d[0], p[1] - t18d[1])
        # 1x10 header column (DOC A.8): CR pad lands 1.9 mm square; posts 0.64 mm square (Samtec F-226 TSW, 0.025 in)
        land = [i + 1 for i, q in enumerate(PIN_B) if d_rect_seg((q[0] - 0.95, q[1] - 0.95, q[0] + 0.95, q[1] + 0.95),
                                                                 p, t18d) <= 0.0]
        k = min(range(len(PIN_B)), key=lambda i: dpt_seg(PIN_B[i][0], PIN_B[i][1], p[0], p[1], t18d[0], t18d[1]))
        q = PIN_B[k]
        dcl = dpt_seg(q[0], q[1], p[0], p[1], t18d[0], t18d[1])
        dpost = d_rect_seg((q[0] - POST / 2, q[1] - POST / 2, q[0] + POST / 2, q[1] + POST / 2), p, t18d)
        dreg = d_rect_seg(reg5, p, t18d)
        cy_pad = (p[0] - PAD / 2 - CY_PAD, p[1] - PAD / 2 - CY_PAD, p[0] + PAD / 2 + CY_PAD, p[1] + PAD / 2 + CY_PAD)
        dj101 = rect_dist(cy_pad, J101_BOX)
        t18rows.append(dict(lab=lab, p=p, L=Lt, cr=crosses(p, t18d), land=land, post=k + 1, dcl=dcl, dpost=dpost,
                            dreg=dreg, dj101=dj101))
    # BASIS section 11 B3 (A2 restated): F22 = the low-row position (y 35.80) nearest CO-5V whose straight path clears
    # the REG-5V box; the low row keeps the pad clear of the mated W5 socket envelope beside J101
    low = [r for r in t18rows if not r["cr"] and abs(r["p"][1] - 35.80) < 1e-9]
    t18r = min(low, key=lambda r: r["L"])
    t18 = (t18r["lab"], t18r["p"], t18r["L"])
    R7_RESID = dict(RESID)
    R7_RESID["T18"] = t18[1]
    out("  assignment (r7 review 7, D-F4): minimum straight-length sum over the free positions subject to the adjacency "
        "exclusions (no two of T3/T4/T5 orthogonally adjacent; T6/F07 beside R175 with no GND (T7b, T17r) or EN "
        "(T3/T4/T5) neighbour; T10 not beside T21; T1 and T2 not beside a raw Teensy-pin pad; T1/T7b and T17/T17r on "
        "adjacent positions; T18 off tab X, A2), by local search (single moves and swaps from the r7 rev-2 assignment "
        "and 24 seeded random starts per R175 row option). R175 vertical in column 1, rows %d-%d. Tab X: %d pads + R175; "
        "spare grid positions %s. Straight-length sum over the tab X pads %.1f mm (r7 rev 2, length only, %.1f mm: "
        "%+.1f mm)." % (r175[0][1] + 1, r175[1][1] + 1, len(TAPS_X_R7), [(xs[c], ys[r]) for c, r in spare], tot, base,
                        tot - base))
    out("  r7 rev-2 assignment against the D-F4 exclusions: %s" % ("; ".join(viol_r2) or "none"))
    out("  r7 review-7 assignment against the D-F4 exclusions: %s" % ("; ".join(viol_new) or "none violated"))
    chg = [(t, placeR2[t], place[t]) for t in TAPS_X_R7 if placeR2[t] != place[t]]
    out("  moves against r7 rev 2 (R175 rows %d-%d -> %d-%d): %s"
        % (r175R2[0][1] + 1, r175R2[1][1] + 1, r175[0][1] + 1, r175[1][1] + 1,
           ("; ".join("%s %s (%.2f, %.2f) -> (%.2f, %.2f)" % (t, TAPS[t][0], xs[a[0]], ys[a[1]], xs[b[0]], ys[b[1]])
                      for t, a, b in chg)) if chg else "none"))
    out("  T18 / F22 residual position (A2; destination CO-5V pad 1 (%.3f, %.3f); straight path must not cross the "
        "REG-5V box x %.2f-%.2f, y %.2f-%.2f; F08-F10 hold k = 1-3 on the low row):" % (t18d[0], t18d[1], reg5[0],
                                                                                       reg5[2], reg5[1], reg5[3]))
    for r in t18rows:
        out("    %-22s (%.2f, %.2f): straight %.2f mm; crosses REG-5V %s (path to the box %.3f mm); nearest 1x10 post "
            "pin %d: centreline %.3f mm from the post centre, %s; over the 1.9 mm pad land(s) %s; pad courtyard to the "
            "J101 box %.2f mm%s"
            % (r["lab"], r["p"][0], r["p"][1], r["L"], "yes" if r["cr"] else "no", r["dreg"], r["post"], r["dcl"],
               ("passes BESIDE (not over) the 0.64 mm post, %.3f mm from its square" % r["dpost"]) if r["dpost"] > 0
               else "passes OVER the 0.64 mm post", r["land"] or "none", r["dj101"],
               "  <- CHOSEN (B3: low row, nearest CO-5V)" if r["p"] == t18[1] else ""))
    sh = min(t18rows, key=lambda r: r["L"])
    out("    every candidate ends at CO-5V pad 1 (%.3f, %.3f), %.3f mm from the REG-5V box (x %.2f): the wire end and the "
        "joint sit beside the LM1084 body whichever F22 position is chosen (F101/R172 temperature derating at that "
        "joint: T-A-05, BASIS B3)" % (t18d[0], t18d[1], d_end_reg5, reg5[0]))
    out("    choice (BASIS section 11 B3): F22 (T18) at (%.2f, %.2f), straight %.2f mm; the path passes beside (not over) "
        "the pin-%d post (%.3f mm from the post square; it crosses that post's 1.9 mm CR pad land, so the wire is "
        "dressed over the CR top there); pad courtyard %.2f mm from the J101 box x %.1f-%.1f, y %.2f-%.2f (BASIS D7). "
        "The shortest candidate %s (%.2f, %.2f), %.2f mm, has its pad courtyard %.2f mm from the J101 box, where the "
        "mated W5 socket envelope extends past the box (BASIS B3; envelope size TODO(verify: W5 IDC socket drawing)); "
        "rejected."
        % (t18[1][0], t18[1][1], t18[2], t18r["post"], t18r["dpost"], t18r["dj101"], J101_BOX[0], J101_BOX[2],
           J101_BOX[1], J101_BOX[3], sh["lab"], sh["p"][0], sh["p"][1], sh["L"], sh["dj101"]))
    r175_box = (xs[0] - 2.3 / 2, (ys[r175[0][1]] + ys[r175[1][1]]) / 2 - 4.75 / 2, xs[0] + 2.3 / 2,
                (ys[r175[0][1]] + ys[r175[1][1]]) / 2 + 4.75 / 2)
    out("  R175 1206 courtyard (vertical, 2.3 x 4.75 mm, DOC A.8) x %.3f-%.3f, y %.3f-%.3f"
        % (r175_box[0], r175_box[2], r175_box[1], r175_box[3]))
    # ---- grid map and the adjacent-pad short table (D-F4)
    cell = {}
    r175a = next(z for z in r175 if adj(place["T6"], z))
    for z in r175:
        cell[z] = "R175a" if z == r175a else "R175b"
    for t, p in place.items():
        cell[p] = t
    out("  grid map (row 4 at the top; R175a = the R175 pad on the F07/Teensy 3V3 side, R175b = the CR rail side, "
        "'-' = spare, no pad):")
    for r in (3, 2, 1, 0):
        out("    y %.2f  %s" % (ys[r], "  ".join("%-12s" % (("%s/%s" % (cell[(c, r)], TAPS[cell[(c, r)]][0]))
                                                            if cell.get((c, r)) in TAPS else (cell.get((c, r)) or "-"))
                                              for c in range(6))))
    out("    x       %s" % "  ".join("%-12.2f" % x for x in xs))
    adj_ok = {pr: adj(place[pr[0]], place[pr[1]]) for pr in (("T1", "T7b"), ("T17", "T17r"))}
    out("  adjacency check (D-F4): T1/T7b %s, T17/T17r %s, T6 beside R175 %s; EN pairs adjacent: %s; T6 neighbours: %s; "
        "T10 beside T21: %s; T1 neighbours: %s; T2 neighbours: %s"
        % (adj_ok[("T1", "T7b")], adj_ok[("T17", "T17r")], any(adj(place["T6"], z) for z in r175),
           [(a, b) for a in sorted(EN_TAPS) for b in sorted(EN_TAPS) if a < b and adj(place[a], place[b])] or "none",
           sorted(cell[q] for q in pos if adj(q, place["T6"]) and q in cell),
           adj(place["T10"], place["T21"]), sorted(cell[q] for q in pos if adj(q, place["T1"]) and q in cell),
           sorted(cell[q] for q in pos if adj(q, place["T2"]) and q in cell)))
    out("  adjacent-pad short table, every orthogonal pair of the 6 x 4 grid (pad gap 2.54 - 1.50 = 1.04 mm; one hand "
        "solder bridge or stray strand per row):")
    out("    %-14s %-14s %-12s %-74s %s" % ("pad A", "pad B", "verdict", "consequence", "detector"))
    adj_rows = []
    for r in range(4):
        for c in range(6):
            for (dc, dr) in ((1, 0), (0, 1)):
                c2, r2 = c + dc, r + dr
                if c2 > 5 or r2 > 3:
                    continue
                a, b = cell.get((c, r)), cell.get((c2, r2))
                cons, det, ver = short_effect(a, b)
                la = ("%s %s" % (a, TAPS[a][0])) if a in TAPS else (a or "spare")
                lb = ("%s %s" % (b, TAPS[b][0])) if b in TAPS else (b or "spare")
                adj_rows.append(dict(a=la, b=lb, pa=(xs[c], ys[r]), pb=(xs[c2], ys[r2]), verdict=ver, cons=cons,
                                     det=det))
                out("    %-14s %-14s %-12s %-74s %s" % (la, lb, ver, cons[:74], det))
    n_forb = sum(1 for z in adj_rows if z["verdict"].startswith("FORBIDDEN"))
    out("    %d orthogonal pairs, %d FORBIDDEN (must be 0)" % (len(adj_rows), n_forb))
    out("  residual row (y 35.80; pitch 2.54 mm between F08-F09-F10, F22 10.16 mm from F10):")
    res_pairs = [("T22", "T8"), ("T8", "T9"), ("T9", "T18")]
    res_rows = []
    for a, b in res_pairs:
        pa, pb = (RESID.get(a) or R7_RESID[a]), (RESID.get(b) or R7_RESID[b])
        gap = abs(pa[0] - pb[0]) - PAD
        if gap > PITCH:
            cons, det, ver = "not adjacent (pad gap %.2f mm)" % gap, "-", "-"
        else:
            cons, det, ver = short_effect(a, b)
        res_rows.append(dict(a=a, b=b, gap=gap, verdict=ver, cons=cons, det=det))
        out("    %s %s (%s) / %s %s (%s): pad gap %.2f mm; %s; %s; detector %s"
            % (TAPS[a][0], a, TAP_NET[a][0], TAPS[b][0], b, TAP_NET[b][0], gap, ver, cons, det))
    # ---- residual row
    out("  residual pads on the footprint: F08 (T22) %s, F09 (T8) %s, F10 (T9) %s (DOC A.7 r6 positions k = 1-3 on the "
        "low row y 35.80), F22 (T18) %s (A2)" % (RESID["T22"], RESID["T8"], RESID["T9"], R7_RESID["T18"]))
    # ---- dressing rule paths (D-F4): pad -> adjacent inter-row gap -> +x past column 6 -> MB point
    X_EXIT = xs[-1] + PITCH / 2
    pad_sq = {t: (xs[c] - PAD / 2, ys[r] - PAD / 2, xs[c] + PAD / 2, ys[r] + PAD / 2) for t, (c, r) in place.items()}
    res_sq = {t: (p[0] - PAD / 2, p[1] - PAD / 2, p[0] + PAD / 2, p[1] + PAD / 2) for t, p in R7_RESID.items()}
    co5 = ELS["CO-5V"]["bbox"]

    WIRE_R = 0.5                                       # 26 AWG jacket radius (OD ~1.0 mm ASSUMPTION): no jacket over a pad
    LANE = {}

    def clean(a, b, own, resid=False, gap=0.0):
        sq = res_sq if resid else pad_sq
        g_ = WIRE_R + gap
        for u, s_ in sq.items():
            if u != own and seg_hits_rect(a, b, (s_[0] - g_, s_[1] - g_, s_[2] + g_, s_[3] + g_)):
                return False
        if not resid and seg_hits_rect(a, b, r175_box):
            return False
        if crosses(a, b) or (own != "T18" and seg_hits_rect(a, b, co5)):     # T18 ends on CO-5V pad 1
            return False
        return True

    def plen(path):
        return sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]) for i in range(len(path) - 1))

    def dress(t, p, d):
        if t in R7_RESID:
            if clean(p, d, t, resid=True):
                return [p, d], "straight"
            cands = []
            # revision 4: a lane keeps the jacket >= T8_PAD_GAP from every other residual pad and lies on the CR
            # (jacket inside the CR low edge). (**superseded:** the r7 review-7 lane y 34.40, 0.15 mm below the F10/F22
            # pads, 0.24 mm over the CR low edge.)
            pads_o = [s_ for u, s_ in res_sq.items() if u != t]
            y_lo = R6[1] + WIRE_R                       # lowest centreline with the jacket on the CR
            y_hi = min(s_[1] for s_ in pads_o) - WIRE_R - T8_PAD_GAP
            LANE[t] = dict(low=(y_lo, y_hi))
            if y_lo <= y_hi + 1e-9:
                pa = [p, (p[0], y_hi), (X_EXIT - 1.27, y_hi), d]
                if all(clean(pa[i], pa[i + 1], t, resid=True, gap=T8_PAD_GAP) for i in range(3)):
                    cands.append((plen(pa), pa, "low-edge lane y %.2f to x %.2f" % (y_hi, X_EXIT - 1.27)))
            right = [s_ for s_ in pads_o if s_[0] > p[0]]
            if right:
                y_up = max(s_[3] for s_ in right) + T8_PAD_GAP + WIRE_R
                x_dn = max(s_[2] for s_ in right) + T8_PAD_GAP + WIRE_R
                pu = [p, (p[0], y_up), (x_dn, y_up), (x_dn, y_lo), (X_EXIT - 1.27, y_lo), d]
                ok_u = all(clean(pu[i], pu[i + 1], t, resid=True, gap=T8_PAD_GAP) for i in range(len(pu) - 1))
                LANE[t].update(upper=(y_up, x_dn, y_lo), upper_ok=ok_u, upper_path=pu)
                if ok_u:
                    cands.append((plen(pu), pu, "upper lane y %.2f over the residual row to x %.2f, down to y %.2f, "
                                  "to x %.2f" % (y_up, x_dn, y_lo, X_EXIT - 1.27)))
            t9 = TAPS["T9"][2]
            pb = [p, t9, d]
            if all(clean(pb[i], pb[i + 1], t, resid=True, gap=T8_PAD_GAP) for i in range(2)):
                cands.append((plen(pb), pb, "with T9 to the SNS-BT pad 15 region, then to the MB point"))
            if not cands:
                return [p, d], "NO LEGAL PATH"
            c_ = min(cands, key=lambda z: z[0])
            return c_[1], c_[2] + ("" if len(cands) == 1 else " (alternative: %s, %.1f mm)" %
                                   ([z for z in cands if z is not c_][0][2], [z for z in cands if z is not c_][0][0]))
        if clean(p, d, t):
            return [p, d], "straight"
        c, r = place[t]
        cands = []
        gaps = [ys[r] + PITCH / 2] if r == 0 else ([ys[r] - PITCH / 2] if r == 3 else
                                                   [ys[r] - PITCH / 2, ys[r] + PITCH / 2])   # inter-row gaps only
        for g in gaps:
            pa = [p, (p[0], g), (X_EXIT, g), d]
            if all(clean(pa[i], pa[i + 1], t) for i in range(1, 3)):
                cands.append((plen(pa), pa, "gap y %.2f" % g))
        if not cands:
            return [p, d], "NO LEGAL PATH"
        c_ = min(cands, key=lambda z: z[0])
        return c_[1], c_[2]
    out("")
    out("  %-5s %-4s %-30s %-18s %-18s %8s %8s %8s %6s %8s  %s" % ("tap", "F", "MB point (BRD)", "r7 pad", "MB point xy",
                                                                   "r6 (mm)", "r7 (mm)", "delta", "LM1084", "dressed",
                                                                   "dressed path"))
    rows = []
    s6 = s7 = s7d = s6c = 0.0
    s6f08 = 0.0
    gap_use = {}
    for t, (F, desc, dst, mm) in TAPS.items():
        if t in R7_RESID:
            p = R7_RESID[t]
        else:
            c, r = place[t]
            p = (xs[c], ys[r])
        # r6 basis: F08-F10 at their r6 pads (RESID, k = 1-3); every other tap at the r6 field centre (its r6 pad is
        # not recorded per tap)
        p6 = RESID.get(t, R6_FIELD_C)
        l6 = math.hypot(p6[0] - dst[0], p6[1] - dst[1])
        l6c = math.hypot(R6_FIELD_C[0] - dst[0], R6_FIELD_C[1] - dst[1])
        l7 = math.hypot(p[0] - dst[0], p[1] - dst[1])
        cr = crosses(p, dst)                       # r7 review 7: residual taps are tested too (T8, D-F4)
        dpath, dlab = dress(t, p, dst)
        ld = plen(dpath)
        if dlab.startswith("gap"):
            gap_use.setdefault(dlab, []).append(t)
        if t in SUM20:
            s6 += l6
            s6c += l6c
            s6f08 += l6 if t == "T22" else l6c
            s7 += l7
            s7d += ld
        rows.append(dict(tap=t, F=F, desc=desc, pad=p, dst=dst, r6=l6, r7=l7, crosses=cr, dressed=ld, mbm=mm,
                         dpath=dpath, dlab=dlab))
        out("  %-5s %-4s %-30s (%6.2f,%6.2f)  (%7.3f,%7.3f) %8.1f %8.1f %+8.1f %6s %8.1f  %s%s"
            % (t, F, desc[:30], p[0], p[1], dst[0], dst[1], l6, l7, l7 - l6, "yes" if cr else "no", ld, dlab,
               "" if t in SUM20 else "  (not in the 20-tap sum)"))
    out("  SUM of the 20 taps (T7b follows T1; T18, T19, F24 are options): r6 %.1f mm (F08-F10 at their r6 pads, the "
        "rest at the r6 field centre), r7 straight %.1f mm (%+.1f %%), r7 dressed %.1f mm (%+.1f %% against r6)"
        % (s6, s7, 100 * (s7 / s6 - 1), s7d, 100 * (s7d / s6 - 1)))
    out("  sensitivity of the r6 basis: only F08 held at its r6 position (T8, T9 at the field centre): r6 sum %.1f mm, "
        "r7 %+.1f %%; all 20 at the field centre (first-run basis): r6 sum %.1f mm, r7 %+.1f %%"
        % (s6f08, 100 * (s7 / s6f08 - 1), s6c, 100 * (s7 / s6c - 1)))
    out("  'LM1084' = the straight line from the pad crosses the REG-5V box (x %.2f-%.2f, y %.2f-%.2f), tested for every "
        "tap including the residual row (r7 review 7). 'dressed' = the path the A.4 / PM6 dressing rule allows (D-F4): "
        "a tab X wire whose straight jacket (radius 0.5 mm, ASSUMPTION) crosses another pad, or whose straight line "
        "crosses the R175 courtyard, the REG-5V box or CO-5V, leaves its "
        "pad into the adjacent inter-row gap, runs +x in that gap to x %.2f (half a pitch past column 6; courtyard "
        "edge %.2f) and only then turns to its MB point, so it stays at y > 56 until x > 63 and crosses no pad; a "
        "residual wire that crosses the REG-5V box takes the shorter legal path listed. (**superseded in r7:** pad -> "
        "(63.50, pad y) -> MB point, which ran over the row-1 pads.)" % (reg5[0], reg5[2], reg5[1], reg5[3], X_EXIT,
                                                                       cyd[2]))
    out("  inter-row gap occupancy (wires per 1.04 mm gap; 26 AWG OD ~1.0 mm ASSUMPTION, so more than one wire per "
        "gap is stacked, not side by side): %s" % "; ".join("%s: %d (%s)" % (k, len(v), ", ".join(v))
                                                           for k, v in sorted(gap_use.items())))
    # residual straight paths against the 1x10 posts (D-F4, T8)
    for t in ("T22", "T8", "T9"):
        p, d = R7_RESID[t], TAPS[t][2]
        k = min(range(len(PINS)), key=lambda i: d_rect_seg((PINS[i][0] - POST / 2, PINS[i][1] - POST / 2,
                                                            PINS[i][0] + POST / 2, PINS[i][1] + POST / 2), p, d))
        q = PINS[k]
        dp = d_rect_seg((q[0] - POST / 2, q[1] - POST / 2, q[0] + POST / 2, q[1] + POST / 2), p, d)
        out("  residual %s straight path: nearest header post (%.3f, %.3f): %s; REG-5V box %s; CO-5V box %s"
            % (t, q[0], q[1], ("over the post square" if dp <= 0 else "beside, %.3f mm from the post square" % dp),
               "CROSSED" if crosses(p, d) else "clear", "CROSSED" if seg_hits_rect(p, d, co5) else "clear"))
    # ---- revision 4: the T8 lane (jacket >= 0.5 mm from the F10/F22 pads and on the CR)
    t8row = next(r for r in rows if r["tap"] == "T8")
    ln = LANE.get("T8", {})
    if ln:
        y_lo, y_hi = ln["low"]
        out("  T8 lane (revision 4; jacket radius %.1f mm, ASSUMPTION; >= %.1f mm from every other residual pad edge, "
            "jacket on the CR): a low-edge lane needs the centreline at y >= %.2f (jacket inside the CR low edge y %.2f) "
            "and y <= %.2f (jacket %.1f mm below the F10/F22 pad edge y %.2f): %s"
            % (WIRE_R, T8_PAD_GAP, y_lo, R6[1], y_hi, T8_PAD_GAP, y_hi + WIRE_R + T8_PAD_GAP,
               ("infeasible by %.2f mm (the band between the CR edge and the pads, %.2f mm, holds a jacket of at most "
                "%.2f mm OD with the 0.5 mm gap)" % (y_lo - y_hi, (y_hi + WIRE_R + T8_PAD_GAP) - R6[1],
                                                     (y_hi + WIRE_R + T8_PAD_GAP) - R6[1] - T8_PAD_GAP))
               if y_lo > y_hi + 1e-9 else "feasible"))
        dp_ = t8row["dpath"]
        segs = list(zip(dp_[:-1], dp_[1:]))
        d_pads = min((d_rect_seg(s_, a, b) - WIRE_R, u) for u, s_ in res_sq.items() if u != "T8" for a, b in segs)
        cr_pts = [q for a, b in segs for q in (a, b) if q[0] <= R6[2] + 1e-9 and q[1] < 35.0]
        d_edge = min((q[1] - WIRE_R - R6[1] for q in cr_pts), default=float("nan"))
        d_reg = min(d_rect_seg(reg5, a, b) for a, b in segs) - WIRE_R
        d_co5 = min(d_rect_seg(co5, a, b) for a, b in segs) - WIRE_R
        k_p = min(range(len(PINS)), key=lambda i: min(d_rect_seg((PINS[i][0] - POST / 2, PINS[i][1] - POST / 2,
                                                                   PINS[i][0] + POST / 2, PINS[i][1] + POST / 2), a, b)
                                                       for a, b in segs))
        q_ = PINS[k_p]
        d_post = min(d_rect_seg((q_[0] - POST / 2, q_[1] - POST / 2, q_[0] + POST / 2, q_[1] + POST / 2), a, b)
                     for a, b in segs) - WIRE_R
        d_land = min(d_rect_seg((q_[0] - 0.95, q_[1] - 0.95, q_[0] + 0.95, q_[1] + 0.95), a, b) for a, b in segs) - WIRE_R
        t18p, t18d_ = R7_RESID["T18"], TAPS["T18"][2]
        x_t18 = any(seg_x(a, b, t18p, t18d_) for a, b in segs)
        band_over = [(max(min(a[0], b[0]), BAND_RECT[0]), min(max(a[0], b[0]), BAND_RECT[2])) for a, b in segs
                     if abs(a[1] - b[1]) < 1e-9 and BAND_RECT[1] < a[1] < BAND_RECT[3]]
        out("    T8 dressed path (%s): %s; %.1f mm (straight %.1f mm; r7 review 7 lane y 34.40: 86.0 mm); jacket to the "
            "nearest other residual pad %.2f mm (%s); jacket to the CR low edge %.2f mm (inside); jacket to the REG-5V "
            "box %.2f mm, to CO-5V %.2f mm; nearest header post pin %s (%.3f, %.3f): jacket %.2f mm from the post "
            "square, %.2f mm from its 1.9 mm CR pad land; it crosses the T18 straight path: %s (T18 is an option); it "
            "lies over the comparator band at y %.2f over x %s (wire over parts, not booked as area)"
            % (t8row["dlab"], " -> ".join("(%.2f, %.2f)" % q for q in dp_), t8row["dressed"], t8row["r7"], d_pads[0],
               TAPS[d_pads[1]][0] + " " + d_pads[1], d_edge, d_reg, d_co5, k_p + 1 - 12 if k_p >= 12 else 22 - k_p,
               q_[0], q_[1], d_post, d_land, "yes" if x_t18 else "no", ln.get("upper", (float("nan"),))[0],
               ", ".join("%.2f-%.2f" % z for z in band_over) or "none"))
        LANE["T8"]["report"] = dict(path=dp_, L=f2(t8row["dressed"]), d_pads=(f2(d_pads[0]), d_pads[1]),
                                    d_edge=f2(d_edge), d_reg5=f2(d_reg), d_co5=f2(d_co5), d_post=f2(d_post),
                                    d_land=f2(d_land), crosses_t18=x_t18, band_over=band_over)
    # ---- revision 4: computed consequences of the open pairs and of the residual-row pairs (DOC A.8 short table)
    dl = {r["tap"]: r["dressed"] for r in rows}
    v_en = V_IO * (1 / R_DRV) / (2 / R_DRV + 1 / R_EN_BODGE)
    i_pp = V_IO / (2 * R_DRV)
    r_w45 = R26 * (dl["T4"] + dl["T11"]) * 1e-3
    r_w67 = R26 * (dl["T6"] + dl["T11"]) * 1e-3
    i_37 = V_IO / (R_DRV + r_w67)
    out("  computed consequences of the open pairs and the residual-row pairs (revision 4; R_DRV %.0f ohm per i.MX "
        "output, ASSUMPTION; tap wires 26 AWG %.1f mOhm/m at their dressed lengths):" % (R_DRV, R26 * 1e3))
    cons_rows = [
        ("F05 T4 - F12 T11", "pin 30 (REGEN_ENABLE, D-BC-RG EN) - pin 17 (CHG_FCCEIL), both push-pull",
         "outputs equal: no current. Outputs opposite: %.1f mA through both drivers (wires %.1f mOhm), %.0f mW in each; "
         "the EN net sits at %.3f V (with the %.0f kOhm EN bodge), above VEN_R max %.1f V, so D-BC-RG turns on, and "
         "pin 17 reads HIGH. The REGEN switch is ON whenever pin 30 OR pin 17 is HIGH (pin 17 HIGH while pin 30 commands "
         "OFF closes REGEN); U121 RGN_ON (trip 1.75-1.88 V) reads OFF at %.2f V" % (i_pp * 1e3, r_w45 * 1e3,
                                                                             i_pp ** 2 * R_DRV * 1e3, v_en,
                                                                             R_EN_BODGE / 1e3, VEN_R_MAX, v_en),
         "none in service: the closed REGEN is not proven by U121 at %.2f V; T-F-12 tap-to-tap check before power-up"
         % v_en),
        ("F07 T6 - F12 T11", "Teensy 3V3 (J1.29, before R175) - pin 17 push-pull",
         "pin 17 HIGH: no current. pin 17 LOW: the driver sinks the 3V3 rail through %.1f mOhm of wire, %.1f mA and "
         "%.0f mW in the driver (rating TODO(verify: i.MX RT1062 datasheet); Teensy 3V3 regulator load TODO(verify: "
         "PJRC)); the node stays at the rail, so CHG_FCCEIL reads HIGH ('FC ceiling confirmed') whatever pin 17 commands"
         % (r_w67 * 1e3, i_37 * 1e3, i_37 ** 2 * R_DRV * 1e3),
         "none in service (no FCCEIL readback); T-F-12 tap-to-tap check before power-up"),
        ("F08 T22 - F09 T8", "BQ29200 OUT (BAL-NOK) - INA253 BT output / pin 41 / U104 IN- (via R140)",
         "no OV: OUT is low and sinks %.0f-%.0f uA at 0.05 V; the INA253 output (%.1f V/A x I_BT) overrides it, so pin 41 "
         "reads the BT current (error <= the sink current into the INA253 output) and N_BAL (via R178) follows the "
         "INA253 level, LOW below the U123 threshold: OVN correct. Pack OV: OUT sources >= %.0f uA at 1.75 V and up to "
         "%.0f mA into a short, against the INA253 output, which INA253A1IPWR.pdf Figure 14 characterises only to "
         "%.0f mA: either the INA253 holds the node near its own level, so N_BAL stays LOW and the BQ29200 pack-OV term "
         "(OVN) is MASKED while the pack is over voltage, or OUT lifts the node toward its %.1f-%.1f V drive level (at "
         "VDD 10 V) and drives pin 41 above its 3.3 V supply through the pad clamp"
         % (BQ_IOL[0] * 1e6, BQ_IOL[1] * 1e6, INA_GAIN, BQ_IOH_MIN * 1e6, BQ_IOH_SC * 1e3, INA_IOUT_FIG * 1e3,
            BQ_VOUT[0], BQ_VOUT[1]),
         "none in service for the masked OVN (it appears only at a pack OV); T-A-01c and the T-F-12 tap-to-tap check "
         "before power-up"),
        ("F09 T8 - F10 T9", "INA253 BT output / pin 41 - GND Kelvin (SNS-BT pad 15)",
         "the INA253 output drives a short to the Kelvin GND (current limit not in INA253A1IPWR.pdf; Figure 14 ends at "
         "%.0f mA); pin 41 and U104 IN- read 0 A: BT current reads 0 A, U104 BT_OK takes the 'no current' state, and the "
         "share loop loses its BT current feedback; the short current returns through the T9 Kelvin wire (%.2f mOhm), "
         "so the U104 reference bottom moves by < 0.1 mV" % (INA_IOUT_FIG * 1e3, R26 * dl["T9"]),
         "BT current plausibility (firmware); T-F-12 tap-to-tap check before power-up"),
    ]
    for pr_, nets, cons_, det_ in cons_rows:
        out("    %s (%s): %s. Detector: %s" % (pr_, nets, cons_, det_))
    # ---- revision 4: the extended exclusion set (A.8 proposed closure) run as a candidate
    viol_ext_adopted = violations(place, r175, ext=True)
    viol_ext = violations(place_ext, r175_ext, ext=True)
    s20_ext = sum(math.hypot(xs[place_ext[t][0]] - TAPS[t][2][0], ys[place_ext[t][1]] - TAPS[t][2][1])
                  if t in place_ext else math.hypot(R7_RESID[t][0] - TAPS[t][2][0], R7_RESID[t][1] - TAPS[t][2][1])
                  for t in SUM20)
    chg_ext = [(t, place[t], place_ext[t]) for t in TAPS_X_R7 if place[t] != place_ext[t]]
    out("  candidate with the extended exclusion set (revision 4; A.8 proposed closure: no EN tap T3/T4/T5 and no F07 (T6) "
        "beside a push-pull pad T10/T11/T21; NOT adopted here): the adopted assignment violates it at %s; the "
        "candidate (R175 rows %d-%d) violates %s; tab X straight sum %.1f mm (adopted %.1f mm, %+.1f mm); 20-tap "
        "straight sum %.1f mm (adopted %.1f mm, %+.1f mm); moves against the adopted assignment: %s"
        % ("; ".join(viol_ext_adopted) or "none", r175_ext[0][1] + 1, r175_ext[1][1] + 1, "; ".join(viol_ext) or "none",
           lsum(place_ext), tot, lsum(place_ext) - tot, s20_ext, s7, s20_ext - s7,
           "; ".join("%s %s (%.2f, %.2f) -> (%.2f, %.2f)" % (t, TAPS[t][0], xs[a[0]], ys[a[1]], xs[b[0]], ys[b[1]])
                     for t, a, b in chg_ext) or "none"))
    cell_x = {}
    r175a_x = next((z for z in r175_ext if adj(place_ext["T6"], z)), r175_ext[0])
    for z in r175_ext:
        cell_x[z] = "R175a" if z == r175a_x else "R175b"
    for t_, p_ in place_ext.items():
        cell_x[p_] = t_
    out("    candidate grid map (row 4 at the top):")
    for r in (3, 2, 1, 0):
        out("      y %.2f  %s" % (ys[r], "  ".join("%-12s" % (("%s/%s" % (cell_x[(c, r)], TAPS[cell_x[(c, r)]][0]))
                                                              if cell_x.get((c, r)) in TAPS else
                                                              (cell_x.get((c, r)) or "-")) for c in range(6))))
    nb_ext = {t_: sorted(cell_x[q] for q in pos if adj(q, p_) and q in cell_x) for t_, p_ in place_ext.items()}
    out("    candidate neighbours: T4 %s; T5 %s; T3 %s; T6 %s; T11 %s; T10 %s; T21 %s; T1 %s; T2 %s"
        % tuple(nb_ext[k] for k in ("T4", "T5", "T3", "T6", "T11", "T10", "T21", "T1", "T2")))
    ft1b = find_feet()["ft1"]["body"]
    over_ft1 = [(t, TAPS[t][0]) for t, s_ in pad_sq.items() if rect_overlap(s_, ft1b)]
    out("  tab X top pads over the FT1 body on the CR underside (x %.3f-%.3f, y %.3f-%.3f): %s (their joints are "
        "soldered after T-A-09 or T-A-09 runs after PM6, D-F1)" % (ft1b[0], ft1b[2], ft1b[1], ft1b[3],
                                                                  ", ".join("%s/%s" % z for z in over_ft1) or "none"))
    dif = [(t, r["mbm"], r["dst"]) for t, r in ((r["tap"], r) for r in rows) if r["mbm"] and
           math.hypot(r["mbm"][0] - r["dst"][0], r["mbm"][1] - r["dst"][1]) > 0.05]
    out("  BRD point vs mb_mech_calc.py TAPS (MIN used the latter): %s"
        % ["%s: BRD (%.3f, %.3f) vs (%.3f, %.3f), %.2f mm apart" % (t, d[0], d[1], m[0], m[1],
                                                                   math.hypot(m[0] - d[0], m[1] - d[1]))
           for t, m, d in dif])
    out("  MIN reported r3 1308.9 -> r7 892.8 mm (-32 %) with the mb_mech_calc points and the field centre (57.08, 61.61)")
    FIELD = dict(xs=xs, ys=ys, env=env, cyd=cyd, place=place, r175=r175, r175_box=r175_box, spare=spare,
                 resid=R7_RESID, t18=t18)
    RJ["g"] = dict(xs=xs, ys=ys, envelope=env, courtyard=cyd, r175_box=r175_box,
                   assignment={t: (r["F"], f2(r["pad"][0]), f2(r["pad"][1]), f2(r["r6"]), f2(r["r7"]), r["crosses"],
                                   f2(r["dressed"]), r["dlab"]) for t, r in ((r["tap"], r) for r in rows)},
                   sum_r6=f2(s6), sum_r6_f08_only=f2(s6f08), sum_r6_field_centre=f2(s6c), sum_r7=f2(s7),
                   sum_r7_dressed=f2(s7d), tab_x_pads=TAPS_X_R7, spare=[(xs[c], ys[r]) for c, r in spare],
                   r175_rows=(r175[0][1] + 1, r175[1][1] + 1), r175a=(xs[r175a[0]], ys[r175a[1]]),
                   violations_rev2=viol_r2, violations_new=viol_new, length_sum_new=f2(tot), length_sum_rev2=f2(base),
                   assignment_changes=[(t, (xs[a[0]], ys[a[1]]), (xs[b[0]], ys[b[1]])) for t, a, b in chg],
                   adjacent_pairs=adj_rows, residual_pairs=res_rows, gap_use=gap_use, pads_over_ft1=over_ft1,
                   t18_candidates=[dict(label=r["lab"], pad=r["p"], straight=f2(r["L"]), crosses_reg5v=r["cr"],
                                        path_to_reg5v=f2(r["dreg"]), pad_lands_crossed=r["land"],
                                        nearest_post=r["post"], centreline_to_post_centre=f2(r["dcl"]),
                                        path_to_post_square=f2(r["dpost"]), courtyard_to_j101=f2(r["dj101"]))
                                   for r in t18rows],
                   t18_pad=t18[1], t18_end_to_reg5v=f2(d_end_reg5), residual={k: v for k, v in R7_RESID.items()})
    RJ["g"].update(t8_lane={k: v for k, v in LANE.get("T8", {}).items() if k != "upper_path"},
                   open_pair_consequences=[dict(pair=a, nets=b, consequence=c, detector=d) for a, b, c, d in cons_rows],
                   ext_candidate=dict(violations_adopted=viol_ext_adopted, violations=viol_ext,
                                      r175_rows=(r175_ext[0][1] + 1, r175_ext[1][1] + 1),
                                      place={t: (xs[c], ys[r]) for t, (c, r) in place_ext.items()},
                                      tabx_sum=f2(lsum(place_ext)), sum20=f2(s20_ext)))
    summ("T8 lane (revision 4)", "%s, %.1f mm dressed; jacket %.2f mm from the nearest other residual pad, %.2f mm inside "
         "the CR low edge; a low-edge lane is infeasible by %.2f mm"
         % (t8row["dlab"], t8row["dressed"], LANE["T8"]["report"]["d_pads"][0], LANE["T8"]["report"]["d_edge"],
            LANE["T8"]["low"][0] - LANE["T8"]["low"][1]), "H.23(g)")
    summ("open adjacent pairs (revision 4)", "F05-F12: EN net %.3f V > VEN_R max %.1f V, %.1f mA contention; F07-F12: "
         "%.1f mA into pin 17 when LOW; F08-F09: BQ29200 OV term can be masked by the INA253 output"
         % (v_en, VEN_R_MAX, i_pp * 1e3, i_37 * 1e3), "H.23(g)")
    summ("extended exclusion candidate (revision 4)", "violations %s; 20-tap straight sum %.1f mm (%+.1f mm); not adopted"
         % ("; ".join(viol_ext) or "none", s20_ext, s20_ext - s7), "H.23(g)")
    summ("tab X tap field pad centres", "x %s, y %s" % (xs, ys), "H.23(g)")
    summ("tab X pad assignment (D-F4)", "%d pads + R175 (rows %d-%d of column 1; R175a at (%.2f, %.2f)); spare positions "
         "%s; D-F4 exclusions violated: %s (r7 rev 2: %s); moves against r7 rev 2: %s"
         % (len(TAPS_X_R7), r175[0][1] + 1, r175[1][1] + 1, xs[r175a[0]], ys[r175a[1]],
            [(xs[c], ys[r]) for c, r in spare], "; ".join(viol_new) or "none", "; ".join(viol_r2) or "none",
            "; ".join("%s -> (%.2f, %.2f)" % (t, xs[b[0]], ys[b[1]]) for t, a, b in chg) or "none"), "H.23(g)")
    summ("adjacent-pad short table (D-F4)", "%d orthogonal grid pairs, %d FORBIDDEN; residual row: F08-F09 and F09-F10 "
         "adjacent, F10-F22 not" % (len(adj_rows), n_forb), "H.23(g)")
    summ("T18 pad (A2, B3)", "F22 at (%.2f, %.2f) on the footprint low row, straight %.2f mm to CO-5V pad 1; passes "
         "beside (not over) the pin-%d post (%.3f mm from the post square); pad courtyard %.2f mm from the J101 box; "
         "every candidate ends at CO-5V pad 1, %.3f mm from the REG-5V box (shortest candidate %s, %.2f mm, rejected: "
         "courtyard %.2f mm from the J101 box); residual pads F08 (T22), F09 (T8), F10 (T9), F22 (T18)"
         % (t18[1][0], t18[1][1], t18[2], t18r["post"], t18r["dpost"], t18r["dj101"], d_end_reg5,
            "(%.2f, %.2f)" % sh["p"], sh["L"], sh["dj101"]), "H.23(g)")
    t8r = next(r for r in rows if r["tap"] == "T8")
    summ("tap straight-length sum (20 taps)", "r6 %.1f mm -> r7 %.1f mm (%+.1f %%); dressed on the legal path %.1f mm "
         "(D-F4); T8 crosses the REG-5V box (straight %.1f mm, dressed %.1f mm: %s)"
         % (s6, s7, 100 * (s7 / s6 - 1), s7d, t8r["r7"], t8r["dressed"], t8r["dlab"]), "H.23(g)")
    return FIELD


# ======================================================================================================================
# H.23(h) thermal band
# ======================================================================================================================
BAND = 6.4         # BASIS section 1: thermal band = part of tab X within 6.4 mm of the MB 5V copper rim


def sec_h():
    head("H.23(h) thermal band: tab X distances from the MB 5V copper rim; the 6.4 mm band boundary")
    sh5 = five_v_shapes()
    out("5V layer-1 copper (BRD): %s" % "; ".join(s["label"] for s in sh5 if mbn.bbox(s["pts"])[3] > 45))
    out("(the 5V layer-16 trace (60.66, 56.85)-(76.20, 75.69) lies on the MB underside and is not part of the layer-1 rim)")
    F = find_feet()
    fx = FIELD
    classes = {
        "tab X low edge y 56.30": (TAB_X[0], TAB_X[1], TAB_X[2], TAB_X[1] + 1e-6),
        "tap field row 1 (low pad edges)": (fx["env"][0], fx["env"][1], fx["env"][2], fx["env"][1] + 1e-6),
        "tap field row 2 pads": (fx["env"][0], fx["ys"][1] - PAD / 2, fx["env"][2], fx["ys"][1] + PAD / 2),
        "tap field row 3 pads": (fx["env"][0], fx["ys"][2] - PAD / 2, fx["env"][2], fx["ys"][2] + PAD / 2),
        "tap field row 4 pads": (fx["env"][0], fx["ys"][3] - PAD / 2, fx["env"][2], fx["ys"][3] + PAD / 2),
        "R175 courtyard": fx["r175_box"],
        "FT1 foot body": F["ft1"]["body"],
        "tab X top edge y 68.30": (TAB_X[0], TAB_X[3] - 1e-6, TAB_X[2], TAB_X[3]),
        "tab X right edge x 65.00": (TAB_X[2] - 1e-6, TAB_X[1], TAB_X[2], TAB_X[3]),
        "tab X bottom courtyard limit y 56.80": (TAB_X[0], TAB_X[1] + CY, TAB_X[2] - CY, TAB_X[1] + CY + 1e-6),
    }
    res = {}
    for k, r in classes.items():
        d = d5v_rect(r)
        # farthest point of the class from the rim (for areas)
        far = max(d5v(x, y) for x in (r[0], (r[0] + r[2]) / 2, r[2]) for y in (r[1], (r[1] + r[3]) / 2, r[3]))
        res[k] = (d, far)
        # r7 review 7: a span that straddles the 6.4 mm boundary is 'crossing', not 'inside'
        lab = "inside the band" if far <= BAND else ("outside" if d > BAND else "crossing the band boundary")
        out("  %-38s nearest %6.3f mm, farthest %6.3f mm -> %s" % (k, d, far, lab))
    out("Band boundary inside tab X (largest y with distance <= %.1f mm, per x):" % BAND)
    bnd = []
    x = TAB_X[0]
    while x <= TAB_X[2] + 1e-9:
        yb = None
        y = TAB_X[1]
        while y <= TAB_X[3] + 1e-9:
            if d5v(x, y) <= BAND:
                yb = y
            y += 0.02
        bnd.append((round(x, 2), round(yb, 2) if yb is not None else None))
        x += 1.0
    out("  " + ", ".join("x %.1f: y %s" % (a, ("%.2f" % b) if b is not None else "-") for a, b in bnd))
    G = Grid(TAB_X[0], TAB_X[1], TAB_X[2], TAB_X[3], 0.05)
    nb = 0
    for j in range(G.ny):
        for i in range(G.nx):
            if d5v(G.cx(i), G.cy(j)) <= BAND:
                nb += 1
    a_band = nb * G.cell
    out("  band area inside tab X %.1f of %.1f mm2 (%.0f %%)" % (a_band, 195.6, 100 * a_band / 195.6))
    out("Content rule (BASIS section 1): the band carries pads, wires, the RTV bead and temperature-insensitive passives "
        "(R175, 1 % logic series resistors and pull-downs) only. Thermal estimate at 1/5/10 mm: 4.5-23.5 / 3.3-17.0 / "
        "2.4-11.9 C (mb_mechanical.md Table 4, ESTIMATE; MS4 replaces it).")
    RJ["h"] = dict(classes={k: (f2(v[0]), f2(v[1])) for k, v in res.items()}, boundary=bnd, band_area=f2(a_band))
    summ("thermal band in tab X", "boundary y %s..%s across x 48.7-65.0; band area %.1f mm2; tab X low edge %.3f mm, "
         "top edge %.3f mm from the 5V rim" % (min(b for a, b in bnd if b), max(b for a, b in bnd if b), a_band,
                                               res["tab X low edge y 56.30"][0], res["tab X top edge y 68.30"][0]),
         "H.23(h)")


# ======================================================================================================================
# H.23(i) feet, stiffness, first modes and pin loads (ORDER OF MAGNITUDE)
# ======================================================================================================================
E_LAM = 20e3          # N/mm2 = 20 GPa, MBM eq. 3 ASSUMPTION (TODO(verify: fab laminate datasheet), MS6)
RHO = 1850.0          # kg/m3, MBM eq. 3
T_CR = 1.6            # mm, CR thickness (DOC PM4 ASSUMPTION; TODO(verify: CR fab stack-up), MS6)
MF = (1.0, 2.0)       # part mass factor, MBM eq. 3
E_RTV = (1.0, 3.0)    # MPa, BASIS D3 ASSUMPTION; TODO(verify: RTV datasheet)
T_BED = (0.15, 0.30, 0.45)     # mm, BASIS D3: 0.30 +- 0.15
# r7 review 7, D-F1: controlled CR-side bond and the vertical tolerance budget of the bed thickness
T_BOND = 0.05         # mm, acrylic transfer tape CR-side bond (D-F1; TODO(verify: tape datasheet, temperature rating))
H_HDR = 2.54          # mm, header plastic body height = CR underside to sheet (BASIS D2; TODO(verify: Samtec TSW drawing))
H_F = H_HDR - T_BED[1] - T_BOND                    # foot block height, 2.19 mm (D-F1)
TOL_BODY = 0.13       # mm, +- header body height (D-F1; TODO(verify: Samtec TSW drawing))
BOW = 0.0075          # CR local bow, 0.75 % x span from the nearer pin column/row to the foot (IPC-6012 class bow/twist)
TOL_BLOCK = (-0.05, 0.0)   # mm, foot block tolerance +0/-0.05 (D-F1)
TOL_TAPE = (0.0, 0.05)     # mm, pressed transfer-tape thickness (0-0.05; nominal 0.05) (D-F1)
GATE = (0.15, 0.45)   # mm, PM4 (2d) feelers: 0.15 enters, 0.45 does not (D-F1)
A_FOOT = FOOT * FOOT
M_MAIN = (5.0, 10.0)  # g, main CR + headers, mb_pinload.py ASSUMPTION
RHO_A = (0.6, 0.8)    # g/cm2 populated areal mass, mb_pinload.py ASSUMPTION
SHOCK = (10.0, 30.0)  # g, mb_pinload.py (30 g ASSUMED, MS5)
P_PUSH = 10.0         # N handling push, MIN r7_handling.py
BETA1, SIGMA1 = 1.8751, 0.7341


def phi1(xi):
    b = BETA1 * xi
    return (math.cosh(b) - math.cos(b) - SIGMA1 * (math.sinh(b) - math.sin(b))) / \
        (math.cosh(BETA1) - math.cos(BETA1) - SIGMA1 * (math.sinh(BETA1) - math.sin(BETA1)))


def f1_cant(L_mm, mf, beta=1.875):
    L = L_mm * 1e-3
    return beta ** 2 / (2 * math.pi * L * L) * math.sqrt(E_LAM * 1e6 * (T_CR * 1e-3) ** 2 / (12 * RHO * mf))


def defl_unit(a, xi, EI):
    """Deflection at a due to a unit load at xi on a cantilever clamped at 0 (mm/N)."""
    if xi >= a:
        return a * a * (3 * xi - a) / (6 * EI)
    return xi * xi * (3 * a - xi) / (6 * EI)


def reaction(EI, a, ks, load):
    """Spring reaction at a for a load list [(position, force N)]; ks in N/mm."""
    d = sum(F * defl_unit(a, xi, EI) for xi, F in load)
    return d / (a ** 3 / (3 * EI) + 1.0 / ks)


def pin_group():
    xc = sum(p[0] for p in PINS) / 22
    yc = sum(p[1] for p in PINS) / 22
    sxx = sum((p[0] - xc) ** 2 for p in PINS)
    syy = sum((p[1] - yc) ** 2 for p in PINS)
    return xc, yc, sxx, syy


def worst_pin(forces):
    xc, yc, sxx, syy = pin_group()
    F = sum(f for _, _, f in forces)
    My = sum(f * (x - xc) for x, _, f in forces)
    Mx = sum(f * (y - yc) for _, y, f in forces)
    loads = [F / 22 + My * (p[0] - xc) / sxx + Mx * (p[1] - yc) / syy for p in PINS]
    i = max(range(22), key=lambda k: abs(loads[k]))
    return abs(loads[i]), PINS[i]


def sec_i():
    head("H.23(i) far-end support feet FT1/FT2: spots, copper under them, heights, stiffness, first modes, pin loads "
         "(ORDER OF MAGNITUDE)")
    F = find_feet()
    out("Rules (BASIS D3): body >= %.1f mm inside the r7 outline; no MB via pad (any net) under the body; every non-GND "
        "MB layer-1 copper rim (polygon outline width, %.4f mm via pads, square CHG pads) >= %.1f mm from the body; every "
        "MB part box >= %.1f mm from the body. The first-run 4 x 4 scan below uses a 0.10 mm grid (%d spots for 4 x 4)."
        % (CY, 2 * VIA_R, FOOT_CU, FOOT_CU, F["ncand"]))
    out("A1 search (BASIS section 10): body width (x) %.1f-%.1f mm and height (y) %.1f-%.1f mm in 0.1 mm steps; the body "
        "lies inside its tab rectangle (the tab root line is interior, not an outline edge). Placement tolerance t of a "
        "centre = the largest t such that the body moved by any (dx, dy) in [-t, t] x [-t, t] meets the rule; the union "
        "of those moved bodies is the body grown by t on every side, so t is computed exactly as the largest growth "
        "that meets the rule. tx = the largest x half-range of moves with the y half-range held at t, ty likewise, so "
        "min(tx, ty) = t. Stage 1 (raster %.2f mm, every centre of the grid, half-cell convention, error about +-0.02 "
        "mm) gives the best t of every size; stage 2 (exact distances, bisection to 1e-4 mm) hill-climbs the centre on "
        "the %.2f mm grid, then resolves a plateau of equal t by the tie rule (FT1: larger x; FT2: centred) and "
        "finally moves the centre y off the grid to the exact max-min y (golden-section search on t(y), BASIS section "
        "11 B1). Adopted FT1 = the largest bed area with tx >= %.2f and ty >= %.2f mm (a tip-zone centre x >= %.1f is "
        "preferred when it also meets %.2f mm). Adopted FT2 (BASIS section 11 B2) = the 4 x 4 body moved from the "
        "max-min centre toward the far edge to the largest lever (distance from the pin-11 row y %.3f) with t >= %.2f "
        "mm; the max-min result is kept as a labelled alternative."
        % (FOOT_WS[0], FOOT_WS[-1], FOOT_HS[0], FOOT_HS[-1], FRES, FRES, TOL_REQ, TOL_REQ, TIP_X, TOL_REQ, PIN11_Y,
           TOL_REQ))
    st = F["start"]
    out("Start point (62.70, 61.26) (mb_support_spots_out.txt; MIN keep-out x 60.70-64.70, y 59.26-63.26): via pads "
        "under the body %s; non-GND copper clearance %.3f mm (%s). MIN reported 'over no via' from via centres only."
        % (st["vias"] or "none", st["cu_clear"], st["cu_who"]))
    out("4 x 4 mm, via-free spots in tab X by copper-clearance threshold (count, largest-x centre): %s"
        % ", ".join("%.2f mm: %d %s" % (k, F["feas"][k], tuple(round(v, 2) for v in F["feas_maxx"][k])
                                         if F["feas_maxx"][k] else "-") for k in sorted(F["feas"], reverse=True)))
    b44 = F["best_tip44"]
    if b44:
        out("  best 4 x 4 spot in the tip zone (x >= %.1f), copper clearance relaxed: centre (%.2f, %.2f), clearance "
            "%.3f mm (%s)" % (TIP_X, b44["centre"][0], b44["centre"][1], b44["cu_clear"], b44["cu_who"]))
    # ---- A1 candidate tables
    cand_json = {}
    for nm in ("FT1", "FT2"):
        S = F["search"][nm]
        tb = S["table"]
        out("")
        out("%s candidate sizes (%s): stage-1 best tolerance t = min(tx, ty) in mm per body size (rows: height y, "
            "columns: width x; '-' = no compliant centre)%s:" % (nm, FOOT_TAB[nm]["tab"],
                                                                 "; second figure = best t with the centre in the tip "
                                                                 "zone x >= %.1f where it differs" % TIP_X
                                                                 if nm == "FT1" else ""))
        out("  h \\ w " + "".join("%8.1f" % w for w in FOOT_WS))
        for h in FOOT_HS:
            cells = []
            for w in FOOT_WS:
                r = tb[(w, h)]
                s_ = "%.2f" % r["t"] if r["t"] >= 0 else "-"
                if nm == "FT1" and r["t"] >= 0 and r["t_tip"] is not None and abs(r["t_tip"] - r["t"]) > 0.005:
                    s_ += "/%s" % ("%.2f" % r["t_tip"] if r["t_tip"] >= 0 else "-")
                cells.append("%8s" % s_)
            out("  %4.1f  " % h + "".join(cells))
        out("  stage-2 exact results (sizes in descending bed area down to the adopted area; area mm2, best centre, t, "
            "tx, ty, binding feature):")
        rows_j = []
        for s_, e in sorted(S["exact"].items(), key=lambda kv: (-kv[1]["area"], -kv[0][0])):
            for key in ("best", "tip"):
                p = e.get(key)
                if p is None or (key == "tip" and p is e["best"]):
                    continue
                out("    %.1f x %.1f  %5.2f mm2  centre (%.2f, %.3f)%s  t %.3f  tx %.3f  ty %.3f  %s  [%s]"
                    % (e["w"], e["h"], e["area"], p["c"][0], p["c"][1],
                       (" tip zone" if p["c"][0] >= TIP_X else " root side") if nm == "FT1" else "",
                       p["t"], p["tx"], p["ty"], "meets %.2f" % TOL_REQ if p["t"] >= TOL_REQ else "FAILS %.2f" % TOL_REQ,
                       p["bind"]))
                rows_j.append(dict(w=e["w"], h=e["h"], area=e["area"], which=key, centre=p["c"], t=f2(p["t"]),
                                   tx=f2(p["tx"]), ty=f2(p["ty"]), bind=p["bind"]))
        cand_json[nm] = dict(stage1={"%.1fx%.1f" % k: (f2(v["t"]), v["c"], f2(v["t_tip"]) if v["t_tip"] is not None
                                                       else None) for k, v in tb.items()}, stage2=rows_j)
    F["cand_json"] = cand_json
    kos = {n: (k, lane) for n, k, lane in foot_keepouts()}
    out("")
    for nm in ("ft1", "ft2"):
        f = F[nm]
        k, lane = kos[nm.upper()]
        out("%s ADOPTED: body %.1f x %.1f mm (bed area %.2f mm2), centre (%.2f, %.3f), body x %.3f-%.3f, y %.3f-%.3f; "
            "tolerance t = %.3f mm, tx %.3f / ty %.3f mm (binding: %s)%s; via pads under: %s; nearest non-GND copper rim "
            "%s; nearest MB part box %.2f mm (%s); foot keep-out (body + %.1f mm) x %.3f-%.3f, y %.3f-%.3f (%.1f x %.1f "
            "mm), RTV access lane %s"
            % (nm.upper(), f["w"], f["h"], f["w"] * f["h"], f["centre"][0], f["centre"][1], f["body"][0], f["body"][2],
               f["body"][1], f["body"][3], f["t"], f["tx"], f["ty"], f["bind"],
               ("; zone: %s" % f["zone"]) if nm == "ft1" else ("; lever a = %.3f mm from the pin-11 row"
                                                               % (f["centre"][1] - PIN11_Y)), f["vias"] or "none",
               ("%.3f mm (%s)" % (f["cu_clear"], f["cu_who"])) if f["cu_who"] else "> 3 mm (none in the search radius)",
               f["part_clear"], f["part"], FOOT_KO, k[0], k[2], k[1], k[3], k[2] - k[0], k[3] - k[1],
               ("x %.3f-%.3f, y %.3f-%.3f (to the tab X top edge; unchanged method)" % (lane[0], lane[2], lane[1],
                                                                                        lane[3])) if lane else
               ("none (BASIS section 11 B2: bedded through the %.1f mm fill hole at the foot centre)" % FILL_D
                if nm == "ft2" else "none (keep-out reaches the tab edge)")))
    al = F["alts"]
    for a_ in al.values():          # bisection residue of a spot that sits exactly on a limit: print 0.000, not -0.000
        for k_ in ("t", "tx", "ty", "rule_margin"):
            if a_.get(k_) is not None and abs(a_[k_]) < 5e-4:
                a_[k_] = 0.0

    def alt_line(lab, a):
        if a["t"] is None:
            return ("%s: %.1f x %.1f mm at (%.2f, %.2f) VIOLATES the rule (margin %.3f mm: %s; copper clearance %.3f "
                    "mm); tolerances not applicable" % (lab, a["w"], a["h"], a["centre"][0], a["centre"][1],
                                                         a["rule_margin"], a["rule_who"], a["cu_clear"]))
        sl = a["slack"]
        return ("%s: %.1f x %.1f mm at (%.2f, %.2f) meets the rule with margin %.3f mm (%s); tolerance tx %.3f / ty "
                "%.3f mm (t = %.3f); one-sided slack +x %.3f, -x %.3f, +y %.3f, -y %.3f mm"
                % (lab, a["w"], a["h"], a["centre"][0], a["centre"][1], a["rule_margin"], a["rule_who"], a["tx"],
                   a["ty"], a["t"], sl["+x"], sl["-x"], sl["+y"], sl["-y"]))
    out("Labelled alternatives (not adopted):")
    out("  " + alt_line("FT1 alternative A (r7 first run, 4.0 x 2.0)", al["old_ft1"]))
    out("  " + alt_line("FT1 alternative B (relaxed 4 x 4 over masked signal traces; operator option only, the D3 "
                        "MB-mask fallback is unavailable there)", al["relax44"]))
    out("  " + alt_line("FT2 alternative (r7 first run, 4 x 4 at the far edge)", al["old_ft2"]))
    out("  " + alt_line("FT2 alternative M (second run, A1 max-min centre at mid-height of tab Y, lever a = %.3f mm)"
                        % (al["ft2_mid"]["centre"][1] - PIN11_Y), al["ft2_mid"]))
    f1_ = F["ft1"]
    e17 = F["search"]["FT1"]["exact"].get((f1_["w"], round(f1_["h"] + 0.1, 1)))
    p17 = (e17.get("pick") or e17.get("tip") or e17["best"]) if e17 else None
    out("FT1 decision: %s. At the exact max-min centre y %.3f the %.1f x %.1f body reaches t = %.3f mm (tx %.3f, ty "
        "%.3f); the next height, %.1f x %.1f, reaches t = %.3f mm at y %.3f (< %.2f mm), so %.1f mm is the largest "
        "compliant height. The 0.02 mm grid centre y %.2f gave t %.3f mm."
        % (F["rule"], f1_["centre"][1], f1_["w"], f1_["h"], f1_["t"], f1_["tx"], f1_["ty"], f1_["w"],
           round(f1_["h"] + 0.1, 1), p17["t"] if p17 else float("nan"), p17["c"][1] if p17 else float("nan"),
           TOL_REQ, f1_["h"], f1_.get("c_grid", f1_["centre"])[1], f1_.get("t_grid", f1_["t"])))
    f2a = F["ft2"]
    out("FT2 decision: %s. The trimmed tab Y has no non-GND copper and no via under it (H.23(c)), so the tolerance is "
        "set by the outline inset at the far edge (binding: %s) and the tab root line; the far spot (%.2f, %.3f) has "
        "lever a = %.3f mm from the pin-11 row (mid-height max-min spot %.3f mm; first-run far-edge spot %.3f mm), t "
        "= %.3f mm, tx %.3f / ty %.3f mm, one-sided slack +x %.3f, -x %.3f, +y %.3f, -y %.3f mm."
        % (F["rule2"], f2a["bind"], f2a["centre"][0], f2a["centre"][1], f2a["centre"][1] - PIN11_Y,
           al["ft2_mid"]["centre"][1] - PIN11_Y, OLD_FT2[1] - PIN11_Y, f2a["t"], f2a["tx"], f2a["ty"],
           f2a["slack"]["+x"], f2a["slack"]["-x"], f2a["slack"]["+y"], f2a["slack"]["-y"]))
    # ---- BASIS section 11 B2: the FT2 fill hole; B1: the FT1 fallback sheet cut-out
    fh = fill_hole()
    hx, hy = fh["c"]
    hr = fh["d"] / 2
    hb = (hx, hy, hx, hy)
    cu_h = min(((d_rect_shape(hb, s) - hr, s["label"]) for s in NONGND), key=lambda z: z[0])
    via_h = min(((math.hypot(v["x"] - hx, v["y"] - hy) - via_dia(v) / 2 - hr, v["net"], v["x"], v["y"])
                 for v in VIAS), key=lambda z: z[0])
    part_h = min(((rect_dist(p["bbox"], hb) - hr, p["name"]) for p in PARTS), key=lambda z: z[0])
    fb_ = f2a["body"]
    h_in_body = min(hx - fb_[0], fb_[2] - hx, hy - fb_[1], fb_[3] - hy) - hr
    ring_out = min(d_rect_seg(hb, a, b) for a, b in edges(OUTLINE)) - fh["ko_r"]
    out("FT2 fill hole (BASIS section 11 B2): %.1f mm NPTH through tab Y at the foot centre (%.2f, %.3f), RTV injected "
        "from the CR top with a blunt needle; the hole lies inside the foot body with %.3f mm to the body edge, so the "
        "injected RTV lands on the foot. The hole is a CR feature only: under its plan projection the MB carries GND "
        "pour under solder mask (nearest non-GND copper rim %.2f mm from the hole edge (%s); nearest via pad %.2f mm "
        "(%s at (%.3f, %.3f)); nearest MB part box %.2f mm (%s)), and the foot body covers it on the MB side, so no MB "
        "feature bears on it. CR-top keep-out: %.1f mm copper and part ring = %.1f mm disc, %.3f mm inside the r7 "
        "outline, booked in the top area (H.23(e))."
        % (fh["d"], hx, hy, h_in_body, cu_h[0], cu_h[1], via_h[0], via_h[1], via_h[2], via_h[3], part_h[0], part_h[1],
           FILL_KO, 2 * fh["ko_r"], ring_out))
    k1 = kos["FT1"][0]
    cu_k = sorted(((d_rect_shape(k1, s), s["label"], s["net"]) for s in NONGND), key=lambda z: z[0])
    exposed = [z for z in cu_k if z[0] <= 0.0]
    vias_k = [(v["net"], f2(v["x"]), f2(v["y"])) for v in VIAS if d_rect_pt(k1, v["x"], v["y"]) < via_dia(v) / 2]
    parts_k = [p["name"] for p in PARTS if rect_overlap(p["bbox"], k1)]
    out("FT1 fallback sheet cut-out (BASIS D3 / section 11 B1) = the FT1 keep-out rectangle x %.3f-%.3f, y %.3f-%.3f "
        "(%.1f x %.1f mm): non-GND copper rim exposed: %s; nearest non-GND rim %.3f mm outside the cut-out (%s), so the "
        "sheet still covers the MPPT-DISABLE trace by that margin; MB via pads inside the cut-out: %s; MB part boxes: "
        "%s."
        % (k1[0], k1[2], k1[1], k1[3], k1[2] - k1[0], k1[3] - k1[1],
           ("YES: " + ", ".join(z[1] for z in exposed)) if exposed else "none", cu_k[0][0], cu_k[0][1],
           vias_k or "none", parts_k or "none"))
    F["fill"] = dict(centre=fh["c"], d=fh["d"], ko_disc=2 * fh["ko_r"], in_body=f2(h_in_body), cu=(f2(cu_h[0]), cu_h[1]),
                     via=(f2(via_h[0]), via_h[1]), part=(f2(part_h[0]), part_h[1]), ring_to_outline=f2(ring_out))
    F["ft1_cutout"] = dict(rect=k1, exposed=[z[1] for z in exposed], nearest=(f2(cu_k[0][0]), cu_k[0][1]),
                           vias=vias_k, parts=parts_k)
    # copper directly under each foot (rim area by net) and GND vias near
    for nm in ("ft1", "ft2"):
        f = F[nm]
        G = Grid(f["body"][0], f["body"][1], f["body"][2], f["body"][3], 0.02)
        under = {}
        for s in NONGND:
            if rect_dist(mbn.bbox(s["pts"]), f["body"]) > s["r"]:
                continue
            m = G.new()
            G.mark_shape(m, s, 0.0)
            a = count(m) * G.cell
            if a > 0:
                under[s["net"]] = under.get(s["net"], 0.0) + a
        within = sorted({s["net"] for s in NONGND if clearance(s, rpoly(f["body"])) < FOOT_CU})
        out("  %s: non-GND copper directly under the body %s; nets within %.1f mm: %s; the rest is MB GND pour under "
            "solder mask" % (nm.upper(), {k: round(v, 2) for k, v in under.items()} or "none", FOOT_CU,
                             within or "none"))
        f["under"] = under
        f["within"] = within
    # heights (r7 review 7, D-F1): controlled CR-side bond, tolerance budget, PM4 (2d) gate
    out("Foot height (D-F1): h_f = %.2f - t_bed - t_bond = %.2f - %.2f - %.2f = %.2f mm (block tolerance +0/%.2f mm); "
        "CR-side bond = %.2f mm acrylic transfer tape (TODO(verify: tape datasheet, temperature rating)); the header "
        "bodies and the feet both stand on the sheet, so t_bed does not depend on the MB, CR or sheet thickness (CR "
        "underside 2.665 mm above the MB, sheet 0.125 mm, BASIS D2/D3). (**superseded in r7:** h_f = 2.54 - t_bed "
        "= 2.24 mm with a zero-thickness RTV bond, review 7 D-F1.)" % (H_HDR, H_HDR, T_BED[1], T_BOND, H_F, TOL_BLOCK[0], T_BOND))
    tol_rows = {}
    for nm, lever, lab in (("FT1", F["ft1"]["centre"][0] - 45.998, "x from the 1x10 column x 45.998"),
                           ("FT2", F["ft2"]["centre"][1] - PIN11_Y, "y from the pin-11 row y %.3f" % PIN11_Y)):
        bow = BOW * lever
        nom = H_HDR - H_F - T_BOND
        mean = nom - 0.5 * (TOL_BLOCK[0] + TOL_BLOCK[1]) + (T_BOND - 0.5 * (TOL_TAPE[0] + TOL_TAPE[1]))
        halfs = (TOL_BODY, bow, 0.5 * (TOL_BLOCK[1] - TOL_BLOCK[0]), 0.5 * (TOL_TAPE[1] - TOL_TAPE[0]))
        wc = (nom - TOL_BODY - bow - TOL_BLOCK[1] - (T_BOND - TOL_TAPE[1]),
              nom + TOL_BODY + bow - TOL_BLOCK[0] + (T_BOND - TOL_TAPE[0]))
        rss = math.sqrt(sum(h * h for h in halfs))
        # Monte-Carlo with uniform contributors (deterministic seed): share of builds inside the PM4 (2d) gate
        rng = random.Random(7)
        n_mc, n_in, n_lo, n_hi = 200000, 0, 0, 0
        for _ in range(n_mc):
            t = (nom + rng.uniform(-TOL_BODY, TOL_BODY) + rng.uniform(-bow, bow) - rng.uniform(*TOL_BLOCK)
                 + (T_BOND - rng.uniform(*TOL_TAPE)))
            if t <= GATE[0]:
                n_lo += 1
            elif t >= GATE[1]:
                n_hi += 1
            else:
                n_in += 1
        tol_rows[nm] = dict(lever=lever, bow=bow, nom=nom, mean=mean, wc=wc, rss=rss, rss_band=(mean - rss, mean + rss),
                            p_in=n_in / n_mc, p_lo=n_lo / n_mc, p_hi=n_hi / n_mc)
        out("  %s vertical tolerance budget of t_bed: header body +-%.2f (TODO(verify: Samtec TSW drawing)); CR local bow "
            "0.75 %% x %.3f mm (%s) = +-%.3f; block +0/%.2f -> t_bed +0..+%.2f; tape %.2f-%.2f -> t_bed +0..+%.2f. "
            "Nominal %.3f mm, mean %.3f mm; worst case %.3f-%.3f mm; RSS (half-ranges about the mean) %.3f +- %.3f = "
            "%.3f-%.3f mm. PM4 (2d) gate %.2f / %.2f mm feelers (D-F1): Monte-Carlo with uniform contributors "
            "(200 000 builds, ORDER OF MAGNITUDE) %.1f %% pass, %.1f %% at or below %.2f (foot too tall: re-make), "
            "%.1f %% at or above %.2f (foot too short: re-make)"
            % (nm, TOL_BODY, lever, lab, bow, TOL_BLOCK[0], -TOL_BLOCK[0], TOL_TAPE[0], TOL_TAPE[1],
               TOL_TAPE[1] - TOL_TAPE[0], nom, mean, wc[0], wc[1], mean, rss, mean - rss, mean + rss, GATE[0], GATE[1],
               100 * n_in / n_mc, 100 * n_lo / n_mc, GATE[0], 100 * n_hi / n_mc, GATE[1]))
    out("  the worst case reaches below the %.2f mm gate minimum (no bed, a hard prop) and above the %.2f mm gate maximum; "
        "the PM4 (2d) dry-seat gate before the 22 joints are soldered rejects those builds, so the k_s range below "
        "(t_bed %.2f-%.2f mm) is the GATED range, not a tolerance-free claim" % (GATE[0], GATE[1], T_BED[0], T_BED[2]))
    F["tol"] = tol_rows
    # stiffness
    tabs = {
        "tab X": dict(L=TAB_X[2] - 45.998, b=TAB_X[3] - TAB_X[1], root=TAB_X[0] - 45.998,
                      a=F["ft1"]["centre"][0] - 45.998, tip=(TAB_X[2], (TAB_X[1] + TAB_X[3]) / 2),
                      model="cantilever clamped at the 1x10 pin column x 45.998 (MBM eq. 3), width = tab X height 12.0 mm",
                      area=(TAB_X[2] - TAB_X[0]) * (TAB_X[3] - TAB_X[1]),
                      cg=((TAB_X[0] + TAB_X[2]) / 2, (TAB_X[1] + TAB_X[3]) / 2), foot=F["ft1"]["centre"]),
        "tab Y": dict(L=TAB_Y[3] - 64.484, b=TAB_Y[2] - TAB_Y[0], root=TAB_Y[1] - 64.484,
                      a=F["ft2"]["centre"][1] - 64.484, tip=(F["ft2"]["centre"][0], TAB_Y[3]),   # D-F1: grip in line
                      # with FT2 (x 28.00); r7 rev 2 used the +y edge midpoint x 27.63 with a stale x 28.00 label
                      model="plate edge-cantilever clamped along the pin-11 row y 64.484 (mb_pinload.py), width = tab Y "
                            "width 19.86 mm; upper estimate (only pin 11 lies on that line)",
                      area=(TAB_Y[2] - TAB_Y[0]) * (TAB_Y[3] - TAB_Y[1]) - CHAMFER ** 2 / 2,
                      cg=((TAB_Y[0] + TAB_Y[2]) / 2, (TAB_Y[1] + TAB_Y[3]) / 2), foot=F["ft2"]["centre"]),
    }
    areas = {"tab X": F["ft1"]["w"] * F["ft1"]["h"], "tab Y": F["ft2"]["w"] * F["ft2"]["h"]}
    perim = {"tab X": 2 * (F["ft1"]["w"] + F["ft1"]["h"]), "tab Y": 2 * (F["ft2"]["w"] + F["ft2"]["h"])}
    KS = {tn: dict(all=[e * areas[tn] / tt for e in E_RTV for tt in T_BED], nom=[e * areas[tn] / T_BED[1] for e in E_RTV])
          for tn in areas}
    for tn in ("tab X", "tab Y"):
        S = areas[tn] / (perim[tn] * T_BED[1])
        out("RTV bed under the %s foot: k_s = E_RTV x A / t_bed (BASIS D3), A %.1f mm2, E %s MPa (ASSUMPTION), t %s mm -> "
            "%.0f-%.0f N/mm (nominal t: %.0f-%.0f N/mm). Bonded-thin-layer correction (Gent, E_c = E (1 + 2 S^2), "
            "S = A/(perimeter t) = %.2f at 0.30 mm) would raise k_s up to x%.0f: an upper-bound sensitivity only."
            % (tn, areas[tn], E_RTV, T_BED, min(KS[tn]["all"]), max(KS[tn]["all"]), KS[tn]["nom"][0], KS[tn]["nom"][1],
               S, 1 + 2 * S * S))
    res = {}
    for tn, t in tabs.items():
        ks_all, ks_nom = KS[tn]["all"], KS[tn]["nom"]
        I = t["b"] * T_CR ** 3 / 12.0
        EI = E_LAM * I
        k_tip = 3 * EI / t["L"] ** 3
        k_a = 3 * EI / t["a"] ** 3
        out("")
        out("--- %s: %s; L %.3f mm, foot at a = %.3f mm" % (tn, t["model"], t["L"], t["a"]))
        out("  EI %.0f N mm2 (E %.0f GPa, t %.1f mm); tip stiffness 3EI/L^3 = %.1f N/mm; at the foot 3EI/a^3 = %.1f N/mm"
            % (EI, E_LAM / 1e3, T_CR, k_tip, k_a))
        fr = []
        for mf in MF:
            f1 = f1_cant(t["L"], mf)
            m_beam = RHO * T_CR * 1e-3 * t["b"] * 1e-3 * t["L"] * 1e-3 * mf
            K1 = (2 * math.pi * f1) ** 2 * m_beam / 4.0
            ph = phi1(t["a"] / t["L"])
            props = []
            for ks in (min(ks_all), ks_nom[0], ks_nom[1], max(ks_all)):
                fp = f1 * math.sqrt(1 + ks * 1e3 * ph * ph / K1)
                props.append(min(fp, f1 * (3.927 / 1.875) ** 2))
            fr.append((mf, f1, props, ph))
            out("  m_f %.0f: f1 unpropped %.0f Hz (eq. 3); propped (Rayleigh, mode shape phi(a/L) = %.3f, tip-spring "
                "model, capped at the rigid tip-prop value %.0f Hz): k_s %.0f / %.0f / %.0f / %.0f N/mm -> %s Hz"
                % (mf, f1, ph, f1 * (3.927 / 1.875) ** 2, min(ks_all), ks_nom[0], ks_nom[1], max(ks_all),
                   " / ".join("%.0f" % v for v in props)))
        if tn == "tab Y":
            Lr = TAB_Y[3] - TAB_Y[1]
            out("  sensitivity: clamped at the tab Y root y 67.14 instead (L %.2f mm): f1 %.0f-%.0f Hz unpropped"
                % (Lr, f1_cant(Lr, 2.0), f1_cant(Lr, 1.0)))
        res[tn] = dict(EI=EI, k_tip=k_tip, k_a=k_a, f=fr, t=t)
    # pin loads
    out("")
    out("Pin loads (MBM eq. 2, rigid CR on 22 equal axial pin springs, pin group of DOC A.8; tab mass as a uniform load "
        "over the tab part of each cantilever; the foot as a spring at a; ORDER OF MAGNITUDE):")
    xc, yc, sxx, syy = pin_group()
    out("  pin centroid (%.3f, %.3f), Sxx %.1f, Syy %.1f mm2 (Sxy = 0 by symmetry of each column)" % (xc, yc, sxx, syy))
    rows = []
    for mm in M_MAIN:
        for ra in RHO_A:
            for g in SHOCK:
                acc = 9.81 * g
                base = [(xc, yc, mm * 1e-3 * acc)]
                tabload = []
                for tn in ("tab X", "tab Y"):
                    t = tabs[tn]
                    W = ra * t["area"] / 100.0 * 1e-3 * acc
                    tabload.append((tn, W))
                no = list(base) + [(tabs[tn]["cg"][0], tabs[tn]["cg"][1], W) for tn, W in tabload]
                wn, pn = worst_pin(no)
                withs = []
                for ke in (0, 1):
                    fs = list(no)
                    for tn, W in tabload:
                        t = tabs[tn]
                        n = 50
                        seg = (t["L"] - t["root"]) / n
                        load = [(t["root"] + (k + 0.5) * seg, W / n) for k in range(n)]
                        R = reaction(res[tn]["EI"], t["a"], KS[tn]["nom"][ke], load)
                        fs.append((t["foot"][0], t["foot"][1], -R))
                    withs.append(worst_pin(fs)[0])
                r6 = mm * 1e-3 * acc / 22
                rows.append((mm, ra, g, wn, withs, r6))
                out("  main %4.1f g, %.1f g/cm2, %2.0f g: worst pin %.3f N without feet; with feet (bed E 1 / 3 MPa at "
                    "t 0.30 mm) %.3f / %.3f N; r6 CR alone %.3f N" % (mm, ra, g, wn, withs[0], withs[1], r6))
    pushes = {}
    for tn in ("tab X", "tab Y"):
        t = tabs[tn]
        tip = t["tip"]
        ks_all, ks_nom = KS[tn]["all"], KS[tn]["nom"]
        Lp = (tip[0] - 45.998) if tn == "tab X" else (tip[1] - 64.484)
        wn, pn = worst_pin([(tip[0], tip[1], P_PUSH)])
        ws = []
        for ks in (min(ks_all), ks_nom[0], ks_nom[1], max(ks_all)):
            R = reaction(res[tn]["EI"], t["a"], ks, [(Lp, P_PUSH)])
            ws.append((ks, R, worst_pin([(tip[0], tip[1], P_PUSH), (t["foot"][0], t["foot"][1], -R)])[0]))
        pushes[tn] = (wn, pn, ws)
        out("  %.0f N push at the %s tip (%.2f, %.2f): worst pin %.2f N at %s without the foot; with it: %s"
            % (P_PUSH, tn, tip[0], tip[1], wn, pn, "; ".join("k_s %.0f N/mm: foot takes %.2f N, worst pin %.2f N"
                                                             % (k, R, w) for k, R, w in ws)))
    fe2 = F["alts"]["ft2_mid"]
    t = tabs["tab Y"]
    a_far = fe2["centre"][1] - PIN11_Y
    tipY = t["tip"]
    ws_far = []
    for ks in (min(KS["tab Y"]["all"]), KS["tab Y"]["nom"][0], KS["tab Y"]["nom"][1], max(KS["tab Y"]["all"])):
        R = reaction(res["tab Y"]["EI"], a_far, ks, [(tipY[1] - PIN11_Y, P_PUSH)])
        ws_far.append((ks, R, worst_pin([(tipY[0], tipY[1], P_PUSH), (fe2["centre"][0], fe2["centre"][1], -R)])[0]))
    out("  sensitivity, FT2 at the mid-height max-min spot instead (alternative M, %.1f x %.1f mm at (%.2f, %.3f), "
        "a = %.3f mm, tolerance tx %.3f / ty %.3f mm): 10 N tab Y tip push: %s"
        % (fe2["w"], fe2["h"], fe2["centre"][0], fe2["centre"][1], a_far, fe2["tx"], fe2["ty"],
           "; ".join("k_s %.0f N/mm: foot takes %.2f N, worst pin %.2f N" % (k, R, w) for k, R, w in ws_far)))
    rmax = 0.0
    for tn in tabs:
        W = RHO_A[1] * tabs[tn]["area"] / 100 * 1e-3 * 9.81 * 30
        R = reaction(res[tn]["EI"], tabs[tn]["a"], max(KS[tn]["all"]), [(tabs[tn]["L"], W)])
        rmax = max(rmax, R / areas[tn])
    out("  bed stress at 30 g (whole tab load at the tip, stiffest bed): <= %.1f kPa" % (rmax * 1e3))
    # ---- r7 review 7 (D-F1): T-A-09 pull options against the 30 g service bed stress, per tab and per k_s
    out("  T-A-09 pull options (D-F1; tension in the bed = the same lever model as the push; tab X grip at the tip "
        "(%.2f, %.2f), tab Y grip in line with FT2 at (%.2f, %.2f), loop entered from the tab side, never past the tab "
        "Y +y edge (L-FC 0.862 mm, H.23(b))):" % (tabs["tab X"]["tip"][0], tabs["tab X"]["tip"][1],
                                                   tabs["tab Y"]["tip"][0], tabs["tab Y"]["tip"][1]))
    pulls = {}
    for tn in ("tab X", "tab Y"):
        t = tabs[tn]
        Lp = (t["tip"][0] - 45.998) if tn == "tab X" else (t["tip"][1] - 64.484)
        W30 = RHO_A[1] * t["area"] / 100 * 1e-3 * 9.81 * 30
        ks4 = (min(KS[tn]["all"]), KS[tn]["nom"][0], KS[tn]["nom"][1], max(KS[tn]["all"]))
        sh = [reaction(res[tn]["EI"], t["a"], ks, [(Lp, 1.0)]) for ks in ks4]          # foot share per N at the grip
        s30 = [reaction(res[tn]["EI"], t["a"], ks, [(t["L"], W30)]) / areas[tn] for ks in ks4]   # N/mm2 = MPa
        p_lim = min(2.0 * s30[k] * areas[tn] / sh[k] for k in range(4))   # pull with bed stress <= 2 x the 30 g stress
        p_lim1 = min(s30[k] * areas[tn] / sh[k] for k in range(4))        # revision 4: <= 1 x (the service range)
        # revision 4: the distributed-load basis (the 30 g load spread from the root to the tip, as the pin-load rows)
        nseg = 50
        segl = (t["L"] - t["root"]) / nseg
        dload = [(t["root"] + (j + 0.5) * segl, W30 / nseg) for j in range(nseg)]
        s30d = [reaction(res[tn]["EI"], t["a"], ks, dload) / areas[tn] for ks in ks4]
        pulls[tn] = dict(W30=W30, share=sh, s30=s30, p_lim=p_lim, p_lim1=p_lim1, s30d=s30d)
        out("    %s: 30 g whole-tab load %.3f N (0.8 g/cm2 x %.1f mm2); foot share per N at the grip %s; 30 g bed stress "
            "%s kPa (k_s %s N/mm)" % (tn, W30, t["area"], "/".join("%.3f" % v for v in sh),
                                      "/".join("%.1f" % (v * 1e3) for v in s30), "/".join("%.0f" % v for v in ks4)))
        out("      5 N pull: bed stress %s kPa = %s x the 30 g stress; largest pull with bed stress <= 2 x the 30 g "
            "stress at every k_s: %.3f N" % ("/".join("%.0f" % (5.0 * v / areas[tn] * 1e3) for v in sh),
                                             "/".join("%.1f" % (5.0 * sh[k] / areas[tn] / s30[k]) for k in range(4)),
                                             p_lim))
    # revision 4: the design adopts the pull inside the service range on the tip-load basis (<= 1 x the 30 g stress
    # with the whole tab load at the tip), the governing tab setting it; 0.1 N steps. (**superseded:** the r7
    # review-7 recommendation, the 0.1 N floor of the 2 x limit, 0.8 N.)
    gov = min(pulls, key=lambda k: pulls[k]["p_lim1"])
    p_rec = math.floor(10.0 * pulls[gov]["p_lim1"] + 1e-9) / 10.0
    p_old = math.floor(10.0 * min(v["p_lim"] for v in pulls.values()) + 1e-9) / 10.0
    for tn, v in pulls.items():
        v["rec"] = [p_rec * v["share"][k] / areas[tn] for k in range(4)]
        v["rec_ratio"] = [p_rec * v["share"][k] / areas[tn] / v["s30"][k] for k in range(4)]
        v["rec_ratio_d"] = [p_rec * v["share"][k] / areas[tn] / v["s30d"][k] for k in range(4)]
    for tn, v in pulls.items():
        out("    %s: the pull at 1 x the 30 g stress (tip-load basis) is %.3f N; 30 g bed stress on the distributed-load "
            "basis %s kPa (the 30 g load spread from the root to the tip; k_s as above)"
            % (tn, v["p_lim1"], "/".join("%.1f" % (z * 1e3) for z in v["s30d"])))
    out("    recommended T-A-09 pull (revision 4; adopted in the design): %.1f N at each grip for 10 s = the 0.1 N floor of "
        "the 1 x tip-load limit of the governing tab (%s, %.3f N). Bed stress tab X %s kPa, tab Y %s kPa. Stress ratio "
        "on the tip-load basis (whole 30 g tab load at the tip): tab X %.2f x, tab Y %.2f x (inside the service range); "
        "on the distributed-load basis: tab X %.2f-%.2f x, tab Y %.2f-%.2f x (k_s range). (**superseded:** %.1f N, "
        "the 0.1 N floor of the 2 x limit, %.2f-%.2f x on the tip-load basis.) The 5 N r6/r7 pull loads the beds "
        "%.1f-%.1f x the 30 g stress through the sheet's silicone PSA (the A.7 removal layer; PSA strength "
        "TODO(verify: polyimide tape datasheet)); a push-down check on the foot spot is the alternative (D-F1)"
        % (p_rec, gov, pulls[gov]["p_lim1"], "/".join("%.1f" % (v * 1e3) for v in pulls["tab X"]["rec"]),
           "/".join("%.1f" % (v * 1e3) for v in pulls["tab Y"]["rec"]),
           max(pulls["tab X"]["rec_ratio"]), max(pulls["tab Y"]["rec_ratio"]),
           min(pulls["tab X"]["rec_ratio_d"]), max(pulls["tab X"]["rec_ratio_d"]),
           min(pulls["tab Y"]["rec_ratio_d"]), max(pulls["tab Y"]["rec_ratio_d"]), p_old,
           min(p_old * v["share"][k] / areas[tn] / v["s30"][k] for tn, v in pulls.items() for k in range(4)),
           max(p_old * v["share"][k] / areas[tn] / v["s30"][k] for tn, v in pulls.items() for k in range(4)),
           min(5.0 * v["share"][k] / areas[tn] / v["s30"][k] for tn, v in pulls.items() for k in range(4)),
           max(5.0 * v["share"][k] / areas[tn] / v["s30"][k] for tn, v in pulls.items() for k in range(4))))
    # ---- r7 review 7 (D-F1): the feet effect stated plainly
    cut30 = [100 * (r[3] - w) / r[3] for r in rows if r[2] == 30.0 for w in r[4]]
    cutp = {tn: [100 * (v[0] - w) / v[0] for _, _, w in v[2]] for tn, v in pushes.items()}
    out("  feet effect (D-F1; ORDER OF MAGNITUDE, bed confinement (Gent) not modelled): at 30 g the feet cut the worst "
        "pin load by %.0f-%.0f %% (bed E 1-3 MPa at t 0.30 mm); a 10 N tip push loses %.0f-%.0f %% at tab X (FT1 takes "
        "%.2f-%.2f N of it) and %.0f-%.0f %% at tab Y (FT2 takes %.2f-%.2f N); the feet take a larger share of a tip "
        "push than of the distributed 30 g load"
        % (min(cut30), max(cut30), min(cutp["tab X"]), max(cutp["tab X"]),
           min(R for _, R, _ in pushes["tab X"][2]), max(R for _, R, _ in pushes["tab X"][2]),
           min(cutp["tab Y"]), max(cutp["tab Y"]), min(R for _, R, _ in pushes["tab Y"][2]),
           max(R for _, R, _ in pushes["tab Y"][2])))
    gent = {}
    for tn in ("tab X", "tab Y"):
        S = areas[tn] / (perim[tn] * T_BED[1])
        g = 1 + 2 * S * S
        ph_f = res[tn]["f"]
        gent[tn] = [(mf, f1 * math.sqrt(1 + min(KS[tn]["nom"]) * g * 1e3 * ph * ph /
                                         ((2 * math.pi * f1) ** 2 * RHO * T_CR * 1e-3 * tabs[tn]["b"] * 1e-3 *
                                          tabs[tn]["L"] * 1e-3 * mf / 4.0)),
                     f1 * math.sqrt(1 + max(KS[tn]["nom"]) * g * 1e3 * ph * ph /
                                    ((2 * math.pi * f1) ** 2 * RHO * T_CR * 1e-3 * tabs[tn]["b"] * 1e-3 *
                                     tabs[tn]["L"] * 1e-3 * mf / 4.0)), f1 * (3.927 / 1.875) ** 2)
                    for mf, f1, _, ph in ph_f]
    out("  propped f1 with the Gent factor applied at t 0.30 mm (labels, D-F1/vibration finding): tab X %s; tab Y %s "
        "(Hz, k_s nominal E 1 / 3 MPa, capped at the rigid prop): the propped figures are neither upper nor lower bounds; "
        "the unpropped figures are upper estimates (clamped root; tab Y clamp held by pin 11 alone within its width)"
        % ("; ".join("m_f %.0f %.0f-%.0f" % (mf, min(a, c), min(b, c)) for mf, a, b, c in gent["tab X"]),
           "; ".join("m_f %.0f %.0f-%.0f" % (mf, min(a, c), min(b, c)) for mf, a, b, c in gent["tab Y"])))
    F["pulls"] = dict(rec=p_rec, tabs=pulls, cut30=(min(cut30), max(cut30)),
                      cut_push={k: (min(v), max(v)) for k, v in cutp.items()})
    def fjson(f):
        return dict(centre=f["centre"], size=(f["w"], f["h"]), body=f["body"],
                    cu_clear=f["cu_clear"] if f["cu_who"] else None, cu_who=f["cu_who"], vias=f["vias"],
                    part_clear=f2(f["part_clear"]), part=f["part"], t=f2(f["t"]) if f.get("t") is not None else None,
                    tx=f2(f["tx"]) if f.get("tx") is not None else None,
                    ty=f2(f["ty"]) if f.get("ty") is not None else None, bind=f.get("bind"), zone=f.get("zone"),
                    rule_margin=f2(f["rule_margin"]) if f.get("rule_margin") is not None else None,
                    slack={k: f2(v) for k, v in f["slack"].items()} if f.get("slack") else None,
                    under=f.get("under"), within=f.get("within"))
    RJ["i"] = dict(ft1=fjson(F["ft1"]), ft2=fjson(F["ft2"]), keepouts={n: (k, lane) for n, k, lane in foot_keepouts()},
                   alternatives={k: fjson(v) for k, v in F["alts"].items()}, candidates=F.get("cand_json"),
                   rule=F["rule"], rule2=F["rule2"], feasible_44=F["feas"],
                   ft2_mid_push=[(f2(k), f2(R), f2(w)) for k, R, w in ws_far],
                   ft2_fill_hole=F.get("fill"), ft1_fallback_cutout=F.get("ft1_cutout"),
                   best_tip44=(F["best_tip44"]["centre"], f2(F["best_tip44"]["cu_clear"])) if F["best_tip44"] else None,
                   ks={tn: dict(all=[f2(v) for v in KS[tn]["all"]], nom=[f2(v) for v in KS[tn]["nom"]]) for tn in KS},
                   tabs={tn: dict(k_tip=f2(v["k_tip"]), k_a=f2(v["k_a"]),
                                  f=[(mf, f2(f1), [f2(p) for p in pr]) for mf, f1, pr, _ in v["f"]])
                         for tn, v in res.items()},
                   pin_rows=[(r[0], r[1], r[2], f2(r[3]), [f2(v) for v in r[4]], f2(r[5])) for r in rows],
                   pushes={k: (f2(v[0]), v[1], [(f2(a), f2(b), f2(c)) for a, b, c in v[2]]) for k, v in pushes.items()},
                   foot_height=dict(h_f=f2(H_F), t_bond=T_BOND, t_bed_nom=T_BED[1], block_tol=TOL_BLOCK,
                                    tape=TOL_TAPE, body_tol=TOL_BODY, gate=GATE,
                                    budget={n: dict(lever=f2(v["lever"]), bow=f2(v["bow"]), mean=f2(v["mean"]),
                                                    worst=[f2(x) for x in v["wc"]], rss=f2(v["rss"]),
                                                    rss_band=[f2(x) for x in v["rss_band"]], gate_pass=f2(v["p_in"]),
                                                    gate_low=f2(v["p_lo"]), gate_high=f2(v["p_hi"]))
                                            for n, v in F["tol"].items()}),
                   pulls=dict(recommended_N=F["pulls"]["rec"],
                              tabs={k: dict(W30_N=f2(v["W30"]), share=[f2(x) for x in v["share"]],
                                            s30_kPa=[f2(x * 1e3) for x in v["s30"]], p_limit_N=f2(v["p_lim"]),
                                            rec_kPa=[f2(x * 1e3) for x in v["rec"]],
                                            rec_ratio=[f2(x) for x in v["rec_ratio"]])
                                    for k, v in F["pulls"]["tabs"].items()}),
                   feet_effect=dict(cut30_pct=[f2(x) for x in F["pulls"]["cut30"]],
                                    cut_push_pct={k: [f2(x) for x in v] for k, v in F["pulls"]["cut_push"].items()}))
    f1 = F["ft1"]
    kos = {n: k for n, k, lane in foot_keepouts()}
    lanes = {n: lane for n, k, lane in foot_keepouts()}
    summ("FT1 adopted (A1, B1)", "%.1f x %.1f mm body (bed %.2f mm2) at (%.2f, %.3f) (exact max-min y), body x "
         "%.3f-%.3f, y %.3f-%.3f; tolerance t %.3f mm, tx %.3f / ty %.3f mm (binding: %s); %.1f x %.1f reaches t %.3f "
         "(< %.2f); %s; copper clearance %.3f mm (%s); nearest part box %.2f mm (%s); via pads under: none%s"
         % (f1["w"], f1["h"], f1["w"] * f1["h"], f1["centre"][0], f1["centre"][1], f1["body"][0], f1["body"][2],
            f1["body"][1], f1["body"][3], f1["t"], f1["tx"], f1["ty"], f1["bind"].split(" (")[0], f1["w"],
            round(f1["h"] + 0.1, 1), p17["t"] if p17 else float("nan"), TOL_REQ, f1["zone"], f1["cu_clear"],
            f1["cu_who"], f1["part_clear"], f1["part"], "" if not f1["vias"] else (" EXCEPT %s" % f1["vias"])),
         "H.23(i)")
    f2_ = F["ft2"]
    summ("FT2 adopted (B2)", "%.1f x %.1f mm body (bed %.2f mm2) at (%.2f, %.3f), body x %.3f-%.3f, y %.3f-%.3f; "
         "largest lever a %.3f mm with t >= %.2f: t %.3f mm, tx %.3f / ty %.3f mm (binding: %s); no non-GND copper "
         "within 3 mm; nearest part box %.2f mm (%s); via pads under: %s; no edge lane; mid-height alternative M "
         "(%.2f, %.3f), a %.3f mm, t %.3f mm"
         % (f2_["w"], f2_["h"], f2_["w"] * f2_["h"], f2_["centre"][0], f2_["centre"][1], f2_["body"][0],
            f2_["body"][2], f2_["body"][1], f2_["body"][3], f2_["centre"][1] - PIN11_Y, TOL_REQ, f2_["t"], f2_["tx"],
            f2_["ty"], f2_["bind"].split(" (")[0], f2_["part_clear"], f2_["part"], f2_["vias"] or "none",
            fe2["centre"][0], fe2["centre"][1], fe2["centre"][1] - PIN11_Y, fe2["t"]), "H.23(i)")
    fl = F["fill"]
    summ("FT2 fill hole (B2)", "%.1f mm NPTH at (%.2f, %.3f), %.3f mm inside the foot body edge; CR feature only (MB "
         "under it: GND pour; nearest non-GND rim %.2f mm, via %.2f mm, part box %.2f mm from the hole edge); CR-top "
         "keep-out disc %.1f mm booked in the top area" % (fl["d"], fl["centre"][0], fl["centre"][1], fl["in_body"],
                                                           fl["cu"][0], fl["via"][0], fl["part"][0], fl["ko_disc"]),
         "H.23(i)")
    co = F["ft1_cutout"]
    summ("FT1 fallback sheet cut-out (B1)", "= the FT1 keep-out %.1f x %.1f mm; non-GND copper rim exposed: %s (nearest "
         "%.3f mm outside, %s); via pads inside: %s"
         % (co["rect"][2] - co["rect"][0], co["rect"][3] - co["rect"][1], ", ".join(co["exposed"]) or "none",
            co["nearest"][0], co["nearest"][1].split(" (")[0] if "trace" in co["nearest"][1] else co["nearest"][1],
            co["vias"] or "none"), "H.23(i)")
    summ("foot keep-outs (body + 0.5 mm)", "; ".join("%s x %.3f-%.3f, y %.3f-%.3f%s" % (
        n, k[0], k[2], k[1], k[3], (", lane x %.3f-%.3f, y %.3f-%.3f" % (lanes[n][0], lanes[n][2], lanes[n][1],
                                                                         lanes[n][3])) if lanes[n] else ", no lane")
        for n, k in kos.items()), "H.23(i)")
    a = F["alts"]["old_ft1"]
    summ("FT1 alternative A (r7 first run)", "4.0 x 2.0 mm at (62.00, 66.70): meets the rule (margin %.3f mm, %s) but "
         "tolerance tx %.3f / ty %.3f mm; one-sided slack +x %.3f, -x %.3f, +y %.3f, -y %.3f mm (fails the %.2f mm "
         "criterion)" % (a["rule_margin"], a["rule_who"].split(" (")[0], a["tx"], a["ty"], a["slack"]["+x"],
                         a["slack"]["-x"], a["slack"]["+y"], a["slack"]["-y"], TOL_REQ), "H.23(i)")
    b = F["alts"]["relax44"]
    summ("FT1 alternative B (relaxed 4 x 4)", "(%.2f, %.2f): violates the rule, copper clearance %.3f mm (masked signal "
         "traces under the body; operator option only)" % (b["centre"][0], b["centre"][1], b["cu_clear"]), "H.23(i)")
    tr = F["tol"]
    summ("foot height (D-F1)", "h_f = 2.54 - t_bed - t_bond = %.2f mm (t_bed 0.30, transfer tape %.2f mm; block +0/-0.05); "
         "t_bed budget FT1 worst %.3f-%.3f, RSS %.3f-%.3f mm; FT2 worst %.3f-%.3f, RSS %.3f-%.3f mm; PM4 (2d) gate "
         "0.15/0.45 mm passes %.0f %% (FT1) / %.0f %% (FT2) of uniform-tolerance builds"
         % (H_F, T_BOND, tr["FT1"]["wc"][0], tr["FT1"]["wc"][1], tr["FT1"]["rss_band"][0], tr["FT1"]["rss_band"][1],
            tr["FT2"]["wc"][0], tr["FT2"]["wc"][1], tr["FT2"]["rss_band"][0], tr["FT2"]["rss_band"][1],
            100 * tr["FT1"]["p_in"], 100 * tr["FT2"]["p_in"]), "H.23(i)")
    pl = F["pulls"]
    summ("T-A-09 pull (D-F1, revision 4)", "recommended %.1f N at each grip (tab Y grip in line with FT2, x %.2f; tab Y "
         "governs): tip-load basis tab X %.2f x / tab Y %.2f x the 30 g service stress, distributed-load basis %.2f-%.2f x "
         "/ %.2f-%.2f x; the 5 N pull gives %.0f-%.0f kPa at FT1"
         % (pl["rec"], F["ft2"]["centre"][0], max(pl["tabs"]["tab X"]["rec_ratio"]),
            max(pl["tabs"]["tab Y"]["rec_ratio"]), min(pl["tabs"]["tab X"]["rec_ratio_d"]),
            max(pl["tabs"]["tab X"]["rec_ratio_d"]), min(pl["tabs"]["tab Y"]["rec_ratio_d"]),
            max(pl["tabs"]["tab Y"]["rec_ratio_d"]),
            5.0 * min(pl["tabs"]["tab X"]["share"]) / areas["tab X"] * 1e3,
            5.0 * max(pl["tabs"]["tab X"]["share"]) / areas["tab X"] * 1e3), "H.23(i)")
    summ("feet effect (D-F1)", "30 g worst-pin cut %.0f-%.0f %%; 10 N tip push cut tab X %.0f-%.0f %%, tab Y %.0f-%.0f %% "
         "(ORDER OF MAGNITUDE; Gent confinement not modelled)" % (pl["cut30"][0], pl["cut30"][1],
                                                                 pl["cut_push"]["tab X"][0], pl["cut_push"]["tab X"][1],
                                                                 pl["cut_push"]["tab Y"][0], pl["cut_push"]["tab Y"][1]),
         "H.23(i)")
    for tn, v in res.items():
        summ("%s f1 unpropped / propped (bed E 1-3 MPa, t 0.30)" % tn, "%.0f-%.0f Hz / %.0f-%.0f Hz (ORDER OF MAGNITUDE)"
             % (v["f"][1][1], v["f"][0][1], v["f"][1][2][1], v["f"][0][2][2]), "H.23(i)")
        summ("%s stiffness tip / at the foot vs bed" % tn, "%.1f / %.1f N/mm vs RTV bed %.0f-%.0f N/mm"
             % (v["k_tip"], v["k_a"], min(KS[tn]["all"]), max(KS[tn]["all"])), "H.23(i)")
    w30 = [r for r in rows if r[2] == 30.0]
    summ("worst pin at 30 g, without / with feet", "%.3f-%.3f N / %.3f-%.3f N (ORDER OF MAGNITUDE)"
         % (min(r[3] for r in w30), max(r[3] for r in w30), min(min(r[4]) for r in w30), max(max(r[4]) for r in w30)),
         "H.23(i)")
    for tn, v in pushes.items():
        summ("10 N push at the %s tip: worst pin" % tn, "%.2f N without foot; %.2f-%.2f N with foot"
             % (v[0], min(w for _, _, w in v[2]), max(w for _, _, w in v[2])), "H.23(i)")


# ======================================================================================================================
# H.23(j) header post arithmetic with the sheet; stack height
# ======================================================================================================================
def sec_j():
    head("H.23(j) header post arithmetic with the 0.125 mm sheet; CR top height; stack top (information only, D-H)")
    A_, B_, C_ = 10.92, 2.54, 5.84      # Samtec F-226 TSW-1xx-07: A overall, B and C the two ends (BASIS / MBM Table 7)
    BODY, SHEET, MB, CR = 2.54, 0.125, 1.6, 1.6
    out("Inputs: TSW-1xx-07 A %.2f, B %.2f, C %.2f mm, body %.2f mm (Samtec F-226; A - B - C = %.2f); sheet %.3f mm (DOC "
        "A.7, kept BASIS D4); MB %.1f mm (ASSUMPTION, TODO(measure: MS6 caliper at the CHG holes)); CR %.1f mm "
        "(ASSUMPTION, TODO(verify: CR fab stack-up), MS6/MS8)." % (A_, B_, C_, BODY, A_ - B_ - C_, SHEET, MB, CR))
    out("r6 orientation (DOC D.1 PM4 steps 2-4): strips inserted from the CR bottom, body against the CR underside, CR-top "
        "joints first, then seated on the sheet and soldered at the MB bottom, MB-bottom tails cut to <= 1.0 mm in step 4; "
        "'post length = MB + body + CR + top fillet'. That is the short end B up through the CR and the long end C down "
        "through the MB; r7 keeps it.")
    rows = []
    for lab, up, down in (("r6/r7: B up through the CR, C down (adopted)", B_, C_), ("alternative: C up, B down", C_, B_)):
        crt = up - CR
        mbb = down - SHEET - MB
        rows.append((lab, crt, mbb))
        out("  %-48s CR-top protrusion %.3f mm (>= 0.5 for a fillet: %s); MB-bottom protrusion %.3f mm (%s)"
            % (lab, crt, "yes" if crt >= 0.5 else "NO", mbb, "cut to <= 1.0 mm in PM4 step 4" if mbb > 1.0
               else "no cut needed; >= 0.5 for a fillet: %s" % ("yes" if mbb >= 0.5 else "NO")))
    for crt in (1.6, 1.71):
        for mbt in (1.5, 1.7):
            out("  sensitivity CR %.2f / MB %.2f mm: B-up CR-top %.3f mm, MB-bottom %.3f mm"
                % (crt, mbt, B_ - crt, C_ - SHEET - mbt))
    under, top = SHEET + BODY, SHEET + BODY + CR
    fold = 8.0
    stack = top + fold
    env = 2.54 + 1.60 + 9.0
    rib = 0.9                                   # mm, W5 ribbon thickness ASSUMPTION (TODO(verify: cable drawing))
    sw3d = H_LFC + SW_GAP                       # H.23(l) 3-D rule: ribbon bottom over the L-FC plan overlap
    out("CR underside %.3f mm, CR top %.3f mm above the MB top (unchanged from r6). Stack top, INFORMATION ONLY (D-H, "
        "operator statement 2026-11-10: no maximum height for the MB and its PCBs; the Ag105 envelope and any lid "
        "clearance are not limits, so no pass/fail is drawn): W5 IDC socket + ribbon fold >= %.1f mm above the CR top "
        "(DOC A.3) -> stack top >= %.3f mm + the cable (%.3f / %.3f mm with one / two %.1f mm ribbon thicknesses, "
        "ASSUMPTION); with the H.23(l) 3-D switched-conductor height over L-FC (ribbon bottom >= %.2f mm above the MB, "
        "L-FC body %.1f mm ASSUMPTION) the W5 run over tab Y sits >= %.3f mm above the CR top and its top at >= %.3f mm "
        "(one thickness). Reference only: the nominal Ag105 envelope is %.2f mm (AG105_Silvertel.pdf Fig. 11: 2.54 + "
        "1.60 + 9). (**superseded in r7 (D-H):** 'margin <= %.3f mm before the cable; gate D-2 / MS1 decides'.)"
        % (under, top, fold, stack, stack + rib, stack + 2 * rib, rib, sw3d, H_LFC, sw3d - top, sw3d + rib, env,
           env - stack))
    out("  minimal proposal (no sheet): CR top 4.14 mm, MB-bottom protrusion 4.24 mm; the kept sheet adds 0.125 mm to "
        "both stack heights and removes 0.125 mm from the MB-bottom protrusion.")
    RJ["j"] = dict(rows=[(r[0], f2(r[1]), f2(r[2])) for r in rows], cr_under=under, cr_top=top, stack=stack, env=env,
                   info_only=True, ribbon_assumed=rib, w5_over_lfc_bottom=f2(sw3d), w5_over_lfc_top=f2(sw3d + rib))
    summ("post arithmetic (B up, with sheet)", "CR-top protrusion %.3f mm; MB-bottom %.3f mm before the PM4 cut"
         % (rows[0][1], rows[0][2]), "H.23(j)")
    summ("stack top (information only, D-H)", "CR top %.3f mm; W5 fold >= %.3f mm + cable (%.3f / %.3f mm with one / two "
         "%.1f mm ribbon thicknesses); W5 over L-FC (3-D rule) bottom >= %.2f mm, top >= %.3f mm; Ag105 envelope %.2f mm "
         "for reference, not a limit" % (top, stack, stack + rib, stack + 2 * rib, rib, sw3d, sw3d + rib, env), "H.23(j)")


# ======================================================================================================================
# H.23(k) E-lead maxima; E1/C205 resonance; R276
# ======================================================================================================================
EVM_W = 88.90                                       # EVMG section 3
EVM_PTS = {"TP49": (83.440, 79.120), "TP33": (80.011, 63.499), "JP21 pin 1 (lower post)": (75.312, 64.769),
           "JP21 pin 2 (upper post, AGND)": (75.312, 67.309), "JP14 pin 2": (71.375, 64.769), "TP38": (66.041, 59.689),
           "JP12 pin 1 (REGN)": (39.370, 13.741), "TP36": (55.874, 19.710), "JP17 pin 1": (54.611, 26.796)}   # EVMG Table 1
E_ROWS = {"E8": (1, "TP49"), "E3": (3, "TP33"), "E4": (4, "JP21 pin 1 (lower post)"), "E2": (5, "JP14 pin 2"),
          "E7": (7, "TP38"), "E1": (9, "JP12 pin 1 (REGN)"), "E5": (11, "TP36"), "E6": (12, "JP17 pin 1")}  # DOC A.9
R6_EMAX = {"E8": 20, "E3": 25, "E4": 30, "E2": 35, "E7": 40, "E1": 85, "E5": 60, "E6": 60}          # DOC A.5
CRIT = {"E3": 92.0, "E4": 59.0, "E6": 196.0}       # eib_merge_failsafe.md Table 9 (s 5 mm untwisted, class B)
E1_BEND = (51.0, 30.6)                             # DOC A.5 r7 review 7: the one E1 bend near (51.0, 30.6) EVM mm
EVM_JP17_2 = (54.611, 24.257)                      # EVMG Table 1: JP17 pin 2 (AGND), vacated (EM1)
EVM_U1 = (45.448, 39.986, 49.549, 44.086)          # EVMG Table 1: U1 BQ25798 mechanical outline
EVM_L2 = (43.672, 49.812, 51.072, 56.612)          # EVMG Table 1: L2 SPM6530T outline
R28, R26, R20, R18 = 0.2129, 0.1339, 0.03331, 0.02095     # AWG, Ohm/m at 20 C
MU0_PI = 4e-7                                      # mu0/pi, H/m
A28 = 0.16e-3                                      # 28 AWG radius, EIBM loop_L
C205, ESR205 = 100e-9, 0.02                        # DOC B.6 C205 100 nF; ESR 20 mOhm ASSUMPTION (EIBM)
R276 = 10.0                                        # BASIS D7
REGN = (4.8, 5.2)                                  # DOC H.19 REGN 4.8 V; DOC voltage-ratings row: REGN <= 5.2 V
R_PULL, R255, R23, R256, R257 = 47e3, 48.7e3, 49.9e3, 200e3, 59.0e3     # DOC B.6 (R252/R254/R271 47k; R255; EM4 R23)
V_REL = {"regen clamp": (2.06, 2.40), "FC clamp": (1.52, 1.76)}         # DOC H.4 pin levels when released
K_ILIM = 0.8                                       # V/A: V_ILIM = 1 V + 0.8 Ohm x IINDPM (SLUSDV2C 7.3.4.3, via EIBM;
#                                                    reproduces the DOC H.4 pairs 2.06-2.40 V <-> 1.33-1.76 A)


def loop_L(Lm, s):
    return MU0_PI * Lm * math.log(s / A28)


RHO_CU = 1.72e-8                                   # Ohm m, annealed copper at 20 C (task / standard value)
MU0 = 4e-7 * math.pi                               # H/m


def _bessel_j(n, z, terms=60):
    """J_n(z) for complex z by its power series (stdlib cmath; |z| < 10 here)."""
    s, term = 0j, (z / 2) ** n / math.factorial(n)
    for m in range(terms):
        s += term
        term *= -(z / 2) ** 2 / ((m + 1) * (m + 1 + n))
    return s


def skin(f):
    """Skin depth and AC/DC resistance ratio of an isolated round 28 AWG conductor (radius A28) at f.
    Exact ratio: Re[(k a / 2) J0(k a) / J1(k a)] with k = (1 - j)/delta; high-frequency asymptote a/(2 delta) + 1/4."""
    delta = math.sqrt(2 * RHO_CU / (2 * math.pi * f * MU0))
    ka = (1 - 1j) * A28 / delta
    exact = ((ka / 2) * _bessel_j(0, ka) / _bessel_j(1, ka)).real
    return delta, exact, A28 / (2 * delta) + 0.25


def sec_k():
    head("H.23(k) E-lead maxima on the vector EVM positions; E1/E8/C205 resonance; R276 static drop")
    xcol = EVM_W + 7.0
    e3y = EVM_PTS["TP33"][1] + 5.0
    out("r6 placement rule (DOC A.5/A.9): EIB pad column 7 mm off the EVM right edge (x %.2f EVM mm), E3 5 mm above the "
        "TP33 level (y %.3f), rows 2.54 mm apart downward; build max = straight x 1.25 rounded up to 5 mm. Points: "
        "evm_geometry.md Table 1 (vector)." % (xcol, e3y))
    res = {}
    for e, (row, pt) in E_ROWS.items():
        y = e3y - (row - 3) * 2.54
        p = EVM_PTS[pt]
        s = math.hypot(xcol - p[0], y - p[1])
        mx = int(math.ceil(s * 1.25 / 5.0 - 1e-9)) * 5
        crit = CRIT.get(e)
        res[e] = (s, mx)
        out("  %-3s row %2d (%.2f, %.3f) -> %-28s (%.3f, %.3f): straight %5.1f mm, build max %3d mm (r6 %d)%s"
            % (e, row, xcol, y, pt, p[0], p[1], s, mx, R6_EMAX[e],
               "; criterion limit %.0f mm -> %.2f of it" % (crit, mx / crit) if crit else ""))
    s_up = math.hypot(xcol - EVM_PTS["JP21 pin 2 (upper post, AGND)"][0],
                      e3y - 2.54 - EVM_PTS["JP21 pin 2 (upper post, AGND)"][1])
    out("  E4 to the upper JP21 post (the r6 A.5 pixel point (902, 408) = pin 2, AGND): %.1f mm (same, because the E4 row "
        "lies between the posts); the correct E4 post is pin 1 = the lower square post (75.312, 64.769)" % s_up)
    # ---- revision 4: the A.5 E1 route through one bend (EVMG Table 1 positions; D-F6)
    e1p = (xcol, e3y - (E_ROWS["E1"][0] - 3) * 2.54)
    jp12 = EVM_PTS["JP12 pin 1 (REGN)"]
    route = [e1p, E1_BEND, jp12]
    segs = list(zip(route[:-1], route[1:]))
    L_e1 = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs)

    def dpt_route(pt, ss):
        return min(dpt_seg(pt[0], pt[1], a[0], a[1], b[0], b[1]) for a, b in ss)

    def drect_route(r, ss):
        return min(d_rect_seg(r, a, b) for a, b in ss)
    straight = [(e1p, jp12)]
    rows_e1 = []
    for lab, f_ in (("JP17 pin 1 (E6, /CE joint)", lambda ss: dpt_route(EVM_PTS["JP17 pin 1"], ss)),
                    ("JP17 pin 2 (vacated AGND hole, centre)", lambda ss: dpt_route(EVM_JP17_2, ss)),
                    ("TP36 (E5)", lambda ss: dpt_route(EVM_PTS["TP36"], ss)),
                    ("U1 outline", lambda ss: drect_route(EVM_U1, ss)),
                    ("L2 outline", lambda ss: drect_route(EVM_L2, ss))):
        rows_e1.append((lab, f_(segs), f_(straight)))
    out("  E1 route (revision 4; A.5: E1 pad -> one bend -> JP12 pin 1, below U1 and L2; centre distances, EVMG Table "
        "1): E1 pad (%.2f, %.3f) -> bend (%.1f, %.1f) -> JP12 pin 1 (%.3f, %.3f) EVM mm: %.1f mm (straight %.1f mm; "
        "build max %d mm); %s"
        % (e1p[0], e1p[1], E1_BEND[0], E1_BEND[1], jp12[0], jp12[1], L_e1, res["E1"][0], res["E1"][1],
           "; ".join("%s %.2f mm (straight line %.2f mm)" % z for z in rows_e1)))
    RJ["k_e1"] = dict(route=route, L=f2(L_e1), rows=[(a, f2(b), f2(c)) for a, b, c in rows_e1])
    summ("E1 route (revision 4)", "E1 pad -> (%.1f, %.1f) -> JP12 pin 1: %.1f mm (max %d mm); %s"
         % (E1_BEND[0], E1_BEND[1], L_e1, res["E1"][1], "; ".join("%s %.2f" % (a, b) for a, b, _ in rows_e1)), "H.23(k)")
    # resonance
    out("")
    out("E1 + E8 + C205 series loop (EIBM model: two-wire line of length l, spacing s 5 mm, 28 AWG radius 0.16 mm, "
        "L = (mu0/pi) l ln(s/a); return conductor of the same length l; R = 28 AWG x 2l + ESR %.0f mOhm (ASSUMPTION) "
        "+ R276):" % (ESR205 * 1e3))
    rr = {}
    for Lmm in (85.0, 90.0):
        Lm = Lmm * 1e-3
        Ll = loop_L(Lm, 5e-3)
        f0 = 1 / (2 * math.pi * math.sqrt(Ll * C205))
        Z0 = math.sqrt(Ll / C205)
        rl = R28 * 2 * Lm + ESR205
        q0 = Z0 / rl
        q1 = Z0 / (rl + R276)
        rl_e8 = R28 * (Lm + 0.020) + ESR205
        rr[Lmm] = (Ll, f0, Z0, q0, q1, Z0 / rl_e8)
        out("  l %3.0f mm: L %.1f nH, f0 %.3f MHz (BQ25798 fsw 1.5 MHz, JP24/EM19), Z0 %.3f Ohm; Q %.1f without R276 "
            "(%.1f with the E8 return at its 20 mm maximum instead of l), %.3f with R276 (zeta %.1f: overdamped)"
            % (Lmm, Ll * 1e9, f0 / 1e6, Z0, q0, Z0 / rl_e8, q1, 1 / (2 * q1)))
    # Q upper-bound note (BASIS section 10 A4/A6): skin effect in the 28 AWG E1/E8 conductors at f0
    qub = {}
    for Lmm in (85.0, 90.0):
        Ll, f0, Z0 = rr[Lmm][0], rr[Lmm][1], rr[Lmm][2]
        dlt, kac, kas = skin(f0)
        Lm = Lmm * 1e-3
        q_ac = Z0 / (R28 * 2 * Lm * kac + ESR205)
        q_ac_e8 = Z0 / (R28 * (Lm + 0.020) * kac + ESR205)
        qub[Lmm] = dict(f0=f0, delta=dlt, rac_rdc=kac, rac_rdc_asym=kas, Q=q_ac, Q_e8=q_ac_e8)
    q9 = qub[90.0]
    out("  Q upper bound: the undamped Q above uses the DC wire resistance and is an UPPER bound. Skin effect at f0 "
        "%.3f MHz (90 mm): copper rho %.3g Ohm m, mu0: skin depth %.1f um against the %.0f um 28 AWG radius (a/delta "
        "%.2f); Rac/Rdc %.2f (exact round-wire Bessel ratio; high-frequency asymptote a/(2 delta) + 1/4 = %.2f); "
        "undamped Q with Rac %.1f at 90 mm (%.1f at 85 mm; %.1f / %.1f with the E8 return at 20 mm). Proximity effect "
        "of the return conductor (s/a = %.0f) and the C205 ESR frequency dependence are not modelled (both lower Q "
        "further). The R276 conclusion (overdamped) is unchanged."
        % (q9["f0"] / 1e6, RHO_CU, q9["delta"] * 1e6, A28 * 1e6, A28 / q9["delta"], q9["rac_rdc"], q9["rac_rdc_asym"],
           q9["Q"], qub[85.0]["Q"], q9["Q_e8"], qub[85.0]["Q_e8"], 5e-3 / A28))
    att = abs(1 / (2 * math.pi * 1.5e6 * C205)) / math.hypot(R276, 1 / (2 * math.pi * 1.5e6 * C205))
    out("  R276 x C205 low-pass: fc %.0f kHz; a 1.5 MHz REGN ripple reaches C205 at %.3f of its EVM amplitude (x%.1f "
        "attenuation; T-C-16 criterion)" % (1 / (2 * math.pi * R276 * C205) / 1e3, att, 1 / att))
    # static drop
    out("")
    out("R276 static drop. E1 current = the EIB REGN loads (DOC B.6): R252 (Q201 gate, conducts when U202 sinks = "
        "release), R254 (Q202 gate, conducts when U201 3Y sinks = RFC_OFF HIGH = regen clamp), R271 (Q203 G-S, conducts "
        "when U201 2Y sinks = release), each 47 kOhm to ~0 V; plus the release feed REGN -> Q203 -> R255 48.7 kOhm -> "
        "E2 -> ILIM_HIZ. R272/R272b (H.15 'REGN pull-ups') sit on the EVM and do not pass through E1.")
    states = []
    for vr in REGN:
        ip = vr / R_PULL
        states.append(("held, RFC_OFF LOW (FC clamp selected)", vr, 0.0, None))
        states.append(("held, RFC_OFF HIGH = the H.15 E1 load (R254 only)", vr, ip, None))
        for k, (lo, hi) in V_REL.items():
            feed = (vr - lo) / R255
            n = 3 if k == "regen clamp" else 2
            states.append(("released, %s (pin %.2f V)" % (k, lo), vr, n * ip + feed, k))
    out("  %-56s %6s %9s %10s %12s %12s" % ("state", "REGN", "I_E1 mA", "drop mV", "pin shift mV", "IINDPM mA"))
    worst = None
    rows = []
    for lab, vr, i, k in states:
        drop = i * R276
        if k:
            rb = 1 / (1 / R23 + 1 / R256) if k == "regen clamp" else 1 / (1 / R23 + 1 / R256 + 1 / R257)
            sh = drop * rb / (R255 + rb)
            di = sh / K_ILIM
        else:
            sh, di = 0.0, 0.0
        rows.append((lab, vr, i, drop, sh, di))
        if worst is None or drop > worst[3]:
            worst = (lab, vr, i, drop, sh, di)
        out("  %-56s %6.1f %9.3f %10.2f %12.3f %12.2f" % (lab, vr, i * 1e3, drop * 1e3, sh * 1e3, di * 1e3))
    out("  What the drop shifts: (1) REGN at the EIB node (C205 = Q203 source, R252/R254/R271 tops) falls by the drop; "
        "the gate drives (VGS(th) <= 2.0 V class against ~4.8 V) are unaffected at the mV level; Q203's VGS is unaffected "
        "(source and R271 move together). (2) The released ILIM_HIZ level falls by drop x Rbot/(R255 + Rbot) "
        "(Rbot = R23 || R256 = %.2f kOhm regen, || R257 = %.2f kOhm FC), i.e. IINDPM falls by that / %.1f V/A: the "
        "safe direction (less input current). (3) Held states: Q203 is off, no feed flows, the held level is set by "
        "Q201, so the drop changes nothing."
        % (1 / (1 / R23 + 1 / R256) / 1e3, 1 / (1 / R23 + 1 / R256 + 1 / R257) / 1e3, K_ILIM))
    out("  The work note's '1.6 mV at 2 mA' = 0.36 mA x 10 Ohm x 39.9/88.6: 1.6 mV is the pin shift and 2 mA the IINDPM "
        "shift; the R276 current is 0.36 mA, not 2 mA.")
    RJ["k"] = dict(emax={e: (f2(v[0]), v[1]) for e, v in res.items()},
                   resonance={str(k): dict(L_nH=f2(v[0] * 1e9), f0_MHz=f2(v[1] / 1e6), Z0=f2(v[2]), Q=f2(v[3]),
                                           Q_R276=round(v[4], 4), Q_E8_20mm=f2(v[5])) for k, v in rr.items()},
                   drop_rows=[(r[0], r[1], f2(r[2] * 1e3), f2(r[3] * 1e3), round(r[4] * 1e3, 4), f2(r[5] * 1e3))
                              for r in rows],
                   q_upper_bound={str(k): dict(f0_MHz=f2(v["f0"] / 1e6), skin_depth_um=f2(v["delta"] * 1e6),
                                               rac_rdc=f2(v["rac_rdc"]), rac_rdc_asymptote=f2(v["rac_rdc_asym"]),
                                               Q_ac=f2(v["Q"]), Q_ac_E8_20mm=f2(v["Q_e8"])) for k, v in qub.items()})
    summ("E-lead build maxima (mm)", ", ".join("%s %d" % (e, res[e][1]) for e in E_ROWS), "H.23(k)")
    summ("E1/E8/C205 resonance", "%.3f MHz at 85 mm, %.3f MHz at 90 mm; Q %.1f / %.1f undamped (%.1f / %.1f with the E8 "
         "return at 20 mm), %.3f / %.3f with R276 (overdamped)"
         % (rr[85.0][1] / 1e6, rr[90.0][1] / 1e6, rr[85.0][3], rr[90.0][3], rr[85.0][5], rr[90.0][5], rr[85.0][4],
            rr[90.0][4]), "H.23(k)")
    summ("E1/C205 Q upper-bound note", "the undamped Q is an upper bound: 28 AWG skin depth %.0f um at %.2f MHz vs "
         "%.0f um radius, Rac/Rdc %.2f -> undamped Q about %.1f (90 mm) / %.1f (85 mm); R276 conclusion unchanged"
         % (q9["delta"] * 1e6, q9["f0"] / 1e6, A28 * 1e6, q9["rac_rdc"], q9["Q"], qub[85.0]["Q"]), "H.23(k)")
    h15 = [r for r in rows if r[0].startswith("held, RFC_OFF HIGH") and r[1] == 4.8][0]
    summ("R276 static drop", "%.2f mV at the H.15 E1 load (%.3f mA, held); worst %.2f mV at %.3f mA (%s, REGN %.1f V): "
         "release-level shift %.3f mV = IINDPM %.2f mA (lower, safe direction)"
         % (h15[3] * 1e3, h15[2] * 1e3, worst[3] * 1e3, worst[2] * 1e3, worst[0], worst[1], worst[4] * 1e3,
            worst[5] * 1e3), "H.23(k)")


# ======================================================================================================================
# H.23(l) EVM reference placement, USB corridor, EIB, W-lead routes, lead resistance, chassis tie
# ======================================================================================================================
G_J8 = 20.0          # mm, MB +y edge to the EVM bottom edge (J8 mates from -y; pins to EVM y -6.24, EVMG Table 2)
EVM_RIGHT = 88.50    # BASIS D7: EVM right edge x <= 88.5 (chosen at the limit)
USB = (93.47, 93.73, 101.09, 93.73 + 45.0)   # BASIS D7 corridor x 93.47-101.09 from y 93.73; 45 mm plug + bend ASSUMPTION
APPROACH = 10.0      # mm straight approach normal to a terminal's wire-entry face (ferrule + strain relief) ASSUMPTION
AWG20_OD = 1.6       # mm, 20 AWG PVC hook-up wire outer diameter, ASSUMPTION (TODO(measure: MS2 wire OD))
BEND_ALLOW = 10.5    # mm, BASIS section 11 B5: bend radius 6 x OD (9.6 mm) + OD/2 (0.8 mm) = 10.4, rounded up to 0.5 mm
EIB_W, EIB_H, EIB_INSET = 24.0, 36.0, 2.0    # DOC A.9 36 x 24 mm; pad row 2.0 mm from the EVM-facing edge ASSUMPTION
SWITCHED = ("VSW-FC", "VSW-BT")
# revision 4: conductor top heights above the MB top for the 3-D switched-conductor rule (decision 2026-11-10)
H_LFC = 5.0          # mm, Eaton HCM1A1305V3 body height (L-FC and L-BT, BOM line 9): ASSUMPTION from the "1305" size code;
#                      TODO(verify: Eaton HCM1A1305V3 drawing; caliper in MS3). The datasheet is not in references/.
H_REG = 1.0          # mm, TPS61288 VQFN-HR (RQQ0011A) "1 mm max height" (references/Datasheets/TPS61288LRQQR.pdf)
H_POUR = 0.0         # mm, VSW-FC / VSW-BT layer-1 pours: copper at the MB top (decision 2026-11-10)
Z_CR_TOP = 4.265     # mm, CR top above the MB top (H.23(j)); a W lead on the CR lies on it
W5_FOLD = 8.0        # mm, W5 ribbon fold height above the CR top (DOC A.3 minimum)


def evm_to_board(p, X0, Y0):
    return (X0 + p[0], Y0 + p[1])


def seg_hits_rect(a, b, r, eps=1e-7):
    """True if segment a-b passes through the open interior of rectangle r (Liang-Barsky)."""
    x0, y0, x1, y1 = r[0] + eps, r[1] + eps, r[2] - eps, r[3] - eps
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < 1e-15:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return t1 - t0 > 1e-9


def shortest(a, b, obst):
    nodes = [a, b]
    e = 1e-4
    for r in obst:
        nodes += [(r[0] - e, r[1] - e), (r[2] + e, r[1] - e), (r[2] + e, r[3] + e), (r[0] - e, r[3] + e)]
    n = len(nodes)
    dist = [1e18] * n
    prev = [-1] * n
    dist[0] = 0.0
    done = [False] * n
    for _ in range(n):
        u = min((d, i) for i, d in enumerate(dist) if not done[i])[1]
        done[u] = True
        if u == 1:
            break
        for v in range(n):
            if done[v]:
                continue
            if any(seg_hits_rect(nodes[u], nodes[v], r) for r in obst):
                continue
            nd = dist[u] + math.hypot(nodes[v][0] - nodes[u][0], nodes[v][1] - nodes[u][1])
            if nd < dist[v]:
                dist[v], prev[v] = nd, u
    path, k = [], 1
    while k != -1:
        path.append(nodes[k])
        k = prev[k]
    return dist[1], path[::-1]


W_TERM = {     # lead: (terminal label, EVM pin (EVMG Table 2), wire-entry face, face coordinate, Ohm/m, CR pad)
    "W1": ("J1 pin 2 VIN1", (6.604, 50.799), "-x", 2.604, R20, (30.3, 61.2)),
    "W2": ("J1 pin 1 PGND", (6.604, 55.879), "-x", 2.604, R20, (27.7, 61.2)),
    "W3": ("J5 pin 1 BATTERY", (82.487, 24.193), "+x", 86.488, R18, (24.3, 45.4)),
    "W4": ("J5 pin 3 PGND", (82.487, 34.353), "+x", 86.488, R18, (24.3, 55.6)),
    "W6": ("J7 pin 1 EXT_TS", (62.894, 6.223), "-y", 2.773, R26, (33.0, 57.5)),
    "W7 SCL": ("J8 pin 2 SCL (pin tip)", (18.034, -6.24), "-ypin", -6.24, R28, (27.0, 57.5)),
    "W7 SDA": ("J8 pin 3 SDA (pin tip)", (20.574, -6.24), "-ypin", -6.24, R28, (31.0, 57.5)),
    "W5": ("EIB J201, 3 mm inside the EIB +x edge (ASSUMPTION)", None, "eib", None, None, (40.75, 46.83)),
}
TIE_XMAX = TAB_X[2] + math.sqrt(30.0 ** 2 - (MB_OUTLINE[3] - TAB_X[3]) ** 2)
USB_OPEN = (USB[0], USB[1], USB[2], 1000.0)        # BASIS section 10 A4: open-ended corridor (no end in +y)


def w_routes(X0, Y0, evm, eib, usb, leads=None):
    """Route rule for the W leads at an EVM placement (lower-left corner X0, Y0) and an EIB rectangle. The W5
    terminal is J201, 3 mm inside the EIB +x edge (ASSUMPTION). A lead is 'blocked' when its approach point lies inside
    an obstacle (the corridor), when no path exists, or when the only path runs around the MB (below its +y edge)."""
    mb = MB_OUTLINE
    sw = [s for s in SHAPES if s["net"] in SWITCHED and s["kind"] in ("poly", "wire")]
    swb = [ELS[n]["bbox"] for n in ("REG-FC", "REG-BT", "L-BT")] + [LFC_EATON]
    obst = [mb, evm, usb, eib]
    j201 = (eib[2] - 3.0, (eib[1] + eib[3]) / 2)
    res = {}
    for lead, (lab, pin, face, fc, Rw, p0) in W_TERM.items():
        if leads is not None and lead not in leads:
            continue
        if face == "eib":
            term = j201
            app = (j201[0], eib[1] - APPROACH)
            obs = [mb, evm, usb]
        else:
            pb = evm_to_board(pin, X0, Y0)
            if face == "-x":
                fx = X0 + fc
                app = (fx - APPROACH, pb[1])
            elif face == "+x":
                fx = X0 + fc
                app = (fx + APPROACH, pb[1])
            elif face == "-y":
                fy = Y0 + fc
                app = (pb[0], fy - APPROACH)
            else:
                app = (pb[0], pb[1] - APPROACH)
            term = pb
            obs = obst
        blocked = None
        for r in obs:
            if r[0] < app[0] < r[2] and r[1] < app[1] < r[3]:
                blocked = "approach point (%.2f, %.2f) inside %s" % (app[0], app[1], "the USB corridor" if r is usb
                                                                     else "an obstacle")
        best = None
        x2s = [56.0 + 0.25 * k for k in range(int(math.floor((min(80.0, TIE_XMAX) - 56.0) / 0.25 + 1e-9)) + 1)]
        cache = {}
        if blocked is None:
            for x2 in x2s:
                P2 = (x2, mb[3])
                if x2 not in cache:
                    cache[x2] = shortest(P2, app, obs)
                dpath, nodes = cache[x2]
                for k in range(37):
                    x1 = 56.0 + 0.25 * k
                    P1 = (x1, TAB_X[3])
                    L = math.hypot(P1[0] - p0[0], P1[1] - p0[1]) + math.hypot(P2[0] - P1[0], P2[1] - P1[1]) + dpath + \
                        math.hypot(term[0] - app[0], term[1] - app[1])
                    if best is None or L < best[0]:
                        best = (L, P1, P2, nodes)
            if best[0] > 1e17:
                blocked = "no path around the obstacles"
            elif any(n[1] < mb[3] - 1e-3 for n in best[3][1:]):
                blocked = "the only path runs around the MB (below its +y edge): the corridor walls off the +x side"
        if blocked is not None and best is None:
            best = (float("nan"), (float("nan"), TAB_X[3]), (float("nan"), mb[3]), [])
        L, P1, P2, nodes = best
        # switched-conductor distance of the corridor segment and of the CR segment
        sd = float("nan")
        if L == L:
            sd = 1e9
            for segm in ((p0, P1), (P1, P2)):
                for s in sw:
                    sd = min(sd, min(dseg_seg(segm[0], segm[1], a, b) for a, b in shape_segs(s)) - s["r"]
                             if not (s["closed"] and any(pip(q[0], q[1], s["pts"]) for q in segm)) else 0.0)
                for bx in swb:
                    sd = min(sd, min(dseg_seg(segm[0], segm[1], a, b) for a, b in edges(rpoly(bx))))
        tie = math.hypot(max(0.0, P2[0] - TAB_X[2]), P2[1] - TAB_X[3]) if L == L else float("nan")
        mx = int(math.ceil(1.25 * L / 10.0 - 1e-9)) * 10 if (L == L and blocked is None) else None
        res[lead] = dict(term=lab, L=L, max=mx, P1=P1, P2=P2, nodes=nodes, app=app, tie=tie, sw=sd, R=Rw, tpt=term,
                         blocked=blocked)
    return res


def e_leads(xcol_evm, label):
    """E-lead straight lengths and r6-rule build maxima (straight x 1.25 rounded up to 5 mm) for an EIB pad column at
    EVM-frame x xcol_evm (rows as DOC A.9: E3 5 mm above the TP33 level, 2.54 mm pitch)."""
    e3y = EVM_PTS["TP33"][1] + 5.0
    res = {}
    for e, (row, pt) in E_ROWS.items():
        y = e3y - (row - 3) * 2.54
        p = EVM_PTS[pt]
        s = math.hypot(xcol_evm - p[0], y - p[1])
        res[e] = (s, int(math.ceil(s * 1.25 / 5.0 - 1e-9)) * 5)
    return res


def e1_resonance(Lmm):
    Lm = Lmm * 1e-3
    Ll = loop_L(Lm, 5e-3)
    f0 = 1 / (2 * math.pi * math.sqrt(Ll * C205))
    Z0 = math.sqrt(Ll / C205)
    rl = R28 * 2 * Lm + ESR205
    _, kac, _ = skin(f0)
    return dict(L=Ll, f0=f0, Z0=Z0, Q=Z0 / rl, Q_ac=Z0 / (R28 * 2 * Lm * kac + ESR205), Q_R276=Z0 / (rl + R276))


# ---------------------------------------------------------------------------------------------------------------------
# r7 review 7 (D-F2, D-F3): the designed W-lead dressing path, anchors, spans, MB crossings, hard short
# ---------------------------------------------------------------------------------------------------------------------
OD = {"W1": [AWG20_OD], "W2": [AWG20_OD], "W3": [2.0], "W4": [2.0], "W6": [1.0, 1.0], "W7 SCL": [0.8],
      "W7 SDA": [0.8], "W7 GND": [0.8]}           # mm jacket OD: 20 AWG 1.6 (above), 18 AWG silicone 2.0, 26 AWG 1.0,
#                                                   28 AWG 0.8 (ASSUMPTION; TODO(measure: MS2/MS7 wire OD))
RIBBON_W = 14 * 0.635                              # mm, W5 14-way 0.635 mm flat cable width (DOC A.3)
HAZ_GAP = 2.0                                      # mm plan gap of every W lead jacket edge to the listed CR hazards (D-F2)
SW_GAP = 10.0                                      # mm to the MB switched conductors (route rule)
REWORK_GAP = 1.5                                   # mm to the MB rework points C-D2/R171, D-FC-EN (EN bodge), C-D1
BEAD_LEN = 5.0                                     # mm, A.3 RTV bead over the jackets at each CR joint (exempt span)
SPAN_MAX = 30.0                                    # mm, unsupported lead length between anchors (D-F2)
TIE_TOL = 1.5                                      # mm, MB tie-base position tolerance (D-F2)
W5_ALLOW = 20.0                                    # mm, W5 3-D allowance (J101 rise and fold, J201 drop) ASSUMPTION
W12_BUILD = (290.0, 300.0, 310.0)                  # mm, W1/W2 fixed build length 0.30 m +- 10 mm (D-F3)
WP = dict(T0=(25.80, 57.00), J67=(25.80, 59.20), T1=(25.80, 62.60), B1=(25.80, 64.50), T2=(25.80, 69.60),
          T3=(31.00, 69.60), B3=(35.00, 70.80), T4=(36.00, 71.10), T5=(46.00, 71.10), T6=(48.00, 71.75),
          A1=(60.50, 73.50), WN=(58.00, 76.00), E1=(61.00, 85.50), A2=(71.50, 88.00),
          S1=(36.00, 46.83), F1=(28.70, 46.83), S2=(28.70, 55.00), F2=(28.70, 73.10), S3=(35.00, 73.10),
          F3=(42.00, 73.10), F4=(44.50, 73.80), A1R=(60.50, 73.80), E1R=(61.00, 85.80))
TIE_BASES = {"A1": (WP["A1"], 6.0), "A2": (WP["A2"], 10.0)}   # centre, square base side (ASSUMPTION; TODO(verify:
#                                                              adhesive tie-base datasheet))
CR_ANCHORS = {"B1": WP["B1"], "B3": WP["B3"], "S1": WP["S1"], "S2": WP["S2"], "S3": WP["S3"]}
WEST = ("W1", "W2", "W6", "W7 SCL", "W7 SDA")
EAST = ("W3", "W4", "W5")
X_EDGE_W = 58.00


def hgrp(leads):
    ods = [o for ld in leads for o in OD[ld]]
    if len(ods) == 1:
        return ods[0] / 2
    return max(max(ods), 0.575 * math.sqrt(sum(o * o for o in ods)))


H_TRUNK = hgrp(["W1", "W2", "W3", "W4", "W6", "W7 SCL", "W7 SDA", "W7 GND"])
H_WEST = hgrp(["W1", "W2", "W6", "W7 SCL", "W7 SDA", "W7 GND"])
H_EAST = hgrp(["W3", "W4"])                       # W3/W4 pair; W5 lies beside it flat (RIBBON_W / 2)


def w_paths():
    """Fixed CR + MB dressing path of each lead up to its last MB point before the MB +y edge, as [(point, h of the
    segment that starts at this point)]; the east group's MB-edge crossing is optimised in w_routes2."""
    P = WP
    trunk_low = [(P["T0"], hgrp(["W3", "W4"])), (P["J67"], hgrp(["W3", "W4", "W6", "W7 SCL", "W7 SDA", "W7 GND"]))]
    trunk = [(P["T1"], H_TRUNK), (P["B1"], H_TRUNK), (P["T2"], H_TRUNK), (P["T3"], H_TRUNK), (P["B3"], H_TRUNK),
             (P["T4"], H_TRUNK), (P["T5"], H_TRUNK), (P["T6"], H_TRUNK)]
    west = [(P["A1"], H_WEST), (P["WN"], H_WEST)]
    east = [(P["A1"], hgrp(["W3", "W4"])), (P["E1"], hgrp(["W3", "W4"])), (P["A2"], hgrp(["W3", "W4"]))]
    east5 = [(P["A1R"], RIBBON_W / 2), (P["E1R"], RIBBON_W / 2), (P["A2"], RIBBON_W / 2)]   # W5 flat on the MB from A1
    w7h = hgrp(["W7 SCL", "W7 SDA", "W7 GND"])
    paths = {
        "W1": [((30.30, 61.20), hgrp(["W1", "W2"]))] + trunk + west,
        "W2": [((27.70, 61.20), hgrp(["W1", "W2"]))] + trunk + west,
        "W3": [((24.30, 45.40), OD["W3"][0] / 2), ((24.40, 47.00), OD["W3"][0] / 2),
               ((24.40, 54.00), OD["W3"][0] / 2)] + trunk_low + trunk + east,
        "W4": [((24.30, 55.60), OD["W4"][0] / 2)] + trunk_low + trunk + east,
        "W6": [((33.00, 57.50), hgrp(["W6"])), ((33.00, 59.00), hgrp(["W6"]))] + trunk_low[1:] + trunk + west,
        "W7 SCL": [((27.00, 57.50), w7h)] + trunk_low[1:] + trunk + west,
        "W7 SDA": [((31.00, 57.50), w7h), ((31.00, 59.00), w7h)] + trunk_low[1:] + trunk + west,
        # revision 4: S1/S2 are spacer positions under the ribbon (H.23(l) place_spacers), not path waypoints; the path
        # is unchanged (S1 (36.00, 46.83) and S2 (28.70, 55.00) were collinear waypoints)
        "W5": [((40.75, 46.83), RIBBON_W / 2), (P["F1"], RIBBON_W / 2),
               (P["F2"], RIBBON_W / 2), (P["S3"], RIBBON_W / 2),
               (P["F3"], RIBBON_W / 2), (P["F4"], RIBBON_W / 2)] + east5,
    }
    return paths


def arclen(pts):
    s = [0.0]
    for i in range(1, len(pts)):
        s.append(s[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    return s


def hazard_rects():
    """CR hazards of the dressing rule (D-F2): name -> rectangle (x0, y0, x1, y1); 'field' is a never-over area."""
    hz = {}
    for k, (x, y) in enumerate(PINS):
        nm = ("1x12 pin %d post" % (22 - k)) if k < 12 else ("1x10 pin %d post" % (k - 11))
        hz[nm] = (x - POST / 2, y - POST / 2, x + POST / 2, y + POST / 2)
    hz["pin-10 pad (VCHG-IN)"] = (45.998 - 0.95, 61.944 - 0.95, 45.998 + 0.95, 61.944 + 0.95)
    for nm, r in (("C102c", (40.3, 60.10, 43.3, 61.55)), ("C102a", (39.8, 55.30, 42.1, 60.05)),
                  ("R102", (42.65, 56.65, 44.45, 60.05)), ("C102b", (39.75, 52.05, 44.50, 55.25)),
                  ("D107", (36.60, 53.40, 39.70, 60.00))):
        hz["IN strip %s" % nm] = r
    hz["U101 courtyard"] = (39.3, 61.6, 44.3, 66.6)
    hz["+x pocket"] = (44.3, 63.40, 48.2, 66.64)
    fx = FIELD
    for t, (c, r) in fx["place"].items():
        x, y = fx["xs"][c], fx["ys"][r]
        hz["tap pad %s %s" % (TAPS[t][0], t)] = (x - PAD / 2, y - PAD / 2, x + PAD / 2, y + PAD / 2)
    for t, p in fx["resid"].items():
        hz["tap pad %s %s" % (TAPS[t][0], t)] = (p[0] - PAD / 2, p[1] - PAD / 2, p[0] + PAD / 2, p[1] + PAD / 2)
    return hz


def path_min(path, rects, s_from=0.0, square=False):
    """Minimum over the path (from arc length s_from) of the jacket-edge distance to any rect: (value, rect name, s).
    Round lead: centreline distance - h. square=True (the flat W5 ribbon): an axis-aligned segment sweeps the
    rectangle bbox +- h (square fold corners), not extended at a cut end."""
    pts = [p for p, _ in path]
    s = arclen(pts)
    best = (1e9, None, None)
    for i in range(len(pts) - 1):
        a, b, h = pts[i], pts[i + 1], path[i][1]
        if s[i + 1] <= s_from:
            continue
        cut = s[i] < s_from
        if cut:
            t = (s_from - s[i]) / (s[i + 1] - s[i])
            a = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        axis = abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9
        sw = None
        if square and axis:
            sw = [min(a[0], b[0]) - h, min(a[1], b[1]) - h, max(a[0], b[0]) + h, max(a[1], b[1]) + h]

            def coll(p, q, r_):
                return abs((q[0] - p[0]) * (r_[1] - p[1]) - (q[1] - p[1]) * (r_[0] - p[0])) < 1e-9
            # no extension along the run at a cut end or where the run continues straight (only at a fold)
            ends = [(a, cut or (i > 0 and coll(pts[i - 1], a, b))),
                    (b, i + 2 < len(pts) and coll(a, b, pts[i + 2]))]
            for p_, flat in ends:
                if not flat:
                    continue
                if abs(a[1] - b[1]) < 1e-9:
                    sw[0 if p_[0] <= min(a[0], b[0]) + 1e-9 else 2] = p_[0]
                else:
                    sw[1 if p_[1] <= min(a[1], b[1]) + 1e-9 else 3] = p_[1]
        for nm, r in rects.items():
            if sw is not None:
                d = rect_dist(sw, r) if not rect_overlap(sw, r) else -min(sw[2] - r[0], r[2] - sw[0], sw[3] - r[1],
                                                                          r[3] - sw[1])
            else:
                d = d_rect_seg(r, a, b) - h
            if d < best[0]:
                best = (d, nm, s[i])
    return best


def sw_min(path, s_from=0.0):
    sw = [s for s in SHAPES if s["net"] in SWITCHED and s["kind"] in ("poly", "wire")]
    swb = {n: ELS[n]["bbox"] for n in ("REG-FC", "REG-BT", "L-BT")}
    swb["L-FC (Eaton body)"] = LFC_EATON
    pts = [p for p, _ in path]
    best = (1e9, None)
    for i in range(len(pts) - 1):
        a, b, h = pts[i], pts[i + 1], path[i][1]
        for s_ in sw:
            if s_["closed"] and any(pip(q[0], q[1], s_["pts"]) for q in (a, b)):
                d = -h
            else:
                d = min(dseg_seg(a, b, p, q) for p, q in shape_segs(s_)) - s_["r"] - h
            if d < best[0]:
                best = (d, "%s %s" % (s_["net"], s_["kind"]))
        for nm, bx in swb.items():
            d = d_rect_seg(bx, a, b) - h
            if d < best[0]:
                best = (d, nm)
    return best


def in_spike(v0, cs, lin, cin, rin=0.045, ron=0.031, cout=1.0e-6, lout=0.15e-6, dt=1e-9, tend=12e-6):
    """round3/calc/r3_calc.py H.19(b) in_spike(), ported unchanged; it also returns the OUT-lead (W1/W2) peak current."""
    vs, vin, vout = v0, v0, v0
    i_in, i_fet, i_out = 0.0, 0.0, 0.0
    t, t_cross, on, vpk, i_off, i_out_pk = 0.0, None, True, v0, 0.0, 0.0
    while t < tend:
        di_in = (vs - i_in * rin - vin) / lin
        i_in += di_in * dt
        i_fet = (vin - vout) / ron if on else 0.0
        di_out = vout / lout
        i_out += di_out * dt
        i_out_pk = max(i_out_pk, i_out)
        vs -= i_in / cs * dt
        vin += (i_in - i_fet) / cin * dt
        vout += (i_fet - i_out) / cout * dt
        if on and t_cross is None and i_fet > 45.0:
            t_cross = t
        if on and t_cross is not None and t >= t_cross + 1e-6:
            on = False
            i_off = i_in
        if not on:
            vpk = max(vpk, vin)
        t += dt
    return vpk, i_off, i_out_pk


def w_routes2(X0, Y0, evm, eib, usb, leads=None, w5_channel=None):
    """Route rule on the designed dressing path (r7 review 7): fixed CR + MB path to the last MB anchor, MB +y edge
    crossing (west group straight up at x 58.00; east group optimised within 30 mm of A2), then the shortest path
    around the obstacles to the terminal's approach point. w5_channel: an extra W5 obstacle (the W3/W4 channel) with
    the EVM not an obstacle for W5 (W5 crosses over the EVM plate)."""
    mb = MB_OUTLINE
    obst = [mb, evm, usb, eib]
    j201 = (eib[2] - 3.0, (eib[1] + eib[3]) / 2)
    paths = w_paths()
    res = {}
    for lead, (lab, pin, face, fc, Rw, p0) in W_TERM.items():
        if leads is not None and lead not in leads:
            continue
        if face == "eib":
            term = j201
            app = (j201[0], eib[1] - APPROACH)
            obs = [mb, usb] + ([w5_channel] if w5_channel else [evm])
        else:
            pb = evm_to_board(pin, X0, Y0)
            if face == "-x":
                app = (X0 + fc - APPROACH, pb[1])
            elif face == "+x":
                app = (X0 + fc + APPROACH, pb[1])
            elif face == "-y":
                app = (pb[0], Y0 + fc - APPROACH)
            else:
                app = (pb[0], pb[1] - APPROACH)
            term = pb
            obs = obst
        blocked = None
        for r in obs:
            if r[0] < app[0] < r[2] and r[1] < app[1] < r[3]:
                blocked = "approach point (%.2f, %.2f) inside %s" % (app[0], app[1], "the USB corridor" if r is usb
                                                                     else "an obstacle")
        fixed = paths[lead]
        fpts = [p for p, _ in fixed]
        Lfix = arclen(fpts)[-1]
        last = fpts[-1]
        if lead in WEST:
            x2s = [X_EDGE_W]
        else:
            x2s = [last[0] + 0.25 * k for k in range(-112, 113)
                   if math.hypot(0.25 * k, mb[3] - last[1]) <= SPAN_MAX and 0.0 < last[0] + 0.25 * k < mb[2]]
        best = None
        if blocked is None:
            for x2 in x2s:
                P2 = (x2, mb[3])
                dpath, nodes = shortest(P2, app, obs)
                L = Lfix + math.hypot(P2[0] - last[0], P2[1] - last[1]) + dpath + \
                    math.hypot(term[0] - app[0], term[1] - app[1])
                if best is None or L < best[0]:
                    best = (L, P2, nodes)
            if best[0] > 1e17:
                blocked = "no path around the obstacles"
            elif any(n[1] < mb[3] - 1e-3 for n in best[2][1:]):
                blocked = "the only path runs around the MB (below its +y edge)"
        if best is None:
            best = (float("nan"), (float("nan"), mb[3]), [])
        L, P2, nodes = best
        full = fixed + [(P2, fixed[-1][1])]
        mx = int(math.ceil(1.25 * L / 10.0 - 1e-9)) * 10 if (L == L and blocked is None) else None
        res[lead] = dict(term=lab, L=L, max=mx, P2=P2, nodes=nodes, app=app, R=Rw, tpt=term, blocked=blocked,
                         path=full, Lmb=arclen([p for p, _ in full])[-1])
    return res


def bottleneck(h, res=0.25):
    """Largest switched-conductor clearance (jacket edge) of any plan path from the trunk start to the MB +y edge
    that keeps the 2 mm hazard rule with half-width h (raster BFS + bisection)."""
    x0, y0, x1, y1 = 5.0, 30.0, 80.0, 99.0
    nx, ny = int((x1 - x0) / res), int((y1 - y0) / res)
    hz = list(hazard_rects().items())
    fcy = FIELD["cyd"]
    sw = [s for s in SHAPES if s["net"] in SWITCHED and s["kind"] in ("poly", "wire")]
    swb = [ELS[n]["bbox"] for n in ("REG-FC", "REG-BT", "L-BT")] + [LFC_EATON]
    ok = bytearray(nx * ny)
    swd = [0.0] * (nx * ny)
    for j in range(ny):
        y = y0 + (j + 0.5) * res
        for i in range(nx):
            x = x0 + (i + 0.5) * res
            k = j * nx + i
            if min(d_rect_pt(r, x, y) for _, r in hz) >= HAZ_GAP + h and d_rect_pt(fcy, x, y) >= h:
                ok[k] = 1
            d = min(d_rect_pt(b, x, y) for b in swb)
            for s_ in sw:
                if s_["closed"] and pip(x, y, s_["pts"]):
                    d = 0.0
                    break
                d = min(d, min(dpt_seg(x, y, p[0], p[1], q[0], q[1]) for p, q in shape_segs(s_)) - s_["r"])
            swd[k] = d - h
    st = (int((WP["T0"][0] - x0) / res), int((WP["T0"][1] - y0) / res))

    def reach(D):
        seen = bytearray(nx * ny)
        k0 = st[1] * nx + st[0]
        seen[k0] = 1
        q = [k0]
        while q:
            k = q.pop()
            j, i = divmod(k, nx)
            if y0 + (j + 0.5) * res >= MB_OUTLINE[3] - res:
                return True
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < nx and 0 <= jj < ny:
                    kk = jj * nx + ii
                    if not seen[kk] and ok[kk] and swd[kk] >= D:
                        seen[kk] = 1
                        q.append(kk)
        return False
    lo, hi = -10.0, 15.0
    if not reach(lo):
        return None
    for _ in range(12):
        mid = (lo + hi) / 2
        if reach(mid):
            lo = mid
        else:
            hi = mid
    return lo


SPACER_JACKET_GAP = 0.5     # mm, revision 4: spacer bead footprint to any other W-lead jacket (plan), ASSUMPTION
VIA_PAD = 0.7564            # mm, every MB via pad (H.23(c2))
CHASSIS_MARGIN = 2.0        # mm, revision 4: margin on the 30 mm span rule for the last span to the chassis tie


def place_spacers():
    """Revision 4: S1 and S2 under the W5 ribbon, off the J101 region (+ the 0.5 mm region gap), off the W6/W7 pad
    exclusion (pad + 0.5 mm), off the divider strip (+ 0.5 mm) and >= SPACER_JACKET_GAP from every other W-lead jacket
    on the CR; S1 nearest J101, S2 as high (+y) as these allow on the ribbon run x 28.70."""
    hf = ANCHOR_FP / 2
    strip = EXTRA["e2"]["strip"]
    paths = w_paths()
    others = [(pts[i][0], pts[i + 1][0], pts[i][1]) for ld, pts in paths.items() if ld != "W5"
              for i in range(len(pts) - 1) if pip(pts[i][0][0], pts[i][0][1], OUTLINE)]
    w67x = [(x - 0.6 - 0.5, y - 0.75 - 0.5, x + 0.6 + 0.5, y + 0.75 + 0.5) for x, y in W67_PADS]
    wpx = [(x - d / 2 - 0.5, y - d / 2 - 0.5, x + d / 2 + 0.5, y + d / 2 + 0.5) for x, y, d in W_PADS.values()]
    j101x = (J101_REG[0] - REGION_GAP, J101_REG[1] - REGION_GAP, J101_REG[2] + REGION_GAP, J101_REG[3] + REGION_GAP)
    stripx = (strip[0] - REGION_GAP, strip[1] - REGION_GAP, strip[2] + REGION_GAP, strip[3] + REGION_GAP)

    def sd(r, z):          # signed plan distance: negative = overlap depth (the smaller axis)
        if not rect_overlap(r, z):
            return rect_dist(r, z)
        return -min(min(r[2], z[2]) - max(r[0], z[0]), min(r[3], z[3]) - max(r[1], z[1]))

    def checks(c):
        r = (c[0] - hf, c[1] - hf, c[0] + hf, c[1] + hf)
        jk = min((d_rect_seg(r, a, b) - h, "%s-%s" % (a, b)) for a, b, h in others)
        return dict(rect=r, j101=sd(r, J101_REG), w67=min(sd(r, z) for z in w67x), wpads=min(sd(r, z) for z in wpx),
                    strip=sd(r, strip), jacket=jk[0],
                    ok=(sd(r, j101x) >= -1e-9 and min(sd(r, z) for z in w67x + wpx) >= -1e-9
                        and sd(r, stripx) >= -1e-9 and jk[0] >= SPACER_JACKET_GAP - 1e-9))
    y_rib = 46.83
    s1 = (round(J101_REG[0] - REGION_GAP - hf, 2), round(max(y_rib, strip[3] + REGION_GAP + hf) + 0.004, 2))
    xr = WP["F1"][0]
    s2 = None
    y = round(min(w[1] for w in w67x) - hf, 2)
    while y > y_rib + hf:
        c = checks((xr, y))
        if c["ok"]:
            s2 = (xr, y)
            break
        y = round(y - 0.01, 2)
    WP["S1"], WP["S2"] = s1, s2
    CR_ANCHORS["S1"], CR_ANCHORS["S2"] = s1, s2
    o1, o2 = (36.00, 46.83), (28.70, 55.00)          # r7 review-7 positions
    return {"S1": (s1, checks(s1), o1, checks(o1)), "S2": (s2, checks(s2), o2, checks(o2))}


def sw3d(path, lead, s_elev=None):
    """Revision 4 (decision 2026-11-10): the 10 mm switched-conductor rule as a 3-D distance. For each sample on the
    lead path with a plan jacket-edge distance d < 10 mm to a switched conductor of top height H, the jacket bottom
    must sit at >= H + sqrt(10^2 - d^2) above the MB top (H + 10 where d <= 0). Base height: CR top on the CR, the MB
    top off it; W5 at its fold height (CR top + 8 mm) until s_elev (A1). Returns the intervals that need a spacer."""
    sw = [(s_["net"] + " " + s_["kind"], s_, H_POUR) for s_ in SHAPES if s_["net"] in SWITCHED and
          s_["kind"] in ("poly", "wire")]
    bx = [("REG-FC box", ELS["REG-FC"]["bbox"], H_REG), ("REG-BT box", ELS["REG-BT"]["bbox"], H_REG),
          ("L-BT body", ELS["L-BT"]["bbox"], H_LFC), ("L-FC body (Eaton)", LFC_EATON, H_LFC)]
    pts = [p for p, _ in path]
    sl = arclen(pts)
    samples = []
    for i in range(len(pts) - 1):
        a, b, h = pts[i], pts[i + 1], path[i][1]
        n = max(1, int(math.ceil((sl[i + 1] - sl[i]) / 0.25)))
        for k in range(n + (1 if i == len(pts) - 2 else 0)):
            t = k / n
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            s = sl[i] + t * (sl[i + 1] - sl[i])
            if lead == "W5" and s_elev is not None and s < s_elev - 1e-9:
                zb, base = Z_CR_TOP + W5_FOLD, "fold (CR top + 8 mm)"
            elif pip(q[0], q[1], OUTLINE):
                zb, base = Z_CR_TOP, "CR top"
            else:
                zb, base = 0.0, "MB top"
            need, who, dmin = 0.0, None, 1e9
            for nm, s_, H in sw:
                if s_["closed"] and pip(q[0], q[1], s_["pts"]):
                    d = -h
                else:
                    d = min(dpt_seg(q[0], q[1], p_[0], p_[1], r_[0], r_[1]) for p_, r_ in shape_segs(s_)) - s_["r"] - h
                if d < dmin:
                    dmin = d
                if d < SW_GAP:
                    z = H + (SW_GAP if d <= 0 else math.sqrt(SW_GAP ** 2 - d * d))
                    if z > need:
                        need, who = z, (nm, d)
            for nm, r_, H in bx:
                d = d_rect_pt(r_, q[0], q[1]) - h
                if d < dmin:
                    dmin = d
                if d < SW_GAP:
                    z = H + (SW_GAP if d <= 0 else math.sqrt(SW_GAP ** 2 - d * d))
                    if z > need:
                        need, who = z, (nm, d)
            samples.append((s, q, zb, base, need, who, dmin))
    ivs, cur = [], None
    for smp in samples:
        s, q, zb, base, need, who, dmin = smp
        if need > zb + 1e-9:
            if cur is None:
                cur = dict(s0=s, p0=q, s1=s, p1=q, need=need, at=q, who=who, rise=need - zb, base=base, zb=zb,
                           bases={base}, per={})
            cur.update(s1=s, p1=q)
            cur.setdefault("prof", []).append((s, q, need, zb))
            cur["bases"].add(base)
            pb = cur["per"].setdefault(base, dict(s0=s, p0=q, s1=s, p1=q, need=need, at=q, who=who, zb=zb))
            pb.update(s1=s, p1=q)
            if need > pb["need"] + 1e-12 or (abs(need - pb["need"]) <= 1e-12 and who[1] < pb["who"][1]):
                pb.update(need=need, at=q, who=who)
            if need - zb > cur["rise"] + 1e-12:
                cur.update(rise=need - zb, base=base, zb=zb)
            if need > cur["need"] + 1e-12 or (abs(need - cur["need"]) <= 1e-12 and who[1] < cur["who"][1]):
                cur.update(need=need, at=q, who=who)
        elif cur is not None:
            ivs.append(cur)
            cur = None
    if cur is not None:
        ivs.append(cur)
    return ivs, min(z[6] for z in samples)


def sec_l():
    head("H.23(l) EVM reference placement, Teensy USB corridor, EIB position, W-lead dressing path, anchors, routes and "
         "maxima, W1/W2 hard short")
    spc = place_spacers()
    X0 = EVM_RIGHT - EVM_W
    Y0 = MB_OUTLINE[3] + G_J8
    evm = (X0, Y0, X0 + EVM_W, Y0 + EVM_W)
    out("EVM placement (BASIS D7): EVM bottom edge toward the MB, gap g = %.1f mm (J8 mates from -y; its pins reach EVM "
        "y -6.24 (EVMG Table 2), leaving %.2f mm to the MB edge for the KK housing and wire exit; TODO(verify: Molex "
        "22-01-3047 mated length), MS2); right edge x %.2f (<= 88.5). EVM board rectangle x %.2f-%.2f, y %.3f-%.3f; it "
        "overhangs the MB -x edge (x 0) by %.2f mm (chassis room TODO(measure: MS2))."
        % (G_J8, G_J8 - 6.24, EVM_RIGHT, evm[0], evm[2], evm[1], evm[3], -X0))
    out("USB corridor (BASIS D7): x %.2f-%.2f from y %.2f, length %.1f mm (plug + bend ASSUMPTION, MS2) -> y to %.2f. "
        "EVM to corridor: %.2f mm in x." % (USB[0], USB[2], USB[1], USB[3] - USB[1], USB[3], USB[0] - evm[2]))
    # EIB per the r6 rule
    xcol = evm[2] + 7.0
    e3y = Y0 + EVM_PTS["TP33"][1] + 5.0
    e8y, e6y = e3y + 2 * 2.54, e3y - 9 * 2.54
    eib = (xcol - EIB_INSET, (e8y + e6y) / 2 - EIB_H / 2, xcol - EIB_INSET + EIB_W, (e8y + e6y) / 2 + EIB_H / 2)
    ov = rect_overlap(eib, USB)
    gap_y = eib[1] - USB[3]
    out("EIB (r6 rule): pad column x %.2f, E3 y %.3f (E8 %.3f .. E6 %.3f); outline (pad row %.1f mm inside the EVM-facing "
        "long edge, row centred on the 36 mm edge, ASSUMPTION) x %.2f-%.2f, y %.2f-%.2f"
        % (xcol, e3y, e8y, e6y, EIB_INSET, eib[0], eib[2], eib[1], eib[3]))
    out("  EIB vs USB corridor: %s; the EIB lies in the corridor x band (x %.2f-%.2f) from %.2f mm above the Teensy "
        "edge y %.2f, %.2f mm beyond the assumed 45 mm corridor. A USB cable that runs straight +y for more than %.1f mm "
        "would meet it (MS2)." % ("OVERLAP" if ov else "no overlap", max(eib[0], USB[0]), min(eib[2], USB[2]),
                                  eib[1] - USB[1], USB[1], gap_y, eib[1] - USB[1]))
    j5top = Y0 + 36.773
    out("  EIB bottom edge to the J5 body top (W3/W4 entry below the EIB, DOC A.7 >= 3 mm): %.2f mm" % (eib[1] - j5top))
    eib_choice = "r6 rule kept (EIB beside the EVM right edge)" if not ov else "COLLISION: alternative needed"
    T = W_TERM
    j201 = (eib[2] - 3.0, (eib[1] + eib[3]) / 2)
    mb = MB_OUTLINE
    tie_xmax = TIE_XMAX
    old = w_routes(X0, Y0, evm, eib, USB)
    out("(**superseded in r7:** route rule CR pad -> straight to the tab X top edge (x1 56-65) -> MB +y edge (x2 56-68.91) "
        "with a chassis tie at the MB edge; route / maximum mm: %s. That first segment crossed the pin-10 post, the IN "
        "strip and the tap field; r7 review 7, D-F2.)" % ", ".join("%s %.1f / %d" % (k, v["L"], v["max"])
                                                                   for k, v in old.items()))
    out("Designed dressing path (r7 review 7, D-F2; board mm): every W lead leaves its CR joint inside the A.3 RTV bead "
        "(first %.0f mm), joins the TRUNK on the footprint (x %.2f, from y %.2f; W3 runs up x 24.40 from its hole and "
        "pairs with W4 at y %.2f, W6/W7 join at y %.2f, W1/W2 at y %.2f), passes onto tab Y, turns +x at y %.2f on the -y side of the FT2 fill-hole disc, "
        "rises to y %.2f past the U101 courtyard and the +x pocket and to y %.2f past the tap pads (off the CR from the "
        "tab Y edge x 37.56), and reaches the MB tie base A1 (%.2f, %.2f). From A1 the WEST group (W1, W2, W6, W7) runs "
        "to (%.2f, %.2f) and straight up x %.2f to the MB +y edge; the EAST group (W3, W4, W5) runs up x %.2f to "
        "(%.2f, %.2f), clear of D-FC-EN and C-D1, to the MB tie base A2 (%.2f, %.2f) and crosses the MB +y edge "
        "within %.0f mm of A2. W5 (flat, %.2f mm wide) rises at J101, folds -x at >= 8 mm above the CR top to "
        "(%.2f, %.2f), runs +y over the interior to (%.2f, %.2f), +x at y %.2f, steps to y %.2f over x %.2f-%.2f "
        "(clear of the tap pads) and lies flat on the MB from A1, supported on spacer beads S1 "
        "(%.2f, %.2f), S2 (%.2f, %.2f) and S3 (%.2f, %.2f) (S3 next to the B3 spot). Envelope half-widths (jacket edge "
        "about the centreline; OD ASSUMPTION, TODO(measure: MS2/MS7)): trunk %.2f, west group %.2f, east group %.2f "
        "(the ribbon), W3/W4 pair %.2f, single 18 AWG %.2f mm."
        % (BEAD_LEN, WP["T0"][0], WP["T0"][1], WP["T0"][1], WP["J67"][1], WP["T1"][1], WP["T2"][1], WP["T4"][1],
           WP["T6"][1], WP["A1"][0], WP["A1"][1], WP["WN"][0], WP["WN"][1], X_EDGE_W, WP["E1"][0], WP["E1"][0],
           WP["E1"][1], WP["A2"][0], WP["A2"][1], SPAN_MAX, RIBBON_W, WP["F1"][0], WP["F1"][1], WP["F2"][0],
           WP["F2"][1], WP["F2"][1], WP["F4"][1], WP["F3"][0], WP["F4"][0], WP["S1"][0], WP["S1"][1], WP["S2"][0],
           WP["S2"][1], WP["S3"][0], WP["S3"][1],
           H_TRUNK, H_WEST, H_EAST, hgrp(["W3", "W4"]), OD["W3"][0] / 2))
    for nm, (c, ck, c0, ck0) in spc.items():
        out("  spacer bead %s (revision 4; %.1f x %.1f mm footprint, ASSUMPTION) at (%.2f, %.2f), under the ribbon (offset "
            "%.2f mm from its centreline): J101 region %.2f mm (region gap >= %.1f), W6/W7 pads %.2f mm from their + 0.5 "
            "mm exclusion, W1-W4 pad exclusion %.2f mm, divider strip %.2f mm, nearest other W-lead jacket %.2f mm (rule "
            ">= %.1f): %s (**superseded in r7:** (%.2f, %.2f): J101 region %.2f mm, W6/W7 exclusion %.2f mm, jacket "
            "%.2f mm)"
            % (nm, ANCHOR_FP, ANCHOR_FP, c[0], c[1], abs(c[1] - 46.83) if nm == "S1" else abs(c[0] - WP["F1"][0]),
               ck["j101"], REGION_GAP, ck["w67"], ck["wpads"], ck["strip"], ck["jacket"], SPACER_JACKET_GAP,
               "pass" if ck["ok"] else "FAIL", c0[0], c0[1], ck0["j101"], ck0["w67"], ck0["jacket"]))
    res = w_routes2(X0, Y0, evm, eib, USB, w5_channel=(evm[2], MB_OUTLINE[3], USB[0], USB[3]))
    hz = hazard_rects()
    rework = {"C-D2 (R171 / T2 joint)": ELS["C-D2"]["bbox"], "D-FC-EN (EN bodge)": ELS["D-FC-EN"]["bbox"],
              "C-D1": ELS["C-D1"]["bbox"]}
    out("")
    out("  per lead (CR + MB span from the joint to the MB +y edge; clearance = jacket edge, the first %.0f mm in the "
        "bead excluded; W5 from the J101 region edge x 37.0):" % BEAD_LEN)
    chk = {}
    for lead, r in res.items():
        path = r["path"]
        sq = lead == "W5"
        s0 = (40.75 - J101_REG[0]) if sq else BEAD_LEN
        hmin = path_min(path, hz, s0, square=sq)
        hbead = path_min(path, hz, 1e-9, square=sq)
        fmin = path_min(path, {"tap field courtyard": FIELD["cyd"]}, s0, square=sq)
        swm = sw_min(path)
        rwm = path_min(path, rework, 0.0)
        chk[lead] = dict(haz=hmin, bead=hbead, field=fmin, sw=swm, rework=rwm)
        out("  %-7s hazards (>= %.1f): %.2f mm (%s)%s; tap field courtyard %.2f mm; switched conductors (>= %.0f): "
            "%.2f mm (%s); MB rework points (>= %.1f): %.2f mm (%s)"
            % (lead, HAZ_GAP, hmin[0], hmin[1], ("; inside the joint bead / J101 zone %.2f mm (%s)" % (hbead[0], hbead[1]))
               if hbead[0] < hmin[0] - 1e-6 else "", fmin[0], SW_GAP, swm[0], swm[1], REWORK_GAP, rwm[0], rwm[1]))
    zr = (J101_REG[0], 46.83 - RIBBON_W / 2, 40.75, 46.83 + RIBBON_W / 2)
    zmin = min(((rect_dist(zr, r), nm) for nm, r in hz.items() if nm.startswith("IN strip")), key=lambda z: z[0])
    lfc_ov = WP["F2"][1] + RIBBON_W / 2 - LFC_EATON[1]
    out("  W5 exceptions (flat ribbon, square fold corners): over the J101 region x %.2f-40.75 (the riser and the fold, "
        ">= 8 mm above the CR top) the ribbon edge lies %.3f mm in plan from %s, because A.8 sets the J101 region "
        "0.50 mm below the IN strip; the S1 spacer bead holds the fold height there. The tab Y run at y %.2f +- %.3f "
        "overlaps the L-FC body (y >= %.3f) by %.2f mm in plan, %.1f mm or more above the MB (8 mm fold height + the "
        "4.265 mm CR top), L-FC body height TODO(verify: L-FC datasheet)." % (J101_REG[0], zmin[0], zmin[1], WP["F2"][1],
                                                                             RIBBON_W / 2, LFC_EATON[1], lfc_ov,
                                                                             8.0 + 4.265))
    bad_h = [k for k, v in chk.items() if v["haz"][0] < HAZ_GAP - 1e-6 or v["field"][0] < 0]
    bad_rw = [k for k, v in chk.items() if v["rework"][0] < REWORK_GAP - 1e-6]
    sw_all = min(v["sw"][0] for v in chk.values())
    out("  dressing rule (D-F2): hazard gap %s; tap field never crossed %s; MB rework points %s"
        % ("met by every lead" if not [k for k in bad_h if chk[k]["haz"][0] < HAZ_GAP - 1e-6] else
           "FAILS for " + ", ".join(bad_h), "yes" if all(v["field"][0] >= 0 for v in chk.values()) else "NO",
           "met" if not bad_rw else "below 1.5 mm for " + ", ".join(bad_rw)))
    b_tr = bottleneck(H_TRUNK)
    b_1 = bottleneck(0.5)
    out("  switched-conductor rule (>= %.0f mm): the designed path keeps %.2f mm (worst lead). FEASIBILITY: the L-FC "
        "body (Eaton 12.9 mm, y >= %.3f) lies 0.862 mm past the tab Y +y edge, so every point of tab Y and the footprint "
        "strip y > %.2f is within 10 mm of it, and the 2 mm hazard rule closes every other exit (U101/+x pocket/IN "
        "strip/pin-10 post and the tap pads). Raster check (0.25 mm, BFS from the trunk start to the MB +y edge over "
        "all plan paths that keep the 2 mm hazard rule): largest achievable switched clearance %.2f mm for the trunk "
        "bundle (half-width %.2f) and %.2f mm for a single 1.0 mm lead; no CR exit meets 10 mm. The 10 mm rule can be "
        "met only on the MB span (from the tie base A1 on: %s)."
        % (SW_GAP, sw_all, LFC_EATON[1], LFC_EATON[1] - SW_GAP, b_tr if b_tr is not None else float("nan"), H_TRUNK,
           b_1 if b_1 is not None else float("nan"),
           ", ".join("%s %.2f" % (k, sw_min(v["path"][[z[0] for z in v["path"]].index(WP["A1R"] if k == "W5" else
                                                                                         WP["A1"]):])[0])
                     for k, v in res.items())))
    # ---- revision 4: the 10 mm switched-conductor rule as a 3-D distance (decision 2026-11-10, D-H no height limit)
    out("  3-D switched-conductor rule (revision 4; decision 2026-11-10 with the D-H statement of no height limit): where "
        "the plan jacket-edge distance d to a switched conductor is < %.0f mm, the lead is held by insulating spacers / "
        "RTV beads so that its jacket bottom sits at >= H + sqrt(%.0f^2 - d^2) above the MB top (H + %.0f where it "
        "overlaps in plan); conductor tops H: VSW-FC/VSW-BT pours %.1f mm (copper at the MB top), REG-FC/REG-BT %.1f mm "
        "(TPS61288LRQQR.pdf VQFN-HR 1 mm max height), L-FC/L-BT %.1f mm (ASSUMPTION from the HCM1A1305V3 size code; "
        "TODO(verify: Eaton HCM1A1305V3 drawing), MS3 caliper); lead bases: CR top %.3f mm on the CR, MB top off it, "
        "W5 at its fold (CR top + %.0f mm = %.3f mm) until A1. A spacer is needed where the requirement exceeds the base:"
        % (SW_GAP, SW_GAP, SW_GAP, H_POUR, H_REG, H_LFC, Z_CR_TOP, W5_FOLD, Z_CR_TOP + W5_FOLD))
    sw3d_res = {}
    prof_done = set()
    for lead, r in res.items():
        pts_ = [p for p, _ in r["path"]]
        s_el = arclen(pts_)[pts_.index(WP["A1R"])] if lead == "W5" else None
        ivs, dmin = sw3d(r["path"], lead, s_el)
        sw3d_res[lead] = ivs
        if not ivs:
            out("    %-7s no spacer needed (minimum plan distance %.2f mm)" % (lead, dmin))
            continue
        for iv in ivs:
            out("    %-7s s %.1f-%.1f mm, (%.2f, %.2f) -> (%.2f, %.2f): %s"
                % (lead, iv["s0"], iv["s1"], iv["p0"][0], iv["p0"][1], iv["p1"][0], iv["p1"][1],
                   "; ".join("over the %s (%.3f mm) from (%.2f, %.2f) to (%.2f, %.2f): jacket bottom >= %.2f mm above "
                             "the MB top = a spacer %.2f mm above the %s (controlling: %s at plan %.2f mm, at "
                             "(%.2f, %.2f))" % (b, pb["zb"], pb["p0"][0], pb["p0"][1], pb["p1"][0], pb["p1"][1],
                                                pb["need"], pb["need"] - pb["zb"], b, pb["who"][0], pb["who"][1],
                                                pb["at"][0], pb["at"][1])
                             for b, pb in sorted(iv["per"].items(), key=lambda z: z[1]["s0"]))))
            key_ = (round(iv["p0"][0], 2), round(iv["p0"][1], 2), round(iv["p1"][0], 2), round(iv["p1"][1], 2))
            if key_ not in prof_done:
                prof_done.add(key_)
                pr_, last_s = [], -1e9
                for s_, q_, nd_, zb_ in iv["prof"]:
                    if s_ - last_s >= 2.5 - 1e-9 or s_ == iv["prof"][-1][0]:
                        pr_.append("(%.2f, %.2f) %.2f" % (q_[0], q_[1], nd_))
                        last_s = s_
                out("            required jacket-bottom height above the MB top along this run (every 2.5 mm; shared by "
                    "every lead with the same run): %s" % ", ".join(pr_))
    out("    the plan raster bound above stays as information: no plan path meets 10 mm on the CR, so the rule is met in "
        "3-D by the spacer heights listed (W5: the fold height over tab Y is raised to the listed bottom height)")
    # ---- anchors: CR beads, MB tie bases (position, tolerance, part and via check), spans along each lead
    out("  anchors (D-F2): CR RTV beads (footprint %.1f x %.1f mm each, ASSUMPTION) %s; MB adhesive tie bases:"
        % (ANCHOR_FP, ANCHOR_FP, ", ".join("%s (%.2f, %.2f)" % (k, v[0], v[1]) for k, v in CR_ANCHORS.items())))
    tb_chk = {}
    for nm, (c, side) in TIE_BASES.items():
        zone = (c[0] - side / 2 - TIE_TOL, c[1] - side / 2 - TIE_TOL, c[0] + side / 2 + TIE_TOL, c[1] + side / 2 + TIE_TOL)
        dp = min((rect_dist(p["bbox"], zone) if not rect_overlap(p["bbox"], zone) else -1.0, p["name"]) for p in PARTS)
        vz = [(v["net"], f2(v["x"]), f2(v["y"])) for v in VIAS if zone[0] - via_dia(v) / 2 < v["x"] < zone[2] +
              via_dia(v) / 2 and zone[1] - via_dia(v) / 2 < v["y"] < zone[3] + via_dia(v) / 2]
        cu = sorted({s["net"] for s in NONGND if s["kind"] in ("wire", "poly") and clearance(s, rpoly(zone)) <= 0.0})
        on_mb = zone[0] >= 0 and zone[3] <= MB_OUTLINE[3] and zone[1] >= TAB_X[3]
        tb_chk[nm] = dict(zone=zone, part=dp, vias=vz, cu=cu, on_mb=on_mb)
        out("    %s: %.1f x %.1f mm base (ASSUMPTION; TODO(verify: adhesive tie-base datasheet)) centred (%.2f, %.2f) +- %.1f "
            "mm -> zone x %.2f-%.2f, y %.2f-%.2f: nearest MB part box %.2f mm (%s); vias under the zone: %s "
            "(non-GND: %s); non-GND layer-1 copper under the zone: %s; on the MB outside the CR shadow: %s"
            % (nm, side, side, c[0], c[1], TIE_TOL, zone[0], zone[2], zone[1], zone[3], dp[0], dp[1],
               len(vz), [z for z in vz if z[0] != "GND"] or "none", ", ".join(cu) or "none (GND pour)",
               "yes" if on_mb else "NO"))
    spans = {}
    for lead, r in res.items():
        pts = [p for p, _ in r["path"]]
        s = arclen(pts)
        # revision 4: the S spacer beads carry W5 only (anywhere under the ribbon); the B beads carry the round leads
        anc = {k: v for k, v in CR_ANCHORS.items() if (k.startswith("S") == (lead == "W5"))}
        anc.update({k: v[0] for k, v in TIE_BASES.items()})
        pos = []
        for nm, q in anc.items():
            tol = (TIE_BASES[nm][1] / 2) if nm in TIE_BASES else \
                ((RIBBON_W / 2 - ANCHOR_FP / 2) if nm.startswith("S") else 0.05)   # a lead tied over a base anywhere on it
            for i in range(len(pts) - 1):
                if dpt_seg(q[0], q[1], pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) < tol:
                    a, b = pts[i], pts[i + 1]
                    L_ = math.hypot(b[0] - a[0], b[1] - a[1])
                    tt = max(0.0, min(1.0, ((q[0] - a[0]) * (b[0] - a[0]) + (q[1] - a[1]) * (b[1] - a[1])) / L_ ** 2))
                    pos.append((s[i] + tt * L_, nm))
                    break
        pos.sort()
        first = (40.75 - WP["S1"][0], "S1 (J101 fold)") if lead == "W5" else (BEAD_LEN, "joint bead end")
        chain = [first] + [z for z in pos if z[0] > first[0] + 1e-6] + [(s[-1], "MB +y edge")]
        sp = [(chain[i][1], chain[i + 1][1], chain[i + 1][0] - chain[i][0]) for i in range(len(chain) - 1)]
        spans[lead] = sp
        last = sp[-1][2]
        out("    %-7s spans: %s; max %.1f mm %s; the last span runs on past the MB +y edge to the chassis tie: tie <= "
            "%.1f mm past the edge (along the lead) for <= 30 mm, <= %.1f mm with the %.0f mm margin"
            % (lead, "; ".join("%s -> %s %.1f" % z for z in sp), max(z[2] for z in sp),
               "<= 30 ok" if max(z[2] for z in sp) <= SPAN_MAX + 1e-6 else "EXCEEDS 30", SPAN_MAX - last,
               SPAN_MAX - CHASSIS_MARGIN - last, CHASSIS_MARGIN))
    grp_tie = {}
    for gname, members in (("west group (W1, W2, W6, W7)", WEST), ("W3/W4", ("W3", "W4")), ("W5", ("W5",))):
        lastg = max(spans[m][-1][2] for m in members)
        grp_tie[gname] = (lastg, SPAN_MAX - lastg, SPAN_MAX - CHASSIS_MARGIN - lastg)
    # west-group MB tie base nearer the edge: search along the west run (part-box clear, no non-GND via in the zone)
    a3 = {}
    for side, tol in ((6.0, TIE_TOL), (4.0, 1.0)):
        best = None
        for i_ in range(-60, 61):
            cx = X_EDGE_W + 0.05 * i_
            if abs(cx - X_EDGE_W) > side / 2 - 1.0:
                continue
            for j_ in range(0, 480):
                cy = WP["WN"][1] + 0.05 * j_
                z = (cx - side / 2 - tol, cy - side / 2 - tol, cx + side / 2 + tol, cy + side / 2 + tol)
                if z[3] > MB_OUTLINE[3]:
                    break
                dp = min((rect_dist(p["bbox"], z) if not rect_overlap(p["bbox"], z) else -1.0, p["name"]) for p in PARTS)
                if dp[0] < 0:
                    continue
                if any(v["net"] != "GND" and z[0] - VIA_PAD / 2 < v["x"] < z[2] + VIA_PAD / 2 and
                       z[1] - VIA_PAD / 2 < v["y"] < z[3] + VIA_PAD / 2 for v in VIAS):
                    continue
                if best is None or cy > best[1] + 1e-9:
                    best = (cx, cy, dp)
        a3[(side, tol)] = best
    out("    west-group MB tie base nearer the edge (revision 4 search along x %.2f +- (side/2 - 1 mm), zone = base + "
        "tolerance clear of every MB part box and every non-GND via): %s"
        % (X_EDGE_W, "; ".join(("%.0f x %.0f mm +- %.1f: %s" % (k[0], k[0], k[1], ("highest fit at (%.2f, %.2f), %.2f "
                                                                                 "mm from %s, %.2f mm below the MB "
                                                                                 "+y edge" % (v[0], v[1], v[2][0],
                                                                                              v[2][1], MB_OUTLINE[3] -
                                                                                              v[1])) if v else
                                                              "no position (C4C-FC, SNS-FC and the FC-CURR vias "
                                                              "(58.93, 83.57) / (60.71, 90.42) close the run)"))
                               for k, v in a3.items())))
    out("    chassis tie (revision 4; the last span from the last MB anchor runs past the MB +y edge to the chassis "
        "tie, so the tie position closes it; choice: no further MB tie base, because the A1-size base has no fit on "
        "the west run and the only fit is a 4 x 4 mm base +- 1.0 mm touching C4C-FC): %s. (**superseded in r7:** "
        "'the chassis tie is an extra anchor with no distance limit'; the r7 rev-2 tie at the MB +y edge 29.744 mm "
        "from the tab X top edge, margins 0.256 / 0.02 mm.)"
        % "; ".join("%s last span to the edge %.1f mm: tie <= %.1f mm past the edge (rule), <= %.1f mm with the %.0f mm "
                    "margin" % (g, v[0], v[1], v[2], CHASSIS_MARGIN) for g, v in grp_tie.items()))
    # ---- MB parts and untented non-GND vias under each lead (polyimide protection strip extents)
    out("  MB parts and untented non-GND vias under each lead off the CR (plan envelope; every MB via is untented, "
        "H.23(c2)); the polyimide strip covers their union + 2.0 mm:")
    cross = {}
    near_parts = [p for p in PARTS if rect_dist(p["bbox"], (30.0, 64.0, 80.0, 100.0)) < 6.0]
    near_vias = [v for v in VIAS if v["net"] != "GND" and 30.0 - 6 < v["x"] < 86.0 and 58.0 < v["y"] < 100.0]
    for lead, r in res.items():
        pts = [p for p, _ in r["path"]]
        hs = [h for _, h in r["path"]]
        sl = arclen(pts)
        s_mb = sl[pts.index(WP["A1R"])] if lead == "W5" else 0.0       # W5 is elevated on spacers until A1
        parts_x, vias_x = set(), set()
        for i in range(len(pts) - 1):
            a, b, h = pts[i], pts[i + 1], hs[i]
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.25))
            for k in range(n + 1):
                q = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                if sl[i] + (sl[i + 1] - sl[i]) * k / n < s_mb - 1e-9 or pip(q[0], q[1], OUTLINE):
                    continue                                       # on (or elevated above) the CR, not on the MB
                for p in near_parts:
                    if d_rect_pt(p["bbox"], q[0], q[1]) <= h:
                        parts_x.add(p["name"])
                for v in near_vias:
                    if math.hypot(v["x"] - q[0], v["y"] - q[1]) <= h + via_dia(v) / 2:
                        vias_x.add((v["net"], round(v["x"], 3), round(v["y"], 3)))
        cross[lead] = (sorted(parts_x), sorted(vias_x))
        out("    %-7s parts: %s; non-GND vias: %s" % (lead, ", ".join(sorted(parts_x)) or "none",
                                                      ", ".join("%s (%.2f, %.2f)" % v for v in sorted(vias_x)) or "none"))
    # revision 4: the vias under W5's elevated run off the CR (tab Y edge to A1), which W5 would cross if it touched down
    # before A1; listed and added to the strip when they lie inside it
    w5p = res["W5"]["path"]
    w5pts = [p for p, _ in w5p]
    w5s = arclen(w5pts)
    s_a1r = w5s[w5pts.index(WP["A1R"])]
    w5_desc = set()
    for i in range(len(w5pts) - 1):
        a, b, h = w5pts[i], w5pts[i + 1], w5p[i][1]
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.25))
        for k in range(n + 1):
            q = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            if w5s[i] + (w5s[i + 1] - w5s[i]) * k / n > s_a1r + 1e-9 or pip(q[0], q[1], OUTLINE):
                continue
            for v in near_vias:
                if math.hypot(v["x"] - q[0], v["y"] - q[1]) <= h + via_dia(v) / 2:
                    w5_desc.add((v["net"], round(v["x"], 3), round(v["y"], 3)))
    w5_desc = sorted(w5_desc)
    allp = sorted({p for v in cross.values() for p in v[0]})
    allv0 = sorted({x for v in cross.values() for x in v[1]})
    vr = VIA_PAD / 2
    bbs = [ELS[p]["bbox"] for p in allp if p in ELS] + [(v[1] - vr, v[2] - vr, v[1] + vr, v[2] + vr) for v in allv0]
    strip_ext = (min(b[0] for b in bbs) - 2.0, min(b[1] for b in bbs) - 2.0, max(b[2] for b in bbs) + 2.0,
                 min(max(b[3] for b in bbs) + 2.0, MB_OUTLINE[3])) if bbs else None
    strip_old_ymax = min(max([ELS[p]["bbox"][3] for p in allp if p in ELS] + [v[2] for v in allv0]) + 2.0,
                         MB_OUTLINE[3]) if bbs else None
    in_strip = [v for v in w5_desc if strip_ext and strip_ext[0] <= v[1] - vr and v[1] + vr <= strip_ext[2] and
                strip_ext[1] <= v[2] - vr and v[2] + vr <= strip_ext[3]]
    allv = sorted(set(allv0) | set(in_strip))
    if strip_ext:
        out("    W5 elevated run off the CR (tab Y edge to A1, at its fold height): non-GND vias under it %s; inside the "
            "strip extent: %s" % (", ".join("%s (%.2f, %.2f)" % v for v in w5_desc) or "none",
                                  ", ".join("%s (%.2f, %.2f)" % v for v in in_strip) or "none"))
        out("    polyimide strip: covers %s and %d non-GND vias (%d under the leads on the MB + %d more under the W5 elevated "
            "run only); extent of the crossed features + 2.0 mm, via pads at their %.4f mm diameter: x %.2f-%.2f, y %.2f-%.2f "
            "(laid along the lead path, not a full rectangle) (**superseded in r7:** y max %.2f with the via centres as "
            "points)" % (", ".join(allp), len(allv), len(allv0), len(allv) - len(allv0), VIA_PAD, strip_ext[0], strip_ext[2],
                         strip_ext[1], strip_ext[3], strip_old_ymax))
    # ---- routes, maxima, W1/W2 fixed length, W5 minimum fit, the USB channel
    out("")
    out("  %-7s %-30s %-20s %9s %9s %14s  %s" % ("lead", "terminal", "approach point", "CR+MB", "route",
                                                "build (mm)", "MB-edge crossing -> nodes -> terminal"))
    for lead, r in res.items():
        lab_b = ("fixed 300+-10" if lead in ("W1", "W2") else ("fixed 304.8" if lead == "W5" else
                                                               "max %d" % r["max"]))     # revision 4 labels
        out("  %-7s %-30s (%7.2f,%7.2f) %9.1f %9.1f %14s  (%.2f, %.3f) -> %s -> (%.2f, %.2f)"
            % (lead, r["term"][:30], r["app"][0], r["app"][1], r["Lmb"], r["L"], lab_b, r["P2"][0], r["P2"][1],
               " -> ".join("(%.2f, %.2f)" % n for n in r["nodes"][1:]) or "-", r["tpt"][0], r["tpt"][1]))
        out("          full path: %s" % " -> ".join("(%.2f, %.2f)" % n for n in [p for p, _ in r["path"]] +
                                                   list(r["nodes"][1:]) + [r["tpt"]]))
    for lead in ("W1", "W2"):
        L_ = res[lead]["L"]
        out("  %s fixed build length 0.30 m +- 10 mm (D-F3): route %.1f mm; slack %.1f mm at 300 mm (%.1f-%.1f mm over "
            "290-310 mm), dressed as an anchored service loop" % (lead, L_, 300 - L_, 290 - L_, 310 - L_))
    lw1 = res["W1"]["L"]
    hs_rows = []
    for lab, Lm in (("shortest W1 route (this path)", lw1), ("r7 rev-2 W1 route", 181.6),
                    ("0.30 m build, short limit 290 mm", W12_BUILD[0]), ("0.30 m build length", W12_BUILD[1])):
        worst = None
        for v0 in (16.0, 22.0):
            for cs in (5e-6, 20e-6):
                for lin in (50e-9, 150e-9):
                    vpk, ioff, ipk = in_spike(v0, cs, lin, 3.4e-6, lout=0.5e-6 * Lm / 1000.0)
                    if worst is None or vpk > worst[0]:
                        worst = (vpk, ioff, ipk, v0, cs, lin)
        hs_rows.append((lab, Lm, worst))
        out("  hard short at the EVM J1 end (round3 r3_calc.py H.19(b) in_spike, C_IN 3.4 uF, lead 0.5 uH/m x %.1f mm = "
            "%.0f nH; worst of V0 16/22 V, C_S 5/20 uF, L_IN 50/150 nH): %s -> IN peak %.1f V, %.0f A at turn-off, "
            "lead peak %.0f A (V0 %.0f V, C_S %.0f uF, L_IN %.0f nH); D107 VBR(min) 36 V margin %.1f V"
            % (Lm, 0.5 * Lm, lab, worst[0], worst[1], worst[2], worst[3], worst[4] * 1e6, worst[5] * 1e9,
               36.0 - worst[0]))
    out("  D-F3 reason: a W1/W2 cut to its route raises the IN-side spike to %.1f V (%.1f V below D107 VBR(min) 36 V); "
        "the fixed 0.30 m +- 10 mm build length keeps the r3-r6 H.5/H.19/T-C-04 basis (%.1f V at 300 mm, %.1f V at the "
        "290 mm short limit)." % (hs_rows[0][2][0], 36.0 - hs_rows[0][2][0], hs_rows[3][2][0], hs_rows[2][2][0]))
    w5 = res["W5"]
    out("  W5 fixed 0.30 m factory cable (12.00 in = 304.8 mm): plan route %.1f mm + %.0f mm 3-D allowance (J101 rise and "
        "fold, J201 drop; ASSUMPTION) = %.1f mm minimum fit -> slack %.1f mm, stowed as a service loop anchored on the "
        "EVM plate (D-F2); the route figure is a minimum-fit check for W5, not a build maximum"
        % (w5["L"], W5_ALLOW, w5["L"] + W5_ALLOW, 304.8 - w5["L"] - W5_ALLOW))
    ch = (evm[2], MB_OUTLINE[3], USB[0], USB[3])
    in_ch = {lead: any(seg_hits_rect(n1, n2, (ch[0] + 0.01, evm[1] + 0.01, ch[2] - 0.01, ch[3] - 0.01))
                       for n1, n2 in zip([r["P2"]] + r["nodes"][1:], r["nodes"][1:] + [r["app"]]))
             for lead, r in res.items() if lead in ("W3", "W4", "W5")}
    out("  USB channel x %.2f-%.2f (EVM right edge to the corridor; the corridor width is the receptacle silkscreen, the "
        "plug overmold width TODO(measure: MS2)), %.2f mm wide: W3 %s, W4 %s, W5 %s. W5 is routed around it over the "
        "EVM plate (W5 obstacle set: MB, corridor, channel; the EVM is not an obstacle for W5; clear of the EVM L2, "
        "TODO(verify: EVM L2 position, MS2)), so W3/W4 and W5 do not share the channel."
        % (ch[0], ch[2], ch[2] - ch[0], "uses it" if in_ch["W3"] else "clear", "uses it" if in_ch["W4"] else "clear",
           "uses it" if in_ch["W5"] else "clear"))
    EXTRA["l"] = W_EXTRA = dict(chk=chk, spans=spans, cross=cross, strip=strip_ext, tie_bases=tb_chk, hard_short=hs_rows,
                   bottleneck=(b_tr, b_1), in_channel=in_ch, old={k: (v["L"], v["max"]) for k, v in old.items()},
                   strip_vias=allv, w5_run_vias=w5_desc, grp_tie=grp_tie, a3=a3, sw3d=sw3d_res, spacers=spc)
    # J5 approach points
    for lead in ("W3", "W4"):
        a = res[lead]["app"]
        out("  %s J5 approach point (%.2f, %.2f) lies in the corridor x band, %.2f mm beyond the assumed corridor end "
            "y %.2f" % (lead, a[0], a[1], a[1] - USB[3], USB[3]))
    # pairs and resistance
    out("")
    pr = {"W1/W2 input pair (20 AWG)": ("W1", "W2", R20, (1.80,)), "W3/W4 battery pair (18 AWG)": ("W3", "W4", R18,
                                                                                                  (3.10, 3.21))}
    awg_chk = (2 * 0.30 * R20, 2 * 0.30 * R18)
    out("AWG table check against DOC H.11 at 0.30 m: input pair %.2f mOhm (H.11: 20 mOhm, 36 mV / 65 mW at 1.80 A -> "
        "%.1f mV / %.1f mW); battery pair %.2f mOhm (H.11: 12.6 mOhm, 39 mV / 121 mW at 3.10 A -> %.1f mV / %.1f mW)"
        % (awg_chk[0] * 1e3, 1.80 * awg_chk[0] * 1e3, 1.80 ** 2 * awg_chk[0] * 1e3, awg_chk[1] * 1e3,
           3.10 * awg_chk[1] * 1e3, 3.10 ** 2 * awg_chk[1] * 1e3))
    pres = {}
    for lab, (a, b, Rw, Is) in pr.items():
        if a == "W1":
            La, Lb = W12_BUILD[2] / 1000.0, W12_BUILD[2] / 1000.0      # fixed 0.30 m +- 10 mm: the long limit
            what = "fixed build 0.30 m +- 10 mm (310 mm each, D-F3)"
        else:
            La, Lb = res[a]["max"] / 1000.0, res[b]["max"] / 1000.0
            what = "build maxima %d / %d mm" % (res[a]["max"], res[b]["max"])
        Rmax = Rw * (La + Lb)
        R03 = Rw * 0.60
        pres[lab] = (La, Lb, Rmax, R03)
        out("  %-28s %s: pair %.2f mOhm (%s); at 0.30 m each: %.2f mOhm (%s)"
            % (lab, what, Rmax * 1e3,
               ", ".join("%.1f mV / %.1f mW at %.2f A" % (I * Rmax * 1e3, I * I * Rmax * 1e3, I) for I in Is),
               R03 * 1e3, ", ".join("%.1f mV / %.1f mW at %.2f A" % (I * R03 * 1e3, I * I * R03 * 1e3, I) for I in Is)))
    for lead in ("W6", "W7 SCL", "W7 SDA"):
        r = res[lead]
        out("  %-28s build max %d mm: %.1f mOhm per conductor (signal; 0.30 m: %.1f mOhm)"
            % (lead, r["max"], r["R"] * r["max"], r["R"] * 300))
    out("  Until MS2 confirms the placement, the r6 0.30 m caps stay the T-A-02 bound for W3/W4, W6 and W7 (BASIS D7); "
        "W1/W2 stay at 0.30 m +- 10 mm and W5 at the 0.30 m factory cable (D-F2, D-F3).")
    tie = MB_OUTLINE[3] - TAB_X[3]
    # ---- BASIS section 10 A4: fallbacks for an open-ended corridor -----------------------------------------------
    out("")
    out("USB corridor fallbacks (BASIS section 10 A4): open-ended corridor x %.2f-%.2f from y %.2f upward (no end). At "
        "the reference placement the EIB (x %.2f-%.2f) and the W3/W4 J5 approach points (x %.2f) lie inside that band."
        % (USB[0], USB[2], USB[1], eib[0], eib[2], res["W3"]["app"][0]))
    d7 = e_leads(EVM_W + 7.0, "D7")
    fb = {}

    def route_lines(rr):
        for lead, r in rr.items():
            if r["blocked"]:
                out("    %-7s BLOCKED: %s" % (lead, r["blocked"]))
            else:
                out("    %-7s route %6.1f mm, %s, MB-edge crossing x %.2f, CR+MB span %.1f mm, approach (%.2f, %.2f)"
                    % (lead, r["L"], ("W5 minimum fit %.1f mm, slack %.1f mm on the 304.8 mm cable"
                                      % (r["L"] + W5_ALLOW, 304.8 - r["L"] - W5_ALLOW)) if lead == "W5" else
                       (("fixed 0.30 m, slack %.1f mm" % (300 - r["L"])) if lead in ("W1", "W2") else
                        "build max %3d mm" % r["max"]), r["P2"][0], r["Lmb"], r["app"][0], r["app"][1]))
    # (i) whole EVM + EIB group shifted -x
    sh_i = max(eib[2], res["W3"]["app"][0], res["W4"]["app"][0]) - (USB[0] - 3.0)
    X0i = X0 - sh_i
    evm_i = (evm[0] - sh_i, evm[1], evm[2] - sh_i, evm[3])
    eib_i = (eib[0] - sh_i, eib[1], eib[2] - sh_i, eib[3])
    r_i = w_routes2(X0i, Y0, evm_i, eib_i, USB_OPEN)
    out("  (i) EVM + EIB group shifted -x by %.2f mm (the EIB rectangle and the W3/W4 J5 approach points >= 3.0 mm left "
        "of x %.2f): EVM x %.2f-%.2f (left edge %.2f, overhang past the MB -x edge x 0: %.2f mm; the leads reach "
        "further, see the chassis-room line); EIB x %.2f-%.2f; J5 approach points x %.2f; E-leads unchanged (EIB fixed "
        "to the EVM). W-lead routes on the designed dressing path (r7 review 7):"
        % (sh_i, USB[0], evm_i[0], evm_i[2], evm_i[0], -evm_i[0], eib_i[0], eib_i[2], r_i["W3"]["app"][0]))
    route_lines(r_i)
    ok_i = all(r["blocked"] is None for r in r_i.values())
    over300 = [k for k, r in r_i.items() if r["max"] is not None and r["max"] > 300 and k not in ("W1", "W2", "W5")]
    w5_fit = (r_i["W5"]["L"] + W5_ALLOW) <= 304.8 if r_i["W5"]["blocked"] is None else False
    # BASIS section 11 B5: chassis room past the MB -x edge = the most negative x of any approach point, route node or
    # terminal of the shifted group, plus a 20 AWG bend allowance (the lead turns into its 10 mm straight approach at
    # the approach point; a bend of radius R tangent to that approach reaches R + OD/2 beyond it)
    pts_i = [(lead, "approach point", r["app"]) for lead, r in r_i.items()] + \
            [(lead, "route node", tuple(n)) for lead, r in r_i.items() for n in (r["nodes"] or [])] + \
            [(lead, "terminal", r["tpt"]) for lead, r in r_i.items()] + [("EVM", "board edge", (evm_i[0], evm_i[1]))]
    xmin_i = min(pts_i, key=lambda z: z[2][0])
    room_i = -xmin_i[2][0] + BEND_ALLOW
    out("    chassis room past the MB -x edge (BASIS section 11 B5): the most negative x of any approach point, route "
        "node or terminal is %.2f (%s %s (%.2f, %.2f); EVM overhang %.2f mm); + 20 AWG bend allowance %.1f mm "
        "(ASSUMPTION: bend radius 6 x OD with OD %.1f mm (PVC hook-up wire) = %.1f mm, plus OD/2 = %.1f, rounded up "
        "to 0.5 mm; TODO(measure: MS2 wire OD)) -> %.1f mm of chassis room past x 0, clear of the J-BL/J-FC/J-NTC "
        "harness volume (MS2 measures both). The 'EVM rotated' variant is not evaluated (open item)."
        % (xmin_i[2][0], xmin_i[0], xmin_i[1], xmin_i[2][0], xmin_i[2][1], -evm_i[0], BEND_ALLOW, AWG20_OD,
           6 * AWG20_OD, 6.5 * AWG20_OD, room_i))
    v_i = ("PASSES geometrically: no lead blocked; build maxima %s; W1/W2 routes %.1f / %.1f mm against the fixed 0.30 m "
           "(slack %.1f / %.1f mm); %s; W5 minimum fit %.0f mm %s the 304.8 mm cable (slack %.0f mm); it needs %.1f mm "
           "of chassis room past the MB -x edge (%s %s at x %.2f + %.1f mm bend allowance; the EVM itself overhangs "
           "%.1f mm), clear of the J-BL/J-FC/J-NTC harnesses (MS2)"
           % (", ".join("%s %d" % (k, r["max"]) for k, r in r_i.items() if k not in ("W1", "W2", "W5")),
              r_i["W1"]["L"], r_i["W2"]["L"], 300 - r_i["W1"]["L"], 300 - r_i["W2"]["L"],
              ("maxima above the 0.30 m T-A-02 cap: %s" % over300) if over300 else "every W3/W4/W6/W7 maximum <= 0.30 m",
              r_i["W5"]["L"] + W5_ALLOW, "fits" if w5_fit else "EXCEEDS", 304.8 - r_i["W5"]["L"] - W5_ALLOW, room_i,
              xmin_i[0], xmin_i[1], xmin_i[2][0], BEND_ALLOW, -evm_i[0])) if ok_i else \
        "FAILS: %s" % "; ".join("%s %s" % (k, r["blocked"]) for k, r in r_i.items() if r["blocked"])
    out("    verdict (i): %s" % v_i)
    fb["i"] = dict(shift=f2(sh_i), evm=evm_i, eib=eib_i, overhang=f2(-evm_i[0]), xmin=(xmin_i[0], xmin_i[1],
                                                                                        xmin_i[2]),
                   bend_allowance=BEND_ALLOW, chassis_room=f2(room_i),
                   routes={k: dict(L=f2(r["L"]) if r["L"] == r["L"] else None, max=r["max"], x2=f2(r["P2"][0]),
                                   blocked=r["blocked"]) for k, r in r_i.items()},
                   passes=ok_i, verdict=v_i)
    # (ii) EIB moved to the corridor's +x side, EVM unchanged
    eib_ii = (USB[2] + 3.0, eib[1], USB[2] + 3.0 + EIB_W, eib[3])
    xcol_ii = eib_ii[0] + EIB_INSET
    e_ii = e_leads(xcol_ii - X0, "ii")
    out("  (ii) EIB moved to the corridor +x side: EIB x %.2f-%.2f (left edge = corridor edge %.2f + 3.0), pad column "
        "%.1f mm inside the EVM-facing edge at x %.2f (EVM frame %.2f); EVM unchanged at x %.2f-%.2f. E-leads (r6 "
        "rule: straight x 1.25 rounded up to 5 mm):" % (eib_ii[0], eib_ii[2], USB[2], EIB_INSET, xcol_ii,
                                                        xcol_ii - X0, evm[0], evm[2]))
    worst_crit = []
    for e in E_ROWS:
        s, mx = e_ii[e]
        crit = CRIT.get(e)
        if crit:
            worst_crit.append((mx / crit, e))
        out("    %-3s straight %5.1f mm, build max %3d mm (D7 %d, %+d)%s"
            % (e, s, mx, d7[e][1], mx - d7[e][1], "; criterion limit %.0f mm -> %.2f of it%s"
               % (crit, mx / crit, " (EXCEEDS the ~0.5 D7 design margin)" if mx / crit > 0.5 else "") if crit else ""))
    rz = e1_resonance(float(e_ii["E1"][1]))
    out("    E1 + E8 + C205 at the new E1 maximum %d mm: f0 %.3f MHz, Z0 %.3f Ohm, undamped Q %.1f (DC wire resistance; "
        "%.1f with the skin-effect Rac), %.3f with R276 (overdamped)" % (e_ii["E1"][1], rz["f0"] / 1e6, rz["Z0"], rz["Q"],
                                                                        rz["Q_ac"], rz["Q_R276"]))
    r_ii = w_routes2(X0, Y0, evm, eib_ii, USB_OPEN, leads=("W3", "W4", "W5"))
    out("    W3/W4/W5 routes with the open-ended corridor:")
    route_lines(r_ii)
    ys_e = (Y0 + EVM_PTS["TP33"][1] + 5.0 - 9 * 2.54, Y0 + EVM_PTS["TP33"][1] + 5.0 + 2 * 2.54)
    over_d7 = [e for e in E_ROWS if e_ii[e][1] > d7[e][1]]
    v_ii = ("FAILS: the E-lead bundle (EIB pad rows y %.2f-%.2f) and the shared EVM plate (one rigid body, D7/D8) must "
            "span the corridor band x %.2f-%.2f; %s; E-lead maxima above D7: %s; E4 at %.2f of its criterion limit"
            % (ys_e[0], ys_e[1], USB[0], USB[2],
               "; ".join("%s %s" % (k, r["blocked"]) for k, r in r_ii.items() if r["blocked"]) or "no W lead blocked",
               ", ".join("%s %d (D7 %d)" % (e, e_ii[e][1], d7[e][1]) for e in over_d7) or "none",
               e_ii["E4"][1] / CRIT["E4"]))
    out("    verdict (ii): %s" % v_ii)
    fb["ii"] = dict(eib=eib_ii, xcol_board=f2(xcol_ii), e_leads={e: (f2(v[0]), v[1]) for e, v in e_ii.items()},
                    e1=dict(max=e_ii["E1"][1], f0_MHz=f2(rz["f0"] / 1e6), Q=f2(rz["Q"]), Q_ac=f2(rz["Q_ac"]),
                            Q_R276=round(rz["Q_R276"], 4)),
                    routes={k: dict(L=f2(r["L"]) if r["L"] == r["L"] else None, max=r["max"], blocked=r["blocked"])
                            for k, r in r_ii.items()}, passes=False, verdict=v_ii)
    # (iii) EIB at the EVM left edge (mirror of the r6 rule)
    e_iii = e_leads(-7.0, "iii")
    eib_iii = (X0 - 7.0 + EIB_INSET - EIB_W, eib[1], X0 - 7.0 + EIB_INSET, eib[3])
    out("  (iii) EIB at the EVM left edge (mirror of the r6 rule: pad column 7 mm off the EVM left edge, EVM frame x "
        "-7.00, board x %.2f): EIB x %.2f-%.2f (overhang past the MB -x edge %.2f mm). E-leads:"
        % (X0 - 7.0, eib_iii[0], eib_iii[2], -eib_iii[0]))
    for e in E_ROWS:
        s, mx = e_iii[e]
        crit = CRIT.get(e)
        out("    %-3s straight %5.1f mm, build max %3d mm (D7 %d)%s"
            % (e, s, mx, d7[e][1], "; criterion limit %.0f mm: straight %s, build max %.2f of it"
               % (crit, "EXCEEDS it" if s > crit else "inside", mx / crit) if crit else ""))
    v_iii = ("FAILS: E4 (JP21 pin 1) straight %.1f mm exceeds its %.0f mm pickup criterion limit (build max %d mm); "
             "E8 %d / E3 %d mm also exceed D7" % (e_iii["E4"][0], CRIT["E4"], e_iii["E4"][1], e_iii["E8"][1],
                                                 e_iii["E3"][1])) if e_iii["E4"][0] > CRIT["E4"] else \
        ("PASSES the E4 criterion (straight %.1f mm, build max %d mm vs %.0f mm)" % (e_iii["E4"][0], e_iii["E4"][1],
                                                                                    CRIT["E4"]))
    out("    verdict (iii): %s" % v_iii)
    fb["iii"] = dict(eib=eib_iii, e_leads={e: (f2(v[0]), v[1]) for e, v in e_iii.items()},
                     passes=e_iii["E4"][0] <= CRIT["E4"], verdict=v_iii)
    first = next((k for k in ("i", "ii", "iii") if fb[k]["passes"]), None)
    out("  first passing fallback (BASIS A4: the design adopts the reference placement with the first passing "
        "fallback, decided by MS2): %s" % (first or "none"))
    RJ["l"] = dict(evm=evm, usb=USB, eib=eib, eib_overlaps_usb=ov, eib_choice=eib_choice, j201=j201,
                   fallbacks=fb, first_passing_fallback=first,
                   routes={k: dict(term=v["term"], L=f2(v["L"]),
                                   max=v["max"] if k not in ("W1", "W2", "W5") else None,
                                   build=("fixed 0.30 m +- 10 mm" if k in ("W1", "W2") else
                                          ("fixed 304.8 mm cable" if k == "W5" else "route maximum")),
                                   P2=v["P2"], nodes=v["nodes"],
                                   cr_mb_path=[(p, f2(h)) for p, h in v["path"]], cr_mb_len=f2(v["Lmb"]))
                           for k, v in res.items()},
                   dressing=dict(waypoints=WP, half_widths=dict(trunk=f2(H_TRUNK), west=f2(H_WEST), east=f2(H_EAST)),
                                 checks={k: dict(hazard=(f2(c["haz"][0]), c["haz"][1]),
                                                 in_bead=(f2(c["bead"][0]), c["bead"][1]),
                                                 field=f2(c["field"][0]), switched=(f2(c["sw"][0]), c["sw"][1]),
                                                 rework=(f2(c["rework"][0]), c["rework"][1]))
                                         for k, c in W_EXTRA["chk"].items()},
                                 bottleneck_switched=dict(trunk=f2(W_EXTRA["bottleneck"][0]) if W_EXTRA["bottleneck"][0]
                                                          is not None else None,
                                                          single=f2(W_EXTRA["bottleneck"][1]) if W_EXTRA["bottleneck"][1]
                                                          is not None else None),
                                 anchors=dict(cr=CR_ANCHORS, tie_bases={k: dict(centre=v[0], side=v[1], tol=TIE_TOL,
                                                                                zone=W_EXTRA["tie_bases"][k]["zone"],
                                                                                part=(f2(W_EXTRA["tie_bases"][k]["part"][0]),
                                                                                      W_EXTRA["tie_bases"][k]["part"][1]),
                                                                                vias=W_EXTRA["tie_bases"][k]["vias"],
                                                                                cu=W_EXTRA["tie_bases"][k]["cu"])
                                                                         for k, v in TIE_BASES.items()}),
                                 spans={k: [(a, b, f2(s)) for a, b, s in v] for k, v in W_EXTRA["spans"].items()},
                                 mb_crossings={k: dict(parts=v[0], vias=v[1]) for k, v in W_EXTRA["cross"].items()},
                                 polyimide_strip=W_EXTRA["strip"], usb_channel_use=W_EXTRA["in_channel"],
                                 superseded_routes={k: (f2(v[0]), v[1]) for k, v in W_EXTRA["old"].items()}),
                   hard_short=[dict(case=lab, lead_mm=f2(Lm), in_peak_V=f2(w[0]), i_turnoff_A=f2(w[1]),
                                    lead_peak_A=f2(w[2]), v0=w[3], cs_uF=f2(w[4] * 1e6), lin_nH=f2(w[5] * 1e9))
                               for lab, Lm, w in W_EXTRA["hard_short"]],
                   pairs={k: dict(La=v[0], Lb=v[1], R_max_mOhm=f2(v[2] * 1e3), R_030_mOhm=f2(v[3] * 1e3))
                          for k, v in pres.items()},
                   tie=tie, tie_note="superseded in r7 review 7 (D-F2): tab X top edge to the MB +y edge, kept for "
                                     "make_svgs_r7.py; the anchors are the CR beads and the MB tie bases A1/A2",
                   rev4=dict(spacers={k: dict(pos=v[0], checks={kk: (f2(vv) if isinstance(vv, float) else vv)
                                                                 for kk, vv in v[1].items()},
                                              old=v[2]) for k, v in spc.items()},
                             chassis_tie={g: dict(last_span=f2(v[0]), tie_max=f2(v[1]), tie_max_margin=f2(v[2]))
                                          for g, v in grp_tie.items()},
                             west_tie_base_search={"%gx%g+-%g" % (k[0], k[0], k[1]):
                                                   (None if v is None else dict(c=(f2(v[0]), f2(v[1])), part=v[2]))
                                                   for k, v in a3.items()},
                             sw3d={k: [dict(s=(f2(iv["s0"]), f2(iv["s1"])), p0=iv["p0"], p1=iv["p1"],
                                            need=f2(iv["need"]), who=iv["who"][0], d_plan=f2(iv["who"][1]),
                                            rise=f2(iv["rise"]), base=iv["base"],
                                            per={b: dict(p0=pb["p0"], p1=pb["p1"], need=f2(pb["need"]),
                                                         spacer=f2(pb["need"] - pb["zb"]), who=pb["who"][0],
                                                         d_plan=f2(pb["who"][1]), at=pb["at"])
                                                 for b, pb in iv["per"].items()}) for iv in v]
                                   for k, v in sw3d_res.items()},
                             heights=dict(H_LFC=H_LFC, H_REG=H_REG, H_POUR=H_POUR),
                             strip_vias=allv, w5_run_vias=w5_desc))
    summ("spacer beads S1/S2 (revision 4)", "; ".join("%s (%.2f, %.2f): J101 %.2f mm, W6/W7 exclusion %.2f mm, jacket "
                                                      "%.2f mm" % (k, v[0][0], v[0][1], v[1]["j101"], v[1]["w67"],
                                                                   v[1]["jacket"]) for k, v in spc.items()), "H.23(l)")
    summ("chassis tie past the MB +y edge (revision 4)", "; ".join("%s: last span %.1f mm, tie <= %.1f mm past the edge "
                                                                   "(<= %.1f mm with the 2 mm margin)"
                                                                   % (g, v[0], v[1], v[2]) for g, v in grp_tie.items()),
         "H.23(l)")
    summ("3-D switched-conductor heights (revision 4)", "; ".join(
        "%s %s" % (k, ", ".join(", ".join("%s: bottom >= %.2f mm above the MB (spacer %.2f mm; %s)"
                                          % (b, pb["need"], pb["need"] - pb["zb"], pb["who"][0])
                                          for b, pb in sorted(iv["per"].items(), key=lambda z: z[1]["s0"]))
                                for iv in v) or "none")
        for k, v in sw3d_res.items()), "H.23(l)")
    summ("EVM reference placement", "x %.2f-%.2f, y %.3f-%.3f (g %.0f mm, right edge %.2f); EVM-to-USB-corridor %.2f mm"
         % (evm[0], evm[2], evm[1], evm[3], G_J8, EVM_RIGHT, USB[0] - evm[2]), "H.23(l)")
    summ("EIB position (r6 rule)", "x %.2f-%.2f, y %.2f-%.2f; USB corridor (45 mm ASSUMPTION): %s, %.2f mm beyond its end"
         % (eib[0], eib[2], eib[1], eib[3], "overlap" if ov else "clear", gap_y), "H.23(l)")
    WX = W_EXTRA
    summ("W-lead routes on the dressing path (D-F2)", ", ".join("%s %.1f" % (k, v["L"]) for k, v in res.items()) +
         " mm; build maxima (route rule) %s; W1/W2 fixed 0.30 m +- 10 mm (D-F3); W5 fixed 304.8 mm cable"
         % ", ".join("%s %d" % (k, v["max"]) for k, v in res.items() if k not in ("W1", "W2", "W5")), "H.23(l)")
    summ("W1/W2 slack at 0.30 m (D-F3)", "W1 %.1f mm, W2 %.1f mm (routes %.1f / %.1f mm)"
         % (300 - res["W1"]["L"], 300 - res["W2"]["L"], res["W1"]["L"], res["W2"]["L"]), "H.23(l)")
    hsr = WX["hard_short"]
    summ("hard short vs W1 length (D-F3)", "; ".join("%s %.1f mm: %.1f V / %.0f A at turn-off / lead %.0f A"
                                                    % (lab, Lm, w[0], w[1], w[2]) for lab, Lm, w in hsr), "H.23(l)")
    summ("W5 cable fit (D-F2)", "route %.1f mm + %.0f mm 3-D allowance = %.1f mm minimum; slack %.1f mm on 304.8 mm; "
         "W3/W4 channel: W3 %s, W4 %s, W5 %s" % (res["W5"]["L"], W5_ALLOW, res["W5"]["L"] + W5_ALLOW,
                                               304.8 - res["W5"]["L"] - W5_ALLOW,
                                               "in" if WX["in_channel"]["W3"] else "out",
                                               "in" if WX["in_channel"]["W4"] else "out",
                                               "in" if WX["in_channel"]["W5"] else "out (over the EVM plate)"), "H.23(l)")
    summ("W dressing clearances (D-F2)", "hazards min %.2f mm (%s); switched conductors min %.2f mm (rule 10 mm "
         "NOT met on the CR; best achievable %.2f mm bundle / %.2f mm single lead); MB rework points min %.2f mm"
         % (min(c["haz"][0] for c in WX["chk"].values()),
            min(WX["chk"].items(), key=lambda kv: kv[1]["haz"][0])[0],
            min(c["sw"][0] for c in WX["chk"].values()),
            WX["bottleneck"][0] if WX["bottleneck"][0] is not None else float("nan"),
            WX["bottleneck"][1] if WX["bottleneck"][1] is not None else float("nan"),
            min(c["rework"][0] for c in WX["chk"].values())), "H.23(l)")
    summ("W anchors and spans (D-F2)", "CR beads %s; MB tie bases %s; max span %.1f mm (%s)"
         % (", ".join("%s (%.2f, %.2f)" % (k, v[0], v[1]) for k, v in CR_ANCHORS.items()),
            ", ".join("%s %.0f x %.0f mm at (%.2f, %.2f) +- %.1f" % (k, v[1], v[1], v[0][0], v[0][1], TIE_TOL)
                      for k, v in TIE_BASES.items()),
            max(s for v in WX["spans"].values() for _, _, s in v),
            max(((k, s) for k, v in WX["spans"].items() for _, _, s in v), key=lambda z: z[1])[0]), "H.23(l)")
    if WX["strip"]:
        summ("polyimide strip under the W leads (D-F2)", "x %.2f-%.2f, y %.2f-%.2f (crossed parts %s; %d non-GND vias)"
             % (WX["strip"][0], WX["strip"][2], WX["strip"][1], WX["strip"][3],
                ", ".join(sorted({p for v in WX["cross"].values() for p in v[0]})),
                len(WX["strip_vias"])), "H.23(l)")
    for lab, v in pres.items():
        summ("%s resistance" % lab, "%.2f mOhm at the %s vs %.2f mOhm at 0.30 m"
             % (v[2] * 1e3, "0.31 m long limit" if lab.startswith("W1") else "route maxima", v[3] * 1e3), "H.23(l)")
    summ("corridor fallback (i): group shifted -x", "shift %.2f mm, EVM x %.2f-%.2f (EVM overhang %.2f mm past the MB "
         "-x edge; chassis room needed %.1f mm); %s" % (sh_i, evm_i[0], evm_i[2], -evm_i[0], room_i, v_i), "H.23(l)")
    summ("corridor fallback (ii): EIB at x >= %.2f" % (USB[2] + 3.0), "E-lead maxima %s; E1 %d mm: f0 %.3f MHz, Q %.3f "
         "with R276; %s" % (", ".join("%s %d" % (e, v[1]) for e, v in e_ii.items()), e_ii["E1"][1], rz["f0"] / 1e6,
                            rz["Q_R276"], v_ii), "H.23(l)")
    summ("corridor fallback (iii): EIB at the EVM left edge", "E4 straight %.1f mm vs %.0f mm limit; %s"
         % (e_iii["E4"][0], CRIT["E4"], v_iii), "H.23(l)")


# ======================================================================================================================
# H.23(m) r6 sheet vs MB part bodies; r7 sheet outline with trims
# ======================================================================================================================
SHEET_R6 = (16.70, 33.14, 49.70, 68.14)            # DOC A.7 r5/r6: CR outline + 1 mm
SNAP = 1.0                                         # mm: a sheet sliver shorter than this beside a notch is cut away
CUT_TOL = 0.2                                      # mm, hand-cut tolerance of a trimmed edge (information, D-F7)
CUTOUT_PARTS = ("D-BT-SQ", "C-D11", "C-D12", "C-DC11", "C-DC12")   # DOC A.7 five cut-outs


def offset_outline(poly, d):
    n = len(poly)
    lines = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        nx, ny = dy / L, -dx / L               # outward normal for a CCW polygon
        lines.append(((a[0] + nx * d, a[1] + ny * d), (dx, dy)))
    out_pts = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        out_pts.append((p1[0] + t * d1[0], p1[1] + t * d1[1]))
    return out_pts


def insert_notch(poly, trim):
    """Notch an axis-aligned sheet edge so that the sheet keeps out of the trim rectangle (body + 0.5 mm)."""
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if abs(a[0] - b[0]) < 1e-9:            # vertical edge
            x = a[0]
            if not (trim[0] < x < trim[2]):
                continue
            ylo, yhi = min(a[1], b[1]), max(a[1], b[1])
            y0, y1 = max(trim[1], ylo), min(trim[3], yhi)
            if y0 >= y1:
                continue
            xin = trim[0] if pip(x - 1e-3, (y0 + y1) / 2, poly) else trim[2]
            # r7 review 7: a sliver shorter than SNAP between the notch and the edge end joins the notch (no sliver)
            end_b = (yhi - y1 < SNAP) if a[1] < b[1] else (y0 - ylo < SNAP)
            if a[1] < b[1]:
                new = [(x, y0), (xin, y0)] + ([] if end_b else [(xin, y1), (x, y1)])
            else:
                new = [(x, y1), (xin, y1)] + ([] if end_b else [(xin, y0), (x, y0)])
            p2 = list(poly)
            if end_b:
                j = (i + 1) % n
                p2[j] = (xin, p2[j][1])
            lo = ylo if (end_b and a[1] > b[1]) else y0
            hi = yhi if (end_b and a[1] < b[1]) else y1
            return p2[:i + 1] + new + p2[i + 1:], (i, "vertical x %.3f -> %.3f over y %.3f-%.3f%s"
                                                     % (x, xin, lo, hi, " (carried to the sheet corner)" if end_b
                                                        else ""))
        if abs(a[1] - b[1]) < 1e-9:            # horizontal edge
            y = a[1]
            if not (trim[1] < y < trim[3]):
                continue
            xlo, xhi = min(a[0], b[0]), max(a[0], b[0])
            x0, x1 = max(trim[0], xlo), min(trim[2], xhi)
            if x0 >= x1:
                continue
            yin = trim[1] if pip((x0 + x1) / 2, y - 1e-3, poly) else trim[3]
            if a[0] < b[0]:
                new = [(x0, y), (x0, yin), (x1, yin), (x1, y)]
            else:
                new = [(x1, y), (x1, yin), (x0, yin), (x0, y)]
            return poly[:i + 1] + new + poly[i + 1:], (i, "horizontal y %.3f -> %.3f over x %.3f-%.3f" % (y, yin, x0, x1))
    return poly, None


def sec_m():
    head("H.23(m) polyimide sheet: the r6 sheet against MB part bodies; the r7 sheet outline with trims")
    out("Part body = layers 21 + 51 straight wires and rectangles of the package (pin-1 arcs, circles and polygons "
        "excluded); L-FC also as the Eaton 12.9 mm body centred on its origin (ASSUMPTION). Rule (BASIS D4; r7 review 7 "
        "D-F7): the sheet keeps >= 0.5 mm from every MB part body and every MB copper pad (smd dx x dy rotated, "
        "through-hole pad diameter), so a trim notch = (body joined with its pads) + 0.5 mm, and a sheet sliver shorter "
        "than %.1f mm beside a notch is cut away with it; the five r6 cut-outs %s stay." % (SNAP, CUTOUT_PARTS))
    bodies = {n: body_box(n) for n in ELS if n != "CHG"}
    bodies["L-FC (Eaton 12.9 mm)"] = LFC_EATON
    # r6 sheet
    out("")
    out("r6 sheet x %.2f-%.2f, y %.2f-%.2f (DOC A.7):" % (SHEET_R6[0], SHEET_R6[2], SHEET_R6[1], SHEET_R6[3]))
    r6rows = []
    for n, b in sorted(bodies.items()):
        if n in CUTOUT_PARTS:
            continue
        ovl = rect_overlap(b, SHEET_R6)
        d = rect_dist(b, SHEET_R6)
        if ovl or d < 1.0:
            depth = (min(b[2], SHEET_R6[2]) - max(b[0], SHEET_R6[0]), min(b[3], SHEET_R6[3]) - max(b[1], SHEET_R6[1]))
            r6rows.append((n, b, ovl, d, depth))
            out("  %-22s body (%.3f,%.3f)-(%.3f,%.3f): %s" % (n, b[0], b[1], b[2], b[3],
                                                             "OVERLAP %.3f x %.3f mm (%.2f mm2)" % (depth[0], depth[1],
                                                                                                     depth[0] * depth[1])
                                                             if ovl else "clearance %.3f mm%s" % (d, " (< 0.5)" if d < 0.5
                                                                                                    else "")))
    co = [r for r in r6rows if r[0] == "CO-5V"]
    # r7 sheet
    base = offset_outline(OUTLINE, 1.0)
    out("")
    out("r7 sheet before trims = r7 outline + 1 mm (mitred offset), vertices: %s"
        % ", ".join("(%.3f, %.3f)" % p for p in base))
    poly = list(base)
    trims = []
    # r7 review 7 (D-F7): the trim obstacle of a part = its body box joined with its copper pad boxes
    pads = {n: pad_rects(n) for n in bodies if n in ELEM_XML}
    obst = {}
    for n, b in bodies.items():
        pr = pads.get(n, [])
        obst[n] = mbn.bbox([(b[0], b[1]), (b[2], b[3])] + [(r[0], r[1]) for _, r in pr] + [(r[2], r[3]) for _, r in pr])
    for n, b in sorted(bodies.items()):
        if n in CUTOUT_PARTS or n == "L-FC":
            continue
        ob = obst[n]
        d = clearance(dict(kind="box", pts=rpoly(ob), closed=True, r=0.0), poly)
        if d < 0.5:
            db = clearance(dict(kind="box", pts=rpoly(b), closed=True, r=0.0), poly)
            dp = min([clearance(dict(kind="box", pts=rpoly(r), closed=True, r=0.0), poly) for _, r in pads.get(n, [])]
                     or [float("inf")])
            tr = (ob[0] - 0.5, ob[1] - 0.5, ob[2] + 0.5, ob[3] + 0.5)
            poly2, info = insert_notch(poly, tr)
            trims.append((n, ob, d, info, db, dp))
            poly = poly2
    for n, b, d, info, db, dp in trims:
        out("  trim for %-22s body + pads (%.3f,%.3f)-(%.3f,%.3f), clearance before %+.3f mm (body %+.3f, pads %s): %s"
            % (n, b[0], b[1], b[2], b[3], d, db, ("%+.3f" % dp) if dp != float("inf") else "-",
               info[1] if info else "NOT a single-edge notch (handle by hand)"))
    # verify: every part body and every MB pad (layer-1 smd or through-hole pad) >= 0.5 mm from the sheet
    bad = []
    pad_min = (1e9, None)
    for n, b in bodies.items():
        if n in CUTOUT_PARTS or n == "L-FC":
            continue
        d = clearance(dict(kind="box", pts=rpoly(b), closed=True, r=0.0), poly)
        if d < 0.5 - 1e-6:
            bad.append((n, round(d, 3)))
        for pn, r in pads.get(n, []):
            dpp = clearance(dict(kind="box", pts=rpoly(r), closed=True, r=0.0), poly)
            if dpp < pad_min[0]:
                pad_min = (dpp, "%s pad %s" % (n, pn))
            if dpp < 0.5 - 1e-6:
                bad.append(("%s pad %s" % (n, pn), round(dpp, 3)))
    inside_cr = [p for p in poly if pip(p[0], p[1], OUTLINE) and min(dpt_seg(p[0], p[1], a[0], a[1], c[0], c[1])
                                                                     for a, c in edges(OUTLINE)) > 1e-6]
    out("r7 sheet after trims: %d vertices: %s" % (len(poly), ", ".join("(%.3f, %.3f)" % p for p in poly)))
    out("  check: part bodies and MB pads within 0.5 mm after the trims: %s; nearest MB pad %.3f mm (%s; %.3f mm after a "
        "+-%.1f mm hand-cut tolerance, information); trimmed vertices inside the CR outline: %s; area %.1f mm2; bbox %s"
        % (bad or "none", pad_min[0], pad_min[1], pad_min[0] - CUT_TOL, CUT_TOL, inside_cr or "none", area_poly(poly),
           [round(v, 3) for v in mbn.bbox(poly)]))
    co_pad = []
    for n in CUTOUT_PARTS:
        cb = (bodies[n][0] - 0.5, bodies[n][1] - 0.5, bodies[n][2] + 0.5, bodies[n][3] + 0.5)
        dmin = min(min(r[0] - cb[0], r[1] - cb[1], cb[2] - r[2], cb[3] - r[3]) for _, r in pads.get(n, []))             if pads.get(n) else float("nan")
        co_pad.append((n, dmin))
    out("  cut-outs (body + 0.5 mm) against their own pads (smallest pad-edge to cut-out-edge margin; information, the "
        "cut-out rule is unchanged): %s" % ", ".join("%s %.3f mm" % z for z in co_pad))
    # ---- revision 4: relief holes enlarged to clear the 1.650 mm square pad corners by >= 0.5 mm; enlarged cut-outs
    sq_pad = 1.650
    d_req = sq_pad * math.sqrt(2) + 2 * 0.5
    d_new = math.ceil(d_req * 10 - 1e-9) / 10.0
    rh = d_new / 2
    corner = rh - sq_pad * math.sqrt(2) / 2
    flats = rh - sq_pad / 2
    cols = {}
    for (x, y) in PINS:
        cols.setdefault(round(x, 3), []).append(y)
    web = min(min(abs(b - a) for a, b in zip(sorted(v)[:-1], sorted(v)[1:])) for v in cols.values()) - d_new
    slots = {x: (x - rh, min(v) - rh, x + rh, max(v) + rh) for x, v in cols.items()}
    edge_d = min((min(dpt_seg(x, y, a[0], a[1], c[0], c[1]) for a, c in edges(poly)) - rh, (x, y)) for (x, y) in PINS)
    inside = all(pip(x, y, poly) for (x, y) in PINS)
    co_rect = {n: (bodies[n][0] - 0.5, bodies[n][1] - 0.5, bodies[n][2] + 0.5, bodies[n][3] + 0.5) for n in CUTOUT_PARTS}
    co_d = min((d_rect_pt(r, x, y) - rh, n, (x, y)) for n, r in co_rect.items() for (x, y) in PINS)
    co_d22 = min((d_rect_pt(r, x, y) - 1.1, n, (x, y)) for n, r in co_rect.items() for (x, y) in PINS)
    body_w = 2.54
    out("  relief holes against the MB CHG pads (revision 4): a hole that clears the %.3f mm square pad corners by >= 0.5 "
        "mm needs a diameter >= %.3f mm; chosen %.1f mm: it clears the pad corners by %.3f mm and the flats by %.3f mm "
        "(the 2.2 mm holes: flats 0.275 mm, corners covered by up to 0.067 mm). At the %.2f mm pitch the web between "
        "neighbouring holes is %.2f mm, so the holes of each column MERGE into one slot: %s. Each slot is %.2f mm wide, "
        "wider than the %.2f mm header body, so the header bodies lose their seat on the sheet and stand %.3f mm lower "
        "(on the MB mask), while FT1/FT2 stand on the sheet: the nominal t_bed falls from 0.300 to %.3f mm (PM4 (2d) "
        "gate 0.15-0.45 mm). Sheet edge: nearest hole edge %.2f mm from the sheet outline (hole at (%.3f, %.3f)); all "
        "hole centres inside the sheet: %s. Cut-outs: nearest %.2f mm (%s, hole (%.3f, %.3f)); with the 2.2 mm holes "
        "%.2f mm. A square opening that clears the pad by 0.5 mm (%.2f mm) merges as well (%.2f mm > %.2f mm pitch)."
        % (sq_pad, d_req, d_new, corner, flats, PITCH, web, "; ".join("x %.3f: x %.2f-%.2f, y %.2f-%.2f" %
                                                                      (x, s[0], s[2], s[1], s[3])
                                                                      for x, s in slots.items()),
           d_new, body_w, 0.125, 0.300 - 0.125, edge_d[0], edge_d[1][0], edge_d[1][1], "yes" if inside else "NO",
           co_d[0], co_d[1], co_d[2][0], co_d[2][1], co_d22[0], sq_pad + 1.0, sq_pad + 1.0, PITCH))
    co_big = {}
    for n in CUTOUT_PARTS:
        pr = pads.get(n, [])
        ob = obst[n]
        co_big[n] = (ob[0] - 0.5, ob[1] - 0.5, ob[2] + 0.5, ob[3] + 0.5)
    merges = [(a, b) for i, a in enumerate(CUTOUT_PARTS) for b in CUTOUT_PARTS[i + 1:] if rect_overlap(co_big[a], co_big[b])]
    big_rows = []
    for n, r in co_big.items():
        grow = max(co_rect[n][0] - r[0], co_rect[n][1] - r[1], r[2] - co_rect[n][2], r[3] - co_rect[n][3])
        own = min(min(q[0] - r[0], q[1] - r[1], r[2] - q[2], r[3] - q[3]) for _, q in pads.get(n, [])) \
            if pads.get(n) else float("nan")
        dh = min(d_rect_pt(r, x, y) for (x, y) in PINS)
        de = min(min(dpt_seg(c_[0], c_[1], a[0], a[1], b[0], b[1]) for a, b in edges(poly)) for c_ in rpoly(r))
        others_ = [(nm, round(d, 3)) for nm, b in bodies.items() if nm not in CUTOUT_PARTS and nm != "L-FC"
                   for d in [rect_dist(b, r)] if d < 0.5]
        big_rows.append((n, r, grow, own, dh - 1.1, dh - rh, de, others_))
    out("  enlarged cut-outs (revision 4 proposal: (part body joined with its own pads) + 0.5 mm, so each clears its own "
        "pads by >= 0.5 mm):")
    for n, r, grow, own, dh22, dh34, de, oth in big_rows:
        out("    %-8s x %.3f-%.3f, y %.3f-%.3f (grows by up to %.3f mm over body + 0.5): own pads %.3f mm; nearest "
            "relief hole edge %.2f mm (2.2 mm hole) / %.2f mm (%.1f mm hole); sheet outline %.2f mm from its nearest "
            "corner; "
            "other MB bodies within 0.5 mm: %s" % (n, r[0], r[2], r[1], r[3], grow, own, dh22, dh34, d_new, de,
                                                   oth or "none"))
    out("    enlarged cut-outs that overlap and form one opening: %s" % (", ".join("%s + %s" % z for z in merges) or "none"))
    m_rev4 = dict(relief=dict(d_req=f2(d_req), d_new=d_new, corner=f2(corner), flats=f2(flats), web=f2(web),
                               slots={str(k): v for k, v in slots.items()}, edge=f2(edge_d[0]), cutout=f2(co_d[0]),
                               t_bed_nominal_after=f2(0.300 - 0.125)),
                   cutouts_enlarged={n: dict(rect=[f2(v) for v in r], grow=f2(g), own=f2(o), hole22=f2(a),
                                             hole_new=f2(b), others=ot)
                                     for n, r, g, o, a, b, _, ot in big_rows}, cutout_merges=merges)
    summ("relief holes (revision 4)", "%.1f mm holes clear the pad corners by %.3f mm but MERGE at the 2.54 mm pitch "
         "(web %.2f mm): one %.2f mm slot per column, the header bodies lose the sheet seat and t_bed falls to %.3f mm"
         % (d_new, corner, web, d_new, 0.300 - 0.125), "H.23(m)")
    summ("enlarged cut-outs (revision 4)", "; ".join("%s grows %.3f mm, own pads %.3f mm" % (n, g, o)
                                                     for n, _, g, o, _, _, _, _ in big_rows) +
         "; merges: %s" % (", ".join("%s + %s" % z for z in merges) or "none"), "H.23(m)")
    out("  relief holes (DOC A.7, unchanged): 2.2 mm diameter at the 22 header pads (DOC A.8 table); cut-outs (body + "
        "0.5 mm, unchanged): %s" % ({n: [round(v, 3) for v in (bodies[n][0] - 0.5, bodies[n][1] - 0.5,
                                                                  bodies[n][2] + 0.5, bodies[n][3] + 0.5)]
                                         for n in CUTOUT_PARTS}))
    out("  r6 sheet 33.0 x 35.0 mm; r7 sheet bbox %.2f x %.2f mm (BOM: check the sheet stock size)"
        % (mbn.bbox(poly)[2] - mbn.bbox(poly)[0], mbn.bbox(poly)[3] - mbn.bbox(poly)[1]))
    RJ["m"] = dict(r6_rows=[(r[0], r[1], r[2], f2(r[3]), [f2(v) for v in r[4]]) for r in r6rows],
                   r7_base=base, r7_sheet=poly, trims=[(n, b, f2(d), info[1] if info else None)
                                                         for n, b, d, info, _, _ in trims], residual=bad,
                   nearest_pad=(f2(pad_min[0]), pad_min[1]), cutout_own_pads=co_pad,
                   area=f2(area_poly(poly)), bbox=[f2(v) for v in mbn.bbox(poly)])
    RJ["m"].update(m_rev4)
    if co:
        r = co[0]
        summ("r6 sheet vs CO-5V body", "OVERLAP %.3f mm in x over %.3f mm (%.2f mm2): the r6 sheet drapes onto the 2.1 mm "
             "tantalum" % (r[4][0], r[4][1], r[4][0] * r[4][1]) if r[2] else "clearance %.3f mm" % r[3], "H.23(m)")
    summ("r7 sheet trims (bodies + pads, D-F7)", "; ".join("%s: %s" % (n, info[1] if info else "-")
                                                          for n, b, d, info, _, _ in trims) +
         "; nearest MB pad %.3f mm (%s)" % pad_min, "H.23(m)")
    summ("r7 sheet", "%d vertices, area %.1f mm2, bbox %.2f x %.2f mm" % (len(poly), area_poly(poly),
                                                                       mbn.bbox(poly)[2] - mbn.bbox(poly)[0],
                                                                       mbn.bbox(poly)[3] - mbn.bbox(poly)[1]), "H.23(m)")


# ======================================================================================================================
# Revision 5 (r8 of the design; charger-design audit run 001, docs/reviews/charger-design/run-001-2026-11-10.md and
# ledger.md): H.23(n)-(w). The sections above are unchanged; these sections compute the numbers of the r8 fixes.
# ======================================================================================================================
# H.23(n) R106s FLT series resistor (CHG-R1-01, A-01)
R106S = (990.0, 1000.0, 1010.0)       # ohm, r8 R106s 1.00 kOhm 1 % between U101 FLT (pin 14) and the F17 pad (agreed fix)
V_IO_RNG = (3.135, 3.30, 3.465)       # V, Teensy 3V3 +-5 % ASSUMPTION; TODO(verify: PJRC Teensy 4.1 schematic, 3.3 V
#                                       regulator tolerance)
R_FLT = (36.0, 70.0, 130.0)           # ohm, tps2663.pdf (SLVSE94G) sec 6.5 R(FLT) "FLT pull-down resistance" min/typ/max
I_FLT_ABS = 10e-3                     # A, tps2663.pdf sec 6.1: IFLT sink current absolute maximum
I_FLT_LEAK = 150e-9                   # A, tps2663.pdf sec 6.5 I(FLT) input leakage maximum
R_PU35 = (11e3, 22e3, 33e3)           # ohm, Teensy pin-35 INPUT_PULLUP (i.MX RT1062 PUS 22 kOhm) +-50 % ASSUMPTION;
#                                       TODO(verify: IMXRT1060CEC pad pull-up range; PJRC core pinMode())
VIL_FRAC = 0.30                       # x OVDD, i.MX RT1062 GPIO VIL ASSUMPTION; TODO(verify: IMXRT1060CEC)
R127_R = (990.0, 1000.0, 1010.0)      # ohm, DOC B.4 R127 1 kOhm 1 % (pin 16 H2C readback series resistor)
T_CLPLIM = (129e-3, 162e-3, 202e-3)   # s, tps2663.pdf sec 6.6 tCL_PLIM(dly) maximum duration in current limiting
T_CLPLIM_FLT = (1.09e-3, 1.3e-3, 1.6e-3)   # s, tps2663.pdf sec 6.6 tCL_PLIM_FLT(dly)
FLT_DIAG_DWELL = 250e-3               # s, DOC FR-23 r4 dwell (> tCL_PLIM), kept for the r8 FLT-LOW diagnostic read


def sec_n():
    head("H.23(n) R106s FLT series resistor (r8, CHG-R1-01): bridge current bound with tolerances, EN level, FLT "
         "readback level; FR-23 FLT-LOW diagnostic dwell")
    out("Inputs: R106s %.2f kOhm 1 %% (%.0f-%.0f ohm); Teensy 3V3 %.3f-%.3f V (ASSUMPTION +-5 %%, TODO(verify: PJRC "
        "Teensy 4.1 schematic)); U101 FLT pull-down resistance R(FLT) %.0f/%.0f/%.0f ohm min/typ/max (tps2663.pdf "
        "SLVSE94G sec 6.5; the FLT output is specified as a resistance, so V_OL = I x R(FLT)); FLT sink current %.0f mA "
        "absolute maximum (tps2663.pdf sec 6.1); FLT leakage <= %.0f nA (sec 6.5); i.MX output driver resistance 0 ohm "
        "(current bound) or %.0f ohm (H.23(g) ASSUMPTION, level estimate); pin-35 pull-up %.0f-%.0f kOhm (ASSUMPTION, "
        "TODO(verify: IMXRT1060CEC)); VIL %.2f x 3V3 (ASSUMPTION); RT1987 EN thresholds VEN_R max %.1f V, VEN_F min "
        "%.1f V (RT1987_DS-00.pdf EC table)."
        % (R106S[1] / 1e3, R106S[0], R106S[2], V_IO_RNG[0], V_IO_RNG[2], R_FLT[0], R_FLT[1], R_FLT[2], I_FLT_ABS * 1e3,
           I_FLT_LEAK * 1e9, R_DRV, R_PU35[0] / 1e3, R_PU35[2] / 1e3, VIL_FRAC, VEN_R_MAX, VEN_F_MIN))
    # r7 (no series resistor): the bridge F05-F17 / F06-F17 with the EN output HIGH and FLT asserted
    i_r7_max = V_IO_RNG[2] / (0.0 + R_FLT[0])
    i_r7_40 = (V_IO_RNG[0] / (R_DRV + R_FLT[2]), V_IO_RNG[2] / (R_DRV + R_FLT[0]))
    v_en_r7 = (V_IO_RNG[0] * R_FLT[0] / (R_DRV + R_FLT[0]), V_IO_RNG[2] * R_FLT[2] / (R_DRV + R_FLT[2]))
    r_flt_off = VEN_F_MIN * R_DRV / (V_IO_RNG[1] - VEN_F_MIN)
    out("  r7 (no series resistor), bridge F05-F17 or F06-F17, EN output HIGH, FLT asserted: FLT current %.1f-%.1f mA "
        "with the %.0f ohm driver (up to %.1f mA with a 0 ohm driver) against the %.0f mA absolute maximum; the EN net "
        "sits at %.2f-%.2f V (driver/R(FLT) divider; the 10 kOhm EN bodge resistor is negligible), above VEN_R max %.1f V, "
        "so the switch stays as commanded; EN falls below VEN_F min %.1f V only for R(FLT) < %.1f ohm (>= %.1f mA). The "
        "r7 statement 'pulls the EN net only toward off' is not supported."
        % (i_r7_40[0] * 1e3, i_r7_40[1] * 1e3, R_DRV, i_r7_max * 1e3, I_FLT_ABS * 1e3, v_en_r7[0], v_en_r7[1], VEN_R_MAX,
           VEN_F_MIN, r_flt_off, V_IO_RNG[1] / (R_DRV + r_flt_off) * 1e3))
    # r8 with R106s
    i_max = V_IO_RNG[2] / (0.0 + R106S[0] + R_FLT[0])
    i_min = V_IO_RNG[0] / (R_DRV + R106S[2] + R_FLT[2])
    v_flt_pin = max(V_IO_RNG[2] * rf / (rd + R106S[0] + rf) for rf in R_FLT for rd in (0.0, R_DRV))
    v_en_min = min(v - v / (R_DRV + r + rf) * R_DRV for v in V_IO_RNG for r in R106S for rf in R_FLT)
    p_r = i_max ** 2 * R106S[2]
    out("  r8 (R106s between U101 FLT and the F17 pad), same bridge, EN output HIGH, FLT asserted: FLT current %.3f mA "
        "maximum (3V3 %.3f V, driver 0 ohm, R106s %.0f ohm, R(FLT) %.0f ohm) = %.3f of the %.0f mA absolute maximum "
        "(factor %.2f below it); %.3f mA minimum (3V3 %.3f V, driver %.0f ohm, R106s %.0f ohm, R(FLT) %.0f ohm). The "
        "FLT pin rises to <= %.3f V (I x R(FLT)). The EN net stays >= %.3f V (%.0f ohm driver), above VEN_R max %.1f V: "
        "the switch follows its command and pin 35 reads the EN level (HIGH), so an eFuse fault is masked while that EN "
        "output is HIGH. R106s dissipates <= %.1f mW."
        % (i_max * 1e3, V_IO_RNG[2], R106S[0], R_FLT[0], i_max / I_FLT_ABS, I_FLT_ABS * 1e3, I_FLT_ABS / i_max,
           i_min * 1e3, V_IO_RNG[0], R_DRV, R106S[2], R_FLT[2], v_flt_pin, v_en_min, R_DRV, VEN_R_MAX, p_r * 1e3))
    out("  same bridge, EN output LOW: FLT released -> pin 35 reads LOW ('fault') through the bridge (FR-08 sees an EN "
        "LOW with FLT 'fault'), FLT pin at 0 V through R106s with <= %.0f nA leakage; FLT asserted -> no current. The "
        "bridge therefore shows as FLT = EN level on every Idle/Run edge (T-F-12 tap-to-tap DMM before power-up stays "
        "the primary detector)." % (I_FLT_LEAK * 1e9))
    i_h2c_r7 = V_IO_RNG[2] / (R127_R[0] + R_FLT[0])
    i_h2c = V_IO_RNG[2] / (R127_R[0] + R106S[0] + R_FLT[0])
    out("  bridge F17-F15 (pin 16 H2C readback through R127 1 kOhm, U108 output resistance 0 ohm ASSUMPTION), FLT "
        "asserted, U108 HIGH: FLT current <= %.3f mA (r7 without R106s: %.3f mA, the A.8 '<= 3.3 mA')."
        % (i_h2c * 1e3, i_h2c_r7 * 1e3))
    # normal readback level
    rb_max = V_IO_RNG[2] * (R106S[2] + R_FLT[2]) / (R_PU35[0] + R106S[2] + R_FLT[2])
    rb_typ = V_IO_RNG[1] * (R106S[1] + R_FLT[1]) / (R_PU35[1] + R106S[1] + R_FLT[1])
    rb_r7 = V_IO_RNG[2] * R_FLT[2] / (R_PU35[0] + R_FLT[2])
    vil = VIL_FRAC * V_IO_RNG[0]
    i_pu = V_IO_RNG[2] / (R_PU35[0] + R106S[0] + R_FLT[0])
    v_hi = V_IO_RNG[0] - I_FLT_LEAK * R_PU35[2]
    out("  FLT readback with no bridge: FLT asserted -> pin 35 LOW level = V_OL + pull-up drop = 3V3 x (R(FLT) + R106s) / "
        "(R_pu + R(FLT) + R106s): %.3f V typical (22 kOhm, 70 ohm, 1.00 kOhm), %.3f V maximum (%.0f kOhm, %.0f ohm, %.0f "
        "ohm, %.3f V) against VIL %.3f V (%.2f x %.3f V): margin %.3f V (r7 without R106s: <= %.3f V). FLT sinks <= %.3f "
        "mA of pull-up current. FLT released -> pin 35 >= %.3f V (leakage x the 33 kOhm pull-up)."
        % (rb_typ, rb_max, R_PU35[0] / 1e3, R_FLT[2], R106S[2], V_IO_RNG[2], vil, VIL_FRAC, V_IO_RNG[0], vil - rb_max,
           rb_r7, i_pu * 1e3, v_hi))
    out("  FR-23 FLT-LOW diagnostic read (r8, A-01): one REG1B read when FLT reads LOW and V_chg > 10.2 V for > %.0f ms; "
        "the dwell exceeds the tCL_PLIM current-limit maximum %.0f ms (tps2663.pdf sec 6.6; margin %.0f ms), so an "
        "eFuse still current-limiting has latched off and the charger is unpowered: NACK expected. FLT asserts %.2f-%.2f "
        "ms after current limiting begins (tCL_PLIM_FLT, sec 6.6)."
        % (FLT_DIAG_DWELL * 1e3, T_CLPLIM[2] * 1e3, (FLT_DIAG_DWELL - T_CLPLIM[2]) * 1e3, T_CLPLIM_FLT[0] * 1e3,
           T_CLPLIM_FLT[2] * 1e3))
    RJ["n"] = dict(i_bridge_max_mA=f2(i_max * 1e3), i_bridge_min_mA=f2(i_min * 1e3), abs_max_mA=I_FLT_ABS * 1e3,
                   factor=f2(I_FLT_ABS / i_max), v_flt_pin_max=f2(v_flt_pin), v_en_min=f2(v_en_min),
                   p_r106s_mW=f2(p_r * 1e3), i_h2c_mA=f2(i_h2c * 1e3), readback_low_typ=f2(rb_typ),
                   readback_low_max=f2(rb_max), vil=f2(vil), readback_margin=f2(vil - rb_max),
                   r7_bridge_mA=(f2(i_r7_40[0] * 1e3), f2(i_r7_40[1] * 1e3), f2(i_r7_max * 1e3)),
                   r7_en_V=(f2(v_en_r7[0]), f2(v_en_r7[1])), r7_rflt_for_off=f2(r_flt_off),
                   diag_dwell_margin_ms=f2((FLT_DIAG_DWELL - T_CLPLIM[2]) * 1e3))
    summ("R106s FLT bridge bound (r8, CHG-R1-01)", "F05/F06-F17 bridge: FLT current <= %.3f mA (%.2f x below the %.0f mA "
         "abs max, tps2663.pdf 6.1; 3V3 +5 %%, R106s -1 %%, R(FLT) 36 ohm, 0 ohm driver); EN stays >= %.2f V (as "
         "commanded); r7 without R106s %.1f-%.1f mA (40 ohm driver)" % (i_max * 1e3, I_FLT_ABS / i_max,
                                                                       I_FLT_ABS * 1e3, v_en_min, i_r7_40[0] * 1e3,
                                                                       i_r7_40[1] * 1e3), "H.23(n)")
    summ("FLT readback level (r8)", "LOW = 3V3 x (R(FLT) + R106s)/(R_pu + R(FLT) + R106s): %.3f V typ, %.3f V max vs VIL "
         "%.3f V (margin %.3f V); FR-23 diagnostic dwell 250 ms vs tCL_PLIM 202 ms (margin %.0f ms)"
         % (rb_typ, rb_max, vil, vil - rb_max, (FLT_DIAG_DWELL - T_CLPLIM[2]) * 1e3), "H.23(n)")


# H.23(o) T3 I2C transaction schedule (CHG-R1-02)
I2C_TBUF = {100e3: 4.7e-6, 400e3: 1.3e-6}   # s, bus free time STOP -> START (Sm / Fm), NXP UM10204 Table 10;
#                                             not in references/: TODO(verify: NXP UM10204 rev 7)
I2C_CAP = {100e3: 0.50e-3, 400e3: 0.35e-3}  # s, DOC FR-07 longest-transaction cap
FR07_DEADLINE = 1.5e-3                      # s, DOC FR-07 / G.1 T3: edge to write complete


def i2c_bits_write(n_data):
    """START + address(W) + register + n data bytes (8 bits + ACK each) + STOP; START and STOP one bit time each
    (round3 H.16 convention)."""
    return (2 + n_data) * 9 + 2


def i2c_bits_read(n_data):
    """START + address(W) + register + repeated START + address(R) + n data bytes (master ACK/NACK) + STOP."""
    return (3 + n_data) * 9 + 3


def sec_o():
    head("H.23(o) T3 raise: published I2C transaction schedule at 100 and 400 kHz (r8, CHG-R1-02)")
    out("Bit counts: a byte = 8 bits + ACK = 9 bit times; START, repeated START and STOP = 1 bit time each (the round3 "
        "H.16 convention, 'bytes x 9 + 2'); bus free time t_BUF between transactions %.1f us (100 kHz) / %.1f us "
        "(400 kHz) (NXP UM10204 Table 10, TODO(verify: not in references/)); the wait for a transaction already in "
        "flight = the FR-07 cap %.2f / %.2f ms. Writes: W(REG06:07) = %d bits (address, register, 2 data); W(REG03-05) "
        "= %d bits (3 data). Reads: R(n) = %d + 9 n bits (address W, register, repeated START, address R, n data)."
        % (I2C_TBUF[100e3] * 1e6, I2C_TBUF[400e3] * 1e6, I2C_CAP[100e3] * 1e3, I2C_CAP[400e3] * 1e3,
           i2c_bits_write(2), i2c_bits_write(3), i2c_bits_read(0)))
    rows = {}
    for f in (100e3, 400e3):
        tb, cap = I2C_TBUF[f], I2C_CAP[f]
        w2, w3 = i2c_bits_write(2) / f, i2c_bits_write(3) / f
        r2, r1, r7_ = i2c_bits_read(2) / f, i2c_bits_read(1) / f, i2c_bits_read(7) / f
        t_w = cap + tb + w2 + tb + w3
        t_r6 = cap + tb + w2 + tb + r2 + tb + r2 + tb + w3      # r6 FR-46 literal: write, read REG01:02 + REG06:07, write
        four = [("REG01:02 VREG", r2), ("REG03:04 ICHG", r2), ("REG05 VINDPM", r1), ("REG06:07 IINDPM", r2)]
        t_v4 = t_w + sum(tb + t for _, t in four)
        t_v1 = t_w + tb + r7_
        rows[f] = dict(w2=w2, w3=w3, t_w=t_w, t_r6=t_r6, r7=r7_, t_v1=t_v1, t_v4=t_v4, four=four, cap=cap,
                       wr_only=w2 + w3)
        lab = "%.0f kHz" % (f / 1e3)
        out("  %s: W(REG06:07) %.3f ms, W(REG03-05) %.3f ms (writes alone %.3f ms; round3 H.16 '%.2f ms'). r8 schedule "
            "(write first, read back after): in-flight %.3f + t_BUF + W(REG06:07) + t_BUF + W(REG03-05) = edge to write "
            "complete %.3f ms against the FR-07 %.1f ms deadline (margin %.3f ms). r6 FR-46 literal schedule (W(REG06:07), "
            "R(REG01:02), R(REG06:07), then W(REG03-05)): %.3f ms (%s)."
            % (lab, w2 * 1e3, w3 * 1e3, (w2 + w3) * 1e3, (w2 + w3) * 1e3, cap * 1e3, t_w * 1e3, FR07_DEADLINE * 1e3,
               (FR07_DEADLINE - t_w) * 1e3, t_r6 * 1e3, "MISSES the deadline by %.3f ms" % ((t_r6 - FR07_DEADLINE) * 1e3)
               if t_r6 > FR07_DEADLINE else "inside the deadline"))
        out("    verification read after the deadline: (a) one R(REG01-07), 7 data bytes: %.3f ms (%s the %.2f ms cap); "
            "complete %.3f ms after the edge. (b) four field reads %s: each %s the cap; complete %.3f ms after the edge. "
            "A queued write waits behind a read for at most one byte + STOP = %.3f ms (reads abortable at a byte "
            "boundary, FR-07)."
            % (r7_ * 1e3, "inside" if r7_ <= cap else "EXCEEDS", cap * 1e3, t_v1 * 1e3,
               ", ".join("%s %.3f ms" % (n, t * 1e3) for n, t in four),
               "inside" if all(t <= cap for _, t in four) else "NOT all inside", t_v4 * 1e3, 10 / f * 1e3))
    out("  Recommendation (r8): the T3 raising writes REG06:07 then REG03-05 complete first; the FR-46 read-back of "
        "REG01:02, REG03:04, REG05 and REG06:07 follows as four field reads (each inside the FR-07 cap at both rates, "
        "no 16-bit field split across transactions); a mismatch takes the immediate P5-LOW path. The edge-to-write "
        "deadline excludes the read-back. No V-MOT peak is derived from the read-back delay (agreed fix, rejected part).")
    RJ["o"] = {("%.0fk" % (f / 1e3)): dict(w2_ms=f2(v["w2"] * 1e3), w3_ms=f2(v["w3"] * 1e3), edge_to_write_ms=f2(v["t_w"] * 1e3),
                                         r6_literal_ms=f2(v["t_r6"] * 1e3), read7_ms=f2(v["r7"] * 1e3),
                                         verify_single_ms=f2(v["t_v1"] * 1e3), verify_four_ms=f2(v["t_v4"] * 1e3),
                                         cap_ms=v["cap"] * 1e3) for f, v in rows.items()}
    a, b = rows[100e3], rows[400e3]
    summ("T3 schedule (r8, CHG-R1-02)", "edge to write complete %.3f ms (100 kHz) / %.3f ms (400 kHz) vs 1.5 ms; r6 FR-46 "
         "literal %.3f / %.3f ms; read-back after (four field reads, each <= cap) complete at %.3f / %.3f ms; one 7-byte "
         "read %.3f ms exceeds the 0.50 ms cap at 100 kHz" % (a["t_w"] * 1e3, b["t_w"] * 1e3, a["t_r6"] * 1e3,
                                                             b["t_r6"] * 1e3, a["t_v4"] * 1e3, b["t_v4"] * 1e3,
                                                             a["r7"] * 1e3), "H.23(o)")


# H.23(p) W1/W2 lead inductance (CHG-R1-D04)
def awg_d(n):
    """Bare diameter of an AWG gauge, mm (ASTM B258 definition)."""
    return 0.127 * 92 ** ((36 - n) / 39.0)


C103_OUT = 1.0e-6         # F, DOC H.5 / B.4 C103 (the 0.61 us quarter period of 0.15 uH x C103)
T_FASTTRIP = 1.0e-6       # s, tps2663.pdf sec 6.6 tFASTTRIP(dly) hot-short response
TWIST_P = (20.0, 25.0)    # mm, r8 W1/W2 twist pitch (A.3 >= 1 twist / 25 mm; r8 adds the 20 mm lower bound)
W12_INSUL = [             # (label, OD min, OD max) mm: insulation classes, ASSUMPTION; TODO(verify: maker datasheet)
    ("thin-wall PTFE/ETFE (M22759/11 or /16 class)", 1.10, 1.45),
    ("r7 calc assumption (PVC hook-up, 1.6 mm)", 1.60, 1.60),
    ("PVC 300 V hook-up (UL1007/UL1569 class)", 1.55, 1.80),
    ("600 V PVC or silicone (UL1015/UL3135 class)", 1.95, 2.60),
]
TRUNK_LEADS = ["W1", "W2", "W3", "W4", "W6", "W7 SCL", "W7 SDA", "W7 GND"]
WEST_LEADS = ["W1", "W2", "W6", "W7 SCL", "W7 SDA", "W7 GND"]


def paths_with_od(od12):
    """w_paths() with the W1/W2 jacket OD set to od12 (every other OD as in H.23(l)); restores the globals."""
    global H_TRUNK, H_WEST
    sv = (OD["W1"], OD["W2"], H_TRUNK, H_WEST)
    try:
        OD["W1"], OD["W2"] = [od12], [od12]
        H_TRUNK, H_WEST = hgrp(TRUNK_LEADS), hgrp(WEST_LEADS)
        return w_paths(), H_TRUNK, H_WEST
    finally:
        OD["W1"], OD["W2"], H_TRUNK, H_WEST = sv


def plan_rule_with_od(od12):
    paths, htr, hwe = paths_with_od(od12)
    hz = hazard_rects()
    res = {}
    for lead, p in paths.items():
        if lead == "W5":
            continue
        res[lead] = (path_min(p, hz, BEAD_LEN), path_min(p, {"tap field courtyard": FIELD["cyd"]}, BEAD_LEN))
    worst = min(res.items(), key=lambda kv: kv[1][0][0])
    return res, worst, htr, hwe


def lprime(s_mm, a_mm):
    return MU0_PI * math.acosh(s_mm / (2.0 * a_mm))


def spike_worst(Lh):
    worst = None
    for v0 in (16.0, 22.0):
        for cs in (5e-6, 20e-6):
            for lin in (50e-9, 150e-9):
                vpk, ioff, ipk = in_spike(v0, cs, lin, 3.4e-6, lout=Lh)
                if worst is None or vpk > worst[0]:
                    worst = (vpk, ioff, ipk, v0, cs, lin)
    return worst


def sec_p():
    head("H.23(p) W1/W2 lead inductance: L' = (mu0/pi) acosh(s/2a) over the wire geometry; recommended wire; hard-short "
         "IN peak with the unchanged in_spike model (r8, CHG-R1-D04)")
    cond = {"20 AWG solid": awg_d(20) / 2, "20 AWG 7/28 (bundle 3 d)": 3 * awg_d(28) / 2,
            "20 AWG 19/32 (bundle 5 d)": 5 * awg_d(32) / 2}
    a_lo, a_hi = min(cond.values()), max(cond.values())
    out("Model: parallel round conductors, external inductance per unit length L' = (mu0/pi) acosh(s/2a) (H/m), s = "
        "centre spacing = the jacket OD for a twisted pair whose jackets touch, a = conductor radius. Lower bound (the "
        "spike-critical case): s = OD min, a = the largest conductor radius (stranded bundle, current on the bundle "
        "surface at the 0.4-1 MHz ring), no internal inductance, divided by the helix factor k = sqrt(1 + (pi OD_max / p)^2) "
        "evaluated at OD max (conservative: a larger k gives a smaller L') and the tightest pitch p = %.0f mm (the build length is cut along the wire). Upper bound: s = OD max, a = the "
        "solid radius, k = 1, plus the DC internal inductance 2 x mu0/(8 pi) = 0.10 uH/m. Conductor radii (ASTM B258 "
        "diameters): %s. The in_spike model of H.23(l) (round3 r3_calc.py H.19(b)) is unchanged; only lout = L' x "
        "length changes. r7 basis: 0.5 uH/m, unsourced (CHG-R1-D04)."
        % (TWIST_P[0], "; ".join("%s a = %.4f mm" % (k, v) for k, v in cond.items())))
    v95 = spike_worst(95e-9)
    out("  check of the counter-review figure: lout 95 nH (thin-wall PTFE at 290 mm): IN peak %.2f V, lead peak %.2f A "
        "(CHG-R1-D04 round 2: 34.68 V / 140.95 A)" % (v95[0], v95[2]))
    p_ok = plan_rule_with_od(AWG20_OD)
    out("  plan dressing rule (D-F2, >= 2.0 mm) on the designed path at the r7 W1/W2 OD %.2f mm: worst lead %s %.3f mm "
        "(%s), trunk half-width %.3f mm (reproduces H.23(l))." % (AWG20_OD, p_ok[1][0], p_ok[1][1][0][0],
                                                                 p_ok[1][1][0][1], p_ok[2]))
    lo, hi = 1.0, 3.0
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        if plan_rule_with_od(mid)[1][1][0][0] >= HAZ_GAP - 1e-9:
            lo = mid
        else:
            hi = mid
    od_allow = lo
    pr_al = plan_rule_with_od(od_allow)
    out("  largest W1/W2 OD that keeps the 2.0 mm plan dressing rule on the designed path (bisection): %.3f mm (worst "
        "lead %s at %s; trunk half-width %.3f mm, west group %.3f mm). A larger OD widens the trunk bundle (hgrp) and "
        "breaks the rule at the +x pocket unless the path is re-routed." % (od_allow, pr_al[1][0], pr_al[1][1][0][1],
                                                                          pr_al[2], pr_al[3]))
    rows = []
    for lab, od0, od1 in W12_INSUL:
        k = math.sqrt(1 + (math.pi * od1 / TWIST_P[0]) ** 2)
        lmin = lprime(od0, a_hi) / k if od0 > 2 * a_hi else float("nan")
        lmax = lprime(od1, a_lo) + 0.10e-6
        wl = spike_worst(lmin * W12_BUILD[0] / 1000.0)
        wh = spike_worst(lmax * W12_BUILD[2] / 1000.0)
        qp = (math.pi / 2) * math.sqrt(lmax * W12_BUILD[2] / 1000.0 * C103_OUT)
        rows.append((lab, od0, od1, lmin, lmax, wl, wh, qp, od1 <= od_allow + 1e-9))
        out("  %-46s OD %.2f-%.2f mm: L' %.3f-%.3f uH/m; at 290 mm with L' min (%.0f nH): IN peak %.2f V (margin %.2f V "
            "to D107 VBR(min) 36 V), %.0f A at turn-off, lead peak %.0f A; at 310 mm with L' max (%.0f nH): IN peak "
            "%.2f V, lead peak %.0f A; OUT ring quarter period with C103 %.1f uF at L max %.3f us (< tFASTTRIP %.1f us: "
            "%s); plan rule at OD max: %s"
            % (lab, od0, od1, lmin * 1e6, lmax * 1e6, lmin * W12_BUILD[0] * 1e6, wl[0], 36.0 - wl[0], wl[1], wl[2],
               lmax * W12_BUILD[2] * 1e6, wh[0], wh[2], C103_OUT * 1e6, qp * 1e6, T_FASTTRIP * 1e6,
               "yes" if qp < T_FASTTRIP else "NO", "met" if od1 <= od_allow + 1e-9 else "FAILS (> %.3f mm)" % od_allow))
    # recommended wire
    rec_od = (1.60, math.floor(min(1.75, od_allow) * 20 + 1e-9) / 20)
    k = math.sqrt(1 + (math.pi * rec_od[1] / TWIST_P[0]) ** 2)
    lmin = lprime(rec_od[0], a_hi) / k
    lmax = lprime(rec_od[1], a_lo) + 0.10e-6
    rec = {}
    for Lmm in W12_BUILD:
        rec[Lmm] = (spike_worst(lmin * Lmm / 1000.0), spike_worst(lmax * Lmm / 1000.0))
    qp = (math.pi / 2) * math.sqrt(lmax * W12_BUILD[2] / 1000.0 * C103_OUT)
    pr_rec = plan_rule_with_od(rec_od[1])
    out("  RECOMMENDED W1/W2 (r8): 20 AWG stranded copper, 19/32 (or 7/28), insulation OD %.2f-%.2f mm (PVC 300 V "
        "hook-up class, UL1007/UL1569; any insulation whose measured OD lies in the range is admissible), twisted pair, "
        "pitch %.0f-%.0f mm, jackets touching. L' %.3f-%.3f uH/m (lower bound: OD %.2f, a %.4f mm, k %.4f; upper: OD "
        "%.2f, solid a, + internal):"
        % (rec_od[0], rec_od[1], TWIST_P[0], TWIST_P[1], lmin * 1e6, lmax * 1e6, rec_od[0], a_hi, k, rec_od[1]))
    for Lmm in W12_BUILD:
        w0, w1 = rec[Lmm]
        out("    %3.0f mm: L %.1f-%.1f nH; IN peak %.2f V (L min; V0 %.0f V, C_S %.0f uF, L_IN %.0f nH) / %.2f V (L max); "
            "margin to D107 VBR(min) 36 V %.2f V; %.0f A at turn-off; lead peak %.0f A (L min) / %.0f A (L max)"
            % (Lmm, lmin * Lmm * 1e6, lmax * Lmm * 1e6, w0[0], w0[3], w0[4] * 1e6, w0[5] * 1e9, w1[0], 36.0 - w0[0],
               w0[1], w0[2], w1[2]))
    out("    plan rule at OD %.2f mm: worst lead %s %.3f mm (%s); trunk half-width %.3f mm; OUT ring quarter period at L "
        "max %.3f us (< 1 us); the statement 'no pair reaches 36 V' holds only inside this modelled envelope (20 AWG "
        "19/32 or 7/28, OD %.2f-%.2f mm, pitch %.0f-%.0f mm, 290-310 mm, the H.19(b) source grid)."
        % (rec_od[1], pr_rec[1][0], pr_rec[1][1][0][0], pr_rec[1][1][0][1], pr_rec[2], qp * 1e6, rec_od[0], rec_od[1],
           TWIST_P[0], TWIST_P[1]))
    EXTRA["p"] = dict(rec_od=rec_od, od_allow=od_allow, lmin=lmin, lmax=lmax, h_trunk=pr_rec[2], h_west=pr_rec[3])
    RJ["p"] = dict(conductor_radii={k_: f2(v) for k_, v in cond.items()}, check_95nH=(f2(v95[0]), f2(v95[2])),
                   od_allow=f2(od_allow),
                   candidates=[dict(label=r[0], od=(r[1], r[2]), lprime_uH_m=(f2(r[3] * 1e6), f2(r[4] * 1e6)),
                                    in_peak_290_Lmin=f2(r[5][0]), lead_peak_290=f2(r[5][2]), in_peak_310_Lmax=f2(r[6][0]),
                                    quarter_us=f2(r[7] * 1e6), plan_ok=r[8]) for r in rows],
                   recommended=dict(od=rec_od, pitch=TWIST_P, lprime_uH_m=(f2(lmin * 1e6), f2(lmax * 1e6)),
                                    rows={str(k_): dict(in_peak_Lmin=f2(v[0][0]), in_peak_Lmax=f2(v[1][0]),
                                                        i_off=f2(v[0][1]), lead_peak_Lmin=f2(v[0][2]),
                                                        margin=f2(36.0 - v[0][0])) for k_, v in rec.items()},
                                    plan_worst=f2(pr_rec[1][1][0][0]), h_trunk=f2(pr_rec[2])))
    w290 = rec[W12_BUILD[0]][0]
    summ("W1/W2 wire (r8, CHG-R1-D04)", "20 AWG 19/32 (or 7/28), OD %.2f-%.2f mm, pitch %.0f-%.0f mm: L' %.3f-%.3f uH/m; "
         "worst IN peak %.2f V at 290 mm (margin %.2f V to 36 V), lead peak %.0f A; plan rule %.3f mm (OD limit %.3f mm); "
         "counter-review check 95 nH -> %.2f V / %.2f A" % (rec_od[0], rec_od[1], TWIST_P[0], TWIST_P[1], lmin * 1e6,
                                                          lmax * 1e6, w290[0], 36.0 - w290[0], w290[2],
                                                          pr_rec[1][1][0][0], od_allow, v95[0], v95[2]), "H.23(p)")


# H.23(q) pin-38 decay (CHG-R1-D02)
C_VCHGIN_NOM = 25.8e-6       # F, round3 r3_calc.py C_BOARD_VCHGIN: C-D8 + C-D10 20 uF + C102a 1 uF + C102b 4.7 uF + C102c
C_VCHGIN = (0.66 * C_VCHGIN_NOM, 1.10 * C_VCHGIN_NOM)   # ASSUMPTION: -34 % (DC bias and tolerance at ~10 V) / +10 %
#                                                        (tolerance at low voltage); TODO(verify: C-D8/C-D10/C102 parts)
R_DIV38 = 88.7e3             # ohm, R1-CHG 78.7 kOhm + 10 kOhm (round3 K_DIV 10/88.7)
R_UVOV = 845e3 + 66.5e3 + 49.9e3   # ohm, R102 + R103 + R104 (round3 H.5)
IQ_ON = (1.38e-3, 1.70e-3)   # A, tps2663.pdf sec 6.5 IQ(ON) TYPICAL 1.38 mA / MAXIMUM 1.70 mA (enabled,
#                              4.5 V < V(IN_SYS) < 60 V); no minimum is specified (revision 7 label correction)
V_INSYS_MIN = 4.5            # V, tps2663.pdf sec 6.5 operating V(IN_SYS) minimum (IQ below it unspecified)
UVLO_F = (9.70, 10.13)       # V, DOC H.5 eFuse UVLO band (falling basis 9.9 V, FR-12)
ON_STATE = ((30e-6, 4.9e-3), (57e-6, 3.4e-3))   # (C, I) round3 r3_calc.py H.21(g): eFuse ON, charger held, EVM side
V0_SET = (12.5, 16.0, 19.38, 22.28)  # V, V_chg before the switches open: just above 12 V, V_bus, VINDPM max, design clamp


def t_decay(v0, v1, c, iq_fn, dt=1e-4, tmax=20.0):
    """Time for C dV/dt = -(V/R_DIV38 + V/R_UVOV + iq_fn(V)) to fall from v0 to v1 (Euler, dt 0.1 ms)."""
    v, t = v0, 0.0
    if v0 <= v1:
        return 0.0
    while v > v1 and t < tmax:
        i = v / R_DIV38 + v / R_UVOV + iq_fn(v)
        v -= i / c * dt
        t += dt
    return t if v <= v1 else float("inf")


def sec_q():
    head("H.23(q) pin-38 V_chg decay after both charger-path EN readbacks go LOW: the r7 '3 V within 2 s' test and the r8 "
         "proposed '12 V after 0.5 s' stuck-path criterion (CHG-R1-D02)")
    r_par = 1 / (1 / R_DIV38 + 1 / R_UVOV)
    out("Inputs: VCHG-IN (IN side of U101) capacitance %.1f uF nominal (round3 C_BOARD_VCHGIN), %.1f-%.1f uF (ASSUMPTION "
        "-34 %%/+10 %%, TODO(verify: C-D8/C-D10/C102 datasheets; T-C-04 measures)); loads: pin-38 divider %.1f kOhm, "
        "UVLO/OVP string %.1f kOhm (parallel %.1f kOhm), eFuse IN_SYS current IQ(ON) %.2f mA typ / %.2f mA max, no minimum (tps2663.pdf sec 6.5, "
        "specified while enabled and V(IN_SYS) > %.1f V). eFuse states: ON (V above UVLO, no latch: the EVM side is "
        "connected, C and standby draw of round3 H.21(g): %s); LATCHED or in UVLO (FET off, IN side only, IQ(ON) typ above "
        "4.5 V); UNBIASED (IQ = 0, a bound for the unspecified UVLO/latched IQ, TODO(verify: SLVSE94G IQ in UVLO; "
        "T-C-04))." % (C_VCHGIN_NOM * 1e6, C_VCHGIN[0] * 1e6, C_VCHGIN[1] * 1e6, R_DIV38 / 1e3, R_UVOV / 1e3,
                       r_par / 1e3, IQ_ON[0] * 1e3, IQ_ON[1] * 1e3, V_INSYS_MIN,
                       ", ".join("%.0f uF / %.1f mA" % (c * 1e6, i * 1e3) for c, i in ON_STATE)))
    # r7 FR-12(b): 9.9 V -> 3 V within 2 s (below UVLO: IN side only)
    r7rows = []
    for c in (C_VCHGIN[0], C_VCHGIN_NOM, C_VCHGIN[1]):
        t_rc = c * r_par * math.log(9.9 / 3.0)
        t_iq = t_decay(9.9, 3.0, c, lambda v: IQ_ON[0] if v > V_INSYS_MIN else 0.0)
        r7rows.append((c, t_rc, t_iq))
    out("  r7 FR-12(b) basis, 9.9 V -> 3.0 V below UVLO (IN side only): UNBIASED (RC, tau = C x %.1f kOhm) %s; LATCHED "
        "with IQ(ON) typ down to 4.5 V then RC: %s. The 2 s limit fails in the UNBIASED state for C >= %.1f uF (a warm "
        "reset with a fast bring-up can false-fail FR-12(b))."
        % (r_par / 1e3, ", ".join("%.1f uF %.2f s (tau %.2f s)" % (c * 1e6, t1, c * r_par) for c, t1, _ in r7rows),
           ", ".join("%.1f uF %.2f s" % (c * 1e6, t2) for c, _, t2 in r7rows), 2.0 / (r_par * math.log(9.9 / 3.0)) * 1e6))
    # r8 proposed: V_chg < 12 V after both EN readbacks LOW for >= 0.5 s
    out("  r8 proposed stuck-path criterion: V_chg (pin 38) < 12.0 V once both EN readbacks have been LOW for >= 0.5 s. "
        "Time from V0 to 12.0 V (12 V lies above the UVLO band %.2f-%.2f V and above 4.5 V, so IQ(ON) applies whenever "
        "the eFuse is enabled):" % UVLO_F)
    worst = (0.0, None)
    tab = []
    for v0 in V0_SET:
        cells = []
        for c, i in ON_STATE:
            t = c * (v0 - 12.0) / i if v0 > 12.0 else 0.0     # constant standby draw (round3 H.21(g) basis)
            cells.append(("ON %.0f uF/%.1f mA" % (c * 1e6, i * 1e3), t))
        for c in C_VCHGIN:
            t = t_decay(v0, 12.0, c, lambda v: IQ_ON[0])
            cells.append(("LATCHED %.1f uF" % (c * 1e6), t))
        for c in C_VCHGIN:
            t = c * r_par * math.log(v0 / 12.0) if v0 > 12.0 else 0.0
            cells.append(("UNBIASED %.1f uF" % (c * 1e6), t))
        tab.append((v0, cells))
        for lab, t in cells:
            if not lab.startswith("UNBIASED") and t > worst[0]:
                worst = (t, "%s from %.2f V" % (lab, v0))
        out("    V0 %5.2f V: %s" % (v0, "; ".join("%s %.3f s" % z for z in cells)))
    # break-even IN-side current for 0.5 s from the highest V0 with the largest C
    v0m, cm = V0_SET[-1], C_VCHGIN[1]
    lo_, hi_ = 0.0, 5e-3
    for _ in range(40):
        mid = 0.5 * (lo_ + hi_)
        if t_decay(v0m, 12.0, cm, lambda v: mid) <= 0.5:
            hi_ = mid
        else:
            lo_ = mid
    out("  worst case with the eFuse enabled (ON or LATCHED): %.3f s (%s): margin %.3f s against 0.5 s. UNBIASED (IQ = 0 "
        "above 12 V is outside the IQ(ON) conditions) would exceed 0.5 s from >= %.1f V; the criterion needs an IN-side "
        "eFuse current >= %.3f mA (from %.2f V, %.1f uF) against IQ(ON) typ %.2f mA (no minimum specified): TODO(verify) across the initial "
        "voltage and the eFuse states in T-C-04 (proposed criterion, not an established bound)."
        % (worst[0], worst[1], 0.5 - worst[0], 12.0 * math.exp(0.5 / (C_VCHGIN[1] * r_par)), hi_ * 1e3, v0m, cm * 1e6,
           IQ_ON[0] * 1e3))
    vb_nom, vb_low = 15.9, 14.16
    k_tol = 0.02
    out("  stuck path (a shorted D-BC-FC or D-BC-RG with MOT_PWR HIGH in Idle): V_chg = V_bus (V-MOT) = %.1f V no-load "
        "(CLAUDE.md section 6), >= %.2f V at the UVB rise maximum: %.2f V / %.2f V above 12.0 V; with a pin-38 gain error "
        "of +-%.0f %% (divider 1 %% resistors, ASSUMPTION) the reading stays >= %.2f V. A healthy path decays below 12 V "
        "in <= %.3f s (eFuse enabled)." % (vb_nom, vb_low, vb_nom - 12.0, vb_low - 12.0, k_tol * 100,
                                          vb_low * (1 - k_tol), worst[0]))
    RJ["q"] = dict(r7=[dict(c_uF=f2(c * 1e6), t_rc=f2(t1), t_iq=f2(t2)) for c, t1, t2 in r7rows],
                   r8={str(v0): [(lab, f2(t)) for lab, t in cells] for v0, cells in tab},
                   worst_enabled=(f2(worst[0]), worst[1]), margin_s=f2(0.5 - worst[0]),
                   i_break_even_mA=f2(hi_ * 1e3), stuck_low_V=f2(vb_low * (1 - k_tol)))
    summ("pin-38 decay (r8, CHG-R1-D02)", "r7 9.9 -> 3 V: %.2f-%.2f s (UNBIASED RC, C %.1f-%.1f uF); r8 12 V / 0.5 s: "
         "worst %.3f s with the eFuse enabled (margin %.3f s); needs IN-side current >= %.3f mA from %.2f V (IQ(ON) typ "
         "%.2f mA); stuck path >= %.2f V" % (r7rows[0][1], r7rows[-1][1], C_VCHGIN[0] * 1e6, C_VCHGIN[1] * 1e6,
                                             worst[0], 0.5 - worst[0], hi_ * 1e3, v0m, IQ_ON[0] * 1e3,
                                             vb_low * (1 - k_tol)), "H.23(q)")


# H.23(r) foot-bond fallback (CHG-R1-05, A-04)
T_RM = (0.125, 0.150, 0.175)   # mm, removed sheet stack (film + PSA): 0.125 if the DOC A.7 0.125 mm is the total;
#                                + 0.025-0.050 mm silicone PSA if it is the film alone (ASSUMPTION; TODO(verify:
#                                polyimide sheet datasheet, PSA thickness), measured with a micrometer before re-making
T_RM_MEAS = 0.01               # mm, +- micrometer reading of the removed stack (ASSUMPTION)


def sec_r():
    head("H.23(r) foot-bond fallback: re-made foot height from the measured removed sheet stack; PM4 (2d) gate re-run; "
         "FT2 repair access (r8, CHG-R1-05, A-04)")
    fi = RJ["i"]
    out("Basis (H.23(i), D-F1): h_f = %.2f - t_bed - t_bond = %.2f mm with headers and feet both on the sheet. The "
        "fallback removes the sheet (film + PSA) under one foot, so that foot stands t_rm lower while the headers keep "
        "their sheet seat. Unchanged foot: t_bed grows by t_rm." % (H_HDR, H_F))
    fx = {"FT1": fi["ft1"], "FT2": fi["ft2"]}
    for tn, a_ in (("FT1", 6.4), ("FT2", 16.0)):
        tb = (T_BED[0] + T_RM[0], T_BED[2] + T_RM[0])
        kmin_g = E_RTV[0] * a_ / T_BED[2]
        kmin_f = E_RTV[0] * a_ / tb[1]
        out("  %s unchanged foot, t_rm %.3f mm: gated bed %.3f-%.3f mm becomes %.3f-%.3f mm; k_s min %.2f N/mm (E %.0f "
            "MPa, A %.1f mm2) against the gated minimum %.2f N/mm (x%.3f)" % (tn, T_RM[0], T_BED[0], T_BED[2], tb[0], tb[1],
                                                                          kmin_f, E_RTV[0], a_, kmin_g, kmin_f / kmin_g))
    out("  re-made foot h_f' = h_f + t_rm (t_rm = the measured removed stack, film + PSA, +-%.2f mm reading): %s; block "
        "tolerance +0/-0.05 mm as h_f; the bed returns to the nominal %.2f mm and the PM4 (2d) 0.15 / 0.45 mm feeler "
        "gate is repeated before the CR is soldered."
        % (T_RM_MEAS, ", ".join("t_rm %.3f mm -> %.3f mm" % (t, H_F + t) for t in T_RM), T_BED[1]))
    mc = {}
    for tn, lever in (("FT1", fx["FT1"]["centre"][0] - 45.998), ("FT2", fx["FT2"]["centre"][1] - PIN11_Y)):
        bow = BOW * lever
        rng = random.Random(11)
        n, n_in = 200000, 0
        for _ in range(n):
            t = (T_BED[1] + rng.uniform(-TOL_BODY, TOL_BODY) + rng.uniform(-bow, bow) - rng.uniform(*TOL_BLOCK)
                 + (T_BOND - rng.uniform(*TOL_TAPE)) + rng.uniform(-T_RM_MEAS, T_RM_MEAS))
            if GATE[0] < t < GATE[1]:
                n_in += 1
        mc[tn] = n_in / n
    out("  gate re-run with the re-made foot (H.23(i) contributors + the +-%.2f mm t_rm reading, uniform, 200 000 builds, "
        "ORDER OF MAGNITUDE): FT1 %.1f %% pass, FT2 %.1f %% pass (H.23(i): %s); a fail re-makes the foot again"
        % (T_RM_MEAS, 100 * mc["FT1"], 100 * mc["FT2"], "79.7 / 85.8 %"))
    c2 = fx["FT2"]["centre"]
    body = (c2[0] - 2.0, c2[1] - 2.0, c2[0] + 2.0, c2[1] + 2.0)
    gap_lfc = LFC_EATON[1] - body[3]
    slot = Z_CR_TOP - T_CR - 0.125
    out("  FT2 repair access after the CR is soldered: FT2 body x %.2f-%.2f, y %.2f-%.2f under tab Y; slot height under "
        "the CR %.3f mm (CR underside %.3f mm - sheet 0.125 mm); +y face to the tab Y +y edge (y %.2f) %.2f mm and to "
        "the L-FC body (y %.3f, %.1f mm tall, ASSUMPTION) %.3f mm in plan: no tool or new foot passes on that side; -x "
        "face to the tab Y -x edge (x %.2f) %.2f mm under the tab Y bottom parts (decouplers, height cap 1.0 mm); fill "
        "hole (1.0 mm) at the foot centre from the CR top. The sheet under FT2 cannot be removed without lifting the CR, "
        "so the fallback is executable before the 22 joints are soldered (T-A-09 at the PM4 (2d) dry seat); after "
        "soldering, a re-bed is limited to RTV injection through the fill hole."
        % (body[0], body[2], body[1], body[3], slot, Z_CR_TOP - T_CR, TAB_Y[3], TAB_Y[3] - body[3], LFC_EATON[1], H_LFC,
           gap_lfc, TAB_Y[0], body[0] - TAB_Y[0]))
    RJ["r"] = dict(t_rm=T_RM, h_f_new=[f2(H_F + t) for t in T_RM], gate_pass=mc, ft2_body=body, ft2_gap_lfc=f2(gap_lfc),
                   slot=f2(slot))
    summ("foot-bond fallback (r8, CHG-R1-05)", "re-made foot h_f' = %.2f + t_rm: %.3f mm at t_rm 0.125 (%.3f / %.3f at "
         "0.150 / 0.175); gate re-run FT1 %.1f %% / FT2 %.1f %%; unchanged foot k_s down to x%.3f; FT2 +y face %.3f mm "
         "from L-FC" % (H_F, H_F + T_RM[0], H_F + T_RM[1], H_F + T_RM[2], 100 * mc["FT1"], 100 * mc["FT2"],
                        T_BED[2] / (T_BED[2] + T_RM[0]), gap_lfc), "H.23(r)")


# H.23(s) B1 riser and strain relief; H.23(t) W5 / trunk stacking (CHG-R1-D03, CHG-R1-W01)
RISER_MARGIN = 0.50            # mm, design margin over the 3-D requirement (sag, layer and tape tolerance; ASSUMPTION,
#                                T-F-12 measures)
RISER_X = (24.30, 27.30)       # mm, candidate block width 3.0 mm centred on the trunk x 25.80, used only when the toe
#                                lies clear of the W2 exclusion; the chosen 65 deg toe lies inside it, so the built B1R is
#                                the RISER_W_NARROW block below (revision 7 comment correction)
RISER_W_NARROW = 2.50          # mm, block width when the toe lies inside the W2 pad exclusion band (+x edge on x 26.05)
RISER_DEGS = (55.0, 60.0, 65.0, 70.0)   # deg, candidate ramp angles
RISER_Y_END = 67.10            # mm, riser block end inside the footprint interior (tab Y top starts at y 67.14)
RIB_T = 0.9                    # mm, W5 ribbon thickness ASSUMPTION (H.23(j))


def z_need(q, h):
    """3-D switched-conductor requirement (H.23(l) sw3d inner loop, unchanged): jacket bottom above the MB top at plan
    point q for a lead of plan half-width h."""
    need, who = 0.0, None
    for s_ in SHAPES:
        if s_["net"] not in SWITCHED or s_["kind"] not in ("poly", "wire"):
            continue
        if s_["closed"] and pip(q[0], q[1], s_["pts"]):
            d = -h
        else:
            d = min(dpt_seg(q[0], q[1], p_[0], p_[1], r_[0], r_[1]) for p_, r_ in shape_segs(s_)) - s_["r"] - h
        if d < SW_GAP:
            z = H_POUR + (SW_GAP if d <= 0 else math.sqrt(SW_GAP ** 2 - d * d))
            if z > need:
                need, who = z, s_["net"]
    for nm, r_, H in (("REG-FC box", ELS["REG-FC"]["bbox"], H_REG), ("REG-BT box", ELS["REG-BT"]["bbox"], H_REG),
                      ("L-BT body", ELS["L-BT"]["bbox"], H_LFC), ("L-FC body (Eaton)", LFC_EATON, H_LFC)):
        d = d_rect_pt(r_, q[0], q[1]) - h
        if d < SW_GAP:
            z = H + (SW_GAP if d <= 0 else math.sqrt(SW_GAP ** 2 - d * d))
            if z > need:
                need, who = z, nm
    return need, who


def sample_path(pts, step=0.05):
    sl = arclen(pts)
    out_ = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        n = max(1, int(math.ceil((sl[i + 1] - sl[i]) / step)))
        for k in range(n + (1 if i == len(pts) - 2 else 0)):
            t = k / n
            out_.append((sl[i] + t * (sl[i + 1] - sl[i]), (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))))
    return out_


def sec_s_t():
    head("H.23(s) B1 riser and CR-end strain relief: a buildable profile that meets the 3-D switched-conductor rule over "
         "its full length (r8, CHG-R1-D03); H.23(t) W5 ribbon / round-lead trunk vertical stacking (r8, CHG-R1-W01)")
    P = WP
    rec = EXTRA["p"]
    h_old = H_TRUNK
    h_new = rec["h_trunk"]
    tb = 2 * h_new
    # requirement along the trunk run on the CR (x 25.80 from T1, then +x on tab Y), above the CR top
    trunk = [P["T1"], P["B1"], P["T2"], P["T3"], P["B3"], P["T4"], P["T5"], P["T6"], P["A1"]]
    smp = sample_path(trunk)
    prof = []
    for s, q in smp:
        nd, who = z_need(q, h_new)
        prof.append((s, q, nd, who, pip(q[0], q[1], OUTLINE)))
    s_b1 = arclen(trunk)[1]
    on_cr = [z for z in prof if z[4]]
    mx_cr = max(on_cr, key=lambda z: z[2])
    onset = min((z for z in prof if z[2] > 0), key=lambda z: z[0])
    out("Inputs: trunk bundle half-width %.3f mm with the r8 W1/W2 OD %.2f mm (H.23(p); r7 %.3f mm), round bundle "
        "thickness T_b = 2 x half-width = %.3f mm (hgrp, ASSUMPTION as in H.23(l)); the requirement z_req is the H.23(l) "
        "3-D rule recomputed at that half-width (L-FC 5.0 mm ASSUMPTION); CR top %.3f mm above the MB; design margin "
        "%.2f mm (ASSUMPTION: sag, wedge and post height tolerance; T-F-12 measures)." % (h_new, rec["rec_od"][1], h_old,
                                                                                 tb, Z_CR_TOP, RISER_MARGIN))
    out("  requirement onset on the trunk: (%.2f, %.3f), %.3f mm before B1 (r7 half-width: B1 at the onset); maximum on "
        "the CR %.3f mm above the MB = %.3f mm above the CR top at (%.2f, %.2f) (%s)"
        % (onset[1][0], onset[1][1], s_b1 - onset[0], mx_cr[2], mx_cr[2] - Z_CR_TOP, mx_cr[1][0], mx_cr[1][1], mx_cr[3]))
    # the r7 conflict at B1 (r7 half-width)
    pts_w2 = [(27.70, 61.20), P["T1"], P["B1"], P["T2"]]
    s_w2_b1 = arclen(pts_w2)[2]
    q_be = (25.80, P["T1"][1] + (BEAD_LEN - arclen(pts_w2)[1]))
    nd_be = z_need(q_be, h_old)[0]
    out("  r7 conflict (r7 half-width %.3f mm): W2 reaches B1 %.2f mm from its joint, so its >= %.1f mm copper bead ends "
        "at (%.2f, %.2f), %.2f mm past B1, where the rule needs the jacket %.3f mm above the CR top; the r7 B1 post "
        "(>= 10.14 mm) and the bead cannot both hold." % (h_old, s_w2_b1, BEAD_LEN, q_be[0], q_be[1],
                                                           BEAD_LEN - s_w2_b1, nd_be - Z_CR_TOP))
    # B3 post height: the CR maximum requirement + margin, rounded up to 0.1 mm
    z_top = math.ceil((mx_cr[2] - Z_CR_TOP + RISER_MARGIN) * 10 - 1e-9) / 10.0
    sl_tr = arclen(trunk)
    s_b3n = sl_tr[4] - ANCHOR_FP / 2                  # B3 post edge on the -s side
    y_t1 = P["T1"][1]
    od12_min = rec["rec_od"][0]

    def design(y0, m):
        """Wedge B1R: the wire on the ramp z = m (y - y0) from the toe y0 to the apex at RISER_Y_END (capped at z_top),
        then a straight free span from the apex to the B3 post edge at z_top, then level at z_top."""
        za = min(z_top, m * (RISER_Y_END - y0))
        sa = RISER_Y_END - y_t1                           # arc length from T1 along the x 25.80 run

        def zfun(s):
            if s <= sa:
                return min(z_top, max(0.0, m * (s + y_t1 - y0)))
            if s <= s_b3n:
                return za + (z_top - za) * (s - sa) / (s_b3n - sa)
            return z_top
        return za, zfun

    def ok(y0, m):
        za, zf = design(y0, m)
        for s, q, nd, _, oncr in prof:
            if oncr and nd > 0 and zf(s) + 1e-9 < nd - Z_CR_TOP + RISER_MARGIN:
                return False
        return True

    opts = []
    for deg in RISER_DEGS:
        m_ = math.tan(math.radians(deg))
        y0m = None
        y_ = RISER_Y_END - 0.5
        while y_ > y_t1 - 8.0:
            if ok(y_, m_):
                y0m = y_
                break
            y_ -= 0.01
        opts.append((deg, m_, y0m, None if y0m is None else m_ * (y_t1 - y0m)))
    w2x = W_PADS["W2 GND"]
    w2_excl = (w2x[0] - w2x[2] / 2 - 0.5, w2x[1] + w2x[2] / 2 + 0.5)
    out("  riser options (machined insulating wedge B1R under the trunk on the x 25.80 run: the wire on the ramp z = m "
        "(y - y0) from the toe y0 to the apex at y %.2f, then a straight free span to the B3 post edge; B3 post %.1f mm "
        "above the CR top = the CR maximum %.3f + %.2f mm rounded up to 0.1 mm; latest toe y0 that meets the "
        "requirement + margin over the full CR profile; W1/W2 join the trunk at T1 y %.2f and count as joining on the "
        "copper when the ramp there is <= the W1/W2 jacket radius %.3f mm):"
        % (RISER_Y_END, z_top, mx_cr[2] - Z_CR_TOP, RISER_MARGIN, y_t1, od12_min / 2))
    for deg, m_, y0m, zt1 in opts:
        if y0m is None:
            out("    %4.1f deg: infeasible" % deg)
            continue
        za, _ = design(y0m, m_)
        out("    %4.1f deg (m %.3f): latest toe y0 %.2f; ramp at T1 %.2f mm (%s); apex %.2f mm above the CR top"
            % (deg, m_, y0m, max(0.0, zt1), "W1/W2 join on the copper" if zt1 <= od12_min / 2 + 1e-9 else
               "W1/W2 would join a raised trunk", za))
    feas = [z for z in opts if z[2] is not None and z[3] <= od12_min / 2 + 1e-9]
    deg, m, y0, zt1 = feas[0] if feas else [z for z in opts if z[2] is not None][-1]
    y0 = math.floor(y0 * 100 + 1e-6) / 100
    za, z_built_s = design(y0, m)
    rx = RISER_X if y0 >= w2_excl[1] - 1e-9 else (w2_excl[0] - RISER_W_NARROW, w2_excl[0])
    a_blk = (rx[1] - rx[0]) * (RISER_Y_END - y0)

    def z_built(s, q):
        return z_built_s(s)
    mins = []
    for s, q, nd, who, oncr in prof:
        if not oncr or nd <= 0:
            continue
        zb = z_built(s, q)
        mins.append((zb - (nd - Z_CR_TOP), q, nd - Z_CR_TOP, zb, who))
    mn = min(mins, key=lambda z: z[0])
    x_edge = TAB_Y[2]
    span = s_b3n - (RISER_Y_END - y_t1)
    span_slope = math.degrees(math.atan((z_top - za) / span))
    ctl_s = [0.0, 1.0, 2.0, 2.67, 3.5, 4.5, 5.0]
    pts_ctl = []
    for ds in ctl_s:
        s_ = (64.50 - y_t1) + ds
        q_ = (25.80, y_t1 + s_)
        pts_ctl.append((ds, q_, z_need(q_, h_new)[0] - Z_CR_TOP, z_built(s_, q_)))
    out("  CHOSEN (r8): the shallowest listed slope whose W1/W2 join stays on the copper, %.0f deg (m %.3f). B1R = a "
        "machined insulating wedge (G10/FR-4 laminate or PEEK, ASSUMPTION; bonded to the CR top with the %.2f mm "
        "transfer tape), footprint x %.2f-%.2f, y %.2f-%.2f (%.2f mm2, replaces the 9.00 mm2 B1 spot; its +x edge on the "
        "W2 pad exclusion x %.2f), ramp face at %.0f deg from the toe y %.2f to the apex %.2f mm above the CR top at y "
        "%.2f. The leads leave the copper at the toe, lie on the ramp, then span free %.1f mm along the trunk via T2 "
        "(rising at %.1f deg) to B3, a post %.1f mm above the CR top (%.3f mm above the MB), and run level to the tab Y "
        "+x edge x %.2f. Full-profile check on the CR (every 0.05 mm from T1 to x %.2f): minimum margin over the "
        "requirement %.3f mm at (%.2f, %.2f) (required %.3f, built %.3f mm above the CR top; %s): %s. T-F-12 check "
        "points past B1 (s, required / built above the CR top): %s."
        % (deg, m, T_BOND, rx[0], rx[1], y0, RISER_Y_END, a_blk, w2_excl[0], deg, y0, za, RISER_Y_END, span, span_slope,
           z_top, z_top + Z_CR_TOP, x_edge, x_edge, mn[0], mn[1][0], mn[1][1], mn[2], mn[3], mn[4],
           "PASS (>= the %.2f mm design margin)" % RISER_MARGIN if mn[0] >= RISER_MARGIN - 1e-9 else "FAIL",
           "; ".join("+%.2f mm %.2f / %.2f" % (ds, rq, bt) for ds, _, rq, bt in pts_ctl)))
    # bead (strain relief) per lead: plan run on the copper to the toe, and the jacket length to the apex
    paths, _, _ = paths_with_od(rec["rec_od"][1])
    bead = {}
    for lead in ("W1", "W2", "W3", "W4", "W6", "W7 SCL", "W7 SDA"):
        pts = [p for p, _ in paths[lead]]
        sl = arclen(pts)
        s_y0, y_on = None, y0
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if abs(a[0] - 25.80) < 1e-6 and abs(b[0] - 25.80) < 1e-6 and a[1] <= y0 <= b[1] and s_y0 is None:
                s_y0 = sl[i] + (y0 - a[1])
        if s_y0 is None:          # joins at T1, past the toe, within its jacket radius of the copper
            j = next(i for i in range(len(pts)) if abs(pts[i][0] - 25.80) < 1e-6)
            s_y0, y_on = sl[j], pts[j][1]
        jac = s_y0 + math.hypot(RISER_Y_END - y_on, za - m * (y_on - y0))
        bead[lead] = (s_y0, jac)
    out("  CR-end strain relief (r8 restatement of the r5 bead): each lead's jacket is bonded by RTV over >= %.1f mm from "
        "its joint, on the CR copper to the toe and on along the ramp face (the wedge is bonded to the CR). Copper run "
        "to the toe or join / jacket length to the apex: %s"
        % (BEAD_LEN, "; ".join("%s %.2f / %.2f mm%s" % (k, v[0], v[1], "" if v[0] >= BEAD_LEN else
                                                       " (copper part < 5 mm, completed on the ramp)")
                               for k, v in bead.items())))
    a_int = RJ["e2"]["regions"]["interior"]["sum"] - ANCHOR_FP ** 2 + a_blk
    out("  free span from the apex to the B3 post edge %.1f mm (<= 30 mm anchor rule); interior booking with B1R instead "
        "of the B1 spot %.1f of %.1f mm2 = %.1f %% (<= 75 %%: %s); tab Y booking unchanged (B3 keeps its spot)"
        % (span, a_int, RJ["e2"]["areas"]["interior"], 100 * a_int / RJ["e2"]["areas"]["interior"],
           "pass" if a_int / RJ["e2"]["areas"]["interior"] <= 0.75 else "FAIL"))
    # off-CR: support end for a straight descent to A1 (information; the support itself stays TODO(design))
    off = [z for z in prof if not z[4]]
    s_a1 = arclen(trunk)[-1]
    s_edge = min(z[0] for z in off)
    z_hold = z_top + Z_CR_TOP

    def off_ok(s_e):
        for s, q, nd, _, _ in off:
            z = z_hold if s <= s_e else z_hold * (s_a1 - s) / (s_a1 - s_e)
            if nd > 0 and z + 1e-9 < nd + RISER_MARGIN:
                return False
        return True
    lo_, hi_ = s_edge, s_a1 - 0.01
    for _ in range(40):
        mid = 0.5 * (lo_ + hi_)
        if off_ok(mid):
            hi_ = mid
        else:
            lo_ = mid
    s_e = hi_
    q_e = [z[1] for z in off if z[0] >= s_e][0]
    out("  off the CR (information; the support stays TODO(design: T-A-06 dry fit)): held at %.3f mm above the MB from "
        "the tab Y +x edge, a straight descent to the MB top at A1 meets the requirement + %.2f mm when the support "
        "reaches (%.2f, %.2f) (%.1f mm along the trunk past the CR edge)."
        % (z_hold, RISER_MARGIN, q_e[0], q_e[1], s_e - s_edge))
    # ---- H.23(t) stacking
    out("")
    w5 = [(40.75, 46.83), P["F1"], P["F2"], P["S3"], P["F3"], P["F4"], P["A1R"]]
    w5s = sample_path(w5, 0.1)
    s_trunk = [(s, q) for s, q in smp]

    def trunk_bottom(s, q):
        if pip(q[0], q[1], OUTLINE):
            if q[0] < 25.81 and q[1] < P["T1"][1]:
                return Z_CR_TOP
            return Z_CR_TOP + z_built(s, q)
        return z_hold if s <= s_e else z_hold * (s_a1 - s) / (s_a1 - s_e)
    full_trunk = [P["T0"], P["J67"], P["T1"]] + trunk[1:]
    s_full = sample_path(full_trunk, 0.1)
    off0 = arclen(full_trunk)[2]
    ov_rows = []
    for s, q in w5s:
        best = None
        for st, qt in s_full:
            d = math.hypot(q[0] - qt[0], q[1] - qt[1])
            if best is None or d < best[0]:
                best = (d, st, qt)
        d, st, qt = best
        overlap = d < RIBBON_W / 2 + h_new
        zt = trunk_bottom(st - off0, qt) if st >= off0 else Z_CR_TOP
        own = z_need(q, RIBBON_W / 2)[0]
        fold = Z_CR_TOP + W5_FOLD if s < arclen(w5)[-1] - 1e-9 else 0.0
        zb = max(fold, own, zt + tb if overlap else 0.0)
        ov_rows.append((s, q, overlap, zt, zt + tb if overlap else None, own, zb))
    ovs = [r for r in ov_rows if r[2] and r[1][1] >= P["T0"][1] - 1e-9]
    first_ride = next((r for r in ov_rows if r[2] and r[4] is not None and r[4] > Z_CR_TOP + W5_FOLD), None)
    top = max(r[6] for r in ov_rows) + RIB_T
    top_r = max(ov_rows, key=lambda r: r[6])
    ctl = [(36.5, 71.10), (41.5, 71.10), (44.0, 71.10)]
    out("H.23(t) W5 / trunk stacking (r8, CHG-R1-W01): the W5 ribbon (%.2f mm wide, %.1f mm thick ASSUMPTION) overlaps "
        "the trunk (round bundle %.3f mm) in plan from the trunk start y %.2f (T0) on the x 25.80 run to A1 (%d of %d W5 "
        "samples). Below the "
        "riser the trunk top (%.3f mm above the MB) lies under the W5 fold (%.3f mm), so W5 is ABOVE the trunk there. "
        "DECISION: W5 stays above the trunk over the whole overlap and rests on the trunk top, bonded by RTV (the B3/S3 "
        "union spot carries both); W5 bottom = max(fold %.3f, own 3-D requirement, trunk bottom + T_b)."
        % (RIBBON_W, RIB_T, tb, P["T0"][1], len(ovs), len(ov_rows),
           Z_CR_TOP + tb, Z_CR_TOP + W5_FOLD, Z_CR_TOP + W5_FOLD))
    if first_ride:
        out("  W5 first rides on the trunk at (%.2f, %.2f), where the trunk top passes the fold height" %
            (first_ride[1][0], first_ride[1][1]))
    out("  heights above the MB (trunk bottom / trunk top / W5 bottom / W5 top): at the B3 level (tab Y) %.3f / %.3f "
        "/ %.3f / %.3f mm; stack top %.3f mm at (%.2f, %.2f) (%.3f mm above the CR top); W5 own requirement >= %.2f mm is "
        "met with %.3f mm margin. The r7 figures (trunk >= 14.41, W5 >= 15.00 mm) assumed no overlap."
        % (Z_CR_TOP + z_top, Z_CR_TOP + z_top + tb, Z_CR_TOP + z_top + tb, Z_CR_TOP + z_top + tb + RIB_T, top,
           top_r[1][0], top_r[1][1], top - Z_CR_TOP, max(r[5] for r in ov_rows),
           min(r[6] - r[5] for r in ov_rows if r[5] > 0)))
    for qc in ctl:
        st = min(s_trunk, key=lambda z: math.hypot(z[1][0] - qc[0], z[1][1] - qc[1]))
        zb_ = trunk_bottom(st[0], st[1])
        out("    controlling point (%.2f, %.2f): requirement %.3f mm, trunk bottom %.3f mm, W5 bottom %.3f mm above the MB"
            % (qc[0], qc[1], z_need(qc, h_new)[0], zb_, zb_ + tb))
    EXTRA["st"] = dict(z_top=z_top, m=m, y0=y0, za=za)
    EXTRA["t"] = dict(ov_rows=ov_rows, first_ride=first_ride, rx=rx, h=h_new, tb=tb, z_top=z_top)   # revision 7
    RJ["s"] = dict(h_trunk=f2(h_new), T_b=f2(tb), onset=(f2(onset[1][1]), f2(s_b1 - onset[0])),
                   max_req_above_cr=f2(mx_cr[2] - Z_CR_TOP), b3_height=f2(z_top), slope_deg=deg, toe_y=y0, apex=f2(za),
                   block=(rx[0], y0, rx[1], RISER_Y_END), block_area=f2(a_blk), min_margin=f2(mn[0]),
                   checkpoints=[(f2(ds), f2(rq), f2(bt)) for ds, _, rq, bt in pts_ctl],
                   min_at=mn[1], bead={k: (f2(v[0]), f2(v[1])) for k, v in bead.items()}, free_span=f2(span),
                   interior_U=f2(100 * a_int / RJ["e2"]["areas"]["interior"]), off_support_end=q_e,
                   options=[(dd, f2(mm), y_) for dd, mm, y_, _ in opts])
    RJ["t"] = dict(order="W5 above the trunk", stack_top=f2(top), stack_top_at=top_r[1], trunk_top_plateau=f2(
        Z_CR_TOP + z_top + tb), w5_bottom_plateau=f2(Z_CR_TOP + z_top + tb))
    summ("B1 riser B1R (r8, CHG-R1-D03)", "machined insulating wedge at %.0f deg, x %.2f-%.2f, y %.2f-%.2f, apex %.2f mm; "
         "leads leave the copper at the toe y %.2f; B3 post %.1f mm above the CR top; full CR profile margin >= %.3f mm "
         "(design margin %.2f); bonded jacket >= %.2f mm per lead" % (deg, rx[0], rx[1], y0, RISER_Y_END, za, y0, z_top,
                                                                     mn[0], RISER_MARGIN,
                                                                     min(v[1] for v in bead.values())),
         "H.23(s)")
    summ("W5 / trunk stacking (r8, CHG-R1-W01)", "W5 above the trunk, resting on it; trunk round bundle %.3f mm; heights "
         "on tab Y trunk %.3f-%.3f, W5 %.3f-%.3f mm above the MB; stack top %.3f mm" %
         (tb, Z_CR_TOP + z_top, Z_CR_TOP + z_top + tb, Z_CR_TOP + z_top + tb, Z_CR_TOP + z_top + tb + RIB_T, top),
         "H.23(t)")


# H.23(u) EVM-to-CR distances; H.23(v) E8 pickup; H.23(w) closing-pass hand figures (CHG-R1-07)
def sec_u_v_w():
    head("H.23(u) EVM points of the E leads to the r7 CR outline at the H.23(l) reference placement (r8, CHG-R1-07)")
    X0, Y0 = EVM_RIGHT - EVM_W, MB_OUTLINE[3] + G_J8
    out("Board point = (X0 + x_EVM, Y0 + y_EVM) with X0 = EVM_RIGHT - EVM_W = %.3f, Y0 = MB +y edge + g = %.3f (H.23(l)); "
        "EVM points: round4/work/evm_geometry.md Table 1 (vector); distance = plan distance to the nearest point of the "
        "r7 outline (H.23(a)); the r7-superseded basis was the tab X top edge." % (X0, Y0))
    dist = {}
    for e, (row, pt) in sorted(E_ROWS.items(), key=lambda kv: kv[1][0]):
        p = EVM_PTS[pt]
        b = (X0 + p[0], Y0 + p[1])
        best = None
        for (a, c) in edges(OUTLINE):
            dx, dy = c[0] - a[0], c[1] - a[1]
            t = max(0.0, min(1.0, ((b[0] - a[0]) * dx + (b[1] - a[1]) * dy) / (dx * dx + dy * dy)))
            qn = (a[0] + t * dx, a[1] + t * dy)
            d = math.hypot(b[0] - qn[0], b[1] - qn[1])
            if best is None or d < best[0]:
                best = (d, qn)
        d_tx = dpt_seg(b[0], b[1], TAB_X[0], TAB_X[3], TAB_X[2], TAB_X[3])
        dist[e] = (best[0], best[1], b, d_tx)
        out("  %-3s %-28s EVM (%.3f, %.3f) -> board (%.3f, %.3f): %.3f mm to the r7 outline at (%.2f, %.2f); to the tab X "
            "top edge %.3f mm" % (e, pt, p[0], p[1], b[0], b[1], best[0], best[1][0], best[1][1], d_tx))
    d_evm = Y0 - max(v[1] for v in OUTLINE)
    lo = min(dist.items(), key=lambda kv: kv[1][0])
    hi = max(dist.items(), key=lambda kv: kv[1][0])
    oth = [v[0] for k, v in dist.items() if k != "E1"]
    out("  range %.1f-%.1f mm (%s %.1f ... %s %.1f); without E1 %.1f-%.1f mm; EVM board edge to the CR %.2f mm (y %.3f "
        "- the tab Y +y edge %.2f)" % (lo[1][0], hi[1][0], lo[0], lo[1][0], hi[0], hi[1][0], min(oth), max(oth), d_evm,
                                      Y0, max(v[1] for v in OUTLINE)))
    RJ["u"] = {e: dict(board=(f2(v[2][0]), f2(v[2][1])), d=f2(v[0]), at=(f2(v[1][0]), f2(v[1][1])), d_tabx=f2(v[3]))
               for e, v in dist.items()}
    summ("EVM-to-CR distances (r8, CHG-R1-07)", ", ".join("%s %.1f" % (e, dist[e][0]) for e in
                                                         sorted(dist, key=lambda k: dist[k][0])) +
         " mm; EVM edge %.2f mm" % d_evm, "H.23(u)")
    # ---- H.23(v)
    head("H.23(v) E8 pickup through the E1/E8/C205 loop current, with and without R276 (r8, CHG-R1-07)")
    l8 = 0.020
    L8 = (MU0 / (2 * math.pi)) * l8 * (math.log(2 * l8 / A28) - 0.75)
    L8_hf = (MU0 / (2 * math.pi)) * l8 * (math.log(2 * l8 / A28) - 1.0)
    out("E8 partial self-inductance at its 20 mm maximum, 28 AWG radius %.2f mm: (mu0/2pi) l (ln(2l/a) - 3/4) = %.2f nH "
        "(DC, internal included; %.2f nH with -1, no internal). Loop current at the drive frequency f: |I| = V_r / |R + "
        "jwL + 1/(jwC205)| with L, R of H.23(k); E8 drop = |I| x |R_E8 + jw L_E8| (R_E8 = 28 AWG x 20 mm). Ripple V_r = "
        "10 mV at TP27 (the TP27 amplitude is not specified, TODO(verify: SLUUCB5E/SLUSDV2C))." % (A28 * 1e3, L8 * 1e9,
                                                                                                L8_hf * 1e9))
    r_e8 = R28 * l8
    rows = []
    for Lmm in (85.0, 90.0):
        Lm = Lmm * 1e-3
        Ll = loop_L(Lm, 5e-3)
        f0 = 1 / (2 * math.pi * math.sqrt(Ll * C205))
        dlt, kac, _ = skin(f0)
        for rlab, rl in (("DC, return l", R28 * 2 * Lm + ESR205), ("DC, E8 20 mm", R28 * (Lm + 0.020) + ESR205),
                         ("AC, return l", R28 * 2 * Lm * kac + ESR205), ("AC, E8 20 mm", R28 * (Lm + 0.020) * kac + ESR205)):
            for f, flab in ((f0, "f0"), (1.5e6, "1.5 MHz")):
                w = 2 * math.pi * f
                for r276, lab276 in ((0.0, "no R276"), (R276, "R276")):
                    z = complex(rl + r276, w * Ll - 1 / (w * C205))
                    i = 0.010 / abs(z)
                    v8 = i * abs(complex(r_e8, w * L8))
                    vc = 0.010 * abs(1 / complex(0, w * C205)) / abs(z)
                    rows.append((Lmm, rlab, flab, lab276, f, i, v8, vc / 0.010))
    nr_f0 = [r for r in rows if r[3] == "no R276" and r[2] == "f0"]
    wr_f0 = [r for r in rows if r[3] == "R276" and r[2] == "f0"]
    nr_15 = [r for r in rows if r[3] == "no R276" and r[2] == "1.5 MHz"]
    wr_15 = [r for r in rows if r[3] == "R276" and r[2] == "1.5 MHz"]
    for lab, rr in (("without R276 at f0", nr_f0), ("with R276 at f0", wr_f0), ("without R276 at 1.5 MHz", nr_15),
                    ("with R276 at 1.5 MHz", wr_15)):
        out("  %-24s E8 drop per 10 mV: %s; C205/TP27 ratio %s"
            % (lab, ", ".join("%.0f mm %s %.3f mV" % (r[0], r[1], r[6] * 1e3) for r in rr),
               ", ".join("%.3f" % r[7] for r in rr)))
    rng_nr = (min(r[6] for r in nr_f0), max(r[6] for r in nr_f0))
    rng_dc = [r[6] for r in nr_f0 if r[1] == "AC, return l" and r[0] == 90.0] + \
             [r[6] for r in nr_f0 if r[1] == "DC, return l" and r[0] == 85.0]
    wr = max(r[6] for r in wr_f0)
    ratio_nr = (min(r[7] for r in nr_15), max(r[7] for r in nr_15))
    ratio_nr_t = (min(r[7] for r in nr_15 if "return l" in r[1]), max(r[7] for r in nr_15 if "return l" in r[1]))
    tp27_max = 4.8e-3 / (wr / 0.010)
    out("  DOC A.5 / T-C-16 figures: undamped 20-31 mV per 10 mV = %.1f mV (90 mm, AC, return l) to %.1f mV (85 mm, DC, "
        "return l) (full set %.1f-%.1f mV); damped %.3f mV per 10 mV (the A.5 '0.17 mV'; the hand formula 10 mV x 2 pi "
        "f0 L_E8 / 10 ohm gives %.4f mV at 90 mm); C205/TP27 at 1.5 MHz without R276 %.2f-%.2f (two-wire return; %.2f-%.2f "
        "over the full set; T-C-16 '7.8-8.8'); with R276 the T-C-16 4.8 mV limit is met for a TP27 ripple up to %.0f mV "
        "(the T-C-16 'about 280 mV')."
        % (rng_dc[0] * 1e3, rng_dc[1] * 1e3, rng_nr[0] * 1e3, rng_nr[1] * 1e3, wr * 1e3,
           0.010 * 2 * math.pi * rr_f0(90.0) * L8 / R276 * 1e3, ratio_nr_t[0], ratio_nr_t[1], ratio_nr[0], ratio_nr[1],
           tp27_max * 1e3))
    RJ["v"] = dict(L8_nH=f2(L8 * 1e9), undamped_mV=(f2(rng_nr[0] * 1e3), f2(rng_nr[1] * 1e3)),
                   undamped_A5_mV=(f2(rng_dc[0] * 1e3), f2(rng_dc[1] * 1e3)), damped_mV=f2(wr * 1e3),
                   ratio_bridged=(f2(ratio_nr_t[0]), f2(ratio_nr_t[1])), tp27_max_mV=f2(tp27_max * 1e3),
                   rows=[(r[0], r[1], r[2], r[3], f2(r[6] * 1e3), f2(r[7])) for r in rows])
    summ("E8 pickup (r8, CHG-R1-07)", "L_E8 %.2f nH; per 10 mV REGN ripple at f0: %.1f-%.1f mV without R276 (A.5 basis "
         "%.1f-%.1f), %.3f mV with R276; C205/TP27 bridged %.2f-%.2f at 1.5 MHz; TP27 <= %.0f mV for the 4.8 mV limit"
         % (L8 * 1e9, rng_nr[0] * 1e3, rng_nr[1] * 1e3, rng_dc[0] * 1e3, rng_dc[1] * 1e3, wr * 1e3, ratio_nr_t[0],
            ratio_nr_t[1], tp27_max * 1e3), "H.23(v)")
    # ---- H.23(w)
    head("H.23(w) closing-pass hand figures recomputed (r8, CHG-R1-07); each DOC citation becomes this section")
    P = WP
    trunk = [P["T1"], P["B1"], P["T2"], P["T3"], P["B3"], P["T4"], P["T5"], P["T6"], P["A1"]]
    sl = arclen(trunk)
    s_b1 = sl[1]

    def at_s(s):
        for i in range(len(trunk) - 1):
            if sl[i] - 1e-9 <= s <= sl[i + 1] + 1e-9:
                t = (s - sl[i]) / (sl[i + 1] - sl[i])
                return (trunk[i][0] + t * (trunk[i + 1][0] - trunk[i][0]),
                        trunk[i][1] + t * (trunk[i + 1][1] - trunk[i][1]))
    z_b1 = z_need(P["B1"], H_TRUNK)[0] - Z_CR_TOP
    q267 = at_s(s_b1 + 2.67)
    z267 = z_need(q267, H_TRUNK)[0] - Z_CR_TOP
    s756 = s_b1
    while z_need(at_s(s756), H_TRUNK)[0] - Z_CR_TOP < 7.555 and s756 < sl[2]:
        s756 += 0.005
    out("  (1) r7 requirement on the trunk (r7 half-width %.3f mm): %.3f mm above the CR top at B1; %.3f mm at %.2f mm "
        "past B1 (%.2f, %.2f); 7.555 mm is reached %.3f mm past B1 (DOC A.3 '7.56 mm only 2.7 mm past B1')"
        % (H_TRUNK, z_b1, z267, 2.67, q267[0], q267[1], s756 - s_b1))
    s_b3 = sl[4]
    s_a1 = sl[-1]
    x415 = s_b3 + math.hypot(P["T4"][0] - P["B3"][0], P["T4"][1] - P["B3"][1]) + (41.5 - P["T4"][0])
    z_line = 14.41 * (s_a1 - x415) / (s_a1 - s_b3)
    z_req415 = z_need((41.5, 71.10), H_TRUNK)[0]
    out("  (2) a lead straight from 14.41 mm above the MB at B3 to the MB top at A1 (%.3f mm along the path): at x 41.5 "
        "(%.3f mm past B3) it stands %.3f mm above the MB against the %.3f mm requirement (DOC A.3 'about 10.8 mm "
        "against 13.45 mm')" % (s_a1 - s_b3, x415 - s_b3, z_line, z_req415))
    ce = RJ["m"]["cutouts_enlarged"]
    web = (ce["C-D12"]["rect"][0] - ce["D-BT-SQ"]["rect"][2], ce["D-BT-SQ"]["rect"][2], ce["C-D12"]["rect"][0])
    out("  (3) web between the two merged cut-out openings = C-D12 x0 - D-BT-SQ x1 = %.3f - %.3f = %.3f mm (H.23(m) "
        "enlarged cut-outs; DOC A.7 '0.625 mm')" % (web[2], web[1], web[0]))
    a_ty = RJ["e2"]["areas"]["tab Y"]
    gates9 = 6 * CY_PKG["SSOP-8"] + 3 * CY_PKG["SC70-6"]
    ov = ANCHOR_FP * max(0.0, ANCHOR_FP - abs(P["S3"][1] - P["B3"][1]))
    u_b3s3 = 2 * ANCHOR_FP ** 2 - ov
    dec = 9 * CY_PKG["0603"]
    out("  (4) tab Y top %.3f mm2: nine LVC gates %.1f mm2 (6 SSOP-8 x %.1f + 3 SC70-6 x %.1f) + the B3/S3 union %.2f mm2 "
        "= %.2f mm2 = %.1f %% (DOC '82.6 %%'); nine gates + nine 0603 decouplers (%.2f mm2) = %.2f mm2 = %.1f %% (DOC "
        "'150.2 of 153.7 mm2', the r7-superseded 97.7 %%)" % (a_ty, gates9, CY_PKG["SSOP-8"], CY_PKG["SC70-6"], u_b3s3,
                                                          gates9 + u_b3s3, 100 * (gates9 + u_b3s3) / a_ty, dec,
                                                          gates9 + dec, 100 * (gates9 + dec) / a_ty))
    pu = RJ["i"]["pulls"]["tabs"]
    out("  (5) T-A-09 pull, tip-load basis (H.23(i)): 1 x the 30 g stress at %.3f N (tab Y, FT2) / %.3f N (tab X, FT1); "
        "a 2 N pull = %.2f x (FT2) / %.2f x (FT1) (linear in the pull; DOC 'about 4.8 x' at FT2)"
        % (pu["tab Y"]["W30_N"], pu["tab X"]["W30_N"], 2.0 / pu["tab Y"]["W30_N"], 2.0 / pu["tab X"]["W30_N"]))
    c102b_h = 2.5
    out("  (6) W5 over C102b at the J101 fold: fold height %.1f mm above the CR top - C102b body %.1f mm (ASSUMPTION, "
        "TODO(verify: C102b datasheet), MS3 caliper) = %.1f mm (DOC '>= 5.5 mm'); plan offset 0.775 mm (H.23(l))"
        % (W5_FOLD, c102b_h, W5_FOLD - c102b_h))
    f12, f24 = (55.88, 64.02), (55.88, 66.56)
    m11, m24 = TAPS["T11"][2], TAPS["F24"][2]
    t11_0, t11_1 = math.hypot(f12[0] - m11[0], f12[1] - m11[1]), math.hypot(f24[0] - m11[0], f24[1] - m11[1])
    f24_0, f24_1 = math.hypot(f24[0] - m24[0], f24[1] - m24[1]), math.hypot(f12[0] - m24[0], f12[1] - m24[1])
    d1, d0 = t11_1, t11_0
    out("  (7) F12/F24 swap (T11 to (55.88, 66.56), F24 to (55.88, 64.02)): T11 straight %.3f -> %.3f mm, change %.3f mm "
        "on the 20-tap sum (SUM20 holds T11, not F24; DOC J.2 item 63 '-0.14 mm'); F24 (option, outside the sum) %.3f -> "
        "%.3f mm" % (t11_0, t11_1, t11_1 - t11_0, f24_0, f24_1))
    RJ["w"] = dict(z_b1=f2(z_b1), z_267=f2(z267), s_7555=f2(s756 - s_b1), line_415=f2(z_line), req_415=f2(z_req415),
                   web=f2(web[0]), tab_y_b3s3=f2(100 * (gates9 + u_b3s3) / a_ty), tab_y_dec=f2(gates9 + dec),
                   pull_2N=(f2(2.0 / pu["tab Y"]["W30_N"]), f2(2.0 / pu["tab X"]["W30_N"])),
                   c102b=W5_FOLD - c102b_h, swap=f2(d1 - d0))
    summ("closing-pass hand figures (r8, CHG-R1-07)", "B1 %.3f / +2.67 mm %.3f mm above the CR top; straight B3-A1 lead "
         "%.2f vs %.2f mm at x 41.5; web %.3f mm; tab Y %.1f %% / %.1f mm2; 2 N pull %.2f x at FT2; W5 over C102b %.1f mm; "
         "F12/F24 swap %.3f mm" % (z_b1, z267, z_line, z_req415, web[0], 100 * (gates9 + u_b3s3) / a_ty, gates9 + dec,
                                   2.0 / pu["tab Y"]["W30_N"], W5_FOLD - c102b_h, d1 - d0), "H.23(w)")


# ======================================================================================================================
# Revision 6 (r8 integration): H.23(x), the integrator's derived figures. The sections above are unchanged.
# ======================================================================================================================
TW_HB_MAX = 47e-3        # s, DOC FR-08 / H.17: U113 width, firmware constant TW_HB_MAX, provisional until T-C-10
STEP8B_MAX = 70e-3       # s, DOC F.5 T1 step 8b (r7): the heartbeat exercise with QUAL HIGH, <= 70 ms
STEP8C_P33 = 5e-3        # s, DOC F.5 T1 step 8c (r8): pin 33 LOW within 5 ms of the P5 rise
VCHG_PROBE = 3.0         # V, DOC FR-12(b3): the Idle probe waits for V_chg < 3 V
VCHG_STUCK = 12.0        # V, DOC FR-12(b1): r8 proposed stuck-path threshold
B1_DWELL = 0.5           # s, DOC FR-12(b1): both EN readbacks LOW for >= 0.5 s


def sec_x():
    head("H.23(x) r8 integration figures derived from H.23(n), (o) and (q) (r8, CHG-R1-D02, CHG-R1-02, CHG-R1-04, "
         "CHG-R1-01)")
    r_par = 1 / (1 / R_DIV38 + 1 / R_UVOV)
    tau_max = C_VCHGIN[1] * r_par
    t_b2 = B1_DWELL + tau_max * math.log(VCHG_STUCK / VCHG_PROBE)
    out("  (1) FR-12(b2) discharge timeout: worst case after (b1) = %.1f s dwell + tau_max x ln(%.0f/%.0f), tau_max = "
        "%.1f uF x %.1f kOhm = %.3f s (UNBIASED, the H.23(q) maximum): %.3f s; the FR-12(b2) 5 s timeout lies %.2f s above it"
        % (B1_DWELL, VCHG_STUCK, VCHG_PROBE, C_VCHGIN[1] * 1e6, r_par / 1e3, tau_max, t_b2, 5.0 - t_b2))
    sums = {}
    for f in (100e3, 400e3):
        bits = [i2c_bits_read(2), i2c_bits_read(2), i2c_bits_read(1), i2c_bits_read(2)]
        sums[f] = (sum(bits) / f, sum(bits) / f + 4 * I2C_TBUF[f])
    out("  (2) FR-46 four field reads (REG01:02, REG03:04, REG05, REG06:07) in sum: %.3f ms at 100 kHz (%.3f ms with four "
        "t_BUF), %.3f ms at 400 kHz (%.3f ms with four t_BUF): the T1 step-8c pre-edge read bound '<= 1.83 ms at 100 kHz'"
        % (sums[100e3][0] * 1e3, sums[100e3][1] * 1e3, sums[400e3][0] * 1e3, sums[400e3][1] * 1e3))
    hb = TW_HB_MAX * 1.1
    inc = hb + STEP8B_MAX + STEP8C_P33
    out("  (3) T1 arming increment (A-03): step-8 heartbeat pause TW_HB_MAX x 1.1 = %.1f ms + step 8b <= %.0f ms + step 8c "
        "pin-33 release <= %.0f ms = %.1f ms (the F.5 '~0.13 s')" % (hb * 1e3, STEP8B_MAX * 1e3, STEP8C_P33 * 1e3, inc * 1e3))
    i_pu = V_IO_RNG[2] / R_PU35[0]
    out("  (4) T-C-05c pad pull-up current with FLT released and pin 30 LOW: 3V3 max %.3f V into the %.0f kOhm minimum "
        "pull-up = %.3f mA (the T-C-05c bound '<= 0.35 mA'); with FLT asserted the pull-up current is the H.23(n) "
        "<= 0.288 mA" % (V_IO_RNG[2], R_PU35[0] / 1e3, i_pu * 1e3))
    out("  (5) not computed here: the R106s 0402 courtyard in the tab X bottom booking and its bottom-clearance check "
        "(H.23(d)/(e) re-run with R106s placed; TODO(calc); the T-A-06 DRC is the gate)")
    RJ["x"] = dict(t_b2_s=f2(t_b2), tau_max_s=f2(tau_max), four_reads_ms={"100k": f2(sums[100e3][0] * 1e3),
                   "400k": f2(sums[400e3][0] * 1e3)}, t1_increment_ms=f2(inc * 1e3), tc05c_pullup_mA=f2(i_pu * 1e3))
    summ("r8 integration figures (rev 6)", "FR-12(b2) worst %.2f s vs 5 s; four field reads %.2f / %.2f ms; T1 increment "
         "%.0f ms; T-C-05c pull-up %.3f mA" % (t_b2, sums[100e3][0] * 1e3, sums[400e3][0] * 1e3, inc * 1e3, i_pu * 1e3),
         "H.23(x)")


# ======================================================================================================================
# Revision 7 (r8 verification round): H.23(y). The sections above print the same lines (wording-only changes in H.23(p)
# and H.23(q), see the module docstring).
# ======================================================================================================================
VIH_FRAC = 0.70          # x OVDD, i.MX RT1062 GPIO VIH ASSUMPTION; TODO(verify: IMXRT1060CEC)


def in_spike_lead_off(v0, cs, lin, cin, rin=0.045, ron=0.031, cout=1.0e-6, lout=0.15e-6, dt=1e-9, tend=12e-6):
    """The in_spike model unchanged; returns the OUT-lead (W1/W2) current at the instant the FET opens."""
    vs, vin, vout = v0, v0, v0
    i_in, i_out = 0.0, 0.0
    t, t_cross, on, i_lead_off = 0.0, None, True, None
    while t < tend and i_lead_off is None:
        di_in = (vs - i_in * rin - vin) / lin
        i_in += di_in * dt
        i_fet = (vin - vout) / ron if on else 0.0
        i_out += vout / lout * dt
        vs -= i_in / cs * dt
        vin += (i_in - i_fet) / cin * dt
        vout += (i_fet - i_out) / cout * dt
        if on and t_cross is None and i_fet > 45.0:
            t_cross = t
        if on and t_cross is not None and t >= t_cross + 1e-6:
            i_lead_off = (i_out, t, vout)
        t += dt
    return i_lead_off


def sec_y():
    head("H.23(y) r8 verification-round figures (r8, calc revision 7; CHG-R1-01, -02, -D04, -D03, -W01, -07, -04)")
    # (1) F17-F15 node, FLT asserted, U108 H2C HIGH
    def node(v, r127, rpu, rflt_path):
        g1, g2, g3 = 1 / r127, 1 / rpu, 1 / rflt_path
        return v * (g1 + g2) / (g1 + g2 + g3)
    n_min = node(V_IO_RNG[0], R127_R[2], R_PU35[2], R106S[0] + R_FLT[0])
    n_max = node(V_IO_RNG[2], R127_R[0], R_PU35[0], R106S[2] + R_FLT[2])
    n_r7 = node(V_IO_RNG[2], R127_R[0], R_PU35[0], R_FLT[2])
    vil = (VIL_FRAC * V_IO_RNG[0], VIL_FRAC * V_IO_RNG[2])
    vih = (VIH_FRAC * V_IO_RNG[0], VIH_FRAC * V_IO_RNG[2])
    out("  (1) bridge F17-F15 with FLT asserted and U108 H2C HIGH (CHG-R1-01): the node is U108 -> R127 -> node -> R106s + "
        "R(FLT) -> GND with the pin-35 pull-up to 3V3 (U108 output resistance 0 ohm ASSUMPTION): %.2f V minimum (3V3 %.3f V, "
        "R127 %.0f ohm, pull-up %.0f kOhm, R106s %.0f + R(FLT) %.0f ohm) to %.2f V maximum (3V3 %.3f V, R127 %.0f ohm, "
        "pull-up %.0f kOhm, R106s %.0f + R(FLT) %.0f ohm), inside the undefined band between VIL %.2f-%.2f V and VIH "
        "%.2f-%.2f V (VIL %.2f / VIH %.2f x 3V3, ASSUMPTIONs): pins 35 and 16 can read either level. r7 (no R106s): <= "
        "%.3f V, a defined LOW. With FLT released both pins read the U108 level."
        % (n_min, V_IO_RNG[0], R127_R[2], R_PU35[2] / 1e3, R106S[0], R_FLT[0], n_max, V_IO_RNG[2], R127_R[0],
           R_PU35[0] / 1e3, R106S[2], R_FLT[2], vil[0], vil[1], vih[0], vih[1], VIL_FRAC, VIH_FRAC, n_r7))
    # (2) T3 FIFO case
    fifo = {}
    for f in (100e3, 400e3):
        tb, cap = I2C_TBUF[f], I2C_CAP[f]
        w2, w3, r2 = i2c_bits_write(2) / f, i2c_bits_write(3) / f, i2c_bits_read(2) / f
        t_fifo = cap + tb + r2 + tb + r2 + tb + w2 + tb + w3
        inflight = max(w3, 10 / f)
        fifo[f] = (t_fifo, inflight, cap)
    out("  (2) T3 raise behind one FR-41(iii) ramp group (CHG-R1-02): a ramp write in flight (the FR-07 cap term) and its "
        "two FR-46 field reads R(REG01:02), R(REG06:07) queued ahead of the raise, FIFO order: edge to write complete %.3f ms "
        "at 100 kHz (MISSES the 1.5 ms FR-07 deadline by %.3f ms), %.3f ms at 400 kHz. With the FR-07 r8 queue-priority "
        "rule (a posted raise is serviced before every queued transaction that has not started; an in-flight read aborts at "
        "the next byte boundary; an in-flight write completes), the in-flight term is max(W(REG03-05), one byte + STOP) = "
        "%.3f ms at 100 kHz / %.3f ms at 400 kHz, inside the %.2f / %.2f ms cap term of H.23(o), so the published 1.359 / "
        "0.565 ms hold only with that rule."
        % (fifo[100e3][0] * 1e3, (fifo[100e3][0] - FR07_DEADLINE) * 1e3, fifo[400e3][0] * 1e3, fifo[100e3][1] * 1e3,
           fifo[400e3][1] * 1e3, fifo[100e3][2] * 1e3, fifo[400e3][2] * 1e3))
    # (3) W1/W2 lead current at FET turn-off; helix factor at OD min
    rec = EXTRA["p"]
    a_hi = 5 * awg_d(32) / 2
    k_max = math.sqrt(1 + (math.pi * rec["rec_od"][1] / TWIST_P[0]) ** 2)
    k_min = math.sqrt(1 + (math.pi * rec["rec_od"][0] / TWIST_P[0]) ** 2)
    l_odmin = lprime(rec["rec_od"][0], a_hi) / k_min
    lo = in_spike_lead_off(22.0, 20e-6, 150e-9, 3.4e-6, lout=rec["lmin"] * W12_BUILD[0] / 1000.0)
    sp_odmin = spike_worst(l_odmin * W12_BUILD[0] / 1000.0)
    out("  (3) W1/W2 (CHG-R1-D04): at 290 mm and the L' minimum (V0 22 V, C_S 20 uF, L_IN 150 nH) the W1/W2 lead carries "
        "%.1f A when the FET opens (t = %.3f us, OUT %.2f V, unclamped model); the lead peak is the H.23(p) 130 A. Helix factor "
        "at OD max (the H.23(p) basis) %.4f, at OD min %.4f: L' minimum %.4f uH/m and IN peak %.2f V at 290 mm with k at OD "
        "min (H.23(p) %.4f uH/m, %.2f V; the H.23(p) basis is the conservative one)."
        % (lo[0], lo[1] * 1e6, lo[2], k_max, k_min, l_odmin * 1e6, sp_odmin[0], rec["lmin"] * 1e6,
           spike_worst(rec["lmin"] * W12_BUILD[0] / 1000.0)[0]))
    # (4) B1R lateral support
    tt = EXTRA["t"]
    rx, h = tt["rx"], tt["h"]
    ov_p, ov_m = 25.80 + h - rx[1], rx[0] - (25.80 - h)
    u_edge = rx[1] - 25.80
    z_edge = h - math.sqrt(h * h - u_edge * u_edge)
    out("  (4) B1R lateral support (CHG-R1-D03): face width %.2f mm (x %.2f-%.2f) against the trunk width 2 x %.3f = %.3f mm "
        "on x 25.80: support %.0f %% of the width; the trunk overhangs %.3f mm on +x and %.3f mm on -x. The H.23(s) profile "
        "check credits the whole trunk width with the face height at x 25.80. That holds for a cohesive round bundle whose "
        "lowest generatrix (x 25.80) lies on the face: its lower surface at lateral offset u stands h - sqrt(h^2 - u^2) above "
        "the face plane, %.4f mm at the +x face edge (u %.2f mm) and up to %.3f mm at the bundle edge, never below it. A lead "
        "that leaves the bundle past the +x edge is not supported: the trunk is bound into one bundle and bonded to the face "
        "from the toe to the apex (A.3 r8), and T-F-12 measures the lowest lead at the +x trunk edge."
        % (rx[1] - rx[0], rx[0], rx[1], h, 2 * h, 100 * (rx[1] - rx[0]) / (2 * h), ov_p, ov_m, z_edge, u_edge, h))
    # (5) W5 / trunk figures at the T-F-12 points
    rows = tt["ov_rows"]
    fr = tt["first_ride"]
    pre = [r for r in rows if r[2] and r[4] is not None and r[1][1] >= WP["T0"][1] - 1e-9 and fr is not None
           and r[0] < fr[0]]
    gaps = [r[6] - r[4] for r in pre]
    r73 = min(rows, key=lambda r: math.hypot(r[1][0] - 28.70, r[1][1] - 73.10))
    mrow = min((r for r in rows if r[5] > 0), key=lambda r: r[6] - r[5])
    tab_y_margin = Z_CR_TOP + tt["z_top"] + tt["tb"] - 15.00
    out("  (5) W5 / trunk (CHG-R1-W01): between the trunk start (y %.2f) and the ride point (%.2f, %.2f) W5 lies above the "
        "trunk with an air gap of %.3f-%.3f mm (%d samples), so it rests on the trunk only from the ride point to A1; W5 "
        "bottom at (%.2f, %.2f) (the T-F-12 point and the FT2 fill hole at (28.00, 73.25)): %.3f mm above the MB, on the "
        "trunk (fold height %.3f mm); the minimum W5 margin over its own requirement is %.3f mm at (%.2f, %.2f), where the "
        "requirement is %.3f mm and the W5 bottom %.3f mm above the MB; over tab Y the margin against the 15.00 mm r7 "
        "figure is %.3f mm (W5 bottom %.3f mm)."
        % (WP["T0"][1], fr[1][0], fr[1][1], min(gaps), max(gaps), len(gaps), r73[1][0], r73[1][1], r73[6],
           Z_CR_TOP + W5_FOLD, mrow[6] - mrow[5], mrow[1][0], mrow[1][1], mrow[5], mrow[6], tab_y_margin,
           Z_CR_TOP + tt["z_top"] + tt["tb"]))
    # (6) C205/TP27 sweep over the E1 build range
    best, band, sweep_pts = None, [], []
    l8 = 0.020
    f = 1.5e6
    w = 2 * math.pi * f
    nstep = int(round((90.0 - 70.8) / 0.1))
    for k in range(nstep + 1):
        Lmm = 70.8 + 0.1 * k
        Lm = Lmm * 1e-3
        Ll = loop_L(Lm, 5e-3)
        f0 = 1 / (2 * math.pi * math.sqrt(Ll * C205))
        _, kac, _ = skin(f0)
        mx = None
        for rlab, rl in (("DC, return l", R28 * 2 * Lm + ESR205), ("DC, E8 20 mm", R28 * (Lm + l8) + ESR205),
                         ("AC, return l", R28 * 2 * Lm * kac + ESR205), ("AC, E8 20 mm", R28 * (Lm + l8) * kac + ESR205)):
            z = complex(rl, w * Ll - 1 / (w * C205))
            ratio = abs(1 / complex(0, w * C205)) / abs(z)
            if mx is None or ratio > mx[0]:
                mx = (ratio, rlab)
        sweep_pts.append((Lmm, mx[0], mx[1]))
        if best is None or mx[0] > best[1]:
            best = (Lmm, mx[0], mx[1])
        if mx[0] > 17.80:
            band.append(Lmm)
    q_k = max(r[1] for r in sweep_pts)
    assert 25.0 <= best[1] <= 25.6, best
    picks = [p for p in sweep_pts if any(abs(p[0] - x) < 0.05 for x in (70.8, 75.0, 80.0, 85.0, 90.0))]
    # with R276 at 1.5 MHz, the E8 drop per 10 mV at 85/90 mm
    L8 = (MU0 / (2 * math.pi)) * l8 * (math.log(2 * l8 / A28) - 0.75)
    wr15 = 0.0
    for Lmm in (85.0, 90.0):
        Lm = Lmm * 1e-3
        Ll = loop_L(Lm, 5e-3)
        _, kac, _ = skin(1 / (2 * math.pi * math.sqrt(Ll * C205)))
        for rl in (R28 * 2 * Lm + ESR205, R28 * (Lm + l8) + ESR205, R28 * 2 * Lm * kac + ESR205,
                   R28 * (Lm + l8) * kac + ESR205):
            z = complex(rl + R276, w * Ll - 1 / (w * C205))
            wr15 = max(wr15, 0.010 / abs(z) * abs(complex(R28 * l8, w * L8)))
    out("  (6) C205/TP27 ratio without R276 at 1.5 MHz over the E1 build range 70.8-90 mm in 0.1 mm steps, maximum over the "
        "four return/resistance cases of H.23(v) (CHG-R1-07): %s; maximum %.2f at %.1f mm (%s; there f0 = 1.5 MHz); above "
        "17.80 for %s; the bound valid over the whole range is the H.23(k) undamped Q 25.6 (DC wire resistance, E8 return at "
        "20 mm), which the sweep maximum does not exceed; omit threshold 0.5 V p-p / 25.6 = %.1f mV p-p at TP27 (17.80 gives "
        "%.1f mV). With R276 at 1.5 MHz the E8 drop is <= %.4f mV per 10 mV, so the 4.8 mV limit holds for a TP27 ripple up "
        "to %.0f mV (the H.23(v) %s mV is the f0 basis)."
        % (", ".join("%.1f mm %.2f" % (p[0], p[1]) for p in picks), best[1], best[0], best[2],
           ("%.1f-%.1f mm" % (min(band), max(band))) if band else "no length", 500.0 / 25.6, 500.0 / 17.80,
           wr15 * 1e3, 4.8e-3 / (wr15 / 0.010) * 1e3, "273"))
    # (7) T1 increment with the step-8c pre-edge read
    rd100 = sum([i2c_bits_read(2), i2c_bits_read(2), i2c_bits_read(1), i2c_bits_read(2)]) / 100e3
    rd100b = rd100 + 4 * I2C_TBUF[100e3]
    inc = TW_HB_MAX * 1.1 + STEP8B_MAX + rd100b + STEP8C_P33
    out("  (7) T1 increment with every term (CHG-R1-04): step-8 pause %.1f ms + step 8b <= %.0f ms + step-8c pre-edge read "
        "%.3f ms at 100 kHz with four t_BUF + pin-33 release <= %.0f ms = %.1f ms (H.23(x) row (3) %.1f ms omitted the read); "
        "the T1 budget ~0.58-0.73 s is unchanged; the step-8c read bound is <= %.2f ms at 100 kHz."
        % (TW_HB_MAX * 1.1e3, STEP8B_MAX * 1e3, rd100b * 1e3, STEP8C_P33 * 1e3, inc * 1e3,
           (TW_HB_MAX * 1.1 + STEP8B_MAX + STEP8C_P33) * 1e3, math.ceil(rd100b * 1e5) / 1e2))
    RJ["y"] = dict(f17_f15_node_V=(f2(n_min), f2(n_max)), f17_f15_node_r7_V=f2(n_r7), vil=vil, vih=vih,
                   t3_fifo_ms={"100k": f2(fifo[100e3][0] * 1e3), "400k": f2(fifo[400e3][0] * 1e3)},
                   inflight_ms={"100k": f2(fifo[100e3][1] * 1e3), "400k": f2(fifo[400e3][1] * 1e3)},
                   lead_at_off_A=f2(lo[0]), k_odmax=f2(k_max), k_odmin=f2(k_min), in_peak_k_odmin=f2(sp_odmin[0]),
                   b1r_overhang_mm=(f2(ov_p), f2(ov_m)), b1r_support_frac=f2((rx[1] - rx[0]) / (2 * h)),
                   w5_gap_pre_ride_mm=(f2(min(gaps)), f2(max(gaps))), w5_at_28_70_73_10=f2(r73[6]),
                   w5_min_margin=(f2(mrow[6] - mrow[5]), mrow[1], f2(mrow[5])), w5_tab_y_margin=f2(tab_y_margin),
                   c205_sweep_max=(best[0], f2(best[1]), best[2]),
                   c205_band_over_17_80=(min(band), max(band)) if band else None,
                   tp27_limit_15MHz_mV=f2(4.8e-3 / (wr15 / 0.010) * 1e3), t1_increment_full_ms=f2(inc * 1e3))
    summ("r8 verification figures (rev 7)", "F17-F15 node %.2f-%.2f V (undefined band); T3 FIFO %.3f ms at 100 kHz; lead "
         "%.0f A at FET off; B1R support %.0f %% of the trunk width; W5 gap %.3f-%.3f mm before the ride point, %.3f mm at "
         "(28.70, 73.10); C205/TP27 max %.2f at %.1f mm; T1 increment %.1f ms"
         % (n_min, n_max, fifo[100e3][0] * 1e3, lo[0], 100 * (rx[1] - rx[0]) / (2 * h), min(gaps), max(gaps), r73[6],
            best[1], best[0], inc * 1e3), "H.23(y)")


def rr_f0(Lmm):
    return 1 / (2 * math.pi * math.sqrt(loop_L(Lmm * 1e-3, 5e-3) * C205))


def sec_r8():
    sec_n()
    sec_o()
    sec_p()
    sec_q()
    sec_r()
    sec_s_t()
    sec_u_v_w()
    sec_x()       # revision 6 (r8 integration): H.23(x)
    sec_y()       # revision 7 (r8 verification round): H.23(y)


# ======================================================================================================================
# main
# ======================================================================================================================
def main():
    out("r7_calc.py - H.23 of the r7 BQ25798EVM wiring design (round 4). BRD: %s" % os.path.relpath(BRD_PATH, REPO))
    out("Board coordinates mm, top view, +y up. ORDER-OF-MAGNITUDE labels apply to every resonance and pin-load figure.")
    sec_a()
    sec_b()
    sec_c()
    find_feet()
    sec_d()
    sec_e()
    sec_e2()
    sec_f()
    sec_g()
    sec_h()
    sec_i()
    sec_j()
    sec_k()
    sec_l()
    sec_m()
    sec_r8()      # revision 5 (r8): H.23(n)-(w)
    head("H.23 SUMMARY")
    for k, v, s in SUMMARY:
        out("  %-48s %s  [%s]" % (k, v, s))
    with open(OUT_TXT, "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(LINES) + "\n")
    RJ["summary"] = [dict(key=k, value=v, source=s) for k, v, s in SUMMARY]
    with open(OUT_JSON, "w") as f:
        json.dump(RJ, f, indent=1, default=lambda o: list(o) if isinstance(o, (set, tuple)) else str(o))


if __name__ == "__main__":
    main()
