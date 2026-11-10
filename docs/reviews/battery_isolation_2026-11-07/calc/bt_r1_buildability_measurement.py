"""Battle-test round 1, buildability and measurement-integrity lens, against detailed_design_IC1.md revision 3.

Run with the repo .venv_hil python (stdlib only). Every input is cited to the design document (DD), the fact sheets
or the board file. Output is printed; no file is written.
"""
import math
import xml.etree.ElementTree as ET
import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
BRD = os.path.join(REPO, "references", "Scale Car Board PCB 20260625.brd")

def hdr(t):
    print("=" * 78); print(t); print("=" * 78)

# ---------------------------------------------------------------------------------------------------------------
hdr("A. V_PACKN divider with R_VPS in series (DD Fig. 1: PACK- -R_VPS 10k- V_PACKN_S; DD Fig. 5: 3V3 -R_V1 100k- pin23 -R_V2 100k- V_PACKN_S)")
R_V1, R_V2, R_VPS, V33 = 100e3, 100e3, 10e3, 3.3
Rlow = R_V2 + R_VPS
a = V33 * Rlow / (R_V1 + Rlow)          # offset at pin 23
b = R_V1 / (R_V1 + Rlow)                # gain from V_PACKN
print(f"  actual: V(pin23) = {a:.4f} V + {b:.4f} x V_PACKN   (DD states (3.3 + V_PACKN)/2 = 1.65 + 0.5 x V_PACKN)")
def decode_dd(vpin):  # firmware decode per DD 12.1
    return 2 * vpin - V33
for v in (-1.0, -0.65, -0.20, -0.035, 0.0, 0.15):
    vp = a + b * v
    print(f"  true V_PACKN {v:+.3f} V -> pin {vp:.4f} V -> DD decode {decode_dd(vp):+.4f} V (error {decode_dd(vp)-v:+.4f} V)")
lsb = V33 / 4095
print(f"  ADC 12 bit LSB {lsb*1e3:.3f} mV at the pin = {lsb/b*1e3:.3f} mV of V_PACKN")
for I in (1.0, 3.0, 7.2, 17.1):
    dv = I * 5e-3
    print(f"  ERR_RET_DEGRADED: +5 mOhm at {I:4.1f} A = {dv*1e3:5.1f} mV = {dv/(lsb/b):5.1f} LSB ; DD-decode offset error {decode_dd(a)*1e3:.0f} mV"
          f" -> apparent R_ret error {decode_dd(a)/I*1e3:7.1f} mOhm")

# ---------------------------------------------------------------------------------------------------------------
hdr("B. Status-ladder settling (DD Fig. 5 / calc sec 7: R = 20.0k, C_LA = C_LB = 100 nF, step 103.1 mV, decode window 30 mV)")
R, C = 20e3, 100e-9
tau = R * C
step = V33 / 32
print(f"  tau = {tau*1e3:.2f} ms ; LSB step {step*1e3:.1f} mV")
cases = {
    "entry: ladder A bit0 FF1.Q (1 LSB)": 1,
    "entry: ladder B bits0+1 SG1/SG2 (3 LSB)": 3,
    "self-test 5: ladder B bits0+1 up, bit4 UC2_N down (-13 LSB net)": 13,
    "ladder A bit4 UC1_N toggle (16 LSB)": 16,
}
for name, n in cases.items():
    dv = n * step
    t_settle = tau * math.log(dv / 0.030)
    resid_1 = dv * math.exp(-1e-3 / tau); resid_2 = dv * math.exp(-2e-3 / tau)
    print(f"  {name:62s}: settle to 30 mV {t_settle*1e3:5.2f} ms; residual at 1 ms {resid_1*1e3:6.0f} mV, at 2 ms {resid_2*1e3:6.0f} mV")
print("  DD checks: self-test steps 4-6 'within 1 ms'; entry/exit 'within 2 ms'; 12.4 item 4 mismatch persisting 2 ms -> ERR_CHG_LADDER")

# ---------------------------------------------------------------------------------------------------------------
hdr("C. U_C1 is live in the bonded mode (R_SH always in the return; DD Fig. 3 TH1 = 1.500 V = 3.00 A discharge)")
gain = 0.05  # V/A, INA240A3 x 0.5 mOhm (DD Table 15)
for hyst_mV in (2, 8):
    print(f"  TLV3011B hysteresis {hyst_mV} mV = {hyst_mV/1e3/gain:.3f} A of pack current (SBOS300C via DD Table 7)")
