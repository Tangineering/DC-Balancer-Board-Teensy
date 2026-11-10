"""Independent check of H.23 items 5, 6, 7, 9 (tap lengths, E1/C205 resonance and R276 drop, EVM reference placement
and W1/W3 routes, header post arithmetic). Stdlib only; written without reference to r7_calc.py."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brdgeo import Board  # noqa

B = Board()
P = lambda en, pn: (B.els[en]["pads"][pn]["x"], B.els[en]["pads"][pn]["y"])  # noqa: E731

# ---------------------------------------------------------------- 5. taps
MB = {"T1": P("C-D6", "1"), "T7b": P("C-D6", "2"), "T2": P("C-D2", "1"), "T3": P("J1", "39"), "T4": P("J1", "43"),
      "T5": P("J1", "45"), "T6": P("J1", "29"), "T22": P("BAL", "8"), "T8": P("J2", "31"), "T9": P("SNS-BT", "15"),
      "T10": P("J1", "23"), "T11": P("J2", "19"), "T12": P("J2", "47"), "T13": P("J2", "45"), "T14": P("J2", "21"),
      "T15": P("J2", "07"), "T16": P("J2", "43"), "T17": P("J2", "09"), "T17r": P("J2", "29"), "T20": P("ROS", "2"),
      "T21": P("J2", "11"), "T18": P("CO-5V", "1"), "T19": P("J2", "33"), "F24": P("J1", "07")}
# r7 pad assignment as stated in H.23(g)
R7PAD = {"T1": (53.34, 58.94), "T7b": (55.88, 58.94), "T2": (58.42, 66.56), "T3": (55.88, 61.48),
         "T4": (58.42, 58.94), "T5": (53.34, 61.48), "T6": (53.34, 64.02), "T22": (26.44, 35.80),
         "T8": (28.98, 35.80), "T9": (31.52, 35.80), "T10": (63.50, 64.02), "T11": (58.42, 64.02),
         "T12": (60.96, 58.94), "T13": (63.50, 58.94), "T14": (63.50, 61.48), "T15": (55.88, 66.56),
         "T16": (58.42, 61.48), "T17": (60.96, 66.56), "T17r": (60.96, 64.02), "T20": (55.88, 64.02),
         "T21": (63.50, 66.56), "T18": (50.80, 58.94), "T19": (60.96, 61.48), "F24": (53.34, 66.56)}
SUM20 = ["T1", "T2", "T3", "T4", "T5", "T6", "T22", "T8", "T9", "T10", "T11", "T12", "T13", "T14", "T15", "T16",
         "T17", "T17r", "T20", "T21"]
R6C = (23.90 + 3.5 * 2.54, 38.34)          # r6 field centre (DOC A.7: 23.90 + k x 2.54, k 0..7; rows 35.80-40.88)
R6RES = {"T22": (26.44, 35.80), "T8": (28.98, 35.80), "T9": (31.52, 35.80)}   # r6 low-y row k = 1..3
d = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])  # noqa: E731
print("[5] r6 field centre", R6C)
s6c = s6p = s7 = 0.0
for t in SUM20:
    a = d(R6C, MB[t])
    a2 = d(R6RES.get(t, R6C), MB[t])
    b = d(R7PAD[t], MB[t])
    s6c += a
    s6p += a2
    s7 += b
    print("   %-5s MB (%.3f, %.3f)  r6 centre %6.2f  r6 (F08-F10 on their r6 pads) %6.2f  r7 %6.2f" % (
        t, MB[t][0], MB[t][1], a, a2, b))
print("   SUM 20: r6 centre %.1f, r6 with F08-F10 pads %.1f, r7 %.1f mm (%.1f %% / %.1f %%)" % (
    s6c, s6p, s7, (s7 / s6c - 1) * 100, (s7 / s6p - 1) * 100))
# check grid occupancy and uniqueness
pos = list(R7PAD.values())
print("   unique r7 positions:", len(set(pos)) == len(pos), len(pos))

# ---------------------------------------------------------------- 6. E1 + E8 + C205
MU0 = 4e-7 * math.pi
RHO = 1.724e-8                 # copper 20 C
D28 = 0.321e-3                 # 28 AWG diameter (ASTM B258 nominal 0.0126 in)
R28 = RHO / (math.pi * (D28 / 2) ** 2)
C = 100e-9
print("\n[6] 28 AWG %.1f mOhm/m" % (R28 * 1e3))
for l_mm in (85.0, 90.0):
    l = l_mm * 1e-3
    s, a = 5e-3, 0.16e-3
    L = MU0 / math.pi * l * math.log(s / a)
    f0 = 1 / (2 * math.pi * math.sqrt(L * C))
    Z0 = math.sqrt(L / C)
    Rw = R28 * 2 * l
    R = Rw + 0.020
    # skin-effect sensitivity at f0 (round wire, Rac/Rdc ~ a/(2 delta) + 1/4 for a >> delta)
    delta = math.sqrt(RHO / (math.pi * f0 * MU0))
    kac = (D28 / 2) / (2 * delta) + 0.25
    print("   l %.0f mm: L %.1f nH, f0 %.3f MHz, Z0 %.3f Ohm, R %.1f mOhm, Q %.2f; with 10 Ohm Q %.4f (zeta %.2f);"
          " skin delta %.1f um, Rac/Rdc ~%.2f -> Q %.1f" % (
              l_mm, L * 1e9, f0 / 1e6, Z0, R * 1e3, Z0 / R, Z0 / (R + 10.0), (R + 10) / (2 * Z0), delta * 1e6, kac,
              Z0 / (Rw * kac + 0.020)))
print("   R276 x C205 corner %.1f kHz; |H(1.5 MHz)| = %.3f" % (1 / (2 * math.pi * 10 * C) / 1e3,
                                                             1 / math.sqrt(1 + (1.5e6 * 2 * math.pi * 10 * C) ** 2)))
# R276 static drop: E1 current = R252, R254, R271 (47k to ~0 V when their driver sinks) + feed via R255 48.7k
for regn in (4.8, 5.2):
    g = regn / 47e3
    for nm, n_pull, vpin in (("held RFC_OFF LOW", 0, None), ("held RFC_OFF HIGH (R254)", 1, None),
                             ("released regen (R252+R254+R271+feed, pin 2.06)", 3, 2.06),
                             ("released FC (R252+R271+feed, pin 1.52)", 2, 1.52)):
        I = n_pull * g + ((regn - vpin) / 48.7e3 if vpin else 0.0)
        drop = I * 10.0
        rbot = None
        if vpin == 2.06:
            rbot = 1 / (1 / 49.9e3 + 1 / 200e3)
        elif vpin == 1.52:
            rbot = 1 / (1 / 49.9e3 + 1 / 200e3 + 1 / 59.0e3)
        shift = drop * rbot / (48.7e3 + rbot) if rbot else 0.0
        print("   REGN %.1f %-48s I %.4f mA drop %.3f mV pin shift %.3f mV IINDPM %.2f mA" % (
            regn, nm, I * 1e3, drop * 1e3, shift * 1e3, shift / 0.8 * 1e3))

# ---------------------------------------------------------------- 7. EVM placement, EIB, routes
MB_TOP = B.outline_bbox[3]
G = 20.0                         # r7 gap (ASSUMPTION in H.23(l))
XR = 88.50
EVM = (XR - 88.90, MB_TOP + G, XR, MB_TOP + G + 88.90)
ev = lambda x, y: (EVM[0] + x, EVM[1] + y)  # noqa: E731
print("\n[7] MB +y edge %.3f; EVM rect x %.2f-%.2f y %.3f-%.3f" % ((MB_TOP,) + EVM))
te = B.els["U$1"]["box"]
print("   Teensy box", tuple(round(v, 3) for v in te), "USB corridor x 93.47-101.09 from y %.3f" % te[3])
print("   EVM right edge to corridor %.2f mm" % (93.47 - XR))
col = XR + 7.0
e3y = EVM[1] + 63.499 + 5.0
rows = {"E8": 1, "E3": 3, "E4": 4, "E2": 5, "E7": 7, "E1": 9, "E5": 11, "E6": 12}
ys = {k: e3y - (r - 3) * 2.54 for k, r in rows.items()}
print("   EIB pad column x %.2f; E3 y %.3f; E8 %.3f .. E6 %.3f" % (col, e3y, ys["E8"], ys["E6"]))
yc = (ys["E8"] + ys["E6"]) / 2
eib = (col - 2.0, yc - 18.0, col - 2.0 + 24.0, yc + 18.0)
print("   EIB box (pad column 2 mm inside the EVM-facing edge, 36 mm edge vertical, ASSUMPTION as r7):",
      tuple(round(v, 3) for v in eib))
print("   EIB x-overlap with corridor x band: %.2f-%.2f; EIB bottom %.2f is %.2f mm above the Teensy USB end" % (
    max(eib[0], 93.47), min(eib[2], 101.09), eib[1], eib[1] - te[3]))
j5 = (ev(77.487, 21.773), ev(86.488, 36.773))
print("   J5 body board y %.3f-%.3f; EIB bottom - J5 top %.2f" % (j5[0][1], j5[1][1], eib[1] - j5[1][1]))


def plen(pts):
    return sum(d(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# W1: CR (30.3, 61.2) -> tab X top edge (x1 in 56-65, y 68.30) -> MB edge (x2 in 56-68.91) -> around the EVM
# lower-left corner -> 10 mm approach normal to J1 wire face (EVM x 2.604) -> J1 pin 2 VIN1 (6.604, 50.799)
j1 = ev(6.604, 50.799)
face = EVM[0] + 2.604
ap1 = (face - 10.0, j1[1])
best = None
for i in range(0, 91):
    x1 = 56.0 + i * 0.1
    for k in range(0, 130):
        x2 = 56.0 + k * 0.1
        if x2 > 68.91:
            break
        pts = [(30.3, 61.2), (x1, 68.30), (x2, MB_TOP), (EVM[0], EVM[1]), ap1, j1]
        L = plen(pts)
        if best is None or L < best[0]:
            best = (L, pts)
print("   W1 route %.2f mm via %s -> build max %d mm" % (best[0], [(round(a, 2), round(b, 2)) for a, b in best[1]],
                                                       math.ceil(best[0] * 1.25 / 10) * 10))
# alternative W1 rule reading: leave the CR over its +y side directly (not via tab X): sensitivity only
alt = [(30.3, 61.2), (30.3, MB_TOP), (EVM[0], EVM[1]), ap1, j1]
print("   W1 sensitivity, straight +y exit at x 30.3 (no tab X corridor): %.1f mm" % plen(alt))

# W3: CR (24.3, 45.4) -> tab X top edge -> MB edge -> EVM lower-right corner (88.50, EVM y0) -> corridor
# top-left corner (93.47, 93.73 + 45) -> 10 mm approach normal to J5 face (EVM x 86.488) -> J5 pin 1
j5p1 = ev(82.487, 24.193)
face5 = EVM[0] + 86.488
ap3 = (face5 + 10.0, j5p1[1])
corr_end = te[3] + 45.0
print("   J5 pin 1 board (%.3f, %.3f); face x %.3f; approach (%.3f, %.3f); corridor end y %.2f" % (
    j5p1 + (face5,) + ap3 + (corr_end,)))
best = None
for i in range(0, 91):
    x1 = 56.0 + i * 0.1
    for k in range(0, 130):
        x2 = 56.0 + k * 0.01 * 10
        if x2 > 68.91:
            break
        pts = [(24.3, 45.4), (x1, 68.30), (x2, MB_TOP), (EVM[2], EVM[1]), (93.47, corr_end), ap3, j5p1]
        L = plen(pts)
        if best is None or L < best[0]:
            best = (L, pts)
print("   W3 route %.2f mm via %s -> build max %d mm" % (best[0], [(round(a, 2), round(b, 2)) for a, b in best[1]],
                                                       math.ceil(best[0] * 1.25 / 10) * 10))
# the x2 cap: chassis tie <= 30 mm from the CR (nearest CR point (65.0, 68.3))
print("   x2 cap for a 30 mm tie: %.3f; tie distance tab X top edge to MB edge %.3f" % (
    65.0 + math.sqrt(30 ** 2 - (MB_TOP - 68.3) ** 2), MB_TOP - 68.30))

# ---------------------------------------------------------------- 9. posts
A_, B_, C_, BODY = 10.92, 2.54, 5.84, 2.54
SH, MBT, CRT = 0.125, 1.6, 1.6
print("\n[9] TSW-1xx-07: A %.2f = B + body + C = %.2f" % (A_, B_ + BODY + C_))
print("   B up through the CR: CR-top protrusion %.3f; C down: MB-bottom protrusion %.3f" % (B_ - CRT, C_ - SH - MBT))
print("   C up: CR-top %.3f; B down: MB-bottom %.3f" % (C_ - CRT, B_ - SH - MBT))
print("   CR underside %.3f, CR top %.3f above the MB top" % (SH + BODY, SH + BODY + CRT))
