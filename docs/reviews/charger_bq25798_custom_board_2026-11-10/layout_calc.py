"""Layout-plan arithmetic for the custom BQ25798 charger board (CCB), deliverable 3.

Every input is cited in a comment.  Outputs are printed and are reproduced in sec_layout.md.
Run: C:/Users/ricky/miniforge3/python.exe -I layout_calc.py
"""
import math

MIL2_PER_MM2 = 1550.0031
OZ_MIL = {0.5: 0.689, 1.0: 1.378, 2.0: 2.756}   # copper thickness per oz (1 oz = 35 um = 1.378 mil)


def ipc2221_width_mm(i_a, dt_c, oz, external=True):
    """IPC-2221 conductor-sizing chart fit: I = k dT^0.44 A^0.725 (A in mil^2); k 0.048 ext, 0.024 int."""
    k = 0.048 if external else 0.024
    area_mil2 = (i_a / (k * dt_c ** 0.44)) ** (1 / 0.725)
    return area_mil2 / OZ_MIL[oz] / 39.3701


def ipc2221_current(w_mm, dt_c, oz, external=True):
    k = 0.048 if external else 0.024
    area_mil2 = w_mm * 39.3701 * OZ_MIL[oz]
    return k * dt_c ** 0.44 * area_mil2 ** 0.725


print("== 1. IPC-2221 widths ==")
cases = [("battery side, ICHG max 3.21 A (WD A.3)", 3.21), ("battery side, design 3.5 A (WD A.7)", 3.5),
         ("input side, eFuse I_OL max 2.41 A (WD B.4)", 2.41), ("input side, ILIM clamp max 1.76 A (WD H.4)", 1.76),
         ("SW1/SW2 strip, inductor RMS 3.37 A (this calc, sec 4)", 3.37)]
for name, i in cases:
    row = [name]
    for oz in (1.0, 2.0):
        for ext in (True, False):
            for dt in (10, 20):
                row.append(f"{'ext' if ext else 'int'} {oz:.0f}oz dT{dt}: {ipc2221_width_mm(i, dt, oz, ext):.2f} mm")
    print(" | ".join(row))
print("check vs H.22: 2.5 mm 2oz ext dT10 =", round(ipc2221_current(2.5, 10, 2.0), 1), "A; 2.0 mm 1oz ext dT10 =",
      round(ipc2221_current(2.0, 10, 1.0), 1), "A")
for w in (1.5, 2.0, 2.5, 3.0):
    print(f"  {w} mm 1oz ext: dT10 {ipc2221_current(w, 10, 1.0):.2f} A, dT20 {ipc2221_current(w, 20, 1.0):.2f} A;"
          f" 1oz int dT10 {ipc2221_current(w, 10, 1.0, False):.2f} A; 2oz int dT10 {ipc2221_current(w, 10, 2.0, False):.2f} A")

print("\n== 2. Via current and thermal resistance ==")
cu_k = 385.0       # W/m K, copper (general value)
plating = 0.025e-3  # m, 25 um barrel plating (IPC-6012 class 2 typical minimum average 20 um; 25 um assumed)
t_board = 1.6e-3
for drill in (0.2e-3, 0.3e-3):
    a = math.pi * ((drill / 2 + plating) ** 2 - (drill / 2) ** 2)
    a_mil2 = a * 1e6 * MIL2_PER_MM2
    i_int = 0.024 * 10 ** 0.44 * a_mil2 ** 0.725
    i_ext = 0.048 * 10 ** 0.44 * a_mil2 ** 0.725
    r_th = t_board / (cu_k * a)
    print(f"  drill {drill*1e3:.1f} mm: barrel {a*1e6:.4f} mm2 = {a_mil2:.1f} mil2; IPC-2221 dT10 int-k {i_int:.2f} A /"
          f" ext-k {i_ext:.2f} A; R_th through 1.6 mm {r_th:.0f} C/W per via (unfilled)")

print("\n== 3. Inductor ripple / RMS (DS Eq 5) ==")
fsw, L = 1.5e6, 1.0e-6
for vin, vsys, ichg in ((16.0, 8.82, 3.21), (20.0, 8.82, 3.21), (22.28, 8.82, 3.21), (23.63, 8.82, 3.21)):
    rip = vsys * (vin - vsys) / (vin * fsw * L)
    irms = math.sqrt(ichg ** 2 + rip ** 2 / 12)
    print(f"  VIN {vin}: ripple {rip:.2f} A pp, peak {ichg + rip/2:.2f} A, I_L rms {irms:.2f} A")

print("\n== 4. Loss budget ==")
# whole-charger efficiency read from DS Fig 6-4 (1.5 MHz, VBAT 8 V, PFM disabled, SPM6530T 1 uH): my readings,
# +/- 1 percentage point.  Fig 6-3 (750 kHz, 2.2 uH WE-LHMI 74437346022).
reads = {("1.5MHz", 20.0, 3.10): 0.907, ("1.5MHz", 15.0, 3.10): 0.928, ("1.5MHz", 20.0, 2.50): 0.912,
         ("1.5MHz", 15.0, 2.50): 0.932, ("750kHz", 20.0, 3.10): 0.924, ("750kHz", 15.0, 3.10): 0.941}
