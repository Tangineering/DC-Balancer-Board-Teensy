"""Sim 3: CR comparators U102 (H1), U103 (UVB), U119 (FCC_OFF) and U120 (FCC_ON).

Trip points and hysteresis at nominal, Monte Carlo over resistor tolerance and TCR, TLV3012B offset / hysteresis /
CMRR / PSRR / REF tolerance and drift, CR 3V3 rail (Teensy 3V3 through R175) and temperature (-20..+70 C), the same
for the VR-4 H1+ ratio option (R110 44.2 kOhm with R112 rescaled), and V-MOT over-range sweeps (0-40 V) with the
behavioural TLV3012B model and with the TI PSpice model of the non-B TLV3012.

Run:  C:\\Users\\ricky\\miniforge3\\python.exe run.py            (everything; about 13 min on 8 workers)
      C:\\Users\\ricky\\miniforge3\\python.exe run.py --quick    (N = 400 Monte Carlo, for a smoke test)

Outputs (this folder): decks/*.cir, csv/*.csv, png/*.png, summary.json. Console prints are ASCII only.
"""
import os
import re
import sys
import json
import math
import time
import argparse
import concurrent.futures as cf

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
R8 = os.path.dirname(SIM)
sys.path.insert(0, os.path.join(SIM, "common"))
from ngspice_run import run_deck, ngspice_version  # noqa: E402

CRNET = os.path.join(R8, "cr", "cr.net")
MODELS = os.path.join(SIM, "models")
LIB_B = os.path.join(MODELS, "tlv3012b_behav.lib").replace("\\", "/")
LIB_TI = os.path.join(MODELS, "tlv3012_ti_sboc081a.lib").replace("\\", "/")
LIB_D = os.path.join(MODELS, "bav199_behav.lib").replace("\\", "/")
DECKS = os.path.join(HERE, "decks")
CSV = os.path.join(HERE, "csv")
PNG = os.path.join(HERE, "png")
for d in (DECKS, CSV, PNG):
    os.makedirs(d, exist_ok=True)

SEED = 20261114


def log(*a):
    print(*a, flush=True)


# =============================================================================================== 1. netlist values
def parse_crnet(path):
    """Return (values {ref: value string}, pins {ref: {pin: net}}) from the KiCad netlist."""
    s = open(path, encoding="utf-8").read()
    values = dict(re.findall(r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)', s))
    pins = {}
    for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]+)"\)(.*?)\)\)\s*(?=\(net |\)\s*\)\s*$)', s, re.S):
        net = m.group(1).lstrip("/")
        for r, p in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2)):
            pins.setdefault(r, {})[p] = net
    return values, pins


def rval(v):
    """'487k 0.1%' -> 487e3."""
    tok = v.split()[0]
    mult = {"k": 1e3, "M": 1e6, "m": 1e-3}
    if tok[-1] in mult:
        return float(tok[:-1]) * mult[tok[-1]]
    return float(tok)


VALUES, PINS = parse_crnet(CRNET)

# Topology simulated below, asserted against cr.net (pin -> net). 'GND' and '3V3' are the CR ground and rail.
EXPECT = {
    "U102": {"1": "H1", "2": "GND", "3": "N_H1P", "4": "N_H1M", "6": "3V3"},       # 5 REF unconnected
    "R109": {"1": "T1_VMOT", "2": "N_H1P"}, "R110": {"1": "N_H1P", "2": "GND"},
    "R113": {"1": "H1", "2": "N_H1P"},
    "R111": {"1": "T2C", "2": "N_H1M"}, "R112": {"1": "N_H1M", "2": "GND"},
    "D104": {"1": "GND", "2": "3V3", "3": "N_H1P"}, "D105": {"1": "GND", "2": "3V3", "3": "N_H1M"},
    "U103": {"1": "UVB", "2": "GND", "3": "N_UVP", "4": "REF103", "5": "REF103", "6": "3V3"},
    "R114": {"1": "T2C", "2": "N_UVP"}, "R115": {"1": "N_UVP", "2": "GND"}, "R116": {"1": "UVB", "2": "N_UVP"},
    "D106": {"1": "GND", "2": "3V3", "3": "N_UVP"},
    "U119": {"1": "FCCN", "2": "GND", "3": "N_FOP", "4": "N_FOM", "5": "REF119", "6": "3V3"},
    "R184": {"1": "REF119", "2": "N_FOP"}, "R185": {"1": "N_FOP", "2": "GND"},
    "R186": {"1": "FCC", "2": "N_FOM"}, "R187": {"1": "N_FOM", "2": "3V3"},
    "R122": {"1": "FCC_TAP", "2": "FCC"},
    "U120": {"1": "FCC_ON", "2": "GND", "3": "N_FNP", "4": "REF120", "5": "REF120", "6": "3V3"},
    "R188": {"1": "FCC", "2": "N_FNP"}, "R189": {"1": "N_FNP", "2": "GND"},
    "R126": {"1": "H1", "2": "H1_RB"},
    "R175": {"1": "T6_3V3", "2": "3V3"},
    "J102": {"1": "T2C", "7": "T1_VMOT", "6": "T6_3V3", "5": "H1_RB", "4": "FCC_TAP"},
}
for ref, pm in EXPECT.items():
    for p, n in pm.items():
        got = PINS.get(ref, {}).get(p)
        assert got == n, "cr.net mismatch %s.%s: expected %s, got %s" % (ref, p, n, got)
assert PINS["U102"].get("5", "").startswith("unconnected"), "U102 REF expected unconnected"

R = {r: rval(VALUES[r]) for r in ("R109", "R110", "R111", "R112", "R113", "R114", "R115", "R116", "R122",
                                  "R126", "R175", "R184", "R185", "R186", "R187", "R188", "R189")}
# MB-side tap resistors (not in cr.net): R170 (T1, V-MOT at C-D6 pad 1) and R171 (T2, VBUS at C-D2 pad 1), 10.0 kOhm
# 0.1 % 25 ppm/K 0805 (design doc B.2 line 1860; README.md line 640; bom_2026-11-13/README.md line 116:
# TNPW080510K0BEEA / ERA-6AEB103V). MB nets: Scale_Car_Board_20260624.sch line 8852 (C-D6 pin 1 = V-MOT) and 8784
# (C-D2 pin 1 = VBUS).
R["R170"] = 10.0e3
R["R171"] = 10.0e3
# Teensy pin 34 input that loads H1_RB: 100 kOhm pull-down ASSUMPTION (design doc H.15, R9.H15 row).
R["RPIN34"] = 100e3

# Tolerance / TCR classes from the ordering BOM (bom_2026-11-13/cr_bom.csv lines 25-39): 0.1 %/25 ppm thin film,
# 1 %/100 ppm thick film. R122, R126 and R175 are CRCW 1 %/100 ppm (cr_bom.csv lines 22, 34).
TOL = {r: (0.001, 25e-6) for r in ("R109", "R110", "R111", "R112", "R114", "R115", "R170", "R171")}
TOL.update({r: (0.01, 100e-6) for r in ("R113", "R116", "R122", "R126", "R175", "R184", "R185", "R186", "R187",
                                         "R188", "R189")})
TOL["RPIN34"] = (0.0, 0.0)

# ----------------------------------------------------------------------------------------------- TLV3012B limits
# SBOS300C 6.9 (TLV3012B): VOS +-9 mV over -40..125 C (+-6 mV at 25 C), VHYS 2-8 mV, CMRR 54 dB min, PSRR 1 mV/V max,
# REF 1.223-1.260 V at 25 C with 100 ppm/C max drift, REF sourcing load regulation 1 mV/mA max, IQ 2.4-3.6 uA,
# VOH/VOL 90-200 mV from rail at 5 mA -> 18-40 ohm.
VOS_MAX = 9e-3
HYS_RNG = (2e-3, 8e-3)
KCM_MAX = 10 ** (-54 / 20)     # 1.995 mV of offset per V of common mode
KPS_MAX = 1e-3
VREF_RNG = (1.223, 1.260)
REF_TC = 100e-6
RREF_RNG = (0.36, 1.0)
ROUT_RNG = (18.0, 40.0)
IQ_RNG = (2.4e-6, 3.6e-6)
# CR 3V3 rail: Teensy 3V3 3.135-3.465 V (ASSUMPTION, r9_calc.py line 38 / r7_calc.py V_IO_RNG) through R175 68 ohm,
# CR + EIB base load other than the four comparator networks 0.35-1.00 mA (design doc H.24(a) basis).
VT_RNG = (3.135, 3.465)
ILOAD_RNG = (0.35e-3, 1.00e-3)
# Temperature: -20..+70 C = 25 +- 45 C, the same excursion as r3_calc.py DT_CR = (0, 45) used with +-drift.
T_RNG = (-20.0, 70.0)

# VBUS levels for the H1 trips: 15.2 / 15.9 / 16.39 V (design doc H.1 basis) and 19.5 V, the top of the H.1 guard row
# (VBUS 15.2-19.5 V); 19.5 V was added in the check round so that the guard is also checked statistically there.
VBUS_LEVELS = (15.2, 15.9, 16.39, 19.5)
# PSRR reference supply of the offset term KPS x (V+ - PS_REF). SBOS300C 6.9 specifies VOS (+-9 mV, -40..125 C) under
# the table condition 'VS = 1.8 V and 5.5 V' and PSRR over VS 1.65-5.5 V, so the +-9 mV bound already holds at both
# supply extremes; a linear supply dependence then keeps VOS inside +-9 mV at every rail in between, and the KPS term
# is extra margin. ASSUMPTION: reference 3.3 V (the CR rail is 3.06-3.47 V, so the term adds at most +-0.24 mV);
# psref_sweep() repeats the worst case with the reference at 1.8 V and 5.5 V and with the term removed.
PS_REF = 3.3
COMPS = ("U102", "U103", "U119", "U120")


# =============================================================================================== 2. VR-4 option
def t2c_gain(r171, r111, r112, r114, r115):
    """VBUS -> T2C gain with the H1- and UVB dividers loading T2C (R116 ignored, used only for the ratio)."""
    rl = 1 / (1 / (r111 + r112) + 1 / (r114 + r115))
    return rl / (rl + r171)


