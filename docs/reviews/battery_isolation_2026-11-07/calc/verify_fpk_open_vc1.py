"""Verify battle-test finding: F_PK open -> balance midpoint becomes the pack return -> BQ29200 VC1 below -0.3 V.
Sources: BOM 20260622 lines 86-88 (RB1 100 Ohm 0402 0.125 W x2, RB2 160 Ohm, RB3 261 Ohm 0402 0.1 W);
facts_board.md 2.3 (VMID->RB3->VC1, VMID->RB1A->VC1_CB); SLUSA52C 7.1 (VC1-GND min -0.3 V).
Diode drop of the BQ29200 internal GND->VC1 structure is not published: VF swept as UNCONFIRMED."""
RB3, RB1A = 261.0, 100.0
R_par = RB3*RB1A/(RB3+RB1A)
for vcell in (3.0, 3.7, 4.2):
    for vf in (0.5, 0.7):
        imax = (vcell - vf)/R_par          # board loads modelled as a short VBT-GND: upper bound
        i3 = (vcell - vf)/RB3; i1 = (vcell - vf)/RB1A
        print(f"Vcell2={vcell} VF={vf}: R_par={R_par:.1f} Ohm, I_max={imax*1e3:.1f} mA "
              f"(RB3 {i3*1e3:.1f} mA {i3**2*RB3*1e3:.0f} mW vs 100 mW; RB1A {i1*1e3:.1f} mA {i1**2*RB1A*1e3:.0f} mW vs 125 mW); "
              f"VC1-GND ~ -{vf} V vs -0.3 V abs max")
# Fix check: fuse on pack positive. Open -> VBT floats/ pulled to GND by loads; pack- still on GND via S_GND.
vmid_min = 3.0
print(f"Fix (fuse in pack+): VC1-GND = V(cell1) >= {vmid_min} V > -0.3 V; VC2-VC1 = Vcell2 <= 4.2 V < 8 V")