vbat = 8.0
for (f, vin, i), eta in reads.items():
    pout = vbat * i
    ploss = pout * (1 / eta - 1)
    iin = pout / eta / vin
    print(f"  {f} VBUS {vin} ICHG {i}: eta {eta:.3f}, Pout {pout:.1f} W, Ploss {ploss:.2f} W, Iin {iin:.2f} A")

# conduction split at VBUS 20 V, ICHG 3.10 A, 1.5 MHz (DS EC p.14-15 typical RDS(on) at 25 C)
vin, ichg, vsys = 20.0, 3.10, 8.4
D = vsys / vin
rip = vsys * (vin - vsys) / (vin * fsw * L)
i2 = ichg ** 2 + rip ** 2 / 12
iin = vbat * ichg / 0.907 / vin
p_q1 = D * i2 * 0.024
p_q2 = (1 - D) * i2 * 0.035
p_q4 = i2 * 0.017          # Q4 on continuously in buck mode (Q3 off)
p_rsns = iin ** 2 * 0.008
p_batfet = ichg ** 2 * 0.011
p_cond25 = p_q1 + p_q2 + p_q4 + p_rsns + p_batfet
hot = 1 + 0.004 * (100 - 25)   # typical MOSFET RDS(on) rise ~0.4 %/C (general rule; not a TI figure)
p_dcr25 = i2 * 0.0078       # SPM6530T DCR 7.8 mOhm (UG Table 4-1)
p_dcr100 = p_dcr25 * (1 + 0.00393 * 75)
ptot = vbat * ichg * (1 / 0.907 - 1)
print(f"  split @20 V/3.10 A: D {D:.3f}, I_L rms^2 {i2:.2f}; Q1 {p_q1*1e3:.0f} mW, Q2 {p_q2*1e3:.0f}, Q4 {p_q4*1e3:.0f},"
      f" RSNS {p_rsns*1e3:.0f}, BATFET {p_batfet*1e3:.0f} -> IC conduction {p_cond25*1e3:.0f} mW @25 C,"
      f" {p_cond25*hot*1e3:.0f} mW @100 C (x{hot:.2f})")
print(f"  inductor DCR {p_dcr25*1e3:.0f} mW @25 C, {p_dcr100*1e3:.0f} mW @100 C; total {ptot:.2f} W -> residual"
      f" (IC switching + gate + core + caps) {ptot - p_cond25*hot - p_dcr100:.2f} W")
# eFuse TPS26630 31 mOhm (WD U101 row, device comparison table p.2; typical)
for i in (1.37, 1.76, 2.41):
    print(f"  eFuse 31 mOhm at {i} A: {i*i*0.031*1e3:.0f} mW")


print("\n== 5. Lumped board thermal model (order of magnitude) ==")
# Revised 2026-11-10 (review run 001, CCB-R1-11/-12/-15/-20, NP-2/-5/-9): H_u per option S and K, MB pin landings
# from the .brd, MB spreading/convection node, socket contact and gap-pad interface terms, pad area net of the CCB
# underside parts, air area net of the pad, and the 2.0/2.5/2.7/2.9 W cases.  Section 5.0 keeps the legacy model.
# ---------------------------------------------------------------------------------------------------------------
# 5.0 Legacy model (superseded; kept so the earlier figures stay reproducible).  Option S geometry only, MB as a
#     fixed-temperature boundary, pad 2.4 mm in a 2.415 mm gap, air over the full 1219 mm2 in parallel with the pad.
# ---------------------------------------------------------------------------------------------------------------
print("-- 5.0 legacy (superseded by 5.1-5.9) --")
a_side = 1219e-6        # m2 per side, sec_mechanics 1.8
h_top = 10.0            # W/m2K, natural convection + radiation, still air (general handbook range 5-15; assumption)
r_top = 1 / (h_top * a_side)
k_air = 0.026
gap = 2.54e-3 - 0.125e-3   # header body minus polyimide sheet
r_gap = gap / (k_air * a_side)
# header pins: 0.64 mm square; length board-to-board path ~ 2.54 + 1.6 mm; phosphor bronze k ~ 70 W/mK (general)
a_pin = 0.64e-3 ** 2
for kpin in (70.0, 110.0):
    r_pin = (2.54e-3 + 1.6e-3) / (kpin * a_pin)
    n_eff = 6   # pins with copper on both boards: 4, 10, 14, 15, 18, 19 (signal pins 3, 7, 8, 11, 13 neglected)
    r_pins = r_pin / n_eff
    r_par = 1 / (1 / r_top + 1 / r_gap + 1 / r_pins)
    print(f"  k_pin {kpin}: R_pin {r_pin:.0f} C/W each, 6 power/GND pins {r_pins:.1f} C/W; R_top {r_top:.0f}, R_gap(air)"
          f" {r_gap:.0f} -> R_board-to-(MB, air) {r_par:.1f} C/W")
    for p in (2.0, 2.7, 2.9):
        print(f"     P {p} W: board mean rise {p*r_par:.1f} C")
