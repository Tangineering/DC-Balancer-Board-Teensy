#!/usr/bin/env python3
"""Round 4 (r7): extended CHG carrier (CR) - area booking, layer count and stack-up (stdlib only).

Purpose. The operator allows the CR to extend sideways past the 31 x 33 mm Ag105 footprint while it stays plugged into
the 22 Ag105 holes. This script re-books the courtyard area of every CR part and every EIB part, tests single-sided
placement for extension areas of +250 / +400 / +600 / +900 mm2, and computes the electrical quantities that decide
2-layer versus 4-layer: loop inductance of the eFuse commutation loops, inductive coupling to the comparator block,
IPC-2221 copper widths, thermal-pad via resistance and stack-up thickness.

Run:   /c/Users/ricky/miniforge3/python.exe -I stackup_area.py > stackup_area_out.txt

Sources (every constant below names one):
  DOC   docs/charger_bq25798_wiring_design_2026-11-05.md r6: A.2/A.8 hole table, A.7 outline, A.8 courtyards
        ("IPC-7351 nominal land patterns + 0.25 mm": 0402 1.9 x 1.0, 0603 3.0 x 1.45, 0805 3.4 x 1.8, 1206 4.75 x 2.3,
        1210 4.75 x 3.2, SMA 6.6 x 3.1), B.6/B.8 netlists, E BOM packages, H.5/H.11/H.14/H.21(k)/H.22(c)(k).
  R3    round3/calc/r3_calc.py: H.18 per-package bookings for packages without an A.8 courtyard (VQFN-24 incl. via
        allowance 36, SOT-23-6 ~10, SSOP-8 DCT ~15, SC70-5/6 ~7, SOT-23 ~10, J101 3.9 x 9.4, tap field 21 x 8,
        W holes (pad + 1.0 mm)^2, W6/W7 pads 5 x 4, EIB E-pads 8 x 6, M3 keep-out dia 7 mm); H.21(k) loop-inductance
        method L = mu0 h l / w; H.22(c) IPC-2221 external I = 0.048 dT^0.44 A^0.725 (A in mil^2).
  IPC   IPC-2221 conductor-sizing curve fit as coded in r3_calc.py H.22(c); internal layers use k = 0.024 (half of the
        external k; IPC-2221 internal-conductor curve fit, recalled, not in the library). IPC-2152 stays TODO(verify).
  HJ    Microstrip loop inductance per unit length from the Hammerstad closed form (Pozar, Microwave Engineering,
        microstrip design equations; recalled, not in the library): L' = mu0 / [w/h + 1.393 + 0.667 ln(w/h + 1.444)]
        for w/h >= 1, L' = (mu0 / 2 pi) ln(8h/w + w/4h) for w/h < 1 (the eps_eff terms cancel in L' = Z0 sqrt(eps)/c).
  IMG   Mutual inductance per unit length between two thin parallel conductors at height h over an ideal plane, lateral
        spacing d, from image theory (derived here): M' = (mu0 / 4 pi) ln(1 + (2h/d)^2).
  VIA   Through-via inductance L = 0.2 h [ln(4h/d) + 1] nH (h, d in mm), the SI conversion of the Johnson & Graham
        High-Speed Digital Design expression 5.08 h [ln(4h/d) + 1] nH with h, d in inches (recalled, not in the library).
Numbers that no source gives are marked ASSUMPTION or TODO and are swept, not fixed. The routing overhead (section 2)
is a wiring-demand estimate: signal connections = pins - GND pins - unconnected pins - nets, split into local / medium /
long classes with assumed lengths, 0.4 mm track pitch, 0.64 mm2 per via, packing efficiency 0.90; the utilisation
budget is U = 0.90 / (1 + L1 overhead / courtyard sum), and the track demand is swept x0.5 .. x1.5.
Output: stackup_area_out.txt beside this file. Consumer: round4/work/stackup_area.md.
Coordinates: Eagle .brd board coordinates, top view, origin = MB origin, +x right, +y UP, mm.
"""
import math

MU0 = 4e-7 * math.pi
print("=" * 110)
print("Round 4 stack-up / area study for the extended CR (stackup_area.py)")
print("=" * 110)

# ------------------------------------------------------------------------------------------------ 1. package courtyards
# A.8 (DOC): IPC-7351 nominal + 0.25 mm. R3: H.18 bookings for the rest (TODO(verify: IPC-7351B land-pattern
# calculator / TI package drawings DCT, DCK, DBV, RGE) - the package datasheets are not in the library).
CY = {
    "0402": 1.9 * 1.0, "0603": 3.0 * 1.45, "0805": 3.4 * 1.8, "1206": 4.75 * 2.3, "1210": 4.75 * 3.2,
    "SMA": 6.6 * 3.1,
    "VQFN-24": 36.0,          # R3 H.18 (A.8/H.21(k) courtyard 5.0 x 5.0 = 25 mm2 + via/fan-out allowance)
    "SOT-23-6": 10.0, "SSOP-8": 15.0, "SC70-6": 7.0, "SC70-5": 7.0, "SOT-23": 10.0,
    "SOD-323": 3.4 * 1.8,     # ASSUMPTION: booked as an 0805 courtyard (no SOD-323 land pattern in the library)
    "J2x7-1.27": 3.9 * 9.4,   # R3 H.18 r5 J101 booking (mated socket larger: A.7, T-A-05)
}

