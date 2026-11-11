"""tall_stack_calc.py - tall header stack checks for the CCB on the testbench (r2).

Context: operator statement, 2026-11-10: the vehicle does not move (testbench pushing flywheels), a fan may be
mounted on the CCB, and the CCB has no height restriction. A ducted underside gap of 5-12 mm then helps cooling.
This script checks what a taller stack costs electrically and mechanically, for gap heights H_u = 5, 8, 10, 12 mm,
against the r1 option-S baseline H_u = 2.54 mm (document 1.3.2).

Sections:
  (a) extra pin length, extra DC resistance, extra I2R at the 3.3.1 per-pin currents
  (b) extra loop inductance of the input pin (pad 10) with its return pin (pad 4)
  (c) eFuse hard-short IN-side spike (round-3 H.19 (b)/(d), T-C-04) reproduced with the CCB values
  (d) I2C and other header signals through the taller pins
  (e) mechanical: header classes, foot spacer, overhang deflection, lateral sway, socket pull-out

Every input is a cited document value or a stated general value marked TODO(verify). Run with
C:\\Users\\ricky\\miniforge3\\python.exe -I tall_stack_calc.py > tall_stack_calc_out.txt
"""
import math

MU0 = 4e-7 * math.pi
EPS0 = 8.854e-12

GAPS_MM = (5.0, 8.0, 10.0, 12.0)
H_U_R1 = 2.54                    # r1 option S, H_u = plastic body height (document 1.3.2)
T_MB = 1.6608                    # MB thickness, document Table 1.1 ([STUDY] 4.2)
T_CCB = 1.6                      # CCB thickness, document 1.3.2, TODO(verify: CCB fab stack-up)
A_SIDE = 0.64e-3                 # pin section, document Table 1.1 ([AG] Fig 11)
A_PIN = A_SIDE ** 2
RHO_PIN = 1.1e-7                 # ohm m, phosphor bronze general value, as layout_calc.py section 7; TODO(verify: Samtec pin alloy)
L_PIN_R1 = 6e-3                  # r1 electrical pin-body length, layout_calc.py section 7
K_PIN = 70.0                     # W/mK phosphor bronze general value, layout_calc.py line 115
R_GMD = 0.4470 * A_SIDE          # magnetic equivalent radius of a square conductor (GMD 0.447a; Grover, Inductance Calculations, 1946) TODO(verify: citation page)
R_CAP = 0.5903 * A_SIDE          # electrostatic equivalent radius of a square conductor (0.59a, conformal-map result) TODO(verify: citation)

# pin coordinates, document Table 1.1 / 1.8 ([MECH] pad table)
def pin_xy(n):
    if 1 <= n <= 10:
        return 45.998, 39.084 + (n - 1) * 2.54
    return 20.998, 64.484 - (n - 11) * 2.54

def hr(t):
    print("\n== " + t + " ==")

print("Tall header stack checks (r2). Baseline: r1 option S, H_u = %.2f mm. Gaps H_u = %s mm." % (H_U_R1, ", ".join("%.0f" % g for g in GAPS_MM)))

# ---------------------------------------------------------------------------------------------------------------- (a)
hr("(a) Extra pin length, DC resistance and I2R per pin")
# per-pin currents, document 3.3.1 Table 3.7 ([WD] H.4, B.4, A.8 r6 60/40)
CURRENTS = (("10 VCHGIN", 1.76, "continuous"), ("10 VCHGIN", 2.41, "<= 202 ms"),
            ("4 GND input return", 1.76, "continuous"), ("4 GND input return", 2.41, "<= 202 ms"),
            ("18 VCHG (60 %)", 1.93, "continuous"), ("19 VCHG (40 %)", 1.28, "continuous"),
            ("14 GND batt return (60 %)", 1.93, "continuous"), ("15 GND batt return (40 %)", 1.28, "continuous"))
