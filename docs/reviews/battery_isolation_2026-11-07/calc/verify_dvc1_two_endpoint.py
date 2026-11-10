"""Verify finding: D_VC1 cold V_F <= 0.25 V @16.2 mA (-20 C) vs hot I_R <= 40 uA @4.2 V (T_M16,max).
Lower bound I_R >= I_S (reverse leakage of a Schottky at 4.2 V is >= the zero-bias I_S; barrier lowering only adds).
Method A: design's own x2/10 K scaling (calc7 section 3). Method B: thermionic emission I_S = A*A**T^2 exp(-PhiB/kT), n = 1,
with PhiB pinned at the cold-V_F bound; area swept (A* = 110 A/cm2K2, Si n-type; ASSUMED)."""
import math
k = 8.617333e-5
def vt(Tc): return k * (Tc + 273.15)
I_F, VF, V_cell = 0.0162, 0.25, 4.2
R_eff = (V_cell - VF) / I_F
print(f"R_eff=(V_cell-V_F)/I_F = {R_eff:.1f} Ohm (RB3 nominal 261 Ohm); budget 40 uA -> {40e-6*R_eff*1e3:.1f} mV")
print("[A] design x2/10 K scaling")
for n in (1.0, 1.1):
    Is_cold = I_F * math.exp(-VF / (n * vt(-20)))
    Is25 = Is_cold * 2 ** 4.5
    print(f" n {n}: I_S(-20C) >= {Is_cold*1e6:.3f} uA -> {Is25*1e6:.2f} uA at 25 C")
    for Th in (45, 55, 60, 70, 85):
        Ih = Is_cold * 2 ** ((Th + 20) / 10)
        print(f"   T_hot {Th} C: I_R >= {Ih*1e6:7.1f} uA, VC1 error >= {Ih*R_eff*1e3:6.1f} mV ({Ih/40e-6:5.2f} x budget)")
print("[A'] calc7's own 25 C numbers: I_S >= 0.96-2.33 uA vs 40 uA@85 C referred to 25 C = 0.62 uA -> infeasible even at 25 C V_F")
print("[B] thermionic emission, n = 1, PhiB at the cold-V_F bound")
Astar = 110.0
for A_cm2 in (1e-6, 1e-5, 1e-4, 1e-3):
    AA = A_cm2 * Astar
    T1, T2 = 253.15, 358.15
    PhiB = VF + vt(-20) * math.log(AA * T1**2 / I_F)
    Is_h = AA * T2**2 * math.exp(-PhiB / vt(85))
    print(f" area {A_cm2:.0e} cm2: PhiB <= {PhiB:.3f} eV; I_S(85 C) >= {Is_h*1e6:7.1f} uA; error >= {Is_h*R_eff*1e3:6.1f} mV")
