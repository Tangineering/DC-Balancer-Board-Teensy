"""Battle-test round 2 (FMEA lens) calculations for detailed_design_IC1.md revision 4.

Every input is taken from detailed_design_IC1.md (cited "DD"), calc/ic1_rev4_calcs_output.txt ("calc4"),
facts_board.md, or a primary named in the comment. Values without a primary are marked ASSUMED; results that
depend on them carry the same tag. Standard library only.
"""

def hdr(t):
    print("=" * 78)
    print(t)
    print("=" * 78)

# ---------------------------------------------------------------------------------------------
hdr("Section 1: SB control inputs against a negative SGND offset (FF1Q_SB LOW = PCB GND)")
# DD Fig.1: Q_Ak gate = R_GAk 4.7k from FF1Q_SB, R_PAk 100k to SGND; Q_C gate = R_CQ 10k, R_PC 100k to SGND.
# BSS138 V_GS(th) 0.8 / 1.3 / 1.5 V min/typ/max (onsemi BSS138/D Rev 7 p.2, cited in DD Table 7).
kA = 100.0 / (100.0 + 4.7)
kC = 100.0 / (100.0 + 10.0)
for vth in (0.8, 1.3, 1.5):
    print(f"   V_th {vth:.1f} V: Q_A conducts at SGND offset {vth/kA:.3f} V; Q_C at {vth/kC:.3f} V")
# Return resistance: DD 7.6 / calc section 8: both leads 32 mV at 17.1 A; lead A alone 369 mV at 17.1 A;
# DD F22: lead A open raises R_ret by 0.18 mOhm.
r_both = 0.032 / 17.1
r_A = 0.369 / 17.1
r_B = r_both + 0.18e-3
print(f"   R_ret both leads {r_both*1e3:.2f} mOhm; lead A alone {r_A*1e3:.1f} mOhm; lead B alone {r_B*1e3:.2f} mOhm")
for I in (7.2, 17.1):
    print(f"   I = {I:4.1f} A: offset both {I*r_both*1e3:5.0f} mV, lead A alone {I*r_A*1e3:5.0f} mV;"
          f" R_ret for 0.838 V offset = {0.838/I*1e3:5.1f} mOhm")
# Both leads open: the only low-resistance return left is S_CHG + VBATN_X + Ag105 sense (R_chain ~62 mOhm,
# DD 12.6 item 3 working figure). Self-bias: S_CHG conducts only while offset >= Q_A/Q_C threshold.
r_chain = 0.062  # ASSUMED working figure (DD 12.6 item 3)
for vth_off in (0.838, 1.365, 1.65):
    print(f"   both leads open: offset {vth_off:.3f} V -> S_CHG path self-limits at I = {vth_off/r_chain:5.1f} A"
          f" (above this S_CHG is fully on; below it S_CHG sits in the linear region)")
for I in (3.0, 7.2, 13.5):
    print(f"   both leads open, I {I:4.1f} A: S_CHG linear drop ~ (0.84 - I*R_chain) ->"
          f" P(S_CHG) <= {I*max(0.84 - I*r_chain, 0.0):5.2f} W; Ag105 sense reverse current {I:4.1f} A (I_DIS 4 A, DS p.20)")

# ---------------------------------------------------------------------------------------------
hdr("Section 2: Q_D5 body diode clamps D5_N whenever N1 is LOW")
# DD Fig.3: Q_D5 D = N1, S = D5_N, D5_N pulled to 3V3 by R_UD5 10k. N-MOSFET body diode: anode S, cathode D.
# calc4 section 6: N1 <= 0.20-0.32 V with P33B LOW.
i_bd = (3.3 - 0.6 - 0.32) / 10e3
print(f"   body-diode current through R_UD5 ~ {i_bd*1e3:.2f} mA")
for vn1 in (0.20, 0.32):
    for vsd in (0.45, 0.60, 0.70):  # ASSUMED small-signal BSS138 V_SD at ~0.25 mA (BSS138/D gives 1.4 V max at 0.115 A)
        print(f"   N1 {vn1:.2f} V, V_SD {vsd:.2f} V -> D5_N = {vn1+vsd:.2f} V (LVC244A V_IL max 0.8 V, V_IH min 2.0 V; expected H = 3.3 V)")

