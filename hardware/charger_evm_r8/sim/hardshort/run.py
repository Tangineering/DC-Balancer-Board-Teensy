"""Sim 1 (hardshort): T-C-04 hard short, soft short and OVP trip at the EVM J1 end of W1/W2.

Regenerates every deck, CSV and PNG of this simulation:
    C:\\Users\\ricky\\miniforge3\\python.exe run.py            (all case sets)
    C:\\Users\\ricky\\miniforge3\\python.exe run.py --quick    (validation + one case per set)
    C:\\Users\\ricky\\miniforge3\\python.exe run.py --tft-check
        (2026-11-15, review-2 finding R2-SIM-9: re-runs the rsh set and the headline grid cases at the TCKE1401NM
         Table 10.3 tFASTTRIP typical 4 us and maximum 8 us for R101 8.45 kOhm, the DS sec. 7.9 3 us
         typical and the 6 us base; writes only results/tft_check.csv, results/tft_check.md and decks/tft*.cir)

Circuit sources (see RESULTS.md section 2 for the full table with file:line citations):
  CR   : hardware/charger_evm_r8/gen/netlist.py lines 95-124 (C102a/b/c, D107, U101, C103, D103), 228-229 (W1/W2);
         line numbers at git tag charger-r8-pre-review-2026-11-14 (they moved with D-82)
  MB   : references/Scale_Car_Board_20260624.sch (VCHG-IN net: D-BC-RG/D-BC-FC VOUT, C-D8, C-D10, R1-CHG 78.7k;
         CHG-V net: R1-CHG/R2-CHG 10k -> pin 38; V-MOT net: D-BC-RG VIN)
  U101 : references/Datasheets/tcke1401nm.pdf Rev. 3.0, Table 10.1 (RON), Table 10.3 (tFASTTRIP, tSCP), sec. 7.9
  Prior model: docs/reviews/charger_eval_2026-11-05/round4/calc/r7_calc.py lines 4328-4351 (in_spike)
Console output is ASCII only.
"""
import csv
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SIM, "common"))
from ngspice_run import run_deck, ngspice_version  # noqa: E402

DECKS = os.path.join(HERE, "decks")
RES = os.path.join(HERE, "results")
PLOTS = os.path.join(HERE, "plots")
MODELS = os.path.join(SIM, "models")
for d in (DECKS, RES, PLOTS):
    os.makedirs(d, exist_ok=True)

VT25 = 0.025693  # thermal voltage at 25 C

# ----------------------------------------------------------------------------------------------------------------
# D103 candidate models
# ----------------------------------------------------------------------------------------------------------------


def fit_diode(points, n_fixed=None):
    """Fit VF = a ln(I) + b + RS I (a = N Vt, b = -a ln IS) by least squares. Returns (IS, N, RS)."""
    I = np.array([p[0] for p in points], float)
    V = np.array([p[1] for p in points], float)
    if n_fixed is not None:
        a = n_fixed * VT25
        A = np.column_stack([np.ones_like(I), I])
        b, rs = np.linalg.lstsq(A, V - a * np.log(I), rcond=None)[0]
    else:
        A = np.column_stack([np.log(I), np.ones_like(I), I])
        a, b, rs = np.linalg.lstsq(A, V, rcond=None)[0]
    n = a / VT25
    IS = math.exp(-b / a)
    return IS, n, rs


# Behavioural fits (datasheet tables / curves read 2026-11-14), all at Tj = 25 C.
BEHAV = {
    # ST DocID6115 Rev 8 Table 4 (max, 25 C) as quoted in bom_2026-11-13/cr_bom.csv D103 row: 0.79 V at 2 A,
    # 0.88 V at 4 A. st.com did not answer on 2026-11-14, so the Fig. 14 high-current curve was not read. N = 1
    # fixed; RS is the 2-4 A incremental slope less the ideal-diode term: a linear extension (pessimistic bound).
    "STPS2H100A_fit": dict(points=[(2.0, 0.79), (4.0, 0.88)], n_fixed=1.0, cjo=150e-12,
                           src="ST DocID6115 Rev 8 Table 4 (max, 25 C), via cr_bom.csv D103 row; CJO ASSUMPTION"),
    # onsemi MBRS2H100/D Rev. 16 Fig. 2 'Maximum Forward Voltage', 25 C curve, read from the figure: 2 A 0.79 V
    # (also the EC table max), 10 A 0.98 V, 60 A 1.55 V.
    "MBRA2H100_maxfit": dict(points=[(2.0, 0.79), (10.0, 0.98), (60.0, 1.55)], n_fixed=None, cjo=583e-12,
                             src="onsemi MBRS2H100/D Rev.16 Fig. 2 (max, 25 C), read from the figure"),
    # Vishay doc 89405 (27-Feb-2020) Fig. 3 typical 25 C curve read from the figure (1 A 0.56 V, 3 A 0.71 V, 10 A
    # 1.03 V), shifted up by 0.09 V so that 3 A matches the EC table maximum 0.80 V (ASSUMPTION: uniform shift).
    "VSSA310S_fit": dict(points=[(1.0, 0.65), (3.0, 0.80), (10.0, 1.12)], n_fixed=None, cjo=300e-12,
                         src="Vishay doc 89405 Fig. 3 typ + 0.09 V to the Table max at 3 A"),
}

MFR = {
    "MBRA2H100_mfr": ("onsemi_MBRA2H100T3G.lib", "Dmbrs2h100t3g"),
    "SS3H10_mfr": ("vishay_SS3H10.lib", "ss3h10"),
}

# IFSM (10 ms or 8.3 ms half sine) of each candidate, and its datasheet; package
D103_INFO = {
    "STPS2H100A_fit": dict(ifsm=75.0, pkg="SMA", note="ordered candidate (BOM); IFSM 75 A tp 10 ms sine"),
    "MBRA2H100_mfr": dict(ifsm=130.0, pkg="SMA", note="onsemi MODPEX model; IFSM 130 A 60 Hz half wave"),
    "MBRA2H100_maxfit": dict(ifsm=130.0, pkg="SMA", note="same part, Fig. 2 maximum curve"),
    "VSSA310S_fit": dict(ifsm=60.0, pkg="SMA", note="3 A TMBS die; IFSM 60 A fails criterion (2)"),
    "SS3H10_mfr": dict(ifsm=100.0, pkg="SMC", note="3 A larger die, SMC (needs OUT-strip re-plan); "
                                                   "IFSM per Vishay doc 88752 TODO(verify)"),
    "none": dict(ifsm=float("nan"), pkg="-", note="D103 not fitted (reference)"),
}


def write_behav_models(write=True):
    """Write the behavioural D103 fits to sim/models/ with their source tables. Returns {name: model_text}.
    write=False (used by --tft-check) builds the same models in memory and leaves sim/models/ unchanged."""
    out = {}
    for name, d in BEHAV.items():
        IS, N, RS = fit_diode(d["points"], d["n_fixed"])
        mname = "D_" + name
        text = ("* Behavioural Schottky model %s, built by sim/hardshort/run.py on %s.\n"
                "* NOT a manufacturer model. Source table: %s.\n"
                "* Fit VF = N Vt ln(I/IS) + I RS at Tj = 25 C to the points (I A, VF V): %s.\n"
                "* Validity: only inside the fitted current range; above it the series term is a linear extension.\n"
                ".MODEL %s D IS=%.4e N=%.4f RS=%.5f CJO=%.3e M=0.45 VJ=0.4 BV=100 IBV=1e-4 TT=0\n"
                % (name, time.strftime("%Y-%m-%d"), d["src"], d["points"], mname, IS, N, RS, d["cjo"]))
        if write:
            with open(os.path.join(MODELS, "hardshort_%s.lib" % name), "w", encoding="ascii") as fh:
                fh.write(text)
        out[name] = (mname, text, (IS, N, RS))
    for name, (fn, mname) in MFR.items():
        with open(os.path.join(MODELS, fn), "r", encoding="ascii", errors="replace") as fh:
            out[name] = (mname, fh.read(), None)
    return out


DIODES = {}

# SMAJ33A (D107): Littelfuse SMAJ datasheet values as quoted in cr_bom.csv D107 row: VBR 36.70-40.60 V at 1 mA,
# Vc 53.3 V at Ipp 7.5 A -> dynamic resistance (53.3 - 40.6) / 7.5 = 1.69 ohm.
SMAJ_RDYN = 1.69
# Check correction 9: the v1 model had RS = 0.02 ohm and SMAJ_RDYN unused; RS now carries the 1.69 ohm figure.
SMAJ_MODEL = ".MODEL D_SMAJ33A D IS=1e-12 N=1.5 RS=%.4g BV={bv} IBV=1e-3 CJO=1.5n M=0.4 VJ=0.6\n" % SMAJ_RDYN

# ----------------------------------------------------------------------------------------------------------------
# Circuit parameters
# ----------------------------------------------------------------------------------------------------------------
MU0_PI = 4e-7

# U101 divider (gen/netlist.py lines 111-116; cr.net lines 493-528; cr_bom.csv rows R102-R104):
# R102 845k / R103 64.9k / R104 51.1k, VCHGIN -> N_UV -> N_OV -> GND.
R102, R103, R104 = 845e3, 64.9e3, 51.1e3
K_UV = (R102 + R103 + R104) / (R103 + R104)        # VIN per volt at the UVLO pin (TCKE1401NM Formula 4/5)
K_OV = (R102 + R103 + R104) / R104                 # VIN per volt at the OVP pin
# TCKE1401NM DS Rev. 3.0 Table 10.1: VUVLOR 1.142/1.19/1.224 V, VUVLOF 1.039/1.12/1.15 V, VOVPR 1.18/1.233/1.298 V;
# sec. 7.4 and the switching table: UVLO_toff 0.33 us typ, 3 us max; OVP_toff 0.74 us typ, 3 us max.
VIN_UVLOR = tuple(round(x * K_UV, 3) for x in (1.142, 1.19, 1.224))   # 9.46 / 9.86 / 10.14 V
VIN_UVLOF = tuple(round(x * K_UV, 3) for x in (1.039, 1.12, 1.15))    # 8.61 / 9.28 / 9.53 V
VIN_OVPR = tuple(round(x * K_OV, 3) for x in (1.18, 1.233, 1.298))    # 22.19 / 23.19 / 24.41 V
# With the +-320 nA UVLO/OVP pin leakage limit (Table 10.1; review PWR-2; sim/efuse_decay): UVLO falling 8.20-9.93 V,
# UVLO rising 9.06-10.55 V, OVP rising 21.59-25.02 V.
VIN_UVLOF_LEAK = (8.20, 9.93)
VIN_UVLOR_LEAK = (9.06, 10.55)
VIN_OVPR_LEAK = (21.59, 25.02)


