#!/usr/bin/env python3
"""Round-4 work: what happens to the EIB fail-safe arguments if the EVM interface board (EIB) merges onto the carrier (CR).

Companion to eib_merge_failsafe.md (same folder). stdlib only. Run:  python -I eib_merge_calc.py > eib_merge_calc_out.txt
Two geometries: G1 = EVM on or beside the CR, CR-edge-to-EVM-pin 10-60 mm; G2 = EVM off-board 0.10-0.30 m.

Sources (literature numbers):
  DOC  docs/charger_bq25798_wiring_design_2026-11-05.md r6 (A.3, A.5, A.6, B.6, H.4, H.11, H.13, H.15, H.19, H.22(i))
  R3   docs/reviews/charger_eval_2026-11-05/round3/calc/r3_calc.py (H.4, H.13, H.22(i) inputs; TLV3012B constants)
  UG   SLUUCB5E Fig 4-1 rendered at 150 dpi (round4/work/evm/p150-15.png) and 300 dpi (p300-15.png); EVM BOM (bom_raw.txt)
  AWG  standard annealed-copper AWG resistance table (20 C): 18 AWG 20.95, 20 AWG 33.31, 28 AWG 212.9 mOhm/m
Values marked ASSUMED are not in any primary; each one names the measurement that replaces it (eib_merge_failsafe.md section 7).
"""
import math

MU0_4PI = 1e-7          # mu0 / 4 pi, H/m (exact by definition, SI 2019 within 1e-9)
MU0_2PI = 2e-7
EPS0 = 8.854e-12

def par(*rs):
    return 1.0 / sum(1.0 / r for r in rs)

print("=" * 100)
# ------------------------------------------------------------------------------------------------ 1. EVM geometry
# EVM frame (round4/work/evm_geometry.md section 2.3, Table 1: vector extraction of SLUUCB5E Fig 4-1): origin lower-left
# board corner, top view, +x right, +y up, mm; outline 88.90 x 88.90 mm. JP21 pin 1 is the LOWER post (evm_geometry.md 7.2).
EVM_W = EVM_H = 88.90
pts = {"TP49 (E8)": (83.440, 79.120), "TP33 (E3)": (80.011, 63.499), "JP21 pin 1 (E4)": (75.312, 64.769),
       "JP14 pin 2 (E2)": (71.375, 64.769), "TP38 (E7)": (66.041, 59.689), "JP12 pin 1 REGN (E1)": (39.370, 13.741),
       "TP27 REGN (E1 alt.)": (26.670, 80.009), "TP36 /CE (E5)": (55.874, 19.710), "JP17 pin 1 /CE (E6)": (54.611, 26.796)}
# Power-stage copper: L2 and U1 outlines from evm_geometry.md Table 1 (vector); the capacitor banks and the SW test points
# TP3/TP4 (SW1) and TP10/TP11 (SW2) read from p300-15.png and converted with the scale fitted to the vector points
# (8.448 px/mm in x, 8.475 px/mm in y at 150 dpi; origin (266.1, 981.2) px): +-0.5 mm. The raster read of L2 lands within
# 0.2 mm of its vector outline, which checks the conversion.
def px2mm(x0, y0, x1, y1):
    return ((x0 - 266.1) / 8.448, (981.2 - y1) / 8.475, (x1 - 266.1) / 8.448, (981.2 - y0) / 8.475)
stage = {"L2 outline": (43.672, 49.812, 51.072, 56.612), "U1 outline": (45.448, 39.986, 49.549, 44.086),
         "C29-C31 (PMID)": px2mm(585, 568, 640, 597), "C19-C21 (SYS)": px2mm(690, 568, 748, 597), "C37-C40": px2mm(700, 610, 737, 640),
         "SW1 TP3/TP4": px2mm(600, 431, 618, 484), "SW2 TP10/TP11": px2mm(705, 431, 723, 481)}
print("1. EVM outline %.2f x %.2f mm (evm_geometry.md section 3); nearest power-stage copper to each E point:" % (EVM_W, EVM_H))
def rect_dist(p, r):
    x, y = p
    dx = max(r[0] - x, 0, x - r[2])
    dy = max(r[1] - y, 0, y - r[3])
    return math.hypot(dx, dy)