r_per_mm = RHO_PIN * 1e-3 / A_PIN
print("  pin resistance per mm (0.64 mm square, rho %.2e ohm m): %.3f mOhm/mm; r1 body (6 mm) %.2f mOhm" % (RHO_PIN, r_per_mm * 1e3, RHO_PIN * L_PIN_R1 / A_PIN * 1e3))
print("  pin thermal resistance per mm (k %.0f W/mK): %.1f C/W per mm (pin conduction to the MB falls as 1/length)" % (K_PIN, 1e-3 / (K_PIN * A_PIN)))
for g in GAPS_MM:
    dl = g - H_U_R1
    dr = r_per_mm * dl
    print("  H_u %.0f mm: extra length %.2f mm; extra R %.3f mOhm per pin; pin body total %.2f mOhm; pin thermal R %.0f C/W (r1 %.0f C/W, 2.54 + 1.6 mm path)"
          % (g, dl, dr * 1e3, RHO_PIN * (L_PIN_R1 + dl * 1e-3) / A_PIN * 1e3,
             (g + T_CCB) * 1e-3 / (K_PIN * A_PIN), (H_U_R1 + T_CCB) * 1e-3 / (K_PIN * A_PIN)))
    tot_cont = 0.0
    for name, i, dur in CURRENTS:
        p = i * i * dr
        if dur == "continuous":
            tot_cont += p
        print("      pin %-26s %.2f A (%s): extra I2R %.2f mW" % (name, i, dur, p * 1e3))
    print("      sum over the six power pins, continuous: %.1f mW extra (r1 6 mm bodies at the same currents: %.1f mW)"
          % (tot_cont * 1e3, sum(i * i for _, i, d in CURRENTS if d == "continuous") * RHO_PIN * L_PIN_R1 / A_PIN * 1e3))

# ---------------------------------------------------------------------------------------------------------------- (b)
hr("(b) Extra loop inductance, input pin (pad 10) with its return pin (pad 4)")
x10, y10 = pin_xy(10); x4, y4 = pin_xy(4); x14, y14 = pin_xy(14)
D_4_10 = math.hypot(x10 - x4, y10 - y4)
D_14_10 = math.hypot(x10 - x14, y10 - y14)
print("  pad 10 at (%.3f, %.3f), pad 4 at (%.3f, %.3f): spacing %.2f mm (6 pitches); pad 14 at %.2f mm" % (x10, y10, x4, y4, D_4_10, D_14_10))
print("  formula 1 (two-wire line, per unit length, end effects neglected): L' = (mu0/pi) acosh(D / 2r), r = GMD radius %.3f mm" % (R_GMD * 1e3))
print("            source: the parallel two-wire inductance (C. R. Paul, Inductance: Loop and Partial, Wiley 2010, ch. 4) TODO(verify: page)")
def lprime(D):
    return MU0 / math.pi * math.acosh(D / (2 * R_GMD))
def rect_loop(w, h, r):
    # rectangular loop of round wire, high-frequency form (no internal inductance); Grover 1946 / Rosa.
    d = math.hypot(w, h)
    return MU0 / math.pi * (w * math.log(2 * w / r) + h * math.log(2 * h / r) + 2 * d
                            - w * math.asinh(w / h) - h * math.asinh(h / w) - 2 * (w + h))
print("            L' at 2.54 mm spacing (adjacent pair, as specified): %.3f nH/mm" % (lprime(2.54e-3) * 1e6))
print("            L' at %.2f mm (the real 4-10 pair): %.3f nH/mm" % (D_4_10, lprime(D_4_10 * 1e-3) * 1e6))
print("  formula 2 (rectangular loop w x h of round wire, Grover/Rosa HF form), increment from the r1 height;")
print("            vertical side h = H_u + t_MB/2 + t_CCB/2 (plane to plane); the horizontal sides stand in for the MB and CCB copper")
DL_IN = {}
for g in GAPS_MM:
    dl = (g - H_U_R1) * 1e-3
    h0 = (H_U_R1 + T_MB / 2 + T_CCB / 2) * 1e-3
    h1 = h0 + dl
    a254 = lprime(2.54e-3) * dl
    a1524 = lprime(D_4_10 * 1e-3) * dl
    r254 = rect_loop(2.54e-3, h1, R_GMD) - rect_loop(2.54e-3, h0, R_GMD)
    r1524 = rect_loop(D_4_10 * 1e-3, h1, R_GMD) - rect_loop(D_4_10 * 1e-3, h0, R_GMD)
    DL_IN[g] = max(a254, a1524, r254, r1524)
    print("  H_u %.0f mm (+%.2f mm): two-wire 2.54 mm %.1f nH, two-wire %.2f mm %.1f nH; rectangle 2.54 mm %.1f nH, rectangle %.2f mm %.1f nH -> bound used %.1f nH"
          % (g, dl * 1e3, a254 * 1e9, D_4_10, a1524 * 1e9, r254 * 1e9, D_4_10, r1524 * 1e9, DL_IN[g] * 1e9))
