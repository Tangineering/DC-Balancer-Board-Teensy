# Calculations for sec_schematic.md ([DS] = BQ25798 SLUSDV2C; round-3 values cited in the doc)
#
# [DS] equation labels, read from the printed PDF pp.133-134 (the labels in the right margin):
#   Eq 4  I_SAT >= max(I_IN + I_RIPPLE/2, I_CHG + I_RIPPLE/2)          (8.2.2.2)
#   Eq 5  I_RIPPLE_BUCK  = VSYS (VBUS - VSYS) / (VBUS FSW L)            (8.2.2.2)
#   Eq 6  I_RIPPLE_BOOST = VBUS (VSYS - VBUS) / (VSYS FSW L)            (8.2.2.2)
#   Eq 7  I_CIN_BUCK     = I_CHG sqrt(D (1 - D)),  D = VSYS / VBUS     (8.2.2.3)
#   Eq 8  dV_IN_BUCK     = D (1 - D) I_CHG / (C_IN FSW)                (8.2.2.3)
# The [DS] prose cites these one number low ("equations (4) and (5)" for the two ripple equations,
# "equation (6)" / "(7)" for the RMS current and the voltage ripple). The citations below follow the printed labels.
#
# Revision 2026-11-10 (review run 001): CCB-R1-07 / NP-7 (Eq 7 and Eq 8 on a VBUS sweep that includes D = 0.5),
# CCB-R1-03 (inductor peak, PFM and 2 A floors, OCP thresholds, saturation criterion),
# CCB-R1-04 (time constants and coupling bounds at the high-impedance comparator inputs N_FNP, N_RNP, N_CSP).
import math

ICHG_MAX = 3.21          # A, regen image 3.10 A + 3.5 % ([WD] A.3)
VSYS_MAX = 8.82          # V, VBAT_OVP 105 % of 8.40 V ([DS] EC p.12)
F_HI, L_HI = 1.5e6, 1.0e-6
F_LO, L_LO = 0.75e6, 2.2e-6


def rip_buck(vin, vsys, f, L):            # [DS] Eq 5
    return vsys * (vin - vsys) / (vin * f * L)


print("Inductor ripple / peak (buck, [DS] Eq 5, Eq 4)")
for f, L, lab in [(F_HI, L_HI, "1.5MHz 1.0uH"), (F_LO, L_LO, "750kHz 2.2uH")]:
    for vin in (16.0, 21.5, 22.28, 23.63):
        for vsys in (8.4, 8.82):
            for ltol in (1.0, 0.8):
                r = rip_buck(vin, vsys, f, L * ltol)
                for ichg in (3.10, 3.21):
                    print(f"{lab} vin={vin} vsys={vsys} Lx{ltol} rip={r:.3f} App ichg={ichg} pk={ichg+r/2:.3f}")

# ---------------------------------------------------------------------------------------------------------------
print()
print("PMID ripple current, [DS] Eq 7: ICIN = ICHG sqrt(D(1-D)), D = VSYS/VBUS (buck)")
print("VBUS sweep: 12.0 (T-K-07 low), 14.5 (FC VINDPM), 16.0, 2 x VSYS, 19.0, 21.5, 22.28, 23.63 (eFuse OVP max)")
sweep = sorted({12.0, 14.5, 16.0, 16.8, 17.64, 19.0, 21.5, 22.28, 23.63})
icin_max = 0.0
for vsys in (8.4, VSYS_MAX):
    for vin in sweep:
        D = vsys / vin
        k = math.sqrt(D * (1 - D))
        for ichg in (3.10, ICHG_MAX):
            icin = ichg * k
            icin_max = max(icin_max, icin)
            print(f"  vsys={vsys} vbus={vin:6.2f} D={D:.4f} sqrt(D(1-D))={k:.4f} ichg={ichg} ICIN={icin:.3f} A rms"
                  f"  per cap (3 x 10 uF, equal share)={icin/3:.3f} A")
print(f"  maximum ICIN = ICHG/2 at D = 0.5 (VBUS = 2 x VSYS = 16.80 V / 17.64 V): {ICHG_MAX/2:.4f} A rms total,"
      f" {ICHG_MAX/6:.3f} A per capacitor; swept maximum {icin_max:.4f} A")
print(f"  previous published value 1.57 A (21.5 V, VSYS 8.4 V row): understatement "
      f"{(ICHG_MAX/2 - 3.21*math.sqrt((8.4/21.5)*(1-8.4/21.5)))/(ICHG_MAX/2)*100:.1f} %")

