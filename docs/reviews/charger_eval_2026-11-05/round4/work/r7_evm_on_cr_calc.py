#!/usr/bin/env python3
"""Round 4 (r7) proposal "EVM on carrier": every number in work/proposal_evm_on_cr.md.

Coordinates: Eagle .brd board coordinates, top view, origin = MB origin, +x right, +y UP, mm (design A.2).
EVM frame (work/evm_geometry.md): origin at the lower-left corner of the EVM outline, top view, +x right, +y up, mm.

Inputs (each one cited where it is used):
  - .brd 20260625 through mb_mech_calc.py (elements, L1/L16 polygons and wires, vias, height table with sources)
  - EVM points: work/evm_calc/evm_geom_out.txt (vector extraction of SLUUCB5E Figs 4-1..4-4)
  - area booking: round4/calc/stackup_area_out.txt (CR 1188 mm2 incl. pours, DNP 87 mm2, merged CR+EIB 1398 mm2,
    round-3 bottom set 435 mm2, U4 0.75)
  - pickup model and budgets: work/eib_merge_calc.py (dipole EMF formula, budgets E3 75 / E4 48 / E6 159 mV)
  - pin-load / resonance formulas: work/mb_pinload.py (eq. 2 and 3 of work/mb_mechanical.md)
Every ASSUMPTION is printed with its result. Nothing here is a measured value.
Run: /c/Users/ricky/miniforge3/python.exe -I r7_evm_on_cr_calc.py > r7_evm_on_cr_calc_out.txt   (from round4/work/)
"""
import math
import os
import sys

import numpy as np
from matplotlib.path import Path
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mb_mech_calc as M  # noqa: E402  (loads the .brd; prints nothing on import)

MB = (0.0, 0.0, 131.064, 98.044)          # .brd layer 20 outline (mb_neighbours_out.txt)
EVM = 88.90                               # SLUUCB5E outline (evm_geometry.md section 3)


def hdr(t):
    print("\n" + "=" * 118 + "\n" + t + "\n" + "=" * 118)


def ceil5(x):
    return 5 * math.ceil(x / 5.0 - 1e-9)


# ======================================================================================================================
# 1. Mezzanine check: can an 88.9 mm square EVM sit above the MB without covering a tall or unmeasured part?
# ======================================================================================================================
hdr("1. EVM as a mezzanine over the MB (plan check)")
tall = []
for e in M.ELS.values():
    h, src = M.height_of(e)
    if e["name"] == "CHG":
        continue
    if h is None or h >= 4.8:
        tall.append((e["name"], e["bbox"], h, src))
for n, b, h, s in sorted(tall, key=lambda r: r[1][0]):
    print("   %-7s x %6.2f-%6.2f  y %6.2f-%6.2f  h %s   [%s]" % (n, b[0], b[2], b[1], b[3],
                                                                  "%.2f mm" % h if h is not None else "unknown", s[:70]))
tb_right = max(M.ELS[n]["bbox"][2] for n in ("J-BL", "J-FC", "J-BT", "J-NTC"))
j1_left = M.ELS["J1"]["bbox"][0]
print("   free x-span between the terminal-block rear faces (x %.2f) and J1 (x %.2f): %.2f mm vs EVM %.2f mm"
      % (tb_right, j1_left, j1_left - tb_right, EVM))
yl, yh = min(M.ELS[n]["bbox"][1] for n in ("J1", "U$1")), max(M.ELS[n]["bbox"][3] for n in ("J1", "U$1"))
print("   J1 + U$1 (Teensy) span y %.2f-%.2f: MB depth outside it = %.2f mm (low side), %.2f mm (high side)"
      % (yl, yh, yl - MB[1], MB[3] - yh))
# grid search: fraction of the EVM plan over the MB while covering no part >= 13.9 mm or of unknown height
blk = [(n, b) for n, b, h, s in tall if h is None or h >= 13.9]
best = (0.0, None)
for X in np.arange(-EVM, MB[2] + 0.01, 0.5):
    for Y in np.arange(-EVM, MB[3] + 0.01, 0.5):
        ev = (X, Y, X + EVM, Y + EVM)
        if any(M.overlaps(ev, b) for _, b in blk):
            continue
        ox = max(0.0, min(ev[2], MB[2]) - max(ev[0], MB[0]))
        oy = max(0.0, min(ev[3], MB[3]) - max(ev[1], MB[1]))
        f = ox * oy / EVM ** 2
        if f > best[0]:
            best = (f, ev)
print("   best placement covering no TB005 block (21.70 mm), J-NTC (13.90 mm) or unmeasured J1/J2/J3/U$1: %.1f %% of the EVM"
      " over the MB, at x %.1f-%.1f, y %.1f-%.1f" % (100 * best[0], *[best[1][i] for i in (0, 2, 1, 3)]))
# height a mezzanine over J1/J2 must clear: receptacle + tap pin above it (TSW-101-07: body 2.54 + tail 2.54 above the
# receptacle top when the 5.84 mm post is inserted, Samtec F-226 as quoted in mb_mechanical.md Table 7)
print("   over J1/J2 the EVM underside must clear h_J1 + 5.08 mm (TSW-101-07 body + tail above the receptacle) + heat-shrink"
      " + wire bend; EVM top = that + 0.5 clearance + t_EVM (TODO, 1.6 assumed) + 13.0 (ED120 blocks, On-Shore) = h_J1 + 20.2 mm")

# ======================================================================================================================
# 2. The r7 outline (edge-reach ring around L-FC) and its area
# ======================================================================================================================
hdr("2. r7 CR outline: footprint + +y band + lane/strip around L-FC + head at the MB +y edge (+ optional tongue)")
LFC = M.ELS["L-FC"]["bbox"]
OPFC = M.ELS["OP-FC"]["bbox"]
print("   L-FC bbox x %.2f-%.2f y %.2f-%.2f (5.0 mm, Eaton listing, TODO(verify)); OP-FC x %.2f-%.2f y %.2f-%.2f (1.75 mm)"
      % (LFC[0], LFC[2], LFC[1], LFC[3], OPFC[0], OPFC[2], OPFC[1], OPFC[3]))
WIN = (LFC[0] - 0.5, LFC[1] - 0.5, LFC[2] + 0.5, LFC[3] + 0.5)     # window around L-FC, 0.5 mm plan clearance
XH0 = 10.0       # head left end: >= 6.7 mm from the MB fixing hole (3.3, 94.74) edge; hardware TODO(measure, M2)
YTOP = MB[3] - 0.5
REG = {
    "A footprint (r6)": (17.70, 34.14, 48.70, 67.14),
    "B +y band": (17.70, 67.14, 48.70, WIN[1]),
    "C lane (right of L-FC)": (WIN[2], WIN[1], 48.70, WIN[3]),
    "D strip (left of L-FC)": (17.70, WIN[1], WIN[0], WIN[3]),
    "E head (MB +y edge)": (XH0, WIN[3], 48.70, YTOP),
}
TONGUE_T = 12.0     # off-board tongue length past the MB +y edge (enclosure TODO(measure, M2)); 8 mm checked as well
TX1 = 48.70         # tongue right end (off-board: no C4A-FC under it)
REG_T = dict(REG)
REG_T["E head (MB +y edge)"] = (XH0, WIN[3], 48.70, MB[3])
REG_T["F tongue (off-board)"] = (XH0, MB[3], TX1, MB[3] + TONGUE_T)
for n, r in REG_T.items():
    print("   %-24s x %6.2f-%6.2f  y %6.2f-%6.2f   %5.1f x %5.2f = %6.1f mm2"
          % (n, r[0], r[2], r[1], r[3], r[2] - r[0], r[3] - r[1], (r[2] - r[0]) * (r[3] - r[1])))