# CR parts from B.8 (pin -> net table) and E (packages). dnp=True: footprint kept, part not fitted.
CR = []
def add(refs, pkg, dnp=False, side_r3="bottom"):
    for r in refs.split():
        CR.append((r, pkg, dnp, side_r3))

add("U101", "VQFN-24", side_r3="top")
add("U102 U103 U104 U115 U119 U120 U121", "SOT-23-6", side_r3="top")
add("U117", "SOT-23-6", dnp=True, side_r3="top")
add("U112", "SOT-23-6", dnp=True, side_r3="top")                      # TPS22810 DBV keep-alive option
add("U105 U106 U110 U111 U113 U114 U116 U118", "SSOP-8", side_r3="top")
add("U107 U108 U109", "SC70-6", side_r3="top")
add("U122 U123", "SC70-5", side_r3="top")
add("D104 D105 D106 D108", "SOT-23", side_r3="top")                   # BAV199
add("D101", "SOD-323", dnp=True, side_r3="top")
add("D103 D107", "SMA", side_r3="top")
add("C102b", "1210", side_r3="top")
add("C102a", "1206", side_r3="top")
add("R175", "1206")
add("R_KA", "1206", dnp=True)
add("R102 R109 R111 R114 C103 C125 C150", "0805")
for r in ("R102", "C103"):                                             # A.8 high-y band: top side
    CR[[c[0] for c in CR].index(r)] = (r, "0805", False, "top")
add("R101 C101 R103 R104 R105", "0402", side_r3="top")                # A.8 +x pocket, top only
add("C105", "0402", dnp=True, side_r3="top")
res0603 = ("R107 R108 R110 R112 R113 R115 R116 R117 R118 R119 R120 R121 R122 R123 R124 R125 R126 R127 R128 R129 R130 "
           "R131A R131B R132 R133 R135 R136 R137 R140 R141 R142 R143 R144 R147 R148 R150 R151 R176 R177 R178 R179 "
           "R184 R185 R186 R187 R188 R189 R190 R191")
add(res0603, "0603")
add("R106 R134 R145 R146 R160 R161 R162 R163", "0603", dnp=True)
cap0603 = ("C102c C129 C106 C107 C108 C109 C140 C130 C151 C110 C111 C112 C113 C114 C115 C116 C117 C118 C119 C120 "
           "C121 C122 C123 C126 C131 C132 C133 C134 C135")
add(cap0603, "0603")
CR[[c[0] for c in CR].index("C102c")] = ("C102c", "0603", False, "top")
add("C152 C124 C127", "0603", dnp=True)

# Non-part area items (R3 bookings; W holes from the A.8 pad sizes + 1.0 mm).
CR_FIXED = {
    "J101 2x7 1.27 mm SMT (R3 r5 3.9 x 9.4)": CY["J2x7-1.27"],
    "tap field F01-F24, 3 x 8 SMT pads at 2.54 mm (R3 21 x 8)": 21.0 * 8.0,
    "W1/W2 holes, 2.3 mm pad + 1.0 mm (A.8)": 2 * (2.3 + 1.0) ** 2,
    "W3/W4 holes, 2.5 mm pad + 1.0 mm (A.8)": 2 * (2.5 + 1.0) ** 2,
    "W6/W7 SMT pads 5 x 1.2 x 1.5 mm + clearance (R3 5 x 4)": 5 * 4.0,
}
# Power pours on L1 outside every courtyard (ASSUMPTION, lengths from the A.3/A.8 coordinates, widths A.8 >= 2.5 mm):
POUR = {
    "W2 (27.7, 61.2) -> pads 14/15 GND, ~8.7 mm x 2.5 mm (A.6)": 8.7 * 2.5,
    "W4 -> pins 14/15 and W3 -> pins 18/19, 2 x 2.4 mm x 3.0 mm": 2 * 2.4 * 3.0,
    "VCHGOUT OUT 17/18 -> C103/D103 -> W1, ~6 mm x 2.5 mm outside the courtyards": 6.0 * 2.5,
    "VCHGIN pad 10 -> U101 IN_SYS, ~3.5 mm x 2.5 mm": 3.5 * 2.5,
}

def book(parts, fitted_only=False):
    tot, by = 0.0, {}
    for r, pkg, dnp, _ in parts:
        if fitted_only and dnp:
            continue
        a = CY[pkg]
        tot += a
        k = pkg + (" (DNP)" if dnp else "")
        by.setdefault(k, [0, 0.0])
        by[k][0] += 1
        by[k][1] += a
    return tot, by

