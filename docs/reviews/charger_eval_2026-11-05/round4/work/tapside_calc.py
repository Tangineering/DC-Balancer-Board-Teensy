#!/usr/bin/env python3
"""Round 4 (r7) tap-side proposal: every number in work/proposal_tapside.md.

Stdlib only. Run from round4/work/:  /c/Users/ricky/miniforge3/python.exe -I tapside_calc.py > tapside_calc_out.txt

Frames: MB = Eagle .brd board coordinates, top view, +x right, +y up, mm. EVM = SLUUCB5E frame of evm_geometry.md
(origin lower-left of the EVM outline, top view). Sources per block are printed with the result. Values marked
ASSUMPTION are not measured and carry a TODO in the proposal.
"""
import math

def h(t):
    print("\n=== " + t)

# ---------------------------------------------------------------------------------------------------------------
# 1. Outline. Main CR = r6 A.7 outline; arm = this proposal. MB neighbours from round4/calc/mb_neighbours_out.txt
#    and mb_neighbours.py --copper queries (REG-5V body, 5V L1 pour bbox, C-D2, RENC2, J1).
# ---------------------------------------------------------------------------------------------------------------
MAIN = (17.70, 34.14, 48.70, 67.14)
ARM = (48.70, 56.00, 80.23, 67.14)
REG5V = (50.97, 36.87, 62.31, 54.51)      # LM1084 body bbox (.brd)
POUR5V_TOP = 54.61                         # 5V L1 polygon bbox top (.brd query)
VIA5V = (59.39, 55.58)                     # tented 5V via (.brd query)
CD2 = (67.12, 68.80, 70.04, 70.90)
RENC2 = (80.73, 65.59, 82.33, 68.02)
J1BODY_X0 = 83.06
CO5V = (49.30, 37.27, 52.30, 41.98)
h("1. Outline and clearances (MB frame, mm)")
aw, ah = ARM[2] - ARM[0], ARM[3] - ARM[1]
mw, mh = MAIN[2] - MAIN[0], MAIN[3] - MAIN[1]
chamfer = 0.5 * 1.0 * 1.0
print("main %.2f x %.2f = %.1f mm2 (chamfer -%.1f); arm %.2f x %.2f = %.1f mm2; total %.1f mm2 (+%.0f %%)"
      % (mw, mh, mw * mh, chamfer, aw, ah, aw * ah, mw * mh - chamfer + aw * ah, 100 * aw * ah / (mw * mh)))
print("bounding box x %.2f-%.2f (%.2f), y %.2f-%.2f" % (MAIN[0], ARM[2], ARM[2] - MAIN[0], MAIN[1], MAIN[3]))
print("arm low edge y %.2f: to REG-5V body top %.2f mm; to 5V pour bbox top %.2f mm; to 5V via centre %.2f mm (tented)"
      % (ARM[1], ARM[1] - REG5V[3], ARM[1] - POUR5V_TOP, ARM[1] - VIA5V[1]))
print("arm top edge y %.2f: to C-D2 body %.2f mm; arm tip x %.2f: to RENC2 %.2f mm, to J1 body %.2f mm"
      % (ARM[3], CD2[1] - ARM[3], ARM[2], RENC2[0] - ARM[2], J1BODY_X0 - ARM[2]))
print("main right edge x %.2f to REG-5V body %.2f mm, to CO-5V %.2f mm (r6, unchanged)"
      % (MAIN[2], REG5V[0] - MAIN[2], CO5V[0] - MAIN[2]))
print("pin column x 45.998 to arm tip: %.2f mm (cantilever length)" % (ARM[2] - 45.998))