RES = 0.05
GX0, GY0, GX1, GY1 = 0.0, 30.0, 70.0, 110.0
xs = np.arange(GX0 + RES / 2, GX1, RES)
ys = np.arange(GY0 + RES / 2, GY1, RES)
XX, YY = np.meshgrid(xs, ys)


def rmask(r):
    return (XX >= r[0]) & (XX <= r[2]) & (YY >= r[1]) & (YY <= r[3])


KL = (20.998 - 1.45, 36.544 - 1.45, 20.998 + 1.45, 64.484 + 1.45)   # 1x12 column keep-out: 1.9 mm pads + 0.5 mm (A.8)
KR = (45.998 - 1.45, 39.084 - 1.45, 45.998 + 1.45, 61.944 + 1.45)   # 1x10 column keep-out
SE = int(round(1.9 / RES))                                            # opening: drop slivers narrower than a 0402 courtyard length


def usable(regs, extra_keepout=()):
    out = np.zeros_like(XX, dtype=bool)
    for r in regs:
        out |= rmask(r)
    area = out.sum() * RES * RES
    cy = ndimage.binary_erosion(out, structure=np.ones((int(round(1.0 / RES)) + 1,) * 2))   # 0.5 mm courtyard limit
    cy &= ~rmask(KL) & ~rmask(KR)
    for k in extra_keepout:
        cy &= ~k
    cy = ndimage.binary_opening(cy, structure=np.ones((SE, SE)))
    return area, cy.sum() * RES * RES, cy


a0, u0, _ = usable([REG["A footprint (r6)"]])
print("   method check: footprint alone %.0f mm2 outline, %.0f mm2 strict usable (stackup_area.py strict basis 732 mm2,"
      " chamfer 1.1 mm2 not modelled)" % (a0, u0))
VARS = {
    "V1 footprint + B (no edge reach)": [REG["A footprint (r6)"], REG["B +y band"]],
    "V2 ring + head to the MB edge (t = 0)": list(REG.values()),
    "V3a ring + head + tongue t = 8 mm": list(REG.values())[:4] + [(XH0, WIN[3], 48.70, MB[3]), (XH0, MB[3], TX1, MB[3] + 8.0)],
    "V3 ring + head + tongue t = 12 mm": list(REG_T.values()),
    "V4 = V3 + +x core (x 48.70-65.00, y 55.01-67.14)": list(REG_T.values()) + [(48.70, 55.01, 65.00, 67.14)],
}
USE = {}
for n, regs in VARS.items():
    a, u, cy = usable(regs)
    USE[n] = (a, u, cy)
    print("   %-50s outline %6.0f mm2 (+%4.0f), strict usable top %6.0f mm2 (+%4.0f)" % (n, a, a - a0, u, u - u0))

# booking (round4/calc/stackup_area_out.txt): CR 1188 incl. pours; DNP 87; merged 1398 incl. pours; r3 bottom set 435
CR_D, DNP, MERGED_D, BOT = 1188.0, 87.0, 1398.0, 435.0
DEL_MERGE = 2 * 4.35 + 4 * 4.35          # R176/R177 deleted, R130/R131A/R131B/R132 removed (0603 courtyard 3.0 x 1.45)
OPT_MERGE = 2 * 4.35                     # R264/R265 optional (eib_merge_failsafe.md 3.6)
U4 = 0.75
print("   merged demand %.0f mm2 (stackup booking) - %.1f deleted (R176/R177, R130-R132) = %.0f; - DNP footprints %.0f = %.0f;"
      " - optional R264/R265 %.1f" % (MERGED_D, DEL_MERGE, MERGED_D - DEL_MERGE, DNP, MERGED_D - DEL_MERGE - DNP, OPT_MERGE))
dm = MERGED_D - DEL_MERGE
for n, (a, u, cy) in USE.items():
    print("   %-50s single-sided U %3.0f %% (no DNP %3.0f %%); double-sided top U %3.0f %% (r3 bottom set %.0f mm2 kept on the"
          " footprint bottom)" % (n, 100 * dm / u, 100 * (dm - DNP) / u, 100 * (dm - BOT) / u, BOT))
print("   budget U4 = %.2f (0.70-0.80 swept in stackup_area.py)" % U4)

# island capacity (EIB section): head (+ tongue) left of C4A-FC (x <= 43.8), on quiet MB copper only
C4A = M.ELS["C4A-FC"]["bbox"]
ISL_X1 = C4A[0] - 1.0
for tag, regs in (("t = 0", [(XH0, WIN[3], ISL_X1, YTOP)]),
                  ("t = 8", [(XH0, MB[3], TX1, MB[3] + 8.0)]),
                  ("t = 12", [(XH0, MB[3], TX1, MB[3] + TONGUE_T)])):
    a, u, _ = usable(regs)
    need = (198.0 + 48.0) / 0.70
    print("   island region %s (%s): usable %.0f mm2 vs EIB section %.0f mm2 courtyard (198 parts + 48 E pads)"
          " / 0.70 = %.0f mm2 -> %s" % (tag, "head x %.1f-%.1f" % (XH0, ISL_X1) if tag == "t = 0" else
                                       "off-board tongue only, x %.1f-%.1f" % (XH0, TX1), u, 246, need,
                                       "fits" if u >= need else "does not fit (short %.0f mm2)" % (need - u)))