R0 = {}
for k, p in pts.items():
    dmin, which = min((rect_dist(p, r), n) for n, r in stage.items())
    R0[k] = dmin
    print("   %-21s right edge %5.1f mm, bottom edge %5.1f mm, nearest %-15s %5.1f mm"
          % (k, EVM_W - p[0], p[1], which, dmin))

# ------------------------------------------------------------------------------------------------ 2. budgets (criterion)
# Criterion chosen here: the sustained (>= 1 us) pickup at a protected node <= 10 % of the smallest margin of the argument the
# lead serves. The H.4 / H.19 bands already contain tolerance, REF drift, Vos, hysteresis and leakage, so the margin is headroom.
VIL_ILIM = 0.75                     # DOC B.6 / SLUSDV2C 6.5 VIL_ILIM_HIZ max
TRIP_U203 = (0.587, 0.650)          # DOC H.4 pin-referred U203 trip
HELD_MAX = 0.11                     # DOC H.4 held level with Q201 failed open (Q203 off); ~0 V with Q201 on
REL_MIN = 1.52                      # DOC H.4 lowest released level (FC clamp)
# U204 /CE trip: IN- = REF; R3 TLV3012B constants; R262 = R263 = 1.00 MOhm 1 %
VREF = (1.223, 1.260); REF_TC = 100e-6; DT = 45.0; VOS = 0.009; VHYS = 0.008
lo = (VREF[0] * (1 - REF_TC * DT) - VOS - VHYS / 2) * (1 + 0.99 / 1.01)
hi = (VREF[1] * (1 + REF_TC * DT) + VOS + VHYS / 2) * (1 + 1.01 / 0.99)
CE_HIGH_MIN = 4.17                  # DOC H.19, one of R272/R272b open
CE_LOW_MAX = 0.10                   # U201 1Y sinking the 23.5 kOhm pull-ups (0.2 mA): VOL well below 0.1 V (SCES364J VOL 0.1 V at 100 uA) ASSUMED bound
m = {"E3 hold (pin, Q201 on)": VIL_ILIM - 0.0,
     "E4 sense, nuisance (held 0.11 V -> reads released)": TRIP_U203[0] - HELD_MAX,
     "E4 sense, masking (released 1.52 V -> reads held)": REL_MIN - TRIP_U203[1],
     "E6 sense, nuisance (/CE HIGH 4.17 V -> reads LOW)": CE_HIGH_MIN - hi,
     "E6 sense, masking (/CE LOW -> reads HIGH)": lo - CE_LOW_MAX}
print("2. U204 trip referred to /CE: %.2f-%.2f V (R3 TLV3012B constants, 0-45 C rise, 1 %% divider)" % (lo, hi))
for k, v in m.items():
    print("   margin %-55s %.3f V -> 10 %% budget %.0f mV" % (k, v, 100 * v))
B = {"E3": 0.1 * m["E3 hold (pin, Q201 on)"],
     "E4": 0.1 * min(m["E4 sense, nuisance (held 0.11 V -> reads released)"], m["E4 sense, masking (released 1.52 V -> reads held)"]),
     "E6": 0.1 * min(m["E6 sense, nuisance (/CE HIGH 4.17 V -> reads LOW)"], m["E6 sense, masking (/CE LOW -> reads HIGH)"])}
print("   budgets (loop EMF, sustained): E3 %.0f mV, E4 %.0f mV, E6 %.0f mV (E6: the 1:2 divider halves EMF and margin alike)"
      % (B["E3"] * 1e3, B["E4"] * 1e3, B["E6"] * 1e3))

