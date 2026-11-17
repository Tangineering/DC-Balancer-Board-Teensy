"""Sim 2: MB regen chopper and V-MOT ceiling against the U101 (TCKE1401NM) OVP.

Regenerates every deck, CSV and PNG of this simulation:
    C:\\Users\\ricky\\miniforge3\\python.exe run.py            (full run)
    C:\\Users\\ricky\\miniforge3\\python.exe run.py --quick    (smoke test, a few cases)

Outputs (all inside this folder): decks/*.cir, results_*.csv, fig_*.png, waveforms.npz.
Console output is ASCII only. No file outside this folder is written, except the runner's scratch.
Every circuit value carries its source in PARAMETER SOURCES below; RESULTS.md repeats them.
"""
import os
import sys
import csv
import math
import json
import time
import itertools
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SIM, "common"))
from ngspice_run import run_deck, ngspice_version  # noqa: E402

MODELS = os.path.join(SIM, "models")
TL431_LIB = os.path.join(MODELS, "TL431_TI_SLVM071.lib")
DECKS = os.path.join(HERE, "decks")
os.makedirs(DECKS, exist_ok=True)

QUICK = "--quick" in sys.argv
WORKERS = 8

# ---------------------------------------------------------------------------------------------------------------
# PARAMETER SOURCES
#  MB topology (references/Scale_Car_Board_20260624.sch, net list):
#   V-MOT @8852: D-MT-EN.VOUT C-D6.1 J-M.1 C-D7.1 D-BC-RG.VIN R1-SNT.2 R-GS.2 Q-SNT.SOURCE Z-SNT.K CAL.1
#   RGN-V @9096: R1-SNT.1 R2-SNT.2 U-SNT.REF          (Teensy pin 39 joins by label, sch line 7698)
#   N$36  @9114: U-SNT.CATHODE R-G.2 ;  VG @9121: R-G.1 R-GS.1 Q-SNT.GATE Z-SNT.A ;  N$39 @9141: Q-SNT.DRAIN R-SHUNT.1
#   VCHG-IN @9064: R1-CHG.2 D-BC-RG.VOUT C-D8.1 D-BC-FC.VOUT C-D10.1 CHG.VIN+ (CHG = the CR J1 pin 10)
#   GND @8493 includes R2-SNT.1, U-SNT.ANODE, R-SHUNT.2, CAL.2
#  Values: sch part lines 5913-5986; BOM "Scale Car Design PCB BOM 20260622.csv" lines 30 (CAL 470uF 35V, 80 mOhm),
#   33 (R-SHUNT 47 ohm +-5 %, 20 W), 34 (BSP170P), 35 (TL431BIDBZR), 36-37 (R1-SNT 78.7k / R2-SNT 10k, 0.1 %),
#   38 (BZT52C12), 39 (R-GS 3.3k 0.1 %), 40 (R-G 220 ohm 0.1 %), 81 (C-D6/C-D7 10uF 35V X7R 1206).
#  TL431BI: references/Datasheets/TL431_TI.pdf section 6.12: Vref 2483/2495/2507 mV, VI(dev) 14/34 mV,
#   dVref/dVKA -1.4/-2.7 mV/V (Vref..10 V), -1/-2 mV/V (10..36 V), Iref 2/4 uA, II(dev) 0.8/2.5 uA.
#  BSP170P: BSP170P_Infineon.pdf p.2: VGS(th) -2.1/-3/-4 V, RDS(on) 239/300 mOhm at -10 V, Ciss 328 pF.
#  BZT52C12: BZT52C_Diodes.pdf table: Vz 11.4-12.7 V at 5 mA (used as BV 12 V).
#  RT1987 (D-MT-EN, D-BC-RG): RT1987_DS-00.pdf EC: RON 20 mOhm typ (no max), VFWD 35 mV, VOVP_R 33 V min
#   (POVP grounded, no max), tBLK_OVP 512 us, "Latch off. No restart."; 40 V abs max (section 10).
#  U101 TCKE1401NM: tcke1401nm.pdf Table 10.1: RON 44.5 mOhm typ / 80 mOhm max; VOVPR 1.18/1.233/1.298 V,
#   VOVPF 1.09/1.15/1.187 V, OVP pin leakage +-320 nA; Table 10.3: OVP_toff 0.74-3 us, OVP_ton
#   190 + 14.5 x C_dVdT[nF] us; section 7.1 Formula 2: t_dVdT = 20.8e3 x VIN x C_dVdT.
#   Divider R102 845k / R103 64.9k / R104 51.1k (gen/netlist.py 111-116), C101 22 nF (netlist.py 119).
#   OVP band: design doc B.4 R102/R103/R104 row: 22.19/23.19/24.41 V rising, 20.50/21.63/22.32 V falling.
#  CR input caps (gen/netlist.py 95-99): C102a 1uF, C102b 4.7uF (2.96 uF effective at 24.41 V, design doc B.4),
#   C102c 100 nF; D107 SMAJ33A (VBR 36.7-40.6 V, Vc 53.3 V at Ipp, design doc B.4 D107 row). C103 1uF (netlist 121).
#  BQ25798 regen image (design doc G.1 mode images): VINDPM 19.0 V, IINDPM 1.70 A, ICHG 2.50 A interim / 3.10 A;
#   ILIM regen clamp 1.328-1.752 A (design doc F.3 single-fault table, H.4); VINDPM band 18.62-19.38 V (F.3 table).
#   VREG 8.32 V interim (G.1); pack floor 7.4 V (CLAUDE.md fw v30 LIMIT_V_BATT_MIN).
#  Path resistance R_PATH_RG 0.12-0.19 ohm (design doc F.3, H.19).
#  Regen burst: docs/reviews/charger_eval_2026-11-05/round2/regen_dynamics.md section 0 item 4 (11.1 W / 0.30 s,
#   18.9 W / 0.58 s at the -12 A rail), design doc F.3 (23 W case, I_regen,pk 1.1 A), section 1.1 (onset < 5 ms).
#  VESC housekeeping 7-20 mA (docs/vrgn_measurement_error_2026-11-05.md 7.2, swapped-pinout row).
#  RGN-V sink (faulty): vrgn doc 7.1 item 3: I = (V_node - V_on)/R, V_on 1.19-1.25 V, R 9.2-9.5 kOhm; small-signal
#   gain implies 13-17 kOhm; 30.9 uA at a node of 1.522 V (15.93 V bus, vrgn doc section 2, review 4.1).
#  V_rgn scale: teensy_controller.ino:2032 SCALE_V_RGN = 3.3 x 88.7/10/4095 per count.
# ---------------------------------------------------------------------------------------------------------------

VBUS = 15.9            # regulated VBUS (CLAUDE.md, V_BUS_NOMINAL 16.0, measured 15.9 V)
RGN_GAIN = 88.7 / 10.0  # SCALE_V_RGN numerator (ino:2032)
ADC_LSB = 3.3 * RGN_GAIN / 4095.0