cr_parts_all, cr_by = book(CR)
cr_parts_fit, _ = book(CR, fitted_only=True)
cr_fixed = sum(CR_FIXED.values())
cr_pour = sum(POUR.values())
CR_TOTAL = cr_parts_all + cr_fixed
CR_TOTAL_POUR = CR_TOTAL + cr_pour
print("\n1. CR courtyard booking (B.8 / E packages; A.8 courtyards; R3 bookings for the rest)")
for k in sorted(cr_by):
    print("   %-18s x %3d  %7.1f mm2" % (k, cr_by[k][0], cr_by[k][1]))
for k, v in CR_FIXED.items():
    print("   %-72s %7.1f mm2" % (k, v))
n_pas = sum(1 for c in CR if c[1] in ("0402", "0603", "0805", "1206", "1210"))
n_pas_dnp = sum(1 for c in CR if c[1] in ("0402", "0603", "0805", "1206", "1210") and c[2])
print("   two-terminal passives: %d footprints (%d DNP); ICs/diodes: %d footprints" % (n_pas, n_pas_dnp, len(CR) - n_pas))
print("   CR parts %.0f mm2 (fitted only %.0f) + fixed items %.0f mm2 = CR courtyard total %.0f mm2 (r6 H.22(k): ~1082)"
      % (cr_parts_all, cr_parts_fit, cr_fixed, CR_TOTAL))
for k, v in POUR.items():
    print("   pour (ASSUMPTION) %-80s %5.1f mm2" % (k, v))
print("   + L1 power pours outside courtyards %.0f mm2 -> CR demand incl. pours %.0f mm2" % (cr_pour, CR_TOTAL_POUR))
# round-3 side split, for comparison with H.22(k)
top_r3 = sum(CY[p] for r, p, d, s in CR if s == "top") + cr_fixed
bot_r3 = sum(CY[p] for r, p, d, s in CR if s == "bottom")
print("   round-3 side split with this booking: top %.0f mm2, bottom %.0f mm2 (r6 H.22(k): top ~678, bottom ~404)" % (top_r3, bot_r3))

# EIB parts from B.6/B.8 (EIB table) and E.
EIB = []
for r in ("U201",):
    EIB.append((r, "SSOP-8"))
EIB.append(("U202", "SC70-5"))
EIB += [("U203", "SOT-23-6"), ("U204", "SOT-23-6")]
EIB += [(q, "SOT-23") for q in ("Q201", "Q202", "Q203")]
eib_r = "R250 R251 R252 R253 R254 R255 R257 R258 R259 R260 R261 R262 R263 R264 R265 R266 R267 R268 R269 R270 R271 R273 R274 R275".split()
eib_c = "C201 C202 C203 C204 C205".split()
EIB += [(r, "0603") for r in eib_r + eib_c]
eib_parts = sum(CY[p] for _, p in EIB)
EIB_FIXED = {"J201 2x7 1.27 mm (r4; booked as J101, 3.9 x 9.4)": CY["J2x7-1.27"],
             "8 E-lead pads, 1.0 mm hole (R3 8 x 6)": 8 * 6.0,
             "2 x M3 hole keep-out, dia 7 mm (A.9)": 2 * math.pi * 3.5 ** 2}
EIB_TOTAL = eib_parts + sum(EIB_FIXED.values())
print("\n   EIB: %d resistors + %d capacitors 0603, U201 SSOP-8, U202 SC70-5, U203/U204 SOT-23-6, Q201-Q203 SOT-23: parts %.0f mm2"
      % (len(eib_r), len(eib_c), eib_parts))
for k, v in EIB_FIXED.items():
    print("   %-60s %6.1f mm2" % (k, v))
print("   EIB courtyard total %.0f mm2 = %.0f %% of 36 x 24 mm (r3 H.18b: 559 mm2 with the 2.54 mm J201 25.4 x 9.0)"
      % (EIB_TOTAL, 100 * EIB_TOTAL / (36 * 24)))
# merged CR + EIB: J101, J201, the W5 ribbon and the two EIB M3 holes disappear; the E-pad row stays
MERGED = CR_TOTAL - CY["J2x7-1.27"] + eib_parts + EIB_FIXED["8 E-lead pads, 1.0 mm hole (R3 8 x 6)"]
MERGED_POUR = MERGED + cr_pour
print("   merged CR + EIB (no J101/J201, no EIB M3 holes, E-pad row kept): %.0f mm2 (%.0f incl. pours)" % (MERGED, MERGED_POUR))
print("   NOTE: merging moves the E1-E8 leads to the CR, 0.30 m from the EVM; the A.5 build maxima are E8 20, E3 25, E4 30,")
print("         E2 35, E7 40, E5/E6 60, E1 85 mm, so a merged board violates every length-critical lead unless the EVM's")
print("         TP49/TP33/JP21 sit within ~20 mm of the merged board's E-pad row (A.5, A.9).")

