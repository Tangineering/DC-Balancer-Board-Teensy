"""Verifier: row F34b with R_SH element open, KS+ vs INA240 SBOS662C 7.1 (-6 V abs max) and the proposed fixes.
Stdlib. Inputs: calc6 s1 (RB3||RB1A 72.3 Ohm), DD Table 7 (D_VC1 V_F <= 0.25 V; R_K 2.2 Ohm 1 %; INA240 I_B 90 uA typ,
series gain error 3000/(R_S+3000)), DD line 1003 (0.044 A per 10 uA mismatch at 2.2 Ohm), K_IN = 0.5 mOhm (R_SH)."""
RPAR, VF, RK, IB, K_IN = 72.3, 0.25, 2.2, 90e-6, 0.5e-3
print("[1] GND above pack(-) = V_cell1 + V_F + I*72.3 (cap 2*V_cell); threshold current for KS+ < -6 V")
for vc in (3.7, 4.2):
    ith = (6.0 - vc - VF) / RPAR
    print(f"   V_cell {vc}: I_th {ith*1e3:5.1f} mA; at 55 mA GND {min(vc+VF+0.055*RPAR, 2*vc):4.2f} V")
print("[2] Proposed Schottky clamp GND->KS+ (V_F 0.3 V): current via R_K1 before it fuses")
for vg in (4.45, 6.4, 8.4):
    i = (vg - 0.3) / RK
    print(f"   GND {vg} V above pack(-): {i:4.2f} A, {i*i*RK:5.1f} W in 0.25 W R_K1")
print("[3] Proposed series R_S = 100 Ohm per lead: offset and gain terms")
rs = 100.0
print(f"   I_B x dR (1 % match): {IB*2*rs*0.01*1e6:5.1f} uV = {IB*2*rs*0.01/K_IN:5.3f} A equivalent")
print(f"   10 uA I_B mismatch: {10e-6*rs*1e3:4.2f} mV = {10e-6*rs/K_IN:5.2f} A equivalent")
print(f"   series gain error 3000/(R_S+3000): {(1-3000/(rs+3000))*100:4.2f} % (2.2 Ohm: {(1-3000/(RK+3000))*100:5.3f} %)")