# ---- chopper states --------------------------------------------------------------------------------------------
# dv0: shift of Vref from 2.495 V (25 C value plus temperature deviation VI(dev), taken as +-34 mV, the full
#   datasheet VI(dev) maximum applied in one direction, as in the review 4.1 band).
# s1/s2: |dVref/dVKA| in V/V below/above 10 V. The datasheet gives typ and max only; the high corner uses 0
#   (ASSUMPTION: smallest effect, no minimum stated).
# iref: REF input current Iref + II(dev): 0 (low), 2 uA (typ), 6.5 uA (high).
CHOPPERS = {
    # name        tl431 dv0      s1      s2     iref    r1tol   r2tol  rsh    vto   sink  tl431_on
    "H-lo":  dict(dv0=2.483 - 0.034 - 2.495, s1=2.7e-3, s2=2.0e-3, iref=0.0, r1=78.7e3 * 0.999, r2=10e3 * 1.001,
                  rsh=47 * 0.95, vto=-2.1, sink=None, tl431=True, desc="healthy, low corner"),
    "H-typ": dict(dv0=0.0, s1=1.4e-3, s2=1.0e-3, iref=2e-6, r1=78.7e3, r2=10e3,
                  rsh=47.0, vto=-3.0, sink=None, tl431=True, desc="healthy, typical"),
    "H-hi":  dict(dv0=2.507 + 0.034 - 2.495, s1=0.0, s2=0.0, iref=6.5e-6, r1=78.7e3 * 1.001, r2=10e3 * 0.999,
                  rsh=47 * 1.05, vto=-4.0, sink=None, tl431=True, desc="healthy, high corner"),
    # Faulty: measured knee sink on RGN-V (it already contains the REF current, so iref = 0). TL431 typical and connected
    # (it still regulates if REF reaches Vref).
    "F-k9":  dict(dv0=0.0, s1=1.4e-3, s2=1.0e-3, iref=0.0, r1=78.7e3, r2=10e3, rsh=47.0, vto=-3.0,
                  sink=dict(von=1.22, rk=9.35e3, isoft=0.0), tl431=True,
                  desc="faulty, knee 1.22 V / 9.35 kOhm (bus-dip fit), TL431 connected"),
    "F-k15": dict(dv0=0.0, s1=1.4e-3, s2=1.0e-3, iref=0.0, r1=78.7e3, r2=10e3, rsh=47.0, vto=-3.0,
                  sink=dict(von=1.522 - 15e3 * 30.9e-6, rk=15e3, isoft=0.0), tl431=True,
                  desc="faulty, knee 1.06 V / 15 kOhm (small-signal-gain fit through 30.9 uA at 1.522 V)"),
    "F-soft": dict(dv0=0.0, s1=1.4e-3, s2=1.0e-3, iref=0.0, r1=78.7e3, r2=10e3, rsh=47.0, vto=-3.0,
                   sink=dict(von=1.22, rk=9.35e3, isoft=1.0), tl431=True,
                   desc="faulty, knee + constructed two-junction soft clamp (hypothesis, not measured)"),
    "F-open": dict(dv0=0.0, s1=1.4e-3, s2=1.0e-3, iref=0.0, r1=78.7e3, r2=10e3, rsh=47.0, vto=-3.0,
                   sink=dict(von=1.22, rk=9.35e3, isoft=0.0), tl431=False,
                   desc="faulty, knee 1.22 V / 9.35 kOhm, TL431 cathode open (chopper can never trip)"),
}

# Soft-clamp constant: I_soft = IS2 * (exp(V/(2 Vt)) - 1), with IS2 set so that the soft path carries 36 uA at a node
# of 2.050 V (an 18.18 V reading), which together with the knee puts V-MOT at about 28 V for that reading.
VT = 0.02585
I_SOFT_REF, V_SOFT_REF = 36e-6, 2.050   # written as I_ref*exp((V - V_ref)/(2 Vt)) to keep exp() arguments small

# ---- U101 OVP corners (rise, fall) referred to VCHG-IN; "lo-leak" adds the +-320 nA OVP pin leakage
#      x Thevenin 48.4 kOhm x divider gain 18.81 = 0.29 V (review PWR-2 mechanism, applied here to OVP).
#      SUPERSEDED 2026-11-15 (review R2-SIM-0): this corner omits the UVLO-pin leak (also +-320 nA, TCKE1401NM DS
#      Rev. 3.0 Table 10.1) and the 0.1 % resistor tolerance. The sim 5 model (../efuse_decay/run.py part_a) gives
#      OVP rising 21.588-25.019 V. run_r2.py applies that model; the entries below are kept so that the 2026-11-14
#      outputs stay reproducible.
R102, R103, R104 = 845e3, 64.9e3, 51.1e3
GAIN_OVP = (R102 + R103 + R104) / R104
RTH_OVP = R104 * (R102 + R103) / (R102 + R103 + R104)
LEAK_SHIFT = 320e-9 * RTH_OVP * GAIN_OVP
OVPS = {
    "lo": (1.18 * GAIN_OVP, 1.09 * GAIN_OVP),
    "typ": (1.233 * GAIN_OVP, 1.15 * GAIN_OVP),
    "hi": (1.298 * GAIN_OVP, 1.187 * GAIN_OVP),
    "lo-leak": (1.18 * GAIN_OVP - LEAK_SHIFT, 1.09 * GAIN_OVP - LEAK_SHIFT),
}
# Retuned OVP bands (Part F, a design option for the VR-2 operator question, not the fitted parts): the divider gain is
#   scaled so that (r24) the typical rising threshold is 24.0 V, or (r244) the minimum rising threshold is 23.40 V,
#   i.e. above the H-hi chopper onset 23.10 V plus the 0.29 V pin-leakage shift. The leakage shift is scaled with the
#   gain (ASSUMPTION: same divider Thevenin resistance).
for _tag, _g in (("r24", 24.0 / 1.233), ("r244", 23.40 / 1.18)):
    _ls = LEAK_SHIFT * _g / GAIN_OVP
    OVPS[f"{_tag}-lo"] = (1.18 * _g, 1.09 * _g)
    OVPS[f"{_tag}-typ"] = (1.233 * _g, 1.15 * _g)
    OVPS[f"{_tag}-hi"] = (1.298 * _g, 1.187 * _g)
    OVPS[f"{_tag}-lo-leak"] = (1.18 * _g - _ls, 1.09 * _g - _ls)
C_DVDT = 22e-9
T_OVP_ON = (190 + 14.5 * C_DVDT * 1e9) * 1e-6     # 509 us
SR_DVDT = 1.0 / (20.8e3 * C_DVDT)                # 2185 V/s = 2.19 V/ms

# ---- charger (BQ25798 regen image) corners: P_in = VBAT x ICHG / eta (ASSUMPTION eta), I cap = min(IINDPM, ILIM).
CHARGERS = {
    "none": None,  # charger not converting (P5 LOW, FC image or EN_CHG 0): U101 still conducts, no draw
    # "lo": design doc H.7 row 1 (line 3369): ICHG 2.50 A image, pack 7.40 V, eta_max 0.93, ICHG -6.5 % -> 18.8 W
    #   absorption capability; regen clamp minimum 1.328 A (H.4); VINDPM band top 19.38 V (F.3).
    "lo": dict(p=18.8, ilim=1.328, vindpm=19.38),
    # "d310": design doc H.7 row 1: ICHG 3.10 A design image, input-limited at the 1.328 A clamp minimum (21.76 W).
    "d310": dict(p=21.76, ilim=1.328, vindpm=19.0),
    "nom": dict(p=8.0 * 2.50 / 0.92, ilim=1.70, vindpm=19.0),
    "hi": dict(p=8.32 * 3.10 / 0.90, ilim=1.70, vindpm=18.62),
}
T_REQUAL = 0.300       # FR-23 T_REGN_MAX provisional 300-400 ms (review 4.2); 0 = no re-qualification

# ---- node capacitance on V-MOT (CAL + C-D6/C-D7 + VESC bulk): design T-E-04 values 0.4 / 0.97 mF, regen_dynamics 4 mF
CVMOTS = {"0.4mF": 0.4e-3, "0.97mF": 0.97e-3, "4mF": 4.0e-3}

# ---- VESC over-voltage cut (regen_dynamics.md section 0 item 1; UNCONFIRMED reading of the VESC firmware):
#   regen stops when V-MOT exceeds l_max_vin (VCUT), the VESC coasts for its fault-stop time (500 ms default,
#   ASSUMPTION; the logged pulse spacing is 0.523-0.562 s including a 19-47 ms rise), then re-arms and the current
#   ramps back with a first-order 2 ms time constant (ASSUMPTION; logged onset within 5 ms). The decay between pulses
#   is the 15 mA housekeeping draw (logged 14-20 V/s at 0.97 mF = 13.6-19.4 mA). The cut level is unknown; it is swept.
VCUTS = [21.0, 22.0, 23.0, 24.0, 25.2, 27.0, 30.0]
T_VESC_STOP = 0.500
TAU_VESC_REARM = 2e-3
TP_CUT = 1.2           # brake command length for the cut runs: 1.2 s holds two re-arms (YP0166 shows three pulses)

T0 = 0.010             # burst start
TRISE = 0.005          # regen onset < 5 ms (regen_dynamics 1.1)
TFALL = 0.020          # ASSUMPTION


def softplus(x, vs):
    """Overflow-safe softplus string: vs*ln(1+exp(x/vs)), without exp() of a large argument."""
    return f"(({x})>0 ? ({x}) + {vs}*ln(1+exp(-({x})/{vs})) : {vs}*ln(1+exp(({x})/{vs})))"


