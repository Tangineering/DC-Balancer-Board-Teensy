#!/usr/bin/env python3
"""Round-3 calculations for docs/charger_bq25798_wiring_design_2026-11-05.md (BQ25798EVM on the Ag105 pads).

Revision r2 (2026-11-06, after review round 2; r1 after review round 1). Every input constant carries its source. Run:  python3 r3_calc.py
(stdlib only). Output is plain text (redirect to r3_calc_out.txt) plus r3_calc_out.json beside this file. Section
numbers match the design document section H (H.1 ... H.19). Designators match the design document (carrier 1xx, EIB 2xx,
EVM parts written "EVM Rnn").
Sources (literature numbers):
  DS   TI SLUSDV2C BQ25798                         UG  TI SLUUCB5E BQ2579xEVM
  RT   Richtek RT1987 DS-00                        TLV TI SBOS300C TLV3011/3012
  EF   TI SLVSE94G TPS2663x eFuse                  LS  TI SLVSDH0C TPS22810 load switch
  MV   TI SCES586E SN74LVC1G123 monostable          INA TI SLOS954A INA253 (repo copy), section 7.5
  BOARD references/Scale_Car_Board_20260624.sch, .brd 20260625, BOM 20260622, fw v37 rev 2 (.ino)
  BAGS docs/reviews/fw36_regen_2026-11-04/README.md section 2 (H-20 purge statistics, 22 Pi bags, 50 Hz)
  REGEN docs/reviews/charger_eval_2026-11-05/round2/regen_dynamics.md
Values marked TEST are not in any primary and are measured by the named test in section I of the design.
"""
import itertools, json, math, os

OUT = {}
def rec(key, val):
    OUT[key] = val
    return val
def par(*rs):
    return 1.0 / sum(1.0 / r for r in rs)

def solve3(A, b):
    """Gaussian elimination, 3x3 (stdlib)."""
    M = [row[:] + [bb] for row, bb in zip(A, b)]
    n = 3
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(i + 1, n):
            f = M[r][i] / M[i][i]
            for c in range(i, n + 1):
                M[r][c] -= f * M[i][c]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (M[i][n] - sum(M[i][c] * x[c] for c in range(i + 1, n))) / M[i][i]
    return x

print("=" * 100)
# ======================================================================= TLV3012B constants (SBOS300C 6.9, 6.10)
VREF = (1.223, 1.242, 1.260)       # REF output at 25 C
REF_TC = 100e-6                    # 1/C max, -40..125 C
DT_CR = (0.0, 45.0)                # carrier self-heating + ambient excursion from 25 C (TEST T-C-03 at 0 C / 60 C)
VOS = 0.009                        # V, max, VCM = V-, -40..125 C
VHYS = (0.002, 0.008)              # V, internal hysteresis
CMRR_DB = 54.0                     # min (VS 5.5 V; 3.3 V unspecified)
VOH, VOL = (3.1, 3.3), (0.0, 0.2)  # VS 5 V, 5 mA (light load here)

# ======================================================================= H.1 / H.2  H1 and UVB share the T2 VBUS tap
# T1: MB C-D6 pad 1 -> R_T1 10.0k (0.1 %, 0805, at the MB joint) -> wire -> CR R109 487k -> IN+ (R110 56.2k to GND, RH R113)
# T2: MB C-D2 pad 1 -> R_T2 10.0k (0.1 %, 0805, at the MB joint) -> wire -> CR node T2C
#     T2C -> R111 442k -> H1 IN- (R112 56.2k to GND)
#     T2C -> R114 1.00M -> UVB IN+ (R115 104k to GND, RUH R116 10.0M to the UVB output); UVB IN- = own REF
RT1, R109, R110, R113 = 10.0e3, 487e3, 56.2e3, 6.49e6
RT2, R111, R112 = 10.0e3, 442e3, 56.2e3
R114, R115, R116 = 1.00e6, 104e3, 10.0e6   # r2: R116 10.0M (CRCW0603 stops at 10 MOhm, Vishay doc 20035)

def t2_nodes(vbus, vuvb_out, rt2=RT2, r111=R111, r112=R112, r114=R114, r115=R115, r116=R116):
    """Return (H1 IN-, UVB IN+) for a VBUS and a UVB output voltage (nodal, comparator inputs draw no current)."""
    g = 1 / rt2; g1 = 1 / r111; g2 = 1 / r112; g4 = 1 / r114; g5 = 1 / r115; g6 = 1 / r116
    A = [[g + g1 + g4, -g1, -g4],
         [-g1, g1 + g2, 0.0],
         [-g4, 0.0, g4 + g5 + g6]]
    b = [g * vbus, 0.0, g6 * vuvb_out]
    _, vhm, vup = solve3(A, b)
    return vhm, vup

def h1_inplus_coeffs(rt1=RT1, r109=R109, r110=R110, r113=R113):
    ra1 = rt1 + r109
    g1, g2, g3 = 1 / ra1, 1 / r110, 1 / r113
    return g1 / (g1 + g2 + g3), g3 / (g1 + g2 + g3)   # IN+ = a*VMOT + b*VOUT

def h1_trips(vbus, tol=0.0, sgn=(0, 0, 0, 0, 0, 0), vos=0.0, hint=0.005, voh=3.3, vol=0.0, vuvb=3.3, rh=R113):
    s = sgn
    rt1 = RT1 * (1 + s[0] * tol); r109 = R109 * (1 + s[0] * tol); r110 = R110 * (1 - s[0] * tol)
    rt2 = RT2 * (1 + s[1] * tol); r111 = R111 * (1 + s[1] * tol); r112 = R112 * (1 - s[1] * tol)
    vhm, _ = t2_nodes(vbus, vuvb, rt2, r111, r112)
    a, b = h1_inplus_coeffs(rt1, r109, r110, rh)
    rise = (vhm + vos + hint / 2 - b * vol) / a       # output LOW until V-MOT rises past this
    fall = (vhm + vos - hint / 2 - b * voh) / a       # output HIGH until V-MOT falls past this
    return rise, fall

def h1_worst(vb):
    vhm_nom, _ = t2_nodes(vb, 3.3)
    dvcm = vhm_nom * 10 ** (-CMRR_DB / 20)
    lo_f, hi_f, lo_r, hi_r = 1e9, -1e9, 1e9, -1e9
    for s0, s1 in itertools.product([-1, 1], repeat=2):
        for vos in (-(VOS + dvcm), VOS + dvcm):
            for hint in VHYS:
                for voh in VOH:
                    for vol in VOL:
                        for rh in (R113 * 0.99, R113 * 1.01):
                            for vu in (0.0, 3.3):
                                r, f = h1_trips(vb, 0.001, (s0, s1, 0, 0, 0, 0), vos, hint, voh, vol, vu, rh)
                                lo_f, hi_f = min(lo_f, f), max(hi_f, f)
                                lo_r, hi_r = min(lo_r, r), max(hi_r, r)
    return lo_f, hi_f, lo_r, hi_r

print("H.1  H1 comparator (U102) trip points on V-MOT; R_T1/R_T2 10.0k at the MB joints; 0.1 % dividers; TLV3012B worst case incl. CMRR")
h1 = {}
for vb in (15.2, 15.5, 15.9, 16.39, 17.2, 19.5):
    r, f = h1_trips(vb)
    lo_f, hi_f, lo_r, hi_r = h1_worst(vb)
    h1[vb] = dict(rise_nom=r, fall_nom=f, fall_min=lo_f, fall_max=hi_f, rise_min=lo_r, rise_max=hi_r, guard=lo_f - vb)
    print("  VBUS %5.2f V: rise %.3f / fall %.3f nominal (hyst %.3f); fall %.3f-%.3f, rise %.3f-%.3f; guard (fall_min - VBUS) %.3f V; ratio rise/VBUS %.4f"
          % (vb, r, f, r - f, lo_f, hi_f, lo_r, hi_r, lo_f - vb, r / vb))
