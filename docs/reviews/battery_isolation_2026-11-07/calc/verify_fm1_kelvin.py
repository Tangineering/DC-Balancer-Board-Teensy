"""Verification of battle-test finding FM-1 (Kelvin leads KS+/KS-), 2026-11-07.
Inputs: DD Fig.1/Table 4 topology; DD Table 7 F_PK 20 A; DD line 501/620 eFuse I_OL 1.98 A (1.84-2.16 A, SLVSE94G 6.5);
fmea_round1_calcs.py section F chain parts. Pack internal resistance and wire gauge are ASSUMPTIONS (sweep)."""
V_PACK = 8.4
print("Part 1: KS lead shorted to pack+ (loop: pack+ -> short -> KS wire -> [R_SH] -> F_PK -> pack-)")
for awg, ohm_per_m in ((26, 0.1339), (24, 0.0842), (22, 0.0530)):
    for r_int in (0.010, 0.040):
        r = r_int + 0.3 * ohm_per_m + 0.005   # 0.3 m of lead, 5 mOhm fuse/joints
        print(f"  {awg} AWG, R_int {r_int*1e3:.0f} mOhm: I = {V_PACK/r:6.1f} A, P_wire = {(V_PACK/r)**2*0.3*ohm_per_m:6.1f} W")
for rs in (1.0, 10.0):
    print(f"  with {rs} Ohm series fusible resistor at SB: I <= {V_PACK/rs:.2f} A, P_R = {V_PACK**2/rs:.1f} W")
print("Part 2: KS+ bonded to PCB GND in charge mode, Ag105 regulating its sensed (chain) current to 1.75 A")
chain_fixed = 0.5e-3 + 1.6e-3 + 5e-3
ETA = 0.88
for vin, lbl in ((16.0, "FC window"), (21.47, "regen peak")):
    for r_s in (0.02, 0.05, 0.10):
        for r_b in (0.02, 0.1, 0.5):
            chain = chain_fixed + r_s
            i_tot_req = 1.75 * (1 + chain / r_b)
            i_in_req = i_tot_req * V_PACK / ETA / vin
            if i_in_req <= 2.16:
                state = f"sustained, bond {i_tot_req-1.75:4.2f} A (I_in {i_in_req:4.2f} A < I_OL)"
            elif i_in_req <= 1.84 * 2:
                cap = 2.16 * vin * ETA / V_PACK
                state = f"I_in req {i_in_req:4.2f} A > I_OL: limited, latch-off <=233 ms; bond during limit <= {cap*chain/(chain+r_b):4.2f} A"
            else:
                state = f"I_in req {i_in_req:4.2f} A > 2xI_OL: fast trip"
            print(f"  {lbl} R_s {r_s*1e3:3.0f} R_b {r_b*1e3:3.0f} mOhm: I_tot req {i_tot_req:5.2f} A; {state}")