def chopper_block(c):
    """Netlist lines for the chopper and the RGN-V node."""
    L = []
    L.append(f"R1SNT vmot rgn {c['r1']:.6g}")
    L.append(f"R2SNT rgn 0 {c['r2']:.6g}")
    if c["tl431"]:
        L.append(f"XU kint 0 refi TL431")
        # Corner wrapper: internal reference input = REF - (Vref_eff - 2.495); Vref_eff falls with VKA.
        L.append(f"EOFF refi rgn VALUE={{ -({c['dv0']:.6g} - {c['s1']:.6g}*(min(V(kint),10)-2.495)"
                 f" - {c['s2']:.6g}*max(V(kint)-10,0)) }}")
        L.append(f"IREF rgn 0 DC {c['iref']:.6g}")
        L.append("RG kint vg 220")
    else:
        L.append("* TL431 cathode open: U-SNT and R-G carry no current (F-open); kint kept as a probe node")
        L.append("RKPROBE kint vg 1e9")
    L.append("RGS vg vmot 3.3k")
    L.append("DZ vg vmot DZ12")
    L.append("CGS vg vmot 328p")
    L.append("M1 drn vg vmot vmot PBSP170 L=1u W=1u")
    L.append(f"RSH drn 0 {c['rsh']:.6g}")
    s = c["sink"]
    if s:
        L.append(f"BSINK rgn 0 I={{ {softplus('V(rgn)-' + format(s['von'], '.6g'), 0.02)}/{s['rk']:.6g}"
                 f" + {s['isoft']}*{I_SOFT_REF:.6g}*exp((min(V(rgn),2.45)-{V_SOFT_REF})/{2*VT:.6g}) }}")
    return L


MODEL_LINES = [
    ".model DZ12 D(BV=12 IBV=5m RS=10 CJO=50p)",
    "* BSP170P behavioural level-1 (BSP170P_Infineon.pdf p.2): KP from RDS(on) 0.239 ohm at VGS -10 V, VTO -3 V typ",
    ".model PBSP170 PMOS(LEVEL=1 VTO={vto} KP=0.6 LAMBDA=0.01 RD=0.03 RS=0.03)",
    "* D107 SMAJ33A behavioural: VBR(min) 36.7 V, dynamic resistance from Vc 53.3 V at Ipp 7.5 A (ASSUMPTION Ipp)",
    ".model DTVS D(BV={vbr} IBV=1m RS=2.0 CJO=1n)",
]


def build_deck(chop, ovp, chg, cvmot, ipk=1.0, tp=0.6, mode="I", preg=0.0, tstop=None, requal=T_REQUAL,
               rt_ovp=33.0, vbr=36.7, ron_u=0.0445, dt_max=10e-6, title="chopper sim2", vcut=None,
               u101_latch=False, lib=None, u101_body=None):
    c = CHOPPERS[chop]
    vr, vf = OVPS[ovp]
    ch = CHARGERS[chg]
    if tstop is None:
        tstop = T0 + TRISE + tp + TFALL + 0.45
    L = [f"* {title}", f".include \"{lib or TL431_LIB}\"",
         ".options method=gear reltol=1e-3 abstol=1e-9 vntol=1e-5 itl4=200"]
    for m in MODEL_LINES:
        L.append(m.format(vto=c["vto"], vbr=vbr))
    # VBUS and D-MT-EN (RT1987, VIN = VBUS, VOUT = V-MOT): ideal diode, forward drop VFWD 35 mV + I x RON.
    L.append(f"VBUS vbus 0 DC {VBUS}")
    L.append(f"BDMT vbus vmot I={{ {softplus('V(vbus)-V(vmot)-0.035', 0.002)}/0.02 }}")
    # V-MOT capacitance (CAL ESR 80 mOhm BOM line 30; lumped with VESC bulk) and VESC housekeeping 15 mA.
    L.append(f"CVM vmesr 0 {cvmot:.6g} IC={VBUS - 0.035}")
    L.append("RVMESR vmot vmesr 0.08")
    L.append(f"CD67 vmot 0 8u IC={VBUS - 0.035}")
    L.append("IHK vmot 0 DC 0.015")
    # Regen source into V-MOT
    t1, t2, t3 = T0 + TRISE, T0 + TRISE + tp, T0 + TRISE + tp + TFALL
    L.append(f"VENV env 0 PWL(0 0 {T0} 0 {t1} 1 {t2} 1 {t3} 0)")
    # VESC over-voltage cut: vf = fault latch (set above VCUT while braking), tf = fault-stop timer, gt = current gate.
    if vcut is None:
        L.append("VGT gt 0 1")
        L.append("VVF vf 0 0")
    else:
        L.append("CVF vf 0 1u IC=0")
        L.append(f"BVF 0 vf I={{ (V(vmot)>{vcut:.6g} && V(env)>0.05) ? (1-V(vf))*1e-2 : "
                 f"((V(tf)>1 || V(vf)<0.5) ? -V(vf)*1e-2 : 0) }}")
        L.append("CTF tf 0 1u IC=0")
        L.append(f"BTF 0 tf I={{ V(vf)>0.5 ? 1e-6/{T_VESC_STOP:.6g} : -V(tf)*1e-2 }}")
        L.append("CGT gt 0 1u IC=1")
        L.append(f"BGT 0 gt I={{ V(vf)>0.5 ? -V(gt)*1e-2 : (1-V(gt))*1e-6/{TAU_VESC_REARM:.6g} }}")
    if mode == "I":
        L.append(f"BREG 0 vmot I={{ {ipk:.6g}*V(env)*V(gt) }}")
    else:  # constant power P (W) at V-MOT
        L.append(f"BREG 0 vmot I={{ {preg:.6g}*V(env)*V(gt)/max(V(vmot),5) }}")
    L += chopper_block(c)
    # D-BC-RG (RT1987, VIN = V-MOT, VOUT = VCHG-IN), with OVP 33 V min, blanking 512 us, latch off.
    L.append("CTRT trt 0 1u IC=0")
    L.append(f"BTRT 0 trt I={{ V(vmot)>{rt_ovp} ? 1e-6/512e-6 : -V(trt)*1e-3 }}")
    L.append("CLAT lat 0 1u IC=0")
    L.append("BLAT 0 lat I={ (V(trt)>1 || V(lat)>0.5) ? (1-V(lat))*1e-2 : -V(lat)*1e-2 }")
    L.append(f"BDRG vmot vchgmb I={{ (1-V(lat))*{softplus('V(vmot)-V(vchgmb)-0.035', 0.002)}/0.02 }}")
    # MB VCHG-IN: C-D8, C-D10 (10 uF 50 V X5R 0805; 3 uF each effective, ASSUMPTION), R1-CHG/R2-CHG 88.7 kOhm
    L.append("CD810 vchgmb 0 6u IC=15.8")
    L.append("RCHGDIV vchgmb 0 88.7k")
    # MB trace + J1 pin 10 to the CR: 150 nH (H.19 upper), 10 mOhm
    L.append("LMB vchgmb vmbl 150n")
    L.append("RMB vmbl vin 0.01")
    # CR: C102a/b/c effective 0.6 + 2.96 + 0.1 uF, D107, OVP/UVLO string 961 kOhm
    L.append("CIN vin 0 3.66u IC=15.8")
    L.append("RCIN vin 0 961k")
    L.append("VD107 vin vd107 0")
    L.append("D107 0 vd107 DTVS")
    # U101 OVP comparator with hysteresis (switch model), turn-on delay timer, dV/dT ramp.
    vt, vh = (vr + vf) / 2, (vr - vf) / 2
    L.append("VONE one 0 1")
    L.append("SOVP one flag vin 0 SWOVP")
    L.append(f".model SWOVP SW(VT={vt:.5f} VH={vh:.5f} RON=1 ROFF=1e9)")
    L.append("RFLAG flag 0 1k")
    L.append("CFLAG flag 0 1n")
    if u101_latch:
        # Latching OVP variant: once the comparator trips, U101 stays off for the rest of the run (flg = latched flag).
        L.append("CUL ul 0 1u IC=0")
        L.append("BUL 0 ul I={ (V(flag)>0.5 || V(ul)>0.5) ? (1-V(ul))*1e-2 : 0 }")
        L.append("BFLG flg 0 V={ max(V(flag), V(ul)) }")
    else:
        L.append("BFLG flg 0 V={ V(flag) }")
    L.append("CTMR tmr 0 1u IC=2")
    L.append(f"BTMR 0 tmr I={{ V(flg)>0.5 ? -V(tmr)*1 : (V(tmr)<2 ? 1e-6/{T_OVP_ON:.6g} : 0) }}")
    L.append("CVR vr 0 1u IC=80")
    L.append(f"BVR 0 vr I={{ V(flg)>0.5 ? -V(vr)*1 : ((V(tmr)>1 && V(vr)<80) ? {SR_DVDT:.6g}*1e-6 : 0) }}")
    L.append(f"BU101 vin vout I={{ max(0, min((V(vin)-V(vout))/{ron_u:.6g}, 50*(min(V(vr),V(vin))-V(vout)))) }}")
    if u101_body is not None:
        # 2026-11-15 (review R2-SIM-7): no reverse blocking. The CR ties VSYS to VIN and leaves BGATE/DRV open
        # (gen/netlist.py U101 pins 1, 2, 5 = VCHGIN, 3 and 4 open), so TCKE1401NM DS Rev. 3.0 section 7.6 and
        # Figure 7.1 (right) give no reverse-current blocking. The internal FET body diode conducts from VOUT (anode)
        # to VIN (cathode) at all times, as in sim 5 (../efuse_decay/RESULTS.md section 2.2). The datasheet gives no
        # body-diode data: ideality 1, forward voltage u101_body (V) at 1 mA, RS 50 mOhm (ASSUMPTION).
        _is = 1e-3 / (math.exp(u101_body / VT) - 1.0)
        L.append("VDBODY vout vdb 0")
        L.append("DBODY vdb vin DBODYM")
        L.append(f".model DBODYM D(IS={_is:.6g} N=1 RS=0.05 CJO=100p)")
    # VCHGOUT: C103 1 uF; W1/W2 + EVM input (0.05 ohm, 0.15 uH); EVM input caps 25 uF effective (ASSUMPTION)
    L.append("CC103 vout 0 1u IC=15.8")
    L.append("LW vout vwl 0.15u")
    L.append("RW vwl vbe 0.05")
    L.append("CEVM vbe 0 25u IC=15.8")
    L.append("BIQCHG vbe 0 I={ 1m*tanh(V(vbe)/0.5) }")
    # Charger: I = rdy x min(Ilim, P/V, Gv (V - VINDPM)), first-order lag 100 us; re-qualification timer.
    if ch is None:
        L.append("VICF icf 0 0")
        L.append("VRDY rdy 0 0")
    else:
        L.append("CTQ tq 0 1u IC=2")
        if requal > 0:
            L.append(f"BTQ 0 tq I={{ V(flg)>0.5 ? -V(tq)*1 : ((V(vout)>0.95*V(vin) && V(tq)<2) ? 1e-6/{requal:.6g} : 0) }}")
        else:
            L.append("BTQ 0 tq I={ V(tq)<2 ? 1e-3 : 0 }")
        L.append("BRDY rdy 0 V={ V(tq)>1 ? 1 : 0 }")
        L.append(f"BICMD icmd 0 V={{ V(rdy)*min({ch['ilim']:.6g}, min({ch['p']:.6g}/max(V(vbe),5),"
                 f" max(0, 10*(V(vbe)-{ch['vindpm']:.6g})))) }}")
        L.append("RICF icmd icf 1")
        L.append("CICF icf 0 100u IC=0")
        L.append("BCHG vbe 0 I={ V(icf) }")
    L.append(f".tran 2u {tstop:.6g} 0 {dt_max:.3g} UIC")
    L.append(".end")
    return "\n".join(L) + "\n"