# ------------------------------------------------------------------------------------------------ 2. usable top area
# Footprint: CR outline x 17.70-48.70, y 34.14-67.14; courtyard limit 0.5 mm in (A.7, H.21(k) CR_CY).
CYX0, CYX1, CYY0, CYY1 = 18.2, 48.2, 34.64, 66.64
cy_area = (CYX1 - CYX0) * (CYY1 - CYY0)
PAD_R, CLR = 0.95, 0.5                    # 1.9 mm header pads (A.8), >= 0.5 mm courtyard to pad (A.8 / H.21(k))
P = 2.54
ycol_L = (36.544, 64.484)                 # pins 22 .. 11 at x 20.998
ycol_R = (39.084, 61.944)                 # pins 1 .. 10 at x 45.998
kL = (20.998 - PAD_R - CLR, 20.998 + PAD_R + CLR, ycol_L[0] - PAD_R - CLR, ycol_L[1] + PAD_R + CLR)
kR = (45.998 - PAD_R - CLR, 45.998 + PAD_R + CLR, ycol_R[0] - PAD_R - CLR, ycol_R[1] + PAD_R + CLR)
a_kL = (kL[1] - kL[0]) * (min(kL[3], CYY1) - max(kL[2], CYY0))
a_kR = (kR[1] - kR[0]) * (kR[3] - kR[2])
a_out_R = (CYX1 - kR[1]) * (kR[3] - kR[2])         # 0.75 mm strip outboard of the 1x10 column: no courtyard fits
a_out_L = (kL[0] - CYX0) * (CYY1 - CYY0)           # 1.35 mm strip outboard of the 1x12 column: 0402-vertical only
a_chamfer = 1.5 * 1.5 / 2                          # nothing within 1.5 mm of the pin-11 chamfer corner (A.7)
USE_STRICT = cy_area - a_kL - a_kR - a_out_R - a_out_L - a_chamfer
USE_MID = USE_STRICT + a_out_L
USE_R3 = 23.1 * 31.0 + 2 * 2.5 * 33.0
print("\n2. Usable top area of the 31 x 33 mm footprint")
print("   courtyard limit %.1f mm2; minus 1x12 column keep-out %.1f, 1x10 column keep-out %.1f, outboard strips %.1f (R) + %.1f (L), chamfer %.1f"
      % (cy_area, a_kL, a_kR, a_out_R, a_out_L, a_chamfer))
print("   usable: strict %.0f mm2 (left outboard strip excluded), %.0f mm2 (left strip counted); round-3 H.18 basis %.0f mm2" % (USE_STRICT, USE_MID, USE_R3))
print("   round-3 r6 top side under the strict basis: %.0f / %.0f = %.0f %% (H.22(k) quoted %.0f / %.0f = %.0f %%)"
      % (top_r3, USE_STRICT, 100 * top_r3 / USE_STRICT, 678, 881, 100 * 678 / 881))

# Extension: A mm2 of outline added sideways. Courtyard margin moves with the edge; the strip's two ends lose 0.5 mm each
# (width w = A / 32 mm, the mean side length). One far-end support keep-out (ASSUMPTION: M3 nylon standoff, 7 mm dia
# copper-free keep-out as A.9; TODO(verify: support design) - a bonded foot without a hole would not cost this area).
SUPPORT = math.pi * 3.5 ** 2
def usable(A, base=USE_STRICT, support=True):
    if A <= 0:
        return base
    w = A / 32.0
    return base + A - 2 * 0.5 * w - (SUPPORT if support else 0.0)

# Routing overhead from a wiring-demand estimate (ASSUMPTION, every input swept +-50 % below).
# Pin count from the booking (2 per passive; package pin counts SOT-23-6 6, SSOP-8 8, SC70-6 6, SC70-5 5, SOT-23 3,
# SMA/SOD-323 2, U101 15 connected incl. PAD per B.8, J101 13, taps 24, W pads 9, header pins with a net 11 per A.2).
PINS = {"0402": 2, "0603": 2, "0805": 2, "1206": 2, "1210": 2, "SMA": 2, "SOD-323": 2, "SOT-23": 3, "SOT-23-6": 6,
        "SSOP-8": 8, "SC70-6": 6, "SC70-5": 5, "VQFN-24": 15}
n_pins = sum(PINS[p] for _, p, _, _ in CR) + 13 + 24 + 9 + 11
N_GND, N_NC, N_NETS = 75, 12, 110   # hand count from B.8 (+-15 %): GND pins/pads, unconnected IC pins, signal nets
n_conn = n_pins - N_GND - N_NC - N_NETS          # signal connections (spanning-tree count)
CLS = {"local (passive or decoupler to the adjacent IC pin; length outside courtyards)": (150, 1.0),
       "medium (logic mesh, comparator outputs, series R to taps)": (70, 10.0),
       "long (tap field to consumers, J101 drivers, pins 7/8/13 to W6/W7, 3V3 tree)": (30, 20.0)}