# ======================================================================================================================
# 3. What lies under each extension region: parts (heights, air at the 2.665 mm seated-body height) and copper
# ======================================================================================================================
hdr("3. MB parts and copper under each extension region (body 2.54 mm seated on the 0.125 mm sheet: CR underside 2.665 mm)")
UNDER = 2.54 + 0.125
for n, r in list(REG_T.items())[1:]:
    if "tongue" in n:
        print("   %s: off-board (no MB copper or part); enclosure clearance TODO(measure, M2)" % n)
        continue
    parts = [(e["name"], M.height_of(e)[0], e["bbox"]) for e in M.ELS.values() if M.overlaps(e["bbox"], r) and e["name"] != "CHG"]
    txt = ", ".join("%s %s (air %s)" % (p, "%.2f" % h if h is not None else "?", "%.2f" % (UNDER - h) if h is not None else "?")
                    for p, h, _ in sorted(parts, key=lambda q: -(q[1] or 99)))
    print("   %s parts: %s" % (n, txt or "none"))
    rect = r
    xs_r = np.arange(rect[0] + 0.05, rect[2], 0.1)
    ys_r = np.arange(rect[1] + 0.05, rect[3], 0.1)
    X2, Y2 = np.meshgrid(xs_r, ys_r)
    P2 = np.c_[X2.ravel(), Y2.ravel()]
    nets = {}
    for (net, lay, pts, w) in M.POLYS:
        if net == "GND":
            continue
        k = Path(pts).contains_points(P2).sum() * 0.01
        if k > 0.05:
            nets[(net, "L" + lay, "pour")] = nets.get((net, "L" + lay, "pour"), 0.0) + k
    for (net, lay, x1, y1, x2, y2, w) in M.WIRES:
        if net == "GND":
            continue
        # clip segment length inside the rectangle by sampling
        npts = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.05))
        t = np.linspace(0, 1, npts)
        px, py = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
        inside = (px >= rect[0]) & (px <= rect[2]) & (py >= rect[1]) & (py <= rect[3])
        L = inside.mean() * math.hypot(x2 - x1, y2 - y1)
        if L > 0.05:
            key = (net, "L" + lay, "trace %.3f" % w)
            nets[key] = nets.get(key, 0.0) + L
    vias = sum(1 for (net, vx, vy, d) in M.VIAS if rect[0] <= vx <= rect[2] and rect[1] <= vy <= rect[3])
    ctxt = "; ".join("%s %s %s %.1f %s" % (k[0], k[1], k[2], v, "mm2" if k[2] == "pour" else "mm")
                     for k, v in sorted(nets.items(), key=lambda q: -q[1]))
    sw = [k[0] for k in nets if k[0] in M.SWITCH_NETS]
    print("     copper (non-GND): %s; vias %d (all tented, mlViaStopLimit %s)%s"
          % (ctxt or "none", vias, M.VIA_STOP_LIMIT, ("; SWITCH NODE " + ", ".join(sorted(set(sw)))) if sw else ""))

# ======================================================================================================================
# 4. Head support: bonded-foot and drill spots in the head (same criteria as mb_support_spots.py)
# ======================================================================================================================
hdr("4. Head support spots (4 x 4 mm foot: no part body + 0.25 mm, no via; DRILL: also 3.0 mm from non-GND copper)")


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = np.clip(((px - x1) * dx + (py - y1) * dy) / L2, 0, 1) if L2 > 0 else 0
    return np.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


hz = REG["E head (MB +y edge)"]
fx = np.arange(hz[0] + 2.0, hz[2] - 2.0 + 1e-9, 0.25)
fy = np.arange(hz[1] + 2.0, hz[3] - 2.0 + 1e-9, 0.25)
FX, FY = np.meshgrid(fx, fy)
FP = np.c_[FX.ravel(), FY.ravel()]
foot = np.ones(len(FP), dtype=bool)
for e in M.ELS.values():
    if e["name"] == "CHG":
        continue
    b = e["bbox"]
    foot &= ~((FP[:, 0] + 2.0 > b[0] - 0.25) & (FP[:, 0] - 2.0 < b[2] + 0.25) &
              (FP[:, 1] + 2.0 > b[1] - 0.25) & (FP[:, 1] - 2.0 < b[3] + 0.25))
for (n, vx, vy, d) in M.VIAS:
    foot &= ~((np.abs(FP[:, 0] - vx) < 2.0 + d / 2) & (np.abs(FP[:, 1] - vy) < 2.0 + d / 2))
foot_np = foot.copy()
for (net, lay, pts, w) in M.POLYS:
    if net != "GND" and net in M.POWER_NETS:
        foot_np &= ~Path(pts).contains_points(FP, radius=2 * (2.0 + 0.5))
for (net, lay, x1, y1, x2, y2, w) in M.WIRES:
    if net != "GND" and net in M.POWER_NETS:
        foot_np &= ~(seg_dist(FP[:, 0], FP[:, 1], x1, y1, x2, y2) < 2.0 * 1.415 + w / 2 + 0.5)
drill = foot.copy()
for (net, lay, pts, w) in M.POLYS:
    if net != "GND":
        drill &= ~Path(pts).contains_points(FP, radius=2 * 3.0)
for (net, lay, x1, y1, x2, y2, w) in M.WIRES:
    if net != "GND":
        drill &= ~(seg_dist(FP[:, 0], FP[:, 1], x1, y1, x2, y2) < 3.0 + w / 2)
HOLE = (3.3, 94.74, 3.7973)
drill &= np.hypot(FP[:, 0] - HOLE[0], FP[:, 1] - HOLE[1]) > 8.0
for lab, msk in (("FOOT", foot), ("FOOT off power copper", foot_np), ("DRILL (GND only)", drill)):
    Q = FP[msk]
    if len(Q):
        lo, hi = Q[np.argmin(Q[:, 0])], Q[np.argmax(Q[:, 0])]
        print("   %-22s %4d of %d grid points; x range %.2f-%.2f; leftmost (%.2f, %.2f), rightmost (%.2f, %.2f)"
              % (lab, msk.sum(), len(FP), Q[:, 0].min(), Q[:, 0].max(), lo[0], lo[1], hi[0], hi[1]))
    else:
        print("   %-22s none" % lab)
for cand in ((14.0, 94.0), (35.5, 95.5), (38.0, 95.0), (16.0, 95.5)):
    i = np.argmin(np.hypot(FP[:, 0] - cand[0], FP[:, 1] - cand[1]))
    print("   candidate (%.1f, %.1f): FOOT %s, off power copper %s, DRILL %s" % (cand[0], cand[1], foot[i], foot_np[i], drill[i]))

# ======================================================================================================================
# 5. Distances that the merge conditions and the thermal rule need
# ======================================================================================================================
hdr("5. Clearances: island / E-pad row to switching parts, LM1084 5V pour, C4A-FC")
P5 = [p for p in M.POLYS if p[0] == "5V"][0]
p5 = np.array(P5[2])
ISL0 = (XH0, WIN[3], ISL_X1, YTOP)            # island on the head (t = 0 case, rejected)
ISL = (XH0, MB[3], TX1, MB[3] + TONGUE_T)    # island on the off-board tongue (chosen)
ROW_Y = YTOP - 1.25          # E-pad row centre on the head edge (1.5 mm SMT pads, 0.5 mm to the outline)
ROW_Y_T = MB[3] + TONGUE_T - 1.25


def rect_point_d(r, p):
    dx = max(r[0] - p[0], 0, p[0] - r[2])
    dy = max(r[1] - p[1], 0, p[1] - r[3])
    return math.hypot(dx, dy)


