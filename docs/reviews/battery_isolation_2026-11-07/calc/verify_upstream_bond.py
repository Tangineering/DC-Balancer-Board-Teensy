"""Verification of the battle-test finding 'parallel pack-negative bond upstream of R_SH'.
Split law from calc/fmea_round1_calcs.py section F; caps from DD Table (eFuse I_OL 1.84-2.16 A,
46.4 W regen input bound, DD line 641) and G2 per teensy_controller.ino:5104-5125."""
R_CHAIN_FIXED = 0.5e-3 + 1.6e-3 + 5e-3          # R_SH + S_CHG + VBATN_X/joints (section F)
I_SET = 1.75
print("Split law (uncapped):")
for r_s in (0.02, 0.10):
    for r_b in (0.02, 0.10):
        i = I_SET * (1 + (R_CHAIN_FIXED + r_s) / r_b)
        print(f"  R_s {r_s*1e3:.0f} mOhm R_b {r_b*1e3:.0f} mOhm: pack {i:.2f} A, bond {i-I_SET:.2f} A")
# G2 trip point (FC window; charger fed from the bus): V_p*I_true/eta_true - V_p*I_SET/0.75 > 3 W
for v_p in (7.4, 8.0, 8.4):
    for eta in (0.88, 0.95):
        i_trip = eta * (I_SET / 0.75 + 3.0 / v_p)
        print(f"  G2 trips (FC window) at pack current > {i_trip:.2f} A (V_p {v_p}, eta {eta})")
# Regen window: G2 blind (charger fed from V-MOT); eFuse input bound 46.4 W (DD line 641)
for v_p in (7.4, 8.4):
    for eta in (0.88, 0.95):
        print(f"  regen eFuse cap: pack <= {46.4*eta/v_p:.2f} A (V_p {v_p}, eta {eta})")
# FC window eFuse cap at 16 V bus, I_OL max 2.16 A
print(f"  FC eFuse cap: pack <= {16.0*2.16*0.95/7.4:.2f} A")