rec("H1", h1)
ra_th = par(RT1 + R109, R110, R113)
tauA = ra_th * 470e-12
print("  IN+ divider RC with C106 470 pF: tau %.1f us; ripple attenuation 1/sqrt(1+(2 pi f tau)^2)" % (tauA * 1e6))
for f in (8e3, 20e3, 30e3):
    att = 1 / math.sqrt(1 + (2 * math.pi * f * tauA) ** 2)
    print("    f = %5.0f kHz: attenuation %.3f -> V-MOT ripple p-p that equals the 0.25 V minimum hysteresis: %.2f V" % (f / 1e3, att, 0.25 / att))
rec("H1_tau_us", tauA * 1e6)
print("  Tap short to GND at the CR end: V-MOT through R_T1 10k = %.1f mA, %.0f mW in an 0805 (0.125 W); VBUS through R_T2 = %.1f mA"
      % (22.0 / RT1 * 1e3, 22.0 ** 2 / RT1 * 1e3, 19.5 / RT2 * 1e3))
print("  Open divider bottom: IN+ rises toward V-MOT through %.0f k; BAV199 clamp (D104/D105) to 3V3 carries %.1f uA at 22 V (abs max 7 V, SBOS300C 6.1 note 2)"
      % ((RT1 + R109) / 1e3, (22.0 - 3.3 - 0.7) / (RT1 + R109) * 1e6))

def uvb_trips(vref, vos=0.0, hint=0.005, voh=3.3, vol=0.0, tol=0.0, s=(0, 0), r116=R116):
    r114 = R114 * (1 + s[0] * tol); r115 = R115 * (1 - s[0] * tol)
    rt2 = RT2 * (1 + s[1] * tol)
    out = []
    for vout, sign in ((vol, +1), (voh, -1)):
        # find VBUS such that UVB IN+ = vref + vos + sign*hint/2 (linear in VBUS)
        tgt = vref + vos + sign * hint / 2
        _, v0 = t2_nodes(0.0, vout, rt2, R111, R112, r114, r115, r116)
        _, v1 = t2_nodes(20.0, vout, rt2, R111, R112, r114, r115, r116)
        out.append((tgt - v0) / ((v1 - v0) / 20.0))
    return out[0], out[1]   # rise (re-permit), fall (inhibit)

r_nom, f_nom = uvb_trips(VREF[1])
flo, fhi, rlo, rhi = 1e9, -1e9, 1e9, -1e9
flo25, fhi25 = 1e9, -1e9
dvcm_u = VREF[1] * 10 ** (-CMRR_DB / 20)
for s0, s1 in itertools.product([-1, 1], repeat=2):
    for vr in (VREF[0], VREF[2]):
        for dt in DT_CR:
            for tcs in (-1, 1):
                vref = vr * (1 + tcs * REF_TC * dt)
                for vos in (-(VOS + dvcm_u), VOS + dvcm_u):
                    for hint in VHYS:
                        for voh in VOH:
                            for vol in VOL:
                                for r116 in (R116 * 0.99, R116 * 1.01):
                                    rr, ff = uvb_trips(vref, vos, hint, voh, vol, 0.001, (s0, s1), r116)
                                    flo, fhi, rlo, rhi = min(flo, ff), max(fhi, ff), min(rlo, rr), max(rhi, rr)
                                    if dt == 0.0 and abs(vos) <= VOS + 1e-9:
                                        pass
# 25 C, no CMRR term (the round-3 r0 basis) for comparison
for s0, s1 in itertools.product([-1, 1], repeat=2):
    for vr in (VREF[0], VREF[2]):
        for vos in (-VOS, VOS):
            for hint in VHYS:
                for voh in VOH:
                    for vol in VOL:
                        rr, ff = uvb_trips(vr, vos, hint, voh, vol, 0.001, (s0, s1))
                        flo25, fhi25 = min(flo25, ff), max(fhi25, ff)
VINDPM_FC = 14.5
VINDPM_FC_FLOOR = VINDPM_FC * (1 - 0.026)    # DS EC VINDPM accuracy +-2 % at 18.6 V / +-3 % at 4.6 V -> 2.6 % interpolated (TEST T-B-13)
print("H.2  UVB comparator (U103): R114 1.00M / R115 104k (0.1 %%), R116 10.0M, shared R_T2: rise %.2f V, fall %.2f V nominal"
      % (r_nom, f_nom))
print("     fall (inhibit) band %.2f-%.2f V and rise band %.2f-%.2f V incl. REF drift 100 ppm/C over 0-45 C and CMRR 54 dB"
      % (flo, fhi, rlo, rhi))
print("     (25 C basis without CMRR: fall band %.2f-%.2f V)" % (flo25, fhi25))
print("     FC VINDPM floor %.2f V - UVB fall max %.2f V = margin %.3f V (>= 0.05 V required; T-B-13, T-C-03)"
      % (VINDPM_FC_FLOOR, fhi, VINDPM_FC_FLOOR - fhi))
print("     UVB rise max %.2f V vs the loaded FC-only bus (>= 15.2 V assumed, T-E-08): margin %.2f V" % (rhi, 15.2 - rhi))
rec("UVB", dict(rise_nom=r_nom, fall_nom=f_nom, fall_band=(flo, fhi), rise_band=(rlo, rhi), margin_vindpm=VINDPM_FC_FLOOR - fhi))

# ======================================================================= H.3  BT_OK (U104) and BTB sense (U115)
R141, R142, R143 = 61.9e3, 1.00e3, 100.0
k_sns = 0.1   # V/A INA253A1 (CLAUDE.md section 5)
thr_lo, thr_hi = 1e9, -1e9
for vr in (VREF[0], VREF[2]):
    for dt in DT_CR:
        for tcs in (-1, 1):
            for s in (-1, 1):
                vref = vr * (1 + tcs * REF_TC * dt)
                v = vref * R142 * (1 + s * 0.01) / (R141 * (1 - s * 0.01) + R142 * (1 + s * 0.01))
                thr_lo, thr_hi = min(thr_lo, v), max(thr_hi, v)
bt_lo = thr_lo - VOS - VHYS[1] / 2
bt_hi = thr_hi + VOS + VHYS[1] / 2
print("H.3  BT_OK threshold %.2f mV nominal; %.2f-%.2f mV before Vos (incl. REF drift); with Vos +-9 mV and VHYS/2: %.1f-%.1f mV"
      % (VREF[1] * R142 / (R141 + R142) * 1e3, thr_lo * 1e3, thr_hi * 1e3, bt_lo * 1e3, bt_hi * 1e3))
print("     = %.3f-%.3f A of BT boost forward current (0.1 V/A); INA253 zero-current floor up to 10 mV (SLOS954A 7.5); "
      "T8 pull-up R144 1.00M injects %.1f uA into the INA253 output (T-C-08)" % (max(bt_lo, 0) / k_sns, bt_hi / k_sns, 3.3 / 1e6 * 1e6))