for kpad in (1.0, 3.0):
    for area_mm2 in (100.0, 132.0):
        r = 2.4e-3 / (kpad * area_mm2 * 1e-6) + 0.125e-3 / (0.12 * area_mm2 * 1e-6)
        print(f"  gap pad k {kpad} W/mK, {area_mm2:.0f} mm2, 2.4 mm + 0.125 mm polyimide (k 0.12): {r:.1f} C/W")
r_pins70 = (2.54e-3 + 1.6e-3) / (70 * a_pin) / 6
for kpad in (1.0, 3.0):
    r_pad = 2.4e-3 / (kpad * 132e-6) + 0.125e-3 / (0.12 * 132e-6)
    r_par = 1 / (1 / r_top + 1 / r_gap + 1 / r_pins70 + 1 / r_pad)
    print(f"  with gap pad k {kpad} (132 mm2): R_board {r_par:.1f} C/W; rise at 2.9 W {2.9*r_par:.0f} C,"
          f" at 2.7 W {2.7*r_par:.1f} C")
for p_ic in (1.8, 2.3):
    print(f"  IC share {p_ic} W x RthJB 9.7 = {p_ic*9.7:.0f} C junction-over-board (JEDEC metric, indicative only)")

# ---------------------------------------------------------------------------------------------------------------
# 5.1 Inputs of the revised model.  Every value is either from the document / MB parse or a labelled assumption.
# ---------------------------------------------------------------------------------------------------------------
from scipy.special import k0, k1   # modified Bessel functions (miniforge scipy)
import numpy as np

print("\n-- 5.1 revised model: inputs --")
T_PCB_CCB = 1.6e-3      # CCB thickness, doc 1.3.2 (TODO(verify: CCB fab stack-up))
H_L501 = 3.0e-3         # L501 height, UG Table 4-1
T_SHEET, K_SHEET = 0.125e-3, 0.12   # polyimide sheet (doc 1.6 item 3), k general value
MALE_BODY = 2.54e-3     # TSW male body = option S H_u (doc 1.3.2); option K: H_u = h_k + male body (doc 1.3.4)
ENV_AG105 = 13.14e-3    # Ag105-proven envelope over the footprint, nominal h_s 2.54 mm (doc 1.3.2, [AG] Fig 11)
ENV_MARGIN = 1.0e-3     # proposed margin, verdict condition 2
K_FR4 = 0.30            # W/mK through-plane FR-4 (general value 0.25-0.35; assumption)
T_FR4_MB = 1.5e-3       # MB core (digest_mechanics, mtIsolate 1.5 mm)
KT_MB = 390.0 * 2 * 35e-6   # W/K, two 1 oz (35 um) GND pours on the MB (digest_mechanics board facts)
L0_WF = 2.44e-8         # W Ohm / K^2, Lorenz number (Wiedemann-Franz)
T_CONTACT = 330.0       # K, contact temperature for the WF conversion (about 57 C; assumption)
H_K = {"S": 0.0, "K3": 3.0e-3, "K5": 5.0e-3, "K8.51": 8.51e-3}   # socket seat height h_k; 8.51 mm = SSW-class body,
#   TODO(verify: Samtec SSW drawing); 3.0 and 5.0 mm = low-profile sockets, TODO(verify: socket drawing)
print(f"  KT_MB {KT_MB:.4f} W/K; FR-4 k {K_FR4}; MB core {T_FR4_MB*1e3} mm; L0 {L0_WF}; contact T {T_CONTACT} K")

# MB landing of the six thermally credited pins (digest_mechanics sec 1 and 4.1, from the .brd):
#   pins 4 (VIN-), 14, 15 (VBAT-) -> GND, solid to both MB GND pours -> MB node
#   pin 10 (VIN+) -> VCHG-IN 1.524 mm 1 oz Top trace (pad 10 is a trace end; > 20 mm run) -> fin to bottom GND
#   pins 18, 19 (VBAT+) -> VCHG Top pour, bbox x 20.143-28.651, y 43.307-49.962 (isolated from GND; feeds D-BT-SQ)
w_tr, t_cu, k_cu = 1.524e-3, 35e-6, 390.0
g_lin = K_FR4 * (w_tr + T_FR4_MB) / T_FR4_MB      # W/(m K) to bottom GND, one-t_FR4 fringe each side (approx.)
r_fin10 = 1 / math.sqrt(g_lin * k_cu * t_cu * w_tr)
m_tr = math.sqrt(g_lin / (k_cu * t_cu * w_tr))
print(f"  pin 10 on VCHG-IN 1.524 mm 1 oz: {1/(k_cu*t_cu*w_tr)/1e3:.0f} C/W per mm along the trace; fin to bottom GND"
      f" through 1.5 mm FR-4: R_fin {r_fin10:.0f} C/W (1/m {1/m_tr*1e3:.1f} mm, infinite-fin valid)")
a_pour = (28.651 - 20.143) * (49.962 - 43.307) * 1e-6
a_pour_fr = ((28.651 - 20.143) * 1e-3 + T_FR4_MB) * ((49.962 - 43.307) * 1e-3 + T_FR4_MB)
r_pour_hi = T_FR4_MB / (K_FR4 * a_pour)
r_pour_lo = T_FR4_MB / (K_FR4 * a_pour_fr)
print(f"  pins 18/19 on VCHG pour {a_pour*1e6:.1f} mm2 (bbox), through FR-4 to bottom GND: R_pour {r_pour_lo:.0f}-"
      f"{r_pour_hi:.0f} C/W (fringe area {a_pour_fr*1e6:.1f} mm2 / bbox); the D-BT-SQ -> VBT path is neglected"
      f" (conservative)")


