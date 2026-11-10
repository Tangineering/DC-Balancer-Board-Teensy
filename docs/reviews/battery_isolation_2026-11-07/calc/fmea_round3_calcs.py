"""FMEA round 3 calculations for detailed_design_IC1.md revision 5.

Stdlib only. Every input is labelled with its source; ASSUMED ranges are marked.
Run: python fmea_round3_calcs.py > fmea_round3_calcs_output.txt
"""


def hdr(t):
    print()
    print("=" * 78)
    print(t)
    print("=" * 78)


# ---------------------------------------------------------------------------
hdr("[1] D_VM (M16) short: cell 1 shorted through the balance midpoint lead")
# Loop (bonded mode): cell1+ = midpoint -> balance lead -> J-BL pin 2 -> D_VM (short) -> J-BL pin 3 barrel (GND pours)
#   -> J-BT pin 2 -> lead A || lead B -> SGND -> S_GND1 || S_GND2 -> PACK- -> R_SH -> pack(-) -> cell1-.
# Charge mode: GND -> Ag105 Vin- -> sense (reverse) -> VBATN_X -> S_CHG -> PACK-; U_C1 bonds at 2.52-3.50 A
# (design Table 10), so the loop ends in the bonded path either way.
V_cell1 = (3.0, 3.7, 4.2)                # V, 2S pack per cell (design section 7.6 floor 7.4 V)
R_cell = (0.010, 0.020, 0.040)           # Ohm, ASSUMED pack internal resistance per cell (pack datasheet missing,
                                         # facts_prior section 9; design calc5 section 1 uses 10-40 mOhm per pack)
R_bal_lead = 0.3 * 0.084                 # 24 AWG (0.205 mm2) at 84 mOhm/m, 0.3 m: ASSUMED balance lead
R_contacts = 2 * 0.010                   # balance plug contact pair, ASSUMED 10 mOhm each
R_return = 0.0017 + 0.002                # S_GND pair hot + R_SH (design 7.6) + leads A/B, ASSUMED 2 mOhm
for v in V_cell1:
    for rc in R_cell:
        r = rc + R_bal_lead + R_contacts + R_return
        print(f"  V_cell1 {v:.1f} V, R_cell {rc*1e3:4.0f} mOhm: loop {r*1e3:5.1f} mOhm -> {v/r:6.1f} A "
              f"(balance lead and plug; no fuse in the loop: F_PK is in pack positive only, design section 4.1)")
print("  Pre-revision-5 minimum impedance VMID -> GND on the board: RB3 260 Ohm || RB1A 100 Ohm = "
      f"{1/(1/260+1/100):.1f} Ohm (facts_board 2.3) -> {4.2/(1/(1/260+1/100))*1e3:.0f} mA at 4.2 V")

hdr("[1b] D_VM surge when pack negative opens during traction (row F34b event)")
# After the open, the board return is GND -> D_VM -> VMID -> midpoint: the board sees only cell 2.
# TPS61288 keeps running: VIN range 2.0-18 V (SLVSFP3C 7.3, facts_board 3.3 item 1); switch limit 12/15/17.1 A.
eta = 0.90                               # ASSUMED boost efficiency
for P_out in (20.0, 50.0, 100.0):        # W on the BT channel (vehicle traction share; ASSUMED points)
    for vc2 in (3.5, 4.0):
        vin = vc2 - 0.25                 # minus D_VM V_F at the design's 0.25 V ceiling
        i_in = P_out / (eta * vin)
        print(f"  BT output {P_out:5.1f} W, V_cell2 {vc2:.1f} V: boost input {i_in:5.1f} A "
              f"-> clipped by the switch limit to <= 12-17.1 A (min/max) through D_VM and the midpoint lead")
print("  Duration: until the Teensy browns out (LM1084 input ~3.3-3.75 V < 6.5 V) and the EN pull-downs act;"
      " with USB powering the Teensy (B13 VUSB-VIN state), until UV_BATT latches: UV_BATT_DWELL_LATCH_MS = 1000 ms"
      " (ino:2266) plus the State-99 teardown")
print("  Design requirement for D_VM: V_F < 0.25 V at the brown-out board current, I_R <= 1 uA at 4.2 V, 25 C (M16);"
      " no surge (I_FSM) requirement is stated.")
print("  Reference low-V_F part (WebSearch transcription, Nexperia PMEG2005EB characteristics table, UNCONFIRMED page):"
      " V_F 320-380 mV at 100 mA, I_R 7 uA typ / 30 uA max at 10 V, 25 C -> misses both the V_F and the I_R limit")