for lab, I_ in (("head (t = 0, rejected)", ISL0), ("tongue (chosen)", ISL)):
    print("   island on the %s x %.1f-%.1f, y %.2f-%.2f: to L-FC %.1f, REG-FC %.1f, C4A-FC %.1f, C2-FC %.1f mm; VSW-FC pour %.1f mm"
          % (lab, I_[0], I_[2], I_[1], I_[3], M.rect_dist(I_, M.ELS["L-FC"]["bbox"]), M.rect_dist(I_, M.ELS["REG-FC"]["bbox"]),
             M.rect_dist(I_, M.ELS["C4A-FC"]["bbox"]), M.rect_dist(I_, M.ELS["C2-FC"]["bbox"]),
             min(rect_point_d(I_, q) for (n_, l_, pts_, w_) in M.POLYS if n_ in M.SWITCH_NETS for q in pts_)))
print("   island to 5V pour: %.1f mm (merge condition 8 / H.4 thermal basis; mb_mechanical Table 4: 20 mm -> 1.4-6.3 C)"
      % min(rect_point_d(ISL, q) for q in p5))
for nm in ("L-FC", "REG-FC", "C4A-FC", "C4B-FC", "C2-FC", "C5-FC", "L-BT", "REG-BT", "REG-5V"):
    b = M.ELS[nm]["bbox"]
    print("   %-7s bbox gap to the island %5.1f mm; to the E-pad row (y %.2f) %5.1f mm"
          % (nm, M.rect_dist(ISL, b), ROW_Y, M.rect_dist((XH0, ROW_Y, 48.70, ROW_Y), b)))
for (net, lay, pts, w) in M.POLYS:
    if net in M.SWITCH_NETS:
        pts = np.array(pts)
        d = min(rect_point_d(ISL, q) for q in pts)
        print("   %s pour (L%s) vertex nearest the island: %.1f mm" % (net, lay, d))

# ======================================================================================================================
# 6. Mechanics: cantilever, pin load, resonance (order of magnitude; mb_pinload.py method)
# ======================================================================================================================
hdr("6. Pin-field load and extension resonance (ORDER OF MAGNITUDE; beam FE along y; assumptions as mb_pinload.py)")
from scipy import linalg as sla
PINS = [(20.998, 36.544 + 2.54 * k) for k in range(12)] + [(45.998, 39.084 + 2.54 * k) for k in range(10)]
yc = sum(p[1] for p in PINS) / 22
syy = sum((p[1] - yc) ** 2 for p in PINS)
rmax = max(abs(p[1] - yc) for p in PINS)
Y_ROOT = 64.484                     # pin-11 row: the CR is taken as clamped there (the two pin columns end at 61.9/64.5)
FEET_Y = 94.5                       # two bonded feet on the head, at (14.0, 94.0) and (38.0, 95.0) (section 4)
E_, RHO, TPCB = 20e9, 1850.0, 1.6e-3   # FR4 E ASSUMED (TODO(verify: fab laminate)), rho, thickness ASSUMED 1.6 mm


def width_at(y, t_tongue):
    if y < WIN[1]:
        return 31.0                                   # footprint top / B band, x 17.70-48.70
    if y < WIN[3]:
        return (48.70 - WIN[2]) + (WIN[0] - 17.70)    # lane + strip around L-FC
    if y < MB[3]:
        return 48.70 - XH0                            # head
    return TX1 - XH0                                  # tongue


def beam(t_tongue, mf, feet, areal=None):
    y_tip = MB[3] + t_tongue if t_tongue > 0 else YTOP
    n = int(round((y_tip - Y_ROOT) / 0.25))
    ys_ = np.linspace(Y_ROOT, y_tip, n + 1)
    ndof = 2 * (n + 1)
    K = np.zeros((ndof, ndof)); Mm = np.zeros((ndof, ndof)); Fv = np.zeros(ndof)
    for i in range(n):
        Le = (ys_[i + 1] - ys_[i]) * 1e-3
        w = width_at(0.5 * (ys_[i] + ys_[i + 1]), t_tongue) * 1e-3
        EI = E_ * w * TPCB ** 3 / 12.0
        rA = (areal * 10.0 * w) if areal is not None else RHO * w * TPCB * mf    # areal g/cm2 -> kg/m2 = x10
        k = EI / Le ** 3 * np.array([[12, 6 * Le, -12, 6 * Le], [6 * Le, 4 * Le ** 2, -6 * Le, 2 * Le ** 2],
                                     [-12, -6 * Le, 12, -6 * Le], [6 * Le, 2 * Le ** 2, -6 * Le, 4 * Le ** 2]])
        m = rA * Le / 420.0 * np.array([[156, 22 * Le, 54, -13 * Le], [22 * Le, 4 * Le ** 2, 13 * Le, -3 * Le ** 2],
                                        [54, 13 * Le, 156, -22 * Le], [-13 * Le, -3 * Le ** 2, -22 * Le, 4 * Le ** 2]])
        d = [2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3]
        K[np.ix_(d, d)] += k; Mm[np.ix_(d, d)] += m
        Fv[d] += rA * Le * np.array([0.5, Le / 12, 0.5, -Le / 12])        # load per 1 m/s2 of base acceleration
    fixed = [0, 1]
    j = None
    if feet:
        j = int(np.argmin(np.abs(ys_ - FEET_Y)))
        fixed.append(2 * j)
    free = [d for d in range(ndof) if d not in fixed]
    w2 = sla.eigh(K[np.ix_(free, free)], Mm[np.ix_(free, free)], eigvals_only=True, subset_by_index=[0, 0])[0]
    f1 = math.sqrt(w2) / (2 * math.pi)
    u = np.zeros(ndof)
    u[free] = np.linalg.solve(K[np.ix_(free, free)], Fv[free])
    R = K @ u - Fv                                    # support reactions per 1 m/s2
    V_root, M_root = R[0], R[1]
    R_feet = R[2 * j] if feet else 0.0
    m_tot = Fv[0::2].sum()
    return f1, m_tot, V_root, M_root, R_feet


print("   widths: B band 31.0 mm (y %.2f-%.2f), ring arms %.2f mm (lane %.2f + strip %.2f), head %.1f mm, tongue %.1f mm"
      % (67.14, WIN[1], (48.70 - WIN[2]) + (WIN[0] - 17.70), 48.70 - WIN[2], WIN[0] - 17.70, 48.70 - XH0, TX1 - XH0))
for t_ in (0.0, 8.0, TONGUE_T):
    for mf in (1.0, 2.0):
        f_no = beam(t_, mf, False)[0]
        f_ft = beam(t_, mf, True)[0]
        print("   t %4.1f mm, part-mass factor %.0f: f1 %5.0f Hz unpropped (clamped at y %.2f), %5.0f Hz with the head feet at y %.1f"
              % (t_, mf, f_no, Y_ROOT, f_ft, FEET_Y))