# ---------------------------------------------------------------------------------------------------------------
# 2. Area booking. Bases: round4/calc/stackup_area_out.txt (strict usable top 732 mm2 for the footprint; r6 split
#    top 693 + 60 mm2 pours = 753, bottom 435 mm2; tap field booked 21 x 8 = 168 mm2; J101 3.9 x 9.4 = 36.7 mm2;
#    0603 courtyard 3.0 x 1.45, 1206 4.75 x 2.3 (A.8)); H.18 bottom free 591 mm2 (design H.18).
# ---------------------------------------------------------------------------------------------------------------
h("2. Area booking (courtyard mm2)")
C0603, C1206 = 3.0 * 1.45, 4.75 * 2.3
arm_use = (aw) * (ah - 1.0)              # 0.5 mm outline margin top and bottom; tip margin offset by the root strip
print("arm courtyard-usable: %.2f x %.2f = %.1f mm2 (0.5 mm in from the top, bottom and tip; the x 48.20-48.70 root"
      " strip of the main outline joins it)" % (aw, ah - 1.0, arm_use))
field_x = (7 * 2.54 + 1.5 + 1.0) * (2 * 2.54 + 1.5 + 1.0)   # 3 x 7 pads, +0.5 mm courtyard each side
field_l = 4 * (1.5 + 1.0) * (1.5 + 1.0)                     # 4 single pads
bead_l = 4 * 2.54 * 1.5                                      # adhesive bead strip beside the low field, ASSUMPTION
J101 = 3.9 * 9.4
moved_passives = 6
arm_demand = field_x + J101 + C1206 + moved_passives * C0603
main_top = 753.0 - 168.0 - J101 - C1206 + field_l + bead_l - moved_passives * C0603
print("arm demand: field 3x7 %.1f + J101 %.1f + R175 1206 %.1f + %d x 0603 %.1f = %.1f -> U %.0f %%"
      % (field_x, J101, C1206, moved_passives, moved_passives * C0603, arm_demand, 100 * arm_demand / arm_use))
print("main top demand: 753 - 168 (r6 field) - %.1f (J101) - %.1f (R175) + %.1f (1x4 field) + %.1f (bead) - %.1f"
      " = %.1f on 732 strict -> U %.0f %% (r6: 753/732 = %.0f %%)"
      % (J101, C1206, field_l, bead_l, moved_passives * C0603, main_top, 100 * main_top / 732, 100 * 753 / 732))
print("bottom (main only, r3 set): 435 on 591 -> U %.0f %%; arm bottom: none (continuous L4 GND)" % (100 * 435 / 591))
tot_dem = arm_demand + main_top + 435
print("whole CR: %.0f mm2 of courtyard on %.0f mm2 of usable area (top main 732 + arm %.0f + bottom 591) -> %.0f %%"
      % (tot_dem, 732 + arm_use + 591, arm_use, 100 * tot_dem / (732 + arm_use + 591)))
# single-sided check with the stackup_area break-even (+798 no DNP, +917 all footprints; extension effective = A - A/32 - keep-out)
eff = aw * ah - aw * ah / 32.0
print("single-sided needs +798..+917 mm2 of extension (stackup_area); this arm gives %.0f mm2 (no support keep-out on"
      " the top: the foot is bonded under the CR) -> single-sided NOT reached" % eff)