print("  note: pads 14/15 (about %.1f mm from pad 10) carry part of the return in parallel, so the 4-10 pair is an upper bound" % D_14_10)
# partial self-inductance of one pin, for the ground-shift estimate in (d)
def lpartial(l, r):
    return MU0 * l / (2 * math.pi) * (math.log(2 * l / r) - 1.0)   # straight round wire, HF form (Grover 1946)

# ---------------------------------------------------------------------------------------------------------------- (c)
hr("(c) eFuse IN-side spike at a hard-short turn-off (round-3 H.19 (b)/(d); T-C-04)")
# Model reproduced from docs/reviews/charger_eval_2026-11-05/round3/calc/r3_calc.py in_spike() (read-only source):
# source C_S at V0 (MB C-D8 + C-D10), R_IN 45 mOhm (MB copper), L_IN (MB trace + vias + pin, 50-150 nH, .brd estimate),
# node IN with C_IN, FET 31 mOhm, OUT node C_OUT through L_OUT to the short; the FET opens abruptly 1 us after its
# current crosses 45 A (TPS26630 SLVSE94G 6.6 hot-short response, as cited in r3). Ideal: no ESR, no FET linear region,
# no TVS conduction. The peak is therefore an upper bound; T-C-04 measures. Integration: semi-implicit Euler as r3.
def in_spike(v0, cs, lin, cin, rin=0.045, ron=0.031, cout=1.0e-6, lout=0.15e-6, dt=1e-9, tend=12e-6):
    vs, vin, vout = v0, v0, v0
    i_in, i_fet, i_out = 0.0, 0.0, 0.0
    t, t_cross, on, vpk, i_off = 0.0, None, True, v0, 0.0
    vs_pk = -1e9
    while t < tend:
        i_in += (vs - i_in * rin - vin) / lin * dt
        i_fet = (vin - vout) / ron if on else 0.0
        i_out += vout / lout * dt
        vs -= i_in / cs * dt
        vin += (i_in - i_fet) / cin * dt
        vout += (i_fet - i_out) / cout * dt
        if on and t_cross is None and i_fet > 45.0:
            t_cross = t
        if on and t_cross is not None and t >= t_cross + 1e-6:
            on = False; i_off = i_in
        if not on:
            vpk = max(vpk, vin)
            vs_pk = max(vs_pk, vs)
        t += dt
    return vpk, i_off, vs_pk

# 1. reproduction check against r3_calc_out.txt line 208 / 359 (C_IN 3.4 uF, V0 22 V, C_S 20 uF, L_IN 150 nH: 32.8 V, 65 A; MB end 20.7 V)
vpk, ioff, vspk = in_spike(22.0, 20e-6, 150e-9, 3.4e-6)
print("  reproduction (r3 case: C_IN 3.4 uF, L_OUT 150 nH W1/W2, C_OUT 1 uF, V0 22 V, C_S 20 uF, L_IN 150 nH): IN %.1f V, I_off %.0f A, MB end %.1f V"
      " (r3_calc_out.txt: 32.8 V, 65 A, 20.7 V)" % (vpk, ioff, vspk))
# convergence check of the step
vpk2, ioff2, _ = in_spike(22.0, 20e-6, 150e-9, 3.4e-6, dt=0.25e-9)
print("  step check dt 0.25 ns: IN %.2f V vs %.2f V at 1 ns" % (vpk2, vpk))
for lo in (20e-9, 5e-9):
    a_ = in_spike(22.0, 20e-6, 150e-9, 3.4e-6, lout=lo, dt=0.5e-9)[0]
    b_ = in_spike(22.0, 20e-6, 150e-9, 3.4e-6, lout=lo, dt=0.1e-9)[0]
    print("  step check L_OUT %.0f nH: IN %.2f V at 0.5 ns, %.2f V at 0.1 ns" % (lo * 1e9, a_, b_))