for t_ in (TONGUE_T,):
    for m_main in (5.0, 10.0):
        for areal in (0.6, 0.8):
            for feet in (False, True):
                f1, m_ext, V, Mr, Rf = beam(t_, 1.0, feet, areal=areal)
                a_ = 9.81 * 30.0
                F = m_main * 1e-3 * a_ + abs(V) * a_
                Mc = (abs(Mr) + abs(V) * (Y_ROOT - yc) * 1e-3) * a_
                fp = F / 22 + Mc * rmax * 1e-3 / (syy * 1e-6)
                print("   t %.0f, main %2.0f g, ext %.1f g/cm2 (ext %.1f g), %s, 30 g: worst pin %.3f N (upper bound); feet reaction %.3f N"
                      % (t_, m_main, areal, m_ext * 1e3, "feet   " if feet else "no feet", fp, abs(Rf) * a_))
print("   reference (mb_mechanical Table 6): r6 CR alone 0.067-0.134 N/pin at 30 g; +x usable 0.196-0.305 N unsupported;"
      " pin section ~141 N at an assumed 345 MPa yield")

# ======================================================================================================================
# 7. EVM beside the MB +y edge: placement and lead lengths
# ======================================================================================================================
hdr("7. EVM on the chassis beside the MB +y edge: rotation, offset, lead lengths")
EP = {   # EVM frame points (evm_geom_out.txt)
    "TP49": (83.440, 79.120), "TP33": (80.011, 63.499), "JP21p1": (75.312, 64.769), "JP14p2": (71.375, 64.769),
    "TP38": (66.041, 59.689), "JP12p1": (39.370, 13.741), "TP36": (55.874, 19.710), "JP17p1": (54.611, 26.796),
    "TP27": (26.670, 80.009),
    "J5p1": (82.487, 24.193), "J5p3": (82.487, 34.353), "J1p2": (6.604, 50.799), "J1p1": (6.604, 55.879),
    "J8p2": (18.034, 5.954), "J8p3": (20.574, 5.954), "J7p1": (62.894, 6.223),
    "L2": (47.372, 53.212), "U1": (47.499, 42.036),
}
E_TGT = {"E8": "TP49", "E3": "TP33", "E4": "JP21p1", "E2": "JP14p2", "E7": "TP38", "E1": "JP12p1", "E5": "TP36", "E6": "JP17p1"}
CRIT = ("E8", "E3", "E4", "E2")
# r7 E-pad order (A.9 isolation pairs kept: E1 empty both sides / E7 empty both sides / E8-E3 empty between)
ORDER = ["E8", None, "E3", "E4", "E2", None, "E7", None, "E6", "E5", None, "E1"]


def place(theta, X0, ye):
    """EVM frame -> board for an EVM whose edge facing -y lies at board y = ye. theta: which EVM edge faces the MB."""
    if theta == "right":      # local +x -> board -y, local +y -> board +x
        return lambda p: (X0 + p[1], ye + (EVM - p[0]))
    if theta == "top":        # local +y -> board -y, local +x -> board -x
        return lambda p: (X0 - p[0], ye + (EVM - p[1]))
    if theta == "bottom":     # unrotated
        return lambda p: (X0 + p[0], ye + p[1])
    if theta == "left":       # local -x -> board -y
        return lambda p: (X0 - p[1], ye + p[0])


def cr_points(t, x_row_hi):
    yrow = (MB[3] + t - 1.25) if t > 0 else ROW_Y
    pads = {}
    for i, name in enumerate(ORDER):
        if name:
            pads[name] = (x_row_hi - 2.54 * i, yrow)
    return pads


W_CR = {"W1": (30.3, 61.2), "W2": (27.7, 61.2), "W3": (24.3, 45.4), "W4": (24.3, 55.6), "W7": (29.0, 57.5)}
W_EVM = {"W1": "J1p2", "W2": "J1p1", "W3": "J5p1", "W4": "J5p3", "W7": "J8p2"}


def leads(theta, X0, t, g, dz, x_row_hi):
    ye = MB[3] + t + g
    f = place(theta, X0, ye)
    pads = cr_points(t, x_row_hi)
    out = {}
    for e, tp in E_TGT.items():
        q = f(EP[tp])
        p = pads[e]
        dh = math.hypot(q[0] - p[0], q[1] - p[1])
        out[e] = (dh, math.hypot(dh, dz), q)
    for w, tp in W_EVM.items():
        q = f(EP[tp])
        p = W_CR[w]
        dh = math.hypot(q[0] - p[0], q[1] - p[1])
        out[w] = (dh, math.hypot(dh, dz), q)
    ev = (min(f((0, 0))[0], f((EVM, EVM))[0]), ye, max(f((0, 0))[0], f((EVM, EVM))[0]), ye + EVM)
    return out, ev


USB = (93.47, 101.09)    # Teensy USB end at board y 93.73 (TEENSY41 package, element U$1 R270 at (97.282, 60.706))
print("   Teensy 4.1 USB end (package text 'USB', x -33.02..-27.31 -> board y %.2f, x %.2f-%.2f): the USB plug exits +y;"
      " the EVM keeps x <= %.1f - 5 mm" % (93.73, USB[0], USB[1], USB[0]))
results = []
ROW_HI = (XH0 + 0.5 + 0.75 + 27.94, 48.70 - 0.5 - 0.75)     # E8 pad x range: row 27.94 mm c-c inside the 0.5 mm limit


def optimise(theta, t, x0_min=-120.0):
    best_r = None
    for x_hi in np.arange(ROW_HI[0], ROW_HI[1] + 1e-9, 0.5):
        for X0 in np.arange(x0_min, 220, 1.0):
            L, ev = leads(theta, X0, t, 5.0, 0.0, x_hi)
            if ev[2] > USB[0] - 5.0 and ev[0] < USB[1] + 5.0:
                continue
            crit = max(L[e][0] for e in CRIT)
            cost = crit + 0.25 * sum(L[e][0] for e in E_TGT) / 8 + 0.1 * (L["W3"][0] + L["W1"][0])
            if best_r is None or cost < best_r[0]:
                best_r = (cost, X0, L, ev, x_hi)
    return best_r


for theta in ("right", "top", "bottom", "left"):
    for t in (0.0, TONGUE_T):
        best_r = optimise(theta, t)
        results.append((theta, t, best_r))
        c, X0, L, ev, x_hi = best_r
        print("   EVM edge facing the MB = %-6s t %4.1f: X0 %6.1f, row E8 x %.2f (EVM x %.1f-%.1f); E8/E3/E4/E2 %s; E7 %.0f; E6/E5/E1 %s;"
              " W1/W2 %.0f/%.0f; W3/W4 %.0f/%.0f; W7 %.0f mm (straight, horizontal, gap 5 mm)"
              % (theta, t, X0, x_hi, ev[0], ev[2], "/".join("%.0f" % L[e][0] for e in CRIT), L["E7"][0],
                 "/".join("%.0f" % L[e][0] for e in ("E6", "E5", "E1")),
                 L["W1"][0], L["W2"][0], L["W3"][0], L["W4"][0], L["W7"][0]))

