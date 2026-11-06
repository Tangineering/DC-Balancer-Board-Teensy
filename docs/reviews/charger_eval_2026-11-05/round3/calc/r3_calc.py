#!/usr/bin/env python3
"""Round-3 calculations for docs/charger_bq25798_wiring_design_2026-11-05.md (BQ25798EVM on the Ag105 pads).

Revision r6 (2026-11-06, after review round 6; r5 after review round 5; r4 after review round 4; r3 after review round 3; r2 after review round 2; r1 after review round 1). Every input constant carries its source. Run:  python3 r3_calc.py
(stdlib only). Output is plain text (redirect to r3_calc_out.txt) plus r3_calc_out.json beside this file. Section
numbers match the design document section H (H.1 ... H.22). Designators match the design document (carrier 1xx, EIB 2xx,
EVM parts written "EVM Rnn").
Sources (literature numbers):
  DS   TI SLUSDV2C BQ25798                         UG  TI SLUUCB5E BQ2579xEVM
  RT   Richtek RT1987 DS-00                        TLV TI SBOS300C TLV3011/3012
  EF   TI SLVSE94G TPS2663x eFuse                  LS  TI SLVSDH0C TPS22810 load switch
  MV   TI SCES586E SN74LVC1G123 monostable          INA TI SLOS954A INA253 (repo copy), section 7.5
  BAL  TI SLUSA52C BQ29200 (r6, H.22(b))            ST  TI SCES218AA SN74LVC1G14 (r6, H.22(b))
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
# -> R255 48.7k -> JP14 ILIM-side pin. R256 200k soldered at TP33 to AGND (R23-open guard). Q202 + R257 59.0k = FC leg. Sense: R258 10.0k (r3; was 100k) + R259 10M pull-up to 3V3.
R255, R23, R256, R257 = 48.7e3, 49.9e3, 200e3, 59.0e3
R258, R259 = 10.0e3, 10.0e6   # r3 (finding u203-threshold-ignores-sense-offset): R258 100k -> 10.0k cuts the pin-referred offset to ~3 mV
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
# r3: U203 IN+ sits R258 x I(R259) above the pin; refer the threshold to the ILIM_HIZ pin
def pin_ref(vth, r258):
    # V_in+ = V_pin + (3.3 - V_pin) x r258/(r258 + R259)  ->  V_pin = (vth - 3.3 k)/(1 - k)
    k = r258 / (r258 + R259)
    return (vth - 3.3 * k) / (1 - k)
p_lo, p_hi = pin_ref(s_lo, R258), pin_ref(s_hi, R258)
p_lo100, p_hi100 = pin_ref(s_lo, 100e3), pin_ref(s_hi, 100e3)
print("     ILIM sense PIN-REFERRED (r3): with R258 %.0f k the trip at the ILIM_HIZ pin is %.3f-%.3f V (offset %.1f-%.1f mV); the r2 R258 100k gave %.3f-%.3f V, i.e. -%.0f mV against the 0.57 V R23-open held level"
      % (R258 / 1e3, p_lo, p_hi, (s_lo - p_lo) * 1e3, (s_hi - p_hi) * 1e3, p_lo100, p_hi100, (0.57 - p_lo100) * 1e3))
print("     margins at the pin: below VIL_ILIM_HIZ 0.75 V by %.0f mV; above the R23-open held level 0.57 V by %.0f mV; above the normal held level 0.11 V by %.2f V"
      % ((0.75 - p_hi) * 1e3, (p_lo - 0.57) * 1e3, p_lo - 0.11))
rec("ILIM_SENSE_PIN_V", (p_lo, p_hi))

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
C_BOARD_VCHGIN = 20e-6 + 1.0e-6 + 4.7e-6 + 0.1e-6   # r3: C-D8 + C-D10 (20 uF nominal) + CR C102a 1 uF + C102b 4.7 uF + C102c 0.1 uF (upstream of the eFuse dVdT)
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
          " (r6: a fixed 0.2 V/ms floor in FR-26 refused every rescue at both C_VMOT; the floor is now SAG_FLOOR[C_VMOT] < this rate, H.22(g))" % (slope_ok[str(c_vm)], c_vm * 1e3))
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
print("     false-restore guard (r2 basis, without R_path; r3 value in H.19): V_rgn > %.2f V (VINDPM max 19.38 + calibration 0.19 V) with the FC image and H1 = 1 -> forced raise" % (19.38 + 0.19))

# ======================================================================= H.8  Purge pre-emption timing (R6)
T_PURGE = 10.34
D_PURGE = (0.100, 0.140)
budget = {
    "step-A latency: timer-domain tick T_TICK_MAX + FC_CHARGE/FCCEIL LOW (P5 stays HIGH, r2; r6 FR-45)": 1.0e-3,
    "charger shed settle before BT_BUS (bus recovery; the VINDPM write + read-back, 0.8 ms at 100 kHz, runs inside it, r6)": 2.0e-3,
    "step-D boundary latency: one more timer-domain tick T_TICK_MAX (r6, finding loop-budget-5ms-breaks-1ms-tick-deadlines)": 1.0e-3,
    "RT1987 D-BT-EN tD_ON (8 ms typ, no max: 2x allowance; T-E-06)": 16.0e-3,
    "soft-start to the pre-biased bus (tON/0.8 at 16 V)": 1.4e-3,
    "readiness check (EN, FCC read-back, optional VBUS-BT ADC)": 1.0e-3,
    "purge-onset jitter allowance (UNMEASURED; 50 Hz resolution x3; T-E-01)": 60.0e-3,
    "margin": 17.6e-3,
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
print("     hand-off sag: bus falls at ~0.2 V/ms (aux only, MOT_PWR closed, 0.51 mF; ESTIMATE, r6: not a FR-26 constant any more) to 2.57 V/ms (HIL aux model, 40 uF): 0.5 ms costs 0.1-1.3 V")

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
# r5 (finding ichg-upper-tolerance-omitted-in-ratings): the output-path ratings use the ICHG upper bound. DS 6.5 ICHG_ACC buck mode is
# specified only at 2 A (-6.5/+3.5 %); extrapolated to the 3.10 A regen image it gives 3.21 A (unspecified above 2 A, T-B-19 measures).
ICHG_UP = 1.035
for nm, i in (("regen image 3.10 A", 3.10), ("FC image 1.60 A", 1.60)):
    ii = i * ICHG_UP
    print("     r5 ICHG upper bound (+3.5 %%, DS 6.5 at 2 A, extrapolated): %s -> %.3f A; W3/W4 round trip %.0f mV / %.0f mW; EVM R13 + JP5 link %.0f mW; D-BT-SQ at RON 30 mOhm %.0f mW"
          % (nm, ii, R18AWG * 2 * L * ii * 1e3, R18AWG * 2 * L * ii ** 2 * 1e3, R_EVM_BAT * ii ** 2 * 1e3, 0.030 * ii ** 2 * 1e3))
rec("ICHG_MAX_A", {"regen": 3.10 * ICHG_UP, "fc": 1.60 * ICHG_UP})

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
for name, pout, eta in (("FC charge 1.6 A x 8.4 V", 1.6 * 8.4, 0.935), ("regen 3.1 A x 8.4 V (burst)", 3.1 * 8.4, 0.91),
                        ("r5 FC charge at the ICHG upper bound 1.656 A x 8.4 V", 1.656 * 8.4, 0.935), ("r5 regen at the ICHG upper bound 3.21 A x 8.4 V (burst)", 3.2085 * 8.4, 0.91)):
    loss = pout * (1 / eta - 1)
    print("H.14 %s: loss %.2f W, dT_JA %.0f C (JEDEC; EVM copper better)" % (name, loss, loss * RTHJA_BQ))
print("     eFuse 1.80 A worst RON 53 mOhm: %.0f mW" % (0.053 * 1.8 ** 2 * 1e3))

# ======================================================================= H.15  Run-time standby draw (always-powered regen design)
iq = {"eFuse IQ(ON) (EF 6.5)": (1.38e-3, 1.70e-3), "D-BC-RG RT1987 IQ (RT EC p.7)": (0.65e-3, 0.78e-3),
      "CHG_VOLTAGE divider 88.7k at 16 V": (16 / 88.7e3,) * 2, "eFuse UVLO/OVP string": (16 / RT,) * 2,
      "BQ25798 IC, ILIM held, REGN on (UNSPECIFIED; ISD_VBUS 386 uA is HIZ-mode, used as the floor; T-B-04)": (0.39e-3, 1.0e-3),
      "BQ25798 ADC continuous, IBAT+IBUS (adder; battery-side IQ_BAT_ON 540 vs 17-24 uA, DS 6.5; VBUS-side unspecified, T-B-04)": (0.2e-3, 0.52e-3),
      "EVM TS bias from REGN: R18 5.23k + R24 30.1k || R25 10.0k (JP18 in), 5.0 V / 12.74k": (5.0 / 12.74e3,) * 2,
      "REGN pull-ups sinking in armed cruise (R254 Q202 gate, R272 + R272b /CE, r3), 3 x ~0.10 mA": (0.3e-3,) * 2,
      "D107 TVS at U101 IN, IR at 23.6 V / 60 C (selection limit, T-A-05, r3)": (0.0, 0.005e-3),
      "D103 reverse leakage at 16-23.6 V, 60 C (selection target, T-A-05/T-A-07; B340A fallback below)": (0.005e-3, 0.1e-3)}
lo_ = sum(v[0] for v in iq.values()); hi_ = sum(v[1] for v in iq.values())
print("H.15 Run standby draw from VCHG-IN (bus side) while regen-armed:")
for k, v in iq.items():
    print("     %-58s %.3f-%.3f mA" % (k, v[0] * 1e3, v[1] * 1e3))
print("     total %.2f-%.2f mA x 16 V = %.0f-%.0f mW for all of Run (keep-alive option for comparison: 3.5-7 mW)" % (lo_ * 1e3, hi_ * 1e3, lo_ * 16e3, hi_ * 16e3))
print("     B340A fallback worst case (DS13005 IRM 20 mA at 100 C, rated 40 V): up to 20 mA x 16 V = 0.32 W -> does not fit; operator decision if no low-IR part qualifies")
icc3 = {"2 x SN74LVC1G123 active, Rext/Cext 0.5 VCC (MV EC 280 uA max)": 0.56e-3, "6 x TLV3012 (5 uA max each, SBOS300C)": 30e-6,
        "REF dividers (U104, U115, U203 20k) ~3 x 40 uA": 120e-6, "LVC static (ICC 10 uA max each, 8 parts)": 80e-6,
        "R107 10k STAT pull-up while STAT LOW (charging), r5: through EIB R275 1.00k": 3.3 / (10e3 + 1.08e3),
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
print("     r3: QUAL rises on the REGN marker (PG_STAT = 1 or /CE sense HIGH, T1 step 5), so QQ (>= %.0f ms) must cover only poor-source detection (~30 ms typ) and the ILIM ADC read, with >= 50 ms margin (T-B-20): ~%.0f ms margin on typicals" % (mono["QQ"][0], mono["QQ"][0] - 30))

# ======================================================================= H.18  CR placement area budget (finding carrier-no-buildable-layout-reopen)
court = {"U101 VQFN-24 4x4 + vias": 1 * 36, "6 x SOT-23-6 (TLV3012B incl. DNP U117) at ~10 mm2": 6 * 10, "7 x SSOP-8 DCT (3G04, 2x2G32, 2x1G123, 2x2G08) + U118 2G08 at ~15 mm2": 8 * 15,
         "3 x SC70-6 (1G11) at ~7 mm2": 3 * 7, "~79 x 0603/0805 passives at ~4.3 mm2": 79 * 4.3, "r5: 6 x 0402 in the +x pocket (R101, C101, R103, R104, R105, C105) at ~1.9 mm2": 6 * 1.9, "4 x SOT-23 (BAV199 x3, DNP U112 SOT-23-6) at ~10 mm2": 4 * 10,
         "D103 SMA (r5 courtyard 6.6 x 3.1)": 6.6 * 3.1, "J101 SMT 2x7 1.27 mm vertical (r5: courtyard 3.9 x 9.4; the r3 2.54 mm part was 120)": 3.9 * 9.4, "tap field 3 x 8 SMT pads, 2.54 mm (r3: no holes)": 21 * 8,
         "r5: C102a 1206 (4.75 x 2.3) + C102b 1210 (4.75 x 3.2) + D107 TVS SMA (6.6 x 3.1)": 4.75 * 2.3 + 4.75 * 3.2 + 6.6 * 3.1, "r3: W1-W4 plated holes (2.3 mm annulus + 0.5 mm)": 4 * 3.3 ** 2,
         "r3: W6/W7 SMT pads (5 x 1.2 x 1.5 mm + clearance)": 5 * 4}
area = sum(court.values())
top_free = 23.1 * 31.0 + 2 * 2.5 * 33.0     # interior between the pin columns + the two outer strips (approx.)
bot_free_r2 = 31.0 * 33.0 - 11.5 * 5.0 - 2 * 33.0 * 1.9   # minus the bottom keep-out (24.5-36.0 x 48.5-53.5) and the pin columns
# r3 (finding cr-bottom-over-mb-power-traces): bottom-side parts also stay out of the projected MB layer-1 power copper grown by 1 mm
# (.brd: VBT x 34.04-35.56 y <= 48.65 and the y 34.04-35.05 run for x 39.1-47.0; VCHG-IN diagonal (39.6,34.8)-(43.2,38.4) and x 42.42-43.94
#  from y 38.35 to 61.2 and on to pad 10; VCHG pour x 20.14-28.65 y 43.31-49.96; VBT pour x 30.81-34.98 y 48.34-49.76), areas inside the CR
#  outline and outside the keep-out / pin columns (hand-estimated from the coordinates):
mb_power_shadow = {"VBT x 34.04-35.56 (+1 mm), y 34.14-48.5": 3.52 * 14.4, "VBT y 34.04-35.05 run x 39.1-47 (+1 mm), inside the outline": 7.9 * 1.9,
                   "VCHG-IN diagonal (+1 mm)": 5.1 * 3.52, "VCHG-IN x 42.42-43.94 (+1 mm), y 37.35-62.2": 3.52 * 24.85, "VCHG-IN stub to pad 10": 5.0,
                   "VCHG pour (+1 mm) outside the keep-out and pin column": 66.0, "VBT pour (+1 mm) outside the keep-out": 7.0}
bot_free = bot_free_r2 - sum(mb_power_shadow.values())
print("H.18 CR courtyard estimate %.0f mm2 vs top-side free ~%.0f mm2 and bottom-side free (outside the keep-out) ~%.0f mm2 -> %s"
      % (area, top_free, bot_free, "double-sided placement required" if area > top_free else "fits top side"))
passives = 79 * 4.3
print("     r3: bottom free after the MB power-copper shadow (+1 mm) %.0f mm2 (r2 basis %.0f); bottom height cap 1.0 mm -> passives only on the bottom (%.0f mm2);"
      " top carries the rest %.0f mm2 vs %.0f mm2 free -> %s" % (bot_free, bot_free_r2, passives, area - passives, top_free,
      "fits" if (area - passives) <= top_free and passives <= bot_free else "DOES NOT FIT"))
rec("CR_AREA_MM2", dict(courtyard=area, top=top_free, bottom=bot_free, bottom_r2=bot_free_r2, top_needed=area - passives))
# r3: EIB layout budget (finding eib-layout-unbudgeted; 3M N2514 body length UNVERIFIED, T-A-05)
eib = {"J201 2x7 shrouded TH (body ~25 x 9 mm, TODO(verify: 3M N2514 drawing))": 25.4 * 9.0, "U203, U204 SOT-23-6": 2 * 10, "U201 SSOP-8": 15, "U202 SC70-5": 7,
       "Q201-Q203 SOT-23": 3 * 10, "~31 x 0603 passives (r5: + R275)": 31 * 4.3, "2 x M3 hole keep-out (dia 7 mm)": 2 * math.pi * 3.5 ** 2, "8 x E-lead pads (1.0 mm hole, 2.0 mm annulus + clearance)": 8 * 6}
eib_area = sum(eib.values())
for w, h in ((30.0, 22.0), (36.0, 24.0)):
    print("H.18b EIB courtyard estimate %.0f mm2 on %.0f x %.0f mm = %.0f mm2: utilisation %.0f %% (budget <= 70 %% for single-sided hand assembly) -> %s"
          % (eib_area, w, h, w * h, 100 * eib_area / (w * h), "pass" if eib_area / (w * h) <= 0.70 else "FAIL"))
rec("EIB_AREA_MM2", dict(courtyard=eib_area, outline_r3=(36.0, 24.0)))

# ======================================================================= H.19  round-3 r3 additions (review round 3)
print("H.19 Round-3 r3 additions")
# (a) Input-path resistance R_path (finding input-path-ir-drop-omitted). V-MOT = VINDPM (regulated at the BQ25798 VBUS pin) + I_in x R_path.
#     Terms (min, max), ohm. RT1987 RON: 20 mOhm typ at 20 V / 1 A (RT EC p.7, Note 6, no max): hot allowance x1.5 (TEST T-F-13).
#     MB VCHG-IN copper: 1.524 mm x 35 um, ~105 mm main path + two 0.35 mm vias (.brd); 34 mOhm at 20 C, ~39-55 mOhm at 40-60 C incl. vias (reviewer
#     integration 47.8 mOhm); CR copper + pad-10 pin 3-8 mOhm (estimate); eFuse RON 19-53 mOhm (EF EC); W1/W2 round trip 20 mOhm (H.11, includes
#     the W2 return); EVM R2 10 mOhm (UG BOM WSL2010R0100); JP3 soldered link 1-2 mOhm; EVM PGND + MB GND return copper outside W2 5-15 mOhm (estimate).
RP_TERMS = {"D-BC-RG RT1987 RON (typ 20 mOhm, hot x1.5 allowance, TEST)": (0.020, 0.030), "MB VCHG-IN copper + 2 vias, 40-60 C (.brd)": (0.039, 0.055),
            "CR copper + pad-10 pin (estimate)": (0.003, 0.008), "eFuse U101 RON (EF EC)": (0.019, 0.053), "W1/W2 round trip (H.11)": (0.020, 0.020),
            "EVM R2 sense 10 mOhm (UG BOM)": (0.010, 0.010), "EVM JP3 soldered link": (0.001, 0.002), "EVM PGND + MB GND return copper (estimate)": (0.005, 0.015)}
RP = (sum(v[0] for v in RP_TERMS.values()), sum(v[1] for v in RP_TERMS.values()))
RP_FC_EXTRA = 0.0   # D-BC-FC branch: same terms with D-BC-FC RON in place of D-BC-RG; MB path length from D-BC-FC differs (TEST T-F-13 measures it)
for k, v in RP_TERMS.items():
    print("     R_path term %-62s %.0f-%.0f mOhm" % (k, v[0] * 1e3, v[1] * 1e3))
print("     R_PATH_RG = %.0f-%.0f mOhm (regen branch, V-MOT to the BQ25798 VBUS pin and back); drop at 1.1 A %.0f-%.0f mV, at the 1.76 A clamp max %.0f-%.0f mV"
      % (RP[0] * 1e3, RP[1] * 1e3, 1.1 * RP[0] * 1e3, 1.1 * RP[1] * 1e3, 1.76 * RP[0] * 1e3, 1.76 * RP[1] * 1e3))
rec("R_PATH_RG_OHM", RP)
wr3 = {}
for lab, vmax in (("regen-armed cruise (VINDPM 19.0 V, max 19.38 V)", 19.0 * 1.02), ("raised stage 1 (max %.2f V)" % (stage1 * 1.02), stage1 * 1.02)):
    for C in (0.4e-3, 0.97e-3):
        b = (V_CEIL - vmax - I_REGEN_PK * RP[1]) * C / I_REGEN_PK
        wr3["%s|%.2f" % (lab, C * 1e3)] = b * 1e3
        print("     warm budget WITH R_path,max at 1.1 A: %s, C_VMOT %.2f mF: %.2f ms (r2 basis without R_path %.2f ms)"
              % (lab, C * 1e3, b * 1e3, wr["%s|%.2f" % (lab, C * 1e3)]))
rec("WARM_BUDGET_RPATH_MS", wr3)
vmot_max = 19.0 * 1.02 + 1.76 * RP[1]
print("     threshold stack, static: V-MOT max = VINDPM max 19.38 V + 1.76 A x R_path,max = %.2f V; VESC cut 21.35 V margin %.2f V (r2: 1.97 V); stack stays monotone"
      % (vmot_max, VESC_CUT - vmot_max))
print("     false-restore guard (FC image, H1 = 1): V_rgn > VINDPM max + 1.76 A x R_path,max + calibration 0.19 V = %.2f V (r2: 19.57 V)" % (vmot_max + 0.19))
print("     favourable rows left unchanged (conservative): H.7 capability (power at the charger pin), H.1 H1 margins and H.2 UVB margin (V-MOT / bus sit higher by I x R)")
rec("VMOT_STATIC_MAX", vmot_max)

# (b) eFuse IN-side spike at a hard-short turn-off (finding efuse-in-spike-c102-undersized). EF 9.5.1 Eq.14 Vspike = V(IN) + I x sqrt(L(IN)/C(IN));
#     the current at turn-off is higher than I_SCP 45 A because it keeps rising during the 1 us response (EF 6.6). Lumped explicit simulation:
#     source C_S (C-D8 + C-D10 effective 5-20 uF) at V0, R_IN 45 mOhm (MB copper), L_IN (MB trace + vias + pin, 50-150 nH, .brd estimate),
#     node IN with C_IN, FET 31 mOhm, OUT node C103 1 uF, OUT lead 0.15 uH (W1/W2 estimate, H.5) shorted at the EVM J1 end; the FET opens
#     abruptly 1 us after its current crosses 45 A. Ideal (no ESR, no FET linear region): real peaks are expected lower; T-C-04 measures.
def in_spike(v0, cs, lin, cin, rin=0.045, ron=0.031, cout=1.0e-6, lout=0.15e-6, dt=1e-9, tend=12e-6):
    vs, vin, vout = v0, v0, v0
    i_in, i_fet, i_out = 0.0, 0.0, 0.0
    t, t_cross, on, vpk, i_off = 0.0, None, True, v0, 0.0
    vs_pk = -1e9                                 # r6: MB-end (C-D8/C-D10 node = D-BC-RG/D-BC-FC VOUT) peak after the turn-off
    while t < tend:
        di_in = (vs - i_in * rin - vin) / lin
        i_in += di_in * dt
        i_fet = (vin - vout) / ron if on else 0.0
        di_out = vout / lout
        i_out += di_out * dt
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
    if MB_END:
        return vpk, i_off, vs_pk
    return vpk, i_off
MB_END = False
spk = {}
for cin, lab in ((0.1e-6, "r2 C102 100 nF"), (0.7e-6, "1 uF at 23.6 V bias (eff. 0.7 uF)"), (3.4e-6, "r3 C102a 1 uF + C102b 4.7 uF (eff. >= 3.4 uF at 23.6 V)")):
    worst = (0.0, 0.0)
    for v0 in (16.0, 22.0):
        for cs in (5e-6, 20e-6):
            for lin in (50e-9, 150e-9):
                vpk, ioff = in_spike(v0, cs, lin, cin)
                spk["%s|%.0f|%.0fu|%.0fn" % (lab, v0, cs * 1e6, lin * 1e9)] = (vpk, ioff)
                if vpk > worst[0]:
                    worst = (vpk, ioff, v0, cs, lin)
    print("     U101 IN peak at a hard-short turn-off, %s: worst %.0f V (V0 %.0f V, C_S %.0f uF, L_IN %.0f nH, input current at turn-off %.0f A); EF 6.1 abs max 67 V"
          % (lab, worst[0], worst[2], worst[3] * 1e6, worst[4] * 1e9, worst[1]))
rec("EFUSE_IN_SPIKE", {k: v for k, v in spk.items()})
print("     -> local bulk C102a/C102b is the main lever; D107 TVS fitted by default as the backstop (VRWM >= 26 V, VBR min > 23.6 V, Vc < 50 V at the T-C-04 residual current, MPN after T-A-05)")
print("     Run-entry REGEN close inrush with C102a/b/c upstream of the eFuse: %.2f A (board side) + %.2f A (EVM side) = %.2f A vs the H8 1.0 A budget"
      % (C_BOARD_VCHGIN * SR, OUT["EFUSE_INRUSH_A"], C_BOARD_VCHGIN * SR + OUT["EFUSE_INRUSH_A"]))

# (c) /CE pull-up redundancy (finding ce-pullup-link-sense-divider-fails-low): R272 + R272b 47.0k each to REGN.
I_CE = 1e-6 + 10e-6 + 4.8 / 2.0e6        # IIN_BIAS_CE 1 uA max (DS EC), U201 Ioff 10 uA (SCES364J), U204 divider R262 + R263 2.0 MOhm at 4.8 V
for lab, r in (("both fitted (23.5k)", 23.5e3), ("one open (47.0k)", 47.0e3)):
    print("     /CE HIGH with %s: REGN 4.8 V - %.2f V = %.2f V (VIH_CE 1.3 V; U204 trip ~2.5 V)" % (lab, r * I_CE, 4.8 - r * I_CE))
print("     both open: R263 pulls /CE toward 0 V -> U204 reads LOW -> FR-08(b) trips while P5 LOW (announces); draw while U201 sinks /CE: 2 x 4.8/47k = %.2f mA" % (2 * 4.8 / 47e3 * 1e3))

# (d) U117 FCI_OK option values (finding u117-option-values-missing). IN+ = REF x R161/(R160 + R161), R163 hysteresis OUT -> IN+, IN- = FC_CURRENT via R162 10k + C127 10 nF.
R160, R161, R163 = 10.0e3, 1.18e3, 1.00e6
lo, hi = 1e9, -1e9
for vr in (VREF[0], VREF[2]):
    for dt in DT_CR:
        for tcs in (-1, 1):
            for s_ in (-1, 1):
                vref = vr * (1 + tcs * REF_TC * dt)
                v = vref * R161 * (1 + s_ * 0.01) / (R160 * (1 - s_ * 0.01) + R161 * (1 + s_ * 0.01))
                lo, hi = min(lo, v), max(hi, v)
hys = 3.3 * par(R160, R161) / R163
f_lo, f_hi = lo - VOS - VHYS[1] / 2 - hys, hi + VOS + VHYS[1] / 2
print("     U117 option: R160 10.0k / R161 1.18k 1 %% -> %.1f mV nominal (%.1f-%.1f mV before Vos); R163 1.00M adds %.1f mV hysteresis; trip (FCI_OK falls) %.0f-%.0f mV = %.2f-%.2f A at 0.1 V/A; R162 10k + C127 10 nF (tau 100 us)"
      % (VREF[1] * R161 / (R160 + R161) * 1e3, lo * 1e3, hi * 1e3, hys * 1e3, f_lo * 1e3, (f_hi + hys) * 1e3, f_lo / 0.1, (f_hi + hys) / 0.1))
print("     the unselected band reaches OC_FC 1.4 A at its top (Vos +-9 mV = +-0.09 A dominates), so R161 is SELECT-ON-TEST like R142: measure the U117 trip with a mV source"
      " (T-F-04b) and pick R161 for a measured falling trip of 1.30 +-0.03 A; residual drift ~1 mV = 0.01 A over 0-60 C")
rec("U117_TRIP_A", (f_lo / 0.1, (f_hi + hys) / 0.1))

# (e) BT_OK select-on-test R142 (finding btok-selftest-floor-overlap). Falling trip = measured floor + >= 4 mV, rising trip <= 29 mV (R8 bound 0.29 A).
print("     BT_OK R142 select-on-test table (R141 61.9k, REF 1.242 V nominal; the per-part Vos/VHYS are removed by measuring the actual trip in T-C-03):")
for r in (0.604e3, 0.715e3, 0.825e3, 1.00e3, 1.21e3, 1.40e3):
    print("       R142 %.3f k -> nominal REF tap %.1f mV" % (r / 1e3, VREF[1] * r / (R141 + r) * 1e3))
print("     residual drift after selection (dVos/dT ~12 uV/C + REF 100 ppm/C over 0-60 C): ~0.5-1 mV -> selection margin 4 mV at 25 C keeps >= 3 mV at 0/60 C")

# (f) Early purge: bus sag can set H1 with no brake (findings early-purge-sag-asserts-h1, h1-asserts-on-bus-sag)
for vm in (15.2, 15.9):
    print("     V-MOT held at %.1f V on C_VMOT behind D-MT-EN: H1 rises once VBUS < %.2f V (ratio 1.089), above the UVB fall band 12.89-13.78 V" % (vm, vm / 1.089))
for C in (0.4e-3, 0.97e-3):
    print("     V-MOT drain while the FC image runs from V-MOT before P5 LOW lands (0.9 A x 1.5 ms): %.1f V at %.2f mF" % (0.9 * 1.5e-3 / C, C * 1e3))

# ======================================================================= H.20  round-3 r4 additions (review round 4)
print("H.20 Round-3 r4 additions")
# (a) Pre-raise V-MOT race in an FC window (finding fc-window-raise-ignores-governor-floor). After H1 rises, RFC_OFF lifts the FC pin clamp,
#     so the register IINDPM (governor min(0.90 A, G), window open down to G = 0.30 A) is the only absorption limit until T3 lands (FR-07 1.5 ms).
#     Absorbed input current = IINDPM x IINDPM_TOL (EC -12 %); brake current = P / V-MOT; start at the H1 rise max 18.05 V (VBUS 16.39 V).
T_RAISE = 1.5e-3
V_H1R = h1[16.39]["rise_max"]
race = {}
for P in (18.9, 23.0):
    for ii in (0.30, 0.90):
        for C in (0.4e-3, 0.97e-3):
            # integrate dV/dt = (P/V - ii*TOL)/C over T_RAISE
            v = V_H1R; t = 0.0; dt = 1e-6
            while t < T_RAISE:
                v += (P / v - ii * IINDPM_TOL) / C * dt
                t += dt
            race["P%.1f|I%.2f|C%.2f" % (P, ii, C * 1e3)] = v
            print("     pre-raise race: brake %.1f W, IINDPM %.2f A (absorbs %.3f A), C_VMOT %.2f mF: V-MOT %.2f V after %.1f ms (ceiling 20.5 V, cut %.2f V)"
                  % (P, ii, ii * IINDPM_TOL, C * 1e3, v, T_RAISE * 1e3, VESC_CUT))
rec("PRE_RAISE_RACE_V", race)
def i_floor(P, C, t=T_RAISE, vceil=20.5):
    return (P / V_H1R - (vceil - V_H1R) * C / t) / IINDPM_TOL
for P in (18.9, 23.0):
    for C in (0.4e-3, 0.97e-3):
        print("     race-derived IINDPM floor (keeps V-MOT <= 20.5 V for %.1f ms): %.1f W, %.2f mF: %.3f A" % (T_RAISE * 1e3, P, C * 1e3, max(0.0, i_floor(P, C))))
rec("RACE_FLOOR_A", {"18.9W_0.4mF": i_floor(18.9, 0.4e-3), "23W_0.4mF": i_floor(23.0, 0.4e-3)})
# 3 ms r0 budget at 0.90 A / 18.9 W / 0.4 mF (doc correction)
v = V_H1R; t = 0.0
while t < 3e-3:
    v += (18.9 / v - 0.90 * IINDPM_TOL) / 0.4e-3 * 1e-6; t += 1e-6
print("     r0 3 ms budget at 0.90 A / 18.9 W / 0.4 mF: %.2f V (the r3 text said 19.75 V)" % v)
rec("RACE_3MS_V", v)
# false-restore: registers at FC values (0.90 A with the feed-forward) while H1 = 1, starting from the held static max (H.19)
for P in (18.9, 23.0):
    for tdet in (1.0e-3, 2.5e-3):
        v = vmot_max; t = 0.0
        while t < tdet:
            v += (P / v - 0.90 * IINDPM_TOL) / 0.4e-3 * 1e-6; t += 1e-6
        print("     false restore from the held state (V-MOT %.2f V, 0.90 A absorbing, 0.4 mF), %.1f W: %.2f V after %.1f ms (detect + raise)" % (vmot_max, P, v, tdet * 1e3))

# (b) Purge lock tolerance tied to the lead time (finding purge-lock-tolerance-exceeds-tlead)
T_TICK_MAX = 1.0e-3                         # r6 (FR-45): worst timer-domain latency, set by T-C-09; every step boundary costs one
T_EXEC = T_TICK_MAX + 2.0e-3 + T_TICK_MAX   # r6: step-A tick + the 2 ms D wait (B/C writes run inside it) + the step-D boundary tick
                                            # (r5: 1.0 + 0.8 + 2.0 = 3.8 ms summed the B write serially and counted no D-boundary tick)
T_DON_MAX = 16.0e-3                         # 2 x RT1987 tD_ON typ (no max given; T-E-06)
T_ON_PB = 1.4e-3                            # soft-start to the pre-biased bus (H.8)
T_READY = 5.0e-3 + 1.0e-3                   # step E dwell + check
T_HANDOFF_MAX = T_EXEC + T_DON_MAX + T_ON_PB + T_READY
T_MARGIN = 17.6e-3                          # r6: 17.8 -> 17.6 ms so PURGE_EARLY_MAX stays 55 ms with t_exec 4.0 ms
PURGE_EARLY_MAX = T_LEAD - T_HANDOFF_MAX - T_MARGIN
print("     T_HANDOFF_MAX = t_exec %.1f + tD_ON,max %.1f + tON %.1f + step-E dwell/check %.1f = %.1f ms; PURGE_EARLY_MAX = T_LEAD %.0f - %.1f - margin %.1f = %.1f ms"
      % (T_EXEC * 1e3, T_DON_MAX * 1e3, T_ON_PB * 1e3, T_READY * 1e3, T_HANDOFF_MAX * 1e3, T_LEAD * 1e3, T_HANDOFF_MAX * 1e3, T_MARGIN * 1e3, PURGE_EARLY_MAX * 1e3))
print("     latest early onset that still finds D-BT-EN conducting (no step-E dwell): %.1f ms before t_pred; T_LEAD that keeps a 100 ms early tolerance: %.0f ms"
      % ((T_LEAD - (T_EXEC + T_DON_MAX + T_ON_PB)) * 1e3, (0.100 + T_HANDOFF_MAX + T_MARGIN) * 1e3))
rec("PURGE_EARLY_MAX_MS", PURGE_EARLY_MAX * 1e3); rec("T_HANDOFF_MAX_MS", T_HANDOFF_MAX * 1e3)

# (c) OV_BATT nuisance-latch error budget (finding ov-batt-cv-margin-ignores-adc-error). SLUSDV2C 6.5 VREG_ACC at 8.4 V -0.25/+0.65 %;
#     RT1987 VFWD has no minimum (RT EC p.7) -> 0; R13/JP5 drop at the 0.2 A tail -> 0 for the maximum. Teensy reading = pack x (1 + e_ref) + 2 LSB.
LIMIT_V_BATT_MAX = 8.5
LSB_BT = 3.3 * (16.2 + 10) / 10 / 4095
for vreg, code in ((8.40, 0x348), (8.32, 0x340)):
    pmax = vreg * 1.0065
    for e in (0.0, 0.006, 0.01, 0.013):
        rd = pmax * (1 + e) + 2 * LSB_BT
        print("     VREG %.2f V (0x%04X): pack max %.4f V (VFWD 0, lead 0); reference error %.1f %% -> reading max %.4f V vs LIMIT_V_BATT_MAX %.1f V: margin %+.0f mV"
              % (vreg, code, pmax, e * 100, rd, LIMIT_V_BATT_MAX, (LIMIT_V_BATT_MAX - rd) * 1e3))
print("     1 LSB of BT_VOLTAGE = %.2f mV of pack voltage (ADC_VREF 3.3 V nominal, 12-bit, 16.2k/10k); ADC ceiling %.3f V nominal" % (LSB_BT * 1e3, 3.3 * 2.62))
print("     criterion for restoring VREG 8.40 V after T-E-13: 8.4546 x (1 + e_res) + 4.2 mV <= 8.48 V -> e_res <= %.2f %%" % ((8.48 - 0.0042) / 8.4546 * 100 - 100))
rec("OVBATT_PACKMAX", {"8.40": 8.40 * 1.0065, "8.32": 8.32 * 1.0065})

# (d) D107 re-specification (finding d107-tvs-crowbars-vmot-regen): SMBJ33A / SMCJ33A class, catalogue VBR 36.7-40.6 V, Vc 53.3 V at Ipp (T-A-05 confirms)
print("     D107 class SMxJ33A (catalogue, T-A-05): VRWM 33 V, VBR 36.7-40.6 V, Vc 53.3 V at Ipp vs U101 IN abs max 67 V (EF 6.1): margin %.1f V; RT1987 OVP 33 V minimum (no max, RT EC p.7)" % (67 - 53.3))
print("     D-BC-RG OVP latch: tBLK_OVP 512 us typ, latch-off, no restart (RT 17.7): D107 conducts <= ~0.5 ms per event if the OVP trip sits >= 2 V below D107 VBR(min) (T-A-05b)")

# (e) 3V3 feed limiters (finding cr-eib-3v3-feed-unprotected-short): R175 68 ohm 1206 at F07, R176/R177 200 ohm 0603 per ribbon 3V3 conductor
I_CR = 1.82e-3; I_EIB = 0.45e-3
R175, R176 = 68.0, 200.0
v_cr = 3.30 - I_CR * R175
v_eib = v_cr - I_EIB * R176 / 2
v_eib1 = v_cr - I_EIB * R176
print("     R175 %.0f ohm: CR rail %.3f V at %.2f mA; EIB rail %.3f V (both conductors), %.3f V (one open); LVC row 3.0-3.6 V, TLV3012 >= 1.8 V"
      % (R175, v_cr, I_CR * 1e3, v_eib, v_eib1))
print("     dead short of the CR rail: %.1f mA, %.0f mW in R175 (1206 0.25 W); ribbon 3V3 conductor to GND: %.1f mA, %.0f mW in one 200 ohm 0603 (0.1 W); EIB rail short: %.1f mA"
      % (3.3 / R175 * 1e3, 3.3 ** 2 / R175 * 1e3, v_cr / R176 * 1e3, v_cr ** 2 / R176 * 1e3, 2 * v_cr / R176 * 1e3))
print("     C125 10 uF downstream of R175: inrush peak %.0f mA, tau %.2f ms" % (3.3 / R175 * 1e3, R175 * 10e-6 * 1e3))
rec("RAIL_3V3_CR_EIB", (v_cr, v_eib, v_eib1))
# (f) TLV3012B ribbon drivers R264/R265 470 ohm (finding tlv3012-ribbon-driver-short-current; SBOS300C 6.2 short-circuit 10 mA)
print("     U203/U204 ribbon drivers R264/R265 470 ohm: %.1f mA into a conductor-to-GND short (abs max 10 mA); edge tau with ~30 pF cable %.0f ns"
      % (v_eib / 470 * 1e3, 470 * 30e-12 * 1e9))
# (g) pin 22 keeper (finding pin22-adc-keeper-imon-error)
print("     CHG_IIN source impedance R105 27.4k + R129 10.0k = 37.4 kOhm: 1 uA of pad keeper current = %.0f mV = %.0f mA at 0.764 V/A (FR-11 band +-50 mA)" % (37.4, 37.4 / 0.764))
# (h) T18 protection (finding r172-0805-short-dissipation): F101 fuse + R172 33 ohm 1206
print("     T18: F101 (0603 fast fuse, ~50 mA class) + R172 33 ohm 1206: prospective short %.0f mA (%.2f W in R172 until F101 opens); drop at 1.4 mA %.0f mV; KA VCHG min %.2f V (UVLO rise max 3.35 V)"
      % (5.0 / 33 * 1e3, 5.0 ** 2 / 33, 1.4e-3 * 33 * 1e3, vmin - 1.4e-3 * 33))
# (i) wire quantity (finding bom-26awg-wire-quantity): A.4 tap lengths, m
taps = {"T1": 0.15, "T7b": 0.15, "T2": 0.10, "T3": 0.12, "T4": 0.12, "T5": 0.12, "T6": 0.12, "T8": 0.15, "T9": 0.12, "T10": 0.12,
        "T11": 0.15, "T12": 0.15, "T13": 0.15, "T14": 0.15, "T15": 0.15, "T16": 0.15, "T17": 0.15, "T17r": 0.15, "T20": 0.10, "T21": 0.15}
s = sum(taps.values())
print("     26 AWG tap wire: fitted taps %.2f m; + W6 pair 0.60 m + T18/T19 0.20 m = %.2f m; with 50 %% strip/twist allowance %.1f m -> order >= 5 m in two colours" % (s, s + 0.8, (s + 0.8) * 1.5))
rec("WIRE_26AWG_M", s)
# (j) MCU watchdog timeout vs the purge (finding hang-fc-window-purge-reclose-death5)
for twd in (0.100, 0.050):
    print("     RTWDOG %.0f ms: hang-coincident purge fraction ~(t_WDT + T_LEAD)/T_purge = %.1f %% of window hangs; reset precedes stack recovery only if t_WDT + 1 ms < purge duration min %.0f ms: %s"
          % (twd * 1e3, (twd + T_LEAD) / T_PURGE * 100, D_PURGE[0] * 1e3, "yes" if twd + 1e-3 < D_PURGE[0] - 0.02 else "marginal / no (20 ms margin)"))
# (k) eFuse IN-side area (finding efuse-cluster-no-room-at-pad10)
print("     r3 eFuse IN-side pocket (x 44.3-48.2, y 62.9-66.64): %.1f mm2 vs ~45-50 mm2 needed for C102a/b/c + D107 -> r4 re-plan (U101 rotated, J101 1.27 mm)" % (3.9 * 3.74))
print("     r4 freed strip below U101 (x 37-45, y 52.5-61.6) %.0f mm2 for C102a/b/c + D107 (+ the C102b 100 V 1210)" % (8.0 * 9.1))

# ======================================================================= H.21  round-3 r5 additions (review round 5)
print("H.21 Round-3 r5 additions")
# (a) Qualified brake feed-forward threshold I_ff (findings ff-brake-edge-clears-peakhold-on-ripple, gov-cmd-proxy-abs-closes-window-on-brake).
#     A brake whose regen power IINDPM = G >= 0.30 A can absorb before H1/T3 lands needs no feed-forward. Allowed brake power at the 0.30 A floor:
#     P_allow = V_H1R x (0.30 x TOL + (20.5 - V_H1R) x C / T_RAISE). Upper bound on I_ff scales the 12 A command linearly with the H.7 brake
#     powers (18.9 W at 3 -> 1 m/s; 23 W HR1), an ASSUMPTION (regen power ~ |I_cmd| x V_bemf); lower bound = fw v37 HIL 1x current ripple 0.64 A.
I_RIPPLE_MOTOR = 0.64      # A, fw v37 HIL 1x motor-current lock-in maximum (CLAUDE.md fw v37 HIL record)
I_FF = 1.0                 # A, chosen; TODO(calibrate: T-G-02d)
for C in (0.4e-3, 0.97e-3):
    p_allow = V_H1R * (0.30 * IINDPM_TOL + (20.5 - V_H1R) * C / T_RAISE)
    print("     FF threshold: brake power the 0.30 A floor absorbs within %.1f ms at C_VMOT %.2f mF: %.1f W -> I_ff upper bound %.1f A (12 A x P/23 W) / %.1f A (12 A x P/18.9 W);"
          " lower bound ripple %.2f A; chosen I_ff = %.1f A" % (T_RAISE * 1e3, C * 1e3, p_allow, 12 * p_allow / 23.0, 12 * p_allow / 18.9, I_RIPPLE_MOTOR, I_FF))
rec("I_FF_A", I_FF)
# (b) Measurement-gated feed-forward ramp (finding ff-iindpm-step-overlaps-traction-ocfc): IINDPM_next = min(0.90, IINDPM_now + (I_cap - m_ff - I_fc,raw)).
#     Residual bus-side traction decays linearly from I_tr0 to 0 over T_dec (VESC lag unmeasured), charger draw = min(IINDPM in force, 0.89 A FC-image draw),
#     1 kHz monitor, each step in force 0.5 ms after its tick (400 kHz write + read-back), aux 0.15 A, I_cap 1.20 A, m_ff 0.10 A (TODO(calibrate: T-F-04b)).
def ff_ramp(i_tr0, t_dec, i0=0.30, aux=0.15, icap=1.20, mff=0.10, draw=0.89, t_wr=0.5e-3, dt=1e-5, tend=0.03):
    t = 0.0; ii = i0; pend = []; ifc_max = 0.0; tz = None; i_at = {}
    next_tick = 0.0
    while t < tend:
        tr = max(0.0, i_tr0 * (1 - t / t_dec)) if t_dec > 0 else 0.0
        if tr == 0.0 and tz is None:
            tz = t
        for (te, val) in list(pend):
            if t >= te:
                ii = val; pend.remove((te, val))
        ifc = aux + tr + min(ii, draw)
        ifc_max = max(ifc_max, ifc)
        if t >= next_tick:
            tgt = min(0.90, ii + (icap - mff - ifc))
            if tgt - ii >= 0.05 or tgt < ii:
                pend.append((t + t_wr, max(0.0, tgt)))
            next_tick += 1e-3
        if tz is not None:
            for k in (0.78e-3, 2e-3):
                if k not in i_at and t >= tz + k:
                    i_at[k] = ii
        t += dt
    return ifc_max, i_at
ff_rows = {}
for i_tr0 in (0.30, 0.50, 0.65):
    for t_dec in (2e-3, 5e-3, 10e-3):
        ifc_max, i_at = ff_ramp(i_tr0, t_dec)
        ff_rows["%.2f|%.0f" % (i_tr0, t_dec * 1e3)] = (ifc_max, i_at.get(0.78e-3), i_at.get(2e-3))
        print("     FF ramp: residual traction %.2f A decaying over %.0f ms: max I_fc %.3f A (I_cap - m_ff 1.10 A); IINDPM at traction zero + 0.78 ms %.2f A, + 2 ms %.2f A"
              " (race floor 0.448 A at 18.9 W / 0.706 A at 23 W, 0.4 mF)" % (i_tr0, t_dec * 1e3, ifc_max, i_at.get(0.78e-3), i_at.get(2e-3)))
v_rise = (V_H1R - 16.0) * 0.4e-3 / (18.9 / 17.0)
print("     earliest H1 rise after bus traction reaches zero (V-MOT 16.0 -> %.2f V at 18.9 W into 0.4 mF): %.2f ms" % (V_H1R, v_rise * 1e3))
rec("FF_RAMP", ff_rows)
# old r4 behaviour (worked case of the finding): aux + 0.90 A + residual traction
for tr in (0.16, 0.25, 0.36, 0.45, 0.50):
    print("     r4 step to 0.90 A with residual traction %.2f A: I_fc = 0.15 + 0.89 + %.2f = %.2f A (FR-14(d) 1.20 A, OC_FC 1.4 A)" % (tr, tr, 0.15 + 0.89 + tr))
# (c) Brake -> traction reversal: positive command held until IINDPM = min(0.90, G) is ACKed (<= 1 ms, else P5 LOW)
for peak, rip, mar in ((0.50, 0.10, 0.05), (0.30, 0.10, 0.05)):
    G = 1.20 - 0.15 - peak - rip - mar
    print("     reversal: peak-hold %.2f A, ripple %.2f, margin %.2f -> G %.2f A; FC after the ACK = 0.15 + %.2f + %.2f = %.2f A (<= I_cap 1.20); reversal-headroom test aux + 0.90 + peak + ripple = %.2f A -> %s"
          % (peak, rip, mar, G, max(0.30, G), peak, 0.15 + max(0.30, G) + peak, 0.15 + 0.90 + peak + rip, "ok" if 0.15 + 0.90 + peak + rip <= 1.20 else "close the window at BRAKE exit (T5; r6: never an admission term)"))
print("     reversal-headroom test passes only for peak-hold + ripple <= %.2f A (aux 0.15 A): windows with traction close through T5 when the brake ends" % (1.20 - 0.15 - 0.90))
# (d) Independent pre-emption backstop (finding preempt-deadline-outside-completion-token)
T_BARRIER = 1.0e-3
T_BACKSTOP = 85e-3
need = PURGE_EARLY_MAX + T_DON_MAX + T_ON_PB + T_BARRIER + T_EXEC
latest_en = PURGE_EARLY_MAX + T_DON_MAX + T_ON_PB       # BT_BUS EN edge needed no later than t_pred - this
en_edge = T_BACKSTOP - T_BARRIER - T_EXEC
print("     backstop: T_BACKSTOP >= PURGE_EARLY_MAX %.0f + tD_ON,max %.0f + tON %.1f + barrier %.0f + t_exec %.1f = %.1f ms; chosen %.0f ms (margin %.1f ms) < T_LEAD %.0f ms"
      % (PURGE_EARLY_MAX * 1e3, T_DON_MAX * 1e3, T_ON_PB * 1e3, T_BARRIER * 1e3, T_EXEC * 1e3, need * 1e3, T_BACKSTOP * 1e3, (T_BACKSTOP - need) * 1e3, T_LEAD * 1e3))
print("     backstop EN edge at t_pred - %.1f ms vs latest workable t_pred - %.1f ms; age cap since the frozen last onset = median interval %.2f s - T_BACKSTOP = %.3f s"
      % (en_edge * 1e3, latest_en * 1e3, T_PURGE, T_PURGE - T_BACKSTOP))
rec("T_BACKSTOP_MS", T_BACKSTOP * 1e3)
# (e) MCU flash stall vs watchdog (findings rtwdog-50ms-vs-blocking-flash-ops, flash-commit-stalls-hb-and-wdt-in-run). PJRC cores teensy4/eeprom.c:
#     eeprom_write_byte appends a 2-byte entry to one of 63 4 kB sectors; at 2048 entries it erases (cmd 0x20) and rewrites <= 256 entries, each with IRQs masked.
#     Flash timing: Winbond W25Q64JV class tSE max 400 ms, tPP max 3 ms (from memory, TODO(verify: Winbond W25Q64JV datasheet, PJRC T4.1 flash part)).
ADDR = 4276
print("     encoder EEPROM record at %d: sector (%d >> 2) %% 63 = %d; worst commit = sector erase %.0f ms + 256 x %.0f ms = %.2f s with IRQs masked (vs RTWDOG 50 ms, WDOG1 1.0 s)"
      % (ADDR, ADDR, (ADDR >> 2) % 63, 400, 3, 0.400 + 256 * 0.003))
print("     watchdog window: max legitimate stall + margin < t_WDT < purge min %.0f ms - 20 ms - 1 ms = %.0f ms; armed-state stall budget <= min(FR-27 5 ms, tw_HB,min 20 - 2 ms) = 5 ms"
      % (D_PURGE[0] * 1e3, (D_PURGE[0] - 0.021) * 1e3))
# (f) Early-purge rescue vs bus load (finding purge-fc-only-ridethrough-bag-evidence): a rescue close survives a sag <= dV_SCP/(tD_ON,max + tON),
#     i.e. a source-less bus load <= that slope x C_eff. Bags (4 FC-only onsets, aux ~0.02-0.03 A): reactive BT_BUS close held the bus every time.
for c_vm in (0.4e-3, 0.97e-3):
    c_eff = 40e-6 + c_vm
    smax = slope_ok[str(c_vm)]
    print("     rescue load bound at C_VMOT %.2f mF: sag limit %.3f V/ms -> I_load <= %.3f A; aux 0.02 A (an I/C inference below the INA253 floor, r6) -> %.3f V/ms; aux 0.15 A -> %.2f V/ms; window 1.05 A -> %.2f V/ms"
          % (c_vm * 1e3, smax, smax * 1e3 * c_eff, 0.02 / c_eff / 1e3, 0.15 / c_eff / 1e3, 1.05 / c_eff / 1e3))
rec("RESCUE_I_LOAD_MAX_A", {str(c): slope_ok[str(c)] * 1e3 * (40e-6 + c) for c in (0.4e-3, 0.97e-3)})
# (g) T10 FR-08(b) V_chg decay with the charger inhibited and not converting (finding t10-fr08b-proof-relies-on-slow-decay)
for c_eff, i_q in ((30e-6, 4.9e-3), (57e-6, 3.4e-3)):
    print("     V_chg 16.0 -> 9.9 V with C_eff %.0f uF and %.1f mA standby draw: %.0f ms (+ RT1987 turn-off + 2 ms)" % (c_eff * 1e6, i_q * 1e3, c_eff * 6.1 / i_q * 1e3))
rec("VCHG_DECAY_MS", (30e-6 * 6.1 / 4.9e-3 * 1e3, 57e-6 * 6.1 / 3.4e-3 * 1e3))
# (h) EIB R275 1.00 kOhm in series with STAT (findings ribbon-4-5-stat-sink-abs-max, ribbon-adjacent-short-stat-cedrv). SLUSDV2C 6.1 STAT sink 6 mA abs max,
#     6.5 VOL_STAT <= 0.4 V at 5 mA (Rds <= 80 ohm); SCES198N 6.5 VOH >= 2.4 V at -16 mA, VCC 3 V (Rout <= 37.5 ohm); CR rail 3.176 V (H.20).
VCR = 3.176; ROUT = (0.0, 37.5); RDS = (0.0, 80.0); R130, R275, R107 = 100.0, 1000.0, 10e3
for r275 in (0.0, R275):
    imax = VCR / (ROUT[0] + R130 + r275 + RDS[0]); imin = VCR / (ROUT[1] + R130 + r275 + RDS[1])
    vnode = VCR - imax * (ROUT[1] + R130) if r275 else VCR * (RDS[1]) / (ROUT[1] + R130 + RDS[1])
    print("     4-5 short (STAT sinking, CE_DRV HIGH), R275 = %.0f ohm: STAT current %.1f-%.1f mA (abs max 6 mA); ribbon-5 node %.2f V -> U201 1A %.2f V (VIH 2.0 V)"
          % (r275, imin * 1e3, imax * 1e3, vnode, vnode * 47 / 48))
vol6 = VCR * (R275 + RDS[1]) / (R107 + R275 + RDS[1])
print("     normal STAT LOW at pin 6 with R275: %.2f V (i.MX VIL 0.99 V); sink %.3f mA; 3-4 short: pin 6 stuck LOW, R275 limits any STAT-pin current to <= %.1f mA"
      % (vol6, VCR / (R107 + R275) * 1e3, VCR / R275 * 1e3))
rec("STAT_R275", dict(short_mA_max=VCR / (R130 + R275) * 1e3, vol_pin6=vol6))
# (i) IMON ground-offset sensitivity (finding imon-vchg-ground-offset-under-charge-current)
print("     CHG_IIN ground offset: 1/0.764 = %.3f A/V -> 5 mV = %.1f mA, 15 mV = %.1f mA of apparent input current (FR-11 band +-50 mA provisional)" % (1 / 0.764, 5 / 0.764, 15 / 0.764))
# (j) Fallback-2 fused link (finding fallback2-pack-unfused-on-w3-and-bridge-rating)
for r_pack in (0.010, 0.030, 0.060):
    print("     fallback 2 prospective fault current: 8.4 V / (pack DCIR %.0f mOhm + link/lead 10 mOhm) = %.0f A (fuse interrupting rating must exceed it; T-A-05c)" % (r_pack * 1e3, 8.4 / (r_pack + 0.010)))
print("     fuse nominal >= ICHG max %.2f A / 0.75 derating = %.2f A -> >= 5 A class" % (3.2085, 3.2085 / 0.75))
# (k) CR high-y band re-plan (finding efuse-cluster-no-room-at-pad10-reopen): courtyard rectangles (x0, x1, y0, y1), IPC-7351 nominal + 0.25 mm
CR_CY = (18.2, 48.2, 34.64, 66.64)
parts = {"U101": (39.3, 44.3, 61.6, 66.6), "C102c 0603 horiz": (40.3, 43.3, 60.10, 61.55), "C102a 1206 vert": (39.8, 42.1, 55.30, 60.05),
         "R102 0805 vert": (42.65, 44.45, 56.65, 60.05), "C102b 1210 horiz": (39.75, 44.50, 52.05, 55.25), "D107 SMA vert": (36.60, 39.70, 53.40, 60.00),
         "C103 0805 vert": (37.45, 39.25, 63.20, 66.60), "D103 SMA horiz": (30.80, 37.40, 63.50, 66.60), "J101 2x7 1.27 body": (38.55, 42.45, 42.13, 51.53),
         "pocket 6 x 0402 (2 x 3 grid)": (44.3, 48.2, 63.40, 66.64)}
holes = {"W1 VCHGOUT pad 2.3": (30.3, 61.2, 1.15), "W2 GND pad 2.3": (27.7, 61.2, 1.15), "pin 10 pad 1.9": (45.998, 61.944, 0.95), "pin 9 pad 1.9": (45.998, 59.404, 0.95),
         "pin 8 pad 1.9": (45.998, 56.864, 0.95), "pin 7 pad 1.9": (45.998, 54.324, 0.95), "pin 6 pad 1.9": (45.998, 51.784, 0.95), "pin 5 pad 1.9": (45.998, 49.244, 0.95),
         "pin 4 pad 1.9": (45.998, 46.704, 0.95), "pin 3 pad 1.9": (45.998, 44.164, 0.95)}
smt = {"W7 SCL": (26.4, 27.6, 56.75, 58.25), "W7 GND": (28.4, 29.6, 56.75, 58.25), "W7 SDA": (30.4, 31.6, 56.75, 58.25), "W6 TS": (32.4, 33.6, 56.75, 58.25), "W6 GND": (34.4, 35.6, 56.75, 58.25)}
def ov(a, b):
    return min(a[1], b[1]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[2], b[2])
viol = []
names = list(parts)
for i in range(len(names)):
    a = parts[names[i]]
    if a[0] < CR_CY[0] or a[1] > CR_CY[1] + 1e-9 or a[2] < CR_CY[2] or a[3] > CR_CY[3] + 1e-9:
        viol.append("%s outside the courtyard limit" % names[i])
    for j in range(i + 1, len(names)):
        dx, dy = ov(a, parts[names[j]])
        if dx > 1e-9 and dy > 1e-9:
            viol.append("%s overlaps %s" % (names[i], names[j]))
    for hn, (hx, hy, hr) in holes.items():
        cx = min(max(hx, a[0]), a[1]); cy = min(max(hy, a[2]), a[3])
        d = math.hypot(cx - hx, cy - hy) - hr
        if d < 0.5 and not (names[i] == "U101" and hn == "pin 10 pad 1.9" and d >= 0.5):
            viol.append("%s %.2f mm from %s (< 0.5)" % (names[i], d, hn))
    for sn, b in smt.items():
        dx, dy = ov(a, b)
        if dx > -0.5 and dy > -0.5:
            viol.append("%s within 0.5 mm of %s" % (names[i], sn))
print("     r5 CR high-y band: %d courtyards checked against each other, the CR courtyard limit, the pin-3..10 / W1 / W2 pads (>= 0.5 mm) and the W6/W7 pads: %s"
      % (len(parts), "no violation" if not viol else "; ".join(viol)))
regions = {"J101": (37.0, 44.5, 42.13, 51.53), "IN strip": (36.1, 44.55, 52.03, 61.55), "OUT strip": (30.8, 39.3, 62.85, 66.64), "+x pocket": (44.3, 48.2, 63.40, 66.64)}
for a, b in (("J101", "IN strip"), ("IN strip", "OUT strip")):
    ra, rb = regions[a], regions[b]
    gap = max(rb[2] - ra[3], ra[2] - rb[3])
    print("     region gap %s / %s: %.2f mm (rule >= 0.5)" % (a, b, gap))
print("     tap field top y 41.63 -> J101 courtyard start 42.13 (0.50 mm); pocket start y 63.40 vs pin-10 pad edge 62.894 (+0.51 mm); 1x10 body ends y 63.21: no bottom overflow used")
# loop-inductance rule replacing the fixed 3 mm / 5 mm distances (microstrip L ~ mu0 x h x l / w)
MU0 = 4e-7 * math.pi
for nm, h, l, w in (("C102b via L3 over L4 (0.2 mm), 8 mm x 2.5 mm", 0.2e-3, 8e-3, 2.5e-3), ("D103 cathode run on L1 over L2 (0.2 mm), 4 mm x 2.5 mm", 0.2e-3, 4e-3, 2.5e-3),
                     ("same over a 1.1 mm core (L3 over L2)", 1.1e-3, 8e-3, 2.5e-3)):
    print("     added loop inductance %s: %.2f nH (vs the 50-150 nH MB VCHG-IN path / 150 nH W1-W2 lead)" % (nm, MU0 * h * l / w * 1e9))
rec("CR_REGION_VIOLATIONS", viol)


# ======================================================================= H.22  round-3 r6 additions (review round 6)
print("H.22 Round-3 r6 additions")
# (a) VREG corruption by a single-bit address error (finding vreg-corruption-no-fixed-pack-ovp). SLUSDV2C Table 7-15: REG01:02 VREG_10:0, 10 mV/LSB,
#     bits 15:8 at the lower offset (REG01 holds VREG_10:8 in bits 2:0); static image REG02 = 0x40 (8.32 V interim) / 0x48 (8.40 V).
REG01, REG02 = 0x03, 0x40
writes = {0x00: [0x04], 0x03: [0x01, 0x36], 0x05: [0xBE, 0xB6, 0x91], 0x06: [0x00, 0xAA], 0x08: [0x03], 0x09: [0x25], 0x0E: [0x3D],
          0x0F: [0x02, 0x22], 0x10: [0x81, 0x89], 0x11: [0x00], 0x12: [0x04], 0x13: [0x01], 0x15: [0xAA], 0x18: [0x54]}
hits = []
for a0, data in writes.items():
    for b in range(8):
        a = a0 ^ (1 << b)
        for k, byte in enumerate(data if len(data) <= 2 and a0 in (0x03, 0x06) else data[:1] if False else data):
            pass
        if a0 in (0x03, 0x06):           # one 16-bit transaction [hi, lo] with auto-increment
            seq = [(a, data[0]), (a + 1, data[1])]
            r1, r2 = REG01, REG02
            for ad, by in seq:
                if ad == 0x01: r1 = by
                if ad == 0x02: r2 = by
            if (r1, r2) != (REG01, REG02):
                hits.append((a0, a, "[0x%02X 0x%02X]" % tuple(data), (((r1 & 7) << 8) | r2) * 0.01))
        else:
            for by in data:
                r1, r2 = REG01, REG02
                if a == 0x01: r1 = by
                elif a == 0x02: r2 = by
                else: continue
                hits.append((a0, a, "0x%02X" % by, (((r1 & 7) << 8) | r2) * 0.01))
for a0, a, d, v in sorted(set(hits)):
    print("     single-bit address error: write to 0x%02X lands on 0x%02X with %s -> VREG %.2f V%s" % (a0, a, d, max(v, 3.0), "  <-- above the 8.70 V cell-OVP pack level" if v > 8.70 else ""))
print("     BQ25798 VBAT_OVP follows VREG (103-105 %% rising, SLUSDV2C 6.5): at VREG 16.00 V it sits at %.1f-%.1f V, i.e. no independent backstop" % (16.0 * 1.03, 16.0 * 1.05))
rec("VREG_CORRUPTION", [(hex(a0), hex(a), d, v) for a0, a, d, v in sorted(set(hits))])
# (b) BQ29200 OUT -> carrier permit (SLUSA52C 7.5): VPROTECT 4.35 V +-10 mV (25 C) / +-25 mV (0-60 C), VHYS 200-400 mV, XDELAY 5.5-13.5 s/uF,
#     OUT high 1.75 V min at IOH -100 uA and VDD = VPROTECT (only spec'd there), IOL 30-85 uA at OUT 0.05 V, OUT low <= 0.2 V at IOL 100 uA, regulated <= 9.5 V.
#     Input stage: R178 100 kOhm series, D108 BAV199 clamp, R179 1.00 MOhm pull-up to the CR rail 3.176 V, into U123 SN74LVC1G14 (SCES218AA: VT+ 1.5-1.87 V,
#     VT- 0.84-1.14 V at VCC 3 V, DCK).
R178, R179, VRAIL = 100e3, 1.00e6, 3.176
def node(vout):
    return vout + (VRAIL - vout) * R178 / (R178 + R179)
vt_p_max, vt_m_min = 1.87, 0.84
print("     BAL OUT LOW (<= 0.2 V): U123 input %.2f V vs VT- min %.2f V (margin %.2f V); sink %.1f uA vs IOL >= 30 uA"
      % (node(0.2), vt_m_min, vt_m_min - node(0.2), VRAIL / (R178 + R179) * 1e6))
v_need = (vt_p_max - VRAIL * R178 / (R178 + R179)) / (1 - R178 / (R178 + R179))
print("     BAL OUT HIGH: U123 needs >= VT+ max %.2f V -> OUT >= %.3f V; datasheet OUT min 1.75 V (IOH -100 uA, VDD = VPROTECT only): margin %.0f mV at that corner; T-F-17 measures OUT at the 8.7 V pack"
      % (vt_p_max, v_need, (1.75 - v_need) * 1e3))
for vout in (6.0, 8.25, 9.5):
    i = max(0.0, (vout - (VRAIL + 0.6)) / R178)
    print("     BAL OUT %.2f V: BAV199 clamp current %.0f uA into the CR rail (IOH spec -100 uA); input node clamped ~%.2f V" % (vout, i * 1e6, VRAIL + 0.6))
print("     open tap or unpowered BQ29200: R179 pulls the U123 input to %.2f V = OV (fail-safe); T-F-17 measures the unpowered case (OUT ESD path into a floating VDD)" % VRAIL)
td = [0.33 * 0.9 * 5.5, 0.33 * 1.1 * 13.5]   # C in uF x XDELAY in s/uF
print("     response: CBLD 330 nF (+-10 %%) x XDELAY 5.5-13.5 s/uF = %.1f-%.1f s (customer test mode is bench-only; CBLD is not shrunk)" % (td[0], td[1]))
print("     trip: 4.35 V/cell (4.325-4.375 V over 0-60 C) = pack 8.65-8.75 V with balanced cells; legitimate CV max 8.4546 V = 4.227 V/cell -> %.0f mV per-cell imbalance allowance before a nuisance trip"
      % ((4.325 - 8.4546 / 2) * 1e3))
rec("BAL_PERMIT", dict(out_min_needed=v_need, delay_s=td))
# (c) Battery-side copper (finding cr-and-mb-battery-path-copper-sized-below-ichg). IPC-2221 external: I = 0.048 dT^0.44 A^0.725 (A in mil^2).
def ipc2221(w_mm, oz, dT):
    a = (w_mm / 0.0254) * (oz * 1.378)
    return 0.048 * dT ** 0.44 * a ** 0.725
for lab, w, oz in (("CR pour 2.5 mm, 2 oz", 2.5, 2), ("CR fallback r5 1.5 mm, 1 oz", 1.5, 1), ("CR fallback r6 2.0 mm, 1 oz", 2.0, 1), ("MB VBT trace 1.524 mm, 1 oz", 1.524, 1),
                    ("MB VBT trace 1.524 mm, 2 oz", 1.524, 2), ("MB VBT pour neck 1.42 mm, 1 oz", 1.42, 1)):
    print("     IPC-2221 external %s: %.1f A at 10 C rise, %.1f A at 20 C rise (basis ICHG max 3.21 A, design >= 3.5 A)" % (lab, ipc2221(w, oz, 10), ipc2221(w, oz, 20)))
RHO = 1.72e-8
def r_cu(l_mm, w_mm, oz):
    return RHO * l_mm * 1e-3 / (w_mm * 1e-3 * oz * 35e-6)
r1 = r_cu(3.3, 1.42, 1) + r_cu(0.72, 1.524, 1) + r_cu(16.9, 1.524, 1)
r2 = r1 / 2
print("     MB VBT path, D-BT-SQ VOUT pour at x ~31 to the trace at (34.798, 31.75): pour neck 3.3 mm x 1.42 mm + 0.72 mm + 16.9 mm of 1.524 mm trace: %.1f mOhm at 1 oz, %.1f mOhm at 2 oz (20 C);"
      " pass for 'at least 1 oz' R <= %.1f mOhm (+15 %%); dissipation at 3.21 A %.0f mW (1 oz)" % (r1 * 1e3, r2 * 1e3, r1 * 1.15e3, 3.21 ** 2 * r1 * 1e3))
print("     header pins: 3.21 A over the two VBAT+ pins at 60/40 sharing = %.2f A per pin (rating >= 2.0 A each); GND pins 14/15 likewise; pad 10 / pin 4 carry the input side <= 2.41 A" % (0.6 * 3.21))
rec("CU_MB_VBT_MOHM", (r1 * 1e3, r2 * 1e3))
# (d) MB end of the eFuse IN-side spike (finding tc04-in-spike-criterion-omits-mb-vchgin-ratings): same lumped model, tracking C_S (C-D8/C-D10 node = D-BC-RG/D-BC-FC VOUT)
MB_END = True
mb_rows = {}
for cs in (4e-6, 5e-6, 10e-6, 20e-6):
    for lin in (50e-9, 150e-9):
        for v0 in (16.0, 22.0):
            vpk, ioff, vspk = in_spike(v0, cs, lin, 3.4e-6)
            mb_rows["%.0fu|%.0fn|%.0f" % (cs * 1e6, lin * 1e9, v0)] = (vpk, vspk)
            print("     hard short, C102 eff 3.4 uF, C_S %.0f uF, L_IN %.0f nH, V0 %.0f V: U101 IN %.1f V, MB end (C-D8 / RT1987 VOUT) %.1f V (limits 35 V C-D8/C-D10, 40 V RT1987 VOUT abs max); pin 38 %.2f V"
                  % (cs * 1e6, lin * 1e9, v0, vpk, vspk, vspk * 10 / 88.7))
MB_END = False
worst_mb = max(mb_rows.values(), key=lambda x: x[1])
print("     worst MB-end peak %.1f V (U101 IN %.1f V there; the source node is first depleted by the short, so the ring returns it to about V0); lossless two-capacitor bound without that depletion: rise_MB = rise_U101 x C102/C_S (H.5 r6 row); a U101 IN at the 60 V T-C-04 limit would put the MB end near %.0f V"
      % (worst_mb[1], worst_mb[0], 22 + (60 - 22) * 3.4 / 5.0))
rec("MB_END_SPIKE", mb_rows)
for cs in (4e-6, 5e-6, 20e-6):
    ceq = 3.4e-6 * cs / (3.4e-6 + cs)
    A = 65.0 * math.sqrt(150e-9 / ceq)
    print("     undepleted lossless bound (verifier model; a stiff V-MOT/CAL source behind D-BC-RG keeps C_S near V0): I0 65 A, 150 nH, C102 3.4 uF, C_S %.0f uF, V0 22 V: U101 IN %.1f V, MB end %.1f V"
          % (cs * 1e6, 22 + A * cs / (3.4e-6 + cs), 22 + A * 3.4e-6 / (3.4e-6 + cs)))
print("     snubber fail branch: R_SN ~ sqrt(L_IN / C_eq) = %.2f-%.2f ohm (50-150 nH, C_eq ~2 uF), C_SN >= 3 x 3.4 uF = 10 uF (100 V)" % (math.sqrt(50e-9 / 2e-6), math.sqrt(150e-9 / 2e-6)))
# (e) Pins 38/39 behind the MB 78.7k / 10k dividers (finding pin38-39-adc-overvoltage-on-vmot-excursion)
K_DIV, R_TH = 10.0 / 88.7, 1 / (1 / 78.7e3 + 1 / 10e3)
print("     pins 38/39: ratio %.5f, Thevenin %.2f kOhm; pin at 3.30 V when the source is %.1f V; at 3.6 V when %.1f V" % (K_DIV, R_TH / 1e3, 3.3 / K_DIV, 3.6 / K_DIV))
for vs in (29.3, 33.0, 36.0, 40.0):
    vth = vs * K_DIV
    print("       source %.1f V: open-circuit pin %.2f V; injection into a 3.3 V + 0.3 V clamp %.0f uA (the r6 finding's 0.3-0.4 mA omitted the 10 k bottom leg)" % (vs, vth, max(0.0, (vth - 3.6) / R_TH) * 1e6))
print("     BAV199 clamp fallback at the pin: leakage <= 5 nA (TODO(verify: Nexperia BAV199)) x 8.87 kOhm = %.0f uV of error" % (5e-9 * R_TH * 1e6))
# (f) Timing budgets with the timer domain (finding loop-budget-5ms-breaks-1ms-tick-deadlines)
print("     T_TICK_MAX %.1f ms (timer domain, T-C-09): t_exec = %.1f ms, T_HANDOFF_MAX = %.1f ms, PURGE_EARLY_MAX = %.1f ms (margin %.1f ms), T_BACKSTOP >= %.1f ms (chosen 85), backstop EN edge t_pred - %.1f ms"
      % (T_TICK_MAX * 1e3, T_EXEC * 1e3, T_HANDOFF_MAX * 1e3, PURGE_EARLY_MAX * 1e3, T_MARGIN * 1e3, (PURGE_EARLY_MAX + T_DON_MAX + T_ON_PB + T_BARRIER + T_EXEC) * 1e3, (T_BACKSTOP - T_BARRIER - T_EXEC) * 1e3))
for tt in (1.0e-3, 2.0e-3, 5.0e-3):
    te = tt + 2.0e-3 + tt
    pem = T_LEAD - (te + T_DON_MAX + T_ON_PB + T_READY) - T_MARGIN
    print("       if T-C-09 measures T_TICK_MAX %.0f ms: t_exec %.1f ms -> PURGE_EARLY_MAX %.1f ms (static_assert re-derives it; 5 ms = the r5 loop budget used as a tick)" % (tt * 1e3, te * 1e3, pem * 1e3))
# FR-41(vii) hold: write ACK vs write + read-back at 100 / 400 kHz with the 0.5 / 0.35 ms transaction already in flight
for f, inflight in ((100e3, 0.5e-3), (400e3, 0.35e-3)):
    wr, rb = 38 / f, 47 / f
    print("     reversal hold at %.0f kHz: in-flight %.2f ms + IINDPM write %.2f ms = ACK at %.2f ms; + read-back %.2f ms = %.2f ms" % (f / 1e3, inflight * 1e3, wr * 1e3, (inflight + wr) * 1e3, rb * 1e3, (inflight + wr + rb) * 1e3))
# (g) Early-purge rescue predicate without the fixed floor (finding purge-fc-only-ridethrough-bag-evidence-reopen)
T17 = T_DON_MAX + T_ON
V_BT_EST = 16.0
SAG_FLOOR = 0.005     # V/ms: ~2 LSB of V_bus (4.55 mV) over the 2 ms slope window; provisional until T-E-01 / T-E-04
dvs = OUT["RESCUE_DV_SCP"]
for c_vm in (0.4e-3, 0.97e-3):
    rhs = max(12.0, V_BT_EST - dvs[str(c_vm)])
    print("     C_VMOT %.2f mF: RHS max(12.0, V_BT_est %.1f - dV_SCP %.2f) = %.2f V; static_assert SAG_FLOOR %.3f V/ms x %.1f ms = %.3f V < dV_SCP %.2f V: %s; r5 floor 0.2 V/ms alone predicted %.2f V"
          % (c_vm * 1e3, V_BT_EST, dvs[str(c_vm)], rhs, SAG_FLOOR, T17 * 1e3, SAG_FLOOR * T17 * 1e3, dvs[str(c_vm)], "holds" if SAG_FLOOR * T17 * 1e3 < dvs[str(c_vm)] else "FAILS", 0.2 * T17 * 1e3))
    for lab, vb, sl in (("(a) V_fc-onset class, V_bus 15.8 V, post-shed 0.02 V/ms", 15.8, 0.02), ("(b) V_bus 15.8 V, 1.04 V/ms (1.05 A)", 15.8, 1.04),
                        ("(c) H2c class at V_bus 14.16 V, slope 0", 14.16, 0.0), ("r5 predicate (0.2 V/ms floor), V_bus 16.0, slope 0", 16.0, 0.2)):
        lhs = vb - max(sl, SAG_FLOOR if not lab.startswith("r5") else 0.2) * T17 * 1e3
        print("       %s: LHS %.2f V -> %s" % (lab, lhs, "admit" if lhs >= rhs else "refuse"))
for vmin in (12.89, 14.62):
    print("     bag rescue close delta V_BT_est - V_bus,min = %.2f V vs the dV_SCP no-trip bound 1.11 / 2.56 V: %s"
          % (V_BT_EST - vmin, "exceeds both (bags did not latch: dV_SCP model pessimistic or SCP gaps unseen at 50 Hz, T-F-07b)" if V_BT_EST - vmin > 2.56 else "exceeds the 0.97 mF bound"))
# (h) FCC/RGN taps through comparators (finding fcc-rgn-lvc-threshold-vs-rt1987-en-band). U119 FCC_OFF = U115 network (REF/3); U120 FCC_ON / U121 RGN_ON:
#     IN+ = tap x R_b/(R_a + R_b), R_a 453 kOhm, R_b 1.00 MOhm (1 %), IN- = own REF. FCC tap pull-up R187 3.30 MOhm to the CR rail (R134 DNP); RGN keeps R133 100 kOhm.
RA, RB, RPU = 453e3, 1.00e6, 3.30e6
lo, hi = 1e9, -1e9
for vr in (VREF[0], VREF[2]):
    for dt in DT_CR:
        for tcs in (-1, 1):
            for s_ in (-1, 1):
                vref = vr * (1 + tcs * REF_TC * dt)
                k = RB * (1 - s_ * 0.01) / (RA * (1 + s_ * 0.01) + RB * (1 - s_ * 0.01))
                for vos in (-VOS, VOS):
                    for vh in (0.0, VHYS[1]):
                        v = (vref + vos + vh) / k
                        lo, hi = min(lo, v), max(hi, v)
print("     FCC_ON / RGN_ON trip at the EN net: %.3f-%.3f V (nominal %.3f V) vs RT1987 VEN_R max 1.4 V: margin %.2f V; TPD 2-4 us (SBOS300C 6.10)"
      % (lo, hi, VREF[1] * (RA + RB) / RB, lo - 1.4))
REN = (475e3, 985e3); RDIV = RA + RB
def par2(*r): return 1 / sum(1 / x for x in r)
print("     FCC tap open: node %.2f V -> FCC_OFF reads 'may be on' (> 0.44 V), FCC_ON reads off (< %.2f V)" % (VRAIL * RDIV / (RPU + RDIV), lo))
lows = [par2(rp, RDIV) for rp in REN]
print("     FCC tap connected, pin 31 high-Z, 10 kOhm bodge open: EN %.2f-%.2f V (< VEN_F min 0.6 V; FCC_OFF may read 'may be on': safe)"
      % (min(VRAIL * l / (RPU + l) for l in lows), max(VRAIL * l / (RPU + l) for l in lows)))
for pin, extra in (("31 (FCC)", [10e3, RDIV, 730e3, RPU]), ("30 (RGN)", [10e3, 100e3, RDIV, 730e3])):
    rl = par2(*[r for r in extra if r != RPU])
    v = 3.3 * rl / (22e3 + rl)
    print("     pin %s left INPUT_PULLUP (~22 kOhm pad): EN %.2f V -> FCC_OFF/FCC_ON/RGN_ON all read the safe value (FCC_OFF 0, FCC_ON 0, RGN_ON 0)" % (pin, v))
print("     FCC_OFF (U119) threshold = U115 network: REF/3 0.39-0.44 V; the R187 3.30 MOhm current through R186 10.0 kOhm lifts IN- by %.0f mV" % (3.3 / 3.3e6 * 10e3 * 1e3))
rec("FCC_RGN_ON_TRIP_V", (lo, hi))
# (i) EIB placement re-derived (finding eib-e-lead-max-lengths-geometrically-infeasible): SLUUCB5E Fig 4-1 rendered at 150 dpi, 8.66 px/mm from the J8 pitch
#     (22 px per 2.54 mm), positions read from the render (+-2 mm). EIB pad column 7 mm off the EVM right edge (x = 1017 px).
PXMM = 22 / 2.54
evm = {"TP49": (970, 308), "TP33": (941, 441), "JP21 pin 1": (902, 408), "JP14 pin 2": (869, 432), "TP38": (822, 474), "TP27": (490, 300),
       "JP12 REGN pin": (598, 862), "TP36": (740, 812), "JP17 /CE pin": (727, 752)}
x_pad = 1017 + 7 * PXMM; y3 = 398.0
order = ["E8", None, "E3", "E4", "E2", None, "E7", None, "E1", None, "E5", "E6"]
target = {"E8": ["TP49"], "E3": ["TP33"], "E4": ["JP21 pin 1"], "E2": ["JP14 pin 2"], "E7": ["TP38"], "E1": ["JP12 REGN pin", "TP27"], "E5": ["TP36"], "E6": ["JP17 /CE pin"]}
crit = {"E3": "length-critical (ILIM hold node)", "E4": "length-critical (far-end sense, 10 MOhm pull-up)", "E6": "length-critical (far-end sense, 1 MOhm divider)",
        "E8": "length-critical (ground reference)", "E2": "semi-critical (48.7 kOhm release feed)", "E1": "static (REGN supply, 100 nF at the EIB)",
        "E5": "static (/CE drive, open drain)", "E7": "static (STAT, R275)"}
eib_len = {}
for i, e in enumerate(order):
    if e is None: continue
    y = y3 + (i - 2) * 2.54 * PXMM
    best = min(((math.hypot(x_pad - evm[t][0], y - evm[t][1]) / PXMM, t) for t in target[e]))
    mx = 5 * math.ceil(best[0] * 1.25 / 5)
    eib_len[e] = (best[1], best[0], mx)
    print("     EIB position %2d %s -> %-13s straight %.1f mm, build maximum %d mm (x1.25, rounded up to 5 mm), %s" % (i + 1, e, best[1], best[0], mx, crit[e]))
rec("EIB_LEADS_MM", eib_len)
# (j) chg_src difference channel (finding chg-src-misattributes-subh1-regen-reopen): V_rgn - V_bus with a single scalar offset learned at 16 V
for g_err in (0.15, 0.01):
    print("     V_rgn gain error %.0f %%: a scalar offset learned at 16.0 V leaves %.0f mV at 14.2 V and %.0f mV at 17.5 V (LSBs 7.15 / 4.55 mV); an offset + slope fit removes it" % (g_err * 100, g_err * 1.8 * 1e3, g_err * 1.5 * 1e3))
print("     D-MT-EN stays in VFWD regulation (baseline valid) while I x RON < VFWD: 35 mV / 20 mOhm = %.2f A typ (RON and VFWD typical only, RT1987 DS-00 17.6)" % (0.035 / 0.020))
# (k) CR area re-booked (r6: U119-U121 SOT-23-6, U122 SC70-5 1G08, U123 SC70-5 1G14, D108 SOT-23, 16 passives; R134 DNP)
add_ic = 3 * 10 + 2 * 7 + 10
add_pas = 16 * 4.3 - 4.3
print("     H.18 r6 re-book: + ICs %.0f mm2 (top) + passives %.0f mm2 (bottom): courtyard ~%.0f mm2; top ~%.0f of %.0f mm2, bottom ~%.0f of %.0f mm2"
      % (add_ic, add_pas, OUT["CR_AREA_MM2"]["courtyard"] + add_ic + add_pas, OUT["CR_AREA_MM2"]["top_needed"] + add_ic, OUT["CR_AREA_MM2"]["top"], 79 * 4.3 + add_pas, OUT["CR_AREA_MM2"]["bottom"]))
rec("CR_AREA_R6_MM2", OUT["CR_AREA_MM2"]["courtyard"] + add_ic + add_pas)
# (l) D-BT-SQ short detection (finding dbtsq-short-unfused-pack-on-vchg): VCHG decays below the RT1987 UVLO in 0.17-0.66 s with D-BT-SQ healthy (H.9)
print("     D-BT-SQ short check: healthy VCHG < 3 V within <= 0.78 s of cruise (H.9) or of Idle; shorted VCHG = V_batt +- 0.2 V -> separable by > 4 V (keep-alive holds <= 4.46 V)")

# ======================================================================= register encodings
def enc(v, lsb):
    return int(round(v / lsb))
print("REG  VINDPM 19.0 V = 0x%02X, %.1f V (stage 1) = 0x%02X, 14.5 V = 0x%02X (REG05, 100 mV/LSB); IINDPM 1.70 A = 0x%04X, 0.90 A = 0x%04X (REG06, 10 mA/LSB); "
      "ICHG 3.10 A = 0x%04X, 2.50 A = 0x%04X, 1.60 A = 0x%04X (REG03, 10 mA/LSB); VREG 8.40 V = 0x%04X, 8.32 V (r4 interim) = 0x%04X"
      % (enc(19.0, 0.1), stage1, enc(stage1, 0.1), enc(14.5, 0.1), enc(1.70, 0.01), enc(0.90, 0.01), enc(3.10, 0.01), enc(2.50, 0.01), enc(1.60, 0.01), enc(8.40, 0.01), enc(8.32, 0.01)))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "r3_calc_out.json"), "w") as fh:
    json.dump(OUT, fh, indent=1, default=str)