print("     T9 open: R142 returns through R143 100 ohm to the CR plane; plane-offset coupling with T9 intact ~ R_wire/R143 = %.1e" % (0.02 / R143))
rec("BT_OK_A", (max(bt_lo, 0) / k_sns, bt_hi / k_sns))
# BTB sense: U115 IN+ = REF/3 via R117 20.0k / R118 10.0k; IN- = D-BT-EN tap via R120 10k; R119 1.00M pull-up to 3V3 at IN-
R117, R118, R119, R120 = 20.0e3, 10.0e3, 10.0e6, 10.0e3   # r2: R119 10.0M (finding btb-pullup-backdrives-en)
REN_PD = (475e3, 985e3)     # RT DS-00 EC p.7
VEN_R_MAX, VEN_F_MIN = 1.4, 0.6
b_lo = min(vr * (1 - REF_TC * dt) for vr in (VREF[0],) for dt in DT_CR) * R118 * 0.99 / (R117 * 1.01 + R118 * 0.99) - VOS - VHYS[1] / 2
b_hi = max(vr * (1 + REF_TC * dt) for vr in (VREF[2],) for dt in DT_CR) * R118 * 1.01 / (R117 * 0.99 + R118 * 1.01) + VOS + VHYS[1] / 2
r_en = par(10e3, REN_PD[0])
v_en_reset = 3.3 * r_en / (R119 + R120 + r_en)
v_in_reset = 3.3 * (R120 + r_en) / (R119 + R120 + r_en)
v_in_drv_low = 3.3 * R120 / (R119 + R120)
print("H.3b BTB sense (U115): threshold REF/3 %.3f-%.3f V worst case, below VEN_F min %.1f V (RT EC p.7): margin %.2f V"
      % (b_lo, b_hi, VEN_F_MIN, VEN_F_MIN - b_hi))
print("     Teensy driving pin 28 LOW: IN- %.0f mV; Teensy in reset (EN net only on 10k || REN_PD): EN net %.0f mV, IN- %.0f mV; open tap: IN- -> 3.3 V (BTB_OFF LOW)"
      % (v_in_drv_low * 1e3, v_en_reset * 1e3, v_in_reset * 1e3))
print("     pin 28 accidentally INPUT_PULLUP (~22 k against 10 k): EN %.2f V -> BTB_OFF LOW (permit removed); the old LVC input read that as LOW"
      % (3.3 * r_en / (22e3 + r_en)))
en_open_bodge = [3.3 * r / (r + R119 + R120) for r in REN_PD]
print("     10 kOhm EN bodge pull-down OPEN and pin 28 high-Z (reset): EN net held only by REN_PD 475-985k against R119+R120: %.3f-%.3f V (VEN_F min %.1f V; r1 1.00M gave 1.06-1.63 V)"
      % (en_open_bodge[0], en_open_bodge[1], VEN_F_MIN))
print("     comparator offset from the R119 current through R120 with the tap intact (pin 28 LOW): %.1f mV" % (3.3 / (R119 + R120) * R120 * 1e3))
rec("BTB_EN_OPEN_BODGE_V", en_open_bodge)
rec("BTB_SENSE_V", (b_lo, b_hi))

# ======================================================================= H.4  ILIM_HIZ network (DS 7.3.4.3: ILIM = (V - 1 V)/0.8 ohm)
# EVM R21 REMOVED, JP14/JP13/JP21 open. EVM R23 100k REPLACED by 49.9k 1 % (halves the leakage error). EIB: Q203 PMOS (source REGN)
# -> R255 48.7k -> JP14 ILIM-side pin. R256 200k soldered at TP33 to AGND (R23-open guard). Q202 + R257 59.0k = FC leg. Sense: R258 100k + R259 10M pull-up to 3V3.
R255, R23, R256, R257 = 48.7e3, 49.9e3, 200e3, 59.0e3
R258, R259 = 100e3, 10.0e6
I_LEAK_PIN = 1.5e-6        # DS EC ILEAK_ILIM +-1.5 uA at 4 V
I_LEAK_FET = 1.0e-6        # 2N7002K / BSS84 off-state drain leakage allowance at < 3 V (TEST T-A-03)
def ilim_v(regn, r_rel, rb, i_inj):
    """ILIM_HIZ node voltage: Thevenin of R_REL from REGN against rb, plus an injected current i_inj (A, + = into node)."""
    vth = regn * rb / (r_rel + rb)
    return vth + i_inj * par(r_rel, rb)
res = {}
for name, legs in (("regen (Q202 off)", (R23, R256)), ("FC (Q202 on, R257 || EVM R23)", (R23, R256, R257))):
    vals, vpins = [], []
    for a, b, c in itertools.product((-1, 1), repeat=3):
        for regn in (4.8, 5.2):
            rb = par(*[l * (1 + b * 0.01) for l in legs])
            r_rel = R255 * (1 + a * 0.01)
            for leak in (-1, 1):
                # pin leakage +-1.5 uA; FET leakage: Q201 off (sinks), Q202 off in regen state (sinks via R257 path) -> negative;
                # sense pull-up injects (3.3 - V)/(R258 + R259) -> positive
                v0 = regn * rb / (r_rel + rb)
                i_sense = (3.3 - v0) / (R258 + R259)
                i_fet = -I_LEAK_FET * (2 if name.startswith("regen") else 1)
                i = leak * I_LEAK_PIN + (i_fet if leak < 0 else 0.0) + i_sense
                v = ilim_v(regn, r_rel, rb, i)
                vpins.append(v)
                vals.append((v - 1.0) / 0.8)
    nom_rb = par(*legs)
    nom_v = 5.0 * nom_rb / (R255 + nom_rb)
    res[name] = (min(vals), max(vals), (nom_v - 1.0) / 0.8, min(vpins), max(vpins))
    print("H.4  ILIM %-26s pin %.2f-%.2f V -> clamp %.3f-%.3f A (nominal %.3f A at REGN 5.0 V; incl. pin leakage +-1.5 uA, FET 1 uA, sense pull-up)"
          % (name, min(vpins), max(vpins), min(vals), max(vals), (nom_v - 1.0) / 0.8))
rec("ILIM", res)
v_hiz_q201_off = (I_LEAK_PIN + I_LEAK_FET + 3.3 / (R258 + R259)) * par(R23, R256)
print("     HIZ state (Q203 off, Q201 failed open): ILIM <= %.2f V from leakage (pin 1.5 uA + PMOS 1 uA + sense 0.3 uA) into R23 || R256 -> below 0.75 V"
      % v_hiz_q201_off)
print("     HIZ state with EVM R23 open as well (TP33 R256 200k alone): <= %.2f V" % ((I_LEAK_PIN + I_LEAK_FET + 3.3 / (R258 + R259)) * R256))
print("     Sense pull-up error with the wire intact: <= %.0f mV; sense wire open: comparator IN+ -> 3.3 V (reads RELEASED)"
      % (3.3 / (R258 + R259) * par(R255, R23, R256) * 1e3))
# ILIM sense comparator U203: IN- = REF x R261/(R260+R261), R260 10.0k, R261 26.1k
R260, R261 = 10.0e3, 10.0e3   # r2: R261 26.1k -> 10.0k so "held" implies < VIL_ILIM_HIZ 0.75 V (DS 6.5)
s_lo = VREF[0] * (1 - REF_TC * 45) * R261 * 0.99 / (R260 * 1.01 + R261 * 0.99) - VOS - VHYS[1] / 2
s_hi = VREF[2] * (1 + REF_TC * 45) * R261 * 1.01 / (R260 * 0.99 + R261 * 1.01) + VOS + VHYS[1] / 2
print("     ILIM sense (U203) threshold %.3f-%.3f V: below VIL_ILIM_HIZ max 0.75 V (held reading guarantees no switching), above the held level (<= 0.11 V; 0.57 V with EVM R23 open: margin %.0f mV) and below the lowest released level %.2f V"
      % (s_lo, s_hi, (s_lo - 0.57) * 1e3, res["FC (Q202 on, R257 || EVM R23)"][3]))
rec("ILIM_SENSE_V", (s_lo, s_hi))