# chosen: right edge facing the MB, tongue t = 8; table with gap and dz sensitivity
theta, t = "right", TONGUE_T
best = [r for r in results if r[0] == theta and r[1] == t][0][2]
X0, XHI = best[1], best[4]
bc = optimise(theta, t, x0_min=-0.5)
print("   constrained case (EVM kept inside the MB x-range, X0 >= -0.5): X0 %.1f, row E8 at x %.2f; E8/E3/E4/E2 %s; E7 %.0f;"
      " E6/E5/E1 %s; W1/W2 %.0f/%.0f; W3/W4 %.0f/%.0f mm"
      % (bc[1], bc[4], "/".join("%.0f" % bc[2][e][0] for e in CRIT), bc[2]["E7"][0],
         "/".join("%.0f" % bc[2][e][0] for e in ("E6", "E5", "E1")), bc[2]["W1"][0], bc[2]["W2"][0], bc[2]["W3"][0], bc[2]["W4"][0]))
print("\n   CHOSEN: EVM right edge (J5, TP33/TP49 cluster) facing the MB, tongue t = %.0f mm, X0 = %.1f, E8 pad at x %.2f" % (t, X0, XHI))
f = place(theta, X0, MB[3] + t + 5.0)
for k in ("J5p1", "J5p3", "TP49", "TP33", "JP21p1", "JP14p2", "TP38", "JP17p1", "TP36", "JP12p1", "J1p2", "J1p1", "J8p2",
          "L2", "U1"):
    q = f(EP[k])
    print("     %-7s EVM (%6.2f, %6.2f) -> board (%7.2f, %7.2f)" % (k, EP[k][0], EP[k][1], q[0], q[1]))
_, ev = leads(theta, X0, t, 5.0, 0.0, XHI)
print("     EVM outline on the chassis: x %.2f-%.2f, y %.2f-%.2f (gap 5 mm to the tongue tip); J5 wire face at y %.2f facing -y;"
      " J1 wire face at y %.2f facing +y; J8 mates from -x (pins to x %.2f)"
      % (ev[0], ev[2], ev[1], ev[3], ev[1] + (EVM - 86.49), ev[1] + (EVM - 2.60), X0 - 6.24))
pads = cr_points(t, XHI)
print("     E-pad row (SMT 1.5 x 1.5 mm, 2.54 mm pitch) on the tongue edge y %.2f: %s"
      % (list(pads.values())[0][1], ", ".join("%s x %.2f" % (k, v[0]) for k, v in pads.items())))
print("     %-4s %-7s | %s" % ("lead", "target", " | ".join("g %2.0f dz %+3.0f: straight / r3 max / r7 max" % (g, dz)
                                                       for g, dz in ((5, 0), (5, 10), (15, 10)))))
R6 = {"E8": 20, "E3": 25, "E4": 30, "E2": 35, "E7": 40, "E1": 90, "E5": 65, "E6": 60, "W1": 300, "W2": 300, "W3": 300,
      "W4": 300, "W7": 300}
LOOP = 10.0   # service loop between two bodies (MB on its mounts, EVM on its bracket): ASSUMPTION, TODO(measure, M5)
TABLE7 = {}
for key in list(E_TGT) + list(W_EVM):
    row = []
    for g, dz in ((5, 0), (5, 10), (15, 10)):
        L, _ = leads(theta, X0, t, g, dz, XHI)
        dh, d3, q = L[key]
        r3max = ceil5(1.25 * d3)
        r7max = ceil5(1.25 * dh + abs(dz) + LOOP)
        row.append("%5.1f / %3d / %3d" % (d3, r3max, r7max))
        if (g, dz) == (5, 10):
            TABLE7[key] = (d3, r3max, r7max)
    tgt = E_TGT.get(key, W_EVM.get(key))
    print("     %-4s %-7s | %s   (r6 max %d)" % (key, tgt, " | ".join(row), R6[key]))
print("   r3 rule = straight 3-D x 1.25 rounded up to 5 mm; r7 rule = 1.25 x horizontal + |dz| + %.0f mm service loop, rounded up"
      % LOOP)

# ======================================================================================================================
# 8. Pickup from L-FC at the E-pad row (dipole model of eib_merge_calc.py) and from the W pairs
# ======================================================================================================================
hdr("8. Pickup checks for the length-critical leads (eib_merge_calc.py dipole model; budgets E3 75 / E4 48 / E6 159 mV)")
MU0_4PI = 1e-7


def dip_emf(dmdt, r0, s, L):
    return 2 * MU0_4PI * dmdt * s * L / (r0 ** 2 * math.sqrt(r0 ** 2 + L ** 2 / 4))


didt_lfc = 16.0 / 2.2e-6     # upper bound max(Vin, Vout - Vin)/L <= Vout/L; VBUS 16.0 V nominal, L-FC 2.2 uH (.brd value)
A_EFF = (5e-6, 50e-6)        # ASSUMED effective area, same as the EVM ripple loop; a molded shielded part is lower
lc = ((LFC[0] + LFC[2]) / 2, (LFC[1] + LFC[3]) / 2)
for t_, yrow in ((0.0, ROW_Y), (TONGUE_T, MB[3] + TONGUE_T - 1.25)):
    r0 = math.hypot(0.0, yrow - LFC[3]) + 0.0
    r0c = yrow - lc[1]
    for s in (0.005, 0.002):
        e = [1e3 * dip_emf(a * didt_lfc, r0c * 1e-3, s, 0.060) for a in A_EFF]
        print("   t %.0f: row y %.2f, L-FC centre (%.1f, %.1f) %.1f mm away; lead pair s %.0f mm, 60 mm run: %.1f-%.1f mV sustained"
              % (t_, yrow, lc[0], lc[1], r0c, s * 1e3, e[0], e[1]))
print("   di/dt bound %.2f A/us = 16.0 V / 2.2 uH; the E-leads leave the row in +y, away from L-FC, so this is an upper bound"
      % (didt_lfc / 1e6))
print("   W1-W4 pairs: DC + ms steps (class A, 1 A/us): merge-note Table 9 limits E3 925 / E4 588 / E6 1957 mm at 10 mm")

# ======================================================================================================================
# 9. Lead resistance and the R_PATH / H.11 rows
# ======================================================================================================================
hdr("9. W-lead resistance (20 AWG 33.3 mOhm/m, 18 AWG 20.9 mOhm/m: the values implied by H.11 20.0 / 12.6 mOhm at 0.30 m)")
for pair, awg_r, key, cur in (("W1/W2 input", 33.3e-3, "W1", 1.80), ("W3/W4 battery", 20.9e-3, "W3", 3.21)):
    Lb = TABLE7[key][2] / 1000.0
    r_new = 2 * Lb * awg_r
    r_old = 2 * 0.30 * awg_r
    print("   %-14s r6 0.30 m: %.1f mOhm; r7 build max %.0f mm: %.1f mOhm (-%.1f); at %.2f A: %.0f -> %.0f mW"
          % (pair, r_old * 1e3, Lb * 1e3, r_new * 1e3, (r_old - r_new) * 1e3, cur, r_old * cur ** 2 * 1e3, r_new * cur ** 2 * 1e3))
