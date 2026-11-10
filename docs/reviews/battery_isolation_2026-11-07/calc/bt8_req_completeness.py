"""Battle-test round 8, requirements and completeness lens (IC1 revision 11).

Stdlib only. Every input is cited; ASSUMED values are marked.

  [1] HR2 headline recomputation (Table 22, Table 27, Table 20, PI-3) and the dead-time drain the 1.18-1.20 A omits
  [2] J-FC bench-supply setpoint of section 9.2 step 2 (16 V, 1.5 A) against the FC_VOLTAGE divider and the window draw
  [3] Gate-order dependency: D_VC1 selection <- B8 <- FC window <- commissioning <- BG-17b / B-PKN <- D_VC1 fitted
  [4] W1 duration against FC_CHG_MAX_MS
  [5] CC-B6 3V3 order-of-magnitude check
"""
import math

def hdr(n, t):
    print("=" * 100); print(f"[{n}] {t}"); print("=" * 100)

# ---------------------------------------------------------------------------------------------------------------
hdr(1, "HR2 headline numbers (detailed_design_IC1.md Tables 20, 22, 27; calc10 sections 1-3)")
I_SET = 1.25                     # A, FC profile (DD section 9.7 entry step 1)
PERIOD = 10.34                   # s, facts_prior section 7
DEAD = (0.450, 0.569)            # s per period, calc10 section 2
for d in DEAD:
    print(f"  dead {d:.3f} s: usable {(PERIOD-d)/PERIOD*100:.1f} %, I_set x usable = {I_SET*(PERIOD-d)/PERIOD:.3f} A")
print(f"  horizon = 0.2018 + 1.0 + 0.080 = {0.2018+1.0+0.080:.4f} s (PI-3: 1.282 s)")
print(f"  T_lead,min = ceil10(T_late 61 + gap 9.76) = {math.ceil((61+9.76)/10)*10} ms; T_late = ceil(60.55) = {math.ceil(60.55)} ms")
for name, t in (("61 s cycle", 5.5), ("RegenTest_decel_sweep", 91.8)):
    print(f"  D-s {name}: {t} s x 1.25 A = {t*I_SET/3.6:.1f} mAh (Table 27)")
# Bonded dead time: the pack supplies the VBT load. Table 22 bills I_set x usable only.
for i_l in (0.20, 0.30):         # A: 0.20-0.25 A State-99 logic load (pc s6, UNCONFIRMED); 0.30 A = ASSUMED I_L (B8)
    for d in DEAD:
        net = I_SET*(PERIOD-d)/PERIOD - i_l*d/PERIOD
        print(f"  net pack current with I_L,bonded {i_l:.2f} A over the {d:.3f} s dead time: {net:.3f} A")

# ---------------------------------------------------------------------------------------------------------------
hdr(2, "J-FC 16 V commissioning setpoint (DD section 9.2 step 2) against pin 24 and the window draw")
R1, R2 = 27.4e3, 10.0e3           # ino:2022-2024 (BOM R1-FC, R2-FC); SCH nets VFC-R1-FC-FC-V-R2-FC, FC-V = Teensy pin 24 (J1 31/32)
V_ABS = 3.3 + 0.3                 # V, OVDD + 0.3 (IMXRT1060CEC Table 7 as cited in calc/bt5_buildability_operability_output.txt)
Rth = R1*R2/(R1+R2)
print(f"  divider full scale = 3.3 x (R1+R2)/R2 = {3.3*(R1+R2)/R2:.3f} V (SCALE_V_FC, ino:2024)")
for vfc in (9.3, 12.0, 12.34, 13.0, 16.0):
    vth = vfc*R2/(R1+R2)
    inj = max(0.0, (vth - V_ABS)/Rth)
    print(f"  J-FC {vfc:5.2f} V: pin 24 open-circuit {vth:.3f} V (abs max {V_ABS:.1f} V); "
          f"current into the clamp at a {V_ABS:.1f} V clamp {inj*1e6:6.1f} uA (Thevenin {Rth/1e3:.2f} kOhm)")
