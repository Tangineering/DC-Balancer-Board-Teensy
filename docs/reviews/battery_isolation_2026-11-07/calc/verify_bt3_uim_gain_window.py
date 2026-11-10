"""Verifier for battle-test finding 'U_IM trip not guaranteed below eFuse I_OL'.
Sources: SLVSE94G (TPS2663, rev June 2024) 6.5: GAIN(IMON) 25.66/27.9/30.14 uA/A (0.6-2 A);
I(OL) 1.84/2.00/2.16 A at R_ILIM 9 k; Eq. 8 R_ILIM(k) = 18 / I_OL.  SBOS300C 6.9: V_OS +/-9 mV, V_HYS 2/6/8 mV;
REF 1.223-1.260 V.  Design: detailed_design_IC1.md Figure 2 (R_IMa 59.0k / R_IMb 10.0k from 3V3, R_IM 10k), R_ILIM 9.09k.
"""
G = (25.66e-6, 27.9e-6, 30.14e-6); RIM = 10e3; DIV = 10/69
IOLmin = 1.84*9/9.09; IOLmax = 2.16*9/9.09
print(f"I_OL at 9.09k: {IOLmin:.3f}-{IOLmax:.3f} A")
for v33 in (3.2, 3.3, 3.4):
    vt = v33*DIV
    # hysteresis: rising-input trip sits above the centre by Vhys/2 (0.5..4 mV); one-sided, not +/-
    hi = (vt*1.002 + 0.009 + 0.004)/(G[0]*RIM*0.999)
    lo = (vt*0.998 - 0.009 + 0.001)/(G[2]*RIM*1.001)
    print(f"3V3 {v33}: trip {lo:.3f}-{hi:.3f} A (hys one-sided); gain-only {vt/(G[2]*RIM):.3f}-{vt/(G[0]*RIM):.3f}")
# proposed fix 1: absolute REF divided down to ~0.47 V
vt = 0.47; rs = (1.260/1.2415, 1.223/1.2415)
hi = (vt*rs[0]*1.002 + 0.013)/(G[0]*RIM*0.999); lo = (vt*rs[1]*0.998 - 0.008)/(G[2]*RIM*1.001)
print(f"REF-based threshold 0.47 V nominal: trip {lo:.3f}-{hi:.3f} A, ratio {hi/lo:.3f} vs available {IOLmin/1.46:.3f}")
# proposed fix 2 direction: I_OL = 18/R_ILIM, so I_OL_min above 1.92+0.05 needs a SMALLER R_ILIM
need = (1.920+0.05)/0.92  # nominal I_OL with -8 % spec spread
print(f"needed nominal I_OL {need:.3f} A -> R_ILIM <= {18/need:.2f} k (lower, not raise); 8.25k gives "
      f"{18/8.25*0.92:.3f}-{18/8.25*1.08:.3f} A")