def ovp_reach(v0):
    """Which U101 parts conduct at a static VCHG-IN of v0 (OVP rising band, without and with pin leakage)."""
    if v0 < VIN_OVPR_LEAK[0]:
        return "all parts"
    if v0 < VIN_OVPR[0]:
        return "all parts at typ. leakage"
    if v0 < VIN_OVPR[1]:
        return "parts with VOVPR >= %.3f V (typ. on)" % (v0 / K_OV)
    return "upper-tolerance parts only (VOVPR >= %.3f V; typ. is off)" % (v0 / K_OV)


def lead_lr():
    """W1/W2 twisted pair, 0.30 m, 20 AWG (design doc A.3 / H.23(p)): L' = (mu0/pi) acosh(s/2a) with s = jacket OD
    1.675 mm (mid of 1.60-1.75 mm) and a = 20 AWG solid radius 0.406 mm; R = 2 x 0.30 m x 33.31 mOhm/m (20 AWG at
    20 C) + 2 mOhm EVM terminal contact (ASSUMPTION)."""
    s, a = 1.675, 0.8128 / 2
    lp = MU0_PI * math.acosh(s / (2 * a))
    return lp * 0.30, 2 * 0.30 * 0.03331 + 0.002, lp


L_LEAD_NOM, R_LEAD_NOM, LPRIME = lead_lr()


def c102b_eff(v):
    # TDK DC-bias data for CNC6P1X7R2A475K250AE quoted in design doc B.4 C102b row (r9-22): 3.84 uF at 16 V,
    # 2.90 uF at 25 V; linear interpolation, clamped to [2.90, 4.40] uF (ASSUMPTION outside 16-25 V).
    return min(4.40e-6, max(2.90e-6, 3.84e-6 + (v - 16.0) * (2.90e-6 - 3.84e-6) / 9.0))


def c102a_eff(v):
    # Samsung CL31B105KCHSFNE 1 uF 100 V X7R 1206: DC-bias curve not read (cr_bom.csv row). ASSUMPTION 0.75 uF at
    # 16 V, 0.65 uF at 23.6 V (design doc H.5 uses 0.7 uF effective), linear, clamped [0.6, 0.9] uF.
    return min(0.9e-6, max(0.6e-6, 0.75e-6 + (v - 16.0) * (0.65e-6 - 0.75e-6) / 7.6))


BASE = dict(
    feed="veh", V0=23.6,
    # bench feed (T-C-04 r3: ~100-150 nH and ~20 uF)
    Cs=20e-6, Cs_esr=0.010, Lfeed=150e-9, Rfeed=0.025,
    # vehicle MB feed
    Rsrc=0.005, Lsrc=20e-9, Cvmot=400e-6, Cvmot_esr=0.010,     # H.6: C_VMOT 0.4-0.97 mF (lower bound used)
    # Check correction 6: VESC bulk -> motor-supply wire (ASSUMPTION, swept 20-1000 nH in set 'vmot') -> MB V-MOT node
    # with C-D6 + C-D7 (2 x 10 uF 1206, MB .sch lines 5913/5923, V-MOT net line 8852; 14 uF effective ASSUMPTION,
    # DC-bias curve not read; swept 0 / 14 uF) -> D-BC-RG VIN.
    Lwire=20e-9, Rwire=0.005, Cd67=14e-6, Cd67_esr=0.005,
    Ron_rt=0.025, rt_model="frc", tfrc=0.5e-6,                                # H.19: D-BC-RG RON 20-30 mOhm
    Cmb=4e-6, Cmb_esr=0.005, Cmb_esl=1e-9,                      # C-D8 + C-D10 effective, H.5 MB-end row (4-5 uF)
    Lmb=100e-9, Rmb=0.047,                                       # H.19: MB VCHG-IN copper 39-55 mOhm; L_IN 50-150 nH
    Rpin=0.005, Lpin=5e-9,                                       # H.19 "CR + pin 3-8 mOhm"; L ASSUMPTION
    # CR input
    c102_esr=0.005, c102_esl=1e-9, d107_bv=40.6,
    # U101 TCKE1401NM
    Ron=0.0445, Iscp=45.0, tscp=1.0e-6, ilim=2.37, tft=6e-6, tf=100e-9, tovp=None,
    # Check correction 2: UVLO turn-off path (VIN_UVLOF typ 9.28 V, UVLO_toff 0.33 us typ); uvlo=False disables it
    uvlo=True, Vuvf=VIN_UVLOF[1], tuv=0.33e-6,
    # OUT side
    C103=0.70e-6, C103_esr=0.005, C103_esl=1e-9, d103="STPS2H100A_fit", Ld=3e-9,
    Llead=L_LEAD_NOM, Rlead=R_LEAD_NOM,
    # EVM side at J1 (SLUUCB5E: J1 = VIN1 -> R2 10 mOhm sense -> ACFET1/RBFET1 -> VBUS C11, C12)
    evm=True, Cj1=48e-9, Revm=0.030, Levm=10e-9, Cvbus=8e-6, Cvbus_esr=0.005,
    # stimulus
    stim="short", Rsh=0.005, Lsh=0.0, tsh=2e-6, Iset=0.0, tend=60e-6, tstep=2e-9,
)