def ratio_minus(r112, r111=None):
    r111 = R["R111"] if r111 is None else r111
    return t2c_gain(R["R171"], r111, r112, R["R114"], R["R115"]) * r112 / (r111 + r112)


def ratio_plus(r110):
    return r110 / (R["R170"] + R["R109"] + r110)


E192 = [100, 101, 102, 104, 105, 106, 107, 109, 110, 111, 113, 114, 115, 117, 118, 120, 121, 123, 124, 126, 127,
        129, 130, 132, 133, 135, 137, 138, 140, 142, 143, 145, 147, 149, 150, 152, 154, 156, 158, 160, 162, 164, 165,
        167, 169, 172, 174, 176, 178, 180, 182, 184, 187, 189, 191, 193, 196, 198, 200, 203, 205, 208, 210, 213, 215,
        218, 221, 223, 226, 229, 232, 234, 237, 240, 243, 246, 249, 252, 255, 258, 261, 264, 267, 271, 274, 277, 280,
        284, 287, 291, 294, 298, 301, 305, 309, 312, 316, 320, 324, 328, 332, 336, 340, 344, 348, 352, 357, 361, 365,
        370, 374, 379, 383, 388, 392, 397, 402, 407, 412, 417, 422, 427, 432, 437, 442, 448, 453, 459, 464, 470, 475,
        481, 487, 493, 499, 505, 511, 517, 523, 530, 536, 542, 549, 556, 562, 569, 576, 583, 590, 597, 604, 612, 619,
        626, 634, 642, 649, 657, 665, 673, 681, 690, 698, 706, 715, 723, 732, 741, 750, 759, 768, 777, 787, 796, 806,
        816, 825, 835, 845, 856, 866, 876, 887, 898, 909, 920, 931, 942, 953, 965, 976, 988]


def vr4_option():
    k0 = ratio_minus(R["R112"]) / ratio_plus(R["R110"])        # present ratio of ratios ("1.079")
    r110n = 44.2e3
    target = k0 * ratio_plus(r110n)
    lo, hi = 10e3, 100e3
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if ratio_minus(mid) < target:
            lo = mid
        else:
            hi = mid
    exact = 0.5 * (lo + hi)
    cands = [m * 10 ** e for e in (1, 2, 3) for m in E192]
    cands = [c for c in cands if 30e3 < c < 80e3]
    best = min(cands, key=lambda c: abs(ratio_minus(c) / ratio_plus(r110n) - k0))
    return dict(k0=k0, rp0=ratio_plus(R["R110"]), rm0=ratio_minus(R["R112"]), r110n=r110n,
                rpn=ratio_plus(r110n), r112_exact=exact, r112n=best, rmn=ratio_minus(best),
                kn=ratio_minus(best) / ratio_plus(r110n))


OPT = vr4_option()
DESIGNS = {"baseline": dict(R110=R["R110"], R112=R["R112"]),
           "opt08": dict(R110=OPT["r110n"], R112=OPT["r112n"])}


# =============================================================================================== 3. samples
def nominal_params(basis="typ"):
    p = {"T": 25.0, "Vt": 3.30, "Iload": 0.70e-3}
    for r in R:
        p[r] = 1.0                      # multiplicative deviation (tolerance x TCR)
    for c in COMPS:
        p[c] = dict(VOS=0.0, HYS=6e-3, KCM=0.0, KPS=0.0, VREF=1.242, RREF=0.36, ROUT=18.0, IQ=2.4e-6, INDET=0)
    if basis == "doc":                  # the r3_calc.py nominal basis: 5 mV hysteresis, rail 3.30 V, no base load
        p["Iload"] = 0.0
        for c in COMPS:
            p[c]["HYS"] = 5e-3
            p[c]["ROUT"] = 1e-3
    return p


def sample_params(n, rng, dist="uniform"):
    """Monte Carlo draws. dist 'uniform': uniform over the full datasheet/BOM limits (primary); 'gauss': normal with
    sigma = limit/3, truncated at the limit (sensitivity variant, analytic model only)."""
    def u(lo, hi, size=n):
        if dist == "uniform":
            return rng.uniform(lo, hi, size)
        c, h = 0.5 * (lo + hi), 0.5 * (hi - lo)
        return c + h * np.clip(rng.normal(0, 1 / 3, size), -1, 1)

    P = {"T": rng.uniform(*T_RNG, n), "Vt": u(*VT_RNG), "Iload": u(*ILOAD_RNG)}
    for r, (tol, tcr) in TOL.items():
        P[r] = (1 + u(-tol, tol)) * (1 + u(-tcr, tcr) * (P["T"] - 25.0)) if tol else np.ones(n)
    for c in COMPS:
        P[c] = dict(VOS=u(-VOS_MAX, VOS_MAX), HYS=u(*HYS_RNG), KCM=u(-KCM_MAX, KCM_MAX), KPS=u(-KPS_MAX, KPS_MAX),
                    VREF=u(*VREF_RNG) * (1 + u(-REF_TC, REF_TC) * (P["T"] - 25.0)), RREF=u(*RREF_RNG),
                    ROUT=u(*ROUT_RNG), IQ=u(*IQ_RNG), INDET=np.zeros(n, dtype=int))
    return P


def pick(P, i):
    q = {k: (float(v[i]) if not isinstance(v, dict) else None) for k, v in P.items()}
    for c in COMPS:
        q[c] = {k: float(v[i]) for k, v in P[c].items()}
    return q


# =============================================================================================== 4. decks
def rv(p, design, name):
    base = DESIGNS[design].get(name, R.get(name))
    return base * p[name]


def libs(model):
    """Include lines: the TI library only for decks that instantiate it (it needs PSpice compatibility mode)."""
    out = ['.include "%s"' % LIB_B, '.include "%s"' % LIB_D]
    if model in ("ti", "ti102"):
        out.insert(0, '.include "%s"' % LIB_TI)
    return out


def comp_line(name, ref, inp, inm, vp, out, refn, cp, model):
    if model == "ti" or (model == "ti102" and ref == "U102"):
        return "X%s %s %s %s 0 %s %s TLV3012" % (name, inp, inm, vp, out, refn)
    return ("X%s %s %s %s 0 %s %s TLV3012B params: VOS=%.6g HYS=%.6g KCM=%.6g KPS=%.6g VREF=%.7g RREF=%.4g "
            "ROUT=%.4g IQ=%.4g INDET=%d" % (name, inp, inm, vp, out, refn, cp["VOS"], cp["HYS"], cp["KCM"],
                                             cp["KPS"], cp["VREF"], cp["RREF"], cp["ROUT"], cp["IQ"],
                                             int(cp["INDET"])))


def board(k, p, design, model="behav", bav="BAV199", vt=None, iload=None):
    """One CR instance (suffix _k): rail, U102, U103, U119, U120 and their networks. Shared stimulus nodes: vmot,
    vbus, fcctap. Values: cr.net (asserted above); deviations from p."""
    s = "_%d" % k
    vt = p["Vt"] if vt is None else vt
    iload = p["Iload"] if iload is None else iload
    L = ["* ---- board instance %d (T = %.2f C)" % (k, p["T"]),
         "VT%s t6%s 0 %.6f" % (s, s, vt),
         "R175%s t6%s v33%s %.6g" % (s, s, s, rv(p, design, "R175")),
         "IL%s v33%s 0 %.6g" % (s, s, iload),
         # H1 (U102): T1 -> R170 (MB) -> R109 -> N_H1P; R110 to GND; R113 OUT -> IN+; D104
         "R170%s vmot t1%s %.6g" % (s, s, rv(p, design, "R170")),
         "R109%s t1%s h1p%s %.6g" % (s, s, s, rv(p, design, "R109")),
         "R110%s h1p%s 0 %.6g" % (s, s, rv(p, design, "R110")),
         "R113%s h1%s h1p%s %.6g" % (s, s, s, rv(p, design, "R113")),
         "XD104%s 0 d104k%s h1p%s %s" % (s, s, s, bav),
         "VD104%s d104k%s v33%s 0" % (s, s, s),
         # T2 -> R171 (MB) -> T2C; R111/R112 to H1-; R114/R115 to UVB+; R116 OUT -> IN+
         "R171%s vbus t2c%s %.6g" % (s, s, rv(p, design, "R171")),
         "R111%s t2c%s h1m%s %.6g" % (s, s, s, rv(p, design, "R111")),
         "R112%s h1m%s 0 %.6g" % (s, s, rv(p, design, "R112")),
         "XD105%s 0 v33%s h1m%s %s" % (s, s, s, bav),
         comp_line("U102" + s, "U102", "h1p" + s, "h1m" + s, "v33" + s, "h1" + s, "ref102" + s, p["U102"], model),
         "R126%s h1%s h1rb%s %.6g" % (s, s, s, rv(p, design, "R126")),
         "RP34%s h1rb%s 0 %.6g" % (s, s, R["RPIN34"]),
         "R114%s t2c%s uvp%s %.6g" % (s, s, s, rv(p, design, "R114")),
         "R115%s uvp%s 0 %.6g" % (s, s, rv(p, design, "R115")),
         "R116%s uvb%s uvp%s %.6g" % (s, s, s, rv(p, design, "R116")),
         "XD106%s 0 v33%s uvp%s %s" % (s, s, s, bav),
         comp_line("U103" + s, "U103", "uvp" + s, "ref103" + s, "v33" + s, "uvb" + s, "ref103" + s, p["U103"], model),
         # FCC tap: FCC_TAP -> R122 -> FCC; U119 IN+ = REF/3 (R184/R185), IN- = FCC via R186, R187 to 3V3
         "R122%s fcctap fcc%s %.6g" % (s, s, rv(p, design, "R122")),
         "R184%s ref119%s fop%s %.6g" % (s, s, s, rv(p, design, "R184")),
         "R185%s fop%s 0 %.6g" % (s, s, rv(p, design, "R185")),
         "R186%s fcc%s fom%s %.6g" % (s, s, s, rv(p, design, "R186")),
         "R187%s fom%s v33%s %.6g" % (s, s, s, rv(p, design, "R187")),
         comp_line("U119" + s, "U119", "fop" + s, "fom" + s, "v33" + s, "fccn" + s, "ref119" + s, p["U119"], model),
         # U120: IN+ = FCC x R189/(R188+R189); IN- = own REF
         "R188%s fcc%s fnp%s %.6g" % (s, s, s, rv(p, design, "R188")),
         "R189%s fnp%s 0 %.6g" % (s, s, rv(p, design, "R189")),
         comp_line("U120" + s, "U120", "fnp" + s, "ref120" + s, "v33" + s, "fccon" + s, "ref120" + s, p["U120"], model),
         ]
    if model == "ti":
        # the TI model's REF pin is an ideal source to node 0 inside the subcircuit; U102 REF is unconnected (B.8)
        pass
    return L