# ---------------------------------------------------------------------------------------------------------------
# 3. Tap fields and tap lengths. Destinations: round4/work/mb_mech_calc.py TAPS (from A.4 and the .brd).
#    r6 lengths: design A.4. Build rule here: ceil10(1.5 x straight + 15 mm).
# ---------------------------------------------------------------------------------------------------------------
h("3. Tap fields and tap wire lengths (mm)")
TAPS = {
    "T1 C-D6 pad1 (V-MOT)": ((97.79, 19.80), 150), "T7b C-D6 pad2 (GND)": ((97.79, 16.00), 150),
    "T2 C-D2 pad1 (VBUS)": ((67.705, 69.85), 100),
    "T3 J1.39": ((87.122, 42.926), 120), "T4 J1.43": ((87.122, 37.846), 120), "T5 J1.45": ((87.122, 35.306), 120),
    "T6 J1.29": ((87.122, 55.626), 120), "T22 BAL pad8": ((25.86, 30.44), 50), "T8 J2.31": ((109.982, 53.086), 150),
    "T9 SNS-BT GND/REF": ((55.118, 23.622), 120), "T10 J1.23": ((87.122, 63.246), 120),
    "T11 J2.19": ((109.982, 68.326), 150), "T12 J2.47": ((109.982, 32.766), 150),
    "T13 J2.45": ((109.982, 35.306), 150), "T14 J2.21": ((109.982, 65.786), 150),
    "T15 J2.07": ((109.982, 83.566), 150), "T16 J2.43": ((109.982, 37.846), 150),
    "T17 J2.09": ((109.982, 81.026), 150), "T17r J2.29": ((109.982, 55.626), 150),
    "T20 ROS pad2": ((81.534, 69.797), 100), "T21 J2.11": ((109.982, 78.486), 150),
}
# T7b: C-D6 pad 2 position is not in the mb_mech TAPS table; C-D6 pad 1 + 3.8 mm in -y is an ASSUMPTION (0805-class
# pad pitch); it only sets T7b, which is twisted with T1 and has the same length by construction.
FIELD_X = [(63.00 + 2.54 * k, 58.00 + 2.54 * r) for r in range(3) for k in range(7)]   # 3 x 7, arm
FIELD_L = [(24.00, 35.80), (38.70, 35.80), (41.24, 35.80), (43.78, 35.80)]          # F08 T22 | F09 T8, F10 T9, F22 T18
cx = sum(p[0] for p in FIELD_X) / len(FIELD_X); cy = sum(p[1] for p in FIELD_X) / len(FIELD_X)
lx = sum(p[0] for p in FIELD_L) / len(FIELD_L); ly = sum(p[1] for p in FIELD_L) / len(FIELD_L)
print("arm field 3 x 7 centres x %.2f-%.2f, y %.2f/%.2f/%.2f; envelope x %.2f-%.2f, y %.2f-%.2f; centroid (%.2f, %.2f)"
      % (FIELD_X[0][0], FIELD_X[6][0], 58.0, 60.54, 63.08, FIELD_X[0][0] - 0.75, FIELD_X[6][0] + 0.75, 57.25, 63.83, cx, cy))
print("low pads (main, y 35.80): F08 x 24.00 (T22), F09 x 38.70 (T8), F10 x 41.24 (T9), F22 x 43.78 (T18 option)")
LOWPAD = {"T22 BAL pad8": FIELD_L[0], "T8 J2.31": FIELD_L[1], "T9 SNS-BT GND/REF": FIELD_L[2]}
LOW = {"T22 BAL pad8", "T8 J2.31", "T9 SNS-BT GND/REF"}
R3F = (32.79, 38.34)
def ceil10(v):
    return int(math.ceil(v / 10.0) * 10)
s_r3 = s_new = s_b6 = s_b7 = 0.0
print("%-22s %6s %6s %6s %7s %7s  field" % ("tap", "r6 str", "r7 str", "-%", "r6 bld", "r7 bld"))
for name, ((x, y), r6b) in TAPS.items():
    d3 = math.hypot(x - R3F[0], y - R3F[1])
    f = LOWPAD[name] if name in LOW else (cx, cy)
    dn = math.hypot(x - f[0], y - f[1])
    b7 = ceil10(1.5 * dn + 15)
    s_r3 += d3; s_new += dn; s_b6 += r6b; s_b7 += b7
    print("%-22s %6.1f %6.1f %5.0f%% %7d %7d  %s" % (name, d3, dn, 100 * (dn - d3) / d3, r6b, b7,
                                                    "low" if name in LOW else "arm"))
print("SUM straight r6 %.0f -> r7 %.0f mm (%.0f %%); build r6 %.0f -> r7 %.0f mm (%.0f %%)"
      % (s_r3, s_new, 100 * (s_new - s_r3) / s_r3, s_b6, s_b7, 100 * (s_b7 - s_b6) / s_b6))