def deck(p, title):
    V0 = p["V0"]
    L = []
    a = L.append
    a("* hardshort %s" % title)
    if p["feed"] == "veh":
        a("Vsrc vs0 0 %.6g" % V0)
        a("Rsrc vs0 vs1 %.6g" % p["Rsrc"])
        a("Lsrc vs1 vmot %.6g" % p["Lsrc"])
        a("Cvm vmot cvm %.6g ic=%.6g" % (p["Cvmot"], V0))
        a("Rcvm cvm 0 %.6g" % p["Cvmot_esr"])
        a("Rwire vmot vw1 %.6g" % p["Rwire"])
        a("Lwire vw1 vmotmb %.6g" % p["Lwire"])
        # 1 nF pad/trace capacitance at the D-BC-RG VIN (ASSUMPTION; gives the node a capacitive path at the uic start)
        a("Cpad vmotmb 0 1n ic=%.6g" % V0)
        if p["Cd67"] > 0:
            a("Cd67 vmotmb cd671 %.6g ic=%.6g" % (p["Cd67"], V0))
            a("Rcd67 cd671 cd672 %.6g" % p["Cd67_esr"])
            a("Lcd67 cd672 0 1n")
        a("Vrt vmotmb vmot2 0")
        g = 1.0 / p["Ron_rt"]
        if p["rt_model"] == "res":
            a("Brt vmot2 mb I=(v(vmot2)-v(mb))*%.6g" % g)
        elif p["rt_model"] == "rcb":  # instantaneous reverse blocking (upper bracket of the RT1987 comparator)
            a("Brt vmot2 mb I=%.6g*(max(v(vmot2)-v(mb),0)+0.02*ln(1+exp(-abs(v(vmot2)-v(mb))/0.02)))" % g)
        else:  # "frc": RT1987 DS-00 sec. 17.6 fast reverse-current comparator: off when VOUT - VIN > 50 mV
            # (VFRC) has persisted for tFRC (0.5 us typ); back on when VIN > VOUT (forward servo not modelled)
            a("Bfrc 0 trc I=1m*0.5*(1+tanh((v(mb)-v(vmot2)-0.05)/0.005))"
              "-(0.5*(1-tanh((v(mb)-v(vmot2)-0.05)/0.005)))*v(trc)*0.1")
            a("Ctrc trc 0 1n ic=0")
            a("Rtrc trc 0 1e9")
            a("Brt vmot2 mb I=(v(vmot2)-v(mb))*%.6g*0.5*(1-tanh((v(trc)-%.6g)/0.01))" % (g, p["tfrc"] * 1e6))
        a("Cmb mb cmb1 %.6g ic=%.6g" % (p["Cmb"], V0))
        a("Rcmb cmb1 cmb2 %.6g" % p["Cmb_esr"])
        a("Lcmb cmb2 0 %.6g" % p["Cmb_esl"])
        a("Rmb mb mb1 %.6g" % p["Rmb"])
        a("Lmb mb1 pin %.6g" % p["Lmb"])
    else:
        a("Cs mb cs1 %.6g ic=%.6g" % (p["Cs"], V0))
        a("Rcs cs1 0 %.6g" % p["Cs_esr"])
        a("Rfd mb mb1 %.6g" % p["Rfeed"])
        a("Lfd mb1 pin %.6g" % p["Lfeed"])
        a("Vrt vx 0 0")  # dummy so the vector exists
        a("Rvx vx 0 1")
    # MB pin-38 divider R1-CHG 78.7k / R2-CHG 10k (MB VCHG-IN -> CHG-V)
    a("R1chg mb chgv 78.7k")
    a("R2chg chgv 0 10k")
    a("Rpin pin pin1 %.6g" % p["Rpin"])
    a("Lpin pin1 in %.6g" % p["Lpin"])
    # C102a/b/c (DC-bias derated) with ESR/ESL, D107
    for nm, c, esl in (("a", c102a_eff(V0), p["c102_esl"]), ("b", c102b_eff(V0), p["c102_esl"]),
                       ("c", 0.09e-6, 0.5e-9)):
        a("C102%s in n%s1 %.6g ic=%.6g" % (nm, nm, c, V0))
        a("R102%s n%s1 n%s2 %.6g" % (nm, nm, nm, p["c102_esr"]))
        a("L102%s n%s2 0 %.6g" % (nm, nm, esl))
    a("Vd107 in d107k 0")
    a("D107 0 d107k D_SMAJ33A")
    # U101: switch with latch timers (timer node voltage in volts = microseconds)
    a("Vsense in in2 0")
    ift = 2.0 * p["ilim"]
    a("Bscp 0 nscp I=1m*0.5*(1+tanh((i(vsense)-%.6g)/0.5))" % p["Iscp"])
    a("Cscp nscp 0 1n ic=0")
    a("Rscp nscp 0 1e12")
    a("Bft 0 nft I=1m*0.5*(1+tanh((i(vsense)-%.6g)/0.1))" % ift)
    a("Cft nft 0 1n ic=0")
    a("Rft nft 0 1e12")
    a("Btscp 0 tscp I=1m*0.5*(1+tanh((v(nscp)-0.005)/0.002))")
    a("Ctscp tscp 0 1n ic=0")
    a("Rtscp tscp 0 1e12")
    a("Btft 0 tft I=1m*0.5*(1+tanh((v(nft)-0.005)/0.002))")
    a("Ctft tft 0 1n ic=0")
    a("Rtft tft 0 1e12")
    tf_us = p["tf"] * 1e6
    terms = ["(v(tscp)-%.6g)/%.6g" % (p["tscp"] * 1e6, tf_us), "(v(tft)-%.6g)/%.6g" % (p["tft"] * 1e6, tf_us)]
    if p.get("uvlo"):
        # UVLO comparator: the timer integrates (in us) while VIN is below VIN_UVLOF; the FET starts to open UVLO_toff
        # later. The timer does not reset if VIN recovers (conservative: earliest opening); after a UVLO opening
        # the FET stays off for the run (re-turn-on is a soft start on a ms scale).
        a("Buv 0 nuv I=1m*0.5*(1+tanh((%.6g-v(in))/0.02))" % p["Vuvf"])
        a("Cuv nuv 0 1n ic=0")
        a("Ruv nuv 0 1e12")
        terms.append("(v(nuv)-%.6g)/%.6g" % (p["tuv"] * 1e6, tf_us))
    if p.get("tovp") is not None:
        terms.append("(time*1e6-%.6g)/%.6g" % (p["tovp"] * 1e6, tf_us))
    arg = terms[0]
    for t in terms[1:]:
        arg = "max(%s,%s)" % (arg, t)
    a("Bfrac frac 0 V=0.5*(1-tanh(6*(%s-0.5)))" % arg)
    a("Bfet in2 out I=(v(in2)-v(out))*(v(frac)/%.6g+1e-9)" % p["Ron"])
    # OUT: C103, D103 (with loop inductance), W1/W2 lead
    a("C103 out o1 %.6g ic=%.6g" % (p["C103"], V0))
    a("R103 o1 o2 %.6g" % p["C103_esr"])
    a("L103 o2 0 %.6g" % p["C103_esl"])
    if p["d103"] != "none":
        a("D103 0 dk %s" % DIODES[p["d103"]][0])
        a("Ld dk dk2 %.6g" % p["Ld"])
        a("Vd dk2 out 0")
    else:
        a("Vd dk2 out 0")
        a("Rdk dk2 0 1e9")
    a("Vlead out ol 0")
    a("Rlead ol ol1 %.6g" % p["Rlead"])
    a("Llead ol1 j1 %.6g" % p["Llead"])
    # J1 node and EVM input (VIN1 -> R2 -> ACFET1/RBFET1 -> VBUS C11 + C12)
    a("Cj1 j1 0 %.6g ic=%.6g" % (p["Cj1"], V0))
    if p["evm"]:
        a("Revm j1 ev1 %.6g" % p["Revm"])
        a("Levm ev1 ev2 %.6g" % p["Levm"])
        a("Cvbus ev2 ev3 %.6g ic=%.6g" % (p["Cvbus"], V0))
        a("Rvbus ev3 0 %.6g" % p["Cvbus_esr"])
    # stimulus
    if p["stim"] == "short":
        if p.get("Lsh", 0.0) > 0:
            # Check correction 8: series inductance of the short resistor and its bench wiring (ASSUMPTION, swept)
            a("Lsh j1 jsh %.6g" % p["Lsh"])
            a("Bsh jsh 0 I=v(jsh)*(0.5*(1+tanh((time-%.6g)/5n))/%.6g+1e-9)" % (p["tsh"], p["Rsh"]))
        else:
            a("Bsh j1 0 I=v(j1)*(0.5*(1+tanh((time-%.6g)/5n))/%.6g+1e-9)" % (p["tsh"], p["Rsh"]))
    elif p["stim"] == "load":
        a("Bld j1 0 I=%.6g*tanh(v(j1)/0.5)*0.5*(1+tanh((time-%.6g)/0.2u))" % (p["Iset"], p["tsh"]))
    a(SMAJ_MODEL.format(bv=p["d107_bv"]).strip())
    if p["d103"] != "none":
        for line in DIODES[p["d103"]][1].splitlines():
            if line.strip() and not line.strip().startswith("*"):
                a(line)
    a(".options method=gear reltol=1e-4 abstol=1e-9 vntol=1e-6 itl4=200")
    a(".tran %.6g %.6g 0 %.6g uic" % (p["tstep"], p["tend"], p["tstep"]))
    a(".end")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------------------------
# Run and measure
# ----------------------------------------------------------------------------------------------------------------
VEC = {"t": "time", "out": "out", "in": "in", "mb": "mb", "j1": "j1", "chgv": "chgv",
       "ifet": "vsense#branch", "ilead": "vlead#branch", "id": "vd#branch", "irt": "vrt#branch",
       "id107": "vd107#branch", "frac": "frac", "tscp": "tscp", "tft": "tft", "nuv": "nuv"}


def diode_params(name):
    """(IS, N, RS) of a D103 case: the fit tuple, or parsed from the maker's .MODEL text."""
    mname, text, fit = DIODES[name]
    if fit:
        return fit
    import re
    body = " ".join(ln.lstrip("+") for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("*"))
    vals = {}
    for key in ("IS", "N", "RS"):
        m = re.search(r"\b%s\s*=\s*([0-9.eE+-]+)" % key, body, re.I)
        vals[key] = float(m.group(1)) if m else float("nan")
    return vals["IS"], vals["N"], vals["RS"]


def vf_of(name, i):
    IS, N, RS = diode_params(name)
    return N * VT25 * math.log(i / IS + 1.0) + i * RS


def cross_down(t, y, thr):
    """Interpolated times at which y falls through thr (list)."""
    d = y - thr
    idx = np.where((d[:-1] > 0) & (d[1:] <= 0))[0]
    return [float(t[i] + (t[i + 1] - t[i]) * d[i] / (d[i] - d[i + 1])) for i in idx]


def integ(y, t):
    return float(np.trapezoid(y, t)) if hasattr(np, "trapezoid") else float(np.trapz(y, t))


def time_below(v, t, thr):
    """Total time with v < thr. Each sample interval counts 1 if both ends are below, 0.5 if one end is below.
    (Check correction 1: the bool arrays are cast to float before the sum; the v1 script added two bool arrays, which
    numpy evaluates as a logical OR, so every interval was weighted 0.5 and every duration was halved.)"""
    m = (np.asarray(v) < thr).astype(float)
    if not m.any():
        return 0.0
    dt = np.diff(t)
    return float(np.sum(dt * 0.5 * (m[:-1] + m[1:])))


def _selftest_time_below():
    """Unit check of time_below on a known square wave: 1 us period, 50 % duty, 10 us -> 5.0 us below 0."""
    t = np.linspace(0.0, 10e-6, 100001)
    v = np.where((t * 1e6) % 1.0 < 0.5, -1.0, 1.0)
    got = time_below(v, t, 0.0)
    assert abs(got - 5.0e-6) < 2e-9, got
    t2 = np.array([0.0, 1.0, 2.0, 3.0])
    assert time_below(np.array([-1.0, -1.0, -1.0, -1.0]), t2, 0.0) == 3.0
    assert time_below(np.array([1.0, 1.0, 1.0, 1.0]), t2, 0.0) == 0.0
    return got