# ------------------------------------------------------------------------------------------------ 3. EVM power stage as a dipole
# di/dt of L2: (V_in - V_bat)/L2. L2 1 uH (UG BOM SPM6530T-1R0M120), 1.5 MHz (JP24, DOC EM19). V_in max = V-MOT static max 19.72 V,
# V_bat min 7.4 V (DOC H regen threshold stack, H.7). Inductor peak current ~ ICHG 3.21 A + ripple/2 (DOC A.3).
L2, FSW = 1e-6, 1.5e6
VIN, VBAT = 19.72, 7.4
didt_rip = (VIN - VBAT) / L2
D = VBAT / VIN
ripple = (VIN - VBAT) * D / (L2 * FSW)
i_pk = 3.21 + ripple / 2
t_on = D / FSW
A_RIP = (5e-6, 50e-6)        # ASSUMED effective area of the ripple loop (U1 SW -> L2 -> C19-C21 -> PGND), m2; T-C-16 replaces it
A_HOT = (1e-6, 10e-6)        # ASSUMED effective area of the input hot loop (C29-C31 -> high-side/low-side FETs), m2
T_EDGE = (2e-9, 10e-9)       # ASSUMED SW edge time of the BQ25798 integrated FETs; T-C-16
print("3. EVM L2 ripple: di/dt %.2f A/us (on-time %.0f ns), ripple %.2f A p-p, inductor peak %.2f A"
      % (didt_rip / 1e6, t_on * 1e9, ripple, i_pk))
dmdt_rip = A_RIP[1] * didt_rip
dmdt_hot = A_HOT[1] * i_pk / T_EDGE[0]
print("   dm/dt upper bounds: ripple loop %.0f A m2/s (sustained %.0f ns), hot loop %.3g A m2/s (%.0f ns edges)"
      % (dmdt_rip, t_on * 1e9, dmdt_hot, T_EDGE[0] * 1e9))
def dip_emf(dmdt, r0, s, L):
    """EMF in a flat two-lead loop (separation s) on a straight route whose closest approach to the dipole is r0, segment
    centred on that point (the maximum for a straight route), Bz <= 2 x mu0/4pi x m / r^3 (upper bound in and out of plane)."""
    return 2 * MU0_4PI * dmdt * s * L / (r0 ** 2 * math.sqrt(r0 ** 2 + L ** 2 / 4))
print("   EMF in a lead pair (s = 5 mm untwisted) vs length, closest approach r0 (ripple: sustained; hot loop: ns, before filtering):")
for r0 in (0.010, 0.013, 0.020):
    row = []
    for L in (0.010, 0.030, 0.060, 0.100, 0.300):
        row.append("L %3.0f mm: %4.1f mV / %4.0f mV" % (L * 1e3, 1e3 * dip_emf(dmdt_rip, r0, 0.005, L), 1e3 * dip_emf(dmdt_hot, r0, 0.005, L)))
    print("   r0 %2.0f mm  " % (r0 * 1e3) + "; ".join(row))
asym = lambda dmdt, r0, s: 2 * MU0_4PI * dmdt * s * 2 / r0 ** 2
print("   asymptote (L -> inf) at r0 13 mm: ripple %.1f mV, hot loop %.0f mV: the EVM term saturates with length (field ~ r^-3)"
      % (1e3 * asym(dmdt_rip, 0.013, 0.005), 1e3 * asym(dmdt_hot, 0.013, 0.005)))
# minimum clearance at which the sustained ripple pickup reaches each budget (s = 5 mm, L -> inf)
for k, b in B.items():
    r_min = math.sqrt(2 * MU0_4PI * dmdt_rip * 0.005 * 2 / b)
    print("   %s: ripple pickup reaches the %.0f mV budget only below r0 = %.1f mm from the stage centre-line (dipole model invalid there)"
          % (k, b * 1e3, r_min * 1e3))

# ns-class filtering at the protected nodes
C252 = 2.2e-9
def loop_L(Lm, s, a=0.16e-3):
    return 4 * MU0_4PI * Lm * math.log(s / a)          # two-wire loop inductance, mu0/pi ln(s/a) per metre
print("   ns spike at the ILIM_HIZ pin with Q201 on (impulse into the E3+E8 loop, rings on C252):")
for Lm in (0.010, 0.060, 0.300):
    for s in (0.6e-3, 5e-3):
        Ll = loop_L(Lm, s)
        e = dip_emf(dmdt_hot, 0.013, s, Lm)
        v = (e * T_EDGE[0] / Ll) * math.sqrt(Ll / C252)
        print("     L %3.0f mm s %.1f mm: L_loop %5.1f nH, EMF %5.0f mV for %.0f ns -> pin peak %4.1f mV (budget %.0f mV)"
              % (Lm * 1e3, s * 1e3, Ll * 1e9, e * 1e3, T_EDGE[0] * 1e9, v * 1e3, B["E3"] * 1e3))