print("  Bonded Run pack current: BT channel 1.5-3 A bus at 16 V -> about 3.6-7.2 A pack at 7.4 V, eta 0.9 (working figures);")
print("  in-service 7.2 A (DD 7.6). Every acceleration and deceleration crosses 3 A; UC1_N = ladder A MSB (1.65 V step).")

# ---------------------------------------------------------------------------------------------------------------
hdr("D. BQ29200 bottom-cell reading in the charge mode (facts_board 5 item 1: bottom cell = VC1 - PCB GND; J-BL pos 3 removed by M12)")
R_SH, R_DS = 0.5e-3, 1.6e-3
rho_05 = 0.0172e-6 / 0.5e-6  # Ohm/m, 0.5 mm2 copper at 20 C
for L in (0.3, 0.5):
    print(f"  VBATN_X 0.5 mm2 lead {L} m: {rho_05*L*1e3:.1f} mOhm (not counted in rev 2 Table 10 / DD 12.6)")
OVP_min = 4.35 - 0.025  # facts_prior: 4.35 V +/-25 mV
for R_s in (0.020, 0.050, 0.077, 0.100):
    for I_p in (1.25, 1.75):
        off = I_p * (R_SH + R_DS + rho_05 * 0.3 + R_s)
        vb_trip = OVP_min - off
        print(f"  R_s {R_s*1e3:5.1f} mOhm, I_p {I_p:.2f} A: over-read {off*1e3:5.0f} mV -> OVP fires at true bottom cell {vb_trip:.3f} V "
              f"(pack 2 x = {2*vb_trip:.2f} V balanced)")
print("  Rev 3: BQ OUT -> Q_OV -> N1 -> FF1 clear -> ERR_CHG_TRIP -> State 99 in production (DD 9.10, OR-E).")

# ---------------------------------------------------------------------------------------------------------------
hdr("E. Ag105 module body footprint versus rework sites (BRD package AG105 outline, element CHG R180)")
t = ET.parse(BRD).getroot()
pk = [p for p in t.iter('package') if p.get('name') == 'AG105'][0]
xs, ys = [], []
for w in pk.findall('wire'):
    if w.get('layer') in ('21', '51', '39', '41'):
        xs += [float(w.get('x1')), float(w.get('x2'))]; ys += [float(w.get('y1')), float(w.get('y2'))]
el = [e for e in t.iter('element') if e.get('name') == 'CHG'][0]
ox, oy = float(el.get('x')), float(el.get('y'))
# R180: (x, y) -> (ox - x, oy - y)
bx = sorted([ox - min(xs), ox - max(xs)]); by = sorted([oy - min(ys), oy - max(ys)])
print(f"  AG105 outline on the board: x {bx[0]:.1f}-{bx[1]:.1f} mm, y {by[0]:.1f}-{by[1]:.1f} mm")
def inside(x, y):
    return bx[0] <= x <= bx[1] and by[0] <= y <= by[1]
sites = {
    "M3 cut segment D-BT-SQ (32.258, 51.054)-(32.258, 52.324)": (32.258, 51.7),
    "M11 R_KA end at C-D11 (26.162, 50.292)": (26.162, 50.292),
    "M11 R_KA end at VBT pour at D-BT-SQ (30.8-35.0 x 48.3-49.8)": (32.9, 49.0),
    "D-BT-SQ RT1987 (29.718, 50.038)": (29.718, 50.038),
    "D-BT-SQ EN bottom segment (45.466, 36.068)-(60.96, 36.068) at x = 55": (55.0, 36.068),
    "M5 candidate D-BC-RG (80.772, 25.4)-(80.772, 35.56)": (80.772, 30.0),
    "M4 D-BT-EN (66.294, 24.384)-(66.294, 29.718)": (66.294, 27.0),
}
for k, (x, y) in sites.items():
    print(f"  {k:70s}: {'UNDER the module body' if inside(x, y) else 'outside'}")
pads = {"pin 10 VIN+ (46.0, 61.94)": (46.0, 61.94), "pin 14 VBAT-1 (21.0, 56.86)": (21.0, 56.86),
        "pin 15 VBAT-2 (21.0, 54.32)": (21.0, 54.32)}
for k, (x, y) in pads.items():
    print(f"  {k:30s}: depth inside the nearest body edge {min(x-bx[0], bx[1]-x):.1f} mm")
print("  Pin pitch 2.54 mm; neighbours of 14/15: pin 13 THERM (59.40) and pin 16 VLoad- (51.78, internally Vin-, facts_board 4.1/4.2)")