# ======================================================================= H.5  eFuse TPS26630 (SLVSE94G)
RILIM_EF = 8.06e3
iol = 18 / (RILIM_EF / 1e3)
IOL = (iol * 0.92, iol, iol * 1.08)
print("H.5  eFuse R101 %.2f k -> I_OL %.3f A nominal (Eq.5; +-8 %% per EC 1.84-2.16 A at 9 k) -> %.2f-%.2f A; fast-trip 2x = %.1f-%.1f A in 2.2-4.5 us"
      % (RILIM_EF / 1e3, iol, IOL[0], IOL[2], 2 * IOL[0], 2 * IOL[2]))
print("     margin to the regen clamp max %.3f A (with leakage): %.2f A" % (res["regen (Q202 off)"][1], IOL[0] - res["regen (Q202 off)"][1]))
rec("EFUSE_IOL", IOL)
R102, R103, R104 = 845e3, 66.5e3, 49.9e3      # IN_SYS - R102 - UVLO - R103 - OVP - R104 - GND, 0.1 %
RT = R102 + R103 + R104
vuv = 1.2 * RT / (R103 + R104)
vov = 1.2 * RT / R104
def ef_band():
    uv, ov = [], []
    for v in (1.176, 1.224):
        for a, b, c in itertools.product((-1, 1), repeat=3):
            r2, r3, r4 = R102 * (1 + a * 0.001), R103 * (1 + b * 0.001), R104 * (1 + c * 0.001)
            uv.append(v * (r2 + r3 + r4) / (r3 + r4)); ov.append(v * (r2 + r3 + r4) / r4)
    return (min(uv), max(uv)), (min(ov), max(ov))
uvb_, ovb_ = ef_band()
print("     UVLO/OVP divider R102 %.0fk / R103 %.1fk / R104 %.1fk (0.1 %%): V_UV %.2f V (%.2f-%.2f), V_OV %.2f V (%.2f-%.2f); Eq.9/10, V(UVLOR)/V(OVPR) 1.176-1.224 V"
      % (R102 / 1e3, R103 / 1e3, R104 / 1e3, vuv, uvb_[0], uvb_[1], vov, ovb_[0], ovb_[1]))
print("     OVP band vs design clamp 22.28 V max: %.2f V above; vs BQ25798 VBUS recommended max 24 V (DS 6.3): %.2f V below; string current at 21 V %.1f uA"
      % (ovb_[0] - 22.28, 24.0 - ovb_[1], 21 / RT * 1e6))
rec("EFUSE_UV_OV", dict(uv=(vuv,) + uvb_, ov=(vov,) + ovb_))
CDVDT = 22e-9
C_EVM_IN = 50.4e-6 + 1.0e-6    # EVM C11, C12, C29, C30, C31 (5 x 10 uF) + C13, C32, C14, C15 (4 x 0.1 uF), UG Fig 4-5 / Table 4-1; + carrier C103 1 uF
for vin in (15.9, 19.0):
    t = 20.8e3 * vin * CDVDT
    print("     dVdT 22 nF at VIN %.1f V: ramp %.2f ms, %.2f V/ms -> inrush into %.1f uF = %.3f A; turn-on delay 742+49.5*22 us = %.2f ms"
          % (vin, t * 1e3, vin / t / 1e3, C_EVM_IN * 1e6, C_EVM_IN * vin / t, (742 + 49.5 * 22) / 1e3))
rec("EFUSE_INRUSH_A", C_EVM_IN * 15.9 / (20.8e3 * 15.9 * CDVDT))
L_LEAD = 0.5e-6 * 0.30     # H/m twisted-pair loop estimate x 0.30 m (UNVERIFIED; T-C-04 measures OUT)
z0 = math.sqrt(L_LEAD / 1e-6)
tq = math.pi / 2 * math.sqrt(L_LEAD * 1e-6)
print("     turn-off, case 1 (overload / fast-trip at %.1f A): OUT starts near VIN (~16 V) and dips by I x sqrt(L/C103) = %.1f V; never negative, D103 does not conduct"
      % (2 * IOL[2], 2 * IOL[2] * z0))
print("     turn-off, case 2 (hard short at the EVM J1 end): C103 + lead quarter period %.2f us < 1 us hot-short response (EF 6.6): OUT crosses 0 V before the FET opens;"
      % (tq * 1e6))
print("       D103 freewheels a lead current of the order of I_SCP 45 A for < 1 us, OUT clamped at -VF(I) (~ -0.5 to -1 V): below the -0.3 V abs min (EF 6.1),"
      " accepted under EF 9.5.1 / 11 (TODO(verify: TI E2E), T-C-04)")
rec("EFUSE_TURNOFF", dict(case1_dip_V=2 * IOL[2] * z0, case2_quarter_us=tq * 1e6))
# IMON: R105 27.4k, C105 10 nF at IMON; R129 10.0k series, C129 1 nF at the pin (D102 removed, review r1)
R105 = 27.4e3
G_IMON = (25.66e-6, 27.9e-6, 30.14e-6)
print("     IMON R105 %.1f k: %.3f V/A (%.3f-%.3f); 1.72 A -> %.2f V; I_OL max %.2f A -> %.2f V (current-regulated above I_OL)"
      % (R105 / 1e3, G_IMON[1] * R105, G_IMON[0] * R105, G_IMON[2] * R105, 1.72 * G_IMON[1] * R105, IOL[2], IOL[2] * G_IMON[2] * R105))
v_tr = min(5.5, 4.8 * G_IMON[2] * R105)
print("     fast-trip window (<= 4.5 us) with IMON up to %.2f V: R129 10k + C129 1 nF (tau 10 us) passes %.2f V to pin 22; continuous clamp current at 4 V: %.0f uA (TODO(verify: i.MX RT1062 injection limit))"
      % (v_tr, v_tr * (1 - math.exp(-4.5 / 10.0)), (4.0 - 3.3 - 0.3) / 10e3 * 1e6))
rec("IMON_V_PER_A", tuple(g * R105 for g in G_IMON))

# ======================================================================= H.6  Inrush on every switch closure
CSS_NF = 5.6        # D-BT-EN C-DC4 5600 pF (.sch net N$20, BOM C-DS); all RT1987 on the board use the same CSS (spec.md 6)
def t_on_us(vin, css_nf=CSS_NF):
    return vin / 35.0 * (css_nf / 0.0023 - 100.0)        # RT DS-00 17.3
def slew(vin, css_nf=CSS_NF):
    return 0.8 * vin / (t_on_us(vin, css_nf) * 1e-6)      # V/s, 10-90 %
SR = slew(16.0)
print("H.6  Inrush. RT1987 soft-start with CSS %.1f nF: tON %.2f ms at 16 V, slew %.1f V/ms (VIN-independent)" % (CSS_NF, t_on_us(16.0) / 1e3, SR / 1e3))
C_BOARD_VCHGIN = 20e-6
print("     Run-entry REGEN close (cold): board %.0f uF x %.0f V/ms = %.2f A; EVM side behind the eFuse dVdT %.3f A; EVM dark until VCHG-IN > ~10 V (UVLO)"
      % (C_BOARD_VCHGIN * 1e6, SR / 1e3, C_BOARD_VCHGIN * SR, OUT["EFUSE_INRUSH_A"]))