# 2. CCB values. C_IN = C302a 1.0 uF + C302b 4.7 uF + C302c 0.1 uF, 100 V (document 1.11.1); effective >= 3.4 uF at 23.6 V
#    for the 1.0 + 4.7 uF pair (r3 H.19 label), nominal 5.8 uF. C_OUT = C303 1.0 uF (document 1.11.1); the short is at the
#    C511/C512 pads through on-board copper (T-C-04 changed step (2), document Table 7.x row T-C-04), so L_OUT falls from
#    the 150 nH W1/W2 estimate to a copper value: 5-20 nH assumed, TODO(calc: L_OUT from the capture).
#    L_IN = r3 50-150 nH (unchanged MB side, document 1.11.2 item 4) + the tall-stack increment of (b).
LIMITS = "U301 IN abs max 67 V (SLVSE94G 6.1 via r3); T-C-04 IN criterion 60 V (r3 H.19 (d)); D307 SMAJ33A-class VBR min 36.7 V (TVS starts to conduct; not modelled); MB end 35 V (C-D8/C-D10) / 40 V (RT1987 VOUT)"
print("  limits: " + LIMITS)
rows = []
for lout_lab, lout in (("W1/W2 150 nH (r3)", 150e-9), ("copper 20 nH", 20e-9), ("copper 10 nH", 10e-9), ("copper 5 nH", 5e-9)):
    for cin_lab, cin in (("C_IN eff 3.4 uF", 3.4e-6), ("C_IN nom 5.8 uF", 5.8e-6)):
        for gap in (H_U_R1,) + GAPS_MM:
            dL = 0.0 if gap == H_U_R1 else DL_IN[gap]
            worst = None
            mbw = None
            for v0 in (16.0, 22.0):
                for cs in (4e-6, 5e-6, 10e-6, 20e-6):
                    for lin in (50e-9, 150e-9):
                        dt = 1e-9 if lout >= 20e-9 else 0.5e-9
                        r = in_spike(v0, cs, lin + dL, cin, lout=lout, dt=dt)
                        if worst is None or r[0] > worst[0][0]:
                            worst = (r, v0, cs, lin)
                        if mbw is None or r[2] > mbw[0]:
                            mbw = (r[2], v0, cs, lin)
            (vp, io, vs_), v0, cs, lin = worst
            rows.append((lout_lab, cin_lab, gap, vp, io, v0, cs, lin, dL, mbw))
            print("  %-18s %-16s H_u %5.2f mm (+%4.1f nH): worst IN %5.1f V (I_off %4.0f A; V0 %.0f V, C_S %.0f uF, L_IN %.0f nH); worst MB end %4.1f V"
                  % (lout_lab, cin_lab, gap, dL * 1e9, vp, io, v0, cs * 1e6, lin * 1e9, mbw[0]))
print("  verdicts:")
for lout_lab in ("W1/W2 150 nH (r3)", "copper 20 nH", "copper 10 nH", "copper 5 nH"):
    for cin_lab in ("C_IN eff 3.4 uF",):
        base = [r for r in rows if r[0] == lout_lab and r[1] == cin_lab and r[2] == H_U_R1][0]
        top = [r for r in rows if r[0] == lout_lab and r[1] == cin_lab and r[2] == 12.0][0]
        print("    %s, %s: IN %.1f V at 2.54 mm -> %.1f V at 12 mm (+%.1f V); MB end %.1f -> %.1f V; above 36.7 V (TVS conducts): %s; above 60 V: %s; above 67 V: %s"
              % (lout_lab, cin_lab, base[3], top[3], top[3] - base[3], base[9][0], top[9][0],
                 "yes" if top[3] > 36.7 else "no", "yes" if top[3] > 60 else "no", "yes" if top[3] > 67 else "no"))
