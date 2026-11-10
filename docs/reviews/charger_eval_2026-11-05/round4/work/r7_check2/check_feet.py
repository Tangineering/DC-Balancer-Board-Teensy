"""Item 2: adopted FT1/FT2 against the D3 rule; tolerances by explicit moves; larger sizes; stiffness and f1."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo2 import (B, FEATS, VIAS, PARTS, margins, min_margin, grow, body, tolerances, near, d_rect_rect)  # noqa

ZONE_X = (44.0, 52.0, 70.0, 73.0)
ZONE_Y = (12.0, 60.0, 43.0, 82.0)
FX = near(ZONE_X, FEATS, 0.0)
VX = near(ZONE_X, VIAS, 0.0)
FY = near(ZONE_Y, FEATS, 0.0)
VY = near(ZONE_Y, VIAS, 0.0)
KX = dict(feats=FX, vias=VX)
KY = dict(feats=FY, vias=VY)
print("features near tab X: %d copper, %d vias; near tab Y: %d copper, %d vias" % (len(FX), len(VX), len(FY), len(VY)))


def report(name, cx, cy, w, h, tab, kw):
    R = body(cx, cy, w, h)
    ms = sorted(margins(R, tab, **kw))
    print("\n%s %.1f x %.1f at (%.2f, %.2f): body x %.3f-%.3f y %.3f-%.3f" % ((name, w, h, cx, cy) + R[0::2] + R[1::2]))
    for m, lab in ms[:5]:
        print("   margin %+.4f  %s" % (m, lab))
    tol = tolerances(R, tab, **kw)
    print("   tolerances t %s, tx %s, ty %s" % tuple("%.4f" % v for v in tol) if tol else "   NOT COMPLIANT")
    return R, tol


def moves(R, tab, kw, t, tx, ty, eps=0.005):
    worst = 1e9
    for dx in (-tx, 0.0, tx):
        for dy in (-t, 0.0, t):
            m = min_margin((R[0] + dx, R[1] + dy, R[2] + dx, R[3] + dy), tab, **kw)
            worst = min(worst, m)
    for dx in (-t, 0.0, t):
        for dy in (-ty, 0.0, ty):
            m = min_margin((R[0] + dx, R[1] + dy, R[2] + dx, R[3] + dy), tab, **kw)
            worst = min(worst, m)
    beyond = {}
    for lab, dx, dy in (("+x", tx + eps, 0), ("-x", -tx - eps, 0), ("+y", 0, ty + eps), ("-y", 0, -ty - eps)):
        beyond[lab] = min_margin((R[0] + dx, R[1] + dy, R[2] + dx, R[3] + dy), tab, **kw)
    print("   explicit moves within (+-tx, +-t) and (+-t, +-ty): worst margin %+.4f" % worst)
    print("   one move %.3f mm beyond each half-range: %s" % (eps, ", ".join("%s %+.4f" % kv for kv in beyond.items())))


R1, (t1, tx1, ty1) = report("FT1 adopted", 61.72, 66.70, 4.0, 1.6, "X", KX)
moves(R1, "X", KX, t1, tx1, ty1)
print("   nearest part box: %.3f %s" % min((d_rect_rect(R1, bx), en) for en, bx in PARTS))
# nearest non-GND copper at zero growth
print("   nearest non-GND copper rim: %.4f (%s)" % min((m + 1.0, l) for m, l in margins(R1, "X", **KX) if l.startswith("copper")))
print("   keep-out (body + 0.5): x %.2f-%.2f y %.2f-%.2f; RTV lane to the top edge y 68.30" % grow(R1, 0.5, 0.5))

R2, (t2, tx2, ty2) = report("FT2 adopted", 28.00, 71.32, 4.0, 4.0, "Y", KY)
moves(R2, "Y", KY, t2, tx2, ty2)
print("   nearest part box: %.3f %s" % min((d_rect_rect(R2, bx), en) for en, bx in PARTS))
cop = [(m + 1.0, l) for m, l in margins(R2, "Y", **KY) if l.startswith("copper")]
print("   nearest non-GND copper rim: %.4f (%s)" % min(cop))
print("   keep-out (body + 0.5): x %.2f-%.2f y %.2f-%.2f" % grow(R2, 0.5, 0.5))
report("FT2 far-edge sensitivity", 28.00, 73.25, 4.0, 4.0, "Y", KY)
report("FT2 first run", 27.63, 73.50, 4.0, 4.0, "Y", KY)
report("FT1 alternative A", 62.00, 66.70, 4.0, 2.0, "X", KX)
report("FT1 4.0x1.7 (calc best)", 61.78, 66.70, 4.0, 1.7, "X", KX)
report("FT1 3.9x1.7 (calc best)", 61.82, 66.70, 3.9, 1.7, "X", KX)
report("FT1 3.8x1.7 (calc best)", 61.88, 66.70, 3.8, 1.7, "X", KX)

# -------- screening of larger sizes over the whole tab X: m0 (zero-growth margin) is an upper bound of t
print("\nScreen of tab X (0.05 mm centre grid): best zero-growth margin m0 (upper bound of t) per size")
for w, h in ((4.0, 1.7), (3.8, 1.7), (3.6, 1.8), (3.0, 2.2), (4.0, 1.6), (3.0, 1.6)):
    best = (-9, None)
    nx = int(round((65.0 - 48.7 - w) / 0.05)) + 1
    ny = int(round((68.3 - 56.3 - h) / 0.05)) + 1
    for i in range(nx):
        cx = 48.7 + w / 2 + i * 0.05
        for j in range(ny):
            cy = 56.3 + h / 2 + j * 0.05
            R = body(cx, cy, w, h)
            fl = near(R, FX, 3.0)
            vl = near(R, VX, 1.0)
            m = min_margin(R, "X", feats=fl, vias=vl)
            if m > best[0]:
                best = (m, (round(cx, 3), round(cy, 3)))
    print("   %.1f x %.1f (%.2f mm2): best m0 %+.4f at %s -> %s" % (
        w, h, w * h, best[0], best[1], "can reach 0.25" if best[0] >= 0.25 else "cannot reach t 0.25"))

# -------- stiffness, bed, f1
E, TH = 20000.0, 1.6
for nm, wid, a, L, A in (("tab X", 12.0, 61.72 - 45.998, 65.0 - 45.998, 6.4), ("tab Y", 19.86, 71.32 - 64.484, 76.0 - 64.484, 16.0)):
    EI = E * wid * TH ** 3 / 12
    print("\n%s: EI %.0f N mm2; a %.3f mm, L %.3f mm; 3EI/a^3 %.1f N/mm; tip 3EI/L^3 %.1f N/mm" % (
        nm, EI, a, L, 3 * EI / a ** 3, 3 * EI / L ** 3))
    ks = [Ee * A / t for Ee in (1.0, 3.0) for t in (0.15, 0.30, 0.45)]
    per = 2 * (math.sqrt(A) * 2) if nm == "tab Y" else 2 * (4.0 + 1.6)
    print("   bed k_s range %.1f-%.1f N/mm (nominal t 0.30: %.1f-%.1f); Gent S at 0.30 %.2f" % (
        min(ks), max(ks), 1.0 * A / 0.3, 3.0 * A / 0.3, A / (per * 0.3)))
    # first mode: uniform cantilever, rho_FR4 1850 kg/m3 (back-solved, m_f 1), Rayleigh with tip-normalised modal mass
    bl = 1.875104
    sig = (math.cosh(bl) + math.cos(bl)) / (math.sinh(bl) + math.sin(bl))
    phi = lambda x: (math.cosh(bl * x) - math.cos(bl * x) - sig * (math.sinh(bl * x) - math.sin(bl * x)))  # noqa
    ph = phi(a / L) / phi(1.0)
    rho = 1850.0
    m_len = rho * wid * TH * 1e-6           # kg/m
    EIs = EI * 1e-6                         # N m2
    Lm = L * 1e-3
    f1 = bl ** 2 / (2 * math.pi) * math.sqrt(EIs / (m_len * Lm ** 4))
    mmod = 0.25 * m_len * Lm
    k_nom = 1.0 * A / 0.3 * 1e3
    fp = math.sqrt((2 * math.pi * f1) ** 2 + k_nom * ph ** 2 / mmod) / (2 * math.pi)
    print("   phi(a/L) %.3f; f1 unpropped (rho 1850) %.0f Hz; propped at k_s %.1f N/mm (E 1 MPa, t 0.30): %.0f Hz" % (
        ph, f1, k_nom / 1e3, fp))