rec("INRUSH_RUN_ENTRY_A", C_BOARD_VCHGIN * SR)
print("     FC_CHARGE close in Run (warm, VCHG-IN held by REGEN): dV ~70 mV, ~5 uC: negligible")
# BT_BUS close onto an FC-only bus (pre-emption / early purge). C_eff = VBUS 40 uF + V-MOT (D-MT-EN forward) 0.4-0.97 mF (T-E-04)
ISCP = 8.5          # A, VIN-VOUT <= 5 V during soft-start (RT EC p.8); 250 us timer (17.5); retry after 64 ms (Table 1)
T_SCP = 250e-6
bt_close = []
print("     BT_BUS close (D-BT-EN) onto a pre-biased FC-only bus: I_pk = min(C_eff x SR + I_load, ISCP 8.5 A), width = delta/SR; SCP if clamp > 250 us")
for c_vm in (0.4e-3, 0.97e-3):
    c_eff = 40e-6 + c_vm
    for i_load in (0.15, 1.05):
        for dv in (0.05, 0.3, 0.8, 1.5, 2.4, 4.0):
            ipk = min(c_eff * SR + i_load, ISCP)
            if c_eff * SR + i_load > ISCP:
                t_clamp = dv * c_eff / (ISCP - i_load)
            else:
                t_clamp = 0.0
            width = dv / SR if t_clamp == 0.0 else t_clamp
            scp = t_clamp > T_SCP
            bt_close.append(dict(c_vm=c_vm, i_load=i_load, dv=dv, ipk=ipk, width_us=width * 1e6, scp=scp))
            print("       C_VMOT %.2f mF, load %.2f A, delta %.2f V: I_pk %.1f A for %.0f us%s; P(1 kHz OC_BT 3.0 A sample lands in it) ~ %.1f %%"
                  % (c_vm * 1e3, i_load, dv, ipk, width * 1e6, "  -> SCP TRIP, 64 ms retry" if scp else "",
                     min(100.0, width * 1e3 * 100.0) if ipk > 3.0 else 0.0))
rec("BT_CLOSE", bt_close)
for c_vm in (0.4e-3, 0.97e-3):
    c_eff = 40e-6 + c_vm
    dv_scp = 0.6 * T_SCP * (ISCP - 1.0) / c_eff
    print("     SCP no-trip bound (60 %% of 250 us, 1 A load): delta < %.2f V at C_VMOT %.2f mF -> purge-rescue floor = VBUS-BT - %.2f V"
          % (dv_scp, c_vm * 1e3, dv_scp))
rec("RESCUE_DV_SCP", {str(c): 0.6 * T_SCP * (ISCP - 1.0) / (40e-6 + c) for c in (0.4e-3, 0.97e-3)})
T_DON_MAX, T_ON = 16.0e-3, 1.4e-3
slope_ok = {}
for c_vm in (0.4e-3, 0.97e-3):
    dv_scp = 0.6 * T_SCP * (ISCP - 1.0) / (40e-6 + c_vm)
    slope_ok[str(c_vm)] = dv_scp / (T_DON_MAX + T_ON) / 1e3
    print("     early-purge rescue: highest bus sag rate a rescue close survives = dV_SCP / (tD_ON,max + tON) = %.3f V/ms at C_VMOT %.2f mF"
          " (H.8 sag 0.2-2.57 V/ms -> every rescue refused)" % (slope_ok[str(c_vm)], c_vm * 1e3))
rec("RESCUE_MAX_SAG_V_PER_MS", slope_ok)
sr68 = slew(16.0, 68.0)
print("     Lever (i) C-DC4 68 nF: tON %.1f ms, slew %.2f V/ms -> I_pk %.2f A + load at 0.97 mF (no SCP); conduction delay tD_ON + %.1f ms"
      % (t_on_us(16.0, 68.0) / 1e3, sr68 / 1e3, (40e-6 + 0.97e-3) * sr68, t_on_us(16.0, 68.0) / 1e3))
print("     Pre-biased conduction delay (5.6 nF): tD_ON 8 ms typ + (V_bus/VIN) x tON/0.8 ~ %.1f ms" % (t_on_us(16.0) / 1e3 / 0.8))

# ======================================================================= H.7  Regen absorption capability (both images)
VESC_CUT = 21.35
P_PEAK = {"2->1 m/s, 12 A": 11.1, "3->1 m/s, 12 A": 18.9}     # REGEN section 0 item 4
IINDPM_TOL = 0.88           # DS EC IINDPM -12 % at 1 A (only point specified); applied to the clamp as a conservatism
ICHG_TOL_BUCK = -0.065      # DS EC ICHG_ACC buck mode at 2 A, VBAT 8 V: -6.5 %/+3.5 % (2.5-3.1 A unspecified -> T-B-19)
ETA_MAX = 0.93              # highest 19 V -> 7.4 V efficiency assumed (worst case for absorption); TEST T-B-19
R_BATLEAD = 21.0e-3 * 0.60  # 18 AWG pair, 0.30 m each way
R_RT1987 = 0.020            # RT EC p.7 RON typ (max not given; T-B-15)
def vbat_pin(vpack, ichg):
    return vpack + ichg * (R_BATLEAD + R_RT1987)
def p_cap(ichg, vindpm_min, clamp_min, vpack=7.40):
    p_in_lim = min(clamp_min, 1.70) * IINDPM_TOL * vindpm_min
    p_ichg = ichg * (1 + ICHG_TOL_BUCK) * vbat_pin(vpack, ichg) / ETA_MAX
    return min(p_in_lim, p_ichg), p_in_lim, p_ichg
VINDPM_REGEN_MIN = 19.0 * 0.98
STAGE1_PRE = math.ceil((h1[16.39]["fall_max"] + 0.05) / 0.98 / 0.1 - 1e-9) * 0.1   # recomputed below as VINDPM_STAGE1
clamp_regen_min = res["regen (Q202 off)"][0]
clamp_fc_min = res["FC (Q202 on, R257 || EVM R23)"][0]
print("H.7  Absorption capability P = min(IINDPM limit, ICHG x (1-6.5 %%) x V_BATpin / eta_max %.2f), pack 7.40 V" % ETA_MAX)
cap = {}
for lab, ichg, vmin, cl in (("regen image ICHG 2.50 A (round-3 r0)", 2.50, VINDPM_REGEN_MIN, clamp_regen_min),
                            ("regen image ICHG 3.10 A (r1)", 3.10, VINDPM_REGEN_MIN, clamp_regen_min),
                            ("raised image stage 1 (VINDPM_STAGE1), ICHG 3.10 A", 3.10, STAGE1_PRE * 0.98, clamp_regen_min),
                            ("FC image ICHG 1.60 A", 1.60, 14.5 * 0.974, 0.90)):
    p, pi, pc = p_cap(ichg, vmin, cl)
    cap[lab] = (p, pi, pc)
    print("     %-52s input-limit %.1f W, ICHG-limit %.1f W -> %.1f W; vs 18.9 W: %+.1f %%; vs 11.1 W: %+.1f %%"
          % (lab, pi, pc, p, (p / 18.9 - 1) * 100, (p / 11.1 - 1) * 100))
rec("H7_CAP", cap)
ichg_need = 23.0 * ETA_MAX / ((1 + ICHG_TOL_BUCK) * vbat_pin(7.40, 3.06))
print("     ICHG needed for the HR1 23 W condition at 7.40 V: %.2f A; for 18.9 W: %.2f A"
      % (ichg_need, 18.9 * ETA_MAX / ((1 + ICHG_TOL_BUCK) * vbat_pin(7.40, 2.5))))
d84 = 3.10 * 1.035 * vbat_pin(8.40, 3.10) / 0.91
print("     At 8.40 V pack, ICHG 3.10 A +3.5 %%: demand %.1f W = %.2f A at 18.62 V -> the ILIM clamp (max %.3f A) binds; eFuse I_OL min %.2f A"
      % (d84, d84 / 18.62, res["regen (Q202 off)"][1], IOL[0]))
print("     In CV (pack near 8.4 V) ICHG tapers toward ITERM: capability -> ~0 W (FR-25 regen derate)")
for name, p in P_PEAK.items():
    veq = p / (0.90 * IINDPM_TOL)
    print("     %s, static FC image, input-limited: balances at V-MOT %.1f V; ICHG-limited capability %.1f W: %s"
          % (name, veq, cap["FC image ICHG 1.60 A"][2], "cannot balance -> raise required" if p > cap["FC image ICHG 1.60 A"][0] else "absorbed"))