# ---------------------------------------------------------------------------
hdr("[2] VBATN_X (0.5 mm2) shorted to a pack-positive conductor: loop current and conductor protection")
# Bonded mode: S_CHG off, its body diode (anode PACK-, cathode VBATN_X) reverse biased.
# Loop: pack+ -> F_PK -> short -> VBATN_X lead (short point to module) -> Ag105 VBat- stubs -> internal sense R_s ->
#   VLoad-/Vin- -> GND pours -> lead A/B -> SGND -> S_GND -> PACK- -> R_SH -> pack(-).
# Charge mode: S_CHG path first (U_C1 trips at 2.52-3.50 A discharge, Q_D turns S_CHG off), then the same loop.
V_pack = (7.4, 8.4)
R_s = (0.010, 0.050, 0.100)              # Ohm, Ag105 sense: UNKNOWN (S0-1 measures it); ASSUMED range
R_lead = (0.0103, 0.0172)                # Ohm, design 12.6 item 1: 0.3-0.5 m of 0.5 mm2
R_pack = 0.020                           # ASSUMED pack R_int (2S)
R_fault = (0.0, 0.1, 0.3)                # Ohm, bolted vs resistive chafe, ASSUMED
k_pvc = 115.0                            # A s^0.5 / mm2, copper/PVC adiabatic constant (IEC 60364-4-43 table 43A)
S = 0.5                                  # mm2
i2t_wire = (k_pvc * S) ** 2
print(f"  Adiabatic limit of 0.5 mm2 PVC copper: I^2 t = (k S)^2 = {i2t_wire:.0f} A^2 s (k = 115)")
for vp in V_pack:
    for rs in R_s:
        for rf in R_fault:
            r = rs + R_lead[1] + R_pack + 0.004 + rf
            i = vp / r
            t_wire = i2t_wire / i ** 2
            print(f"  V {vp:.1f} V, R_s {rs*1e3:4.0f} mOhm, R_fault {rf*1e3:5.0f} mOhm: I = {i:6.1f} A "
                  f"({i/20*100:5.0f} % of F_PK 20 A; {i/4:5.1f} x Ag105 I_DIS 4 A); 0.5 mm2 adiabatic in {t_wire:7.2f} s")
print("  F_PK 20 A ATO: opening time at 135-200 % is seconds to minutes (SAE J1284 class curve,"
      " TODO(verify: fuse datasheet)); 0.5 mm2 continuous rating is about 8-10 A (ASSUMED) -> F_PK does not protect"
      " VBATN_X; the Ag105 internal sense (I_DIS 4 A, DS p.20 row 6) carries the full fault current.")

# ---------------------------------------------------------------------------
hdr("[3] Ladder confirmation deadlines against the measured loop gap")
loop_median, loop_p99, loop_worst = 1.131, 1.341, 9.76     # ms, design Table 11 / facts_firmware section 8
deadline_entry_exit = 5.0                                    # ms, design 9.5 steps 4 and exit 4, Table 16
persist_ladder = 3.0                                         # ms, design 12.4 item 4
for name, gap in (("median", loop_median), ("p99", loop_p99), ("worst measured", loop_worst)):
    settled = 2 * gap                                        # two identical decodes on successive iterations
    print(f"  loop {name:15s} {gap:5.2f} ms: settled reading after the edge >= {settled:5.2f} ms; "
          f"5 ms entry/exit deadline {'MET' if settled <= deadline_entry_exit else 'MISSED'}; "
          f"one undecodable read spans {gap:5.2f} ms vs 3 ms persistence {'OK' if gap <= persist_ladder else 'LATCHES'}")
print("  A single 9.76 ms iteration adjacent to a commanded pin-33 edge, or after a read that straddles a hardware edge"
      " (EF_EN, CHk_OK, D5_N, VOK toggles in Stage 2), exceeds both limits on a healthy board.")
print("  Minimum single gap that fails the 5 ms deadline when the edge is written at the end of an iteration:"
      f" 2 gaps > 5 ms -> one gap > {deadline_entry_exit/2:.2f} ms with the other at the median: "
      f"{deadline_entry_exit - loop_median:.2f} ms")

# ---------------------------------------------------------------------------
hdr("[4] ERR_VCHG_FED: dependence on a single pin-38 channel")
full_scale = 3.3 * 88.7 / 10                                 # ino:2030, calc5 section 5
print(f"  SCALE_V_CHG full scale {full_scale:.2f} V; an open upper divider leg or open ADC input reads ~0 V:"
      " ERR_VCHG_FED (threshold 11 V) and the regen-window precondition 'V_chg below 11 V' both pass.")
print("  Pin-38 health is exercised only where chargerHasPower() needs V_chg >= 13.5 V (FC window, configuration"
      " check, probe step 3) -> at most once per power cycle in Stage 2 on the vehicle (no FC window in State 2).")