# Stimulus (quasi-static: the decks carry no input filter capacitors, C106-C108 and C130 do not change DC trips)
LO_K, HI_K = 1.040, 1.125     # V-MOT ramp window as a multiple of VBUS
UVB_HI, UVB_LO = 15.0, 12.0


def stimulus():
    """PWL for vmot, vbus, fcctap. Time unit us."""
    vm = [(0, 0.0)]
    vb = [(0, VBUS_LEVELS[0])]
    t = 0.0
    events = {}
    for j, v in enumerate(VBUS_LEVELS):
        if j > 0:
            vb += [(t, VBUS_LEVELS[j - 1]), (t + 5, v)]
        vm += [(t + 5, vm[-1][1]), (t + 10, LO_K * v), (t + 60, HI_K * v), (t + 110, LO_K * v)]
        events[v] = (t + 10, t + 110)
        t += 110
    # UVB stage
    vm += [(t + 5, 0.0)]
    vb += [(t, VBUS_LEVELS[-1]), (t + 10, UVB_HI), (t + 130, UVB_LO), (t + 250, UVB_HI)]
    t_end = t + 260
    fc = [(0, 0.0), (200, 2.1), (400, 0.0), (t_end, 0.0)]
    vm += [(t_end, 0.0)]
    vb += [(t_end, UVB_HI)]
    return vm, vb, fc, t_end


def pwl(pts):
    return "PWL(" + " ".join("%.6gu %.6g" % (a, b) for a, b in pts) + ")"


def mc_deck(ps, design, title, tmax_ns=20, model="behav"):
    vm, vb, fc, t_end = stimulus()
    L = ["* %s" % title, *libs(model),
         "VMOT vmot 0 " + pwl(vm), "VBUS vbus 0 " + pwl(vb), "VFCC fcctap 0 " + pwl(fc)]
    meas = []
    for k, p in enumerate(ps):
        L += board(k, p, design, model)
        s = "_%d" % k
        for j, v in enumerate(VBUS_LEVELS):
            meas.append(".meas tran h1r%d%s FIND v(vmot) WHEN v(h1%s)=1.5 RISE=%d" % (j, s, s, j + 1))
            meas.append(".meas tran h1f%d%s FIND v(vmot) WHEN v(h1%s)=1.5 FALL=%d" % (j, s, s, j + 1))
        meas += [".meas tran uvbf%s FIND v(vbus) WHEN v(uvb%s)=1.5 FALL=1" % (s, s),
                 ".meas tran uvbr%s FIND v(vbus) WHEN v(uvb%s)=1.5 RISE=1" % (s, s),
                 ".meas tran focr%s FIND v(fcctap) WHEN v(fccn%s)=1.5 FALL=1" % (s, s),   # FCC rising: FCCN falls
                 ".meas tran focrm%s FIND v(fom%s) WHEN v(fccn%s)=1.5 FALL=1" % (s, s, s),
                 ".meas tran focf%s FIND v(fcctap) WHEN v(fccn%s)=1.5 RISE=1" % (s, s),
                 ".meas tran focfm%s FIND v(fom%s) WHEN v(fccn%s)=1.5 RISE=1" % (s, s, s),
                 ".meas tran fonr%s FIND v(fcctap) WHEN v(fccon%s)=1.5 RISE=1" % (s, s),
                 ".meas tran fonrn%s FIND v(fcc%s) WHEN v(fccon%s)=1.5 RISE=1" % (s, s, s),
                 ".meas tran fonf%s FIND v(fcctap) WHEN v(fccon%s)=1.5 FALL=1" % (s, s),
                 ".meas tran fonfn%s FIND v(fcc%s) WHEN v(fccon%s)=1.5 FALL=1" % (s, s, s),
                 ".meas tran rail%s AVG v(v33%s) FROM=1u TO=5u" % (s, s)]
    L += meas
    L += [".options reltol=1e-5 abstol=1e-12 vntol=1e-7 method=gear",
          ".tran %gn %gu 0 %gn" % (tmax_ns, t_end, tmax_ns), ".end"]
    return "\n".join(L) + "\n"


MEAS_KEYS = (["h1r%d" % j for j in range(len(VBUS_LEVELS))] + ["h1f%d" % j for j in range(len(VBUS_LEVELS))] +
             ["uvbf", "uvbr", "focr", "focrm", "focf", "focfm", "fonr", "fonrn", "fonf", "fonfn", "rail"])


def run_batch(args):
    ps, design, tag, model, ngb = args
    deck = mc_deck(ps, design, tag, model=model)
    path = os.path.join(DECKS, tag + ".cir")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(deck)
    t0 = time.time()
    r = run_deck(deck, vectors=["time"], ngbehavior=ngb, timeout_s=1800)
    out = np.full((len(ps), len(MEAS_KEYS)), np.nan)
    for k in range(len(ps)):
        for j, key in enumerate(MEAS_KEYS):
            out[k, j] = r.meas.get("%s_%d" % (key, k), np.nan)
    return tag, r.ok, [e for e in r.errors][:5], out, time.time() - t0


