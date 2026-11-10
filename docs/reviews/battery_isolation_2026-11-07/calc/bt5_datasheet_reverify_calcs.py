"""Battle-test round 5, datasheet re-verification lens (detailed_design_IC1.md revision 7).

Sections:
 1. D_VC1: can any Schottky meet BOTH revision-7 limits (V_F <= 0.25 V at 16.2 mA over -20..85 C AND
    I_R <= 40 uA at 4.2 V at T_M16,max)?  RB3-independent invariant.
 2. D_VC1 against a real low-V_F part (onsemi NSR0320MW2T1/D Rev. 8, April 2022).
 3. Consequence of the hot leakage on the BQ29200 cell-1 OVP and on ERR_CELL_MISMATCH.
 4. TPS2663 R_ILIM 8.06 kOhm cross-check (SLVSE94G Eq. 5 and section 6.5 I(OL) rows).
 5. F_VX: Littelfuse 451/453 rev GD (08/23/21) 4 A row vs the design's cited values.
 6. Pin-8 sink current for U_MS with RENC2 left fitted (gate P8 permits it).

Model assumptions are tagged ASSUMED.  Primaries: SLUSA52C 7.1/7.3; SLVSE94G 6.5, Eq. 5; NSR0320MW2T1/D Rev 8;
Littelfuse 451/453 datasheet rev GD; SCH net ENC_B / 3V3 (RENC2); Teensy core 1.62.0 digital.c (INPUT_PULLUP = PUS(3)).
"""
import math

k_q = 8.617333e-5  # V/K


def vt(tc):
    return k_q * (tc + 273.15)


print("[1 D_VC1 feasibility invariant]")
# In row F34b the clamp current is I_F = (V_cell - V_F)/RB3 and the leakage error is delta = I_R * RB3.
# So delta = I_R * (V_cell - V_F) / I_F, independent of RB3.  I_R(hot) >= I_S(hot) (reverse leakage is at least
# the saturation current; barrier lowering at 4.2 V only increases it).  V_F(cold) <= 0.25 V at I_F requires
# I_S(cold) >= I_F * exp(-0.25 / (n Vt(cold))).
V_cell = 4.2
V_F_max = 0.25
T_cold = -20.0
budget_mV = 10.4  # design: 40 uA x 261 Ohm
for label, per10K in (("design ASSUMED x2.00 per 10 K", 2.0),
                      ("NSR0320 primary, 25->85 C at 15 V: 450/10 typ = x45 over 60 K -> x%.2f per 10 K" % (45 ** (1 / 6)), 45 ** (1 / 6))):
    print(" ", label)
    for n in (1.0, 1.1):
        for T_hot in (45.0, 60.0, 70.0, 85.0):
            ratio_hot_cold = per10K ** ((T_hot - T_cold) / 10.0)
            # I_S(cold)/I_F lower bound
            x = math.exp(-V_F_max / (n * vt(T_cold)))
            delta_min = (V_cell - V_F_max) * x * ratio_hot_cold * 1e3  # mV
            print("    n %.1f, T_hot %4.0f C: minimum VC1 leakage error %7.1f mV (design budget %.1f mV) -> %s" % (
                n, T_hot, delta_min, budget_mV, "feasible" if delta_min <= budget_mV else "INFEASIBLE x%.1f" % (delta_min / budget_mV)))
# Same statement as I_R at the design RB3 = 261 Ohm
RB3 = 261.0
I_F = (V_cell - 0.0) / RB3
print("  at RB3 261 Ohm the fault current is %.1f mA; the 40 uA limit is %.2e of it" % (I_F * 1e3, 40e-6 / I_F))
# 25 C-only check in calc7 section 3 (what the design did)
for n in (1.0, 1.1):
    Is25 = 16.2e-3 * math.exp(-0.25 / (n * vt(25.0)))
    Is_m20 = 16.2e-3 * math.exp(-0.25 / (n * vt(-20.0)))
    print("  n %.1f: I_S needed for 0.25 V at 16.2 mA: %.2f uA at 25 C (calc7) but %.3f uA at -20 C,"
          " i.e. %.1f uA referred to 25 C with x2/10 K" % (n, Is25 * 1e6, Is_m20 * 1e6, Is_m20 * 2 ** 4.5 * 1e6))