VECS = ["time", "vmot", "rgn", "vchgmb", "vin", "vout", "vbe", "flag", "flg", "drn", "icf", "rdy", "lat",
        "vd107#branch", "env", "vg", "kint", "vf", "gt", "vdbody#branch"]
# Saved decks include the TL431 library by a path relative to the decks/ folder; run ngspice with decks/ as the working
# directory (run.py itself always passes the absolute path).
LIB_REL = "../../models/TL431_TI_SLVM071.lib"


def save_deck(name, **kw):
    with open(os.path.join(DECKS, name), "w", encoding="ascii") as fh:
        fh.write(build_deck(lib=LIB_REL, **kw))


def run_case(case, keep_wave=False, save_deck=None):
    deck = build_deck(**case["deck"])
    if save_deck:
        globals()["save_deck"](save_deck, **case["deck"])
    t_start = time.time()
    r = run_deck(deck, vectors=VECS, ngbehavior="psa", plots="last", timeout_s=900)
    out = dict(case["meta"])
    out["wall_s"] = round(time.time() - t_start, 2)
    if not r.ok or "vmot" not in r.vec:
        out["ok"] = False
        out["err"] = "; ".join(r.errors[:3])
        return out, None
    out["ok"] = True
    t = r["time"]
    vm = r["vmot"]
    vin = r["vin"]
    flag = r["flag"] > 0.5
    flg = r["flg"] > 0.5          # U101 actually off (equals flag unless the latching variant is selected)
    rsh = CHOPPERS[case["deck"]["chop"]]["rsh"]
    ish = r["drn"] / rsh
    icf = r["icf"]
    vbe = r["vbe"]
    rgn = r["rgn"]
    dt = np.diff(t, prepend=t[0])
    out["vmot_peak"] = float(vm.max())
    out["t_vmot_peak"] = float(t[vm.argmax()])
    out["vin_peak"] = float(vin.max())
    out["ish_peak"] = float(ish.max())
    out["e_chopper_J"] = float(np.sum(r["drn"] * ish * dt))
    out["e_charger_J"] = float(np.sum(vbe * icf * dt))
    out["ichg_peak"] = float(icf.max())
    edges = np.flatnonzero(np.diff(flag.astype(int)) == 1)
    out["ovp_trips"] = int(len(edges))
    out["ovp_off_s"] = float(np.sum(dt[flg]))
    # VESC over-voltage cuts and the regen energy the VESC delivered into V-MOT
    vfc = r["vf"] > 0.5
    out["vesc_cuts"] = int(np.sum(np.diff(vfc.astype(int)) == 1))
    d = case["deck"]
    if d.get("mode", "I") == "I":
        ireg = d.get("ipk", 1.0) * r["env"] * r["gt"]
    else:
        ireg = d.get("preg", 0.0) * r["env"] * r["gt"] / np.maximum(vm, 5.0)
    out["e_regen_J"] = float(np.sum(vm * ireg * dt))
    out["harvest_frac"] = out["e_charger_J"] / out["e_regen_J"] if out["e_regen_J"] > 0 else float("nan")
    out["t_first_trip"] = float(t[edges[0] + 1]) if len(edges) else float("nan")
    if len(edges):
        k = edges[0] + 1
        out["v_at_trip"] = float(vm[k])
        out["vmot_after_trip_peak"] = float(vm[k:].max())
        out["excursion_after_trip"] = out["vmot_after_trip_peak"] - out["v_at_trip"]
    else:
        out["v_at_trip"] = out["vmot_after_trip_peak"] = out["excursion_after_trip"] = float("nan")
    for lim in (35.0, 40.0):
        above = vm > lim
        out[f"t_above_{int(lim)}_s"] = float(np.sum(dt[above]))
        out[f"t_first_{int(lim)}"] = float(t[np.argmax(above)]) if above.any() else float("nan")
    out["rt1987_latched"] = bool(r["lat"].max() > 0.5)
    # Component stress in the chopper (ratings: TL431 IKA 150 mA abs max and VKA 37 V abs max, TL431_TI.pdf 6.1;
    # BZT52C12 PD 500 mW, BZT52C_Diodes.pdf; R-SHUNT 20 W, BOM line 33; BSP170P VDS -60 V).
    vg, kint = r["vg"], r["kint"]
    settled = t > 1e-3   # exclude the first 1 ms: the UIC start charges the junction and gate capacitances
    ika = (vg - kint) / 220.0 if CHOPPERS[case["deck"]["chop"]]["tl431"] else np.zeros_like(vg)
    out["ika_peak_mA"] = float(ika[settled].max() * 1e3)
    out["vka_peak"] = float((kint).max()) if CHOPPERS[case["deck"]["chop"]]["tl431"] else float("nan")
    # R-G 220 ohm 0402 1/16 W (MB BOM line 40); R-GS 3.3 kOhm 0603 1/10 W (MB BOM line 39)
    out["p_rg_peak_W"] = float(np.max(ika[settled] ** 2 * 220.0))
    out["p_rgs_peak_W"] = float(np.max(((vm - vg)[settled]) ** 2 / 3300.0))
    # VKA above the 37 V absolute maximum; above about 100 V the TI macro-model's internal clamp diodes (BV 100 V)
    # conduct, so results with vka_peak near 100 V are model artefacts beyond device destruction.
    out["vka_over_37V"] = bool(out["vka_peak"] > 37.0) if CHOPPERS[case["deck"]["chop"]]["tl431"] else False
    iz = np.clip(ika - (vm - vg) / 3300.0, 0, None)
    out["p_zener_peak_W"] = float(np.max((iz * (vm - vg))[settled]))
    out["p_rshunt_peak_W"] = float(np.max((r["drn"] ** 2 / rsh)[settled]))
    out["p_fet_peak_W"] = float(np.max(((vm - r["drn"]) * ish)[settled]))
    id107 = r["vd107#branch"]
    out["d107_peak_A"] = float(max(0.0, id107[settled].max()))
    out["e_d107_J"] = float(np.sum(np.clip(id107, 0, None) * vin * dt))
    counts = np.clip(np.round(rgn * 4095 / 3.3), 0, 4095)
    vread = counts * ADC_LSB
    out["vrgn_read_peak"] = float(vread.max())
    out["rgn_node_peak"] = float(rgn.max())
    # reading at 15.9 V steady (t < T0)
    k0 = np.searchsorted(t, T0 * 0.9)
    out["vrgn_read_idle"] = float(vread[k0])
    out["vbe_min_after_trip"] = float(vbe[edges[0] + 1:].min()) if len(edges) else float("nan")
    if "vdbody#branch" in r.vec:
        # U101 body-diode (reverse) current, VOUT to VIN, only in decks built with u101_body (2026-11-15)
        idb = r["vdbody#branch"]
        out["body_peak_A"] = float(max(0.0, idb[settled].max()))
        out["body_charge_C"] = float(np.sum(np.clip(idb, 0, None) * dt))
        out["vout_minus_vin_max"] = float(np.max((r["vout"] - vin)[settled]))
    wave = None
    if keep_wave:
        # decimate to <= 6000 points on a uniform grid
        tg = np.linspace(t[0], t[-1], 6000)
        wave = {k: np.interp(tg, t, v) for k, v in
                dict(vmot=vm, vin=vin, vbe=vbe, flag=flg.astype(float), ish=ish, icf=icf, vread=vread,
                     rgn=rgn, ireg=ireg, vf=r["vf"]).items()}
        wave["t"] = tg
    return out, wave