# undepleted lossless bound (r3 H.19 (d) verifier model) with the added inductance
print("  undepleted lossless bound (r3 verifier model, I0 65 A, C102 3.4 uF, V0 22 V), L_IN 150 nH + increment:")
for gap in (H_U_R1,) + GAPS_MM:
    dL = 0.0 if gap == H_U_R1 else DL_IN[gap]
    for cs in (4e-6, 20e-6):
        ceq = 3.4e-6 * cs / (3.4e-6 + cs)
        A = 65.0 * math.sqrt((150e-9 + dL) / ceq)
        print("    H_u %5.2f mm, C_S %2.0f uF: U301 IN %.1f V, MB end %.1f V" % (gap, cs * 1e6, 22 + A * cs / (3.4e-6 + cs), 22 + A * 3.4e-6 / (3.4e-6 + cs)))

# ---------------------------------------------------------------------------------------------------------------- (d)
hr("(d) Signals through the taller pins")
print("  header signals (document 2.5.2): pad 3 STAT, 7 SCL, 8 SDA, 11 MPPTD (CHG_ARM), 13 THERM (TS_EXT); the comparator taps F01-F24 are flying leads to")
print("  top-side SMT pads (document 2.5.9, 1.3.5), not header pins: the header height changes their lead length only.")
def cprime(D):
    return math.pi * EPS0 / math.acosh(D / (2 * R_CAP))
print("  two-wire capacitance per mm, C' = pi eps0 / acosh(D / 2r), r = %.3f mm: %.4f pF/mm at 2.54 mm, %.4f pF/mm at 5.08 mm, %.4f pF/mm at 7.62 mm"
      % (R_CAP * 1e3, cprime(2.54e-3) * 1e9, cprime(5.08e-3) * 1e9, cprime(7.62e-3) * 1e9))
# SCL pad 7: neighbours pad 6 (isolated anchor), pad 8 SDA, pad 5 (isolated), pad 4 GND (3 pitches), pad 9/10.
# Bound: sum of pairwise C' to every column neighbour within 4 pitches, treated as grounded (over-counts).
c_bound_pm = 2 * (cprime(2.54e-3) + cprime(5.08e-3) + cprime(7.62e-3) + cprime(10.16e-3))
RP = 2.7e3   # MB RSDA/RSCL (document 2.2.1 Table, PM9)
TR_MAX = 300e-9   # Fast-mode 400 kHz rise time max (NXP UM10204 Table 10) TODO(verify: rev and table number)
cb_max = TR_MAX / (0.8473 * RP)
print("  per-pin added capacitance bound (all column neighbours within 4 pitches, both sides, as grounded): %.4f pF/mm" % (c_bound_pm * 1e9))
print("  rise time tr = 0.8473 R_p C_b (30-70 %%, UM10204): with R_p 2.7 kOhm the 300 ns Fast-mode limit allows C_b <= %.0f pF" % (cb_max * 1e12))
for g in GAPS_MM:
    dl = (g - H_U_R1) * 1e-3
    dc = c_bound_pm * dl
    print("  H_u %.0f mm: added C <= %.2f pF per I2C line; added tr <= %.2f ns (%.2f %% of 300 ns); SCL->SDA coupling C %.3f pF; added pin L %.1f nH (partial)"
          % (g, dc * 1e12, 0.8473 * RP * dc * 1e9, 0.8473 * RP * dc / TR_MAX * 100, cprime(2.54e-3) * dl * 1e12,
             (lpartial(g * 1e-3 + 1.63e-3, R_GMD) - lpartial(H_U_R1 * 1e-3 + 1.63e-3, R_GMD)) * 1e9))
print("  the bus capacitance C_b itself is unmeasured: TODO(measure: SCL/SDA rise time on the CCB, measurement item 15 / 5.8 item 9)")
# ground shift across the inter-board GND pins during the hard-short turn-off
print("  inter-board ground shift at the hard-short turn-off: the short current returns through pads 4, 14, 15 (the only GND pins; the anchors are isolated)")
for g in (H_U_R1,) + GAPS_MM:
    lp = lpartial(g * 1e-3 + 1.63e-3, R_GMD)
    for tf in (1e-6, 0.1e-6):
        di = 65.0 / tf
        print("    H_u %5.2f mm: one-pin partial L %.2f nH; with 65 A (r3 worst I_off) falling in %.1f us: %.2f V (one pin) to %.2f V (three pins, no mutual)"
              % (g, lp * 1e9, tf * 1e6, lp * di, lp / 3 * di))