def r_mb_fin(a, h):
    """MB spreading + convection beyond an isothermal disc of radius a, infinite convecting fin, h on both faces."""
    m = math.sqrt(2 * h / KT_MB)
    return k0(m * a) / (2 * math.pi * KT_MB * m * a * k1(m * a))


r_mb = {}
for a in (10e-3, 19.7e-3):
    for h in (10.0, 15.0):
        r_mb[(a, h)] = r_mb_fin(a, h)
        print(f"  R_MB (a {a*1e3:.1f} mm, h {h:.0f}): {r_mb[(a, h)]:.2f} C/W")
mb_area = 131.064e-3 * 98.044e-3
print(f"  MB convective floor (whole board, both faces, h 10): {1/(10*2*mb_area):.2f} C/W; finite board and the"
      f" off-centre cell raise R_MB above the infinite-fin value")
R_MB_BAND = (min(r_mb.values()), max(r_mb.values()))


def r_socket(r_e, engage=3.0e-3, film=0.05e-3):
    """Thermal resistance of one socket contact interface: WF constriction || air film around the pin."""
    if not r_e:
        return 0.0, 0.0, 0.0
    r_wf = r_e / (L0_WF * T_CONTACT)
    r_film = film / (k_air * 2 * 0.64e-3 * engage)
    return 1 / (1 / r_wf + 1 / r_film), r_wf, r_film


for r_e in (2e-3, 5e-3, 20e-3):
    rc, rwf, rfl = r_socket(r_e)
    print(f"  socket contact R_e {r_e*1e3:.0f} mOhm: WF {rwf:.0f} C/W || air film (0.05 mm over 2 x 0.64 x 3.0 mm)"
          f" {rfl:.0f} C/W -> R_c {rc:.0f} C/W per contact (TODO(verify: socket contact resistance and engagement))")

# ---------------------------------------------------------------------------------------------------------------
# 5.2 Network: nodes C (CCB mean), V (MB VCHG pour, pins 18/19 MB end), M (MB GND under the cell);
#     reference = T_MB,0 = MB temperature under the cell with the Ag105 fitted and idle and no CCB (T-K-02 as written).
#     The top surface convects to the same reference (conservative while the cabin air is cooler than T_MB,0).
#     The closed air layer is heated from above, so it is stable: conduction only, at every H_u considered.
# ---------------------------------------------------------------------------------------------------------------
I_PIN = {4: 1.37, 10: 1.37, 14: 1.93, 15: 1.28, 18: 1.93, 19: 1.28}   # A at 20 V / 3.10 A (doc 3.3.1, 60/40 split)
R_PIN_BODY_E = 1.1e-7 * 6e-3 / a_pin                                  # section 7 pin body


def network(opt, k_pin, p_w, r_mb_v, pad=None, r_e=None, pins_only=False, joule=True, r_pour=None):
    """Return dict of node rises over T_MB,0 and derived resistances.

    pad: None or dict(k=, area=, r_int=) with r_int per interface in K cm2/W.
    pins_only: drop top and air paths (for the 'met by the pins alone' check).
    """
    h_u = MALE_BODY + H_K[opt]
    gap_t = h_u - T_SHEET
    l_pin = h_u + T_PCB_CCB                               # same convention as the legacy model
    r_c = 0.0 if opt == "S" else r_socket(r_e)[0]
    r_pp = l_pin / (k_pin * a_pin) + r_c                  # one pin, CCB copper to MB landing
    a_pad = 0.0 if pad is None else pad["area"]
    a_air = a_side - a_pad
    g = {}
    g["top"] = 0.0 if pins_only else 1 / r_top
    g["gap"] = 0.0 if pins_only else 1 / (gap_t / (k_air * a_air) + T_SHEET / (K_SHEET * a_air))
    g["gnd_pins"] = 3 / r_pp                              # pins 4, 14, 15
    g["pin10"] = 1 / (r_pp + r_fin10)
    g["p1819"] = 2 / r_pp
    if r_pour is None:   # pair the optimistic pour with the better pin conductivity, and the reverse
        r_pour = r_pour_lo if k_pin >= 110.0 else r_pour_hi
    g["pour"] = 1 / r_pour
    if pad is None or pins_only:
        g["pad"] = 0.0
    else:
        r_pad = (gap_t / (pad["k"] * a_pad) + T_SHEET / (K_SHEET * a_pad) + 2 * pad["r_int"] * 1e-4 / a_pad)
        g["pad"] = 1 / r_pad
    g_cm = g["gap"] + g["gnd_pins"] + g["pin10"] + g["pad"]
    g_mb = 1e12 if r_mb_v == 0 else 1 / r_mb_v
    # nodal matrix [C, V, M]
    G = np.array([[g["top"] + g_cm + g["p1819"], -g["p1819"], -g_cm],
                  [-g["p1819"], g["p1819"] + g["pour"], -g["pour"]],
                  [-g_cm, -g["pour"], g_cm + g["pour"] + g_mb]])
    q = np.array([p_w, 0.0, 0.0])
    if joule:   # pin Joule heat (body + socket contact), half to each end
        for pin, i in I_PIN.items():
            pj = i * i * (R_PIN_BODY_E + (0.0 if (opt == "S" or not r_e) else r_e))
            far = 1 if pin in (18, 19) else 2
            q[0] += pj / 2
            q[far] += pj / 2
    t = np.linalg.solve(G, q)
    p_mb = t[2] * g_mb if r_mb_v else (q.sum() - t[0] * g["top"])
    return {"tC": t[0], "tV": t[1], "tM": t[2], "R_tot": t[0] / p_w, "p_mb": p_mb, "r_pp": r_pp, "gap_t": gap_t,
            "h_u": h_u}


