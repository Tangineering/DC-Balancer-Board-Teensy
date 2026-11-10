"""Verifier recompute: BQ29200 bottom-cell reading in the IC1 charge mode (battle-test finding, BQ over-read).
Model: Ag105 CV holds VCHG - VBat- = 8.40 V (concept_IC1 rev 2 Table 10 row 'Ag105 CV sense', UNCONFIRMED sense point);
VCHG = pack+ + 35 mV (D-BT-SQ, RT1987 forward regulation). Return path pack- -> R_SH -> S_CHG -> VBATN_X lead -> R_s -> GND.
BQ29200 bottom cell = VC1 - PCB GND (facts_board 5.1). OVP 4.35 V +/-25 mV (facts_prior 148)."""
R_SH, R_DS, VFWD, VCV = 0.5e-3, 1.6e-3, 0.035, 8.40
rho = 0.0172e-6 / 0.5e-6
OVP_MIN, OVP_NOM = 4.325, 4.35
for L in (0.3, 0.5):
    R_lead = rho * L
    R_pre = R_SH + R_DS + R_lead          # inside the Ag105 CV loop sense span
    print(f"VBATN_X 0.5 mm2 x {L} m = {R_lead*1e3:.1f} mOhm; R_SH+R_DS+lead = {R_pre*1e3:.1f} mOhm")
    for R_s in (0.020, 0.050, 0.077, 0.100):
        for I in (1.25, 1.75):
            v_pack = VCV - VFWD - I * R_pre             # true pack at CV entry (max reading instant)
            cell = v_pack / 2
            reading = cell + I * (R_pre + R_s)
            margin = OVP_MIN - reading
            rs_trip = (OVP_MIN - (VCV - VFWD) / 2) / I - R_pre / 2
            print(f"  R_s {R_s*1e3:5.1f} mOhm I {I:.2f} A: true pack {v_pack:.4f} V, balanced BQ reading {reading:.4f} V, "
                  f"margin to 4.325 V {margin*1e3:+6.1f} mV (imbalance to trip {2*margin*1e3:6.1f} mV); "
                  f"balanced trip needs R_s > {rs_trip*1e3:.1f} mOhm")