PITCH = 0.4          # mm, 0.2 mm track + 0.2 mm space (TODO(verify: fab rule; 2 oz outer usually needs >= 0.2 mm space))
A_VIA = 0.8 ** 2     # mm2, 0.6 mm via land + 0.2 mm clearance
ETA = 0.90           # packing efficiency of the usable area (fragmentation by odd shapes; ASSUMPTION)
XU = 0.10            # 2-layer: share of the medium/long track length allowed as L2 cross-unders (keeps L2 ~90 % intact)
def overheads(k=1.0):
    loc = CLS[list(CLS)[0]][0] * CLS[list(CLS)[0]][1] * PITCH * k
    ml = sum(n * l for n, l in list(CLS.values())[1:]) * PITCH * k
    n_ml = sum(n for n, _ in list(CLS.values())[1:])
    o4 = loc + (N_GND + 2 * n_ml) * A_VIA                    # L1: local tracks + GND vias + two L3 vias per medium/long run
    o2 = loc + ml * (1 - XU) + N_GND * A_VIA                  # L1: all tracks except the cross-unders + GND vias
    return o4, o2, loc + ml
def budget(o, c):
    return ETA / (1 + o / c)
o4, o2, r_tot = overheads()
U4, U2 = budget(o4, CR_TOTAL_POUR), budget(o2, CR_TOTAL_POUR)
U4_lo, U2_lo = budget(overheads(1.5)[0], CR_TOTAL_POUR), budget(overheads(1.5)[1], CR_TOTAL_POUR)
U4_hi, U2_hi = budget(overheads(0.5)[0], CR_TOTAL_POUR), budget(overheads(0.5)[1], CR_TOTAL_POUR)
print("\n   routing overhead (ASSUMPTION): %d pins - %d GND - %d NC - %d nets = %d signal connections (classes: %s)"
      % (n_pins, N_GND, N_NC, N_NETS, n_conn, ", ".join("%d x %.0f mm" % v for v in CLS.values())))
print("   track area at %.1f mm pitch %.0f mm2; L1 overhead 4-layer (local tracks + %d vias) %.0f mm2, 2-layer (all but %.0f %% cross-unders + GND vias) %.0f mm2"
      % (PITCH, r_tot, N_GND + 2 * 100, o4, 100 * XU, o2))
print("   utilisation budget U = eta / (1 + overhead / courtyards), eta %.2f: 4-layer single-sided U4 = %.2f (%.2f-%.2f for track demand x1.5..x0.5),"
      " 2-layer single-sided U2 = %.2f (%.2f-%.2f); r3 EIB budget 0.70 (A.9)" % (ETA, U4, U4_lo, U4_hi, U2, U2_lo, U2_hi))

def a_needed(demand, U, base=USE_STRICT):
    # smallest A with demand / usable(A) <= U (usable linear in A above 0)
    need = demand / U
    if need <= base:
        return 0.0
    return (need - base + SUPPORT) / (1 - 1 / 32.0)

DNP_AREA = sum(CY[p] for _, p, d, _ in CR if d)
print("\n3. Single-sided placement vs extension area (strict usable basis; one far-end support keep-out %.1f mm2)" % SUPPORT)
print("   demand: CR %.0f mm2 incl. pours (%.0f without the %.0f mm2 of DNP option footprints U112/U117/D101/R_KA/...); merged CR + EIB %.0f mm2"
      % (CR_TOTAL_POUR, CR_TOTAL_POUR - DNP_AREA, DNP_AREA, MERGED_POUR))
print("   %-7s %-7s | %-36s | %-22s | %s" % ("ext", "usable", "CR single-sided U (no-DNP U)", "merged single-sided U", "CR double-sided (bottom = r3 set)"))
TABLE = []
BOT_R3 = bot_r3                       # passives round 3 put on the bottom (this booking): stays on the footprint bottom
BOT_FREE_R3 = 591.0                   # H.18 bottom free outside keep-out and power shadow (r3 basis, not re-derived here)
for A in (0, 250, 400, 600, 900):
    us = usable(A)
    u_cr, u_nd, u_m = CR_TOTAL_POUR / us, (CR_TOTAL_POUR - DNP_AREA) / us, MERGED_POUR / us
    u_top_ds = (CR_TOTAL_POUR - BOT_R3) / us
    v = lambda u: "4L" if u <= U4 else ("4L marg." if u <= 0.80 else "no")
    v2 = lambda u: "2L" if u <= U2 else "-"
    bot_need = max(0.0, CR_TOTAL_POUR - U4 * us)
    print("   %-7d %-7.0f | %4.0f %% (%4.0f %%) %-9s %-3s | %4.0f %% %-9s %-3s | top %4.0f %% with the r3 bottom set %.0f mm2; bottom still needed at U4: %.0f mm2"
          % (A, us, 100 * u_cr, 100 * u_nd, v(u_cr), v2(u_cr), 100 * u_m, v(u_m), v2(u_m), 100 * u_top_ds, BOT_R3, bot_need))
    TABLE.append((A, us, u_cr, u_nd, u_m, u_top_ds))