def r_board_fixed(opt, k_pin, pad=None, r_e=None, pins_only=False):
    """R from the CCB mean to a fixed MB (R_MB = 0), Joule heat off: the definition used by the legacy table."""
    return network(opt, k_pin, 1.0, 0, pad, r_e, pins_only, joule=False)["R_tot"]


def p_ic(p_total):
    return (2.3 / 2.54) * (p_total - 0.15)     # doc 3.7.1: IC 2.3 W of the 2.54 W charger loss; eFuse+logic 0.15 W


print("\n-- 5.2 check: legacy geometry with the revised pin landing, MB fixed (R_MB = 0) --")
for k_pin in (70.0, 110.0):
    print(f"  option S, k_pin {k_pin:.0f}: R_board {r_board_fixed('S', k_pin):.2f} C/W (legacy six-pin credit"
          f" {1/(1/r_top + 1/r_gap + 6*k_pin*a_pin/(2.54e-3+1.6e-3)):.2f}); pins only (six pins, revised landing)"
          f" {r_board_fixed('S', k_pin, pins_only=True):.1f} C/W")

# ---------------------------------------------------------------------------------------------------------------
# 5.3 Geometry and envelope per option
# ---------------------------------------------------------------------------------------------------------------
print("\n-- 5.3 geometry per option (H_u = h_k + 2.54 mm male body; top = H_u + t_pcb + 3.0 mm L501) --")
for opt, hk in H_K.items():
    h_u = MALE_BODY + hk
    top = h_u + T_PCB_CCB + H_L501
    print(f"  {opt}: h_k {hk*1e3:.2f} mm, H_u {h_u*1e3:.2f} mm, air layer {(h_u-T_SHEET)*1e3:.3f} mm, pin path"
          f" {(h_u+T_PCB_CCB)*1e3:.2f} mm, CCB top {top*1e3:.2f} mm; margin to 13.14 mm {(ENV_AG105-top)*1e3:.2f} mm")
print(f"  h_k limit for top + 1 mm <= 13.14 mm: {(ENV_AG105-ENV_MARGIN-(MALE_BODY+T_PCB_CCB+H_L501))*1e3:.2f} mm")

# ---------------------------------------------------------------------------------------------------------------
# 5.4 Gap pad geometry: candidate x 25-36, y 54-66 less a notch for the CCB underside parts of doc 3.4.4
# ---------------------------------------------------------------------------------------------------------------
print("\n-- 5.4 gap pad area and thickness --")
pad_full = (36 - 25) * (66 - 54)
# CCB coordinates from doc Table 3.8a with the 180 deg rotation about U501 (28.2, 65.0): (x, y) -> (28.2-x, 65.0-y)
c508 = (28.2 - 1.9, 65.0 - 0.6)       # (26.3, 64.4), 0402 vertical, courtyard 1.0 x 1.9 (WD A.8 r5)
c506 = (28.2 + 1.9, 65.0 - 0.6)       # (30.1, 64.4)
sw_x = (28.2 - 1.13, 28.2 + 1.15)     # SW via centres x 27.07 .. 29.35
sw_y = (65.0 - 0.85, 65.0 - 0.30)     # y 64.15 .. 64.70
land_r = 0.25                         # 0.254 mm drill via land radius, about 0.25 mm (assumption)
x0 = min(c508[0] - 0.5, sw_x[0] - land_r)
x1 = max(c506[0] + 0.5, sw_x[1] + land_r)
y0 = min(c508[1] - 0.95, sw_y[0] - land_r)
y1 = max(c508[1] + 0.95, sw_y[1] + land_r)
clr = 0.5
nx0, nx1, ny0 = max(25.0, x0 - clr), x1 + clr, y0 - clr
notch = (nx1 - nx0) * (66.0 - ny0)
pad_cut = pad_full - notch
print(f"  underside parts: C508 ({c508[0]:.1f}, {c508[1]:.1f}), C506 ({c506[0]:.1f}, {c506[1]:.1f}), SW lands x {sw_x[0]-land_r:.2f}-{sw_x[1]+land_r:.2f},"
      f" y {sw_y[0]-land_r:.2f}-{sw_y[1]+land_r:.2f}; union x {x0:.2f}-{x1:.2f}, y {y0:.2f}-{y1:.2f}")
