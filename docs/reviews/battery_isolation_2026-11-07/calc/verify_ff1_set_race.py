"""Verify battle-test finding: FF1 /CLR release vs CLK RC race (design Fig.2).
N1: R_N1 10k to 3V3, start V0 (BAT54 VF ~0.25 V), optional step kick from pin-33 edge
coupled through D_N33 junction capacitance C_D33 (charge share: dV = 3.3*C_D33/C_N1).
CLK: R_CK 1k x C_CK 1 nF (tau 0.95-1.05 us). Both inputs: same threshold Vt.
Crossover C_N1* where t_clr == t_clk:  C* = tau_ck*ln(3.3/(3.3-Vt)) / (R_N1*ln((3.3-V0)/(3.3-Vt)))."""
import math
VCC = 3.3
def c_star(vt, v0, tau_ck, rn1):
    return tau_ck * math.log(VCC / (VCC - vt)) / (rn1 * math.log((VCC - v0) / (VCC - vt)))
print("Crossover node capacitance C* (pF) where FF1 fails to set (C_N1 > C*):")
for tau in (0.95e-6, 1.05e-6):
    for rn1 in (10e3, 10.1e3):
        for vt in (0.8, 1.4, 1.6, 2.0):
            for v0, tag in ((0.25, "no kick"), (0.25 + 3.3 * 10 / 100, "kick C_D33 10pF/100pF")):
                print(f"  tau_ck {tau*1e6:.2f} us R_N1 {rn1/1e3:.1f}k Vt {vt:.1f} V V0 {v0:.2f} V ({tag}): C* = {c_star(vt, v0, tau, rn1)*1e12:6.1f} pF")
print("\nMargin vs C_N1 (tau_ck 0.95 us, R_N1 10k, V0 0.25 V):")
for cn in (70e-12, 85e-12, 100e-12, 115e-12, 130e-12):
    for vt in (0.8, 1.4, 2.0):
        tc = 10e3 * cn * math.log((VCC - 0.25) / (VCC - vt)); tk = 0.95e-6 * math.log(VCC / (VCC - vt))
        print(f"  C {cn*1e12:5.0f} pF Vt {vt:.1f}: clr {tc*1e9:6.0f} ns clk {tk*1e9:6.0f} ns margin {(tk-tc)*1e9:+6.0f} ns")
print("\nInput edge rate at threshold (LVC1G family limit dt/dv ~10 ns/V at 3.3 V, TODO(verify: SCES431/SCES794)):")
for vt in (1.4, 2.0):
    slope_ck = (VCC - vt) / 1e-6; print(f"  CLK at Vt {vt}: {1e9/slope_ck:5.0f} ns/V")
    slope_n = (VCC - vt) / (10e3 * 100e-12); print(f"  N1 (100 pF) at Vt {vt}: {1e9/slope_n:5.0f} ns/V")
print("\nProposed fix R_CK 10k (tau 9.5 us), C_N1 130 pF, Vt 2.0: margin",
      round((9.5e-6*math.log(VCC/(VCC-2.0)) - 10e3*130e-12*math.log(3.05/1.3))*1e6, 2), "us")
print("Alt fix R_N1 2.2k, C_N1 130 pF Vt 2.0: margin",
      round((0.95e-6*math.log(VCC/(VCC-2.0)) - 2.2e3*130e-12*math.log(3.05/1.3))*1e6, 2), "us;",
      "extra sink current per clear source 3.3/2.2k =", round(3.3/2.2e3*1e3, 2), "mA")