print("   ('4L' = within U4 %.2f; '4L marg.' = within 0.80, the top of the swept range; '2L' = within U2 %.2f)" % (U4, U2))
print("   break-even extension (strict basis):")
for lab, dem in (("CR", CR_TOTAL_POUR), ("CR without DNP footprints", CR_TOTAL_POUR - DNP_AREA), ("CR + EIB merged", MERGED_POUR)):
    print("     %-26s single-sided 4L: +%4.0f mm2 (U4 %.2f; +%4.0f at 0.80, +%4.0f at 0.70) | single-sided 2L: +%4.0f mm2 (U2 %.2f; +%4.0f at %.2f, +%4.0f at %.2f)"
          % (lab, a_needed(dem, U4), U4, a_needed(dem, 0.80), a_needed(dem, 0.70), a_needed(dem, U2), U2, a_needed(dem, U2_hi), U2_hi, a_needed(dem, U2_lo), U2_lo))
print("   double-sided 4L, top side at U4 %.2f with the round-3 bottom set kept: +%.0f mm2" % (U4, a_needed(CR_TOTAL_POUR - BOT_R3, U4)))
print("   sensitivity: left outboard strip counted (base %.0f mm2): single-sided 4L +%.0f, 2L +%.0f mm2 (CR incl. pours)"
      % (USE_MID, a_needed(CR_TOTAL_POUR, U4, USE_MID), a_needed(CR_TOTAL_POUR, U2, USE_MID)))

# ------------------------------------------------------------------------------------------------ 4. stack-ups
# Nominal 1.6 mm boards. Dielectrics: H.21(k) basis (0.2 mm L1-L2 and L3-L4 prepreg, 1.1 mm core); TODO(verify: the
# chosen fab's standard 1.6 mm stack-up table). Copper: 1 oz = 35 um, 2 oz = 70 um.
OZ = 0.035
def stack(layers):
    return sum(t for _, t in layers)
S4_1 = [("L1 1 oz", OZ), ("prepreg", 0.20), ("L2 1 oz", OZ), ("core", 1.10), ("L3 1 oz", OZ), ("prepreg", 0.20), ("L4 1 oz", OZ)]
S4_2 = [("L1 2 oz", 2 * OZ), ("prepreg", 0.20), ("L2 1 oz", OZ), ("core", 1.10), ("L3 1 oz", OZ), ("prepreg", 0.20), ("L4 2 oz", 2 * OZ)]
print("\n4. Stack-up thickness: 4-layer 1/1/1/1 oz %.3f mm, 2/1/1/2 oz %.3f mm (core trimmed by the fab to the 1.6 mm target)"
      % (stack(S4_1), stack(S4_2)))
H2 = {"2-layer 1.6 mm, 1 oz": 1.60 - 2 * OZ, "2-layer 1.6 mm, 2 oz": 1.60 - 4 * OZ}
for k, v in H2.items():
    print("   %s: L1-L2 dielectric %.2f mm (finished 1.6 mm including copper; TODO(verify: fab laminate))" % (k, v))

# ------------------------------------------------------------------------------------------------ 5. loop inductance
def l_pp(h, w):            # nH/mm, H.21(k) parallel-plate method
    return MU0 * h / w * 1e6
def l_hj(h, w):            # nH/mm, Hammerstad microstrip
    r = w / h
    if r >= 1:
        return MU0 / (r + 1.393 + 0.667 * math.log(r + 1.444)) * 1e6
    return MU0 / (2 * math.pi) * math.log(8 / r + r / 4) * 1e6
def l_via(h, d=0.3):       # nH, one via
    return 0.2 * h * (math.log(4 * h / d) + 1)
print("\n5. Loop inductance (per mm of 2.5 / 4.0 mm pour over its return plane)")
for lab, h in (("4L L1/L2 or L3/L4, h 0.20 mm", 0.20), ("4L L3/L2 across the core, h 1.10 mm", 1.10),
               ("2L, h 1.53 mm (1 oz)", 1.53), ("2L, h 1.46 mm (2 oz)", 1.46)):
    print("   %-38s pp %.3f / %.3f nH/mm   microstrip %.3f / %.3f nH/mm" % (lab, l_pp(h, 2.5), l_pp(h, 4.0), l_hj(h, 2.5), l_hj(h, 4.0)))