print(f"  notch with {clr} mm clearance to the pad edge y 66: x {nx0:.2f}-{nx1:.2f}, y {ny0:.2f}-66.00 = {notch:.1f} mm2;"
      f" pad {pad_full} -> {pad_cut:.1f} mm2")
print("  SYS-row remedy of doc 3.4.2 (0805 on L4, x about 20.0-25.2, y about 60.5): move the pad edge to x >= 25.7")
for opt in ("S", "K3", "K5"):
    gt = MALE_BODY + H_K[opt] - T_SHEET
    print(f"  {opt}: compressed thickness {gt*1e3:.3f} mm; free thickness for 10-30 % compression"
          f" {gt/0.9*1e3:.2f}-{gt/0.7*1e3:.2f} mm; legacy 2.4 mm pad compression {(1-gt/2.4e-3)*100:.1f} %")

# ---------------------------------------------------------------------------------------------------------------
# 5.5 Results.  Bands: k_pin 70-110 W/mK; R_MB 0 (fixed MB) and the fin band; socket R_e 2-20 mOhm.
# ---------------------------------------------------------------------------------------------------------------
P_CASES = (2.0, 2.5, 2.7, 2.9)
PADS = {"none": None,
        "pad k1 113": {"k": 1.0, "area": pad_cut * 1e-6, "r_int": 2.0},
        "pad k3 113": {"k": 3.0, "area": pad_cut * 1e-6, "r_int": 0.5},
        "pad k1 132": {"k": 1.0, "area": pad_full * 1e-6, "r_int": 2.0},
        "pad k3 132": {"k": 3.0, "area": pad_full * 1e-6, "r_int": 0.5}}
print("\n-- 5.5 results at 2.7 W (IC share {:.2f} W, dT_JB {:.1f} C) --".format(p_ic(2.7), 9.7 * p_ic(2.7)))
print("  columns: R_board (MB fixed) | P_MB share at R_MB band | R_total to T_MB,0 | CCB rise | MB self-heating"
      " | T_J - T_MB,0 | T_MB,0 max for T_J <= 100 C")


def band_case(opt, padkey, r_e_list):
    rows = []
    for k_pin in (110.0, 70.0):
        for r_e in r_e_list:
            for rmb in R_MB_BAND:
                pad = PADS[padkey]
                rb = r_board_fixed(opt, k_pin, pad, r_e)
                n = network(opt, k_pin, 2.7, rmb, pad, r_e)
                rise_j = n["tC"] + 9.7 * p_ic(2.7)
                rows.append((rb, n["p_mb"] / 2.7, n["R_tot"], n["tC"], n["tM"], rise_j, 100 - rise_j, n["tV"],
                             n["tV"] - n["tM"], k_pin, r_e, rmb))
    return rows


summary = {}
for opt in ("S", "K3", "K5"):
    r_e_list = [None] if opt == "S" else [0.0, 2e-3, 20e-3]
    for padkey in PADS:
        if opt != "S" and padkey.endswith("132"):
            continue
        rows = band_case(opt, padkey, r_e_list)
        lo = [min(r[i] for r in rows) for i in range(9)]
        hi = [max(r[i] for r in rows) for i in range(9)]
        summary[(opt, padkey)] = (lo, hi, rows)
        print(f"  {opt:3s} {padkey:11s}: R_board {lo[0]:.1f}-{hi[0]:.1f} | P_MB {lo[1]*100:.0f}-{hi[1]*100:.0f} %"
              f" | R_tot {lo[2]:.1f}-{hi[2]:.1f} | CCB {lo[3]:.0f}-{hi[3]:.0f} C | MB +{lo[4]:.0f}-{hi[4]:.0f} C"
              f" | T_J-T_MB,0 {lo[5]:.0f}-{hi[5]:.0f} C | T_MB,0 max {lo[6]:.0f}-{hi[6]:.0f} C"
              f" | pin-18 MB joint +{lo[7]:.0f}-{hi[7]:.0f} C over T_MB,0, +{lo[8]:.0f}-{hi[8]:.0f} C over T_MB,local")
print("  option K rows span socket R_e 0 (no contact term), 2 and 20 mOhm; split:")
for opt in ("K3", "K5"):
    for padkey in ("none", "pad k3 113"):
        for r_e_list, lab in (([0.0], "no contact term"), ([2e-3, 20e-3], "R_e 2-20 mOhm")):
            rows = band_case(opt, padkey, r_e_list)
            print(f"    {opt} {padkey:11s} {lab:16s}: R_board {min(r[0] for r in rows):.1f}-{max(r[0] for r in rows):.1f}"
                  f" C/W; T_J-T_MB,0 {min(r[5] for r in rows):.0f}-{max(r[5] for r in rows):.0f} C; T_MB,0 max"
                  f" {min(r[6] for r in rows):.0f}-{max(r[6] for r in rows):.0f} C")
print("  (pads: k1 with 2.0 K cm2/W per interface, k3 with 0.5 K cm2/W per interface, both at 10-30 % compression;"
      " TODO(verify: gap-pad datasheet))")