def measure(r, p):
    w = {k: np.asarray(r[v]).real for k, v in VEC.items() if v in r.vec}
    V0 = p["V0"]
    o = {}
    # The uic start has a sub-ns settling transient (junction capacitances start at 0 V). Measure only from
    # 1.0 us on, and record the largest deviation of U101 IN from V0 in 1.0 us .. 0.95 x tsh as a check.
    t_all = w["t"]
    pre = (t_all >= 1.0e-6) & (t_all <= 0.95 * p["tsh"])
    o["pre_dev_V"] = float(np.abs(w["in"][pre] - V0).max()) if pre.any() else float("nan")
    m = t_all >= 1.0e-6
    w = {k: v[m] for k, v in w.items()}
    t = w["t"]
    o["out_min_V"] = float(w["out"].min())
    o["t_out_below_m0p3_us"] = time_below(w["out"], t, -0.3) * 1e6
    o["t_out_below_0_us"] = time_below(w["out"], t, 0.0) * 1e6
    # Check correction 4: spike and plateau reported separately
    o["t_out_below_m1_us"] = time_below(w["out"], t, -1.0) * 1e6
    o["t_out_below_m2_us"] = time_below(w["out"], t, -2.0) * 1e6
    o["t_out_below_m3_us"] = time_below(w["out"], t, -3.0) * 1e6
    if o["out_min_V"] < -0.3:
        half = 0.5 * o["out_min_V"]
        o["t_spike_us"] = time_below(w["out"], t, half) * 1e6           # width below half the minimum
        below = np.where(w["out"] < half)[0]
        t_end = t[below[-1]]
        win = (t >= t_end + 0.2e-6) & (t <= t_end + 2.2e-6)
        o["plateau_V"] = integ(w["out"][win], t[win]) / max(1e-12, t[win][-1] - t[win][0]) if win.sum() > 2 \
            else float("nan")
    else:
        o["t_spike_us"] = 0.0
        o["plateau_V"] = float("nan")
    o["in_peak_V"] = float(w["in"].max())
    o["mb_peak_V"] = float(w["mb"].max())
    o["pin38_peak_V"] = float(w["chgv"].max())
    o["t_pin38_above_3p3_us"] = time_below(-w["chgv"], t, -3.3) * 1e6
    o["t_mb_above_35_us"] = time_below(-w["mb"], t, -35.0) * 1e6
    o["mb_end_V"] = float(w["mb"][-1])
    o["ifet_peak_A"] = float(w["ifet"].max())
    o["ilead_peak_A"] = float(w["ilead"].max())
    idd = w["id"]
    o["id103_peak_A"] = float(idd.max())
    o["id103_i2t_A2s"] = integ(np.clip(idd, 0, None) ** 2, t)
    o["irt_peak_A"] = float(np.abs(w["irt"]).max()) if p["feed"] == "veh" else float("nan")
    o["id107_peak_A"] = float(-w["id107"].min()) if w["id107"].min() < 0 else 0.0
    # FET turn-off instant: frac crosses 0.5
    fr = w["frac"]
    k = np.where(fr < 0.5)[0]
    o["t_off_us"] = float(t[k[0]] * 1e6) if len(k) else float("nan")
    o["ifet_at_off_A"] = float(w["ifet"][k[0]]) if len(k) else float("nan")
    # which turn-off term opened the FET (largest term at the frac = 0.5 instant)
    if len(k):
        j = k[0]
        cand = {"SCP": (w["tscp"][j] - p["tscp"] * 1e6), "FASTTRIP": (w["tft"][j] - p["tft"] * 1e6)}
        if p.get("uvlo") and "nuv" in w:
            cand["UVLO"] = w["nuv"][j] - p["tuv"] * 1e6
        if p.get("tovp") is not None:
            cand["OVP"] = t[j] * 1e6 - p["tovp"] * 1e6
        o["trip_path"] = max(cand, key=cand.get)
    else:
        o["trip_path"] = "none"
    # Check correction 5: effective FET current fall time (90 % -> 10 % of the current at the start of the fall)
    o["t_fall_90_10_ns"] = float("nan")
    if len(k):
        jpk = int(np.argmax(w["ifet"][: k[0] + 1]))
        ipk = float(w["ifet"][jpk])
        if ipk > 0.5:
            t90 = cross_down(t[jpk:], w["ifet"][jpk:], 0.9 * ipk)
            t10 = cross_down(t[jpk:], w["ifet"][jpk:], 0.1 * ipk)
            if t90 and t10:
                o["t_fall_90_10_ns"] = (t10[0] - t90[0]) * 1e9
    # Check correction 9: analytic cross-check of the OUT minimum, VF(I0) + I0 sqrt(L_loop / C103), with I0 the lead
    # current when OUT first crosses 0 V after the turn-off and L_loop = L_d + ESL(C103)
    o["i0_at_zero_A"] = float("nan")
    o["out_min_est_V"] = float("nan")
    o["vf_i0_V"] = float("nan")
    o["k_ring"] = float("nan")
    if len(k) and p["d103"] != "none":
        z = np.where((t > t[k[0]]) & (w["out"] < 0.0))[0]
        if len(z):
            i0 = float(w["ilead"][z[0]])
            o["i0_at_zero_A"] = i0
            if i0 > 0:
                lloop = p["Ld"] + p["C103_esl"]
                zc = math.sqrt(lloop / p["C103"])
                vf0 = vf_of(p["d103"], i0)
                o["out_min_est_V"] = -(vf0 + i0 * zc)
                o["vf_i0_V"] = vf0
                # effective ring factor k: OUT_min = -(VF(I0) + k I0 Zc); k = 1 is the undamped LC bound
                o["k_ring"] = (-o["out_min_V"] - vf0) / (i0 * zc)
    pfet = (w["in"] - w["out"]) * w["ifet"]
    o["e_fet_mJ"] = integ(np.clip(pfet, 0, None), t) * 1e3
    o["out_min_over_V0"] = o["out_min_V"] - V0
    # U101 VIN minimum while the FET conducts (up to the turn-off instant): VIN collapses under the short
    if len(k):
        o["in_min_on_V"] = float(w["in"][: k[0] + 1].min())
    else:
        o["in_min_on_V"] = float(w["in"].min())
    return o, w


def run_case(cid, p, keep=False):
    txt = deck(p, cid)
    with open(os.path.join(DECKS, cid + ".cir"), "w", encoding="ascii") as fh:
        fh.write(txt)
    r = run_deck(txt, plots="last", timeout_s=900)
    if not r.ok or "out" not in r.vec:
        return cid, p, None, None, (r.errors[:5] or ["no vectors"])
    o, w = measure(r, p)
    return cid, p, o, (w if keep else None), r.errors[:3]


def run_many(cases, keep_ids=(), workers=4, label=""):
    t0 = time.time()
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_case, cid, p, cid in keep_ids) for cid, p in cases]
        for f in futs:
            cid, p, o, w, err = f.result()
            out[cid] = (p, o, w, err)
            if o is None:
                print("  FAIL %s: %s" % (cid, "; ".join(err)))
    print("  %s: %d cases in %.1f s" % (label, len(cases), time.time() - t0))
    return out


def mk(**kw):
    p = dict(BASE)
    p.update(kw)
    return p


PARAM_COLS = ["feed", "V0", "stim", "Rsh", "Lsh", "Iset", "d103", "Llead", "Rlead", "Ron", "Iscp", "tscp", "tft",
              "ilim", "tf", "tovp", "uvlo", "Vuvf", "tuv", "Ld", "C103", "Lmb", "Cmb", "rt_model", "Lwire", "Cd67",
              "Cvmot", "evm", "d107_bv", "Lfeed", "Cs"]
OUT_COLS = ["pre_dev_V", "out_min_V", "out_min_est_V", "i0_at_zero_A", "vf_i0_V", "k_ring", "t_out_below_m0p3_us", "t_out_below_0_us",
            "t_out_below_m1_us", "t_out_below_m2_us", "t_out_below_m3_us", "t_spike_us", "plateau_V",
            "t_fall_90_10_ns", "trip_path", "id103_peak_A", "id103_i2t_A2s",
            "ilead_peak_A", "ifet_peak_A", "ifet_at_off_A", "t_off_us", "e_fet_mJ", "in_min_on_V", "in_peak_V", "id107_peak_A",
            "mb_peak_V", "pin38_peak_V", "t_pin38_above_3p3_us", "mb_end_V", "irt_peak_A"]


def write_csv(name, res, extra_cols=()):
    path = os.path.join(RES, name)
    with open(path, "w", newline="", encoding="ascii") as fh:
        wr = csv.writer(fh)
        wr.writerow(["case"] + list(extra_cols) + PARAM_COLS + OUT_COLS)
        for cid, (p, o, _w, _e) in res.items():
            if o is None:
                wr.writerow([cid, "FAILED"])
                continue
            row = [cid] + [p.get(c, "") for c in extra_cols]
            for c in PARAM_COLS:
                v = p.get(c)
                row.append("%.6g" % v if isinstance(v, float) else v)
            row += [("%.6g" % o[c]) if not isinstance(o[c], str) else o[c] for c in OUT_COLS]
            wr.writerow(row)
    return path


# ----------------------------------------------------------------------------------------------------------------
# Validation against round4/calc/r7_calc.py in_spike (ported verbatim, lines 4328-4351)
# ----------------------------------------------------------------------------------------------------------------
def in_spike_ref(v0, cs, lin, cin, rin=0.045, ron=0.031, cout=1.0e-6, lout=0.15e-6, dt=1e-9, tend=12e-6):
    vs, vin, vout = v0, v0, v0
    i_in, i_fet, i_out = 0.0, 0.0, 0.0
    t, t_cross, on, vpk, i_off, i_out_pk = 0.0, None, True, v0, 0.0, 0.0
    while t < tend:
        di_in = (vs - i_in * rin - vin) / lin
        i_in += di_in * dt
        i_fet = (vin - vout) / ron if on else 0.0
        di_out = vout / lout
        i_out += di_out * dt
        i_out_pk = max(i_out_pk, i_out)
        vs -= i_in / cs * dt
        vin += (i_in - i_fet) / cin * dt
        vout += (i_fet - i_out) / cout * dt
        if on and t_cross is None and i_fet > 45.0:
            t_cross = t
        if on and t_cross is not None and t >= t_cross + 1e-6:
            on = False
            i_off = i_in
        if not on:
            vpk = max(vpk, vin)
        t += dt
    return vpk, i_off, i_out_pk