# raise latency, VINDPM staging
fall_max_1639 = h1[16.39]["fall_max"]
stage1 = math.ceil((fall_max_1639 + 0.05) / 0.98 / 0.1 - 1e-9) * 0.1
print("     VINDPM_STAGE1 = lowest 100 mV code with -2 %% minimum > H1 fall max %.2f V + 50 mV: %.1f V (min %.2f, max %.2f)"
      % (fall_max_1639, stage1, stage1 * 0.98, stage1 * 1.02))
rec("VINDPM_STAGE1", stage1)
for C in (0.4e-3, 0.97e-3):
    v0 = h1[16.39]["rise_max"]
    i_sur = 18.9 / v0 - 0.90 * IINDPM_TOL
    dvdt = i_sur / C
    for tl in (0.52e-3, 1.22e-3, 3e-3):
        print("     before the raise lands (latency %.2f ms), C_VMOT %.2f mF, 18.9 W from H1 rise max %.2f V: +%.2f V/ms -> %.2f V (cut %.2f V)"
              % (tl * 1e3, C * 1e3, v0, dvdt / 1e3, v0 + dvdt * tl, VESC_CUT))
    i_all = 18.9 / v0
    for vnd, lab in ((19.0 * 1.02, "un-staged 19.0 V block (r0)"), (stage1 * 1.02, "stage 1")):
        head = VESC_CUT - vnd
        print("       worst unload (VINDPM written above V-MOT, charger draws ~0): %s: V-MOT climbs at %.2f V/ms; headroom %.2f V = %.2f ms for the VINDPM loop to reload"
              % (lab, i_all / C / 1e3, head, head / (i_all / C) * 1e3))
I_REGEN_PK = 1.1     # 18.9 W / VINDPM min ~ 1.02 A, rounded up (REGEN section 0 item 4)
V_CEIL = 20.5        # V-MOT ceiling used by T-B-09/T-B-10/T-B-12/T-D-12 (0.85 V below the 21.35 V VESC cut)
wr = {}
for lab, vmax in (("regen-armed cruise (VINDPM 19.0 V, max 19.38 V)", 19.0 * 1.02), ("raised stage 1 (max %.2f V)" % (stage1 * 1.02), stage1 * 1.02)):
    for C in (0.4e-3, 0.97e-3):
        b = (V_CEIL - vmax) * C / I_REGEN_PK
        wr["%s|%.2f" % (lab, C * 1e3)] = b * 1e3
        print("     warm-response budget t_d + tau <= (20.5 - VINDPM_max) x C / I_regen,pk 1.1 A: %s, C_VMOT %.2f mF: %.2f ms" % (lab, C * 1e3, b * 1e3))
rec("WARM_BUDGET_MS", wr)
print("     an 8 ms dead time (tD_ON repeat on a D-BT-SQ UVLO recovery) lifts V-MOT by %.0f V at 0.4 mF: keep-alive mandatory if T-B-09 measures it" % (1.1 * 8e-3 / 0.4e-3))
print("     false-restore guard: V_rgn > %.2f V (VINDPM max 19.38 + calibration 0.19 V) with the FC image and H1 = 1 -> forced raise" % (19.38 + 0.19))

# ======================================================================= H.8  Purge pre-emption timing (R6)
T_PURGE = 10.34
D_PURGE = (0.100, 0.140)
budget = {
    "firmware tick + P5 LOW + FC_CHARGE/FCCEIL LOW (one tick)": 1.0e-3,
    "VINDPM 19.0 V write + read-back (2 transactions, 100 kHz worst)": 0.8e-3,
    "charger shed settle before BT_BUS (bus recovery)": 2.0e-3,
    "RT1987 D-BT-EN tD_ON (8 ms typ, no max: 2x allowance; T-E-06)": 16.0e-3,
    "soft-start to the pre-biased bus (tON/0.8 at 16 V)": 1.4e-3,
    "readiness check (EN, FCC read-back, P5, optional VBUS-BT ADC)": 1.0e-3,
    "purge-onset jitter allowance (UNMEASURED; 50 Hz resolution x3; T-E-01)": 60.0e-3,
    "margin": 17.8e-3,
}
T_LEAD = sum(budget.values())
print("H.8  Purge pre-emption lead-time budget:")
for k, v in budget.items():
    print("     %-78s %6.1f ms" % (k, v * 1e3))
print("     T_LEAD = %.0f ms before the predicted purge onset" % (T_LEAD * 1e3))
T_REOPEN = 0.200 + 0.030
for d in D_PURGE:
    closed = T_LEAD + d + T_REOPEN
    print("     purge %.0f ms: window closed %.0f ms per %.2f s cycle -> FC-charge duty %.1f %% UPPER BOUND (uninterrupted admission: standstill or steady load)"
          % (d * 1e3, closed * 1e3, T_PURGE, 100 * (1 - closed / T_PURGE)))
rec("PURGE_T_LEAD_MS", T_LEAD * 1e3)
rec("PURGE_DUTY_PCT", [100 * (1 - (T_LEAD + d + T_REOPEN) / T_PURGE) for d in D_PURGE])
print("     hand-off sag: bus falls at ~0.2 V/ms (aux only, MOT_PWR closed, 0.51 mF; ESTIMATE) to 2.57 V/ms (HIL aux model, 40 uF): 0.5 ms costs 0.1-1.3 V")

# ======================================================================= H.9 / H.10  VCHG decay and keep-alive option (unchanged inputs)
C_BAT_NOM = 10e-6 + 20e-6 + 50e-6
I_RT_IQ = (0.650e-3, 0.780e-3)
I_BQ_BAT = (0.0, 0.5e-3)
print("H.9  VCHG decay with the converter in HIZ between bursts, no keep-alive (C_BAT %.0f uF nominal)" % (C_BAT_NOM * 1e6))
for cf in (1.0, 0.5):
    C = C_BAT_NOM * cf
    for il in (I_RT_IQ[0] + I_BQ_BAT[0], I_RT_IQ[1] + I_BQ_BAT[1]):
        print("     C x%.1f (%.0f uF), I %.2f mA: 8.4 V -> RT1987 UVLO-falling ~3.0 V in %.2f s; -> VBAT_SHORT 2.06 V in %.2f s"
              % (cf, C * 1e6, il * 1e3, (8.4 - 3.0) * C / il, (8.4 - 2.06) * C / il))
V5 = (4.9, 5.1); VF_D = (0.2, 0.4); RKA = 680.0
vmin = V5[0] - VF_D[1] - (I_RT_IQ[1] + I_BQ_BAT[1]) * RKA
vmax = V5[1] - VF_D[0] - I_RT_IQ[0] * RKA
print("H.10 KA option (DNP): VCHG held at %.2f-%.2f V; drain %.2f-%.2f mA + 0.062-0.080 mA in Run only; parked 0.5-2.3 uA" % (vmin, vmax, I_RT_IQ[0] * 1e3, (I_RT_IQ[1] + I_BQ_BAT[1]) * 1e3))
rec("KA_VCHG", (vmin, vmax))

# ======================================================================= H.11  leads, CV
R20AWG, R18AWG = 33.3e-3, 21.0e-3
L = 0.30
print("H.11 Leads (0.30 m each way)")
for name, rpm, i in (("input pair W1/W2 20 AWG", R20AWG, 1.80), ("battery pair W3/W4 18 AWG", R18AWG, 3.10)):
    r = rpm * 2 * L
    print("     %s: %.1f mOhm round trip; at %.2f A drop %.0f mV, loss %.0f mW" % (name, r * 1e3, i, r * i * 1e3, r * i * i * 1e3))