r_w12 = 2 * TABLE7["W1"][2] / 1000.0 * 33.3e-3
print("   R_PATH_RG (H.19) 0.117-0.193 ohm includes W1/W2 20 mOhm -> %.3f-%.3f ohm; warm budget numerator"
      " (20.5 - 19.38 - 1.1 x R_max) rises by %.1f mV (H.7, regen-armed cruise)"
      % (0.117 - 0.020 + r_w12, 0.193 - 0.020 + r_w12, 1.1 * (0.020 - r_w12) * 1e3))

# ======================================================================================================================
# 10. Header stack-up (unchanged TSW body) and height envelope
# ======================================================================================================================
hdr("10. Header stack-up and height envelope")
A_, B_, C_ = 10.92, 2.54, 5.84          # TSW -07 lead style: A total, B tail, C post (Samtec F-226 via mb_mechanical Table 7)
body, sheet, t_mb, t_cr = 2.54, 0.125, 1.6, 1.6
print("   TSW-1xx-07-G-S: body %.2f; CR end (B %.2f) through the CR %.1f -> %.2f mm above the CR top (fillet); MB end (C %.2f)"
      " through sheet %.3f + MB %.1f -> %.2f mm below the MB before the PM4 cut to <= 1.0 mm"
      % (body, B_, t_cr, B_ - t_cr, C_, sheet, t_mb, C_ - sheet - t_mb))
print("   CR underside %.3f mm above the MB top (foot height under the head, where no sheet lies); CR top %.3f mm"
      % (body + sheet, body + sheet + t_cr))
print("   air over OP-FC %.2f mm, over C4A-FC %.2f mm, over MDAC-FC %.2f mm, over REG-FC %.2f mm (T-A-06 criterion >= 0.3 mm)"
      % (body + sheet - 1.75, body + sheet - 1.35, body + sheet - 1.10, body + sheet - 1.00))
print("   L-FC top 5.0 mm stands %.2f mm above the CR top inside the window; Ag105 nominal envelope 2.54 + 1.60 + 9 = 13.14 mm"
      % (5.0 - (body + sheet + t_cr)))

# ======================================================================================================================
# 11. Routed W-lead lengths (the straight line of section 7 passes through the EVM for W1/W2/W7) and the figure
# ======================================================================================================================
hdr("11. Routed W leads (waypoints; dressing corridors keep W pairs off the island and apart from the E leads)")
fch = place("right", X0, MB[3] + TONGUE_T + 5.0)
ye_ch = MB[3] + TONGUE_T + 5.0
J1FACE = ye_ch + (EVM - 2.604)
J5FACE = ye_ch + (EVM - 86.488)
J7FACE_X = X0 + 2.773
J8TIP_X = X0 - 6.24
EVMX1 = X0 + EVM
ROUTES = {
    "W1 -> J1 pin 2 (VIN1)": [W_CR["W1"], (45.0, 92.0), (52.0, 97.0), (EVMX1 + 4.0, ye_ch), (EVMX1 + 4.0, ye_ch + EVM + 3.0),
                              (fch(EP["J1p2"])[0], ye_ch + EVM + 3.0), (fch(EP["J1p2"])[0], J1FACE)],
    "W2 -> J1 pin 1 (PGND)": [W_CR["W2"], (45.0, 92.0), (52.0, 97.0), (EVMX1 + 4.0, ye_ch), (EVMX1 + 4.0, ye_ch + EVM + 3.0),
                              (fch(EP["J1p1"])[0], ye_ch + EVM + 3.0), (fch(EP["J1p1"])[0], J1FACE)],
    "W3 -> J5 pin 1 (BATTERY)": [W_CR["W3"], (19.1, 70.0), (19.1, 90.0), (9.0, 97.0), (fch(EP["J5p1"])[0], J5FACE)],
    "W4 -> J5 pin 3 (PGND)": [W_CR["W4"], (19.1, 70.0), (19.1, 90.0), (9.0, 97.0), (fch(EP["J5p3"])[0], J5FACE)],
    "W7 -> J8 pins 2/3 (pin tips)": [W_CR["W7"], (19.1, 70.0), (19.1, 90.0), (9.0, 97.0), (J8TIP_X - 2.0, ye_ch + 10.0),
                                     (J8TIP_X - 2.0, fch(EP["J8p2"])[1]), (J8TIP_X, fch(EP["J8p2"])[1])],
    "W6 -> J7 pin 1 (only with an NTC)": [(33.0, 57.5), (19.1, 70.0), (19.1, 90.0), (9.0, 97.0), (J7FACE_X - 3.0, ye_ch + 15.0),
                                          (J7FACE_X - 3.0, fch(EP["J7p1"])[1]), (J7FACE_X, fch(EP["J7p1"])[1])],
}
ROUTED = {}
for k, pts in ROUTES.items():
    L = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    mx = ceil5(L + 10.0 + LOOP)          # + |dz| 10 mm (ASSUMED until M2) + service loop
    ROUTED[k] = (L, mx, pts)
    print("   %-34s routed %5.1f mm in plan; build max %3d mm (+ dz 10 + loop %.0f, rounded up; r6 max 300 mm)  via %s"
          % (k, L, mx, LOOP, " ".join("(%.1f,%.1f)" % p for p in pts[1:-1])))
print("   J8: the KK 254 housing body beyond the pin tips is not in the library (TODO(verify: Molex 22-01-3047 drawing));"
      " W7 ends at the pin tips")
print("   E-lead corridor: from the tongue edge (y %.2f) straight +y to the EVM; W3/W4/W6/W7 leave the CR at x < 10 (left of the"
      " tongue), W1/W2 at x > 48.7 (right of it), so no W pair crosses the island or runs with an E lead" % (MB[3] + TONGUE_T))

# figure
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
fig, ax = plt.subplots(figsize=(11, 15))
ax.add_patch(Rectangle((0, 0), MB[2], MB[3], fill=False, lw=1.5, ec="k"))
for (x, y, d) in M.HOLES:
    ax.add_patch(plt.Circle((x, y), d / 2, fill=False, ec="k"))
