"""Battle-test round 8, datasheet re-verification lens (revision-8 LB-entry resistors, D_VC1, pin 20).

Cited in the round-8 findings as "bt8 calc section N". Standard library only.
Primaries (read 2026-11-08 from the vendor URLs; nothing stored in the repo):
  SBOS300C (TLV3011B, rev. April 2023) section 6.2 and its footnote (2)
  SCES214AF (SN74LVC1G04, rev. October 2025) section 5.1 and section 8 layout note
  SLVSE94G (TPS2663, rev. June 2024) section 6.1
  IMXRT1060CEC Rev. 4 (04/2024) Table 7 and Table 22
  onsemi NSR0320MW2T1/D Rev. 8 (April 2022) electrical characteristics
  onsemi BSS138/D (V_GSS)
  SLUSA52C (repo: references/Datasheets/BQ29200_TI.pdf) section 7.1
Design values from detailed_design_IC1.md revision 11 (Figures 2, 6; Table 7; rows F54b, F54c; calc8 sections 3-5).
"""
import math

CHAFE = (("VBT", 8.5), ("VBUS", 17.5), ("VCHG-IN", 21.5))
V3V3 = (3.2, 3.3, 3.4)

print("=" * 96)
print("[1] TLV3011B inputs behind R_MS3 22k (U_MS IN+) and R_IMF 10k (U_IM IN-)")
print("=" * 96)
# SBOS300C 6.2 footnote (2): inputs diode-clamped to V- only; may exceed V+ within -0.5..7 V;
# 'inputs beyond 7 V must be externally voltage clamped'. Bias current 10 pA max (6.7).
IB = 10e-12
for name, r in (("R_MS3 -> U_MS IN+", 22e3), ("R_IMF -> U_IM IN-", 10e3)):
    for cond, v in CHAFE:
        vin = v - IB * r
        print(f"  {name}: lead chafed to {cond} {v:4.1f} V -> input {vin:6.3f} V "
              f"(abs max 7.0 V: {'EXCEEDED by %.1f V' % (vin - 7.0) if vin > 7.0 else 'ok'}); "
              f"current {IB*1e12:.0f} pA, not the 0.22-0.81 mA calc8 assumed (no V+ clamp exists)")
print("  calc8 s5 'injected (v - 3.6)/R, 3.6 V clamp onset ASSUMED' has no clamp to inject into.")
# with an external Schottky to 3V3 behind the resistor (BAT54 class, V_F about 0.32 V at 1 mA, TODO(verify))
for name, r in (("R_MS3", 22e3), ("R_IMF", 10e3)):
    i = (21.5 - 3.4 - 0.32) / r
    print(f"  with an external clamp to 3V3 behind {name}: {i*1e3:.2f} mA at 21.5 V, input <= {3.4+0.32:.2f} V (< 7 V)")

print()
print("=" * 96)
print("[2] Driven LVC outputs (SHDN_EF via R_SD 1k, MD_G via R_MDS 1k) and the CB-end pins")
print("=" * 96)
# SCES214AF 5.1: VO in high or low state -0.5 .. VCC+0.5 V; IOK rated only for VO < 0 (-50 mA);
# 7.1/8: Ioff circuitry 'disables the outputs, preventing damaging current backflow'; 'Outputs should not be
# pulled above VCC'. There is no positive output clamp to carry the '18 mA' of row F54c.
for v3 in V3V3:
    print(f"  3V3 {v3:.1f} V: LVC output abs max {v3+0.5:.1f} V; VBT chafe 8.5 V exceeds it by {8.5-v3-0.5:.1f} V")
# SLVSE94G 6.1: OVP, dVdT, IMON, MODE, SHDN, ILIM, PLIM: -0.3 .. 5.5 V
for cond, v in CHAFE:
    print(f"  CB end, chafe to {cond} {v:4.1f} V: TPS26631 SHDN / IMON pin {v:4.1f} V vs 5.5 V abs max; "
          f"BSS138 Q_CS/Q_MP V_GS {v*100/101:5.2f} V (R_PG 1k, R_PGP 100k) vs +/-20 V V_GSS")
print("  No LB-end element (R_SD, R_IMF, R_PGL, R_MDS) is in series with the CB-end pin of its own lead.")