RON_EF = (0.019, 0.0304, 0.053)
print("     eFuse at 1.80 A: drop %.0f-%.0f mV, loss %.0f-%.0f mW" % (RON_EF[0] * 1.8e3, RON_EF[2] * 1.8e3, RON_EF[0] * 1.8 ** 2 * 1e3, RON_EF[2] * 1.8 ** 2 * 1e3))
lo, hi = 8.400 * (1 - 0.0025), 8.400 * (1 + 0.0065)
R_EVM_BAT = 0.010 + 0.001   # EVM R13 10 mOhm (UG Fig 4-5, J5 -> R13 -> JP5 -> BAT) + soldered 18 AWG JP5 link allowance 1 mOhm (EM12)
for i in (0.2, 3.1):
    dl = R18AWG * 2 * L * i + R_EVM_BAT * i
    dr = max(0.035, R_RT1987 * i)
    print("     CV at %.1f A (sensed at the BAT pin, JP9 2-3): pack = VREG - leads + R13 + JP5 link %.1f mV - D-BT-SQ %.0f mV = %.3f-%.3f V" % (i, dl * 1e3, dr * 1e3, lo - dl - dr, hi - dl - dr))
rec("CV_TERM", (lo - (R18AWG * 2 * L + R_EVM_BAT) * 0.2 - 0.035, hi - (R18AWG * 2 * L + R_EVM_BAT) * 0.2 - 0.035))
rec("CV_3A1", (lo - (R18AWG * 2 * L + R_EVM_BAT) * 3.1 - 0.062, hi - (R18AWG * 2 * L + R_EVM_BAT) * 3.1 - 0.062))

# ======================================================================= H.12  FC-window bus load vs arm drop / P_MAX / OC_FC
I_AUX = (0.09, 0.15)
OC_FC, P_MAX_BUS, ARM_DROP = 1.4, 1.247, 1.20
print("H.12 FC-window bus-side load (standstill, no traction)")
for name, i in (("FC image IINDPM 0.90 A at +0 %", 0.90),
                ("FC hardware clamp max (charger POR in the window), with leakage", res["FC (Q202 on, R257 || EVM R23)"][1]),
                ("regen clamp max (FC image lost, firmware fault)", res["regen (Q202 off)"][1])):
    for ia in I_AUX:
        tot = i + ia
        print("     %-66s aux %.2f: %.2f A  (arm drop 1.20 %s, P_MAX 1.247 %s, OC_FC 1.4 %s)"
              % (name, ia, tot, "ok" if tot < ARM_DROP else "OVER", "ok" if tot < P_MAX_BUS else "OVER", "ok" if tot < OC_FC else "LATCH"))
P_MAX_STACK, ETA_BOOST = 23.416, 0.85   # docs/modeling/h20_hydrogen_map_20260908.md 3.5 (brochure map end), HIL_PLANT ETA_BOOST
p_bus = P_MAX_STACK * ETA_BOOST
print("     H-20 P_MAX %.3f W stack = %.2f W bus at ETA_BOOST %.2f: %.3f A at 15.95 V, %.3f A at the loaded FC-only bus 15.2 V; OC_FC 1.4 A sits ABOVE the characterised stack range"
      % (P_MAX_STACK, p_bus, ETA_BOOST, p_bus / 15.95, p_bus / 15.2))
print("     window cap = min(OC_FC margin 1.20 A, (P_MAX_bus - 1.0 W margin)/V_bus) = %.3f A at 15.2 V; admission/close test G = cap - I_aux - max(I_trac,peak, I_cmd) - I_ripple - margin"
      % min(1.20, (p_bus - 1.0) / 15.2))
rec("FC_WINDOW_CAP_A", min(1.20, (p_bus - 1.0) / 15.2))
print("     cruise headroom: governor holds I_aux + I_trac + IINDPM <= 1.10 A -> 0.30 A to OC_FC for traction steps and ripple (FR-14, T-F-04b)")

# ======================================================================= H.13  inhibit latency allowances, glitch immunity
C_VMOT_MIN = 0.4e-3
CISS = 50e-12         # 2N7002K Ciss assumed (T-A-03)
R252 = 47e3
tau_q = R252 * CISS
print("H.13 Inhibit-latency allowance (H1 fall -> D-MT-EN conduction); deductions 24 us RC, 15 us comparator, %.1f us Q201 gate (47k x Ciss), 0.1 us LVC" % (3 * tau_q * 1e6))
C252 = 2.2e-9
tau_ilim = par(R255, R23, R256) * C252
for tg in (100e-9, 1e-6):
    t_off = tg + 3 * tau_q          # both Q201 (R252 47k) and Q203 (R254b 47k) recover through 47k x Ciss
    v = res["regen (Q202 off)"][3] * (1 - math.exp(-t_off / tau_ilim))
    print("     release glitch %.1f us (both Q201 and Q203 must change state; C252 2.2 nF): ILIM_HIZ reaches <= %.2f V -> %s"
          % (tg * 1e6, v, "no resume (< 0.75 V)" if v < 0.75 else "may resume"))
for I in (0.90, 1.25, 1.80):
    for vb in (15.5, 15.9, 16.39):
        lo_ = h1[vb]["fall_min"]
        s_ = I / C_VMOT_MIN
        t = (lo_ - (vb - 0.035)) / s_
        print("     I_in %.2f A, VBUS %.2f: %.2f V/ms, allowance %.0f us" % (I, vb, s_ / 1e3, (t - 24e-6 - 15e-6 - 3 * tau_q) * 1e6))

# ======================================================================= H.14  thermal
RTHJA_BQ = 44.2
for name, pout, eta in (("FC charge 1.6 A x 8.4 V", 1.6 * 8.4, 0.935), ("regen 3.1 A x 8.4 V (burst)", 3.1 * 8.4, 0.91)):
    loss = pout * (1 / eta - 1)
    print("H.14 %s: loss %.2f W, dT_JA %.0f C (JEDEC; EVM copper better)" % (name, loss, loss * RTHJA_BQ))
print("     eFuse 1.80 A worst RON 53 mOhm: %.0f mW" % (0.053 * 1.8 ** 2 * 1e3))

# ======================================================================= H.15  Run-time standby draw (always-powered regen design)
iq = {"eFuse IQ(ON) (EF 6.5)": (1.38e-3, 1.70e-3), "D-BC-RG RT1987 IQ (RT EC p.7)": (0.65e-3, 0.78e-3),
      "CHG_VOLTAGE divider 88.7k at 16 V": (16 / 88.7e3,) * 2, "eFuse UVLO/OVP string": (16 / RT,) * 2,
      "BQ25798 IC, ILIM held, REGN on (UNSPECIFIED; ISD_VBUS 386 uA is HIZ-mode, used as the floor; T-B-04)": (0.39e-3, 1.0e-3),
      "BQ25798 ADC continuous, IBAT+IBUS (adder; battery-side IQ_BAT_ON 540 vs 17-24 uA, DS 6.5; VBUS-side unspecified, T-B-04)": (0.2e-3, 0.52e-3),
      "EVM TS bias from REGN: R18 5.23k + R24 30.1k || R25 10.0k (JP18 in), 5.0 V / 12.74k": (5.0 / 12.74e3,) * 2,
      "EIB REGN pull-ups sinking in armed cruise (R254 Q202 gate, R272 /CE), 2 x ~0.11 mA": (0.2e-3,) * 2,
      "D103 reverse leakage at 16-23.6 V, 60 C (selection target, T-A-05/T-A-07; B340A fallback below)": (0.005e-3, 0.1e-3)}
lo_ = sum(v[0] for v in iq.values()); hi_ = sum(v[1] for v in iq.values())
print("H.15 Run standby draw from VCHG-IN (bus side) while regen-armed:")
for k, v in iq.items():
    print("     %-58s %.3f-%.3f mA" % (k, v[0] * 1e3, v[1] * 1e3))
