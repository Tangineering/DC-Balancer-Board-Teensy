"""Third independent check: FT2 stiffness, propped f1, 10 N tab Y tip push with the foot; area U; corridor (i) room.

Own code; reads stackup_area.py (the booking source) by runpy, never r7_calc.py.
"""
import contextlib
import io
import math
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- tab Y cantilever
E, TH, WID = 20000.0, 1.6, 37.56 - 17.70
EI = E * WID * TH ** 3 / 12
Y0 = 64.484
a = 73.25 - Y0
L = 76.00 - Y0
ka = 3 * EI / a ** 3
print("tab Y: EI %.1f N mm2, a %.4f, L %.4f, 3EI/a^3 %.2f N/mm, 3EI/L^3 %.2f N/mm" % (EI, a, L, ka, 3 * EI / L ** 3))

AREA = 16.0
KS = sorted({Ee * AREA / t for Ee in (1.0, 3.0) for t in (0.15, 0.30, 0.45)})
print("bed k_s set %s" % ["%.2f" % k for k in KS])

# first mode, Rayleigh with the exact cantilever mode, foot as a spring at a
bl = 1.8751040687
sig = (math.cosh(bl) + math.cos(bl)) / (math.sinh(bl) + math.sin(bl))


def phi(x):
    return math.cosh(bl * x) - math.cos(bl * x) - sig * (math.sinh(bl * x) - math.sin(bl * x))


ph = phi(a / L) / phi(1.0)
rho = 1850e-9  # kg/mm3 -> use SI below
for mf in (1.0, 2.0):
    m_len = 1850.0 * (WID * 1e-3) * (TH * 1e-3) * mf  # kg/m
    EIs = EI * 1e-6
    Lm = L * 1e-3
    w1 = bl ** 2 * math.sqrt(EIs / (m_len * Lm ** 4))
    mmod = 0.25 * m_len * Lm  # modal mass with the tip-normalised mode
    out = []
    for k in (AREA * 1.0 / 0.30, AREA * 3.0 / 0.30):
        w = math.sqrt(w1 ** 2 + k * 1e3 * ph ** 2 / mmod)
        out.append("k %.1f -> %.0f Hz" % (k, w / (2 * math.pi)))
    print("m_f %.0f: unpropped %.0f Hz; phi(a/L) %.4f; propped %s" % (mf, w1 / (2 * math.pi), ph, "; ".join(out)))

# ---------------------------------------------------------------- 10 N tab Y tip push, rigid CR on 22 pin springs
PINS = [(20.998, 36.544 + 2.54 * k) for k in range(12)] + [(45.998, 39.084 + 2.54 * k) for k in range(10)]
xc = sum(p[0] for p in PINS) / 22
yc = sum(p[1] for p in PINS) / 22
Sx = sum((p[0] - xc) ** 2 for p in PINS)
Sy = sum((p[1] - yc) ** 2 for p in PINS)
print("pins: centroid (%.3f, %.3f), Sum dx^2 %.1f, Sum dy^2 %.1f" % (xc, yc, Sx, Sy))


def pinloads(loads):
    """loads: list of (F, x, y), F positive = push toward the MB. Returns worst pin compression."""
    F = sum(f for f, x, y in loads)
    Mx = sum(f * (y - yc) for f, x, y in loads)
    My = sum(f * (x - xc) for f, x, y in loads)
    return max((F / 22 + Mx * (py - yc) / Sy + My * (px - xc) / Sx, (px, py)) for px, py in PINS)


FOOT = (28.00, 73.25)
dfac = a ** 2 * (3 * L - a) / (6 * EI)       # foot-point deflection per unit tip load (cantilever)
cfoot = a ** 3 / (3 * EI)                    # foot-point compliance
for tipx in (27.63, 28.00):
    P = 10.0
    w0 = pinloads([(P, tipx, 76.0)])
    row = []
    for k in KS:
        Ff = P * dfac / (1 / k + cfoot)
        w = pinloads([(P, tipx, 76.0), (-Ff, FOOT[0], FOOT[1])])
        row.append("k %.0f: foot %.2f N, worst %.3f N" % (k, Ff, w[0]))
    print("10 N at (%.2f, 76.00): no foot worst %.3f N at %s; %s" % (tipx, w0[0], w0[1], "; ".join(row)))

# ---------------------------------------------------------------- area booking
SA = os.path.normpath(os.path.join(HERE, "..", "..", "calc", "stackup_area.py"))
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(SA)
CR, CY = g["CR"], g["CY"]
bot = sum(CY[p] for r, p, dnp, s in CR if s == "bottom")
rows = {r: p for r, p, dnp, s in CR}
mv = sum(CY[rows[r]] for r in ("R175", "R109", "R110", "R111", "R112", "R114", "R115"))
DEMAND = 1188.0
top = DEMAND - bot
TU = 1084.2 - math.pi * 1.0 ** 2
BA = 569.1
print("r3 bottom set %.3f, top %.3f (1188 - bottom), moved %.3f; top usable %.2f" % (bot, top, mv, TU))
for nm, t, b in (("r3 kept", top, bot), ("adopted", top + mv, bot - mv)):
    print("  %-8s top %.2f mm2 U %.3f %%; bottom %.2f mm2 U %.3f %% (with my bottom 569.45: %.3f %%)" % (
        nm, t, t / TU * 100, b, b / BA * 100, b / 569.45 * 100))
cm = 48.81 + 10.92
print("  core+R175 top U %.3f %% bottom U %.3f %%" % ((top + cm) / TU * 100, (bot - cm) / BA * 100))
m = (bot * TU - top * BA) / (TU + BA)
print("  balanced split %.2f mm2 -> %.2f %%" % (m, (top + m) / TU * 100))

# ---------------------------------------------------------------- corridor fallback (i)
EVM_W = 88.90
x0 = 88.50 - EVM_W
col = EVM_W + 7.0
eib_hi = x0 + col - 2.0 + 24.0
j5 = x0 + 86.488 + 10.0
shift = max(eib_hi, j5) - (93.47 - 3.0)
xs = x0 - shift
app1 = xs + 2.604 - 10.0
OD = 1.6
bend = 6 * OD + OD / 2
print("(i): shift %.3f, EVM x %.3f (overhang %.3f), W1 J1 approach x %.3f; bend 6xOD + OD/2 = %.2f -> rounded up %.1f; room %.2f"
      % (shift, xs, -xs, app1, bend, math.ceil(bend * 2) / 2, -app1 + math.ceil(bend * 2) / 2))
