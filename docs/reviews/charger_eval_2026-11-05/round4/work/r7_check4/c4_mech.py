"""Check 4 of r7_calc revision 3, item 1: foot tolerance budget, gate, T-A-09 pull, feet effect, Gent f1.

Own code; inputs are the D-F1 / BASIS values, not r7_calc functions.
"""
import math
import random

# ---------------------------------------------------------------- D-F1 tolerance budget of t_bed
HDR, TBED, TBOND = 2.54, 0.30, 0.05
HF = HDR - TBED - TBOND
print("h_f = %.3f" % HF)
GATE = (0.15, 0.45)
for nm, lever in (("FT1", 61.72 - 45.998), ("FT2", 73.25 - 64.484)):
    bow = 0.0075 * lever
    # contributors to t_bed = body - h_f - tape; body +-0.13; bow +-bow; block h_f -0.05..0 -> t_bed +0..+0.05;
    # tape 0..0.05 (nominal 0.05) -> t_bed +0..+0.05
    lo = TBED - 0.13 - bow + 0.0 + 0.0
    hi = TBED + 0.13 + bow + 0.05 + 0.05
    mean = TBED + 0.025 + 0.025
    rss = math.sqrt(0.13 ** 2 + bow ** 2 + 0.025 ** 2 + 0.025 ** 2)
    # exact probability by fine numerical convolution of the four uniforms
    N = 4000
    def unif(a, b):
        return (a, b)
    comps = [(-0.13, 0.13), (-bow, bow), (0.0, 0.05), (0.0, 0.05)]
    # Monte-Carlo with fixed seed, 2e6 samples
    rnd = random.Random(12345)
    n = 2_000_000
    nin = nlo = nhi = 0
    for _ in range(n):
        v = TBED + sum(rnd.uniform(a, b) for a, b in comps)
        if v <= GATE[0]:
            nlo += 1
        elif v >= GATE[1]:
            nhi += 1
        else:
            nin += 1
    print("%s: lever %.3f bow +-%.4f; worst %.3f-%.3f; mean %.3f; RSS +-%.4f -> %.3f-%.3f; MC pass %.2f %% lo %.2f %% hi %.2f %%"
          % (nm, lever, bow, lo, hi, mean, rss, mean - rss, mean + rss, 100 * nin / n, 100 * nlo / n, 100 * nhi / n))

# ---------------------------------------------------------------- beam / bed / pin-load model (own implementation)
E, T, RHO = 20000.0, 1.6, 1850.0
PINS = [(20.998, 36.544 + 2.54 * k) for k in range(12)] + [(45.998, 39.084 + 2.54 * k) for k in range(10)]
xc = sum(p[0] for p in PINS) / 22
yc = sum(p[1] for p in PINS) / 22
Sxx = sum((p[0] - xc) ** 2 for p in PINS)
Syy = sum((p[1] - yc) ** 2 for p in PINS)
print("pin centroid (%.3f, %.3f) Sxx %.1f Syy %.1f" % (xc, yc, Sxx, Syy))


def worst(forces):
    F = sum(f for _, _, f in forces)
    Mx = sum(f * (x - xc) for x, _, f in forces)
    My = sum(f * (y - yc) for _, y, f in forces)
    return max(abs(F / 22 + Mx * (p[0] - xc) / Sxx + My * (p[1] - yc) / Syy) for p in PINS)


def defl(a, x, EI):
    # deflection at a, unit load at x, cantilever clamped at 0 (Roark)
    return a * a * (3 * x - a) / (6 * EI) if x >= a else x * x * (3 * a - x) / (6 * EI)


def R_spring(EI, a, ks, loads):
    d = sum(F * defl(a, x, EI) for x, F in loads)
    return d / (a ** 3 / (3 * EI) + 1 / ks)


TABX = dict(b=12.0, L=65.0 - 45.998, a=61.72 - 45.998, root=48.70 - 45.998, A=6.4, per=2 * (4.0 + 1.6),
            area=16.3 * 12.0, cg=((48.7 + 65.0) / 2, (56.3 + 68.3) / 2), foot=(61.72, 66.705), grip=(65.0, 62.3))
TABY = dict(b=19.86, L=76.0 - 64.484, a=73.25 - 64.484, root=67.14 - 64.484, A=16.0, per=16.0,
            area=19.86 * 8.86 - 0.5, cg=((17.7 + 37.56) / 2, (67.14 + 76.0) / 2), foot=(28.0, 73.25), grip=(28.0, 76.0))
