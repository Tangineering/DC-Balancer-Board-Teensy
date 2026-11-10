"""Verifier for the FMEA finding 'negative SGND offset turns S_GND off and S_CHG on' (both return leads open).
Inputs: DD Fig.1 (R_GA 4.7k/R_PA 100k, R_CQ 10k/R_PC 100k, S_GND body diodes anode SGND cathode PACK-),
DD 7.9 (V(pin23) = 1.7286 + 0.4762*V_PACKN), Table 16 ERR_PACKN_RANGE -1.2 V, BSS138/D Rev 7 p.2 Vth 0.8/1.3/1.5 V.
ASSUMED: SGND sits one small-current body-diode drop above PACK- (0.35-0.55 V at ~1 mA pull-up current);
R_chain 62 mOhm (DD 12.6 item 3 working figure)."""
kA = 100/104.7; kC = 100/110
r_chain = 0.062
for vth in (0.8, 1.3, 1.5):
    offA, offC = vth/kA, vth/kC
    off = max(offA, offC)  # both must be on (Q_A releases Q_D, Q_C drives Q_B)
    for vbd in (0.35, 0.55):
        vgp = off + vbd  # V(GND) - V(PACK-) = -V_PACKN at equilibrium
        line = f"Vth {vth}: Q_A {offA:.3f} V, Q_C {offC:.3f} V; Vbd {vbd}: -V_PACKN {vgp:.2f} V"
        line += f" (ERR_PACKN_RANGE {'trips' if vgp>1.2 else 'no'}; pin23 {1.7286-0.4762*vgp:.3f} V)"
        for I in (1.0, 7.2, 17.1):
            vds = max(vgp - I*r_chain, 0.0)
            line += f"; I {I}: P_SCHG {I*vds:.1f} W"
        print(line)
for R_int in (0.010, 0.020, 0.040):
    I = 8.0/(R_int+0.002+0.00187+0.0005)
    print(f"VBT short, R_int {R_int*1e3:.0f} mOhm: I {I:.0f} A, lead drop {I*0.00187:.2f} V (Q_A min 0.838 V)")