C_IN = (3e-12, 8e-12)        # ASSUMED U203 IN+ node (TLV3012B input + layout); SBOS300C gives no input capacitance in the library
for c in C_IN:
    tau = 10e3 * c
    att = (T_EDGE[0] / tau)
    print("   E4: R258 10.0 kOhm x %.0f pF = %.0f ns; a %.0f ns spike reaches IN+ at ~%.2f of its EMF; TLV3012B response 2-4 us (DOC B.1)"
          % (c * 1e12, tau * 1e9, T_EDGE[0] * 1e9, att))

# ------------------------------------------------------------------------------------------------ 4. parallel aggressor conductors
print("4. Parallel aggressor conductor (line current, coplanar worst case), M' = mu0/2pi ln((d+s)/d):")
CLASSES = {"A (load steps, >= 1 us: 1 A/us)": 1e6, "B (inductor-ripple class: 10 A/us; EVM L2 12.3 A/us, MB boost 3.8 A/us)": 1e7}
geoms = {"untwisted s 5 mm, d 10 mm": (0.005, 0.010), "untwisted s 2 mm, d 10 mm": (0.002, 0.010),
         "untwisted s 5 mm, d 20 mm": (0.005, 0.020)}
P_TWIST, S_TW = 0.025, 0.6e-3   # twist pitch from the A.3 W1/W2 rule; centre spacing of two touching 28 AWG Kynar leads ASSUMED 0.6 mm
Lmax = {}
for gk, (s, d) in geoms.items():
    Mp = MU0_2PI * math.log((d + s) / d)
    for ck, didt in CLASSES.items():
        lm = {k: b / (Mp * didt) for k, b in B.items()}
        Lmax[(gk, ck)] = lm
        print("   %-27s M' %.3g H/m  class %-70s L_max E3 %6.0f mm, E4 %6.0f mm, E6 %6.0f mm"
              % (gk, Mp, ck, lm["E3"] * 1e3, lm["E4"] * 1e3, lm["E6"] * 1e3))
M_res = MU0_2PI * math.log((0.010 + S_TW) / 0.010) * P_TWIST / 2
for ck, didt in CLASSES.items():
    print("   twisted (pitch 25 mm, s 0.6 mm, d 10 mm): residual one half twist M %.3g H -> %.2f mV at class %s, independent of length"
          % (M_res, M_res * didt * 1e3, ck.split()[0]))

# ------------------------------------------------------------------------------------------------ 5. capacitive pickup
# Two-wire capacitance between a lead (r 0.3 mm with insulation) and an aggressor (r 1.0 mm) at centre distance D:
# C' = pi eps0 / acosh((D^2 - a1^2 - a2^2)/(2 a1 a2)); lead to chassis at height hh: C' = 2 pi eps0 / acosh(hh/a)
def c_two(D, a1, a2):
    return math.pi * EPS0 / math.acosh((D * D - a1 * a1 - a2 * a2) / (2 * a1 * a2))
Cc = c_two(0.010, 0.3e-3, 1.0e-3)
Cg = 2 * math.pi * EPS0 / math.acosh(0.005 / 0.16e-3)
DV = 20.0     # ASSUMED aggressor edge amplitude: a V-MOT/VBUS-class switched conductor (VESC phase, boost SW) <= 20 V
print("5. Capacitive pickup: lead-to-aggressor C' %.1f pF/m at 10 mm, lead-to-chassis C' %.1f pF/m at 5 mm height; aggressor edge %.0f V"
      % (Cc * 1e12, Cg * 1e12, DV))
for Lm in (0.010, 0.060, 0.300):
    cc = Cc * Lm
    print("   L %3.0f mm (parallel run): C_c %.2f pF -> ILIM_HIZ node (C252 2.2 nF) %.1f mV; /CE node (23.5 kOhm, C %.1f pF + 5 pF pin ASSUMED) %.2f V for ~%.2f us"
          % (Lm * 1e3, cc * 1e12, DV * cc / (C252 + cc) * 1e3, Cg * Lm * 1e12, DV * cc / (cc + Cg * Lm + 5e-12),
             23.5e3 * (cc + Cg * Lm + 5e-12) * 1e6))