print("rule check on r6 taps (1.5 x straight + 15, ceil 10): T22 %d (r6 50), T2 %d (r6 100), T8 %d (r6 150), T12 %d (r6 150)"
      % (ceil10(1.5 * 10.5 + 15), ceil10(1.5 * 47.0 + 15), ceil10(1.5 * 78.6 + 15), ceil10(1.5 * 77.4 + 15)))
T18 = (50.80, 39.62)   # CO-5V pad 1 centre, ASSUMPTION from the CO-5V bbox (3528, pad 1 at the low-x end)
print("T18 option (CO-5V pad 1 ~%s) from the low field: %.1f mm straight (r6 0.05 m)"
      % (T18, math.hypot(T18[0] - FIELD_L[3][0], T18[1] - FIELD_L[3][1])))

# ---------------------------------------------------------------------------------------------------------------
# 4. Thermal bands on the arm (distance from the 5V L1 pour bbox top, y 54.61). Rise estimates: round4/work/
#    mb_mechanical.md Table 4 (ESTIMATE, rise above local enclosure air; best/nom/worst; 0.40/0.63/1.08 W).
# ---------------------------------------------------------------------------------------------------------------
h("4. Arm thermal bands")
for lab, y in (("arm low edge", 56.00), ("band A/B boundary", 61.00), ("J101 courtyard low", 62.74),
               ("arm top edge", 67.14)):
    print("%-20s y %.2f -> d %.2f mm from the 5V pour" % (lab, y, y - POUR5V_TOP))
print("Table 4 nominal 0.63 W: 1 mm 7.0/8.6/13.6 C, 5 mm 5.2/6.4/9.9 C, 10 mm 3.8/4.6/6.9 C; 1.08 W worst 1 mm 23.5 C")
print("main-footprint comparator block (x 24-36) to the pour bbox (x >= 49.78): >= %.1f mm" % (49.78 - 36.0))

# ---------------------------------------------------------------------------------------------------------------
# 5. Pin field, arm resonance, tip foot. Method and ASSUMPTIONS of round4/work/mb_pinload.py (E 20 GPa, rho 1850,
#    t 1.6 mm, areal mass 0.6-0.8 g/cm2, main CR 5-10 g, 10/30 g). Tip foot = a 2-position TSW body segment
#    (5.08 x 2.54 mm, pins pulled) bonded with the BOM RTV to the CR and to a polyimide patch.
# ---------------------------------------------------------------------------------------------------------------
h("5. Pin load, arm resonance, tip foot (ORDER OF MAGNITUDE)")
XA, XB, NA, NB = 20.998, 45.998, 12, 10
pins = [(XA, 36.544 + 2.54 * k) for k in range(NA)] + [(XB, 39.084 + 2.54 * k) for k in range(NB)]
xc = sum(p[0] for p in pins) / 22
sxx = sum((p[0] - xc) ** 2 for p in pins)
rmax = max(abs(p[0] - xc) for p in pins)
arm_cg = (ARM[0] + ARM[2]) / 2 - xc
foot = (77.0, 61.5)      # foot centre: x 75.73-78.27, y 58.96-64.04 (2.54 along x, 5.08 along y)
L = ARM[2] - XB
area_cm2 = aw * ah / 100
for m_main in (5.0, 10.0):
    for rho in (0.6, 0.8):
        m_ext = rho * area_cm2           # g (stripped of cable loads; see the J101/ribbon note in the proposal)
        for g in (10.0, 30.0):
            a = 9.81 * g * 1e-3          # N per g of mass
            F = (m_main + m_ext) * a
            M = m_ext * a * arm_cg
            p_no = F / 22 + M * rmax / sxx
            R = 0.5 * m_ext * a          # prop carries half the arm load (mb_pinload convention)
            M_s = abs(M - R * (foot[0] - xc))
            p_sup = (F - R) / 22 + M_s * rmax / sxx
            if g == 30.0:
                print("main %4.1f g, rho %.1f, m_arm %.2f g, %2.0f g: per-pin %.3f N unpropped / %.3f N with the foot;"
                      " foot reaction %.3f N -> bond stress %.0f kPa on 12.9 mm2"
                      % (m_main, rho, m_ext, g, p_no, p_sup, R, R / 12.9e-6 / 1e3))