print()
print("PMID voltage ripple, [DS] Eq 8: dVIN = D(1-D) ICHG / (CIN FSW); CIN effective 4 / 10 / 15 uF")
for f in (F_HI, F_LO):
    for c in (4e-6, 10e-6, 15e-6):
        row = []
        for vin in (16.0, 2 * VSYS_MAX, 21.5, 23.63):
            D = VSYS_MAX / vin
            row.append(f"{vin:.2f}V:{D*(1-D)*ICHG_MAX/(c*f)*1e3:.1f}")
        dmax = 0.25 * ICHG_MAX / (c * f)
        old = (8.4 / 21.5) * (1 - 8.4 / 21.5) * ICHG_MAX / (c * f)
        print(f"  fsw={f/1e6:.2f} MHz C={c*1e6:.0f} uF  mV p-p at " + "  ".join(row) +
              f"  | D=0.5 max {dmax*1e3:.1f} mV (old D=8.4/21.5 value {old*1e3:.1f} mV, {(dmax-old)/dmax*100:.1f} % low)")

# ---------------------------------------------------------------------------------------------------------------
print()
print("L501 current requirement (CCB-R1-03)")
VIN_W = 23.63
pk_w = ICHG_MAX + rip_buck(VIN_W, VSYS_MAX, F_HI, 0.8 * L_HI) / 2
print(f"  [DS] Eq 4 worst peak (23.63 V, VSYS 8.82 V, 0.8 uH, 1.5 MHz): {pk_w:.3f} A; 6.5 A floor margin {6.5/pk_w:.3f}")
print("  [DS] 8.2.2.2 floor: Isat >= 2 A (PFM pulses); [DS] 7.3.6.4 PFM peak limit 2 A (OOA enabled) / 3.3 A (OOA disabled)")
print("  [DS] 7.3.13.1.5 VSYS_SHORT 2.1-2.3 V (EC): converter output current < 1 A")
# IBUS_OCP is an input-current threshold. In buck mode the average inductor current is I_IN / D.
for vin in (14.5, 16.0, 23.63):
    D = VSYS_MAX / vin
    print(f"  IBUS_OCP 7.0 / 9.0 A ([DS] EC p.9) at VBUS {vin} V (D={D:.3f}) maps to average I_L {7.0/D:.1f} / {9.0/D:.1f} A")
print("  -> IBUS_OCP cannot act before the average inductor current exceeds 11.5 A in buck operation; in boost operation")
print("     (not reached, eFuse UVLO 9.70 V > VSYS 8.82 V) I_L = I_IN and IBUS_OCP would bound it at 7.0-9.0 A average")
print("  IBAT_OCP 9.3 A ([DS] EC p.12, 7.3.13.1.7): SFET discharge path only (SFET omitted, D6); not an L501 current")

print("  Self-consistent peak: L at the peak = 0.8 uH (-20 % tolerance) x (1 - dL_sat)")
for dl in (0.0, 0.10, 0.125, 0.20, 0.30):
    Lpk = 0.8e-6 * (1 - dl)
    pk = ICHG_MAX + rip_buck(VIN_W, VSYS_MAX, F_HI, Lpk) / 2
    print(f"    1.5 MHz: dL_sat {dl*100:4.1f} %  L {Lpk*1e6:.3f} uH  Eq 4 peak {pk:.3f} A")
for dl in (0.0, 0.125, 0.30):
    Lpk = 0.8 * L_LO * (1 - dl)
    pk = ICHG_MAX + rip_buck(VIN_W, VSYS_MAX, F_LO, Lpk) / 2
    print(f"    750 kHz: dL_sat {dl*100:4.1f} %  L {Lpk*1e6:.3f} uH  Eq 4 peak {pk:.3f} A")
L_FLOOR = 0.70e-6
pk_floor = ICHG_MAX + rip_buck(VIN_W, VSYS_MAX, F_HI, L_FLOOR) / 2
print(f"  Proposed criterion: L >= 0.70 uH at 6.5 A and T_max, at the -20 % tolerance limit. Eq 4 peak at 0.70 uH:"
      f" {pk_floor:.3f} A; margin 6.5 / {pk_floor:.3f} = {6.5/pk_floor:.3f}")
print(f"  Equivalent on a typical (nominal 1.0 uH) vendor curve: L_typ(6.5 A, T_max) >= {0.70/0.8:.3f} uH,"
      f" i.e. dL <= {(1-0.70/0.8)*100:.1f} %")