# lead-off of a sense lead: the floating lead hangs on the comparator input behind its defining resistor
print("   lead-off masking: a floating E4 (R259 10 MOhm pulls IN+ to 3V3 = 'released') or E6 (R262 + R263 2 MOhm pulls IN+ to 0 = '/CE LOW'):")
for Lm in (0.030, 0.060, 0.300):
    cc = Cc * Lm; cl = Cg * Lm + 3e-12
    dv = DV * cc / (cc + cl)
    print("     L %3.0f mm: spike %.2f V at the lead, recovery tau E4 %.0f us, E6 %.0f us (an aggressor edge every 33-50 us at 20-30 kHz PWM ASSUMED)"
          % (Lm * 1e3, dv, 10e6 * (cc + cl) * 1e6, 2e6 * (cc + cl) * 1e6))

# ------------------------------------------------------------------------------------------------ 6. hold-loop dynamics, E1 ring
CISS = 50e-12; R252 = 47e3                     # R3 H.13 (Ciss ASSUMED 50 pF, T-A-03)
tau_g = R252 * CISS
print("6. Q201 turn-on through R252: tau %.2f us; the 2N7002K Rds passes the hold-loop Z0 over ~us, much slower than the LC period" % (tau_g * 1e6))
for Lm in (0.020, 0.060, 0.100, 0.300):
    for s in (0.6e-3, 5e-3):
        Ll = loop_L(Lm, s)
        f0 = 1 / (2 * math.pi * math.sqrt(Ll * C252))
        Z0 = math.sqrt(Ll / C252)
        print("   E3+E8 L %3.0f mm s %.1f mm: L_loop %5.1f nH, f0 with C252 %5.2f MHz, Z0 %4.1f ohm (Q201 Rds 2-4 ohm -> zeta %.2f-%.2f once fully on)"
              % (Lm * 1e3, s * 1e3, Ll * 1e9, f0 / 1e6, Z0, 2 / (2 * Z0), 4 / (2 * Z0)))
C205 = 100e-9
for Lm in (0.020, 0.060, 0.085, 0.300):
    Ll = loop_L(Lm, 5e-3)
    print("   E1 + C205 100 nF, L %3.0f mm (return via E8, s 5 mm): L %5.1f nH, f0 %.2f MHz, critical damping R = sqrt(L/C) %.2f ohm"
          % (Lm * 1e3, Ll * 1e9, 1 / (2 * math.pi * math.sqrt(Ll * C205)) / 1e6, math.sqrt(Ll / C205)))
ESR205 = 0.02          # ASSUMED X7R 0603 100 nF ESR near 1.5 MHz; T-C-16 measures the ring
f_gate = 1 / (2 * math.pi * R252 * CISS)
print("   E1 ring: Q = sqrt(L/C)/(R_lead + ESR %.0f mOhm); the Q201 gate low-pass R252 x Ciss = %.0f kHz attenuates a 1.5 MHz ripple %.0fx"
      % (ESR205 * 1e3, f_gate / 1e3, math.hypot(1, FSW / f_gate)))
for Lm in (0.060, 0.085):
    Ll = loop_L(Lm, 5e-3)
    for rs in (0.0, 10.0, 100.0):
        rtot = 0.2129 * Lm * 2 + ESR205 + rs          # 28 AWG E1 + E8 (AWG table) + ESR + series R
        q = math.sqrt(Ll / C205) / rtot
        dv_rel = 0.36e-3 * rs * 39.9 / 88.6          # gate pull-ups + feed <= 0.36 mA (DOC H.15) through rs; release Thevenin 39.9/88.6
        print("     L %2.0f mm, series R_E1 %5.1f ohm: Q %5.1f; release-level shift %.1f mV = %.0f mA of ILIM clamp (0.8 ohm/V, DS 7.3.4.3)"
              % (Lm * 1e3, rs, q, dv_rel * 1e3, dv_rel / 0.8 * 1e3))