print("\n-- 5.6 same, with the MB as a fixed boundary at T_MB,local (the 3.7.3 table definition) --")
for opt in ("S", "K3", "K5"):
    r_e_list = [None] if opt == "S" else [2e-3, 20e-3]
    for padkey in ("none", "pad k1 113", "pad k3 113"):
        vals = []
        for k_pin in (110.0, 70.0):
            for r_e in r_e_list:
                vals.append(r_board_fixed(opt, k_pin, PADS[padkey], r_e))
        lo, hi = min(vals), max(vals)
        print(f"  {opt:3s} {padkey:11s}: R_board {lo:.1f}-{hi:.1f} C/W; T_J - T_MB,local {2.7*lo+9.7*p_ic(2.7):.0f}-"
              f"{2.7*hi+9.7*p_ic(2.7):.0f} C; T_MB,local max {100-2.7*hi-9.7*p_ic(2.7):.0f}-"
              f"{100-2.7*lo-9.7*p_ic(2.7):.0f} C")

print("\n-- 5.7 load sweep, option S (no pad / pad k1 113) and K3 (no pad), CCB rise and T_J - T_MB,0 --")
for opt, padkey, r_e_list in (("S", "none", [None]), ("S", "pad k1 113", [None]), ("K3", "none", [0.0, 2e-3, 20e-3])):
    for p in P_CASES:
        vals = []
        for k_pin in (110.0, 70.0):
            for r_e in r_e_list:
                for rmb in R_MB_BAND:
                    n = network(opt, k_pin, p, rmb, PADS[padkey], r_e)
                    vals.append((n["tC"], n["tC"] + 9.7 * p_ic(p)))
        print(f"  {opt:3s} {padkey:11s} P {p} W (IC {p_ic(p):.2f} W): CCB rise {min(v[0] for v in vals):.0f}-"
              f"{max(v[0] for v in vals):.0f} C; T_J - T_MB,0 {min(v[1] for v in vals):.0f}-{max(v[1] for v in vals):.0f} C")

# ---------------------------------------------------------------------------------------------------------------
# 5.8 The 3.7.3 table rows, re-derived
# ---------------------------------------------------------------------------------------------------------------
print("\n-- 5.8 table rows re-derived (option S) --")
req40 = (100 - 40 - 9.7 * p_ic(2.7)) / 2.7
print(f"  T_MB,local 40 C: required R_board <= {req40:.2f} C/W (MB fixed)")
for k_pin in (70.0, 110.0):
    print(f"    k_pin {k_pin:.0f}: pins only (revised landing) {r_board_fixed('S', k_pin, pins_only=True):.1f} C/W;"
          f" pins + top + air {r_board_fixed('S', k_pin):.2f} C/W")
# k_pin at which the full parallel just meets the 40 C requirement (bisection)
lo_k, hi_k = 10.0, 1000.0
for _ in range(60):
    mid = 0.5 * (lo_k + hi_k)
    if r_board_fixed('S', mid) > req40:
        lo_k = mid
    else:
        hi_k = mid
print(f"    full parallel meets {req40:.2f} C/W for k_pin >= {hi_k:.0f} W/mK (legacy landing: 76 W/mK)")
for name, ploss, iin in (("750 kHz", 2.04, 1.34), ("ICHG 2.5 A", 1.93, 1.10)):
    pt = ploss + 0.15
    pic = (2.3 / 2.54) * ploss
    req = (100 - 60 - 9.7 * pic) / pt
    s_no = [r_board_fixed('S', k) for k in (70.0, 110.0)]
    s_pad = [r_board_fixed('S', k, PADS[pk]) for k in (70.0, 110.0) for pk in ("pad k1 113", "pad k3 113")]
    print(f"  T_MB,local 60 C, {name}: P {pt:.2f} W, IC {pic:.2f} W -> R_board <= {req:.2f} C/W; no pad"
          f" {min(s_no):.1f}-{max(s_no):.1f}; with pad (113 mm2) {min(s_pad):.1f}-{max(s_pad):.1f} C/W")
    for rmb in R_MB_BAND:
        n_no = [network('S', k, pt, rmb)["tC"] for k in (70.0, 110.0)]
        n_pad = [network('S', k, pt, rmb, PADS[pk])["tC"] for k in (70.0, 110.0) for pk in ("pad k1 113", "pad k3 113")]
        print(f"    with R_MB {rmb:.1f}: T_MB,0 max no pad {100-9.7*pic-max(n_no):.0f}-{100-9.7*pic-min(n_no):.0f} C;"
              f" with pad {100-9.7*pic-max(n_pad):.0f}-{100-9.7*pic-min(n_pad):.0f} C")

# ---------------------------------------------------------------------------------------------------------------
# 5.9 Gap-pad interface sensitivity (option S, 113 mm2, k 1 and 3): compressed vs near-zero-pressure contact
# ---------------------------------------------------------------------------------------------------------------
print("\n-- 5.9 gap pad interface sensitivity, option S, 113 mm2, MB fixed --")
for k in (1.0, 3.0):
    for r_int in (0.0, 0.5, 2.0, 10.0):
        pad = {"k": k, "area": pad_cut * 1e-6, "r_int": r_int}
        gt = MALE_BODY - T_SHEET
        r_pad = gt / (k * pad["area"]) + T_SHEET / (K_SHEET * pad["area"]) + 2 * r_int * 1e-4 / pad["area"]
        print(f"  k {k:.0f}, r_int {r_int:4.1f} K cm2/W per face: R_pad {r_pad:.1f} C/W; R_board"
              f" {r_board_fixed('S', 70.0, pad):.2f} (k_pin 70) / {r_board_fixed('S', 110.0, pad):.2f} (k_pin 110) C/W")
