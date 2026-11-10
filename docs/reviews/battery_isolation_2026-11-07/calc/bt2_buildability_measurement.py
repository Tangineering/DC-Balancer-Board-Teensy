"""Battle-test round 2, buildability / measurement-integrity lens, calculations.

Sources: detailed_design_IC1.md rev 4 (Figures 2-5, Tables 7, 16); facts_board.md 2.1, 3.3, 3.4, 5;
SLUSA52C section 7.5 (BQ29200 OUT: I_OL 30 uA min at OUT = 0.05 V; V_OUT 6-9.5 V at OVP);
onsemi BSS138/D (V_GS(th) 0.8-1.5 V); BRD element placements (Teensy U$1 at 97.282, 60.706; J2 at 108.712;
board outline 131.064 x 98.044 mm). Stdlib only.
"""

print("=" * 78)
print("Section 1. Shared Kelvin pair: signature of a KS+ to KS- short (or a cracked Kelvin joint)")
print("=" * 78)
R_SH = 0.5e-3; G = 100.0; VS = 3.3; mid = VS / 2
for I in (1.0, 3.0, 7.2, 17.1):
    vd_true = I * R_SH
    out1_ok = mid - G * vd_true  # discharge lowers OUT1
    out2_ok = mid + G * vd_true  # reversed channel
    # pair shorted downstream of R_K: differential = 0 at both amplifiers
    print(f"discharge {I:5.1f} A: intact OUT1 {out1_ok:.3f} V / OUT2 {out2_ok:.3f} V; "
          f"KS shorted OUT1 = OUT2 = {mid:.3f} V -> I_PACK1 = I_PACK2 = 0, |I1-I2| = 0 (XCHK passes)")
# current through the pair short (limited by R_K1 + R_K2)
for I in (7.2, 17.1):
    print(f"  current in the KS-pair short at {I} A pack: {I*R_SH/(2*2.2)*1e3:.2f} mA (no fusing, silent)")
print("Consequences with I_PACK1 = 0: sense-path test step 5 SKIPPED (needs >= 0.2 A discharge);")
print("ERR_SGND_OPEN and ERR_RET_DEGRADED never evaluate (need I_PACK1 > 1 A / >= 5 A);")
print("ERR_PROFILE_OC never fires; U_C1 and U_C2 never trip; ERR_ISO_MISMATCH only in FC windows.")
# Independent estimate from the BT INA253 (boost output, facts_board 3.3)
print("Independent pack-current estimate (bonded): I_pack ~= I_batt_bus*V_bus/(eta*V_batt) + I_LM1084")
for ib in (0.3, 1.0, 2.0, 3.0):
    for vb in (7.4, 8.4):
        est = ib * 16.0 / (0.90 * vb)
        print(f"  I_batt(bus) {ib:.1f} A, V_batt {vb} V -> I_pack >= {est:.2f} A (+ LM1084 load), eta 0.90 ASSUMED")

print()
print("=" * 78)
print("Section 2. BQ29200 OUT fly-wire: open-wire behaviour, present vs proposed bias")
print("=" * 78)
VTH_MAX = 1.5; VTH_MIN = 0.8
print(f"Present (R_OVG 1k, R_OVP 1M to GND): wire open -> Q_OV gate 0 V < V_th,min {VTH_MIN} V -> "
      "OVP actuation silently lost (F25 'latent')")
R_PU = 1.0e6
i_pu = VS / R_PU
I_OL_MIN = 30e-6  # SLUSA52C 7.5: low-level output current >= 30 uA at OUT = 0.05 V
v_out_low = 0.05 * i_pu / I_OL_MIN  # linear interpolation of the sink characteristic (UNCONFIRMED shape)
print(f"Proposed (R_OVP replaced by {R_PU/1e6:.0f} MOhm to 3V3): pull-up current {i_pu*1e6:.1f} uA "
      f"< 30 uA guaranteed sink at 0.05 V -> OUT low <= about {v_out_low*1e3:.1f} mV (gate off)")
print(f"  wire open -> gate {VS:.1f} V > V_th,max {VTH_MAX} V -> Q_OV on, N1 LOW, FF1 cannot set (fail-safe, "
      "seen as ERR_CHG_ENTRY / self-test step 4)")
print(f"  OVP: OUT 6-9.5 V back-feeds 3V3 through 1 MOhm: <= {(9.5-3.3)/R_PU*1e6:.1f} uA (negligible)")

print()
print("=" * 78)
print("Section 3. LB footprint versus the free strip beside the Teensy")
print("=" * 78)
# courtyard areas (mm^2), typical IPC nominal land patterns, ASSUMED
parts = {
    "SOT-23-5/SC-70 logic (U_P33,U_CKS,U_CLS,U_BF,U_PS,U_SG1,U_SG2,U_CH1,U_CH2,U_VA,U_OR,U_AND,U_FF,U_PD)": (14, 3.5*3.5),
    "TSSOP-20 LVC244A x2": (2, 7.0*8.0),
    "TSSOP-8 INA240 x2": (2, 4.0*6.9),
    "SOT-23-6 TLV3011B x7": (7, 3.5*3.5),
    "SOT-23 BSS138 x15 + BAT54 x14": (29, 3.5*3.5),
    "0603/0805 passives (~150)": (150, 2.6*1.6),
    "0805 thin-film 49.9k x8 + C_P1 1206": (9, 3.5*2.0),
}
tot = 0.0
for k, (n, a) in parts.items():
    tot += n * a
    print(f"  {k}: {n} x {a:.1f} = {n*a:.0f} mm2")
print(f"Component courtyard total {tot:.0f} mm2; 2-layer routed at x2.0-2.5 -> {2.0*tot:.0f}-{2.5*tot:.0f} mm2 "
      "plus about 30 wire landing pads")
strip = (131.064 - 112.0) * (98.044 - 30.0)
print(f"Free strip right of J2 (x 112-131, y 30-98, RSDA/RSCL at x 112.5 excluded): about {strip:.0f} mm2 "
      "(BRD element scan; mounting holes and connector keep-outs not checked)")