def run_many(cases, keep=lambda c: False, tag=""):
    res, waves = [], {}
    t0 = time.time()

    def work(c):
        return c, run_case(c, keep_wave=keep(c))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (c, (o, w)) in enumerate(ex.map(work, cases)):
            res.append(o)
            if w is not None:
                waves[c["meta"]["id"]] = w
            if (i + 1) % 25 == 0 or i + 1 == len(cases):
                print(f"  [{tag}] {i + 1}/{len(cases)} done, {time.time() - t0:.0f} s")
    bad = [o for o in res if not o["ok"]]
    if bad:
        print(f"  [{tag}] WARNING {len(bad)} failed runs, first: {bad[0]}")
    return res, waves


def write_csv(path, rows):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="ascii") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})


# ---------------------------------------------------------------------------------------------------------------
# Part A: static chopper I-V (V-MOT forced, current into the chopper and the RGN-V reading)
# ---------------------------------------------------------------------------------------------------------------
def dc_iv(chop):
    c = CHOPPERS[chop]
    L = [f"* chopper static I-V {chop}", f".include \"{TL431_LIB}\""]
    # (the saved copy below uses LIB_REL, relative to the decks/ folder)
    for m in MODEL_LINES:
        L.append(m.format(vto=c["vto"], vbr=36.7))
    L.append("VM vmot 0 DC 15")
    L += chopper_block(c)
    L.append(".dc VM 10 45 0.005")
    L.append(".end")
    deck = "\n".join(L) + "\n"
    with open(os.path.join(DECKS, f"dc_iv_{chop}.cir"), "w", encoding="ascii") as fh:
        fh.write(deck.replace(TL431_LIB, LIB_REL))
    r = run_deck(deck, ngbehavior="psa", plots="last")
    assert r.ok, (chop, r.errors[:5])
    v = r.vec[[k for k in r.vec if "sweep" in k][0]]
    i_tot = -r["vm#branch"]
    ish = r["drn"] / c["rsh"]
    rgn = r["rgn"]
    return v, i_tot, ish, rgn