print("     total %.2f-%.2f mA x 16 V = %.0f-%.0f mW for all of Run (keep-alive option for comparison: 3.5-7 mW)" % (lo_ * 1e3, hi_ * 1e3, lo_ * 16e3, hi_ * 16e3))
print("     B340A fallback worst case (DS13005 IRM 20 mA at 100 C, rated 40 V): up to 20 mA x 16 V = 0.32 W -> does not fit; operator decision if no low-IR part qualifies")
icc3 = {"2 x SN74LVC1G123 active, Rext/Cext 0.5 VCC (MV EC 280 uA max)": 0.56e-3, "6 x TLV3012 (5 uA max each, SBOS300C)": 30e-6,
        "REF dividers (U104, U115, U203 20k) ~3 x 40 uA": 120e-6, "LVC static (ICC 10 uA max each, 8 parts)": 80e-6,
        "R107 10k STAT pull-up while STAT LOW (charging)": 3.3 / 10e3,
        "4 ribbon driver inputs (100 + 1k + 47k to AGND) while HIGH": 4 * 3.3 / 48.1e3,
        "EIB 3V3 bleed R274 10.0k": 3.3 / 10e3, "other pull-ups/pull-downs worst": 0.1e-3}
print("     3V3 load of CR + EIB (I2C pull-ups now on the MB side, not on this rail): %.2f mA worst static; Teensy 4.1 3.3 V pin rated ~250 mA (TODO(verify: PJRC pinout card)); 26 AWG T6: no constraint" % (sum(icc3.values()) * 1e3))
rec("ICC3_MA", sum(icc3.values()) * 1e3)
rec("RUN_DRAW_MW", (lo_ * 16e3, hi_ * 16e3))

# ======================================================================= H.16  I2C at 400 kHz
for rp, lab in ((10e3, "10k only (RSDA/RSCL as built)"), (2.7e3, "MB RSDA/RSCL changed to 2.7k, CR R145/R146 DNP (r2)")):
    cbmax_fm = 300e-9 / (0.8473 * rp)
    print("H.16 I2C %s: Rp %.2f k; Cb max for tr 300 ns (Fm) %.0f pF, for 1000 ns (Sm) %.0f pF; sink at VOL 0.4 V %.2f mA (3 mA limit)"
          % (lab, rp / 1e3, cbmax_fm * 1e12, 1000e-9 / (0.8473 * rp) * 1e12, (3.3 - 0.4) / rp * 1e3))
cb_est = 0.30 * 50e-12 + 30e-12 + 20e-12 + 10e-12
print("     Cb estimate: W7 0.30 m x 50 pF/m + board 30 pF + EVM 20 pF + Teensy 10 pF = %.0f pF (TEST T-C-06 scopes tr); tr = %.0f ns with 2.7k"
      % (cb_est * 1e12, 0.8473 * 2.7e3 * cb_est * 1e9))
for f, lab in ((100e3, "100 kHz"), (400e3, "400 kHz")):
    bits = lambda nbytes: nbytes * 9 + 2
    print("     %s: T3 = REG06-07 write (4 bytes) + REG03-05 write (5 bytes) = %.2f ms; longest poll transaction capped at %.2f ms"
          % (lab, (bits(4) + bits(5)) / f * 1e3, 0.5 if f < 200e3 else 0.35))

# ======================================================================= H.17  monostables (SN74LVC1G123, SCES586E)
C_LO = 0.90 * 0.85 * 0.80   # tolerance -10 %, X7R tempco -15 % (EIA X7R), DC-bias loss at the Rext/Cext swing up to -20 % (TODO(verify: Murata GRM21BR71C335 / GRM188R71C334 characteristic data))
C_HI = 1.10 * 1.15 * 1.00
mono = {}
for key, lab, r, c in (("QQ", "QUAL one-shot U111 (R150 100k, C150 3.3 uF X7R)", 100e3, 3.3e-6), ("HB", "heartbeat U113 (R151 100k, C151 330 nF X7R)", 100e3, 330e-9)):
    lo_t, hi_t = 1.0 * r * 0.99 * c * C_LO, 1.1 * r * 1.01 * c * C_HI
    mono[key] = (lo_t * 1e3, hi_t * 1e3)
    print("H.17 %s: tw ~ K x R x C, K 1.0-1.1 (MV 5.8; K at 100k read from Fig 5-6, TODO(calibrate)), R +-1 %%, C x%.3f-x%.3f: %.0f-%.0f ms (r1 band: C +-10 %% only)"
          % (lab, C_LO, C_HI, lo_t * 1e3, hi_t * 1e3))
print("     firmware constants until T-C-10: TW_HB_MAX = %.0f ms, TW_QQ_MAX = %.0f ms; HB_dead = no CHG_HB rising edge for > TW_HB_MAX + 2 loop periods; loop budget (FR-27) tw_HB_min/4 = %.1f ms"
      % (math.ceil(mono["HB"][1]), math.ceil(mono["QQ"][1]), mono["HB"][0] / 4))
rec("MONO_MS", mono)
print("     QUAL window must cover the DS 7.3.4 sequence (REGN +150 ms, poor-source ~30 ms, ILIM read) and end before 400 ms after REGEN close")

# ======================================================================= H.18  CR placement area budget (finding carrier-no-buildable-layout-reopen)
court = {"U101 VQFN-24 4x4 + vias": 1 * 36, "6 x SOT-23-6 (TLV3012B incl. DNP U117) at ~10 mm2": 6 * 10, "7 x SSOP-8 DCT (3G04, 2x2G32, 2x1G123, 2x2G08) + U118 2G08 at ~15 mm2": 8 * 15,
         "3 x SC70-6 (1G11) at ~7 mm2": 3 * 7, "~85 x 0603/0805 passives at ~4.3 mm2": 85 * 4.3, "4 x SOT-23 (BAV199 x3, DNP U112 SOT-23-6) at ~10 mm2": 4 * 10,
         "D103 SMA/SMB": 25, "J101 SMT 2x7 vertical (body ~ 18 x 5 mm + pads)": 120, "tap field 3 x 8, 2.54 mm": 21 * 8}
area = sum(court.values())
top_free = 23.1 * 31.0 + 2 * 2.5 * 33.0     # interior between the pin columns + the two outer strips (approx.)
bot_free = 31.0 * 33.0 - 11.5 * 5.0 - 2 * 33.0 * 1.9   # minus the bottom keep-out (24.5-36.0 x 48.5-53.5) and the pin columns
print("H.18 CR courtyard estimate %.0f mm2 vs top-side free ~%.0f mm2 and bottom-side free (outside the keep-out) ~%.0f mm2 -> %s"
      % (area, top_free, bot_free, "double-sided placement required" if area > top_free else "fits top side"))
rec("CR_AREA_MM2", dict(courtyard=area, top=top_free, bottom=bot_free))

# ======================================================================= register encodings
def enc(v, lsb):
    return int(round(v / lsb))
print("REG  VINDPM 19.0 V = 0x%02X, %.1f V (stage 1) = 0x%02X, 14.5 V = 0x%02X (REG05, 100 mV/LSB); IINDPM 1.70 A = 0x%04X, 0.90 A = 0x%04X (REG06, 10 mA/LSB); "
      "ICHG 3.10 A = 0x%04X, 2.50 A = 0x%04X, 1.60 A = 0x%04X (REG03, 10 mA/LSB); VREG 8.40 V = 0x%04X"
      % (enc(19.0, 0.1), stage1, enc(stage1, 0.1), enc(14.5, 0.1), enc(1.70, 0.01), enc(0.90, 0.01), enc(3.10, 0.01), enc(2.50, 0.01), enc(1.60, 0.01), enc(8.40, 0.01)))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "r3_calc_out.json"), "w") as fh:
    json.dump(OUT, fh, indent=1, default=str)