def spice_mc(P, n, design, batch, workers, tag0):
    ps = [pick(P, i) for i in range(n)]
    jobs = [(ps[i:i + batch], design, "%s_%s_b%03d" % (tag0, design, i // batch), "behav", None)
            for i in range(0, n, batch)]
    res = np.full((n, len(MEAS_KEYS)), np.nan)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for tag, ok, errs, out, dt in ex.map(run_batch, jobs):
            b = int(tag.split("_b")[-1])
            res[b * batch:b * batch + len(out)] = out
            log("  %s ok=%s %.1f s missing=%d %s" % (tag, ok, dt, int(np.isnan(out).sum()), errs[:1]))
    # keep only the first deck of each set on disk (the decks are regenerated deterministically from the seed)
    for f in os.listdir(DECKS):
        if f.startswith("%s_%s_b" % (tag0, design)) and not f.endswith("_b000.cir"):
            os.remove(os.path.join(DECKS, f))
    return {key: res[:, j] for j, key in enumerate(MEAS_KEYS)}


# =============================================================================================== 5. analytic model
def analytic(P, design, n):
    """Independent nodal solution of every trip (numpy), same parameters as the SPICE decks. Rail from the same
    linear feed (Teensy - R175 x (base load + network currents)); BAV199 leakage and IB neglected (pA class)."""
    g = lambda name: np.asarray(DESIGNS[design].get(name, R.get(name))) * P[name]
    r170, r109, r110, r113 = g("R170"), g("R109"), g("R110"), g("R113")
    r171, r111, r112, r114, r115, r116 = g("R171"), g("R111"), g("R112"), g("R114"), g("R115"), g("R116")
    r122, r184, r185, r186, r187, r188, r189 = g("R122"), g("R184"), g("R185"), g("R186"), g("R187"), g("R188"), g("R189")
    r126, r175 = g("R126"), g("R175")
    out = {}
    # rail: base load + comparator IQ + typical network currents into GND (evaluated at VBUS 15.9 V, UVB HIGH,
    # FCC 0): a few tens of uA x 68 ohm -> mV-class; iterated once.
    iq = sum(P[c]["IQ"] for c in COMPS)
    rail = P["Vt"] - r175 * (P["Iload"] + iq)
    for _ in range(3):
        i_ref = P["U119"]["VREF"] / (r184 + r185)
        i_r187 = rail / (r186 + r187 + r122)
        i_h1 = 0.0
        rail = P["Vt"] - r175 * (P["Iload"] + iq + i_ref + i_r187 + i_h1 + 0.0)
    out["rail_a"] = rail

    def vcm_terms(c, inp, inm):
        q = P[c]
        return q["VOS"] + q["KCM"] * 0.5 * (inp + inm) + q["KPS"] * (rail - PS_REF)

    # T2C network: unknowns T2C, H1M, UVP with UVB output voltage vu
    def t2_solve(vbus, vu):
        G = np.zeros((n, 3, 3))
        b = np.zeros((n, 3))
        g0, g1, g2, g4, g5, g6 = 1 / r171, 1 / r111, 1 / r112, 1 / r114, 1 / r115, 1 / r116
        G[:, 0, 0] = g0 + g1 + g4; G[:, 0, 1] = -g1; G[:, 0, 2] = -g4
        G[:, 1, 0] = -g1; G[:, 1, 1] = g1 + g2
        G[:, 2, 0] = -g4; G[:, 2, 2] = g4 + g5 + g6
        b[:, 0] = g0 * vbus; b[:, 2] = g6 * vu
        x = np.linalg.solve(G, b[..., None])[..., 0]
        return x[:, 1], x[:, 2]

    # output levels: HIGH = rail minus ROUT x load (H1: R126 + pin-34 100k and R113 path), LOW = 0
    q = P["U102"]
    a_g = 1 / (r170 + r109); b_g = 1 / r113; s_g = a_g + 1 / r110 + b_g
    for j, vbus in enumerate(VBUS_LEVELS):
        vu = rail  # UVB is HIGH at VBUS >= 15.2 V (light load: 10 MOhm)
        vhm, _ = t2_solve(vbus, vu)
        # rise: output LOW (0 V); IN+ = (a_g*Vm)/s_g ; condition IN+ - IN- - off = +HYS/2, off has KCM*(IN+ + IN-)/2
        # solve linear: (1 - KCM/2)*IN+ = vhm*(1 + KCM/2) + VOS + KPS*(rail-3.3) + HYS/2
        kc = q["KCM"]
        inp_r = (vhm * (1 + kc / 2) + q["VOS"] + q["KPS"] * (rail - PS_REF) + q["HYS"] / 2) / (1 - kc / 2)
        out["h1r%d_a" % j] = inp_r * s_g / a_g
        il = rail / (r126 + R["RPIN34"])
        voh = rail - q["ROUT"] * il
        inp_f = (vhm * (1 + kc / 2) + q["VOS"] + q["KPS"] * (rail - PS_REF) - q["HYS"] / 2) / (1 - kc / 2)
        out["h1f%d_a" % j] = (inp_f * s_g - b_g * voh) / a_g
        out["h1hys%d_a" % j] = out["h1r%d_a" % j] - out["h1f%d_a" % j]
    # UVB: IN- = VREF (no load on REF103); IN+ = c0*VBUS + c1*vu
    q = P["U103"]
    for key, vu, sgn in (("uvbr_a", 0.0, +1), ("uvbf_a", rail, -1)):
        _, v0 = t2_solve(0.0, vu)
        _, v1 = t2_solve(20.0, vu)
        c1 = (v1 - v0) / 20.0
        kc = q["KCM"]
        tgt = (q["VREF"] * (1 + kc / 2) + q["VOS"] + q["KPS"] * (rail - PS_REF) + sgn * q["HYS"] / 2) / (1 - kc / 2)
        out[key] = (tgt - v0) / c1
    # U119 FCC_OFF: IN+ = VREF loaded by R184+R185 through RREF, divided; IN- = FCC + (rail - FCC) R186/(R186+R187)
    q = P["U119"]
    vref_l = q["VREF"] * (r184 + r185) / (r184 + r185 + q["RREF"])
    vfop = vref_l * r185 / (r184 + r185)
    kd = r186 / (r186 + r187)
    kc = q["KCM"]
    for key, sgn in (("focr", +1), ("focf", -1)):
        # FCC rising: output HIGH -> switches LOW when vd < -HYS/2: IN- = IN+ - off + HYS/2 (with KCM linear)
        vfom = (vfop * (1 - kc / 2) - q["VOS"] - q["KPS"] * (rail - PS_REF) + sgn * q["HYS"] / 2) / (1 + kc / 2)
        fcc = (vfom - kd * rail) / (1 - kd)
        # FCC_TAP = FCC + R122 x (FCC/(R188+R189) - (rail - FCC)/(R186+R187))
        tap = fcc + r122 * (fcc / (r188 + r189) - (rail - fcc) / (r186 + r187))
        out[key + "_a"] = tap
        out[key + "m_a"] = vfom
    q = P["U120"]
    kc = q["KCM"]
    for key, sgn in (("fonr", +1), ("fonf", -1)):
        vin = (q["VREF"] * (1 + kc / 2) + q["VOS"] + q["KPS"] * (rail - PS_REF) + sgn * q["HYS"] / 2) / (1 - kc / 2)
        fcc = vin * (r188 + r189) / r189
        tap = fcc + r122 * (fcc / (r188 + r189) - (rail - fcc) / (r186 + r187))
        out[key + "_a"] = tap
        out[key + "n_a"] = fcc
    return out


# =============================================================================================== 6. nominal decks
def nominal_runs():
    rows = []
    res = {}
    cases = [(b, d) for b in ("doc", "typ") for d in DESIGNS]

    def one_nom(case):
        basis, design = case
        tag = "nominal_%s_%s" % (basis, design)
        deck = mc_deck([nominal_params(basis)], design, tag, tmax_ns=5)
        open(os.path.join(DECKS, tag + ".cir"), "w").write(deck)
        r = run_deck(deck, vectors=["time", "vmot", "vbus", "fcctap", "h1_0", "uvb_0", "fccn_0", "fccon_0",
                                    "h1p_0", "h1m_0", "uvp_0", "fom_0", "fop_0", "fnp_0", "v33_0"])
        assert r.ok, (tag, r.errors[:5])
        return case, tag, r

    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for (basis, design), tag, r in ex.map(one_nom, cases):
            res[(basis, design)] = r
            m = {k: r.meas.get(k + "_0", float("nan")) for k in MEAS_KEYS}
            rows.append(dict(basis=basis, design=design, **m))
            log("  %s: rail %.4f V; H1 at 15.9 V rise %.4f fall %.4f; UVB rise %.4f fall %.4f; FCC_OFF %.4f/%.4f; "
                "FCC_ON %.4f/%.4f" % (tag, m["rail"], m["h1r1"], m["h1f1"], m["uvbr"], m["uvbf"], m["focr"],
                                      m["focf"], m["fonr"], m["fonf"]))
    # TI model cross-check (non-B TLV3012: VOS 0.5 mV, no hysteresis, 6.5 us propagation delay). The TI model runs as
    # up and down DC sweeps (its transmission-line delay makes a ramped transient slow and biases a ramp trip); the
    # behavioural model runs the transient deck with the same 0.5 mV offset / HYS 0 / ideal 1.242 V REF. The TI model
    # adds +0.5 mV to IN+ (V_VOS N785573 IN+BUFF 0.5m), which is VOS = -0.5 mV in this script's sign convention
    # (vd = IN+ - IN- - VOS).
    p = nominal_params("doc")
    q = json.loads(json.dumps(p))
    for c in COMPS:
        q[c].update(VOS=-0.5e-3, HYS=0.0, RREF=1e-6, ROUT=60.0)
    tag = "nominal_tiCheck_behav"
    deck = mc_deck([q], "baseline", tag, tmax_ns=5, model="behav")
    open(os.path.join(DECKS, tag + ".cir"), "w").write(deck)
    r = run_deck(deck, vectors=["time"])
    assert r.ok, (tag, r.errors[:5])
    ti = {"behav": {k: r.meas.get(k + "_0", float("nan")) for k in MEAS_KEYS}, "ti": {}}
    sweeps = []
    for j, vb_ in enumerate(VBUS_LEVELS):
        sweeps += [("h1r%d" % j, "VMOT", LO_K * vb_, HI_K * vb_, dict(vbus=vb_), "h1_0", "vmot", +1),
                   ("h1f%d" % j, "VMOT", HI_K * vb_, LO_K * vb_, dict(vbus=vb_), "h1_0", "vmot", -1)]
    sweeps += [("uvbf", "VBUS", UVB_HI, UVB_LO, {}, "uvb_0", "vbus", -1),
               ("uvbr", "VBUS", UVB_LO, UVB_HI, {}, "uvb_0", "vbus", +1),
               ("focr", "VFCC", 0.0, 2.1, {}, "fccn_0", "fcctap", -1),
               ("focf", "VFCC", 2.1, 0.0, {}, "fccn_0", "fcctap", +1),
               ("fonr", "VFCC", 0.0, 2.1, {}, "fccon_0", "fcctap", +1),
               ("fonf", "VFCC", 2.1, 0.0, {}, "fccon_0", "fcctap", -1)]
    for key, src, a, b, kw, outv, xv, edge in sweeps:
        deck = dc_deck(q, "baseline", "ti", src, a, b, **kw)
        if key in ("h1r1", "uvbf", "focr", "fonr"):
            open(os.path.join(DECKS, "nominal_tiCheck_ti_dc_%s.cir" % key), "w").write(deck)
        rr = run_deck(deck, vectors=[outv, xv], ngbehavior="psa")
        assert rr.ok, (key, rr.errors[:5])
        ti["ti"][key] = dc_trip(rr[xv], rr[outv], edge)
    for k in MEAS_KEYS:
        ti["ti"].setdefault(k, float("nan"))
    return rows, res, ti


def dc_deck(p, design, model, src, start, stop, vbus=15.9, vmot=0.0, fcc=0.0, bav="BAV199", vt=None, iload=None,
            rail_force=None, step=None):
    """DC sweep of one source (VMOT, VBUS or VFCC) for one board; up or down by the sign of stop - start."""
    step = step if step is not None else (stop - start) / 5000.0
    L = ["* dc sweep %s %s %s" % (design, model, src),
         *libs(model),
         "VMOT vmot 0 %.6g" % vmot, "VBUS vbus 0 %.6g" % vbus, "VFCC fcctap 0 %.6g" % fcc]
    L += board(0, p, design, model, bav=bav, vt=vt, iload=iload)
    if rail_force is not None:
        L = [ln for ln in L if not ln.startswith(("VT_0", "R175_0", "IL_0"))]
        L += ["VRAIL_0 v33_0 0 %.4f" % rail_force]
    L += [".options reltol=1e-6 vntol=1e-8 gmin=1e-15", ".dc %s %.6g %.6g %.6g" % (src, start, stop, step), ".end"]
    return "\n".join(L) + "\n"


def dc_trip(x, y, edge, thr=1.5):
    """Sweep value at the first crossing of y through thr in direction edge (+1 rising, -1 falling)."""
    d = (y - thr) * edge
    idx = np.where((d[:-1] < 0) & (d[1:] >= 0))[0]
    if not len(idx):
        return float("nan")
    i = idx[0]
    return float(x[i] + (x[i + 1] - x[i]) * (thr - y[i]) / (y[i + 1] - y[i]))



# =============================================================================================== 7. over-range
def overrange_deck(design, model, vbus, vt, iload, bav, indet, rail_force=None):
    p = nominal_params("typ")
    for c in COMPS:
        p[c]["INDET"] = indet
    L = ["* over-range %s %s VBUS %.2f" % (design, model, vbus),
         *libs(model),
         "VMOT vmot 0 PWL(0 0 400u 40)", "VBUS vbus 0 %.4f" % vbus, "VFCC fcctap 0 0"]
    L += board(0, p, design, model, bav=bav, vt=vt, iload=iload)
    if rail_force is not None:          # degraded rail (EIB-2 case): replace the Teensy source and R175 drop
        L = [ln for ln in L if not ln.startswith(("VT_0", "R175_0", "IL_0"))]
        L += ["VRAIL_0 v33_0 0 %.4f" % rail_force]
    L += [".options reltol=1e-5 method=gear", ".tran 20n 400u 0 50n", ".end"]
    return "\n".join(L) + "\n"


def ti_point_deck(design, vbus, vt, iload, bav, rail_force, vmot):
    """One operating point of the U102 network with the TI TLV3012 model (PSpice compatibility mode)."""
    p = nominal_params("typ")
    d = DESIGNS[design]
    L = ["* ti point %s VBUS %.2f V-MOT %.3f" % (design, vbus, vmot), '.include "%s"' % LIB_TI,
         '.include "%s"' % LIB_D, "VMOT vmot 0 %.6g" % vmot, "VBUS vbus 0 %.6g" % vbus]
    if rail_force is None:
        L += ["VT t6 0 %.6f" % vt, "R175 t6 v33 %.6g" % R["R175"], "IL v33 0 %.6g" % iload]
    else:
        L += ["VRAIL v33 0 %.4f" % rail_force]
    L += ["R170 vmot t1 %.6g" % R["R170"], "R109 t1 h1p %.6g" % R["R109"], "R110 h1p 0 %.6g" % d["R110"],
          "R113 h1 h1p %.6g" % R["R113"], "XD104 0 dk h1p %s" % bav, "VD104 dk v33 0",
          "R171 vbus t2c %.6g" % R["R171"], "R111 t2c h1m %.6g" % R["R111"], "R112 h1m 0 %.6g" % d["R112"],
          "XD105 0 v33 h1m %s" % bav, "R114 t2c uvp %.6g" % R["R114"], "R115 uvp 0 %.6g" % R["R115"],
          "R116 v33 uvp %.6g" % R["R116"], "XD106 0 v33 uvp %s" % bav,
          "XU102 h1p h1m v33 0 h1 ref102 TLV3012", "R126 h1 h1rb %.6g" % R["R126"], "RP34 h1rb 0 %.6g" % R["RPIN34"],
          ".options reltol=1e-4", ".op", ".end"]
    return "\n".join(L) + "\n"


def overrange_runs():
    rows = []
    waves = {}
    rails = [("lo", 3.135, 1.00e-3, None), ("nom", 3.30, 0.70e-3, None), ("hi", 3.465, 0.35e-3, None),
             ("sag1.83", None, None, 1.83)]
    jobs = []
    for design in DESIGNS:
        for vbus in (15.9, 19.5):
            for rname, vt, il, rf in rails:
                for bav in ("BAV199_LO", "BAV199_HI"):
                    for model, indet in (("behav", 0), ("behav", 1), ("ti", 0)):
                        if model == "ti" and bav == "BAV199_LO":
                            continue
                        jobs.append((design, vbus, rname, vt, il, rf, bav, model, indet))

    def one(j):
        design, vbus, rname, vt, il, rf, bav, model, indet = j
        vt_, il_ = (vt if vt else 3.3), (il if il else 0.7e-3)
        if model == "ti":
            # TI model, U102 network only (rail feed, R170/R109/R110/R113, R171/R111/R112, R114/R115 with R116 held at
            # the rail = UVB HIGH, D104-D106, R126 + pin-34 load). Neither a DC sweep nor an alter/op loop of the TI
            # model finished within 6-10 min in ngspice-46 (its ideal IF() switches, mid-supply output state and
            # transmission-line delay), so each V-MOT point is one .op deck (about 0.3 s each). The points from 18 V
            # to 40 V are unique operating points because IN+ is far above IN- there.
            grid = np.round(np.arange(18.0, 40.0001, 0.5), 3)
            vals = {k: [] for k in ("vmot", "h1", "h1p", "h1m", "v33", "vd104#branch")}
            deck = None
            for v in grid:
                deck = ti_point_deck(design, vbus, vt_, il_, bav, rf, float(v))
                rr = run_deck(deck, vectors=list(vals), ngbehavior="psa", timeout_s=5)
                # a point with no DC solution (the TI model's output toggles between HIGH and mid-supply at the
                # common-mode boundary, and R113 feeds the change back to IN+) times out; it is kept as NaN
                for k in vals:
                    if k == "vmot":
                        vals[k].append(float(v))
                    else:
                        vals[k].append(float(rr[k][0]) if (rr.ok and k in rr.vec) else float("nan"))
            r = rr
            r.ok = True
            r.meta_nosol = [float(g) for g, h in zip(grid, vals["h1"]) if not np.isfinite(h)]
            for k, k2 in (("vmot", "vmot"), ("h1", "h1_0"), ("h1p", "h1p_0"), ("h1m", "h1m_0"), ("v33", "v33_0"),
                          ("vd104#branch", "vd104_0#branch")):
                r.vec[k2] = np.array(vals[k])
        else:
            deck = overrange_deck(design, model, vbus, vt_, il_, bav, indet, rf)
            r = run_deck(deck, vectors=["vmot", "h1_0", "h1p_0", "h1m_0", "v33_0", "vd104_0#branch"])
        return j, deck, r

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for j, deck, r in ex.map(one, jobs):
            design, vbus, rname, vt, il, rf, bav, model, indet = j
            tag = "overrange_%s_%s_vbus%.1f_rail%s_%s_indet%d" % (design, model, vbus, rname, bav, indet)
            if (bav == "BAV199_HI" and rname in ("nom", "sag1.83")) or rname == "lo":
                open(os.path.join(DECKS, tag + ".cir"), "w").write(deck)
            assert r.ok, (tag, r.errors[:5])
            vm, h1, inp, inm, v33 = r["vmot"], r["h1_0"], r["h1p_0"], r["h1m_0"], r["v33_0"]
            idio = r["vd104_0#branch"] if "vd104_0#branch" in r.vec else np.zeros_like(vm)
            rail = float(np.nanmedian(v33))
            # first rise of H1
            hi_idx = np.where(h1 > 0.5 * rail)[0]
            v_rise = float(vm[hi_idx[0]]) if len(hi_idx) else float("nan")
            above = vm > (v_rise + 0.5 if len(hi_idx) else 1e9)
            cm_hi = rail + 0.2
            in_out = np.where(inp > cm_hi)[0]
            v_cm = float(vm[in_out[0]]) if len(in_out) else float("nan")
            h_above = h1[above] if above.any() else np.array([np.nan])
            nosol = getattr(r, "meta_nosol", [])
            if np.isfinite(h_above).any():
                h_above = h_above[np.isfinite(h_above)]
            # classification against SN74LVC2G08 thresholds at VCC 3.0-3.6 V (VIH 2.0 V, VIL 0.8 V; B.3)
            vih = 2.0 if rail >= 2.7 else 0.65 * rail
            vil = 0.8 if rail >= 2.7 else 0.35 * rail
            n_low = int((h_above < vil).sum())
            n_mid = int(((h_above >= vil) & (h_above < vih)).sum())
            state = "HIGH" if (n_low == 0 and n_mid == 0) else ("LOW" if n_low else "UNDEFINED (mid)")
            if not len(hi_idx):
                mid_any = bool(((h1 >= vil) & (h1 < vih)).any())
                state = "never HIGH (%s)" % ("mid-supply" if mid_any else "LOW")
            rows.append(dict(design=design, model=model, indet=indet, vbus=vbus, rail_case=rname, rail_v=rail,
                             bav=bav, h1_rise_vmot=v_rise, vmot_inplus_leaves_cm=v_cm,
                             inplus_max=float(np.nanmax(inp)), inminus=float(np.nanmedian(inm)),
                             h1_min_above_rise=float(np.nanmin(h_above)) if np.isfinite(h_above).any() else float("nan"),
                             h1_max_above_rise=float(np.nanmax(h_above)) if np.isfinite(h_above).any() else float("nan"),
                             state_above_rise=state, d104_up_current_max_uA=float(np.nanmax(idio) * 1e6),
                             no_dc_solution_vmot=";".join("%.2f" % x for x in nosol)))
            if bav == "BAV199_HI" and rname in ("nom", "sag1.83") and indet == 0:
                waves[(design, model, vbus, rname)] = (vm, h1, inp, inm, rail)
    return rows, waves


# =============================================================================================== 7b. ripple chatter
MINHYS_VERTEX = {}


def ripple_deck(design, vcentre, vpp, f, hys_case):
    """H1 with the input filters fitted (C106 470 pF on N_H1P, C107 470 pF on N_H1M; cr.net / gen/netlist.py lines
    135 and 140): V-MOT = vcentre + (vpp/2) sin(2 pi f t) at VBUS 15.9 V. hys_case 'nom' = typical part (HYS 6 mV),
    'min' = the vertex of minimum H1 hysteresis at VBUS 15.9 V from the exhaustive worst-case search (low Teensy 3V3,
    high base load, VHYS 2 mV, R113 at +tolerance + TCR, ...; check round: replaces the earlier HYS 2 mV / R113 +1 % /
    rail 3.30 V corner, which was not the minimum)."""
    p = nominal_params("typ") if hys_case == "nom" else MINHYS_VERTEX[design]
    L = ["* ripple %s f %.0f Hz p-p %.4f V" % (design, f, vpp), *libs("behav"),
         "VMOT vmot vmx SIN(0 %.6f %.6g %.6g)" % (vpp / 2, f, 2.0 / f),
         "VMOTDC vmx 0 PWL(0 0 %.6g %.6f)" % (1.0 / f, vcentre), "VBUS vbus 0 15.9", "VFCC fcctap 0 0"]
    L += board(0, p, design, "behav")
    L += ["C106_0 h1p_0 0 470p", "C107_0 h1m_0 0 470p", "C108_0 uvp_0 0 1n",
          ".options reltol=1e-5 method=gear",
          ".tran %gn %gu 0 %gn" % (1e6 / f, 12e6 / f, 1e6 / f / 2),
          ".meas tran nflip_max MAX v(h1_0) FROM=%gu TO=%gu" % (4e6 / f, 12e6 / f),
          ".meas tran nflip_min MIN v(h1_0) FROM=%gu TO=%gu" % (4e6 / f, 12e6 / f), ".end"]
    return "\n".join(L) + "\n"


def ripple_runs(nom_rows):
    """Smallest V-MOT ripple (p-p) at the H1 hysteresis centre that toggles H1 (bisection, 10 steps), for each
    frequency of the H.1 ripple row. The centre is the mean of the nominal rise and fall trips at VBUS 15.9 V."""
    rows = []
    jobs = []
    for design in DESIGNS:
        nr = [r for r in nom_rows if r["basis"] == "typ" and r["design"] == design][0]
        for hc in ("nom", "min"):
            for f in (8e3, 20e3, 30e3):
                jobs.append((design, hc, f, nr))

    def one(j):
        design, hc, f, nr = j
        if hc == "nom":
            centre = 0.5 * (nr["h1r1"] + nr["h1f1"])
        else:
            # centre of the minimum-hysteresis vertex from the analytic model
            P = {k: np.array([v]) if not isinstance(v, dict) else {kk: np.array([vv]) for kk, vv in v.items()}
                 for k, v in MINHYS_VERTEX[design].items()}
            A = analytic(P, design, 1)
            centre = 0.5 * (A["h1r1_a"][0] + A["h1f1_a"][0])
        lo, hi = 0.0, 3.0
        for _ in range(11):
            mid = 0.5 * (lo + hi)
            r = run_deck(ripple_deck(design, centre, mid, f, hc), vectors=["time"])
            toggles = r.ok and r.meas.get("nflip_max", 0) > 1.5 and r.meas.get("nflip_min", 3.3) < 1.5
            if toggles:
                hi = mid
            else:
                lo = mid
        open(os.path.join(DECKS, "ripple_%s_%s_%.0fkHz.cir" % (design, hc, f / 1e3)), "w").write(
            ripple_deck(design, centre, hi, f, hc))
        pv = nominal_params("typ") if hc == "nom" else MINHYS_VERTEX[design]
        PA = {k: np.array([v]) if not isinstance(v, dict) else {kk: np.array([vv]) for kk, vv in v.items()}
              for k, v in pv.items()}
        AA = analytic(PA, design, 1)
        return dict(design=design, hysteresis_case=hc, f_kHz=f / 1e3, centre_vmot=centre, vpp_toggle=hi,
                    h1_hyst_vmot=float(AA["h1hys1_a"][0]), rail=float(AA["rail_a"][0]), Vt=pv["Vt"],
                    Iload_mA=pv["Iload"] * 1e3, U102_HYS_mV=pv["U102"]["HYS"] * 1e3, R113_dev=pv["R113"])

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for row in ex.map(one, jobs):
            rows.append(row)
            log("  ripple %-8s %-3s %5.1f kHz: H1 toggles at V-MOT ripple >= %.3f V p-p (centre %.3f V, hyst %.4f V, "
                "rail %.3f V)" % (row["design"], row["hysteresis_case"], row["f_kHz"], row["vpp_toggle"],
                                  row["centre_vmot"], row["h1_hyst_vmot"], row["rail"]))
    return rows


# =============================================================================================== 8. statistics
def stats(x):
    x = x[np.isfinite(x)]
    m, s = float(np.mean(x)), float(np.std(x, ddof=1))
    return dict(n=len(x), min=float(x.min()), max=float(x.max()), mean=m, std=s, lo3=m - 3 * s, hi3=m + 3 * s,
                p0135=float(np.percentile(x, 0.135)), p99865=float(np.percentile(x, 99.865)))


N_EXH = 12      # dominant parameters enumerated exhaustively (2^12 = 4096 vertices per bound)


def worst_case(design, tcr_on=True, return_vertex=()):
    """Deterministic extreme of each trip. Linear sensitivities of the analytic model over every bounded parameter
    select the bound of each parameter (the 'sensitivity vertex'); then the N_EXH parameters with the largest
    sensitivity are enumerated exhaustively over their two bounds (4096 vertices) with the others held at the
    sensitivity-selected bound, and the extreme over that set and the sensitivity vertex is reported. Keys listed in
    return_vertex also return the extreme vertices as parameter dicts (pick() format)."""
    p0 = nominal_params("typ")

    def flat(p):
        v = {"T": p["T"], "Vt": p["Vt"], "Iload": p["Iload"]}
        for r in R:
            v[r] = p[r]
        for c in COMPS:
            for k in ("VOS", "HYS", "KCM", "KPS", "VREF", "RREF", "ROUT", "IQ"):
                v["%s.%s" % (c, k)] = p[c][k]
        return v
    base = flat(p0)
    # bounds (temperature handled through explicit TCR/drift terms: each resistor's total deviation and each REF value
    # span the product of tolerance and TCR x 45 K; REF 1.223-1.260 V x (1 +- 100 ppm x 45 K))
    bnd = {"Vt": VT_RNG, "Iload": ILOAD_RNG}
    for r, (tol, tcr) in TOL.items():
        if tol:
            k = 45.0 if tcr_on else 0.0
            bnd[r] = ((1 - tol) * (1 - tcr * k), (1 + tol) * (1 + tcr * k))
    for c in COMPS:
        bnd[c + ".VOS"] = (-VOS_MAX, VOS_MAX); bnd[c + ".HYS"] = HYS_RNG; bnd[c + ".KCM"] = (-KCM_MAX, KCM_MAX)
        bnd[c + ".KPS"] = (-KPS_MAX, KPS_MAX)
        bnd[c + ".VREF"] = (VREF_RNG[0] * (1 - REF_TC * 45), VREF_RNG[1] * (1 + REF_TC * 45))
        bnd[c + ".RREF"] = RREF_RNG; bnd[c + ".ROUT"] = ROUT_RNG; bnd[c + ".IQ"] = IQ_RNG
    names = list(bnd)

    def unflat(vecs, n):
        P = {"T": np.full(n, 25.0)}
        for k in ("Vt", "Iload"):
            P[k] = vecs.get(k, np.full(n, base[k]))
        for r in R:
            P[r] = vecs.get(r, np.full(n, base[r]))
        for c in COMPS:
            P[c] = {k: vecs.get("%s.%s" % (c, k), np.full(n, base["%s.%s" % (c, k)]))
                    for k in ("VOS", "HYS", "KCM", "KPS", "VREF", "RREF", "ROUT", "IQ")}
            P[c]["INDET"] = np.zeros(n, dtype=int)
        return P
    # midpoint vector
    mid = {k: np.array([0.5 * (a + b)]) for k, (a, b) in bnd.items()}
    n = 2 * len(names)
    vecs = {k: np.repeat(mid[k], n) for k in names}
    for i, k in enumerate(names):
        vecs[k][2 * i] = bnd[k][0]
        vecs[k][2 * i + 1] = bnd[k][1]
    A = analytic(unflat(vecs, n), design, n)
    keys = [k for k in A if k.endswith("_a") and k != "rail_a"]
    nv = 2 ** N_EXH
    bits = ((np.arange(nv)[:, None] >> np.arange(N_EXH)[None, :]) & 1).astype(bool)
    out = {}
    for key in keys:
        d = A[key][1::2] - A[key][0::2]      # effect of moving each parameter from its low to its high bound
        lo_v = {k: np.array([bnd[k][0] if d[i] > 0 else bnd[k][1]]) for i, k in enumerate(names)}
        hi_v = {k: np.array([bnd[k][1] if d[i] > 0 else bnd[k][0]]) for i, k in enumerate(names)}
        lo = float(analytic(unflat(lo_v, 1), design, 1)[key][0])
        hi = float(analytic(unflat(hi_v, 1), design, 1)[key][0])
        order = sorted(range(len(names)), key=lambda i: -abs(d[i]))
        dom = [names[i] for i in order[:N_EXH]]
        ext = {}
        for side, v1, fn in (("lo", lo_v, np.argmin), ("hi", hi_v, np.argmax)):
            vv = {k: np.repeat(v1[k], nv) for k in names}
            for b, k in enumerate(dom):
                vv[k] = np.where(bits[:, b], bnd[k][1], bnd[k][0])
            PP = unflat(vv, nv)
            val = analytic(PP, design, nv)[key]
            i = int(fn(val))
            ext[side] = float(val[i])
            if key[:-2] in return_vertex:
                ext[side + "_vertex"] = pick(PP, i)
        top = [(names[i], float(abs(d[i]))) for i in order[:4]]
        res = dict(lo=min(ext["lo"], lo), hi=max(ext["hi"], hi), lo_sens=lo, hi_sens=hi, top=top, dominant=dom)
        res.update({k: v for k, v in ext.items() if k.endswith("_vertex")})
        out[key[:-2]] = res
    return out


def psref_sweep():
    """Worst-case sensitivity of the trips to the PSRR reference supply (check round). Each variant reruns the
    exhaustive worst case (with TCR) on the analytic model: reference 3.3 V (used), 1.8 V, 5.5 V, and KPS = 0."""
    global PS_REF, KPS_MAX
    keep = (PS_REF, KPS_MAX)
    rows = []
    try:
        for tag, ref, kps in (("ref 3.3 V (used)", 3.3, keep[1]), ("ref 1.8 V", 1.8, keep[1]),
                              ("ref 5.5 V", 5.5, keep[1]), ("KPS = 0", 3.3, 0.0)):
            PS_REF, KPS_MAX = ref, kps
            for design in DESIGNS:
                w = worst_case(design)
                row = dict(variant=tag, design=design)
                for k in ("h1r2", "h1f2", "h1f3", "uvbf", "uvbr", "focr", "fonf"):
                    row[k + "_lo"] = w[k]["lo"]
                    row[k + "_hi"] = w[k]["hi"]
                rows.append(row)
    finally:
        PS_REF, KPS_MAX = keep
    return rows


# =============================================================================================== 9. plots
def plots(nom, mc, ana, waves, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig 1: nominal hysteresis loops (typical basis, baseline)
    r = nom[("typ", "baseline")]
    t, vm, vb, fc = r["time"], r["vmot"], r["vbus"], r["fcctap"]
    fig, ax = plt.subplots(2, 2, figsize=(11, 8))
    tw = summary["stimulus_windows_us"]
    a, b = tw["15.9"]
    sel = (t >= a * 1e-6) & (t <= b * 1e-6)
    ax[0, 0].plot(vm[sel], r["h1_0"][sel], lw=1.2)
    ax[0, 0].set_xlabel("V-MOT (V) at VBUS 15.9 V"); ax[0, 0].set_ylabel("H1 (V)"); ax[0, 0].set_title("U102 H1")
    sel = t >= tw["uvb"][0] * 1e-6
    ax[0, 1].plot(vb[sel], r["uvb_0"][sel], lw=1.2, color="C1")
    ax[0, 1].set_xlabel("VBUS (V)"); ax[0, 1].set_ylabel("UVB (V)"); ax[0, 1].set_title("U103 UVB")
    sel = t <= 400e-6
    ax[1, 0].plot(fc[sel], r["fccn_0"][sel], lw=1.2, color="C2")
    ax[1, 0].set_xlim(0.3, 0.5)
    ax[1, 0].set_xlabel("FCC_TAP / EN net (V)"); ax[1, 0].set_ylabel("FCCN (V)"); ax[1, 0].set_title("U119 FCC_OFF")
    ax[1, 1].plot(fc[sel], r["fccon_0"][sel], lw=1.2, color="C3")
    ax[1, 1].set_xlim(1.7, 1.9)
    ax[1, 1].set_xlabel("FCC_TAP / EN net (V)"); ax[1, 1].set_ylabel("FCC_ON (V)"); ax[1, 1].set_title("U120 FCC_ON")
    for x in ax.flat:
        x.grid(alpha=0.3)
    fig.suptitle("Nominal transfer characteristics (typical basis: HYS 6 mV, Teensy 3V3 3.30 V, base load 0.70 mA)")
    fig.tight_layout(); fig.savefig(os.path.join(PNG, "fig1_nominal_loops.png"), dpi=130); plt.close(fig)

    # Fig 2: H1 MC distributions at VBUS 16.39 V with the regen threshold stack
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for i, (design, lab) in enumerate((("baseline", "baseline (R110 56.2k)"),
                                      ("opt08", "VR-4 option (R110 44.2k, R112 %.1fk)" % (OPT["r112n"] / 1e3)))):
        f, rr = mc[design]["h1f2"], mc[design]["h1r2"]
        ax[i].hist(f[np.isfinite(f)], bins=60, alpha=0.7, label="H1 fall (SPICE MC)")
        ax[i].hist(rr[np.isfinite(rr)], bins=60, alpha=0.7, label="H1 rise (SPICE MC)")
        for x, c, lb in ((16.39, "k", "VBUS steady max 16.39"), (17.34, "C0", "doc fall min 17.34"),
                         (17.84, "m", "VINDPM_STAGE1 min 17.84"),
                         (18.05, "C1", "doc rise max 18.05"), (18.62, "r", "VINDPM min 18.62")):
            ax[i].axvline(x, color=c, ls="--", lw=1)
            ax[i].text(x, ax[i].get_ylim()[1] * 0.95, lb, rotation=90, va="top", ha="right", fontsize=7)
        ax[i].set_xlabel("V-MOT trip (V) at VBUS 16.39 V"); ax[i].set_ylabel("count"); ax[i].set_title(lab)
        ax[i].legend(fontsize=8, loc="center left"); ax[i].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(PNG, "fig2_h1_mc_16v39.png"), dpi=130); plt.close(fig)

    # Fig 3: UVB MC
    fig, ax = plt.subplots(figsize=(7, 4.5))
    f, rr = mc["baseline"]["uvbf"], mc["baseline"]["uvbr"]
    ax.hist(f[np.isfinite(f)], bins=60, alpha=0.7, label="UVB fall (inhibit)")
    ax.hist(rr[np.isfinite(rr)], bins=60, alpha=0.7, label="UVB rise (re-permit)")
    for x, c, lb in ((12.89, "C0", "doc fall band"), (13.78, "C0", ""), (13.26, "C1", "doc rise band"),
                     (14.16, "C1", ""), (14.12, "r", "FC VINDPM floor 14.12")):
        ax.axvline(x, color=c, ls="--", lw=1)
        if lb:
            ax.text(x, ax.get_ylim()[1] * 0.95, lb, rotation=90, va="top", ha="right", fontsize=7)
    ax.set_xlabel("VBUS trip (V)"); ax.set_ylabel("count"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set_title("U103 UVB, SPICE Monte Carlo (baseline)")
    fig.tight_layout(); fig.savefig(os.path.join(PNG, "fig3_uvb_mc.png"), dpi=130); plt.close(fig)

    # Fig 4: FCC comparators
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for key, lb in (("focr", "FCC rising (FCCN falls)"), ("focf", "FCC falling (FCCN rises)")):
        x = mc["baseline"][key]; ax[0].hist(x[np.isfinite(x)], bins=50, alpha=0.7, label=lb)
    for x, c in ((0.377, "k"), (0.432, "k"), (0.6, "r")):
        ax[0].axvline(x, color=c, ls="--", lw=1)
    ax[0].set_title("U119 FCC_OFF on the EN net (doc 0.377-0.432 V; VEN_F min 0.6 V)")
    for key, lb in (("fonr", "FCC rising"), ("fonf", "FCC falling")):
        x = mc["baseline"][key]; ax[1].hist(x[np.isfinite(x)], bins=50, alpha=0.7, label=lb)
    for x, c in ((1.745, "k"), (1.875, "k"), (1.4, "r")):
        ax[1].axvline(x, color=c, ls="--", lw=1)
    ax[1].set_title("U120 FCC_ON on the EN net (doc 1.745-1.875 V; VEN_R max 1.4 V)")
    for x in ax:
        x.set_xlabel("FCC_TAP (V)"); x.legend(fontsize=8); x.grid(alpha=0.3); x.title.set_fontsize(9)
    fig.tight_layout(); fig.savefig(os.path.join(PNG, "fig4_fcc_mc.png"), dpi=130); plt.close(fig)

    # Fig 5: over-range, behavioural vs TI, baseline and option, VBUS 15.9 V, nominal rail
    fig, ax = plt.subplots(2, 2, figsize=(12, 7.5))
    for i, design in enumerate(DESIGNS):
        for model, c in (("behav", "C0"), ("ti", "C3")):
            if (design, model, 15.9, "nom") in waves:
                vm, h1, inp, inm, rail = waves[(design, model, 15.9, "nom")]
                ax[0, i].plot(vm, h1, color=c, label="H1, %s model" % ("TLV3012B behavioural" if model == "behav"
                                                                       else "TI TLV3012 (non-B) PSpice"))
                if model == "behav":
                    ax[1, i].plot(vm, inp, color="C0", label="IN+ (N_H1P)")
                    ax[1, i].plot(vm, inm, color="C2", label="IN- (N_H1M)")
                    ax[1, i].axhline(rail + 0.2, color="k", ls="--", lw=1, label="V+ + 0.2 V (CM limit)")
                    ax[1, i].axhline(5.5, color="r", ls=":", lw=1, label="fail-safe limit 5.5 V")
        for y in (0.8, 2.0):
            ax[0, i].axhline(y, color="gray", ls=":", lw=1)
        ax[0, i].set_title("%s: H1 output, VBUS 15.9 V, V-MOT 0-40 V" % design)
        ax[0, i].set_ylabel("V"); ax[0, i].legend(fontsize=7); ax[0, i].grid(alpha=0.3)
        ax[1, i].set_xlabel("V-MOT (V)"); ax[1, i].set_ylabel("V"); ax[1, i].legend(fontsize=7)
        ax[1, i].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(PNG, "fig5_overrange.png"), dpi=130); plt.close(fig)

    # Fig 6: SPICE vs analytic agreement
    fig, ax = plt.subplots(figsize=(7, 4))
    for key in ("h1r1", "h1f1", "uvbf", "uvbr", "focr", "fonr"):
        d = (mc["baseline"][key] - ana["baseline"][key + "_a"]) * 1e3
        ax.hist(d[np.isfinite(d)], bins=60, alpha=0.5, label=key)
    ax.set_xlabel("SPICE - analytic (mV)"); ax.set_ylabel("count"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set_title("Trip agreement, SPICE transient vs analytic nodal model (baseline MC)")
    fig.tight_layout(); fig.savefig(os.path.join(PNG, "fig6_spice_vs_analytic.png"), dpi=130); plt.close(fig)


# =============================================================================================== 10. main
def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(",".join(keys) + "\n")
        for r in rows:
            fh.write(",".join(("%.6g" % r[k]) if isinstance(r[k], float) else str(r[k]) for k in keys) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    n = 400 if a.quick else a.n
    t_start = time.time()
    log("Sim 3 comparators: %s" % ngspice_version())
    log("cr.net topology asserted for %d parts" % len(EXPECT))
    log("VR-4 option: present H1+ ratio %.5f, H1- ratio %.5f, ratio of ratios %.5f; R110 44.2k -> H1+ %.5f; "
        "R112 exact %.0f ohm, E192 %.0f ohm -> H1- %.5f, ratio of ratios %.5f"
        % (OPT["rp0"], OPT["rm0"], OPT["k0"], OPT["rpn"], OPT["r112_exact"], OPT["r112n"], OPT["rmn"], OPT["kn"]))
    vm, vb, fc, t_end = stimulus()
    summary = dict(ngspice=ngspice_version(), seed=SEED, n_mc=n, vr4=OPT,
                   stimulus_windows_us=dict([("%g" % v, (10 + 110 * j, 110 + 110 * j))
                                             for j, v in enumerate(VBUS_LEVELS)] +
                                            [("uvb", (10 + 110 * len(VBUS_LEVELS), t_end))]))

    log("[1] nominal decks")
    nom_rows, nom, ti = nominal_runs()
    write_csv(os.path.join(CSV, "nominal_trips.csv"), nom_rows)
    write_csv(os.path.join(CSV, "ti_model_crosscheck.csv"),
              [dict(quantity=k, ti_model=ti["ti"][k], behavioural=ti["behav"][k],
                    diff_mV=(ti["ti"][k] - ti["behav"][k]) * 1e3) for k in MEAS_KEYS])
    summary["nominal"] = nom_rows
    summary["ti_crosscheck"] = ti

    log("[2] Monte Carlo, N = %d, uniform over the limits, seed %d" % (n, SEED))
    rng = np.random.default_rng(SEED)
    P = sample_params(n, rng, "uniform")
    mc, ana = {}, {}
    for design in DESIGNS:
        mc[design] = spice_mc(P, n, design, a.batch, a.workers, "mc")
        ana[design] = analytic(P, design, n)
    # per-sample CSV
    for design in DESIGNS:
        rows = []
        for i in range(n):
            row = dict(i=i, T=float(P["T"][i]), Vt=float(P["Vt"][i]), Iload_mA=float(P["Iload"][i] * 1e3))
            for c in COMPS:
                row[c + "_VOS_mV"] = float(P[c]["VOS"][i] * 1e3)
                row[c + "_HYS_mV"] = float(P[c]["HYS"][i] * 1e3)
                row[c + "_VREF"] = float(P[c]["VREF"][i])
            for key in MEAS_KEYS:
                row[key] = float(mc[design][key][i])
                if key + "_a" in ana[design]:
                    row[key + "_analytic"] = float(ana[design][key + "_a"][i])
            rows.append(row)
        write_csv(os.path.join(CSV, "mc_%s.csv" % design), rows)

    # statistics and agreement
    labels = {"h1r0": "H1 rise @ VBUS 15.20", "h1f0": "H1 fall @ VBUS 15.20", "h1r1": "H1 rise @ VBUS 15.90",
              "h1f1": "H1 fall @ VBUS 15.90", "h1r2": "H1 rise @ VBUS 16.39", "h1f2": "H1 fall @ VBUS 16.39",
              "h1r3": "H1 rise @ VBUS 19.50", "h1f3": "H1 fall @ VBUS 19.50",
              "uvbf": "UVB fall (VBUS)", "uvbr": "UVB rise (VBUS)", "focr": "FCC_OFF at FCC rising (EN net)",
              "focrm": "FCC_OFF at FCC rising (IN-)", "focf": "FCC_OFF at FCC falling (EN net)",
              "focfm": "FCC_OFF at FCC falling (IN-)", "fonr": "FCC_ON rising (EN net)",
              "fonrn": "FCC_ON rising (/FCC)", "fonf": "FCC_ON falling (EN net)", "fonfn": "FCC_ON falling (/FCC)",
              "rail": "CR 3V3 rail"}
    wc = {d: worst_case(d, return_vertex=("h1hys1",)) for d in DESIGNS}
    for d in DESIGNS:
        MINHYS_VERTEX[d] = wc[d]["h1hys1"]["lo_vertex"]
        v = MINHYS_VERTEX[d]
        log("  %s minimum H1 hysteresis vertex at VBUS 15.9 V: %.4f V (Teensy %.3f V, load %.2f mA, U102 HYS %.1f mV, "
            "R113 x%.5f)" % (d, wc[d]["h1hys1"]["lo"], v["Vt"], v["Iload"] * 1e3, v["U102"]["HYS"] * 1e3, v["R113"]))
    wc_rows = []
    for d in DESIGNS:
        for k, w in wc[d].items():
            wc_rows.append(dict(design=d, key=k, wc_lo=w["lo"], wc_hi=w["hi"], sens_vertex_lo=w["lo_sens"],
                                sens_vertex_hi=w["hi_sens"],
                                exhaustive_minus_sens_lo_mV=(w["lo"] - w["lo_sens"]) * 1e3,
                                exhaustive_minus_sens_hi_mV=(w["hi"] - w["hi_sens"]) * 1e3,
                                dominant=";".join(w["dominant"])))
    write_csv(os.path.join(CSV, "worst_case_vertices.csv"), wc_rows)
    summary["worst_case"] = wc_rows
    ps_rows = psref_sweep()
    write_csv(os.path.join(CSV, "psrr_reference_sweep.csv"), ps_rows)
    summary["psrr_reference_sweep"] = ps_rows
    for r_ in ps_rows:
        log("  PSRR %-17s %-8s H1 fall@16.39 [%.4f, %.4f] rise max %.4f; H1 fall@19.5 min %.4f; UVB fall max %.4f"
            % (r_["variant"], r_["design"], r_["h1f2_lo"], r_["h1f2_hi"], r_["h1r2_hi"], r_["h1f3_lo"], r_["uvbf_hi"]))
    # the design-document basis (r3_calc.py) has no resistor TCR term; this variant drops it for the comparison
    wc0 = {d: worst_case(d, tcr_on=False) for d in DESIGNS}
    stat_rows = []
    agree = {}
    for design in DESIGNS:
        for key in MEAS_KEYS:
            st = stats(mc[design][key])
            ak = key + "_a" if key != "rail" else "rail_a"
            d = mc[design][key] - ana[design][ak]
            d = d[np.isfinite(d)]
            agree[(design, key)] = float(np.max(np.abs(d))) if len(d) else float("nan")
            w = wc[design].get(key, dict(lo=float("nan"), hi=float("nan"), top=[]))
            w0 = wc0[design].get(key, dict(lo=float("nan"), hi=float("nan"), top=[]))
            stat_rows.append(dict(design=design, quantity=labels[key], key=key, n=st["n"], min=st["min"],
                                  max=st["max"], mean=st["mean"], std=st["std"], mean_m3s=st["lo3"],
                                  mean_p3s=st["hi3"], wc_lo=w["lo"], wc_hi=w["hi"], wc_lo_noTCR=w0["lo"],
                                  wc_hi_noTCR=w0["hi"],
                                  max_abs_spice_minus_analytic_mV=agree[(design, key)] * 1e3,
                                  top_sensitivities=";".join("%s %.4f" % t for t in w["top"])))
            log("  %-8s %-30s n=%d min %.4f max %.4f mean %.4f 3s [%.4f, %.4f] WC [%.4f, %.4f] |S-A| %.2f mV"
                % (design, labels[key], st["n"], st["min"], st["max"], st["mean"], st["lo3"], st["hi3"], w["lo"],
                   w["hi"], agree[(design, key)] * 1e3))
    write_csv(os.path.join(CSV, "mc_statistics.csv"), stat_rows)
    summary["mc_statistics"] = stat_rows

    # derived H1 hysteresis and guard
    der = []
    for design in DESIGNS:
        for j, vb_ in enumerate(VBUS_LEVELS):
            hy = mc[design]["h1r%d" % j] - mc[design]["h1f%d" % j]
            gd = mc[design]["h1f%d" % j] - vb_
            sh, sg = stats(hy), stats(gd)
            der.append(dict(design=design, vbus=vb_, hyst_min=sh["min"], hyst_max=sh["max"], hyst_mean=sh["mean"],
                            guard_min=sg["min"], guard_mean=sg["mean"], guard_m3s=sg["lo3"]))
        hy = mc[design]["uvbr"] - mc[design]["uvbf"]
        sh = stats(hy)
        der.append(dict(design=design, vbus="UVB", hyst_min=sh["min"], hyst_max=sh["max"], hyst_mean=sh["mean"],
                        guard_min=float("nan"), guard_mean=float("nan"), guard_m3s=float("nan")))
    write_csv(os.path.join(CSV, "mc_derived.csv"), der)
    summary["mc_derived"] = der

    # Gaussian sensitivity variant (analytic model, validated above), N = 200 000
    rng2 = np.random.default_rng(SEED + 1)
    ng = 200000
    Pg = sample_params(ng, rng2, "gauss")
    Pu = sample_params(ng, np.random.default_rng(SEED + 2), "uniform")
    gauss_rows = []
    for design in DESIGNS:
        Ag, Au = analytic(Pg, design, ng), analytic(Pu, design, ng)
        for key in ("h1r1", "h1f1", "h1r2", "h1f2", "h1r3", "h1f3", "h1f0", "uvbf", "uvbr", "focr", "focf", "fonr", "fonf"):
            sg, su = stats(Ag[key + "_a"]), stats(Au[key + "_a"])
            gauss_rows.append(dict(design=design, quantity=labels[key], gauss_min=sg["min"], gauss_max=sg["max"],
                                   gauss_mean=sg["mean"], gauss_std=sg["std"], uniform200k_min=su["min"],
                                   uniform200k_max=su["max"], uniform200k_std=su["std"]))
    write_csv(os.path.join(CSV, "analytic_200k_gauss_vs_uniform.csv"), gauss_rows)
    summary["analytic_200k"] = gauss_rows

    log("[3] over-range sweeps (V-MOT 0-40 V)")
    orow, waves = overrange_runs()
    write_csv(os.path.join(CSV, "overrange.csv"), orow)
    summary["overrange"] = orow
    for r_ in orow:
        if r_["bav"] == "BAV199_HI":
            log("  %-8s %-5s indet=%d VBUS %.1f rail %-7s (%.3f V): H1 rise %.2f V, IN+ leaves CM at %.2f V, IN+ max "
                "%.3f V, H1 above rise %.3f..%.3f V -> %s; D104 %.1f uA"
                % (r_["design"], r_["model"], r_["indet"], r_["vbus"], r_["rail_case"], r_["rail_v"],
                   r_["h1_rise_vmot"], r_["vmot_inplus_leaves_cm"], r_["inplus_max"], r_["h1_min_above_rise"],
                   r_["h1_max_above_rise"], r_["state_above_rise"], r_["d104_up_current_max_uA"]))

    log("[3b] V-MOT ripple that toggles H1 (input filters fitted)")
    rrows = ripple_runs(nom_rows)
    write_csv(os.path.join(CSV, "ripple_chatter.csv"), rrows)
    summary["ripple"] = rrows

    log("[4] plots")
    plots(nom, mc, ana, waves, summary)
    summary["runtime_s"] = time.time() - t_start
    with open(os.path.join(HERE, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    log("done in %.0f s" % (time.time() - t_start))


if __name__ == "__main__":
    main()