print("\n[2 NSR0320MW2T1G (onsemi NSR0320MW2T1/D Rev 8): the lowest-V_F small Schottky checked]")
print("  V_F max 0.27 V at 10 mA, 25 C (> 0.25 V at 16.2 mA before any cold shift)")
# ASSUMED -1.5 mV/K V_F tempco at 10-16 mA for a low-barrier Schottky
for tc in (-1.0e-3, -1.5e-3):
    vf_cold = 0.27 + 0.0 + (-20 - 25) * tc  # 0.27 at 10 mA; at 16.2 mA add n Vt ln(1.62)
    vf_cold += 1.0 * vt(-20) * math.log(1.62)
    print("  ASSUMED tempco %.1f mV/K: V_F(16.2 mA, -20 C) about %.3f V -> VC1 at %.3f V (SLUSA52C 7.1 minimum -0.3 V)"
          % (tc * 1e3, vf_cold, -vf_cold))
print("  I_R typ 200 uA at V_R 2.0 V, 85 C; typ 450 uA at 15 V, 85 C (no maximum given at 85 C)")
print("  -> at 85 C: %.0f uA vs the 40 uA limit (x%.0f); VC1 error 200 uA x 261 Ohm = %.1f mV vs 10.4 mV"
      % (200, 200 / 40, 200e-6 * 261 * 1e3))

print("\n[3 Consequence of the hot leakage]")
for IR in (40e-6, 100e-6, 200e-6, 450e-6):
    d = IR * RB3
    print("  I_R %4.0f uA: VC1 reads %5.1f mV low -> true cell-1 OVP trip about 4.35 V + %5.1f mV;"
          " ERR_CELL_MISMATCH sees %5.1f mV of 80 mV" % (IR * 1e6, d * 1e3, d * 1e3, 2 * d * 1e3))

print("\n[4 TPS2663 R_ILIM]")
R = 8.06
I_typ = 18.0 / R
for Rrow, lo, ty, hi in ((30, 0.54, 0.6, 0.66), (9, 1.84, 2.0, 2.16), (4.02, 4.185, 4.5, 4.815), (3, 5.58, 6.0, 6.42)):
    print("  row R(ILIM) %5.2f k: %.3f/%.3f/%.3f A, tolerance -%.1f/+%.1f %%, Eq.5 typ %.3f A"
          % (Rrow, lo, ty, hi, (1 - lo / ty) * 100, (hi / ty - 1) * 100, 18 / Rrow))
print("  8.06 k: Eq.5 typ %.3f A; +/-8 %% -> %.3f-%.3f A (design 2.06-2.41 A); 0.1 %% resistor adds 0.1 %%" % (
    I_typ, I_typ * 0.92, I_typ * 1.08))
print("  TPS26631 pulse phase: I(OL_Pulse) = 2 x I(OL) = %.2f-%.2f A for tCB(dly) 20-31 ms (SLVSE94G 6.5/6.6)"
      % (2 * I_typ * 0.92, 2 * I_typ * 1.08))
print("  GAIN(IMON) specified only for 0.6 A <= I(OUT) <= 2 A; U_IM trip 1.51-1.98 A lies inside it")

print("\n[5 F_VX Littelfuse 451/453 rev GD, 08/23/21]")
rows = {"3.5 A (03.5)": (0.0200, 1.920), "4 A (004.)": (0.0160, 2.469), "5 A (005.)": (0.0125, 3.152)}
for k_, (r, i2t) in rows.items():
    print("  %-13s cold R %.4f Ohm, melting I2t %.3f A2s" % (k_, r, i2t))
print("  design cites 16.0 mOhm with 3.152 A2s: the resistance is the 4 A row, the I2t is the 5 A row")

print("\n[6 Pin-8 low-level sink with RENC2 fitted]")
for renc in (4.7e3, 2.2e3):
    i = 3.3 / renc + 3.3 / 10e3 + 3.3 / 22e3
    print("  RENC2 %.1f k + R_UMS 10 k + Teensy INPUT_PULLUP 22 k (PUS(3)): U_MS sinks %.2f mA at 3V3 3.30 V" % (renc / 1e3, i * 1e3))
print("  SBOS300C 6.9 gives V_OL only at VS = 5 V, 5 mA (200 mV max); 3.3 V supply not tabulated")