# ---------------------------------------------------------------------------------------------
hdr("Section 3: KS+ shorted to KS- (twisted pair, connector or LB): both channels read zero")
# INA240A3 gain 100, R_SH 0.5 mOhm -> 50 mV/A, midpoint 1.65 V (DD Fig.3). TH1 1.500 V, TH2 1.493 V (calc4 s.2).
mid = 1.65
print(f"   OUT1 = OUT2 = {mid:.3f} V at any pack current -> I_PACK1 = I_PACK2 = 0 A (XCHK difference 0)")
print(f"   U_C1 margin to trip {mid-1.500:.3f} V, U_C2 margin {mid-1.4932:.3f} V: never trip")
sig_inj = mid * 8.2 / (8.2 + 1.5)
print(f"   injection: SIG -> {sig_inj:.4f} V (< 1.460 V validity, < TH): self-test steps 6/7 PASS")
print("   gated checks never evaluated with I_PACK1 = 0: sense-path (>= 0.2 A), ERR_SGND_OPEN (> 1 A),")
print("   ERR_RET_DEGRADED (>= 5 A), ERR_PROFILE_OC (> I_set + 0.25 A); ERR_ISO_MISMATCH runs in FC windows only")
r_k = 2.2
print(f"   R_SH shunted by 2 x R_K = {2*r_k:.1f} Ohm: {0.5e-3/(2*r_k)*100:.4f} % of the current diverted (no fusing)")

# ---------------------------------------------------------------------------------------------
hdr("Section 4: pack negative open upstream of R_SH (R_SH, its joints, the pack connector contact)")
# facts_board 2.3: VMID -> RB3 260 Ohm -> VC1; VMID -> RB1A 100 Ohm -> VC1_CB. BQ29200 GND = PCB GND.
# DD M12 removes the J-BL position-3 negative; S_GND body diodes are downstream of R_SH (DD Fig.1).
r_par = 1.0 / (1.0 / 260 + 1.0 / 100)
v_esd = 0.6  # ASSUMED forward drop of the BQ29200 input clamp
for vcell in (3.7, 4.2):
    pn = -(v_esd + vcell)
    imax = (vcell - v_esd) / r_par
    print(f"   V_cell {vcell:.1f} V: pack(-) ~ {pn:.2f} V vs GND (KS+ common mode; INA240 range -4 V, SBOS662C 7.3);"
          f" VC1 ~ -{v_esd:.1f} V (abs max -0.3 V, SLUSA52C 7.1); board supply <= {imax*1e3:.0f} mA through RB3||RB1A")
print("   board voltage <= V_cell2 - 0.6 V = 3.1-3.6 V << LM1084 6.5 V (SNVS037H 5.5): Teensy browns out")

# ---------------------------------------------------------------------------------------------
hdr("Section 5: per-power-cycle configuration check on an FC-only bus (DD 9.7a, Q_X1 keyed to FCQ)")
T_purge = 10.34   # s, facts_prior section 7 (DD 9.7)
d_purge = 0.14    # s, upper duration
t_check = 0.5 + 0.05  # AG105_SETTLE_MS 500 ms (ino:2484) + reads (ASSUMED 50 ms)
print(f"   exposure per unscheduled check = (t_check + d_purge)/T = {(t_check + d_purge)/T_purge*100:.1f} % per boot"
      " (purge into an FC-only bus -> UV_BUS within 20 ms, DD 9.7)")

# ---------------------------------------------------------------------------------------------
hdr("Section 6: Ag105 output with the unregulated VBT load (regen profile 1.75 A)")
for il in (0.6, 1.0, 1.4):
    io = 1.75 + il
    print(f"   I_L {il:.1f} A -> I_o {io:.2f} A ({(io/2.5-1)*100:+.0f} % vs the 2.5 A Table-4 maximum); I_PACK1 sees 1.75 A only")

# ---------------------------------------------------------------------------------------------
hdr("Section 7: SB pack-positive copper upstream of F_PK")
for rint in (0.010, 0.020, 0.040):  # ASSUMED 2S pack internal resistance (pack datasheet missing, facts_prior 9)
    r = rint + 0.002 + 0.0019  # SB copper + leads (ASSUMED 2 mOhm) + return leads (1.87 mOhm)
    print(f"   R_int {rint*1e3:.0f} mOhm: prospective SB pack+ to SGND short {8.0/r:5.0f} A, F_PK (20 A) not in the loop")