def main():
    t_all = time.time()
    print("Sim 2 chopper: " + ngspice_version())
    print(f"U101 OVP: gain {GAIN_OVP:.4f}, leakage shift {LEAK_SHIFT:.3f} V, t_on {T_OVP_ON * 1e6:.0f} us, "
          f"SR {SR_DVDT:.0f} V/s")
    for k, (a, b) in OVPS.items():
        print(f"  OVP {k}: rise {a:.2f} V, fall {b:.2f} V")

    # ---------------- Part A
    print("Part A: static I-V")
    iv_rows, iv_curves = [], {}
    for chop in CHOPPERS:
        v, itot, ish, rgn = dc_iv(chop)
        iv_curves[chop] = (v, itot, ish, rgn)

        def at(arr, thr):
            idx = np.flatnonzero(arr >= thr)
            return float(v[idx[0]]) if len(idx) else float("nan")
        read = np.clip(np.round(rgn * 4095 / 3.3), 0, 4095) * ADC_LSB
        row = dict(chopper=chop, desc=CHOPPERS[chop]["desc"],
                   v_onset_1mA=at(ish, 1e-3), v_clamp_10mA=at(ish, 10e-3), v_at_100mA=at(ish, 0.1),
                   v_at_300mA=at(ish, 0.3), v_at_470mA=at(ish, 0.47),
                   v_at_740mA=at(ish, 0.74), v_at_850mA=at(ish, 0.85),
                   # total chopper-node current (R-SHUNT + divider + R-GS/Z-SNT/R-G/TL431), without VESC housekeeping
                   itot_at_35V=float(np.interp(35.0, v, itot)), itot_at_40V=float(np.interp(40.0, v, itot)),
                   ish_at_35V=float(np.interp(35.0, v, ish)), ish_at_40V=float(np.interp(40.0, v, ish)),
                   rgn_node_15p93=float(np.interp(15.93, v, rgn)),
                   read_15p93=float(np.interp(15.93, v, read)),
                   read_22=float(np.interp(22.0, v, read)), read_25=float(np.interp(25.0, v, read)),
                   read_30=float(np.interp(30.0, v, read)), read_35=float(np.interp(35.0, v, read)),
                   gain_14_17=float((np.interp(17.0, v, read) - np.interp(14.0, v, read)) / 3.0),
                   i_rgn_sink_15p93=float(np.interp(15.93, v, (v - rgn) / CHOPPERS[chop]["r1"]
                                                    - rgn / CHOPPERS[chop]["r2"])))
        # true V-MOT that gives an 18.2 V reading
        k = np.flatnonzero(read >= 18.2)
        row["vmot_for_read_18p2"] = float(v[k[0]]) if len(k) else float("nan")
        iv_rows.append(row)
        print(f"  {chop:7s} onset {row['v_onset_1mA']:.3f} V, clamp(10 mA) {row['v_clamp_10mA']:.3f} V, "
              f"0.47 A at {row['v_at_470mA']:.2f} V, read@15.93 {row['read_15p93']:.3f}, "
              f"V-MOT for 18.2 V reading {row['vmot_for_read_18p2']:.2f}")
    write_csv(os.path.join(HERE, "results_static_iv.csv"), iv_rows)

    # ---------------- Part B: main transient grid (current-source bursts)
    I_GRID = [0.25, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0]
    chops = list(CHOPPERS)
    ovps = ["lo", "typ", "hi"]
    chgs = ["nom", "none"]
    if QUICK:
        I_GRID = [0.5, 1.5]
        chops = ["H-typ", "F-open"]
        ovps = ["typ"]
    cases = []
    for chop, ovp, chg, ipk in itertools.product(chops, ovps, chgs, I_GRID):
        cid = f"B|{chop}|{ovp}|{chg}|{ipk}"
        cases.append(dict(deck=dict(chop=chop, ovp=ovp, chg=chg, cvmot=0.97e-3, ipk=ipk, tp=0.6),
                          meta=dict(id=cid, part="B", chopper=chop, ovp=ovp, charger=chg, cvmot_mF=0.97,
                                    ipk_A=ipk, tp_s=0.6)))
    # charger corners at OVP typ, healthy typ and F-open
    if not QUICK:
        for chop, chg, ipk in itertools.product(["H-lo", "H-typ", "H-hi", "F-open"], ["lo", "d310", "hi"], I_GRID):
            cid = f"B|{chop}|typ|{chg}|{ipk}"
            cases.append(dict(deck=dict(chop=chop, ovp="typ", chg=chg, cvmot=0.97e-3, ipk=ipk, tp=0.6),
                              meta=dict(id=cid, part="B", chopper=chop, ovp="typ", charger=chg, cvmot_mF=0.97,
                                        ipk_A=ipk, tp_s=0.6)))
        # OVP lo-leak corner, healthy chopper corners
        for chop, ipk in itertools.product(["H-lo", "H-typ", "H-hi"], I_GRID):
            cid = f"B|{chop}|lo-leak|nom|{ipk}"
            cases.append(dict(deck=dict(chop=chop, ovp="lo-leak", chg="nom", cvmot=0.97e-3, ipk=ipk, tp=0.6),
                              meta=dict(id=cid, part="B", chopper=chop, ovp="lo-leak", charger="nom",
                                        cvmot_mF=0.97, ipk_A=ipk, tp_s=0.6)))
    keep_ids = {f"B|{c}|typ|nom|{i}" for c in ("H-typ", "F-k9", "F-open", "F-soft", "H-lo", "H-hi")
                for i in (0.6, 1.1, 1.3, 1.5, 2.0)}
    keep_ids |= {f"B|H-typ|typ|none|{i}" for i in (0.4, 0.6, 1.0)}
    keep_ids |= {f"B|H-hi|lo|nom|{i}" for i in (1.2, 1.3, 1.4)}
    # save representative decks
    for c in ("H-typ", "F-k9", "F-open", "F-soft"):
        save_deck(f"tran_{c}_typ_nom_1.3A.cir", chop=c, ovp="typ", chg="nom", cvmot=0.97e-3, ipk=1.3, tp=0.6)
    save_deck("tran_H-typ_typ_nom_2.0A_vcut25.2.cir", chop="H-typ", ovp="typ", chg="nom", cvmot=0.97e-3, ipk=2.0,
              tp=TP_CUT, vcut=25.2)
    save_deck("tran_F-k9_typ_nom_1.6A_vcut24.cir", chop="F-k9", ovp="typ", chg="nom", cvmot=0.97e-3, ipk=1.6,
              tp=TP_CUT, vcut=24.0)
    print(f"Part B: {len(cases)} transient runs")
    resB, wavesB = run_many(cases, keep=lambda c: c["meta"]["id"] in keep_ids, tag="B")
    write_csv(os.path.join(HERE, "results_burst_grid.csv"), resB)

    # ---------------- Part C: capacitance and pulse-width sweep, re-qualification variant
    casesC = []
    if not QUICK:
        for chop, cv, tp, ipk in itertools.product(["H-typ", "F-k9", "F-open"], CVMOTS, [0.3, 0.6],
                                                   [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]):
            cid = f"C|{chop}|{cv}|{tp}|{ipk}"
            casesC.append(dict(deck=dict(chop=chop, ovp="typ", chg="nom", cvmot=CVMOTS[cv], ipk=ipk, tp=tp,
                                         tstop=T0 + TRISE + tp + TFALL + 0.45),
                               meta=dict(id=cid, part="C", chopper=chop, ovp="typ", charger="nom",
                                         cvmot_mF=CVMOTS[cv] * 1e3, ipk_A=ipk, tp_s=tp)))
        for chop, ipk in itertools.product(["H-typ", "H-hi"], [1.1, 1.2, 1.3, 1.4, 1.5, 2.0]):
            for ovp in ("lo", "typ"):
                cid = f"C|{chop}|noreq|{ovp}|{ipk}"
                casesC.append(dict(deck=dict(chop=chop, ovp=ovp, chg="nom", cvmot=0.97e-3, ipk=ipk, tp=0.6,
                                             requal=0.0),
                                   meta=dict(id=cid, part="C-noreq", chopper=chop, ovp=ovp, charger="nom",
                                             cvmot_mF=0.97, ipk_A=ipk, tp_s=0.6, requal="none")))
        print(f"Part C: {len(casesC)} transient runs")
    resC, wavesC = run_many(casesC, keep=lambda c: c["meta"]["id"] in {"C|H-typ|noreq|typ|1.3", "C|H-hi|noreq|lo|1.3"},
                            tag="C") if casesC else ([], {})
    write_csv(os.path.join(HERE, "results_cap_pulse.csv"), resC)

    # ---------------- Part D: constant-power brakes (11.1 / 18.9 / 23 W) and the no-RT1987-OVP variant
    casesD = []
    POWERS = [(11.1, 0.30), (18.9, 0.58), (23.0, 0.58), (30.0, 0.58)]
    if not QUICK:
        for chop, chg, (p, tp), cv in itertools.product(list(CHOPPERS), ["nom", "none", "lo"], POWERS,
                                                         ["0.4mF", "0.97mF", "4mF"]):
            cid = f"D|{chop}|{chg}|{p}|{cv}"
            casesD.append(dict(deck=dict(chop=chop, ovp="typ", chg=chg, cvmot=CVMOTS[cv], mode="P", preg=p, tp=tp),
                               meta=dict(id=cid, part="D", chopper=chop, ovp="typ", charger=chg,
                                         cvmot_mF=CVMOTS[cv] * 1e3, p_W=p, tp_s=tp)))
        for chop, ipk in itertools.product(["H-typ", "F-open"], [1.0, 1.5, 2.0, 3.0, 4.0]):
            cid = f"D|{chop}|nortovp|{ipk}"
            casesD.append(dict(deck=dict(chop=chop, ovp="typ", chg="nom", cvmot=0.97e-3, ipk=ipk, tp=0.6,
                                         rt_ovp=1e3),
                               meta=dict(id=cid, part="D-noRTovp", chopper=chop, ovp="typ", charger="nom",
                                         cvmot_mF=0.97, ipk_A=ipk, tp_s=0.6, rt1987_ovp="none")))
        print(f"Part D: {len(casesD)} transient runs")
    keepD = {f"D|{c}|nom|{p}|0.97mF" for c in ("H-typ", "F-open", "F-k9") for p in (18.9, 23.0)}
    keepD |= {"D|F-open|nortovp|2.0", "D|H-typ|nortovp|2.0"}
    resD, wavesD = run_many(casesD, keep=lambda c: c["meta"]["id"] in keepD, tag="D") if casesD else ([], {})
    write_csv(os.path.join(HERE, "results_power_brakes.csv"), resD)

    # ---------------- Part E: VESC over-voltage cut (regen_dynamics.md section 0 item 1), pulsed regen
    casesE = []
    I_E = [0.25, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0, 3.0]
    if QUICK:
        I_E = [0.6, 1.6]
    for chop, ovp, chg, ipk, vc in itertools.product(chops if QUICK else list(CHOPPERS),
                                                     ["typ"] if QUICK else ["lo", "typ"], ["nom", "none"], I_E,
                                                     [25.2] if QUICK else VCUTS):
        cid = f"E|{chop}|{ovp}|{chg}|{ipk}|{vc}"
        casesE.append(dict(deck=dict(chop=chop, ovp=ovp, chg=chg, cvmot=0.97e-3, ipk=ipk, tp=TP_CUT, vcut=vc),
                           meta=dict(id=cid, part="E", chopper=chop, ovp=ovp, charger=chg, cvmot_mF=0.97, ipk_A=ipk,
                                     tp_s=TP_CUT, vcut=vc)))
    if not QUICK:
        for chop, ovp, ipk, vc, var in itertools.product(["H-typ", "H-hi", "F-k9", "F-open"], ["lo", "typ"],
                                                         [1.2, 1.4, 1.6, 2.0], [23.0, 24.0, 25.2, 27.0],
                                                         ["latch", "noreq"]):
            cid = f"E-{var}|{chop}|{ovp}|nom|{ipk}|{vc}"
            dk = dict(chop=chop, ovp=ovp, chg="nom", cvmot=0.97e-3, ipk=ipk, tp=TP_CUT, vcut=vc)
            mt = dict(id=cid, part=f"E-{var}", chopper=chop, ovp=ovp, charger="nom", cvmot_mF=0.97, ipk_A=ipk,
                      tp_s=TP_CUT, vcut=vc)
            if var == "latch":
                dk["u101_latch"] = True
                mt["u101"] = "latch"
            else:
                dk["requal"] = 0.0
                mt["requal"] = "none"
            casesE.append(dict(deck=dk, meta=mt))
        for chop, chg, p, vc in itertools.product(list(CHOPPERS), ["nom", "none", "d310"], [11.1, 18.9, 23.0, 30.0],
                                                  [21.0, 23.0, 25.2, 27.0, 30.0]):
            cid = f"EP|{chop}|{chg}|{p}|{vc}"
            casesE.append(dict(deck=dict(chop=chop, ovp="typ", chg=chg, cvmot=0.97e-3, mode="P", preg=p, tp=TP_CUT,
                                         vcut=vc),
                               meta=dict(id=cid, part="EP", chopper=chop, ovp="typ", charger=chg, cvmot_mF=0.97,
                                         p_W=p, tp_s=TP_CUT, vcut=vc)))
    print(f"Part E: {len(casesE)} transient runs (VESC cut)")
    keepE = {"E|H-typ|typ|nom|2.0|25.2", "E|F-k9|typ|nom|1.6|24.0", "E|H-typ|typ|none|0.6|25.2",
             "E|F-open|typ|none|0.25|21.0", "E-latch|H-typ|typ|nom|2.0|25.2", "E|H-typ|typ|nom|1.6|25.2",
             "E-latch|F-k9|typ|nom|1.6|24.0"}
    resE, wavesE = run_many(casesE, keep=lambda c: c["meta"]["id"] in keepE, tag="E")
    write_csv(os.path.join(HERE, "results_vesc_cut.csv"), resE)

    # ---------------- Part F: retuned U101 OVP band (design option), healthy chopper, no VESC cut
    casesF = []
    if not QUICK:
        ovpF = [k for k in OVPS if k.startswith("r24")]
        for chop, ovp, ipk in itertools.product(["H-lo", "H-typ", "H-hi"], ovpF,
                                                [1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.75, 2.0]):
            cid = f"F|{chop}|{ovp}|nom|{ipk}"
            casesF.append(dict(deck=dict(chop=chop, ovp=ovp, chg="nom", cvmot=0.97e-3, ipk=ipk, tp=0.6),
                               meta=dict(id=cid, part="F", chopper=chop, ovp=ovp, charger="nom", cvmot_mF=0.97,
                                         ipk_A=ipk, tp_s=0.6)))
        print(f"Part F: {len(casesF)} transient runs (retuned OVP)")
    resF, _ = run_many(casesF, tag="F") if casesF else ([], {})
    write_csv(os.path.join(HERE, "results_ovp_retune.csv"), resF)

    waves = {**wavesB, **wavesC, **wavesD, **wavesE}
    np.savez_compressed(os.path.join(HERE, "waveforms.npz"),
                        **{f"{cid}::{k}": v for cid, w in waves.items() for k, v in w.items()})

    # ---------------- thresholds: lowest regen current at which V-MOT reaches 35 V / 40 V, and OVP trips
    thr_rows = []
    allB = [r for r in resB + resC + resE + resF if r.get("ok") and "ipk_A" in r]
    groups = {}
    for r in allB:
        key = (r["part"], r["chopper"], r["ovp"], r["charger"], r["cvmot_mF"], r["tp_s"], r.get("requal", "300ms"),
               r.get("vcut", "none"), r.get("u101", "release"))
        groups.setdefault(key, []).append(r)
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda x: x["ipk_A"])
        row = dict(part=key[0], chopper=key[1], ovp=key[2], charger=key[3], cvmot_mF=key[4], tp_s=key[5],
                   requal=key[6], vcut=key[7], u101=key[8])
        for name, test in (("I_first_ovp_trip", lambda x: x["ovp_trips"] > 0),
                           ("I_vmot_35V", lambda x: x["vmot_peak"] >= 35.0),
                           ("I_vmot_40V", lambda x: x["vmot_peak"] >= 40.0),
                           ("I_rt1987_latch", lambda x: x["rt1987_latched"])):
            hit = [x["ipk_A"] for x in rows if test(x)]
            miss = [x["ipk_A"] for x in rows if not test(x) and (not hit or x["ipk_A"] < min(hit))]
            row[name + "_le"] = min(hit) if hit else float("nan")
            row[name + "_gt"] = max(miss) if miss else float("nan")
        row["max_ovp_trips"] = max(x["ovp_trips"] for x in rows)
        row["max_vesc_cuts"] = max(x.get("vesc_cuts", 0) for x in rows)
        thr_rows.append(row)
    write_csv(os.path.join(HERE, "results_thresholds.csv"), thr_rows)

    make_plots(iv_curves, iv_rows, resB, resC, resD, waves, resE, thr_rows)
    allres = resB + resC + resD + resE + resF
    summary = dict(ngspice=ngspice_version(), runs=len(allres), failed=sum(1 for r in allres if not r.get("ok")),
                   runs_by_part={k: sum(1 for r in allres if r["part"] == k) for k in sorted({r["part"] for r in allres})},
                   wall_s=round(time.time() - t_all))
    with open(os.path.join(HERE, "run_summary.json"), "w", encoding="ascii") as fh:
        json.dump(summary, fh, indent=1)
    print(f"Done: {summary}")


