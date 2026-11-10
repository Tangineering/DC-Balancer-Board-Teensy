"""Battle-test round 8 (FMEA lens): revision-8 LB-entry resistors and the CB-LB signal sleeve.

Stdlib only. Every input is a value stated in detailed_design_IC1.md revision 11 (section, figure or
table cited inline) or a primary read in this round:
  TI SLVSE94G (TPS2663x, Sept 2018, rev. June 2024) section 6.5, 'LOW IQ SHUTDOWN (SHDN) INPUT':
    V(SHDN) open circuit 2.48-3.3 V at 0.1 uA; V(SHUTF) falling min 0.8 V; V(SHUTR) rising max 2.0 V;
    I(SHDN) leakage at V(SHDN) = 0 V: min -10 uA (sourced by the pin).
Values marked ASSUMED are not from a primary and are flagged in the report.
"""

def par(*rs):
    return 1.0 / sum(1.0 / r for r in rs)


def hdr(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


V33 = 3.30
# Section 5.2 Figure 2 / section 5.3 Figure 6
R_SD, R_SDP = 1e3, 22e3          # U_AND -> R_SD -> SHDN_EF ; R_SDP to GND at CB
R_MDS, R_MDG = 1e3, 100e3        # U_MDI -> R_MDS -> MD_G   ; R_MDG to GND at CB
R_MS1, R_MS2, R_MS3 = 100e3, 16.2e3, 22e3
R_IM, R_IMF = 10e3, 10e3
R_PGL, R_PG, R_PGP = 22e3, 1e3, 100e3
R_FLT = 10e3
I_SHDN_SRC_MAX = 10e-6           # SLVSE94G 6.5 I(SHDN) (sourced)
V_SHUTF_MIN, V_SHUTR_MAX = 0.8, 2.0

# ---------------------------------------------------------------------------------------------
hdr("1. MD_G shorted to SHDN_EF (same CB-LB sleeve, section 5.7 item 4)")
# Two LVC outputs fight through R_SD and R_MDS; they always drive opposite levels (U_MDI = NOT EF_EN).
def node(v_sd, v_md, tol=0.0, rsd=R_SD, rmds=R_MDS):
    rsd_ = rsd * (1 + tol)
    rmds_ = rmds * (1 - tol)
    g = 1 / rsd_ + 1 / rmds_ + 1 / R_SDP + 1 / R_MDG
    i = v_sd / rsd_ + v_md / rmds_ + I_SHDN_SRC_MAX
    return i / g

for ef_en in (1, 0):
    v_sd = V33 if ef_en else 0.0
    v_md = 0.0 if ef_en else V33
    vals = [node(v_sd, v_md, t) for t in (-0.01, 0.0, 0.01)]
    vals2 = [node(v_sd, v_md, t) for t in (-0.01, 0.0, 0.01)]
    print(f"EF_EN {'H' if ef_en else 'L'}: shorted node = {min(vals):.3f}-{max(vals):.3f} V "
          f"(1 % resistors, SHDN pull-up current 10 uA included)")
print(f"eFuse SHDN band: OFF guaranteed only below {V_SHUTF_MIN} V, ON guaranteed only above {V_SHUTR_MAX} V "
      f"(SLVSE94G 6.5) -> ~1.6 V is INDETERMINATE in BOTH EF_EN states")
print("Q_MD gate (TODO(select) logic-level N-MOSFET) also sits at ~1.6 V in both states.")

# Pre-revision-7 case (no R_MDS): U_MDI output (LVC, ~tens of ohms) wins -> node = NOT EF_EN (round 4 'inverted, loud')
for ef_en in (1, 0):
    v = node(V33 if ef_en else 0.0, 0.0 if ef_en else V33, rmds=25.0)
    print(f"  rev 6 (no R_MDS, ~25 Ohm LVC output, ASSUMED): EF_EN {'H' if ef_en else 'L'} -> node {v:.3f} V")

# ---------------------------------------------------------------------------------------------
hdr("2. Q_MD linear-mode dissipation while the module node is fed and Q_MD conducts partially")
R_MD = 15.0
for v_node in (15.5, 16.0, 17.5):
    pmax = v_node ** 2 / (4 * R_MD)
    print(f"V_node {v_node:.1f} V: worst Q_MD dissipation {pmax:.2f} W at I_Q = {v_node/(2*R_MD):.3f} A")
print("I_Q [A]  P_Q [W] at 16 V   P_RMD [W]")
for iq in (0.02, 0.05, 0.1, 0.2, 0.3, 0.39):
    print(f"  {iq:5.2f}   {iq*(16.0-iq*R_MD):6.2f}         {iq*iq*R_MD:5.2f}")

# Detector blind bands (values from sections 5.3 item 1, 9.7b, 7.5, Table 8)
DUMP_STEP = 0.40          # ERR_MOD_DUMP_ON step threshold (9.7b / Table 16)
I_MOD_DUMPCHK = 0.009     # module input in the dump check, pin 32 LOW (calc8 section 2)
OC_FC = 1.40              # BENCH_TEST 0 only
I_AUX = 0.15
P_MOD = (13.0, 14.8)      # Table 8 module input power, FC profile
V_CHG_WIN = (15.52, 15.82)  # in-window V_chg with the fixed split (calc11 section 2)
UIM_MIN = 1.51
print(f"\nDump check: latches only on a step > {DUMP_STEP} A; module input <= {I_MOD_DUMPCHK} A -> "
      f"I_Q up to {DUMP_STEP - I_MOD_DUMPCHK:.3f} A passes")
i_mod = [p / v for p, v in zip(P_MOD, V_CHG_WIN)]
print(f"FC window module input {min(i_mod):.3f}-{max(i_mod):.3f} A (Table 8 power / in-window V_chg)")
iq_ocfc = [OC_FC - I_AUX - im for im in (max(i_mod), min(i_mod))]
iq_uim = [UIM_MIN - im for im in (max(i_mod), min(i_mod))]
print(f"OC_FC (BENCH_TEST 0 only) trips for I_Q above {iq_ocfc[0]:.3f}-{iq_ocfc[1]:.3f} A; "
      f"U_IM (minimum 1.51 A) above {iq_uim[0]:.3f}-{iq_uim[1]:.3f} A")
iq_blind = iq_ocfc[0]
pq = iq_blind * (V_CHG_WIN[0] - iq_blind * R_MD)
print(f"-> in an FC window, I_Q <= {iq_blind:.3f} A runs to the 30 s cap undetected; at that edge "
      f"P_Q = {pq:.2f} W, P_RMD = {iq_blind**2*R_MD:.2f} W (30 s: {30*iq_blind**2*R_MD:.1f} J into R_MD)")
for rth in (125.0, 250.0, 350.0):   # ASSUMED SOT-23-class junction-to-ambient range, part not selected
    print(f"  R_thJA {rth:.0f} K/W (ASSUMED class value): P for Tj 150 C at Ta 40 C = {(150-40)/rth:.2f} W")
print("R_MD design duty (CC-18): 0.095 W mean, 51 mJ per dump; probe-cap single pulse 1.71 J")

# ---------------------------------------------------------------------------------------------
hdr("3. Other conductor pairs inside the CB-LB sleeve (single insulation failure)")
def two_src(v1, r1, v2, r2, *loads):
    g = 1 / r1 + 1 / r2 + sum(1 / r for r in loads)
    return (v1 / r1 + v2 / r2) / g
# MS-SHDN_EF (F55) with R_MS3: IN+ follows the lead node through 22 kOhm (bias pA, Cin few pF)
for ef_en, vnode in ((1, 21.5), (0, 21.5)):
    v = two_src(V33 if ef_en else 0.0, R_SD, vnode, R_MS1, R_SDP, R_MS2)
    print(f"MS-SHDN_EF, EF_EN {'H' if ef_en else 'L'}, module node {vnode} V: lead node {v:.2f} V "
          f"-> pin 8 {'HIGH' if v > 1.242 else 'LOW'} (follows EF_EN; exit hold check catches; eFuse level OK)")
print(f"  R_MS3 x 5 pF (ASSUMED IN+ capacitance) = {22e3*5e-12*1e9:.0f} ns << 150 us hold-check wait")
# MD_G-IMON
v = two_src(0.0, R_MDS, 0.0, 1e12, R_IM)
print(f"MD_G-IMON, EF_EN H: IMON node held at {v:.2f} V by U_MDI -> U_IM blind in the window (but see EF_EN L)")
v = two_src(V33, R_MDS, 0.0, 1e12, R_IM)
print(f"MD_G-IMON, EF_EN L: IMON node {v:.2f} V > 0.478 V -> UIM_N LOW -> N1 LOW -> FF1 cannot set (loud refusal)")
v = two_src(V33, R_SD, 0.0, 1e12, R_IM, R_SDP)
print(f"SHDN_EF-IMON, EF_EN H: IMON node {v:.2f} V -> U_IM trips at entry (loud)")
v = two_src(V33, R_SD, V33, R_FLT, R_SDP)
print(f"SHDN_EF-EF_FLT_N: EF_EN L -> EF_FLT_N reads {two_src(0.0, R_SD, V33, R_FLT, R_SDP):.2f} V (false FLT, loud)")
print(f"MD_G-EF_FLT_N: EF_EN H -> EF_FLT_N reads {two_src(0.0, R_MDS, V33, R_FLT, R_MDG):.2f} V (false FLT in window, loud)")
v_h = two_src(0.0, R_MDS, V33, R_PGL + R_PG, R_MDG)
print(f"PROFILE-MD_G, EF_EN H, pin 10 H: MD_G {v_h:.2f} V (Q_MD off); profile gates follow NOT EF_EN -> regen profile "
      f"(18 V threshold) in an FC window: no charge, benign")
v_l = two_src(V33, R_MDS, 0.0, R_PGL + R_PG, R_MDG)
print(f"PROFILE-MD_G, EF_EN L, pin 10 L: MD_G {v_l:.2f} V (dump intact)")
v = two_src(0.0, R_SD, V33, R_PGL, R_SDP)
print(f"PROFILE-SHDN_EF, EF_EN L, pin 10 H: SHDN_EF {v:.2f} V < 0.8 V (eFuse off)")
v = two_src(V33, R_PGL, 0.0, 1e12, R_MS2)
print(f"PROFILE-MS, pin 10 H, module cold: MS_D {v:.2f} V > 1.242 V -> pin 8 HIGH while cold -> ERR_MOD_DRAIN (loud)")

# ---------------------------------------------------------------------------------------------
hdr("4. Revision-8 resistor single faults (Appendix F later-review items 1-4)")
R_BL1, R_BL3, R_BL2 = 150e3, 47e3, 100e3
k = R_BL2 / (R_BL1 + R_BL3 + R_BL2)
rth = par(R_BL1 + R_BL3, R_BL2)
I_LEAK = 5e-6   # SN74LVC244A input current limit, TODO(verify: TI) as in the design
print(f"BAL_OK ratio {k:.4f}; Thevenin {rth/1e3:.1f} kOhm; leakage offset {I_LEAK*rth:.3f} V")
for vih in (2.0,):
    print(f"  pack voltage for BAL_OK = VIH: {vih/k:.2f} V (no leakage), {(vih+I_LEAK*rth)/k:.2f} V (5 uA) "
          f"vs LIMIT_V_BATT_MIN 7.4 V -> worst effect is a window refusal (ERR_BAL_ABSENT, not latched)")
v_lead = 8.5 * (R_BL3 + R_BL2) / (R_BL1 + R_BL3 + R_BL2)
print(f"  BAL_OK lead (between R_BL1 and R_BL3) at 8.5 V pack: {v_lead:.2f} V (section 5.7 says no sleeve "
      f"conductor above 3.6 V; source impedance {par(R_BL1, R_BL3+R_BL2)/1e3:.0f} kOhm, not a hazard source)")
v_pg = V33 * R_PGP / (R_PGL + R_PG + R_PGP)
print(f"PROFILE gate voltage with R_PGL: {v_pg:.2f} V at 3V3 3.30 V; {3.1*R_PGP/(R_PGL+R_PG+R_PGP):.2f} V at a 3.1 V VOH "
      f"(BSS138 V_GS(th) max 1.5 V, onsemi BSS138/D)")
C_VC1, C_S = 100e-9, 5e-12   # C_S ASSUMED ADC sample capacitance class
for f_read in (50.0, 1000.0):
    tau = 1.0 / (C_S / C_VC1 * f_read)
    print(f"R_VC1c open, pin 20 read at {f_read:.0f} Hz: charge-sharing drift time constant ~{tau:.0f} s "
          f"(C_S {C_S*1e12:.0f} pF ASSUMED) -> reading holds its last value; mismatch latch waits for an "
          f"80 mV pack change (fail-safe, detection delayed)")