print("    the eFuse turn-off fall time is TODO(verify: SLVSE94G); the shift is common to every signal crossing the header and to the CCB")
print("    reference of the comparators against the MB-referenced taps; it lasts for the turn-off edge only (fault event)")

# ---------------------------------------------------------------------------------------------------------------- (e)
hr("(e) Mechanical")
print("  header options by gap (seat heights and lead styles TODO(verify: maker drawing) for every class):")
for g in GAPS_MM:
    l_tot = 1.0 + T_MB + g + T_CCB + 1.5
    print("  H_u %.0f mm: option S total pin length >= %.1f mm (1.0 mm tail under the MB + %.2f MB + %.0f gap + %.1f CCB + 1.5 mm above the CCB); option K socket seat h_k = %.2f mm"
          % (g, l_tot, T_MB, g, T_CCB, g - 2.54))
print("  classes: S1 Samtec TSW-110/-112-xx-G-S with a long-post lead style (TODO(verify: TSW lead-style table, post and tail lengths));")
print("           S2 Samtec MTSW-110/-112 movable-body header, body set at the gap (TODO(verify: MTSW pin lengths));")
print("           S3 standard header plus a plastic spacer strip at the gap height (TODO(verify: spacer MPN));")
print("           K1 Samtec SSW/SSQ socket strip (SSW body 8.51 mm per document 1.3.2, TODO(verify: Samtec SSW drawing)) + TSW male: H_u = 8.51 + 2.54 = 11.05 mm;")
print("           K2 Samtec ESQ elevated socket strip (long tail, stacking) at the gap: TODO(verify: ESQ heights);")
print("           K3 Harwin M20 series female + long-pin male (TODO(verify: Harwin MPN and heights)).")
print("  the two strips run along y (document 1.1), so they form two walls of a y-directed duct between x 21.0 and x 46.0 (25.0 mm)")

E_FR4 = 20e9      # Pa, task value ~20 GPa; TODO(verify: laminate flexural modulus, fab datasheet)
E_PIN = 110e9     # Pa, phosphor bronze general value; TODO(verify: Samtec pin alloy)
E_NYL = 2.8e9     # Pa, nylon 6/6 general value; TODO(verify: spacer datasheet)
B_TAB = 21.2e-3   # tab width, document 1.8
I_PLATE = B_TAB * (T_CCB * 1e-3) ** 3 / 12
Y_TIP = 76.40; Y_FOOT = 70.64
print("  overhang beam: Euler-Bernoulli, width %.1f mm (tab, document 1.8), t %.1f mm, E %.0f GPa, I %.2f mm^4; clamp line at the last pin row,"
      % (B_TAB * 1e3, T_CCB, E_FR4 / 1e9, I_PLATE * 1e12))
print("  load at the tab edge y %.2f; foot at y %.2f (document 1.4) as a spring support (nylon spacer axial stiffness)" % (Y_TIP, Y_FOOT))
s_hex = 5.5e-3; a_hex = s_hex / math.sqrt(3); d_hole = 3.0e-3
A_hex = 3 * math.sqrt(3) / 2 * a_hex ** 2 - math.pi * d_hole ** 2 / 4
I_hex = 5 * math.sqrt(3) / 16 * a_hex ** 4 - math.pi * d_hole ** 4 / 64
for yc, lab in ((64.484, "clamp y 64.484 (pin 11, left column end)"), (61.944, "clamp y 61.944 (pin 10, right column end)")):
    L = (Y_TIP - yc) * 1e-3; a = (Y_FOOT - yc) * 1e-3
    for F in (5.0, 10.0):
        d_free = F * L ** 3 / (3 * E_FR4 * I_PLATE)
        out = []
        for g in GAPS_MM:
            k_foot = 2 * E_NYL * A_hex / (g * 1e-3)            # two feet
            # compatibility at the prop: F a^2(3L-a)/(6EI) - R a^3/(3EI) = R / k
            EI = E_FR4 * I_PLATE
            R = (F * a ** 2 * (3 * L - a) / (6 * EI)) / (a ** 3 / (3 * EI) + 1 / k_foot)
            d_tip = F * L ** 3 / (3 * EI) - R * a ** 2 * (3 * L - a) / (6 * EI)
            out.append("H_u %.0f: %.4f mm (prop %.1f N)" % (g, d_tip * 1e3, R))
        print("    %s, F %.0f N vertical at the tip: no foot %.3f mm; with the feet %s" % (lab, F, d_free * 1e3, "; ".join(out)))