def validation():
    """Reduce the deck to the in_spike topology (bench feed, ideal parts, no D103/D107/EVM, 0-ohm short) and
    compare with the Python reference at the H.23(p) worst case: V0 22 V, C_S 20 uF, L_IN 150 nH, lout 115.7 nH."""
    lout = 115.7e-9
    ref = in_spike_ref(22.0, 20e-6, 150e-9, 3.4e-6, lout=lout)
    txt = "\n".join([
        "* validation vs r7_calc in_spike",
        "Cs mb 0 20u ic=22", "Rin mb m1 0.045", "Vlin m1 m2 0", "Lin m2 in 150n",
        "Cin in 0 3.4u ic=22", "Vsense in in2 0",
        "Bscp 0 nscp I=1m*0.5*(1+tanh((i(vsense)-45)/0.05))", "Cscp nscp 0 1n ic=0", "Rscp nscp 0 1e12",
        "Btscp 0 tscp I=1m*0.5*(1+tanh((v(nscp)-0.0005)/0.0002))", "Ctscp tscp 0 1n ic=0", "Rtscp tscp 0 1e12",
        "Bfrac frac 0 V=0.5*(1-tanh(6*((v(tscp)-1.0)/0.002-0.5)))",
        "Bfet in2 out I=(v(in2)-v(out))*(v(frac)/0.031+1e-9)",
        "Cout out 0 1u ic=22", "Vlead out j1 0", "Llead j1 0 %.6g" % lout,
        ".options method=gear reltol=1e-5", ".tran 1n 12u 0 1n uic", ".end", ""])
    with open(os.path.join(DECKS, "validation_in_spike.cir"), "w", encoding="ascii") as fh:
        fh.write(txt)
    r = run_deck(txt, plots="last")
    t = r["time"].real
    vin = r["in"].real
    frac = r["frac"].real
    k = np.where(frac < 0.5)[0][0]
    vpk = float(vin[k:].max())
    i_lead = float(r["vlead#branch"].real.max())
    # input current at turn-off = the current in L_IN when the FET conductance crosses 50 %
    i_in_off = float(r["vlin#branch"].real[k])
    rows = [("IN peak after turn-off (V)", ref[0], vpk), ("input current at turn-off (A)", ref[1], i_in_off),
            ("W1/W2 lead peak current (A)", ref[2], i_lead)]
    with open(os.path.join(RES, "validation_in_spike.csv"), "w", newline="", encoding="ascii") as fh:
        wr = csv.writer(fh)
        wr.writerow(["quantity", "r7_calc_in_spike_python", "ngspice_deck", "rel_diff"])
        for q, a_, b_ in rows:
            wr.writerow([q, "%.4f" % a_, "%.4f" % b_, "%.4f" % ((b_ - a_) / a_)])
    print("  validation vs r7_calc in_spike (V0 22 V, C_S 20 uF, L_IN 150 nH, lout 115.7 nH):")
    for q, a_, b_ in rows:
        print("    %-34s python %8.3f  ngspice %8.3f  (%+.2f %%)" % (q, a_, b_, 100 * (b_ - a_) / a_))
    return rows


# ----------------------------------------------------------------------------------------------------------------
# Case sets
# ----------------------------------------------------------------------------------------------------------------
D103_LIST = ["STPS2H100A_fit", "MBRA2H100_mfr", "MBRA2H100_maxfit", "VSSA310S_fit", "SS3H10_mfr", "none"]


def set_grid(quick=False):
    cases = []
    feeds = ["bench", "veh"]
    vs = [16.0, 22.0, 23.6] if not quick else [23.6]
    rshs = [0.005, 0.050] if not quick else [0.005]
    lsc = [0.7, 1.0, 1.3] if not quick else [1.0]
    ds = D103_LIST if not quick else ["STPS2H100A_fit"]
    for f in feeds:
        for v in vs:
            for rs in rshs:
                for ls in lsc:
                    for d in ds:
                        cid = "grid_%s_V%04.1f_R%02dm_L%.1f_%s" % (f, v, round(rs * 1e3), ls, d)
                        cases.append((cid, mk(feed=f, V0=v, Rsh=rs, Llead=L_LEAD_NOM * ls, d103=d)))
    return cases


def set_sens(quick=False):
    """One-at-a-time sensitivity around the worst baseline (vehicle feed, 23.6 V, 5 mOhm short, nominal lead)."""
    base = dict(feed="veh", V0=23.6, Rsh=0.005)
    var = [("base", {}),
           ("Rlead_m30", dict(Rlead=R_LEAD_NOM * 0.7)), ("Rlead_p30", dict(Rlead=R_LEAD_NOM * 1.3)),
           ("Ron_max80m", dict(Ron=0.080)),
           ("tscp_0p5us", dict(tscp=0.5e-6)), ("tscp_2us", dict(tscp=2.0e-6)),
           ("tf_20ns", dict(tf=20e-9)), ("tf_300ns", dict(tf=300e-9)),
           ("Iscp_30A", dict(Iscp=30.0)), ("Iscp_60A", dict(Iscp=60.0)),
           ("Ld_1p5nH", dict(Ld=1.5e-9)), ("Ld_6nH", dict(Ld=6e-9)),
           ("C103_0p5u", dict(C103=0.5e-6)), ("C103_1p0u", dict(C103=1.0e-6)),
           ("Lmb_50n", dict(Lmb=50e-9)), ("Lmb_150n", dict(Lmb=150e-9)),
           ("Cmb_8u", dict(Cmb=8e-6)), ("Cmb_2p5u", dict(Cmb=2.5e-6)),
           ("rt_rcb", dict(rt_model="rcb")), ("rt_res", dict(rt_model="res")), ("Ron_rt_20m", dict(Ron_rt=0.020)), ("Ron_rt_30m", dict(Ron_rt=0.030)),
           ("evm_off", dict(evm=False)), ("d107_bv_min", dict(d107_bv=36.7)),
           ("Rmb_39m", dict(Rmb=0.039)), ("Rmb_55m", dict(Rmb=0.055)),
           ("Cvmot_970u", dict(Cvmot=970e-6)),
           ("uvlo_off", dict(uvlo=False)), ("uvlo_8p20V_3us", dict(Vuvf=8.20, tuv=3e-6)),
           ("uvlo_9p93V", dict(Vuvf=9.93)),
           ("tscp_2us_uvlo_late", dict(tscp=2.0e-6, Vuvf=8.20, tuv=3e-6)),
           ("tscp_2us_uvlo_off", dict(tscp=2.0e-6, uvlo=False))]
    if quick:
        var = var[:2]
    cases = []
    for d in ("STPS2H100A_fit", "MBRA2H100_mfr"):
        for name, kv in var:
            q = dict(base)
            q.update(kv)
            cases.append(("sens_%s_%s" % (d, name), mk(d103=d, **q)))
    return cases


def set_ladder(quick=False):
    cases = []
    # Check correction 2: the v1 8 V step is not runnable (VIN_UVLOR 9.46-10.14 V, 9.06-10.55 V with pin leakage:
    # U101 is held off by UVLO at 8 V). The lowest runnable start is above 10.55 V; 10.6 V is used.
    vs = [10.6, 12.0, 16.0, 20.0, 22.0, 23.6] if not quick else [10.6]
    for f in ("bench", "veh"):
        for v in vs:
            for d in ("STPS2H100A_fit", "MBRA2H100_mfr"):
                for lmb in ((100e-9, 150e-9) if f == "bench" else (50e-9, 150e-9)):
                    k = "Lfeed" if f == "bench" else "Lmb"
                    cases.append(("ladder_%s_V%04.1f_L%03dn_%s" % (f, v, round(lmb * 1e9), d),
                                  mk(feed=f, V0=v, Rsh=0.005, d103=d, **{k: lmb})))
    return cases


def set_soft(quick=False):
    """T-C-04 step (1): electronic load at J1 above the fast-trip level. I_FT = 2 x I_LIM; I_LIM 1.97/2.37/2.77 A
    (R101 8.45k band, design doc B.4 R101 row, UNVERIFIED extrapolation). tFASTTRIP 4-8 us (Table 10.3)."""
    cases = []
    combos = [(4.1, 1.97), (5.5, 2.37), (5.5, 2.70)]
    for f in ("bench", "veh"):
        for v in (16.0, 23.6):
            for iset, il in combos:
                for tft in (4e-6, 8e-6):
                    cid = "soft_%s_V%04.1f_I%.1f_ILIM%.2f_tft%dus" % (f, v, iset, il, round(tft * 1e6))
                    cases.append((cid, mk(feed=f, V0=v, stim="load", Iset=iset, ilim=il, tft=tft,
                                          d103="STPS2H100A_fit", tend=40e-6)))
    return cases[:2] if quick else cases


def set_ovp(quick=False):
    """T-C-04 step (3): 1.7 A load, VIN just above the OVP maximum (24.41 V) -> FET opens at tovp."""
    cases = []
    for f in ("bench", "veh"):
        for tf in (20e-9, 100e-9, 300e-9):
            for d in ("STPS2H100A_fit", "MBRA2H100_mfr"):
                cid = "ovp_%s_tf%03dns_%s" % (f, round(tf * 1e9), d)
                cases.append((cid, mk(feed=f, V0=24.5, stim="load", Iset=1.7, tsh=2e-6, tovp=12e-6, tf=tf,
                                      d103=d, tend=40e-6)))
    return cases[:1] if quick else cases


def set_rsh(quick=False):
    """Extra: the short resistance as a test-ordering lever. Above about 0.5 ohm the current stays below I_SCP 45 A
    and the fast-trip path (4-8 us) opens the FET at a lower current."""
    cases = []
    for f in ("bench", "veh"):
        for v in (16.0, 23.6):
            for rsh in ([0.005, 0.05, 0.1, 0.2, 0.3, 0.5, 0.9, 1.0, 1.5, 2.0] if not quick else [0.5]):
                for d in ("STPS2H100A_fit", "MBRA2H100_mfr"):
                    # Check correction 8: R_short 0.9 ohm (1 ohm at -10 %) and 1.5 ohm added; L_short 0 and 100 nH
                    # (ASSUMPTION: resistor body plus about 0.1 m of bench wiring) for R_short >= 0.5 ohm
                    for lsh in ((0.0, 100e-9) if rsh >= 0.5 else (0.0,)):
                        cases.append(("rsh_%s_V%04.1f_R%04dm_Lsh%03dn_%s" % (f, v, round(rsh * 1e3),
                                                                             round(lsh * 1e9), d),
                                      mk(feed=f, V0=v, Rsh=rsh, Lsh=lsh, d103=d)))
    return cases


# R2-SIM-9 (second review, 2026-11-15): the base tFASTTRIP of 6 us is the midpoint of the TCKE1401NM DS Rev. 3.0
# Table 10.3 row for 6 kOhm < RILIM <= 30 kOhm (4 us typical, 8 us maximum); R101 is 8.45 kOhm, so that row applies.
# The --tft-check mode re-runs the rsh set and the headline hard-short grid cases at 4, 6 and 8 us, and at 3 us:
# DS sec. 7.9 (p.9) gives a 3 us (Typ.) fast-trip response for IFASTTRIP < IOUT < ISCP, below the Table 10.3 typical.
TFT_CHECK = (3e-6, 4e-6, 6e-6, 8e-6)
TFT_TAGS = tuple(round(x * 1e6) for x in TFT_CHECK)