E, rhoF, t = 20e9, 1850.0, 1.6e-3
k = math.sqrt(E * t * t / (12 * rhoF))
Lm = L * 1e-3
Lp = (foot[0] - XB) * 1e-3
for mf in (1.0, 2.0):
    fc = 1.875 ** 2 / (2 * math.pi * Lm ** 2) * k / math.sqrt(mf)
    fp = 3.927 ** 2 / (2 * math.pi * Lp ** 2) * k / math.sqrt(mf)
    print("mass factor %.0f: f1 unpropped (L %.1f mm) %.0f Hz; propped at the foot (L %.1f mm, clamped-pinned) %.0f Hz"
          % (mf, L, fc, Lp * 1e3, fp))
Iarm = aw * t ** 3 * 1e9 / 12.0      # mm4 (width aw mm, t in mm)
Iarm = ah * (1.6 ** 3) / 12.0     # section width = arm height along y
defl = 10.0 * L ** 3 / (3 * 20000.0 * Iarm)
print("10 N handling push at the unpropped tip: deflection %.2f mm (gap to MB 2.54 mm); with the foot: ~0" % defl)

# ---------------------------------------------------------------------------------------------------------------
# 6. Header stack (TSW F-226 lead styles via mb_mechanical.md Table 7; MB 1.6 mm per design PM4; CR 1.6 mm assumed).
# ---------------------------------------------------------------------------------------------------------------
h("6. Header stack")
body, sheet, mbt, crt = 2.54, 0.125, 1.6, 1.6
for style, (A, B, C) in {"-05": (8.51, 3.30, 2.67), "-07": (10.92, 2.54, 5.84)}.items():
    print("TSW %s A %.2f B %.2f C %.2f: C up through CR -> top protrusion %.2f mm; B down through sheet+MB -> %.2f mm"
          " below the MB | reversed: B up -> %.2f, C down -> %.2f" % (style, A, B, C, C - crt, B - sheet - mbt,
                                                                       B - crt, C - sheet - mbt))
print("stack top above MB: body %.2f + sheet %.3f + CR %.2f = %.3f mm; + J101 mated socket and W5 fold >= 8 mm (A.3)"
      % (body, sheet, crt, body + sheet + crt))
print("air under the arm: %.2f mm (no MB part in x 48.70-80.23, y 56.00-67.14; .brd query)" % body)

# ---------------------------------------------------------------------------------------------------------------
# 7. EVM placement past the MB +y edge (ASSUMPTION: chassis room exists, TODO(measure: M2)). EVM points from
#    evm_geometry.md Table 1; EIB per design A.5/A.9 r6 rule (pad column 7 mm off the EVM right edge, E3 5 mm above
#    TP33, 12 positions at 2.54 mm downward from E8); J201 on the opposite long edge (edge insets 2.0 / 3.0 mm
#    ASSUMED). CR terminals: W1/W2/W3/W4/W6/W7 unchanged (A.8), J101 in the arm.
#    Route = CR pad -> corridor gate (56, 67.14) -> MB edge at the corridor -> EVM terminal approach -> terminal.
#    Build max = ceil5(1.25 x route) for E-style rounding, and ceil10 for W leads.
# ---------------------------------------------------------------------------------------------------------------
h("7. EVM placement and W-lead lengths (mm)")
YE = 98.044
EIB_EDGE_IN, EIB_DEPTH, J201_IN = 2.0, 24.0, 3.0
padcol = 88.90 + 7.0
E3y = 63.499 + 5.0
E8y = E3y + 2 * 2.54
E6y = E8y - 11 * 2.54
rowc = (E8y + E6y) / 2
eib_x0 = padcol - EIB_EDGE_IN
eib_x1 = eib_x0 + EIB_DEPTH
J201 = (eib_x1 - J201_IN, rowc)
print("EIB (EVM frame): x %.2f-%.2f, y %.2f-%.2f; E-row y %.2f..%.2f; J201 ~(%.2f, %.2f)"
      % (eib_x0, eib_x1, rowc - 18, rowc + 18, E6y, E8y, J201[0], J201[1]))