print()
print("=" * 96)
print("[3] Teensy pin 20 (i.MX RT1062, GPIO_AD_B1 pad on NVCC_GPIO)")
print("=" * 96)
# IMXRT1060CEC Rev 4 Table 7: Vin/Vout -0.5 .. OVDD + 0.3 V; no injection-current row anywhere in the document.
for v3 in V3V3:
    print(f"  OVDD {v3:.1f} V: Vin abs max {v3+0.3:.1f} V; a pad clamp conducting 0.22-0.81 mA sits about 0.5-0.7 V above OVDD"
          f" (silicon junction, UNCONFIRMED) -> outside Table 7 for every chafe of row F54b")
# Table 22: IIN (no PU/PD) -1 .. +1 uA.
sens = 4 * 122e3          # V of mismatch per A of pin current (calc8 s4: 0.488 V/uA)
allow = 79e-9             # calc8 s4 uncalibrated drift allowance
iin = 1e-6
print(f"  IIN max {iin*1e6:.1f} uA (Table 22) x {sens*1e-6:.3f} V/uA = {iin*sens*1e3:.0f} mV of mismatch vs the 80 mV threshold")
print(f"  datasheet IIN / calc8 allowance = {iin/allow:.1f}x; the 80 mV budget needs the pad 12.7x inside its own limit")
print(f"  at the revision-7 100 kOhm source: {iin*4*100e3*1e3:.0f} mV (R_VC1c raised the sensitivity by 22 %)")
for i in (0.1e-6, 0.2e-6, 0.5e-6):
    print(f"    drift {i*1e9:4.0f} nA -> {i*sens*1e3:5.0f} mV")

print()
print("=" * 96)
print("[4] D_VC1 candidates against V_F <= 0.25 V at 16.2 mA (T_min) and I_R <= 40 uA at 4.2 V (T_M16,max)")
print("=" * 96)
k, q = 1.380649e-23, 1.602176634e-19
vt25 = k * 298.15 / q
# NSR0320MW2T1/D Rev 8: VF(10 mA) 0.24 typ / 0.27 max; VF(100 mA) 0.30 typ / 0.35 max; 25 C.
# IR(15 V) 10 typ / 50 max; IR(2 V, 85 C) 200 typ; IR(15 V, 85 C) 450 typ (uA; the micro glyph extracts as 'm').
n_eff = (0.30 - 0.24) / (vt25 * math.log(10))
print(f"  NSR0320MW2 (onsemi, SOD-323, 20 V 1 A): slope 10->100 mA typ gives n_eff {n_eff:.2f}")
for label, vf10 in (("typ", 0.24), ("max", 0.27)):
    vf16 = vf10 + n_eff * vt25 * math.log(16.2 / 10)
    print(f"    V_F({label}) at 16.2 mA, 25 C: {vf16:.3f} V vs 0.25 V limit -> {'FAILS' if vf16 > 0.25 else 'ok'} before any cold shift")
for tc in (-1.0, -1.5):
    for tmin in (-20.0, 0.0):
        vf = 0.27 + n_eff * vt25 * math.log(1.62) + tc * 1e-3 * (tmin - 25.0)
        print(f"    max V_F at T_min {tmin:5.1f} C with {tc:.1f} mV/K (ASSUMED tempco): {vf:.3f} V")
print("    I_R typ 200 uA at V_R 2 V, 85 C (table) = 5.0x the 40 uA limit at half the 4.2 V stress;")
print("    I_R typ 10 uA at 15 V, 25 C -> under the design x2 per 10 K rule the 40 uA limit is reached near "
      f"{25 + 10*math.log2(40/10):.0f} C (typical part, before the max column)")
print("  PMEG2005ESF (Nexperia, DSN0603-2): V_F 0.31 typ / 0.38 max at 10 mA (secondary copy, UNCONFIRMED) -> FAILS V_F")
print("  BAT54-class: V_F 0.40 max at 10 mA (design row BT3-BM-01 already excludes it)")
print("  Inference: a part that meets V_F at 16.2 mA at 25 C needs a die larger than the 1 A NSR0320, whose")
print("  own 85 C leakage is 5x the budget; no stocked part was found that meets both endpoints at any T_min <= 25 C.")

print()
print("=" * 96)
print("[5] BQ29200 pins touched by the revision-8 set (SLUSA52C 7.1)")
print("=" * 96)
print("  VC1-GND -0.3..16 V (D_VC1 limit consistent); VC2-VC1 -0.3..8 V (row F47 consistent);")
print("  VC1_CB: no row in 7.1 (TODO(verify: TI) stands; B-PKN lifts RB1A.2 until rated)")
print("  IIN at VC1 -0.2..+0.2 uA at 0-60 C only (7.5): outside 0-60 C the VC1 input current is unrated")