def set_tft_check():
    cases = []
    for tft in TFT_CHECK:
        tag = "tft%dus" % round(tft * 1e6)
        for cid, p in set_rsh():
            q = dict(p)
            q["tft"] = tft
            cases.append(("%s_%s" % (tag, cid), q))
        for f in ("bench", "veh"):
            for v in (16.0, 22.0, 23.6):
                for d in ("STPS2H100A_fit", "MBRA2H100_mfr"):
                    cid = "%s_grid_%s_V%04.1f_R05m_L1.0_%s" % (tag, f, v, d)
                    cases.append((cid, mk(feed=f, V0=v, Rsh=0.005, Llead=L_LEAD_NOM, d103=d, tft=tft)))
    return cases


def tft_check():
    """Run set_tft_check(); write results/tft_check.csv and results/tft_check.md. No other output is touched."""
    print("hardshort --tft-check: %s" % ngspice_version())
    DIODES.update(write_behav_models(write=False))
    res = run_many(set_tft_check(), workers=4, label="tft_check")
    write_csv("tft_check.csv", res)
    keys = sorted(set(k.split("_", 1)[1] for k in res))
    lines = ["# Sim 1 tFASTTRIP check (R2-SIM-9)", "",
             "Generated by `run.py --tft-check`. tFASTTRIP 4 us (typical) and 8 us (maximum) are the TCKE1401NM DS "
             "Rev. 3.0 Table 10.3 values for 6 kOhm < RILIM <= 30 kOhm (R101 8.45 kOhm); 3 us is the DS sec. 7.9 typical for "
             "IFASTTRIP < IOUT < ISCP; 6 us is the base value of every other set of this simulation.", "",
             "| Case | OUT min 3 / 4 / 6 / 8 us (V) | trip path 3 / 4 / 6 / 8 us | I_FET at turn-off 3 / 4 / 6 / 8 us (A) "
             "| t(OUT < -0.3 V) 3 / 4 / 6 / 8 us (us) | turn-off instant 3 / 4 / 6 / 8 us (us of run time; short at 2 us) |",
             "|---|---|---|---|---|---|"]
    for key in keys:
        r = [res.get("tft%dus_%s" % (n, key)) for n in TFT_TAGS]
        if any(x is None or x[1] is None for x in r):
            lines.append("| %s | FAILED | | | | |" % key)
            continue
        o = [x[1] for x in r]
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            key, " / ".join("%.3f" % x["out_min_V"] for x in o), " / ".join(x["trip_path"] for x in o),
            " / ".join("%.1f" % x["ifet_at_off_A"] for x in o),
            " / ".join("%.2f" % x["t_out_below_m0p3_us"] for x in o),
            " / ".join("%.2f" % x["t_off_us"] for x in o)))
    with open(os.path.join(RES, "tft_check.md"), "w", encoding="ascii") as fh:
        fh.write("\n".join(lines) + "\n")
    print("  wrote results/tft_check.csv and results/tft_check.md (%d case keys)" % len(keys))


def set_uvlo(quick=False):
    """Check correction 2: the UVLO turn-off path at the lower starts. UVLO off / typ (9.28 V, 0.33 us) / latest
    (8.20 V with pin leakage, 3 us max delay) / earliest (9.93 V, 0.33 us)."""
    var = [("off", dict(uvlo=False)), ("typ", {}), ("late", dict(Vuvf=8.20, tuv=3e-6)), ("early", dict(Vuvf=9.93))]
    cases = []
    for f in ("bench", "veh"):
        for v in ((10.6, 12.0, 16.0, 22.0) if not quick else (12.0,)):
            for name, kv in var:
                for d in ("STPS2H100A_fit", "MBRA2H100_mfr"):
                    cases.append(("uvlo_%s_V%04.1f_%s_%s" % (f, v, name, d), mk(feed=f, V0=v, Rsh=0.005, d103=d,
                                                                                 **kv)))
    return cases


def set_vmot(quick=False):
    """Check correction 6: the vehicle feed with the VESC bulk behind a swept wire inductance and the MB C-D6/C-D7
    local capacitance present or absent; also the MB-end worst corner (L_MB 150 nH, C-D8 + C-D10 2.5 uF)."""
    cases = []
    for v in ((22.0, 23.6) if not quick else (23.6,)):
        for lw in (20e-9, 100e-9, 300e-9, 1000e-9):
            for cd in (0.0, 14e-6):
                for corner, kv in (("nom", {}), ("mbw", dict(Lmb=150e-9, Cmb=2.5e-6))):
                    cases.append(("vmot_V%04.1f_Lw%04dn_Cd%02du_%s" % (v, round(lw * 1e9), round(cd * 1e6), corner),
                                  mk(feed="veh", V0=v, Rsh=0.005, d103="MBRA2H100_mfr", Lwire=lw, Cd67=cd,
                                     tend=200e-6, tstep=5e-9, **kv)))
    return cases[:2] if quick else cases


def set_mbend(quick=False):
    """Extra: the MB end (C-D8 node, pin 38) against the RT1987 reverse-current behaviour, the MB copper inductance
    and the effective C-D8 + C-D10 capacitance. Vehicle feed only; D103 = MBRA2H100 (no effect on the MB end)."""
    cases = []
    vs = [16.0, 22.0, 23.6] if not quick else [23.6]
    for v in vs:
        for lmb in (50e-9, 150e-9):
            for cmb in (2.5e-6, 4e-6, 8e-6):
                for rt in ("res", "frc", "rcb"):
                    cases.append(("mbend_V%04.1f_L%03dn_C%.1fu_%s" % (v, round(lmb * 1e9), cmb * 1e6, rt),
                                  mk(feed="veh", V0=v, Rsh=0.005, Lmb=lmb, Cmb=cmb, rt_model=rt,
                                     d103="MBRA2H100_mfr", tend=200e-6, tstep=5e-9)))
    return cases


def set_rs(quick=False):
    """Extra: what a D103 would need. MBRA2H100 max-fit exponential (IS, N of the fit) with RS swept from 0; the
    RS = 0, L_d = 0 case is 'MBRA max-fit exponential, RS = 0', not an ideal diode."""
    IS, N, _ = DIODES["MBRA2H100_maxfit"][2]
    cases = []
    for rs in ([0.0, 0.002, 0.005, 0.010, 0.020, 0.040] if not quick else [0.0]):
        for ld in (0.0, 3e-9):
            nm = "RS%03dm_Ld%dn" % (round(rs * 1e3), round(ld * 1e9))
            DIODES["rs_" + nm] = ("D_rs_" + nm, ".MODEL D_rs_%s D IS=%.4e N=%.4f RS=%.5f CJO=500p TT=0\n"
                                  % (nm, IS, N, max(rs, 1e-5)), None)
            cases.append(("rs_" + nm, mk(feed="veh", V0=23.6, Rsh=0.005, d103="rs_" + nm, Ld=max(ld, 1e-12))))
    return cases