cases = (("C102b link 8 mm x 2.5 mm (r5 rule)", 8.0, 2.5), ("D103 cathode run 4 mm x 2.5 mm (r5)", 4.0, 2.5))
for lab, l, w in cases:
    print("   %-38s 4L(0.2) pp %.2f / ms %.2f nH | 2L(1.46) pp %.2f / ms %.2f nH | 2L(1.53) pp %.2f / ms %.2f nH"
          % (lab, l_pp(0.2, w) * l, l_hj(0.2, w) * l, l_pp(1.46, w) * l, l_hj(1.46, w) * l, l_pp(1.53, w) * l, l_hj(1.53, w) * l))
for w in (2.5, 4.0):
    print("   2-layer (h 1.46-1.53) longest run for <= 2 nH added at w %.1f mm: pp %.1f-%.1f mm, microstrip %.1f-%.1f mm (4L 0.2 mm: pp %.0f mm)"
          % (w, 2.0 / l_pp(1.53, w), 2.0 / l_pp(1.46, w), 2.0 / l_hj(1.53, w), 2.0 / l_hj(1.46, w), 2.0 / l_pp(0.2, w)))
print("   vias (0.3 mm): through 1.6 mm %.2f nH each; 4L L1->L2 (0.2 mm) %.3f nH; 4L L1->L3 (~1.37 mm) %.2f nH;"
      " 6 in parallel (no mutual) 1.6 mm %.2f nH" % (l_via(1.6), l_via(0.2), l_via(1.37), l_via(1.6) / 6))
# commutation loop C102 -> U101 IN -> FET -> OUT -> D103 -> GND -> C102 at a fast-trip turn-off (H.5): extra
# overshoot across the FET = L_loop x I_off / t_off. I_off 45 A (I_SCP) .. 65 A (H.5 r3 worst input current at turn-off).
# t_off: TODO(verify: SLVSE94G fast-trip gate pull-down / turn-off time; T-C-04 measures) - swept.
loops = {"4L r5 placement (C102b 0.8 + D103 0.4 + vias ~0.2)": 0.8 + 0.4 + 0.2,
         "2L at the r5 lengths, pp (5.9 + 2.9 + vias 0.4)": l_pp(1.46, 2.5) * 8 + l_pp(1.46, 2.5) * 4 + 0.4,
         "2L pin-adjacent, each loop at its 2 nH budget": 2.0 + 2.0}
print("   commutation-loop extra overshoot dV = L x I_off / t_off (IN up + OUT down; IN margin 67 - 33 = 34 V, OUT already -0.5..-1 V vs -0.3 V abs min, H.5):")
for lab, L in loops.items():
    s = ", ".join("%.0f A/%.0f ns %.1f V" % (i, t * 1e9, L * 1e-9 * i / t) for i in (45, 65) for t in (50e-9, 100e-9, 200e-9))
    print("     %-52s L %.1f nH: %s" % (lab, L, s))
d103_share = {"4L D103 0.4 + via 0.08 nH": 0.48, "2L D103 at 4 mm pp 2.9 + vias 0.4 nH": l_pp(1.46, 2.5) * 4 + 0.4,
              "2L D103 at 2 nH budget": 2.0}
print("   OUT-side share (D103 loop only) at 45 A:")
for lab, L in d103_share.items():
    print("     %-40s %.2f nH: %s" % (lab, L, ", ".join("%.0f ns %.2f V" % (t * 1e9, L * 1e-9 * 45 / t) for t in (50e-9, 100e-9, 200e-9))))

# ------------------------------------------------------------------------------------------------ 6. coupling
def m_img(h, d):           # H/m
    return MU0 / (4 * math.pi) * math.log(1 + (2 * h / d) ** 2)
DIDT = 65.0 / 100e-9       # A/s, 65 A in 100 ns (t_off TODO(verify)); scales linearly
LV = 10e-3                 # m, victim run parallel to the aggressor (ASSUMPTION)
print("\n6. Inductive coupling, aggressor = commutation-loop conductor, victim = 10 mm comparator-input run, di/dt 65 A / 100 ns")
print("   %-6s | %-24s | %-24s | %s" % ("d mm", "4L h 0.20: M' / EMF", "2L h 1.46: M' / EMF", "ratio 2L/4L"))
for d in (2, 5, 10, 20, 30, 40):
    m4, m2 = m_img(0.20e-3, d * 1e-3), m_img(1.46e-3, d * 1e-3)
    print("   %-6d | %6.4f nH/mm %7.1f mV | %6.4f nH/mm %7.1f mV | %5.1f"
          % (d, m4 * 1e6, m4 * LV * DIDT * 1e3, m2 * 1e6, m2 * LV * DIDT * 1e3, m2 / m4))
d_eq = 5.0 * 1.46 / 0.20
print("   2-layer distance that matches the 4-layer coupling at 5 mm: d x h2/h4 = %.1f mm (far field, M' ~ mu0 h^2 / (pi d^2))" % d_eq)
for tau, lab in ((23.5e-6, "H1 inputs (C106/C107 470 pF, ~50 kOhm)"), (94e-6, "UVB IN+ (C108 1 nF, ~94 kOhm)"), (100e-6, "BT_OK IN- (C140 10 nF, R140 10 kOhm)")):
    e2 = m_img(1.46e-3, 5e-3) * LV * DIDT
    print("   filtered input %-38s: 2L at 5 mm EMF %.0f mV x t_off / tau = %.2f mV at the pin" % (lab, e2 * 1e3, e2 * 100e-9 / tau * 1e3))