print("  (r_int 10 illustrates a pad at about 0.6 % compression: no conductance can be credited without the datasheet)")
# header body plastic in the gap (neglected above; conservative): 22 positions x 2.54 mm x 2.5 mm, k 0.25 (assumed)
a_body = 22 * 2.54e-3 * 2.5e-3
print(f"  neglected parallel path: header body {a_body*1e6:.0f} mm2, k 0.25, 2.54 mm: {2.54e-3/(0.25*a_body):.0f} C/W"
      f" before its two dry interfaces (conservative omission)")


print("\n== 6. Area budget (courtyards per WD A.8 r5: 0402 1.9x1.0, 0603 3.0x1.45, 0805 3.4x1.8, 1206 4.75x2.3,"
      " 1210 4.75x3.2, SMA 6.6x3.1; IC courtyards estimated) ==")
cy = {"0402": 1.9 * 1.0, "0603": 3.0 * 1.45, "0805": 3.4 * 1.8, "1206": 4.75 * 2.3, "1210": 4.75 * 3.2,
      "SMA": 6.6 * 3.1, "DBV": 3.6 * 3.4, "SOT23": 3.6 * 3.4, "DCT": 4.4 * 3.4, "DCK": 2.7 * 2.6,
      "RQM": 4.9 * 4.9, "L6530": 7.6 * 7.0, "TP": 2.0 * 2.0}
power = {"RQM": 1, "L6530": 1, "1210": 5, "0805": 5, "0603": 2 + 1 + 2, "0402": 7}   # C538/539, C535, R515/R529
power_dnp = {"1210": 1, "1206": 1, "0603": 4}
eib = {"DCT": 1, "DCK": 1, "DBV": 2, "SOT23": 3, "0603": 21 + 1 + 4}
chgpins = {"0402": 3, "0603": 2}      # R518, R524, R525 0402; R526, R521 0603
tps = {"TP": 10}
deleted_cr = 3.9 * 9.4 + 6 * cy["0603"]   # J101 body (WD H.18 r5) + R130, R131A/B, R132, R176, R177


def area(d):
    return sum(cy[k] * n for k, n in d.items())


cr = 1082.0     # WD H.22(k)
a_power, a_dnp, a_eib, a_chg, a_tp = area(power), area(power_dnp), area(eib), area(chgpins), area(tps)
total = cr - deleted_cr + a_power + a_dnp + a_eib + a_chg + a_tp
print(f"  CR r6 {cr:.0f}; deleted {deleted_cr:.0f}; power fitted {a_power:.0f}, power DNP {a_dnp:.0f}; EIB {a_eib:.0f};"
      f" charger-pin passives {a_chg:.0f}; new TPs {a_tp:.0f} -> CCB total {total:.0f} mm2")
# usable: CR top 881 / bottom 591 (WD H.18); tab adds top ~(21.2-1.0)*(9.26-0.5) minus two foot circles r 3.0
tab = (21.2 - 1.0) * (9.26 - 0.5) - 2 * math.pi * 3.0 ** 2
reserve_bottom = 13.6 * 14.6   # no bottom parts under the switch-node/inductor cell (sec 3.4 of the plan)
usable_top = 881 + tab
usable_bot = 591 + tab - reserve_bottom
print(f"  tab usable per side {tab:.0f}; usable top {usable_top:.0f}, bottom {usable_bot:.0f}, sum {usable_top+usable_bot:.0f};"
      f" utilisation {total/(usable_top+usable_bot)*100:.0f} % (CR r6 was {1082/1472*100:.0f} %)")
n0603_logic = 30 + 32 + 34   # fitted 0603 parts in sec_schematic 8.5, 8.6, 8.7 (scripted count)
save = n0603_logic * (cy["0603"] - cy["0402"])
a_prime = 9.8 * 9.26 - 0.5 * 9.26
print(f"  0603->0402 for ~{n0603_logic} logic passives saves {save:.0f}; rect A' adds {a_prime:.0f} top (passives only)")
for label, t, u in (("as drawn", total, usable_top + usable_bot),
                    ("0402 logic", total - save, usable_top + usable_bot),
                    ("0402 logic + A'", total - save, usable_top + usable_bot + a_prime),
                    ("0402 logic + A' - DNP power", total - save - a_dnp, usable_top + usable_bot + a_prime)):
    print(f"  {label}: {t:.0f} / {u:.0f} = {t/u*100:.0f} %")

print("\n== 7. Header pin self-heating ==")
rho = 1.1e-7    # ohm m, phosphor bronze (general value; TSW pin alloy TODO(verify: Samtec))
r_pin_e = rho * 6e-3 / a_pin
for i in (1.28, 1.93, 1.76, 2.41):
    print(f"  {i} A: pin body {r_pin_e*1e3:.2f} mOhm -> {i*i*r_pin_e*1e3:.1f} mW; with a 20 mOhm socket contact"
          f" (assumed, TODO) {i*i*0.020*1e3:.0f} mW")