L_FLOOR_LO = 0.70 * L_LO / 1.0
pk_floor_lo = ICHG_MAX + rip_buck(VIN_W, VSYS_MAX, F_LO, L_FLOOR_LO) / 2
print(f"  750 kHz alternate, same rule scaled: L >= {L_FLOOR_LO*1e6:.2f} uH at 6.5 A; Eq 4 peak {pk_floor_lo:.3f} A")

# ---------------------------------------------------------------------------------------------------------------
print()
print("High-impedance comparator inputs (CCB-R1-04)")
# TLV3012B constants as used by round 3 (calc/r3_calc.py lines 45-50, from SBOS300C 6.9 / 6.10; the
# SBOS300C PDF is not in references/): REF 1.223 / 1.242 / 1.260 V at 25 C, 100 ppm/C, carrier dT 0..45 C,
# Vos 9 mV, internal hysteresis 2-8 mV, propagation delay 2-4 us.
REF_LO, REF_NOM, REF_HI, TC, DT, VOS, VHYS = 1.223, 1.242, 1.260, 100e-6, 45.0, 0.009, 0.008
trip_min = REF_LO * (1 - TC * DT) - VOS             # lowest IN+ level that can switch the output HIGH
trip_max = REF_HI * (1 + TC * DT) + VOS + VHYS      # highest IN+ level that may be needed to switch it HIGH
fall_min = REF_LO * (1 - TC * DT) - VOS             # lowest IN+ level at which a falling input releases
print(f"  IN+ trip band {trip_min:.4f}-{trip_max:.4f} V (REF tolerance, drift 45 C, Vos, VHYS)")


def par(*r):
    return 1 / sum(1 / x for x in r)


R_DRV = 1.0e3   # R321 / R322 series from the EN tap; Teensy output impedance neglected
nodes = {
    "N_FNP / N_RNP (R388/R390 453k, R389/R391 1.00M), tap driven": (par(453e3 + R_DRV, 1.00e6), 1.00e6 / (1.00e6 + 453e3 + R_DRV)),
    "N_FNP, FCC tap open (R387 3.30M + R386 10k pull-up)": (par(453e3 + 3.31e6, 1.00e6), None),
    "N_RNP, RGN tap open (R333 100k pull-down)": (par(453e3 + 100e3, 1.00e6), None),
    "N_CSP (R462/R463 1.00M/1.00M), /CE at R472||R472b 23.5k": (par(1.00e6 + par(47e3, 47e3), 1.00e6), 0.5),
}
for name, (rth, k) in nodes.items():
    print(f"  {name}: R_th {rth/1e3:.1f} kOhm; tau unfiltered (Cn 3 / 5 / 10 pF) "
          f"{rth*3e-12*1e6:.2f} / {rth*5e-12*1e6:.2f} / {rth*10e-12*1e6:.2f} us; tau with 100 pF {rth*100e-12*1e6:.1f} us;"
          f" with 1 nF {rth*1e-9*1e6:.0f} us")

k_en = 1.00e6 / (1.00e6 + 453e3 + R_DRV)
v_low = 0.010 * k_en                   # EN driven LOW ~10 mV ([WD] B.2)
v_hi_min, v_hi_max = 3.0 * k_en, 3.3 * k_en   # EN driven HIGH > 3 V ([WD] B.2); 3.3 V rail
m_low = trip_min - v_low
m_high = v_hi_min - trip_max
print(f"  U320/U321 IN+ levels: EN LOW {v_low*1e3:.1f} mV, EN HIGH {v_hi_min:.3f}-{v_hi_max:.3f} V (k = {k_en:.5f})")
print(f"  Static noise margin at IN+: LOW state (false FCC_ON/RGN_ON, unsafe side) {m_low:.3f} V;"
      f" HIGH state (false drop, safe side) {m_high:.3f} V")
print(f"  Proposed T-K-09 (5) limit (50 % of the static margin): LOW {m_low/2:.2f} V pk, HIGH {m_high/2:.2f} V pk"
      f" at N_FNP / N_RNP; the 2-8 mV internal hysteresis is not a usable margin")
ce_hi = 4.49 * 0.5          # /CE HIGH >= 4.49 V ([WD] H.19) through R462/R463 1:1
print(f"  U404: /CE HIGH >= 4.49 V -> N_CSP >= {ce_hi:.3f} V; HIGH-state margin {ce_hi - trip_max:.3f} V;"
      f" LOW-state margin needs the /CE LOW level (TODO(measure: T-K-10))")

