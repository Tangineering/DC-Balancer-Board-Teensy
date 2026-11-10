"""Battle-test round 4, datasheet re-verification lens: calculations.

Every input is cited. Run with the stdlib interpreter:
    .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/bt4_datasheet_reverify_calcs.py

Sections
  1  D_VC1 / D_VCB: Schottky saturation-current floor implied by the design's own V_F spec,
     reverse leakage versus temperature, VC1 error through RB3 against the BQ29200 V_OA.
  2  D_VC1 short (or reversed): VC2 - VC1 against the SLUSA52C 7.1 absolute maximum (8 V).
  3  U_MS with R_MS2 open: IN+ against the TLV3011B absolute maximum (SBOS300C 6.2).
  4  F_VX: prospective chafe current (calc6 section 2 loop + a 4 A fuse cold resistance)
     against the interrupting rating of a typical 4 A SMD fast fuse.
  5  Pin 8 (old ENC_B net) level if the bodged 2.2 kOhm RENC2 returns to 5 V.
"""
import math

k_B = 8.617e-5  # eV/K

print("[1 D_VC1/D_VCB leakage floor and temperature]")
# Design spec (detailed_design_IC1.md Table 7 row D_VC1, D_VCB): V_F <= 0.25 V at 45 mA, 25 C;
# I_R <= 10 uA at 4.2 V, 25 C.  Shockley: I_F = I_S exp(V_F / (n V_T)).
VF, IF, T0 = 0.25, 45e-3, 298.15
VT0 = k_B * T0
for n in (1.0, 1.05, 1.1):
    Is = IF * math.exp(-VF / (n * VT0))
    print(f"  n={n:.2f}: I_S floor implied by V_F spec = {Is*1e6:5.2f} uA (I_R(4.2 V) >= I_S, before barrier lowering)")
# Thermionic emission: I_S ~ T^2 exp(-phi_B / kT).  Ratio from 25 C to T for phi_B 0.5-0.6 eV
RB3 = 261.0       # BOM line 88 (schematic value 260 Ohm)
IR25 = 10e-6      # design's 25 C maximum
VOA = 10e-3       # SLUSA52C 7.5: V_OA +/-10 mV at 25 C
for phi in (0.50, 0.55, 0.60):
    row = []
    for TC in (45, 60, 85):
        T = TC + 273.15
        ratio = (T / T0) ** 2 * math.exp(phi / k_B * (1 / T0 - 1 / T))
        IR = IR25 * ratio
        row.append(f"{TC} C: x{ratio:5.1f} I_R {IR*1e6:6.1f} uA, VC1 low by {IR*RB3*1e3:6.1f} mV ({IR*RB3/VOA:4.1f} x V_OA)")
    print(f"  phi_B {phi:.2f} eV: " + "; ".join(row))
print("  sign: reverse current flows cell1 -> RB3 -> VC1 -> D_VC1 -> GND, so VC1-GND reads LOW:")
print("  cell-1 OVP is masked by I_R*RB3; cell 2 (VC2-VC1) reads high by the same amount.")
print("  BQ29200 own VC1 input current: +/-0.2 uA (SLUSA52C 7.5) -> 10 uA diode = 50 x the IC's own term")

print("\n[2 D_VC1 short or reversed: VC2 - VC1 vs SLUSA52C 7.1 abs max 8 V]")
for vpack in (7.4, 8.0, 8.4, 8.5):
    # VC1 forced to 0 V (short at the pin) or +V_F (reversed, ~0.3 V); VC2 = VBAL+ via RB2 (uA input current)
    print(f"  V_pack {vpack:.1f} V: short VC2-VC1 = {vpack:.2f} V ({'EXCEEDS' if vpack > 8 else 'within'} 8 V); "
          f"reversed (V_F 0.3 V) = {vpack-0.3:.2f} V ({'EXCEEDS' if vpack-0.3 > 8 else 'within'} 8 V)")
print("  RB3 limits the short current to 16 mA (calc6 s1) but not the VC2-VC1 voltage across the IC.")

print("\n[3 U_MS with R_MS2 open]")
for vnode in (13.5, 16.0, 21.5):
    print(f"  node {vnode:4.1f} V: IN+ -> {vnode:4.1f} V through R_MS1 100 k (I_B 10 pA, no clamp to V+); "
          f"abs max 7 V (SBOS300C 6.2 note 2: inputs above 7 V must be externally clamped)")
print("  healthy divider at 21.5 V: IN+ = 3.00 V (within (V+)+0.2)")

print("\n[4 F_VX prospective current vs a typical 4 A SMD fuse interrupting rating]")
R_cold = 0.016   # Littelfuse 0451004 (Nano2 451) cold resistance per distributor listing, UNCONFIRMED vs Littelfuse PDF
IR_rating = 50.0 # 0451 series 1/16-8 A: 50 A at 125 VAC/VDC (distributor listings)
for vp, rl in ((8.4, 0.0333), (7.4, 0.1883)):    # calc6 section 2 loops
    ip = vp / (rl + R_cold)
    print(f"  V_pack {vp} V, loop {rl*1e3:.1f} mOhm + fuse {R_cold*1e3:.0f} mOhm: {ip:6.1f} A = {ip/IR_rating:4.1f} x the 50 A interrupting rating")

print("\n[5 Pin 8 released level if RENC2 2.2 k returns to 5 V (archive: 'possibly to 5 V')]")
g = 1/2.2e3 + 1/10e3 + 1/22e3
v = (5.0/2.2e3 + 3.3/10e3 + 3.3/22e3) / g
print(f"  released node = {v:.2f} V (Teensy 4.1 I/O not 5 V tolerant; 3V3 + 0.3 = 3.6 V)")
i_sink = 5.0/2.2e3 + 3.3/10e3 + 3.3/22e3
print(f"  U_MS sink when LOW: {i_sink*1e3:.2f} mA (V_OL spec only at 5 mA, VS 5 V: 200 mV max)")
g3 = 3.3/2.2e3 + 3.3/10e3 + 3.3/22e3
print(f"  with RENC2 to 3V3: U_MS sink {g3*1e3:.2f} mA")