for e in M.ELS.values():
    if e["name"] == "CHG":
        continue
    b = e["bbox"]
    h = M.height_of(e)[0]
    col = "#e88" if (h is None or h >= 3.0) else ("#fc9" if h >= 1.5 else "#eee")
    if (h is None or h >= 1.0 or e["name"] in ("R1-FC", "R2-FC", "RENC2", "C-D2")):
        ax.add_patch(Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fc=col, ec="0.4", lw=0.4, alpha=0.6))
        if (h is None or h >= 1.3) and (b[2] - b[0]) * (b[3] - b[1]) > 6:
            ax.text((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, "%s\n%s" % (e["name"], "?" if h is None else "%.3g" % h),
                    fontsize=5, ha="center", va="center")
for (net, lay, pts, w) in M.POLYS:
    if net in M.SWITCH_NETS:
        ax.add_patch(Polygon(pts, closed=True, fc="c", ec="none", alpha=0.35))
ax.add_patch(Rectangle((17.70, 34.14), 31.0, 33.0, fill=False, ls="--", ec="b", lw=1.0))
colors = {"A": "#9cf", "B": "#9f9", "C": "#9f9", "D": "#9f9", "E": "#9f9", "F": "#cfc"}
for n, r in REG_T.items():
    ax.add_patch(Rectangle((r[0], r[1]), r[2] - r[0], r[3] - r[1], fc=colors[n[0]], ec="g", lw=0.8, alpha=0.45))
ax.add_patch(Rectangle((ISL[0] + 0.5, ISL[1]), ISL[2] - ISL[0] - 1.0, ISL[3] - ISL[1] - 0.5, fill=False, hatch="////",
                       ec="m", lw=0.6))
for e, (x, y) in cr_points(TONGUE_T, XHI).items():
    ax.plot(x, y, "ms", ms=3)
    ax.text(x, y - 1.8, e, fontsize=5, ha="center", color="m")
for (x, y) in ((14.0, 94.0), (38.0, 95.0)):
    ax.add_patch(Rectangle((x - 2, y - 2), 4, 4, fc="#888", ec="k", lw=0.5))
for k, (x, y) in W_CR.items():
    ax.plot(x, y, "ko", ms=3)
for k, (L, mx, pts) in ROUTED.items():
    xs_, ys_ = zip(*pts)
    ax.plot(xs_, ys_, "-", lw=0.8,
            color="tab:red" if k.startswith(("W1", "W2")) else ("tab:orange" if k.startswith(("W3", "W4")) else "tab:brown"))
ev_pts = [fch((0, 0)), fch((EVM, 0)), fch((EVM, EVM)), fch((0, EVM))]
ax.add_patch(Polygon(ev_pts, closed=True, fill=False, ec="tab:purple", lw=1.4))
for k in ("TP49", "TP33", "JP21p1", "JP14p2", "TP38", "JP17p1", "TP36", "JP12p1", "J5p1", "J5p3", "J1p2", "J1p1", "J8p2"):
    q = fch(EP[k])
    ax.plot(*q, "^", color="tab:purple", ms=3)
    ax.text(q[0] + 0.8, q[1], k, fontsize=5, color="tab:purple")
pads = cr_points(TONGUE_T, XHI)
for e, tp in E_TGT.items():
    q = fch(EP[tp])
    ax.plot([pads[e][0], q[0]], [pads[e][1], q[1]], ":", color="m", lw=0.7)
for nm, (lx0, lx1, ly0, ly1) in {"L2": (43.672, 51.072, 49.812, 56.612), "U1": (45.448, 49.549, 39.986, 44.086)}.items():
    c = [fch((lx0, ly0)), fch((lx1, ly0)), fch((lx1, ly1)), fch((lx0, ly1))]
    ax.add_patch(Polygon(c, closed=True, fc="#c9f", ec="tab:purple", lw=0.5))
    ax.text(sum(p[0] for p in c) / 4, sum(p[1] for p in c) / 4, nm, fontsize=5, ha="center")
for nm, (lx0, lx1, ly0, ly1) in {"J5": (77.487, 86.488, 21.773, 36.773), "J1": (2.604, 11.604, 48.224, 58.299),
                                  "J3 (EM7: desolder)": (77.487, 86.488, 41.648, 51.723)}.items():
    c = [fch((lx0, ly0)), fch((lx1, ly0)), fch((lx1, ly1)), fch((lx0, ly1))]
    ax.add_patch(Polygon(c, closed=True, fc="#fcc", ec="tab:purple", lw=0.5, alpha=0.6))
    ax.text(sum(p[0] for p in c) / 4, sum(p[1] for p in c) / 4, nm, fontsize=5, ha="center")
ax.annotate("Teensy USB end", (97.3, 93.7), (100, 110), fontsize=6, arrowprops=dict(arrowstyle="->", lw=0.5))
ax.set_xlim(-48, 135)
ax.set_ylim(-3, 215)
ax.set_aspect("equal")
ax.grid(True, lw=0.3)
ax.set_title("r7 proposal: CR ring around L-FC to the MB +y edge, 12 mm tongue with the EIB island; EVM on a chassis bracket\n"
             "(Eagle board mm, top view, +y up; blue dashed = r6 CR; green = r7 extension; hatched = AGND island; grey = head feet;\n"
             "purple = EVM, right edge facing the MB; dotted = E leads (straight); red / orange / brown = routed W1-W2 / W3-W4 / W6-W7)",
             fontsize=7)
fig.savefig(os.path.join(HERE, "r7_evm_on_cr_map.png"), dpi=170, bbox_inches="tight")
print("   figure: work/r7_evm_on_cr_map.png")

# ======================================================================================================================
# 12. H.11 / H.19 rows with the routed W build maxima (supersedes the straight-line values of section 9)
# ======================================================================================================================
hdr("12. H.11 / H.19 with the routed build maxima (20 AWG 33.3 mOhm/m, 18 AWG 20.9 mOhm/m)")
lw12 = (ROUTED["W1 -> J1 pin 2 (VIN1)"][1] + ROUTED["W2 -> J1 pin 1 (PGND)"][1]) / 1000.0
lw34 = (ROUTED["W3 -> J5 pin 1 (BATTERY)"][1] + ROUTED["W4 -> J5 pin 3 (PGND)"][1]) / 1000.0
r12, r34 = lw12 * 33.3e-3, lw34 * 20.9e-3
r12_6, r34_6 = 0.60 * 33.3e-3, 0.60 * 20.9e-3
print("   W1/W2 pair %.3f m of conductor: %.1f mOhm (r6 %.1f); %.0f mW at 1.80 A (r6 %.0f)"
      % (lw12, r12 * 1e3, r12_6 * 1e3, r12 * 1.8 ** 2 * 1e3, r12_6 * 1.8 ** 2 * 1e3))
print("   W3/W4 pair %.3f m of conductor: %.1f mOhm (r6 %.1f); %.0f mW at 3.21 A (r6 %.0f)"
      % (lw34, r34 * 1e3, r34_6 * 1e3, r34 * 3.21 ** 2 * 1e3, r34_6 * 3.21 ** 2 * 1e3))
d = r12_6 - r12
print("   R_PATH_RG (H.19) 0.117-0.193 ohm -> %.3f-%.3f ohm; H.7 warm-budget numerator (20.5 - 19.38 - 1.1 x R_max) +%.1f mV"
      % (0.117 - d, 0.193 - d, 1.1 * d * 1e3))
print("   island minimum tongue for 351 mm2 (linear between t 8 -> 264 and t 12 -> 413 mm2): %.1f mm"
      % (8.0 + (351.0 - 264.0) / (413.0 - 264.0) * 4.0))
yrow12 = MB[3] + TONGUE_T - 1.25
for nm in ("L-FC", "REG-FC", "C4A-FC"):
    b = M.ELS[nm]["bbox"]
    print("   %-7s gap to the t = 12 E-pad row (y %.2f): %.1f mm" % (nm, yrow12, yrow12 - b[3]))