# ----------------------------------------------------------------------------------------------------------------
# Plots
# ----------------------------------------------------------------------------------------------------------------
def plots(results, keep):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig 1: hard-short waveforms, vehicle feed, 23.6 V, 5 mOhm, nominal lead; STPS fit vs MBRA mfr
    fig, ax = plt.subplots(4, 1, figsize=(9, 11), sharex=True)
    for cid, ls in keep:
        w = results.get(cid, (None, None, None))[2]
        if w is None:
            continue
        t = w["t"] * 1e6
        lab = cid.split("_L1.0_")[-1]
        ax[0].plot(t, w["out"], ls, label="OUT, " + lab)
        ax[1].plot(t, w["in"], ls, label="U101 IN, " + lab)
        ax[1].plot(t, w["mb"], ls, alpha=0.6, label="MB C-D8 node, " + lab)
        ax[2].plot(t, w["ilead"], ls, label="W1 lead, " + lab)
        ax[2].plot(t, w["ifet"], ls, alpha=0.6, label="U101 FET, " + lab)
        ax[3].plot(t, w["id"], ls, label="D103, " + lab)
    ax[0].axhline(-0.3, color="r", lw=0.8)
    ax[0].axhline(-1.0, color="r", lw=0.6, ls=":")
    ax[0].axhline(-3.0, color="r", lw=0.6, ls="--")
    ax[0].set_ylabel("V (OUT)")
    ax[0].set_ylim(-9, 26)
    ax[1].axhline(35, color="r", lw=0.8)
    ax[1].axhline(60, color="r", lw=0.8, ls=":")
    ax[1].set_ylabel("V")
    ax[2].set_ylabel("A")
    ax[3].set_ylabel("A")
    ax[3].set_xlabel("time (us); short applied at 2 us")
    for a_ in ax:
        a_.grid(alpha=0.3)
        a_.legend(fontsize=7, loc="upper right")
    ax[0].set_xlim(1.5, 30)
    fig.suptitle("Hard short at EVM J1: vehicle MB feed, VCHG-IN 23.6 V, R_short 5 mOhm, W1/W2 163 nH")
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "fig1_hardshort_waveforms.png"), dpi=120)
    plt.close(fig)

    # Fig 2: OUT minimum and time below -0.3 V per D103 candidate over the grid
    grid = {k: v for k, v in results.items() if k.startswith("grid_") and v[1] is not None}
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    for i, d in enumerate(D103_LIST):
        vals = [(v[1]["out_min_V"], v[1]["t_out_below_m0p3_us"]) for k, v in grid.items() if v[0]["d103"] == d]
        if not vals:
            continue
        a1 = np.array(vals)
        x = i + 0.25 * (np.random.default_rng(i).random(len(a1)) - 0.5)
        ax[0].scatter(x, a1[:, 0], s=10)
        ax[1].scatter(x, a1[:, 1], s=10)
    for a_ in ax:
        a_.set_xticks(range(len(D103_LIST)))
        a_.set_xticklabels(D103_LIST, rotation=25, fontsize=8)
        a_.grid(alpha=0.3)
    ax[0].axhline(-0.3, color="r", lw=0.8)
    ax[0].set_ylabel("U101 OUT minimum (V)")
    ax[1].set_ylabel("time with OUT < -0.3 V (us)")
    fig.suptitle("Hard-short grid: 2 feeds x V0 {16, 22, 23.6} V x R_short {5, 50} mOhm x lead L {0.7, 1.0, 1.3}")
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "fig2_out_min_by_d103.png"), dpi=120)
    plt.close(fig)

    # Fig 3: voltage ladder (IN, MB end, pin 38) vs V0
    lad = {k: v for k, v in results.items() if k.startswith("ladder_") and v[1] is not None}
    fig, ax = plt.subplots(1, 3, figsize=(14, 4.5))
    series = {}
    for k, (p, o, _w, _e) in lad.items():
        lm = p["Lfeed"] if p["feed"] == "bench" else p["Lmb"]
        key = (p["feed"], round(lm * 1e9), p["d103"])
        series.setdefault(key, []).append((p["V0"], o["in_peak_V"], o["mb_peak_V"], o["pin38_peak_V"]))
    for key, pts in sorted(series.items()):
        pts = np.array(sorted(pts))
        lab = "%s %d nH %s" % key
        for j in range(3):
            ax[j].plot(pts[:, 0], pts[:, j + 1], "o-", ms=3, label=lab)
    ax[0].axhline(60, color="r", lw=0.8)
    ax[0].axhline(80, color="r", lw=0.8, ls=":")
    ax[0].set_ylabel("U101 IN peak (V)")
    ax[1].axhline(35, color="r", lw=0.8)
    ax[1].axhline(40, color="r", lw=0.8, ls=":")
    ax[1].set_ylabel("MB end (C-D8 node / bench C_S) peak (V)")
    ax[2].axhline(3.3, color="r", lw=0.8)
    ax[2].set_ylabel("pin 38 open-circuit peak (V)")
    for a_ in ax:
        a_.set_xlabel("VCHG-IN before the short (V)")
        a_.grid(alpha=0.3)
    ax[0].legend(fontsize=6)
    fig.suptitle("Hard short, R_short 5 mOhm: peak voltages against the starting VCHG-IN (T-C-04 pre-steps; lowest runnable start 10.6 V)")
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "fig5_voltage_ladder.png"), dpi=120)
    plt.close(fig)

    # Fig 4: sensitivity tornado (OUT min, IN peak)
    fig, ax = plt.subplots(1, 2, figsize=(13, 7))
    for j, (qty, lab) in enumerate((("out_min_V", "U101 OUT minimum (V)"), ("in_peak_V", "U101 IN peak (V)"))):
        for d, col in (("STPS2H100A_fit", "C0"), ("MBRA2H100_mfr", "C1")):
            ks = [k for k in results if k.startswith("sens_%s_" % d) and results[k][1] is not None]
            names = [k.split(d + "_")[1] for k in ks]
            vals = [results[k][1][qty] for k in ks]
            y = np.arange(len(ks)) + (0.2 if col == "C1" else -0.2)
            ax[j].barh(y, vals, height=0.4, color=col, label=d)
            ax[j].set_yticks(np.arange(len(ks)))
            ax[j].set_yticklabels(names, fontsize=7)
        ax[j].set_xlabel(lab)
        ax[j].grid(alpha=0.3)
        ax[j].legend(fontsize=7)
    ax[0].axvline(-0.3, color="r", lw=0.8)
    fig.suptitle("One-at-a-time sensitivity: vehicle feed, 23.6 V, R_short 5 mOhm, W1/W2 nominal")
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "fig3_sensitivity.png"), dpi=120)
    plt.close(fig)

    # Fig 5: RS sweep
    rs = sorted([(float(k.split("RS")[1][:3]), int(k.split("_Ld")[1][0]), results[k][1]["out_min_V"],
                  results[k][1]["id103_peak_A"]) for k in results if k.startswith("rs_") and results[k][1]])
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for ld in sorted(set(r_[1] for r_ in rs)):
        pts = np.array([(r_[0], r_[2]) for r_ in rs if r_[1] == ld])
        ax.plot(pts[:, 0], pts[:, 1], "o-", label="D103 loop L %d nH" % ld)
    ax.axhline(-0.3, color="r", lw=0.8)
    ax.set_xlabel("D103 series resistance RS (mOhm); exponential part = MBRA2H100 max fit")
    ax.set_ylabel("U101 OUT minimum (V)")
    ax.grid(alpha=0.3)
    ax.legend()
    ax.set_title("Hard short, vehicle feed, 23.6 V, 5 mOhm: OUT minimum vs D103 RS")
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "fig4_rs_sweep.png"), dpi=120)
    plt.close(fig)

    # Fig 6: soft short and OVP waveforms
    fig, ax = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for cid in keep_soft:
        w = results.get(cid, (None, None, None))[2]
        if w is None:
            continue
        t = w["t"] * 1e6
        ax[0].plot(t, w["out"], label=cid)
        ax[1].plot(t, w["ilead"], label=cid)
    ax[0].axhline(-0.3, color="r", lw=0.8)
    ax[0].set_ylabel("U101 OUT (V)")
    ax[1].set_ylabel("W1 lead current (A)")
    ax[1].set_xlabel("time (us)")
    for a_ in ax:
        a_.grid(alpha=0.3)
        a_.legend(fontsize=7)
    fig.suptitle("T-C-04 steps (1) soft short and (3) OVP trip at 1.7 A")
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "fig6_soft_ovp.png"), dpi=120)
    plt.close(fig)

    # Fig 7 (check correction 6): vehicle feed, VESC wire inductance and C-D6/C-D7
    vm = [(p, o) for k, (p, o, _w, _e) in results.items() if k.startswith("vmot_") and o is not None]
    if vm:
        fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
        for v0, mk_ in ((22.0, "s"), (23.6, "o")):
            for cd, ls in ((0.0, "--"), (14e-6, "-")):
                for corner, lmb in (("nom", 100e-9), ("mbw", 150e-9)):
                    pts = sorted((p["Lwire"] * 1e9, o["irt_peak_A"], o["mb_peak_V"], o["pin38_peak_V"])
                                 for p, o in vm if p["V0"] == v0 and p["Cd67"] == cd and p["Lmb"] == lmb)
                    if not pts:
                        continue
                    a1 = np.array(pts)
                    lab = "%.1f V, C-D6/7 %d uF, %s" % (v0, round(cd * 1e6), "L_MB 150 nH, 2.5 uF" if corner == "mbw"
                                                         else "nominal MB")
                    for j in range(3):
                        ax[j].plot(a1[:, 0], a1[:, j + 1], ls, marker=mk_, ms=4, label=lab)
        ax[0].axhline(20, color="r", lw=0.8)
        ax[0].set_ylabel("D-BC-RG (RT1987) peak current (A)")
        ax[1].axhline(35, color="r", lw=0.8)
        ax[1].set_ylabel("MB end (C-D8 node) peak (V)")
        ax[2].axhline(3.3, color="r", lw=0.8)
        ax[2].set_ylabel("pin 38 open-circuit peak (V)")
        for a_ in ax:
            a_.set_xscale("log")
            a_.set_xlabel("VESC bulk to MB V-MOT wire inductance (nH)")
            a_.grid(alpha=0.3)
        ax[0].legend(fontsize=6)
        fig.suptitle("Vehicle feed, hard short (5 mOhm, MBRA2H100T3G): VESC wire L and MB C-D6/C-D7 (20 A line = "
                     "RT1987 10 ms peak rating)")
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS, "fig7_vmot_wire.png"), dpi=120)
        plt.close(fig)


keep_soft = []