# FC boost input current in an FC window: bus-side FC current = charger input + aux (DD Table 26; out s1)
I_CHG_BUS = (0.82, 0.93)          # A, DD section 9.11.3 step 1 (out s1)
I_AUX = (0.09, 0.15)              # A, DD Table 26
V_BUS = 15.8                      # V, DD calc11 s2 window bus 15.52-15.82 V
ETA_B = (0.97, 0.90)              # ASSUMED boost efficiency span; SLVSFP3C p.1 "up to 96.9 % at VIN 7.2 V, VOUT 16 V"
for vfc in (9.3, 12.0, 16.0):
    lo = (I_CHG_BUS[0]+I_AUX[0])*V_BUS/ETA_B[0]/vfc
    hi = (I_CHG_BUS[1]+I_AUX[1])*V_BUS/ETA_B[1]/vfc
    print(f"  window J-FC current at {vfc:5.2f} V: {lo:.2f}-{hi:.2f} A against the 1.5 A step-2 limit "
          f"({'INSIDE' if hi <= 1.5 else 'EXCEEDS at the upper end' if lo <= 1.5 else 'EXCEEDS'})")
print("  9.3 V = the bench FC supply of ML0227 (docs/boost-bringup-debug.md, 2026-11-04 log analysis)")
print("  16 V > the 15.95 V bus regulation target: the FC boost cannot boost (VIN > VOUT, TODO(verify: SLVSFP3C));")
print("  the fixed-split droop R_FC 0.094-0.353 Ohm that W1 is meant to check (calc11 s2) is then not in circuit.")

# ---------------------------------------------------------------------------------------------------------------
hdr(3, "Gate dependency chain around D_VC1 (DD Table 7 D_VC1 row; sections 9.2 step 1, 9.7, 15.2, 15.3; OR-AC)")
deps = {
    "D_VC1 part selected": ["B8 (T_M16,max)", "ruling OR-AC"],
    "B8 (T_M16,max)": ["an FC window at the hottest ambient", "a regen window (BT_BUS closed)", "V_batt 8.4 V in charge mode"],
    "an FC window at the hottest ambient": ["commissioning (sec 9.2)", "BAL_OK H (balance plug in)", "V_batt < 8.0 V (code 7)"],
    "commissioning (sec 9.2)": ["BG-17b", "B-PKN"],
    "BG-17b": ["D_VC1 fitted (M16)"],
    "B-PKN": ["D_VC1 V_F <= 0.25 V at 16.2 mA at T_min (a selected part)"],
    "BAL_OK H (balance plug in)": ["C-1 D_VC1 orientation check (D_VC1 fitted)"],
    "a regen window (BT_BUS closed)": ["Stage 2: VOK channels, pin 30 (not fitted in Stage 1, sec 14.2)"],
    "V_batt 8.4 V in charge mode": ["entry refused at >= 8.0 V (code 7) until S0-8b"],
}
def walk(node, depth=0, seen=()):
    print("  " + "   " * depth + node)
    if node in seen:
        print("  " + "   " * (depth+1) + "^^ CYCLE"); return
    for d in deps.get(node, []):
        walk(d, depth+1, seen + (node,))
walk("D_VC1 part selected")
print("  -> D_VC1 must be fitted (BG-17b, C-1, B-PKN, BAL_OK) before B8 can produce the T_M16,max that selects it.")

# ---------------------------------------------------------------------------------------------------------------
hdr(4, "W1 duration against FC_CHG_MAX_MS")
FC_CHG_MAX_MS = 30000            # ino:2633
FC_CHG_COOLDOWN_MS = 2000        # ino:2634
W1 = 60.0                        # s, DD section 15.3 W1
print(f"  W1 asks a {W1:.0f} s window; FC_CHG_MAX_MS force-closes at {FC_CHG_MAX_MS/1000:.0f} s (DD section 9.7 exit list),"
      f" then a {FC_CHG_COOLDOWN_MS/1000:.0f} s cooldown; a single 60 s window cannot occur on the specified firmware")

# ---------------------------------------------------------------------------------------------------------------
hdr(5, "CC-B6: 3V3 rail order of magnitude (UNCONFIRMED part currents)")
lb_res = 10.25e-3                # A, cc section 4 (resistive LB load)
ina240 = 2 * 2.6e-3              # A, ASSUMED max IQ per INA240 (TODO(verify: SBOS662C))
tlv = 9 * 5e-6                   # A, ASSUMED max IQ per TLV3011B (TODO(verify: SBOS300C))
tot = lb_res + ina240 + tlv
print(f"  LB total about {tot*1e3:.1f} mA against the 250 mA PJRC external budget (facts_board section 6.1):"
      f" {tot/0.250*100:.0f} % before the existing 3V3 loads")