CR = {"W1": (30.3, 61.2), "W2": (27.7, 61.2), "W3": (24.3, 45.4), "W4": (24.3, 55.6), "W7": (29.0, 57.5),
      "W6": (34.0, 57.5), "W5": (54.90, 64.69)}
GATE = (56.0, 67.14)
def poly(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
def route(pad, waypoints):
    pts = [pad]
    if pad[0] < GATE[0] or pad[1] < GATE[1]:
        pts.append(GATE)
    return poly(pts + waypoints)
def ceil5(v):
    return int(math.ceil(v / 5.0) * 5)
WEIGHT = {"W1": 1.5, "W2": 1.5, "W3": 2.0, "W4": 2.0, "W5": 1.5, "W7": 1.0}
def place_R0(X0, g):
    Y0 = YE + g
    P = lambda ex, ey: (X0 + ex, Y0 + ey)
    out = {}
    j1 = P(2.604, 53.339); j5 = P(86.488, 29.273); j8 = P(19.304, -6.24); j7 = P(64.644, 2.773); j201 = P(*J201)
    xt = lambda xx: min(max(xx, 56.0), 80.0)
    out["W1"] = route(CR["W1"], [(xt(X0 - 5), YE), (X0 - 5, j1[1]), j1])
    out["W2"] = route(CR["W2"], [(xt(X0 - 5), YE), (X0 - 5, j1[1]), j1])
    out["W3"] = route(CR["W3"], [(xt(X0 + 92.0), YE), (X0 + 92.0, j5[1]), j5])
    out["W4"] = route(CR["W4"], [(xt(X0 + 92.0), YE), (X0 + 92.0, j5[1]), j5])
    out["W7"] = route(CR["W7"], [(xt(j8[0]), YE), j8])
    out["W6"] = route(CR["W6"], [(xt(j7[0]), YE), j7])
    out["W5"] = route(CR["W5"], [(xt(j201[0] + 6), YE), (j201[0] + 6, j201[1]), j201])
    return out
def place_R90cw(X0, gclr):
    Y0 = YE + gclr + eib_x1          # EIB far edge gclr beyond the MB edge
    P = lambda ex, ey: (X0 + ey, Y0 - ex)
    out = {}
    j5 = P(86.488, 29.273); j201 = P(*J201); j1 = P(2.604, 53.339); j8 = P(19.304, -6.24); j7 = P(64.644, 2.773)
    xt = lambda xx: min(max(xx, 56.0), 80.0)
    out["W3"] = route(CR["W3"], [(xt(j5[0]), YE), j5])
    out["W4"] = route(CR["W4"], [(xt(j5[0]), YE), j5])
    out["W5"] = route(CR["W5"], [(xt(j201[0]), YE), j201])
    side = X0 - 5.0                    # around the EVM's MB-left side (ey = 0 side carries J8/J7 anyway)
    out["W1"] = route(CR["W1"], [(xt(side), YE), (side, j1[1] + 6), (j1[0], j1[1] + 6), j1])
    out["W2"] = route(CR["W2"], [(xt(side), YE), (side, j1[1] + 6), (j1[0], j1[1] + 6), j1])
    out["W7"] = route(CR["W7"], [(xt(side), YE), (side, j8[1]), j8])
    out["W6"] = route(CR["W6"], [(xt(side), YE), (side, j7[1]), j7])
    return out, Y0
best = {}
for nm in ("R0", "R90cw"):
    bestv = None
    for X0 in [x * 1.0 for x in range(-40, 81)]:
        if nm == "R0":
            r = place_R0(X0, 20.0)
        else:
            r, _ = place_R90cw(X0, 3.0)
        v = sum(WEIGHT[kk] * r[kk] for kk in WEIGHT)
        if bestv is None or v < bestv[0]:
            bestv = (v, X0, r)
    best[nm] = bestv
    v, X0, r = bestv
    print("%s best X0 %.0f (weighted %.0f): " % (nm, X0, v) +
          ", ".join("%s %.0f" % (kk, r[kk]) for kk in ("W1", "W2", "W3", "W4", "W5", "W6", "W7")))
v, X0, r = best["R90cw"] if best["R90cw"][0] < best["R0"][0] else best["R0"]
pick = "R90cw" if best["R90cw"][0] < best["R0"][0] else "R0"
print("chosen %s, X0 %.0f" % (pick, X0))
if pick == "R90cw":
    _, Y0 = place_R90cw(X0, 3.0)
    print("EVM outline MB x %.1f-%.1f, y %.1f-%.1f; EIB MB y %.1f-%.1f (EVM right edge faces the MB)"
          % (X0, X0 + 88.9, Y0 - 88.9, Y0, Y0 - eib_x1, Y0 - eib_x0))
for kk in ("W1", "W2", "W3", "W4", "W5", "W6", "W7"):
    print("  %s route %.0f mm -> build max (x1.25, ceil 10) %d mm (r6 cap 300)" % (kk, r[kk], ceil10(1.25 * r[kk])))
RAWG = {"20": 33.31e-3, "18": 20.95e-3}   # ohm/m, AWG copper table (reproduces H.11: 0.30 m pairs 20.0 / 12.6 mOhm)
l12 = ceil10(1.25 * max(r["W1"], r["W2"])) / 1e3
l34 = ceil10(1.25 * max(r["W3"], r["W4"])) / 1e3
print("H.11 check: 0.30 m 20 AWG pair %.1f mOhm, 18 AWG pair %.1f mOhm" % (2 * 0.3 * RAWG["20"] * 1e3, 2 * 0.3 * RAWG["18"] * 1e3))
print("at the build maxima: input pair %.2f m -> %.1f mOhm; battery pair %.2f m -> %.1f mOhm (%.0f mV, %.0f mW at 3.21 A)"
      % (l12, 2 * l12 * RAWG["20"] * 1e3, l34, 2 * l34 * RAWG["18"] * 1e3, 3.21 * 2 * l34 * RAWG["18"] * 1e3,
         3.21 ** 2 * 2 * l34 * RAWG["18"] * 1e3))
print("R_PATH_RG (H.19) 0.117-0.193 ohm with 20 mOhm of W1/W2 -> %.3f-%.3f ohm"
      % (0.117 - 0.020 + 2 * l12 * RAWG["20"], 0.193 - 0.020 + 2 * l12 * RAWG["20"]))

# ---------------------------------------------------------------------------------------------------------------
# 8. Why the EIB is not merged: shortest CR-edge-to-EVM-point distance for the EVM past the +y edge with its right
#    edge facing the MB and NO EIB between (gap 3 mm), from the arm top-edge pad row at x 56-80.
#    G1 window of eib_merge_failsafe.md: 10-60 mm (E1 up to 90 mm).
# ---------------------------------------------------------------------------------------------------------------
h("8. Merged-EIB E-lead lengths if the EVM sat 3 mm past the +y edge, right edge toward the MB (best case)")
Y0m = YE + 3.0 + 88.9
EP = {"E8 TP49": (83.440, 79.120), "E3 TP33": (80.011, 63.499), "E4 JP21p1": (75.312, 64.769),
      "E2 JP14p2": (71.375, 64.769), "E7 TP38": (66.041, 59.689), "E1 JP12p1": (39.370, 13.741),
      "E5 TP36": (55.874, 19.710), "E6 JP17p1": (54.611, 26.796)}
for X0m in (8.0, 15.0, 25.0):
    vals = []
    for nmE, (ex, ey) in EP.items():
        p = (X0m + ey, Y0m - ex)
        xr = min(max(p[0], 56.0), 80.0)
        d = math.hypot(p[0] - xr, p[1] - ARM[3])
        vals.append("%s %.0f/%d" % (nmE.split()[0], d, ceil5(1.25 * d)))
    print("X0 %.0f: " % X0m + ", ".join(vals) + "  (straight/x1.25 max; G1 limit 60, E1 90)")
print("EVM-frame E straight / max (evm_geometry.md Table 6, EIB at the EVM, unchanged): E8 13.6/20, E3 16.7/25,"
      " E4 20.6/30, E2 24.6/35, E7 29.9/40, E1 69.0/90, E5 49.1/65, E6 45.4/60")

# ---------------------------------------------------------------------------------------------------------------
# 9. Supplementary figures quoted in the proposal.
# ---------------------------------------------------------------------------------------------------------------
h("9. Supplementary")
# 9a. Short-arm fallback x 48.70-65.00: arm holds J101, R175 and a 2 x 5 field; a 2 x 7 field stays on the main top.
sa = (65.00 - 48.70) * (ah - 1.0)
f25 = (4 * 2.54 + 2.5) * (2.54 + 2.5)
f27 = (6 * 2.54 + 2.5) * (2.54 + 2.5)
arm_s = J101 + C1206 + f25
main_s = 753.0 - J101 - C1206 - 168.0 + f27
print("short arm: courtyard %.1f mm2, demand %.1f -> %.0f %%; main top %.1f on 732 -> %.0f %%"
      % (sa, arm_s, 100 * arm_s / sa, main_s, 100 * main_s / 732))
# 9b. Capacitance of the arm L4 plane to the MB VBUS pour (parallel plate, air): eps0 * A / d.
A_vbus = 139.2e-6     # m2, VBUS pour under the +x usable zone (work/mb_mechanical.md); upper bound for this arm
print("arm L4 to MB VBUS pour: %.2f pF (A <= 139.2 mm2, d 2.665 mm)" % (8.854e-12 * A_vbus / 2.665e-3 * 1e12))
# 9c. H.7 warm-response budget t_d + tau <= (20.5 - VINDPM_max - 1.1 * R_path_max) * C / 1.1, VINDPM_max 19.38 V.
for Rp in (0.193, 0.193 - 0.020 + 2 * l12 * RAWG["20"]):
    print("R_path,max %.3f ohm: %.3f ms (0.4 mF), %.3f ms (0.97 mF)"
          % (Rp, (20.5 - 19.38 - 1.1 * Rp) * 0.4e-3 / 1.1 * 1e3, (20.5 - 19.38 - 1.1 * Rp) * 0.97e-3 / 1.1 * 1e3))
# 9d. Mezzanine height over the MB (rejected): TB005 block + bumpon + EVM board (assumed 1.6) + ED120 block.
print("EVM mezzanine stack: %.2f mm" % (21.70 + 5.08 + 1.6 + 13.0))
# 9e. Tip-foot pull check: 5 N on the 12.9 mm2 bond.
print("T-A-08 pull 5 N on 12.9 mm2: %.0f kPa; ratio to the 30 g foot reaction 0.413 N: %.0f" % (5 / 12.9e-6 / 1e3, 5 / 0.413))
print("R0 chassis footprint past the +y edge: x %.1f-%.1f, y %.1f-%.1f" % (12.0 - 5.0, 12.0 + eib_x1, YE, YE + 20.0 + 88.9))