def main():
    if "--tft-check" in sys.argv:
        tft_check()
        return
    quick = "--quick" in sys.argv
    print("hardshort: %s" % ngspice_version())
    print("  time_below self-test: %.4f us below 0 on a 10 us, 50 %% square wave (expect 5.0000)"
          % (_selftest_time_below() * 1e6))
    print("  U101 thresholds (R102/R103/R104 845k/64.9k/51.1k): UVLO rise %s V, UVLO fall %s V, OVP rise %s V"
          % (VIN_UVLOR, VIN_UVLOF, VIN_OVPR))
    print("  W1/W2: L' %.4f uH/m -> %.1f nH at 0.30 m; R %.1f mOhm" % (LPRIME * 1e6, L_LEAD_NOM * 1e9,
                                                                    R_LEAD_NOM * 1e3))
    DIODES.update(write_behav_models())
    for k, v in DIODES.items():
        if v[2]:
            print("  D103 fit %-18s IS %.3e N %.3f RS %.4f ohm" % (k, *v[2]))
    validation()
    sets = [("grid", set_grid(quick)), ("sens", set_sens(quick)), ("ladder", set_ladder(quick)),
            ("soft", set_soft(quick)), ("ovp", set_ovp(quick)), ("rs", set_rs(quick)),
            ("rsh", set_rsh(quick)), ("mbend", set_mbend(quick)), ("uvlo", set_uvlo(quick)),
            ("vmot", set_vmot(quick))]
    keep = [("grid_veh_V23.6_R05m_L1.0_STPS2H100A_fit", "-"), ("grid_veh_V23.6_R05m_L1.0_MBRA2H100_mfr", "--")]
    global keep_soft
    keep_soft[:] = ["soft_veh_V23.6_I5.5_ILIM2.37_tft8us", "soft_bench_V16.0_I4.1_ILIM1.97_tft4us",
                    "ovp_veh_tf020ns_STPS2H100A_fit", "ovp_bench_tf300ns_STPS2H100A_fit"]
    keep_ids = set(k for k, _ in keep) | set(keep_soft)
    allres = {}
    for name, cases in sets:
        res = run_many(cases, keep_ids=keep_ids, workers=4, label=name)
        write_csv("%s.csv" % name, res)
        allres.update(res)
    # waveform CSV of the two kept hard-short runs (decimated)
    for cid, _ in keep:
        w = allres.get(cid, (None, None, None))[2]
        if w is None:
            continue
        with open(os.path.join(RES, "wave_%s.csv" % cid), "w", newline="", encoding="ascii") as fh:
            wr = csv.writer(fh)
            cols = ["t", "out", "in", "mb", "j1", "ifet", "ilead", "id", "irt", "frac"]
            wr.writerow(cols)
            n = len(w["t"])
            for i in range(0, n, max(1, n // 4000)):
                wr.writerow(["%.6g" % w[c][i] for c in cols])
    plots(allres, keep)
    tables(allres)
    summarize(allres)


def tables(res):
    """Write results/tables.md: the aggregates that RESULTS.md quotes (regenerated on every run)."""
    def ok(prefix, filt=lambda p: True):
        return [(k, v[0], v[1]) for k, v in res.items() if k.startswith(prefix) and v[1] is not None and filt(v[0])]

    L = ["# hardshort: aggregated results (generated by run.py)", ""]
    L.append("## Table A. Hard-short grid, worst case over R_short {5, 50} mOhm and W1/W2 L {0.7, 1.0, 1.3} x nominal")
    L.append("")
    L.append("| Feed | V0 (V) | U101 on at V0 (OVP) | D103 | OUT min (V) | t(OUT < -0.3 V) (us) | t(< -1 V) (us) | "
             "t(< -3 V) (us) | plateau (V) | D103 peak (A) | D103 i2t (A2s) | "
             "U101 IN peak (V) | U101 VIN min while on (V) | MB end peak (V) | pin 38 peak (V) | D-BC-RG peak (A) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for feed in ("bench", "veh"):
        for v in (16.0, 22.0, 23.6):
            for d in D103_LIST:
                xs = [o for _k, p, o in ok("grid_", lambda p: p["feed"] == feed and p["V0"] == v and p["d103"] == d)]
                if not xs:
                    continue
                pl = [o["plateau_V"] for o in xs if o["plateau_V"] == o["plateau_V"]]
                L.append("| %s | %.1f | %s | %s | %.2f to %.2f | %.2f to %.2f | %.2f to %.2f | %.2f to %.2f | %s | "
                         "%.1f | %.4f | %.2f | %.2f | %.2f | %.2f | %s |" % (
                    feed, v, ovp_reach(v), d, min(o["out_min_V"] for o in xs), max(o["out_min_V"] for o in xs),
                    min(o["t_out_below_m0p3_us"] for o in xs), max(o["t_out_below_m0p3_us"] for o in xs),
                    min(o["t_out_below_m1_us"] for o in xs), max(o["t_out_below_m1_us"] for o in xs),
                    min(o["t_out_below_m3_us"] for o in xs), max(o["t_out_below_m3_us"] for o in xs),
                    ("%.2f to %.2f" % (min(pl), max(pl))) if pl else "-",
                    max(o["id103_peak_A"] for o in xs), max(o["id103_i2t_A2s"] for o in xs),
                    max(o["in_peak_V"] for o in xs), min(o["in_min_on_V"] for o in xs),
                    max(o["mb_peak_V"] for o in xs), max(o["pin38_peak_V"] for o in xs),
                    "-" if feed == "bench" else "%.1f" % max(o["irt_peak_A"] for o in xs)))
    L.append("")
    for title, prefix in (("Table B. One-at-a-time sensitivity (vehicle feed, 23.6 V, 5 mOhm, nominal lead)", "sens_"),
                          ("Table C. Short resistance sweep", "rsh_"), ("Table D. Voltage ladder", "ladder_"),
                          ("Table E. Step (1) soft short", "soft_"), ("Table F. Step (3) OVP trip at 1.7 A", "ovp_"),
                          ("Table G. D103 series-resistance sweep (MBRA2H100 max-fit exponential)", "rs_"),
                          ("Table H. MB end against the RT1987 reverse-current model", "mbend_"),
                          ("Table I. UVLO turn-off path (off / typ / late / early)", "uvlo_"),
                          ("Table J. Vehicle feed: VESC wire inductance and C-D6/C-D7", "vmot_")):
        L.append("## " + title)
        L.append("")
        L.append("| Case | OUT min (V) | est. (V) | t(OUT < -0.3 V) (us) | t(< -1 V) (us) | t(< -3 V) (us) | "
                 "spike width (us) | plateau (V) | trip path | FET fall 90-10 (ns) | D103 peak (A) | "
                 "FET I at off (A) | t_off (us) | VIN min on (V) | IN peak (V) | MB peak (V) | pin 38 peak (V) | "
                 "t(pin 38 > 3.3 V) (us) | MB at end (V) | D-BC-RG peak (A) |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for k, p, o in sorted(ok(prefix), key=lambda x: x[0]):
            L.append("| %s | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f | %s | %.1f | %.1f | %.1f | %.2f | %.2f | "
                     "%.2f | %.2f | %.2f | %.2f | %.2f | %s |" % (
                k, o["out_min_V"], o["out_min_est_V"], o["t_out_below_m0p3_us"], o["t_out_below_m1_us"],
                o["t_out_below_m3_us"], o["t_spike_us"], o["plateau_V"], o["trip_path"], o["t_fall_90_10_ns"],
                o["id103_peak_A"], o["ifet_at_off_A"], o["t_off_us"],
                o["in_min_on_V"], o["in_peak_V"], o["mb_peak_V"], o["pin38_peak_V"], o["t_pin38_above_3p3_us"],
                o["mb_end_V"], "-" if p["feed"] == "bench" else "%.1f" % o["irt_peak_A"]))
        L.append("")
    with open(os.path.join(RES, "tables.md"), "w", encoding="ascii") as fh:
        fh.write("\n".join(L) + "\n")


def summarize(res):
    def worst(prefix, key, fn=min, filt=None):
        it = [(k, v[1][key]) for k, v in res.items() if k.startswith(prefix) and v[1] is not None
              and (filt is None or filt(v[0]))]
        return fn(it, key=lambda x: x[1]) if it else (None, float("nan"))

    lines = []
    lines.append("SUMMARY (worst cases)")
    for vmax, lab in ((22.0, "V0 <= 22 V (all parts)"), (23.6, "V0 <= 23.6 V (upper-tolerance OVP)")):
        lines.append("  -- grid, %s" % lab)
        for d in D103_LIST:
            f = (lambda p, d=d, vmax=vmax: p["d103"] == d and p["V0"] <= vmax)
            k, v = worst("grid_", "out_min_V", min, f)
            k2, v2 = worst("grid_", "t_out_below_m0p3_us", max, f)
            k1, v1 = worst("grid_", "t_out_below_m0p3_us", min, f)
            k3, v3 = worst("grid_", "id103_peak_A", max, f)
            k4, v4 = worst("grid_", "t_out_below_m3_us", max, f)
            k5, v5 = worst("grid_", "plateau_V", min, f)
            lines.append("  %-18s OUT min %7.2f V; t<-0.3V %5.2f-%5.2f us; t<-3V max %5.2f us; plateau min %6.2f V; "
                         "D103 peak %6.1f A (IFSM %.0f A)" % (d, v, v1, v2, v4, v5, v3, D103_INFO[d]["ifsm"]))
    fitted = lambda p: p["d103"] != "none"
    lines.append("  grid, D103 fitted: OUT min %.2f to %.2f V; t<-0.3V %.2f to %.2f us"
                 % (worst("grid_", "out_min_V", min, fitted)[1], worst("grid_", "out_min_V", max, fitted)[1],
                    worst("grid_", "t_out_below_m0p3_us", min, fitted)[1],
                    worst("grid_", "t_out_below_m0p3_us", max, fitted)[1]))
    veh_fit = lambda p: p["d103"] != "none" and p["feed"] == "veh"
    lines.append("  grid, vehicle, D103 fitted: D-BC-RG peak %.1f to %.1f A"
                 % (worst("grid_", "irt_peak_A", min, veh_fit)[1], worst("grid_", "irt_peak_A", max, veh_fit)[1]))
    est = [(v[1]["out_min_V"], v[1]["out_min_est_V"]) for k, v in res.items()
           if k.startswith("grid_") and v[1] is not None and v[0]["d103"] != "none"
           and v[1]["out_min_est_V"] == v[1]["out_min_est_V"]]
    if est:
        r_ = np.array([b / a for a, b in est])
        lines.append("  analytic cross-check VF(I0)+I0 sqrt(L/C) / simulated OUT min: %.2f to %.2f (median %.2f)"
                     % (r_.min(), r_.max(), np.median(r_)))
        kk = np.array([v[1]["k_ring"] for k, v in res.items() if k.startswith("grid_") and v[1] is not None
                       and v[0]["d103"] != "none" and v[1]["k_ring"] == v[1]["k_ring"]])
        lines.append("  effective ring factor k (OUT min = -(VF(I0) + k I0 Zc)): %.2f to %.2f (median %.2f)"
                     % (kk.min(), kk.max(), np.median(kk)))
    for key, lab in (("in_peak_V", "U101 IN peak"), ("mb_peak_V", "MB end peak"), ("pin38_peak_V", "pin 38 peak"),
                     ("irt_peak_A", "D-BC-RG peak current"), ("ilead_peak_A", "W1/W2 lead peak")):
        k, v = worst("grid_", key, max, (lambda p: p["feed"] == "veh") if key == "irt_peak_A" else None)
        lines.append("  grid max %-22s %8.2f  (%s)" % (lab, v, k))
    for pre in ("soft_", "ovp_"):
        k, v = worst(pre, "out_min_V", min)
        lines.append("  %s OUT min %.3f V (%s)" % (pre, v, k))
    for key, lab, fn in (("t_pin38_above_3p3_us", "pin 38 > 3.3 V time", max), ("mb_peak_V", "MB peak", max),
                         ("pin38_peak_V", "pin 38 peak", max)):
        for pre in ("mbend_", "vmot_"):
            k, v = worst(pre, key, fn)
            lines.append("  %s %s %.2f (%s)" % (pre, lab, v, k))
    k, v = worst("vmot_", "irt_peak_A", min)
    k2, v2 = worst("vmot_", "irt_peak_A", max)
    lines.append("  vmot_ D-BC-RG peak %.1f to %.1f A" % (v, v2))
    k, v = worst("vmot_", "out_min_V", min)
    k2, v2 = worst("vmot_", "out_min_V", max)
    lines.append("  vmot_ OUT min %.2f to %.2f V" % (v, v2))
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(RES, "summary.txt"), "w", encoding="ascii") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    main()