print("  the vertical tip deflection is set by the plate, not by the gap; the gap sets the lateral sway and the foot length below")
print("  the prop force is about 2 x the tip force (lever); an upward tip pull puts the same force in tension on the foot screws and bonds,")
print("  independent of H_u. Excluded: pin axial compliance, socket-contact compliance (option K), bond and MB compliance (rotation of")
print("  the board about the pin field would add to the no-foot figure; TODO(measure: T-K-18 / dry fit)).")

I_PIN = A_SIDE ** 4 / 12
print("  lateral sway (force in the board plane, e.g. a cable pulled sideways): 22 pins as fixed-guided columns, k = 22 x 12 E I / H^3,")
print("  pin E %.0f GPa, I %.4f mm^4; option S (both ends soldered). Option K adds the socket-contact compliance TODO(verify: socket data)" % (E_PIN / 1e9, I_PIN * 1e12))
SY_PIN = 500e6    # Pa, phosphor bronze spring temper yield, general value TODO(verify: Samtec alloy temper)
for g in (H_U_R1,) + GAPS_MM:
    H = g * 1e-3
    k_pins = 22 * 12 * E_PIN * I_PIN / H ** 3
    k_feet = 2 * 3 * E_NYL * I_hex / H ** 3                  # bonded base, screw head end treated as free (lower bound)
    for F in (5.0, 10.0):
        d = F / (k_pins + k_feet)
        f_pin = F * k_pins / (k_pins + k_feet) / 22
        sig = f_pin * H / 2 * (A_SIDE / 2) / I_PIN
        print("    H_u %5.2f mm, F %2.0f N: sway %.4f mm (pins %.0f N/mm, feet %.1f N/mm); pin bending stress %.0f MPa (yield ~%.0f MPa)"
              % (g, F, d * 1e3, k_pins / 1e3, k_feet / 1e3, sig / 1e6, SY_PIN / 1e6))
print("  the foot spacer as a bonded cantilever under a lateral force at its top (F per foot, bond torque = F x H):")
for g in GAPS_MM:
    for F in (5.0, 10.0):
        print("    H_u %.0f mm, %.1f N per foot: bond moment %.1f N mm (r1 at 2.54 mm: %.1f N mm)" % (g, F / 2, F / 2 * g, F / 2 * H_U_R1))

print("  option K without the foot screws: socket pull-out under a vertical tip force (rigid board pivoting on the pin nearest the tip,")
print("  contact axial forces linear in the distance from the pivot line, all contacts equal):")
pins = [pin_xy(n) for n in (3, 4, 7, 8, 10, 11, 13, 14, 15, 18, 19)] + [pin_xy(n) for n in (1, 2, 5, 6, 9, 12, 16, 17, 20, 21, 22)]
y_piv = max(p[1] for p in pins)
ds = [y_piv - p[1] for p in pins]
s2 = sum(d * d for d in ds)
for F in (5.0, 10.0):
    M = F * (Y_TIP - y_piv)
    tmax = M * max(ds) / s2
    print("    F %.0f N down at y %.2f: moment %.1f N mm about y %.3f; largest contact tension %.2f N; sum of tensions %.2f N"
          % (F, Y_TIP, M, y_piv, tmax, sum(M * d / s2 for d in ds)))
print("    compare with the per-contact socket withdrawal force TODO(verify: socket datasheet); the foot screws remove this load path")