# ---------------------------------------------------------------------------------------------------------------
def make_plots(iv_curves, iv_rows, resB, resC, resD, waves, resE=(), thr_rows=()):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"H-lo": "#1f77b4", "H-typ": "#2ca02c", "H-hi": "#17becf", "F-k9": "#d62728", "F-k15": "#ff7f0e",
              "F-soft": "#9467bd", "F-open": "#7f7f7f"}

    # Fig 1: static I-V and V_rgn reading
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    for chop, (v, itot, ish, rgn) in iv_curves.items():
        ax[0].plot(v, ish, color=colors[chop], label=chop)
        read = np.clip(np.round(rgn * 4095 / 3.3), 0, 4095) * ADC_LSB
        ax[1].plot(v, read, color=colors[chop], label=chop)
    for x, lab in ((22.19, "OVP rise min"), (24.41, "OVP rise max"), (35, "35 V caps"), (40, "RT1987 abs max")):
        ax[0].axvline(x, color="k", lw=0.7, ls=":")
        ax[0].text(x, 0.92, lab, rotation=90, fontsize=7, va="top", ha="right")
    ax[0].set_xlabel("V-MOT (V)")
    ax[0].set_ylabel("Chopper current through R-SHUNT (A)")
    ax[0].set_xlim(15, 45)
    ax[0].set_ylim(0, 1.0)
    ax[0].grid(alpha=0.3)
    ax[0].legend(fontsize=8)
    ax[0].set_title("(a) Static chopper I-V, V-MOT forced")
    ax[1].plot([10, 45], [10, 45], "k:", lw=0.7, label="ideal reading")
    ax[1].axhspan(18.1, 18.3, color="orange", alpha=0.3, label="logged ceiling 18.1-18.3 V")
    ax[1].set_xlabel("V-MOT (V)")
    ax[1].set_ylabel("V_rgn reading, pin 39 (V)")
    ax[1].set_xlim(10, 45)
    ax[1].set_ylim(8, 30)
    ax[1].grid(alpha=0.3)
    ax[1].legend(fontsize=7)
    ax[1].set_title("(b) Pin-39 reading (12-bit, SCALE_V_RGN)")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_static_iv.png"), dpi=130)
    plt.close(fig)

    # Fig 2: V-MOT peak vs regen current, OVP typ, charger nom and none
    if resB:
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
        for j, chg in enumerate(("nom", "none")):
            for chop in CHOPPERS:
                rows = sorted([r for r in resB if r.get("ok") and r["chopper"] == chop and r["ovp"] == "typ"
                               and r["charger"] == chg], key=lambda r: r["ipk_A"])
                if not rows:
                    continue
                ax[j].plot([r["ipk_A"] for r in rows], [r["vmot_peak"] for r in rows], "o-", ms=3,
                           color=colors[chop], label=chop)
            for y, lab in ((23.19, "U101 OVP typ"), (33, "RT1987 OVP min"), (35, "35 V caps"), (40, "40 V abs max")):
                ax[j].axhline(y, color="k", lw=0.7, ls=":")
                ax[j].text(4.0, y, lab, fontsize=7, ha="right", va="bottom")
            ax[j].set_xlabel("Regen current peak into V-MOT (A), 0.6 s burst")
            ax[j].set_title(f"Charger {'regen image (nominal)' if chg == 'nom' else 'not converting'}, OVP typ, 0.97 mF")
            ax[j].grid(alpha=0.3)
        ax[0].set_ylabel("V-MOT peak (V)")
        ax[0].set_ylim(15, 120)
        ax[0].legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, "fig_vmot_peak_vs_current.png"), dpi=130)
        plt.close(fig)

    # Fig 3: waveforms
    def wplot(fname, ids, title, ylim=None):
        ids = [i for i in ids if i in waves]
        if not ids:
            return
        fig, ax = plt.subplots(3, 1, figsize=(11, 8.5), sharex=True)
        for i in ids:
            w = waves[i]
            lab = i.replace("|", " ")
            ax[0].plot(w["t"] * 1e3, w["vmot"], label=lab)
            ax[1].plot(w["t"] * 1e3, w["icf"], label=lab)
            ax[1].plot(w["t"] * 1e3, w["ish"], ls="--", color=ax[1].lines[-1].get_color())
            ax[2].plot(w["t"] * 1e3, w["vread"], label=lab)
        for y in (23.19, 35, 40):
            ax[0].axhline(y, color="k", lw=0.6, ls=":")
        if ylim:
            ax[0].set_ylim(*ylim)
            ax[0].text(0.99, 0.97, f"V-MOT axis clipped at {ylim[1]:.0f} V", transform=ax[0].transAxes,
                       ha="right", va="top", fontsize=8)
        ax[0].set_ylabel("V-MOT (V)")
        ax[1].set_ylabel("Charger draw (solid), chopper (dashed) (A)")
        ax[2].set_ylabel("V_rgn reading (V)")
        ax[2].axhspan(18.1, 18.3, color="orange", alpha=0.3)
        ax[2].set_xlabel("Time (ms)")
        ax[0].set_title(title)
        ax[0].legend(fontsize=7)
        for a in ax:
            a.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, fname), dpi=130)
        plt.close(fig)

    wplot("fig_wave_healthy.png", ["B|H-typ|typ|nom|1.1", "B|H-typ|typ|nom|1.3", "B|H-typ|typ|nom|1.5",
                                   "B|H-typ|typ|none|0.4", "B|H-typ|typ|none|0.6"],
          "Healthy chopper (H-typ), OVP typ, 0.97 mF, 0.6 s current bursts")
    wplot("fig_wave_faulty.png", ["B|F-k9|typ|nom|1.1", "B|F-k9|typ|nom|1.3", "B|F-open|typ|nom|1.3",
                                  "B|F-soft|typ|nom|1.3", "B|F-k9|typ|nom|2.0"],
          "Faulty RGN-V node, OVP typ, 0.97 mF, 0.6 s current bursts", ylim=(10, 90))
    wplot("fig_wave_power.png", ["D|H-typ|nom|18.9|0.97mF", "D|H-typ|nom|23.0|0.97mF", "D|F-k9|nom|23.0|0.97mF",
                                 "D|F-open|nom|23.0|0.97mF"],
          "Constant-power brakes (18.9 W / 23 W), OVP typ, charger nominal, 0.97 mF", ylim=(10, 90))
    # Fig 7: VESC-cut waveforms
    wplot("fig_wave_vesc_cut.png", ["E|H-typ|typ|nom|2.0|25.2", "E-latch|H-typ|typ|nom|2.0|25.2",
                                    "E|F-k9|typ|nom|1.6|24.0", "E|H-typ|typ|none|0.6|25.2"],
          "VESC over-voltage cut (fault stop 0.5 s), OVP typ, 0.97 mF, 1.2 s brake command")

    # Fig 8: VESC-cut map: U101 trips per burst and charger harvest fraction against regen current
    if resE:
        fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
        cmap = plt.get_cmap("viridis")
        for k, vc in enumerate(VCUTS):
            col = cmap(k / (len(VCUTS) - 1))
            for j, (chop, ls) in enumerate((("H-typ", "-"), ("F-k9", "--"))):
                rows = sorted([r for r in resE if r.get("ok") and r["part"] == "E" and r["chopper"] == chop
                               and r["ovp"] == "typ" and r["charger"] == "nom" and r["vcut"] == vc],
                              key=lambda r: r["ipk_A"])
                if not rows:
                    continue
                x = [r["ipk_A"] for r in rows]
                ax[0].plot(x, [r["vmot_peak"] for r in rows], ls, marker="o", ms=3, color=col,
                           label=f"{chop}, cut {vc} V" if j == 0 or k == 0 else None)
                ax[1].plot(x, [r["ovp_trips"] for r in rows], ls, marker="o", ms=3, color=col)
                ax[2].plot(x, [r["e_charger_J"] for r in rows], ls, marker="o", ms=3, color=col)
        for vc, ls in ((25.2, ":"),):
            rows = sorted([r for r in resE if r.get("ok") and r["part"] == "E-latch" and r["chopper"] == "H-typ"
                           and r["ovp"] == "typ" and r["vcut"] == vc], key=lambda r: r["ipk_A"])
            if rows:
                ax[2].plot([r["ipk_A"] for r in rows], [r["e_charger_J"] for r in rows], "k:", marker="x",
                           label=f"H-typ, cut {vc} V, U101 latching")
        ax[0].axhline(23.19, color="k", lw=0.6, ls=":")
        ax[0].set_ylabel("V-MOT peak (V)")
        ax[1].set_ylabel("U101 OVP trips per 1.2 s brake")
        ax[2].set_ylabel("Charger input energy per 1.2 s brake (J)")
        for a in ax:
            a.set_xlabel("Regen current peak (A)")
            a.grid(alpha=0.3)
        ax[0].legend(fontsize=6, ncol=2)
        ax[2].legend(fontsize=7)
        ax[0].set_title("(a) V-MOT peak (solid H-typ, dashed F-k9)")
        ax[1].set_title("(b) U101 OVP trips")
        ax[2].set_title("(c) Energy into the charger")
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, "fig_vesc_cut_map.png"), dpi=130)
        plt.close(fig)

    # Fig 9: first U101 trip current against the OVP band, healthy chopper, nominal charger, no VESC cut
    rowsT = [r for r in thr_rows if r["part"] in ("B", "F") and r["charger"] == "nom" and r["vcut"] == "none"
             and r["chopper"] in ("H-lo", "H-typ", "H-hi")]
    if rowsT:
        order = ["lo-leak", "lo", "typ", "hi", "r24-lo-leak", "r24-lo", "r24-typ", "r24-hi",
                 "r244-lo-leak", "r244-lo", "r244-typ", "r244-hi"]
        fig, ax = plt.subplots(figsize=(12, 4.6))
        for j, chop in enumerate(("H-lo", "H-typ", "H-hi")):
            ys, yl, xs = [], [], []
            for i, o in enumerate(order):
                m = [r for r in rowsT if r["chopper"] == chop and r["ovp"] == o]
                if not m:
                    continue
                hi = m[0]["I_first_ovp_trip_le"]
                lo = m[0]["I_first_ovp_trip_gt"]
                xs.append(i + (j - 1) * 0.25)
                ys.append(hi if hi == hi else 2.1)
                yl.append(lo if lo == lo else 0)
            ax.bar(xs, [a - b for a, b in zip(ys, yl)], bottom=yl, width=0.22, color=colors[chop], label=chop)
        ax.set_xticks(range(len(order)))
        ax.set_xticklabels(order, rotation=30, fontsize=8)
        ax.set_ylabel("First U101 trip: current bracket (A)")
        ax.set_ylim(0.9, 2.15)
        ax.axhline(2.0, color="k", lw=0.6, ls=":")
        ax.text(0, 2.02, "bar ending at 2.1 A: no trip up to 2.0 A", fontsize=7)
        ax.grid(alpha=0.3, axis="y")
        ax.legend(fontsize=8)
        ax.set_title("First U101 OVP trip against the OVP band (fitted 18.81 gain; r24, r244 retuned), charger nominal")
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, "fig_ovp_retune.png"), dpi=130)
        plt.close(fig)

    wplot("fig_wave_noreq.png", ["C|H-typ|noreq|typ|1.3", "B|H-typ|typ|nom|1.3", "B|H-hi|lo|nom|1.3",
                                 "C|H-hi|noreq|lo|1.3"],
          "U101 OVP recovery: with and without a 300 ms charger re-qualification", ylim=(10, 90))


if __name__ == "__main__":
    main()
