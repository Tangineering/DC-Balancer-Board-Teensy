"""Items 5 and 6: corridor fallbacks (i)-(iii), E-lead lengths, E1/C205 at 100 mm, skin effect and Q (own code)."""
import cmath
import math

d = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])  # noqa: E731
MB_TOP = 98.044
EVM_W = 88.90
CORR = (93.47, 101.09)
# EVM points, evm_geometry.md Table 1 (EVM frame)
PT = {"E8": (83.440, 79.120), "E3": (80.011, 63.499), "E4": (75.312, 64.769), "E2": (71.375, 64.769),
      "E7": (66.041, 59.689), "E1": (39.370, 13.741), "E5": (55.874, 19.710), "E6": (54.611, 26.796)}
ROW = {"E8": 1, "E3": 3, "E4": 4, "E2": 5, "E7": 7, "E1": 9, "E5": 11, "E6": 12}
D7 = {"E8": 20, "E3": 25, "E4": 30, "E2": 35, "E7": 40, "E1": 90, "E5": 65, "E6": 60}
LIM = {"E3": 92, "E4": 59, "E6": 196}
E3Y = 63.499 + 5.0
rowy = {k: E3Y - (r - 3) * 2.54 for k, r in ROW.items()}
bmax = lambda s: int(math.ceil(1.25 * s / 5.0 - 1e-9)) * 5  # noqa: E731


def leads(colx, label):
    print("  %s: pad column EVM x %.2f" % (label, colx))
    out = {}
    for k in ("E8", "E3", "E4", "E2", "E7", "E1", "E5", "E6"):
        s = d((colx, rowy[k]), PT[k])
        out[k] = (s, bmax(s))
        extra = ""
        if k in LIM:
            extra = "; straight/limit %.2f, build/limit %.2f" % (s / LIM[k], bmax(s) / LIM[k])
        print("    %s straight %5.1f build max %3d (D7 %d)%s" % (k, s, bmax(s), D7[k], extra))
    return out


# reference: EVM right edge x 88.50, EVM board x0 = -0.40
x0 = 88.50 - EVM_W
col_ref = EVM_W + 7.0
print("reference: EVM board x %.2f-%.2f, EIB pad column EVM %.2f = board %.2f" % (x0, x0 + EVM_W, col_ref, x0 + col_ref))
leads(col_ref, "reference (D7 check)")
eib_ref = (x0 + col_ref - 2.0, x0 + col_ref - 2.0 + 24.0)
j5_app = x0 + 86.488 + 10.0
print("EIB x %.2f-%.2f; J5 approach x %.2f" % (eib_ref + (j5_app,)))

# (i) shift -x until EIB and J5 approach are >= 3.0 mm left of the corridor
shift = max(eib_ref[1], j5_app) - (CORR[0] - 3.0)
print("\n(i) shift %.2f mm: EVM x %.2f-%.2f (overhang %.2f past MB x 0); EIB x %.2f-%.2f; J5 approach x %.2f" % (
    shift, x0 - shift, x0 - shift + EVM_W, -(x0 - shift), eib_ref[0] - shift, eib_ref[1] - shift, j5_app - shift))
xs = x0 - shift
evy = MB_TOP + 20.0
j1p2 = (xs + 6.604, evy + 50.799)
app1 = (xs + 2.604 - 10.0, j1p2[1])
w1 = [(30.3, 61.2), (56.0, 68.3), (56.0, MB_TOP), (xs, evy), app1, j1p2]
L1 = sum(d(w1[i], w1[i + 1]) for i in range(len(w1) - 1))
print("   W1 route %.1f mm (build max %d); J1 approach point x %.2f = %.2f mm past the MB -x edge" % (
    L1, int(math.ceil(1.25 * L1 / 10 - 1e-9)) * 10, app1[0], -app1[0]))
j5p1 = (xs + 82.487, evy + 24.193)
app3 = (xs + 86.488 + 10.0, j5p1[1])
best = None
for i in range(0, 91):
    xa = 56.0 + 0.1 * i
    for k in range(0, 130):
        xb = 56.0 + 0.1 * k
        if xb > 68.91:
            break
        pts = [(24.3, 45.4), (xa, 68.3), (xb, MB_TOP)]
        # straight to the approach point unless the EVM is in the way (approach x > EVM right edge: go around corner)
        evr = xs + EVM_W
        pts += [(evr, evy), app3, j5p1] if app3[0] > evr else [app3, j5p1]
        L = sum(d(pts[q], pts[q + 1]) for q in range(len(pts) - 1))
        if best is None or L < best[0]:
            best = (L, pts)
print("   W3 route %.1f mm (build max %d) via %s" % (best[0], int(math.ceil(1.25 * best[0] / 10 - 1e-9)) * 10,
                                                    [(round(a, 2), round(b, 2)) for a, b in best[1]]))

# (ii) EIB left edge at corridor +x edge + 3.0, pad column 2.0 mm inside
col_ii_board = CORR[1] + 3.0 + 2.0
col_ii = col_ii_board - x0
print("\n(ii) EIB x %.2f-%.2f; pad column board %.2f" % (CORR[1] + 3.0, CORR[1] + 27.0, col_ii_board))
r2 = leads(col_ii, "(ii)")
print("   J5 approach x %.2f inside the corridor band %s: %s" % (j5_app, CORR, CORR[0] <= j5_app <= CORR[1]))

# (iii) EIB at the EVM left edge
print("\n(iii)")
leads(-7.0, "(iii)")

# E1 + E8 + C205 at 100 mm, and the skin-effect note at 85/90 mm
MU0 = 4e-7 * math.pi
RHO = 1.72e-8
A = 0.16e-3
S = 5e-3
C = 100e-9
RDC_M = RHO / (math.pi * A * A)


def rac_rdc(f):
    delta = math.sqrt(RHO / (math.pi * f * MU0))
    k = (1 - 1j) / delta
    z = k * A

    def J(n, x):
        s, term, m = 0, (x / 2) ** n / math.factorial(n), 0
        while True:
            s += term
            m += 1
            term = term * (-(x / 2) ** 2) / (m * (m + n))
            if abs(term) < 1e-18 and m > 5:
                break
        return s
    ratio = (z / 2) * J(0, z) / J(1, z)
    return ratio.real, delta


print("\n28 AWG R_dc %.4f Ohm/m (rho 1.72e-8, a 0.16 mm)" % RDC_M)
for l_mm in (85.0, 90.0, 100.0):
    l = l_mm * 1e-3
    L = MU0 / math.pi * l * math.log(S / A)
    f0 = 1 / (2 * math.pi * math.sqrt(L * C))
    Z0 = math.sqrt(L / C)
    rr, delta = rac_rdc(f0)
    Rw = RDC_M * 2 * l
    Rw20 = RDC_M * (l + 0.020)
    print("  l %3.0f mm: L %.1f nH f0 %.4f MHz Z0 %.4f; delta %.1f um a/delta %.3f Rac/Rdc %.3f (asym %.3f)" % (
        l_mm, L * 1e9, f0 / 1e6, Z0, delta * 1e6, A / delta, rr, A / (2 * delta) + 0.25))
    print("      Q dc %.2f (AWG-table 0.2129 Ohm/m: %.2f); Q ac %.2f; Q dc / ac with E8 at 20 mm %.2f / %.2f; Q with R276 %.4f" % (
        Z0 / (Rw + 0.02), Z0 / (0.2129 * 2 * l + 0.02), Z0 / (Rw * rr + 0.02), Z0 / (Rw20 + 0.02),
        Z0 / (Rw20 * rr + 0.02), Z0 / (Rw + 0.02 + 10.0)))