print("   unfiltered high-impedance inputs (B.8: U115 IN- N_BBM, U119 IN- N_FOM, U120 IN+ N_FNP, U121 IN+ N_RNP) see the EMF for t_off;"
      " smallest static margins 0.16 V (BTB_OFF, H.3) and ~0.24 V at the U120/U121 node ((1.745 - 1.4) V x 1.00/1.453)")

# ------------------------------------------------------------------------------------------------ 7. copper
def ipc_i(w_mm, oz, dT, k=0.048):
    a = (w_mm / 0.0254) * (oz * 1.378)
    return k * dT ** 0.44 * a ** 0.725
def ipc_w(i, oz, dT, k=0.048):
    a = (i / (k * dT ** 0.44)) ** (1 / 0.725)
    return a / (oz * 1.378) * 0.0254
print("\n7. IPC-2221 external widths (both layers of a 2-layer board, L1/L4 of a 4-layer board)")
for i, lab in ((2.41, "input side, eFuse I_OL (A.8)"), (3.21, "battery side, ICHG max (A.3)"), (3.5, "battery-side design target (A.8)")):
    print("   %.2f A %-34s: 1 oz %.2f mm (10 C) / %.2f mm (20 C); 2 oz %.2f / %.2f mm; internal 1 oz %.2f mm (10 C)"
          % (i, lab, ipc_w(i, 1, 10), ipc_w(i, 1, 20), ipc_w(i, 2, 10), ipc_w(i, 2, 20), ipc_w(i, 1, 10, 0.024)))
for w in (2.0, 2.5, 3.0, 4.0):
    print("   %.1f mm external: 1 oz %.1f A / 2 oz %.1f A at 10 C rise" % (w, ipc_i(w, 1, 10), ipc_i(w, 2, 10)))
RHO = 1.72e-8
def r_mohm_per_mm(w, oz):
    return RHO * 1e-3 / (w * 1e-3 * oz * 35e-6) * 1e3
for w, oz in ((3.0, 1), (2.5, 2), (2.5, 1)):
    r = r_mohm_per_mm(w, oz)
    print("   %.1f mm %d oz: %.3f mOhm/mm; 20 mm relocation of W3/W4 into an extension: %.1f mOhm, %.0f mW and %.1f mV at 3.21 A (H.11 battery pair 12.6 mOhm)"
          % (w, oz, r, 20 * r, 3.21 ** 2 * 20 * r, 3.21 * 20 * r))
print("   GND plane sheet resistance: 1 oz %.2f mOhm/sq, 2 oz %.2f mOhm/sq" % (RHO / 35e-6 * 1e3, RHO / 70e-6 * 1e3))

# ------------------------------------------------------------------------------------------------ 8. thermal pad vias
K_CU = 385.0
def via_rth(h=1.6e-3, d=0.3e-3, plate=25e-6):
    a = math.pi * ((d / 2 + plate) ** 2 - (d / 2) ** 2)
    return h / (K_CU * a)
r1 = via_rth()
print("\n8. U101 thermal-pad vias (0.3 mm, 25 um plating TODO(verify: fab plating), 1.6 mm): %.0f K/W each, 9 in parallel %.1f K/W;"
      " at the H.14 eFuse dissipation 0.17 W: %.1f K across the via field" % (r1, r1 / 9, 0.17 * r1 / 9))

# ------------------------------------------------------------------------------------------------ 9. extension geometry
# Strip width for an extension along one full side (33 mm side for +-x, 31 mm side for +-y) and the room to the MB
# outline (0-131.064 x 0-98.044, mb_neighbours_out.txt). MB part heights are not in the .brd: TODO(measure), gate D-2.
ROOM = {"-x (J-BL/J-NTC, x 3.28-17.23)": 17.70 - 0.0, "+x (CO-5V 2.1 mm at x 49.30, REG-5V 4.83 mm at x 50.97)": 131.064 - 48.70,
        "+y (OP-FC SOIC at y 67.30, L-FC at y 77.01)": 98.044 - 67.14, "-y (C4A/B-BT at y 32.54, BAL, L-BT at y 20.78)": 34.14 - 0.0}
print("\n9. Extension strip width w = A / side (one full side) vs room to the MB outline")
for A in (250, 400, 600, 900):
    print("   +%d mm2: w %.1f mm on a 33 mm side (+-x), %.1f mm on a 31 mm side (+-y)" % (A, A / 33.0, A / 31.0))
for k, v in ROOM.items():
    print("   room to the MB edge %-62s %.1f mm" % (k, v))
print("=" * 110)
