"""Verification of FMEA round-4 finding: Stage-3 Q_MD re-key vs rev-6 exit rule.
Sources: detailed_design_IC1.md Fig. 6 (R_MB 3.3k, R_MD 10 Ohm Stage 3, C_HU 1.5 mF), sec 6 item 5
(Stage 3 Q_MD ON = FF1./Q), sec 9.5 exit steps 2-3, sec 14.4 (18 mA idle, 535 ms, 18 V -> 11 V),
sec 5.1 U_MS threshold 8.69-9.15 V, C_mod 100-221 uF (calc6 sec 3)."""
import math
R_MB, R_MD3, I_IDLE = 3300.0, 10.0, 0.018
VTH_HI, VLOCK = 9.15, 11.0
print("1. Exit step 2, FF1 set (Q_MD off), drain via R_MB only, I_idle min 0 (DS gives no minimum)")
for C in (1.5e-3, 1.5e-3+221e-6):
    for V0 in (18.0, 21.5):
        print(f"   C={C*1e3:.3f} mF V0={V0} V -> {VTH_HI} V: {R_MB*C*math.log(V0/VTH_HI):.3f} s (cap 0.010 s)")
print("   with I_idle 18 mA as well (fastest case):")
for V0 in (18.0, 21.5):
    C=1.5e-3; t=R_MB*C*math.log((V0+I_IDLE*R_MB)/(VTH_HI+I_IDLE*R_MB))
    print(f"   C=1.5 mF V0={V0}: {t:.3f} s")
print("2. Hold-up 18 V -> 11 V, I_idle 18 mA, with and without R_MB")
for C in (1.38e-3, 1.5e-3):
    t0=C*(18-VLOCK)/I_IDLE; t1=R_MB*C*math.log((18+I_IDLE*R_MB)/(VLOCK+I_IDLE*R_MB))
    print(f"   C={C*1e3:.2f} mF idle-only {t0*1e3:.0f} ms, with R_MB {t1*1e3:.0f} ms (target 535)")
Creq=0.535/(R_MB*math.log((18+I_IDLE*R_MB)/(VLOCK+I_IDLE*R_MB)))
print(f"   C_HU required with R_MB kept: {Creq*1e3:.3f} mF")
print("3. Proposed fix: dump on at feed drop through R_MD 10 Ohm (|| R_MB negligible)")
for C in (1.5e-3, 1.5e-3+221e-6, Creq+221e-6):
    R=1/(1/R_MD3+1/R_MB)
    for V0 in (18.0, 21.5):
        print(f"   C={C*1e3:.3f} mF V0={V0} -> {VTH_HI} V: {R*C*math.log(V0/VTH_HI)*1e3:.1f} ms (tau {R*C*1e3:.1f} ms)")
