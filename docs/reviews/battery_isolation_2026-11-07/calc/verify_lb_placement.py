"""Verifier for battle-test finding 'LB placement' (2026-11-07).
1) Free strip right of J2 from the BRD element scan.  2) C_N1 crossover for the FF1 set race
(rev-4 network: R_N1 10k to 3V3, N1 from 0.3 V to U_CLS VT+ 2.0 V; earliest U_CKS switch 5.59 us,
ic1_rev4_calcs_output.txt section 6).  3) LB area band at alternative routing factors."""
import math
x0, x1, y0, y1 = 112.0, 131.064, 30.0, 98.044          # strip; board outline 131.064 x 98.044
print(f"strip {x1-x0:.2f} x {y1-y0:.2f} mm = {(x1-x0)*(y1-y0):.0f} mm2 (holes only at x 3.302: none in strip)")
R, V0, VT, VCC, t_ck_min = 10e3, 0.3, 2.0, 3.3, 5.59e-6
k = math.log((VCC - V0) / (VCC - VT))
for c in (130e-12, 230e-12, 330e-12):
    print(f"C_N1 {c*1e12:.0f} pF: /CLR {R*c*k*1e6:.2f} us, margin {(t_ck_min-R*c*k)*1e6:.2f} us")
print(f"crossover C_N1* = {t_ck_min/(R*k)*1e12:.0f} pF")
court = 1467.0
for f in (1.0, 1.5, 2.0, 2.5):
    print(f"routing factor {f}: {court*f:.0f} mm2 single-sided; {court*f/2:.0f} mm2 if placed both sides")