for nm, t in (("tab X", TABX), ("tab Y", TABY)):
    t["EI"] = E * t["b"] * T ** 3 / 12
    t["ks"] = [e * t["A"] / tb for e in (1.0, 3.0) for tb in (0.15, 0.30, 0.45)]
    t["ks4"] = (min(t["ks"]), 1.0 * t["A"] / 0.3, 3.0 * t["A"] / 0.3, max(t["ks"]))
    Lp = t["L"]   # both grips at the tip lever (tab X x 65.00; tab Y y 76.00)
    W30 = 0.8 * t["area"] / 100 * 1e-3 * 9.81 * 30
    sh = [R_spring(t["EI"], t["a"], k, [(Lp, 1.0)]) for k in t["ks4"]]
    s30_tip = [R_spring(t["EI"], t["a"], k, [(t["L"], W30)]) / t["A"] for k in t["ks4"]]
    n = 200
    seg = (t["L"] - t["root"]) / n
    dist = [(t["root"] + (i + 0.5) * seg, W30 / n) for i in range(n)]
    s30_dist = [R_spring(t["EI"], t["a"], k, dist) / t["A"] for k in t["ks4"]]
    plim = min(2 * s30_tip[k] * t["A"] / sh[k] for k in range(4))
    plim_d = min(2 * s30_dist[k] * t["A"] / sh[k] for k in range(4))
    print("%s: EI %.0f W30 %.4f N share %s; 5 N bed kPa %s; ratio %s; p_lim(tip-lumped) %.3f N; p_lim(distributed 30 g) %.3f N"
          % (nm, t["EI"], W30, ["%.3f" % v for v in sh], ["%.0f" % (5 * v / t["A"] * 1e3) for v in sh],
             ["%.2f" % (5 * sh[k] / t["A"] / s30_tip[k]) for k in range(4)], plim, plim_d))
    print("     0.8 N: bed kPa %s ratio(tip) %s ratio(distributed) %s" % (
        ["%.1f" % (0.8 * v / t["A"] * 1e3) for v in sh], ["%.3f" % (0.8 * sh[k] / t["A"] / s30_tip[k]) for k in range(4)],
        ["%.3f" % (0.8 * sh[k] / t["A"] / s30_dist[k]) for k in range(4)]))
    t["W30"] = W30

# pin loads at 30 g and 10 g
cuts = []
for mm in (5.0, 10.0):
    for ra in (0.6, 0.8):
        for g in (10.0, 30.0):
            acc = 9.81 * g
            base = [(xc, yc, mm * 1e-3 * acc)]
            tl = []
            for t in (TABX, TABY):
                W = ra * t["area"] / 100 * 1e-3 * acc
                tl.append((t, W))
            no = base + [(t["cg"][0], t["cg"][1], W) for t, W in tl]
            w0 = worst(no)
            ws = []
            for ke in (1, 2):
                fs = list(no)
                for t, W in tl:
                    n = 200
                    seg = (t["L"] - t["root"]) / n
                    R = R_spring(t["EI"], t["a"], t["ks4"][ke], [(t["root"] + (i + 0.5) * seg, W / n) for i in range(n)])
                    fs.append((t["foot"][0], t["foot"][1], -R))
                ws.append(worst(fs))
            if g == 30.0:
                cuts += [100 * (w0 - w) / w0 for w in ws]
            print("  main %.0f g %.1f g/cm2 %.0f g: %.3f -> %.3f / %.3f" % (mm, ra, g, w0, ws[0], ws[1]))
print("30 g cut %.1f-%.1f %%" % (min(cuts), max(cuts)))
for nm, t in (("tab X", TABX), ("tab Y", TABY)):
    w0 = worst([(t["grip"][0], t["grip"][1], 10.0)])
    out = []
    for k in t["ks4"]:
        R = R_spring(t["EI"], t["a"], k, [(t["L"], 10.0)])
        w = worst([(t["grip"][0], t["grip"][1], 10.0), (t["foot"][0], t["foot"][1], -R)])
        out.append((k, R, w, 100 * (w0 - w) / w0))
    print("%s 10 N push: no foot %.3f; %s" % (nm, w0, "; ".join("ks %.1f R %.2f w %.2f cut %.1f%%" % q for q in out)))

# Gent-corrected propped f1
for nm, t in (("tab X", TABX), ("tab Y", TABY)):
    S = t["A"] / (t["per"] * 0.30)
    gf = 1 + 2 * S * S
    bl, sig = 1.875104, 0.734096
    def phi(x):
        b = bl * x
        return math.cosh(b) - math.cos(b) - sig * (math.sinh(b) - math.sin(b))
    ph = phi(t["a"] / t["L"]) / phi(1.0)
    res = []
    for mf in (1.0, 2.0):
        m = RHO * T * 1e-3 * t["b"] * 1e-3 * t["L"] * 1e-3 * mf
        EIs = t["EI"] * 1e-6
        f1 = bl ** 2 / (2 * math.pi) * math.sqrt(EIs / (m / (t["L"] * 1e-3) * (t["L"] * 1e-3) ** 4))
        K1 = (2 * math.pi * f1) ** 2 * m / 4
        cap = f1 * (4.694091 / bl) ** 2
        fs = [min(cap, f1 * math.sqrt(1 + k * gf * 1e3 * ph * ph / K1)) for k in (t["ks4"][1], t["ks4"][2])]
        res.append((mf, f1, fs, cap))
    print("%s: S %.3f gent x%.2f phi %.3f; %s" % (nm, S, gf, ph, "; ".join("m_f %.0f f1 %.0f propped %.0f-%.0f (cap %.0f)" % (
        mf, f1, fs[0], fs[1], cap) for mf, f1, fs, cap in res)))