# H.13 with lead capacitance
tau_ilim = par(48.7e3, 49.9e3, 200e3) * C252
for Lm in (0.060, 0.300):
    cl = 2 * Cg * Lm + 2 * 20e-12 * Lm / 0.3   # E2 + E3 + E4 leads to chassis, ASSUMED <= 3 x lead C'
    print("   H.13 tau %.1f us with C252 alone; leads E2/E3/E4 add <= %.0f pF (%.1f %%) at L %3.0f mm -> H.13 0.28 / 0.32 V unchanged"
          % (tau_ilim * 1e6, 3 * Cg * Lm * 1e12, 100 * 3 * Cg * Lm / C252, Lm * 1e3))

# ------------------------------------------------------------------------------------------------ 7. ground: E8 share, island
R18, R20, R28 = 20.95e-3, 33.31e-3, 212.9e-3     # AWG, ohm/m
I_NET = 1.5                                      # DOC A.6: net EVM ground current 1.4-1.6 A
R273 = 10.0
print("7. Ground. EVM AGND reaches the CR plane through E8 (+ island R273) in parallel with W2 (20 AWG) || W4 (18 AWG)")
for tag, lw, le in (("G1 W 60 mm, E8 20 mm", 0.060, 0.020), ("G1 W 60 mm, E8 60 mm", 0.060, 0.060), ("r6 W 0.30 m, E8 20 mm", 0.30, 0.020),
                    ("G2 W 0.10 m, E8 0.10 m", 0.10, 0.10), ("G2 W 0.30 m, E8 0.30 m", 0.30, 0.30)):
    rw = par(R20 * lw, R18 * lw)
    re = R28 * le
    direct = I_NET * rw / (re + rw)
    island = I_NET * rw / (re + R273 + rw)
    off_scaled = 0.0195 * lw / 0.30                # DOC H.11: W4 drop 39 mV per pair at 3.10 A -> 19.5 mV per conductor at 0.30 m
    print("   %-24s W2||W4 %.2f mOhm, E8 %.1f mOhm: E8 current without island %4.0f mA (T-F-11 limit 20 mA); with R273 island %.2f mA;"
          " plane-to-EVM offset <= %.1f mV (H.11 scaled) -> R273 current <= %.2f mA"
          % (tag, rw * 1e3, re * 1e3, direct * 1e3, island * 1e3, off_scaled * 1e3, off_scaled / R273 * 1e3))

# ------------------------------------------------------------------------------------------------ 8. lead resistance in the H.4 levels
for Lm in (0.060, 0.300):
    r = R28 * Lm
    print("8. 28 AWG %3.0f mm = %.1f mOhm: in series with R255 48.7 kOhm %.2g of the release level; E3 hold drop at 3 uA leakage %.2g uV;"
          " U203 R259 0.33 uA x lead %.2g uV; E8 drop at 2 mA %.2f mV" % (Lm * 1e3, r * 1e3, r / 48.7e3, 3e-6 * r * 1e6, 0.33e-6 * r * 1e6, 2e-3 * r * 1e3))

# ------------------------------------------------------------------------------------------------ 9. merged-CR area
eib_parts = {"U203, U204 SOT-23-6": 2 * 10, "U201 SSOP-8": 15, "U202 SC70-5": 7, "Q201-Q203 SOT-23": 3 * 10,
             "31 x 0603 passives (R3 H.18b) less R176/R177 not on the EIB": 31 * 4.3, "8 E-lead pads (1.0 mm hole)": 8 * 6}
add = sum(eib_parts.values())
freed = 3.9 * 9.4                               # DOC A.8 J101 body courtyard x 38.55-42.45, y 42.13-51.53
print("9. EIB section on the CR: courtyard ~%.0f mm2 (H.18b basis without J201 and the two M3 keep-outs); J101 body freed %.0f mm2;"
      " net CR increase ~%.0f mm2 against a top side at ~678 of ~881 mm2 (DOC H.22(k)) -> %.0f mm2 = %.0f %% of the r6 top area"
      % (add, freed, add - freed, 678 + add - freed, 100 * (678 + add - freed) / 881))
