"""Battle-test round 2, datasheet re-verification lens: calculations.

Sources (vendor primaries read 2026-11-07, not saved in the repository):
  TPS2663x  SLVSE94G (June 2024): sections 6.5, 6.6, 8.3.1.1, 8.3.2.1, 8.3.3, 8.3.7, 8.3.10, Table 8-1
  BQ29200   SLUSA52C (repo copy BQ29200_TI.pdf): sections 7.3, 7.5
  SN74AHCT1G125 SCLS378P: Recommended Operating Conditions, Electrical Characteristics
  Design values from detailed_design_IC1.md revision 4 (Figures 2, 6; sections 7.5, 7.8).
Run: python bt2_datasheet_reverify_calcs.py  (stdlib only)
"""

def hdr(n, t):
    print(f"\n[{n}] {t}")

# ---------------------------------------------------------------------------
hdr(1, "TPS26631 FLT during the entry ramp (UVLO asserted, SLVSE94G 6.5/6.6/8.3.3)")
V_INSYS_MIN = 4.5            # V, operating IN_SYS minimum (6.5); below it FLT is undriven (pulled HIGH)
V_UV_R = (1.176 * 110.5 / 10.5, 1.224 * 110.5 / 10.5)   # R_UV1 100k / R_UV2 10.5k
V_UV_F = (1.09 * 110.5 / 10.5, 1.15 * 110.5 / 10.5)
T_DEASSERT = (0.500, 0.700)  # ms, tUVLO_FLT(dly) 500-700 us (6.6)
print(f"   UVLO rising {V_UV_R[0]:.2f}-{V_UV_R[1]:.2f} V, falling {V_UV_F[0]:.2f}-{V_UV_F[1]:.2f} V")
for ramp in (12.0, 5.0, 3.65, 2.6, 1.0):     # V/ms; 12 V/ms = RT1987 at CSS 5.6 nF (design 7.8)
    lo = (V_UV_R[0] - V_INSYS_MIN) / ramp + T_DEASSERT[0]
    hi = (V_UV_R[1] - V_INSYS_MIN) / ramp + T_DEASSERT[1]
    print(f"   input ramp {ramp:5.2f} V/ms: FLT LOW for {lo:5.2f}-{hi:5.2f} ms after IN_SYS passes 4.5 V"
          f"  (vs the 3 ms ERR_CHG_LADDER persistence: {'LATCH' if hi >= 3.0 else 'ok'})")
r_crit = (V_UV_R[1] - V_INSYS_MIN) / (3.0 - T_DEASSERT[1])
print(f"   ramp below {r_crit:.2f} V/ms (worst case) holds FLT LOW >= 3 ms -> ERR_CHG_LADDER on entry")
print("   While IN_SYS < 4.5 V (RT1987 t_D_ON 8 ms typ, no max) FLT is undriven -> EF_FLT_N reads HIGH")

# ---------------------------------------------------------------------------
hdr(2, "TPS26631 overload timing (SLVSE94G 6.6, 8.3.1.1, 8.3.7.1.2, 8.3.7.2.1, Table 8-1)")
I_OL = (1.84 * 9.0 / 9.09, 2.16 * 9.0 / 9.09)       # scaled from the R_ILIM 9 k row
tCL = (129, 202)          # ms, current limiting before latch (post start-up)
tCB = (20, 31)            # ms, 2x pulse support -- only after PGOOD HIGH; PGTH grounded -> never active
tTREG = (2300, 2900)      # ms, thermal-regulation timeout during start-up (SHDN/UVLO/VIN power-up)
tFLT_CL = (1.09, 1.6)     # ms, FLT in current limiting
print(f"   I_OL {I_OL[0]:.2f}-{I_OL[1]:.2f} A; fast trip 3 x I_OL = {3*I_OL[0]:.2f}-{3*I_OL[1]:.2f} A (TPS26631, not disabled by PGTH)")
print(f"   post-start overload: latch after tCL {tCL[0]}-{tCL[1]} ms (design claims tCB + tCL <= 233 ms; tCB inapplicable)")
print(f"   post-start overload: FLT LOW after {tFLT_CL[0]}-{tFLT_CL[1]} ms")
print(f"   start-up INTO an overload: thermal regulation up to {tTREG[0]/1e3:.1f}-{tTREG[1]/1e3:.1f} s, FLT only after the timeout")
for v_in, t_ms, label in ((21.47, 47, "regen pulse, longest (47 ms), VOK-gated restart each pulse"),
                          (21.47, 19, "regen pulse, shortest (19 ms)"),
                          (16.0, tTREG[1], "FC window entry, until the Treg timeout")):
    e = v_in * I_OL[1] * t_ms / 1e3
    print(f"   input energy at I_OL max, {v_in} V, {t_ms} ms ({label}): {e:6.1f} J, FLT never/late asserted")

# ---------------------------------------------------------------------------
hdr(3, "BQ29200 CD delay (SLUSA52C 7.3, 7.5; BOM CBLD 0.33 uF X7R)")
C_CD = 0.33
print(f"   recommended CCD max 0.1 uF (7.3); fitted {C_CD} uF = {C_CD/0.1:.1f} x the maximum")
for lo, hi, rng in ((6, 12, "0-60 C"), (5.5, 13.5, "-40..110 C")):
    print(f"   XDELAY {lo}-{hi} s/uF ({rng}) x {C_CD} uF = {lo*C_CD:.2f}-{hi*C_CD:.2f} s "
          f"(spec excludes capacitor variation; outside the recommended C range)")
print(f"   with X7R 5 % initial + 15 % temperature: {6*C_CD*0.80:.2f}-{12*C_CD*1.20:.2f} s (0-60 C)")

# ---------------------------------------------------------------------------
hdr(4, "AHCT1G125 pump driver current (SCLS378P recommended IOH)")
for v_h in (0.0, 3.70):
    i_pk = (5.0 - 0.30 - (v_h + 0.30 if v_h else 0.0)) / 470
    print(f"   PUMP_H at {v_h:.2f} V: first-edge current about {i_pk*1e3:5.1f} mA (recommended |IOH| max 8 mA at 4.5 V)")