# Capacitive coupling from SW1 (buck: SW1 swings 0..VBUS; SW2 static at VSYS in buck)
print("  Coupling capacitance from SW1 needed for a false FCC_ON / RGN_ON (LOW state), node capacitance Cn:")
D_min = VSYS_MAX / 23.63
for dv in (23.63, 27.0):
    for cf in (0.0, 100e-12):
        out = []
        for cn in (3e-12, 5e-12, 10e-12):
            ct = cn + cf
            c_edge = m_low * ct / (dv - m_low)                 # single edge after a quiet interval (PFM burst start)
            c_ccm = (m_low / (1 - D_min)) * ct / (dv - m_low / (1 - D_min))   # AC-coupled CCM square, duty D
            out.append(f"Cn {cn*1e12:.0f} pF: edge {c_edge*1e12:.2f} / CCM {c_ccm*1e12:.2f} pF")
        print(f"    dV {dv} V, C_filter {cf*1e12:.0f} pF: " + "; ".join(out))
t_on_ccm = D_min / F_HI
t_on_pfm = 1.0e-6 * 3.3 / (23.63 - VSYS_MAX)
print(f"  SW1 HIGH time: CCM D/f = {t_on_ccm*1e9:.0f} ns at 23.63 V; PFM to 3.3 A at 1.0 uH = {t_on_pfm*1e9:.0f} ns;"
      f" against the 2-4 us TLV3012 propagation delay ({2e-6/max(t_on_ccm, t_on_pfm):.1f}-{4e-6/min(t_on_ccm, t_on_pfm):.1f} x)")

# Response lags with a filter capacitor
print("  Permit lags with a filter capacitor C_f (Cn 10 pF added):")
for cf in (100e-12, 220e-12, 470e-12, 1e-9):
    tau = par(453e3 + R_DRV, 1.00e6) * (cf + 10e-12)
    t_rise = tau * math.log(v_hi_min / (v_hi_min - trip_max))
    t_fall = tau * math.log(v_hi_max / fall_min)
    print(f"    C_f {cf*1e12:5.0f} pF: tau {tau*1e6:6.1f} us; FCC_ON/RGN_ON rise lag <= {t_rise*1e6:6.1f} us;"
          f" fall lag (H2c release) <= {t_fall*1e6:6.1f} us")
# budget: [WD] F.4 step D runs at max(A + 2 ms, ...) after step A drops FCC; keep the fall lag <= 10 % of it
tau_lim = 0.2e-3 / math.log(v_hi_max / fall_min)
print(f"  Fall-lag budget 10 % of the 2 ms step A -> D spacing ([WD] F.4): tau <= {tau_lim*1e6:.0f} us ->"
      f" C_f + Cn <= {tau_lim/par(453e3 + R_DRV, 1.00e6)*1e12:.0f} pF")
rth_csp = par(1.00e6 + par(47e3, 47e3), 1.00e6)
tau_csp = rth_csp * 110e-12
print(f"  N_CSP with 100 pF (+10 pF): tau {tau_csp*1e6:.1f} us; rise lag <= "
      f"{tau_csp*math.log(ce_hi/(ce_hi-trip_max))*1e6:.1f} us; fall lag (REGN 5.2 V max, [DS] EC) <= "
      f"{tau_csp*math.log(5.2*0.5/fall_min)*1e6:.1f} us; FR-47 persistence 2 ms ([WD] FR-47)")

# ---------------------------------------------------------------------------------------------------------------
print()
print("ILIM: Eq1 V=1+0.8*I")
# header GND pin currents
I = 3.21; print("pins 14/15 60/40:", round(0.6*I, 3), round(0.4*I, 3))
print("net GND into board at Iin 1.76, Ibat 3.21:", round(3.21-1.76, 2))
# input bulk nominal
cvbus = 2*10+0.1; cpmid = 3*10+0.1; cvac = 0.1; c103 = 1.0
print("nominal C after eFuse:", cvbus+cpmid+cvac+c103, "uF")
# dVdT inrush: round3 0.11 A into 51.4 uF at 2.19 V/ms
print("inrush at 2.19 V/ms:", round(2.19e3*(cvbus+cpmid+cvac+c103)*1e-6, 3), "A")
# 3V3 rail adds: bleed 10k
print("bleed current 3.3/10k mA:", 0.33)
# STAT series 1k with Teensy pin driving 3.3 V into STAT LOW (VOL~0)
print("STAT sink if pin6 driven HIGH via 1k:", 3.3/1.0, "mA")
