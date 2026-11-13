#!/usr/bin/env python3
"""r9 re-run of the section H quantitative checks of docs/charger_bq25798_wiring_design_2026-11-05.md (change row r9-9).

Step 2 of the D-50 round order (process decision 2, r9-8). The r9 decisions (r9-1 .. r9-8, DESIGN_STATE_2026-11-12 section 3.5)
remove parts on which r1-r8 calculations rest. This script re-derives every section H row whose subject or inputs changed, with
the removed parts stripped, from the r9 CR netlist `hardware/charger_evm_r8/cr/cr.net` (78 parts) and the EIB netlist
`hardware/charger_evm_r8/eib/eib.net` (r9-2 DNP set applied: U203, U204, C203, C204, R258-R265). It adds the H.24 rows:
  H.24(a) ribbon 9-10 and 8-9 short currents against the LVC output-current limits, with the R175 rail sag (J.2 item 70(a));
  H.24(b) the RT1987 EN-net level on pins 27-32 with the pad left INPUT_PULLUP, high-Z or with a keeper, r9 pull-downs only;
  H.24(c) every numeric figure quoted in the proposed IO CSV rows of design-document section D.3;
  H.24(d) (r9-12, check-in 2 ruling R2) the R132 / R131B series value for J.2 item 70(a) option (a).
It also adds R9.H21(r) (r9-12, audit run 002 ADV-R2-04 and ADV-R2-05): the FR-41(iii) ramp-step schedule and cadence
at 100 and 400 kHz, the FR-41(vii) hold-deadline resolution on the FR-45 tick grid and the T4 edge-to-step-3 restore deadline.
It also adds R9.H25 (r9-15, LAYOUT_DECISIONS D-56): the VCHGIN L3 strap as the only J1.10 feed, its IPC-2152 inner-layer
width at 2.41 A and a 10 degC rise, the J1.10 joint on In2 and the L3-to-L1 via count at the C102c end.

The script does not import or modify round3/calc/r3_calc.py or round4/calc/r7_calc.py: importing r3_calc.py would rewrite
round3/calc/r3_calc_out.json, and r7_calc.py parses the .brd. The models used here are copied from those scripts, with the
section and line of origin named at each copy. Stdlib only. Run from any directory:
    /c/Users/ricky/miniforge3/python.exe r9_calc.py
Output: r9_calc_out.txt and r9_calc_out.json beside this file.

Sources (literature numbers as in r3_calc.py / r7_calc.py; datasheets in references/ where present):
  DS  TI SLUSDV2C BQ25798 (references/TI_BQ25798_design_files/BQ25798_SLUSDV2C.pdf): ILEAK_ILIM +-1.5 uA (p.12), VIL_ILIM_HIZ
      0.75 V, IIN_BIAS_CE 1 uA (p.16), 7-bit address 0x6B (sec 7.3.14, p.53-54), STAT 1 Hz fault blink (Table 7-11, p.48)
  EF  TI SLVSE94G TPS2663x (references/Datasheets/tps2663.pdf): GAIN(IMON) 25.66 / 27.9 / 30.14 uA/A for 0.6-2 A (sec 6.5, p.7),
      R(FLT) 36 / 70 / 130 ohm, FLT sink 10 mA abs max (sec 6.1)
  RT  Richtek RT1987 DS-00 (references/Datasheets/RT1987_DS-00.pdf, EC table p.7): VEN_R max 1.4 V, VEN_F min 0.6 V,
      REN_PD 475 / 730 / 985 kOhm
  TLV TI SBOS300C TLV3011/3012 (not in references/): REF 1.223-1.260 V, 100 ppm/C, Vos 9 mV, VHYS 2-8 mV, IQ 5 uA max,
      supply 1.8-5.5 V; TODO(verify: SBOS300C) as in r3_calc.py
  LVC TI SCES201N SN74LVC2G32 / SCES198N SN74LVC2G08 (not in references/): VOH >= 2.4 V at IOH -16 mA, VCC 3 V (Rout <= 37.5 ohm,
      r3_calc.py H.21(h)); recommended IOH -24 mA at VCC 3 V, -8 mA at 2.3 V, -4 mA at 1.65 V; continuous output current
      +-50 mA abs max; VCC 1.65-5.5 V; VIH 2.0 V at VCC 2.7-3.6 V; ICC 10 uA max. TODO(verify: SCES201N sec 6.1, 6.3, 6.5)
  IMX i.MX RT1062 pad (not in references/): INPUT_PULLUP 22 kOhm nominal, 11-33 kOhm ASSUMPTION (r7_calc.py R_PU35);
      INPUT_PULLDOWN 100 kOhm nominal ASSUMPTION; VIL 0.30 x / VIH 0.70 x OVDD ASSUMPTION; keeper strength unknown.
      TODO(verify: IMXRT1060CEC, IMXRT1060RM)
  TEENSY 3V3 3.135 / 3.30 / 3.465 V ASSUMPTION (r7_calc.py V_IO_RNG); TODO(verify: PJRC Teensy 4.1 schematic)
  MB  references/Scale_Car_Board_20260624.sch: the six RT1987 EN nets (D-FC-EN 27, D-BT-EN 28, D-MT-EN 29, D-BC-RG 30,
      D-BC-FC 31, D-BT-SQ 32) join only the Teensy pad and the RT1987 EN pin; the 10 kOhm EN-to-GND resistor on each is a
      post-manufacturing bodge (CLAUDE.md section 2), tolerance ASSUMPTION +-5 %, TODO(verify: bodge resistor part)
  DOC docs/charger_bq25798_wiring_design_2026-11-05.md (r9): section H r8 values, A.4 tap maxima, D.3 proposed CSV rows
"""
import itertools
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
CR_NET = os.path.join(REPO, "hardware", "charger_evm_r8", "cr", "cr.net")
EIB_NET = os.path.join(REPO, "hardware", "charger_evm_r8", "eib", "eib.net")
OUT_TXT = os.path.join(HERE, "r9_calc_out.txt")
OUT_JSON = os.path.join(HERE, "r9_calc_out.json")

LINES = []
RJ = {}


def out(s=""):
    LINES.append(s)
    print(s)


def head(s):
    out("")
    out("=" * 110)
    out(s)
    out("=" * 110)


def r4(v):
    return round(v, 4) if isinstance(v, float) else v


def par(*rs):
    return 1.0 / sum(1.0 / r for r in rs)


# ======================================================================================================================
# Netlist reader (KiCad S-expression export)
# ======================================================================================================================
SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "": 1.0}


def parse_value(s):
    m = re.match(r"\s*([0-9]*\.?[0-9]+)\s*([pnumkKM]?)", s)
    return float(m.group(1)) * SI[m.group(2)] if m else None


def read_net(path):
    t = open(path, encoding="utf-8").read()
    comps = dict(re.findall(r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)', t))
    nets = {}
    i = t.index("(nets")
    for m in re.finditer(r'\(net \(code "?\d+"?\) \(name "([^"]*)"\)(.*?)(?=\(net \(code|\Z)', t[i:], re.S):
        nets[m.group(1)] = re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2))
    return comps, nets


CR_COMPS, CR_NETS = read_net(CR_NET)
EIB_COMPS, EIB_NETS = read_net(EIB_NET)
EIB_DNP = {"U203", "U204", "C203", "C204"} | {"R%d" % n for n in range(258, 266)}   # r9-2 (dec2-eib)


def val(ref):
    return parse_value(CR_COMPS[ref])


def on_net(net, ref, pin=None, nets=CR_NETS):
    return any(r == ref and (pin is None or p == pin) for r, p in nets[net])


# ======================================================================================================================
# Constants (sources in the docstring; r3_calc.py / r7_calc.py lines named where copied)
# ======================================================================================================================
VREF = (1.223, 1.242, 1.260)       # TLV3012 REF at 25 C (r3_calc.py l.46)
REF_TC = 100e-6                    # 1/C (r3_calc.py l.47)
DT_CR = (0.0, 45.0)                # C excursion from 25 C (r3_calc.py l.48)
VOS = 0.009                        # V (r3_calc.py l.49)
VHYS = (0.002, 0.008)              # V (r3_calc.py l.50)
CMRR_DB = 54.0                     # (r3_calc.py l.51)
VOH, VOL = (3.1, 3.3), (0.0, 0.2)  # (r3_calc.py l.52)
IQ_TLV = 5e-6                      # A max per TLV3012 (r3_calc.py H.15)
ICC_LVC = 10e-6                    # A max per LVC package (r3_calc.py H.15)
V_IO = (3.135, 3.30, 3.465)        # Teensy 3V3 (r7_calc.py V_IO_RNG)
R_PU = (11e3, 22e3, 33e3)          # i.MX INPUT_PULLUP (r7_calc.py R_PU35)
R_PD_IMX = 100e3                   # i.MX INPUT_PULLDOWN nominal ASSUMPTION
VIL_FRAC, VIH_FRAC = 0.30, 0.70    # (r7_calc.py VIL_FRAC, VIH_FRAC)
R_DRV = 40.0                       # ohm, i.MX output driver ASSUMPTION (r7_calc.py l.2238)
VEN_R_MAX, VEN_F_MIN = 1.4, 0.6    # RT1987 EC p.7
REN_PD = (475e3, 730e3, 985e3)     # RT1987 EC p.7
R_BODGE = (9.5e3, 10.0e3, 10.5e3)  # MB EN-to-GND bodge, 10 kOhm, +-5 % ASSUMPTION
ROUT_LVC = (0.0, 37.5)             # ohm, LVC output resistance bound at VCC 3 V (r3_calc.py H.21(h))
RDS_STAT = (0.0, 80.0)             # ohm, BQ25798 STAT sink (VOL <= 0.4 V at 5 mA, r3_calc.py H.21(h))
REGN = (4.8, 5.2)                  # V (r3_calc.py H.4)
I_LEAK_PIN = 1.5e-6                # A, DS ILEAK_ILIM
I_LEAK_FET = 1.0e-6                # A, r3_calc.py H.4 allowance
IMON_GAIN = (25.66e-6, 27.9e-6, 30.14e-6)   # A/A, EF sec 6.5 (0.6-2 A only)
LVC_IOH_REC = {3.0: 24e-3, 2.3: 8e-3, 1.65: 4e-3}   # A, SCES201N sec 6.3, TODO(verify)
LVC_IO_ABS = 50e-3                 # A, SCES201N sec 6.1, TODO(verify)
TLV_VS_MIN, LVC_VCC_MIN = 1.8, 1.65

# CR part values read from cr.net (the netlist is the source; a mismatch with the design document is printed)
R102, R103, R104, R105 = val("R102"), val("R103"), val("R104"), val("R105")
R106S, R107, R108 = val("R106s"), val("R107"), val("R108")
R109, R110, R111, R112, R113 = val("R109"), val("R110"), val("R111"), val("R112"), val("R113")
R114, R115, R116 = val("R114"), val("R115"), val("R116")
R122, R123, R126, R129, R130 = val("R122"), val("R123"), val("R126"), val("R129"), val("R130")
R131A, R131B, R132, R147 = val("R131A"), val("R131B"), val("R132"), val("R147")
R175, R176, R177 = val("R175"), val("R176"), val("R177")
R184, R185, R186, R187, R188, R189 = (val("R184"), val("R185"), val("R186"), val("R187"), val("R188"), val("R189"))
C129 = val("C129")
RT1 = RT2 = 10.0e3                 # MB R170 / R171 10.0 kOhm 0.1 % at the T1 / T2 joints (A.4); not on the CR netlist
# EIB values (eib.net)
R250 = parse_value(EIB_COMPS["R250"]); R267 = parse_value(EIB_COMPS["R267"]); R274 = parse_value(EIB_COMPS["R274"])
R275 = parse_value(EIB_COMPS["R275"]); R255 = parse_value(EIB_COMPS["R255"]); R257 = parse_value(EIB_COMPS["R257"])
R23_EVM, R256_EVM = 49.9e3, 200e3  # EVM R23 49.9 kOhm (EM list, r1-15), R256 200 kOhm at TP33 (C, B.6); not on any netlist
R272 = 47.0e3                      # EVM R272 / R272b 47.0 kOhm (B.6, C); not on any netlist


def solve3(A, b):
    M = [row[:] + [bb] for row, bb in zip(A, b)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(i + 1, 3):
            f = M[r][i] / M[i][i]
            for c in range(i, 4):
                M[r][c] -= f * M[i][c]
    x = [0.0] * 3
    for i in reversed(range(3)):
        x[i] = (M[i][3] - sum(M[i][c] * x[c] for c in range(i + 1, 3))) / M[i][i]
    return x


# ======================================================================================================================
def sec_netlist():
    head("R9.0 Netlist basis (cr.net 78 parts, eib.net with the r9-2 DNP set)")
    out("cr.net: %d components; eib.net: %d components (%d DNP by r9-2: %s)"
        % (len(CR_COMPS), len(EIB_COMPS), len(EIB_DNP & set(EIB_COMPS)), ", ".join(sorted(EIB_DNP & set(EIB_COMPS)))))
    removed = (["U104", "U108", "U109", "U111", "U112", "U113", "U114", "U115", "U116", "U117", "U121", "U122", "U123",
                "R106", "R117", "R118", "R119", "R120", "R121", "R124", "R125", "R127", "R128", "R133", "R134", "R135", "R136",
                "R137", "R140", "R141", "R142", "R143", "R144", "R145", "R146", "R148", "R150", "R151", "R160", "R161", "R162",
                "R163", "R172", "R178", "R179", "R190", "R191", "C105", "C109", "C112", "C113", "C117", "C118", "C120", "C121",
                "C122", "C123", "C124", "C127", "C133", "C134", "C135", "C140", "C150", "C151", "C152", "D101", "D108", "F101"])
    present = [r for r in removed if r in CR_COMPS]
    out("r9-removed CR designators checked absent from cr.net: %d checked, present: %s" % (len(removed), present or "none"))
    checks = [("R105 IMON", "R105", 27.4e3), ("R106s FLT series", "R106s", 1.00e3), ("R107 STAT pull-up", "R107", 10.0e3),
              ("R108 CHG_ARM pull-down", "R108", 47.0e3), ("R109", "R109", 487e3), ("R110", "R110", 56.2e3),
              ("R111", "R111", 442e3), ("R112", "R112", 56.2e3), ("R113 H1 hysteresis", "R113", 6.49e6),
              ("R114", "R114", 1.00e6), ("R115", "R115", 104e3), ("R116", "R116", 10.0e6), ("R122 T5 series", "R122", 1.00e3),
              ("R123 QUAL pull-down", "R123", 47.0e3), ("R126 H1_RB series", "R126", 1.00e3), ("R129 CHG_IIN series", "R129", 10.0e3),
              ("R130 CE_DRV series", "R130", 100.0), ("R131A", "R131A", 100.0), ("R131B", "R131B", 4.99e3), ("R132", "R132", 4.99e3),
              ("R147 QUAL series", "R147", 1.00e3), ("R175 3V3 limiter", "R175", 68.0), ("R176", "R176", 200.0),
              ("R177", "R177", 200.0), ("R184 REF/3 top", "R184", 20.0e3), ("R185 REF/3 bottom", "R185", 10.0e3),
              ("R186", "R186", 10.0e3), ("R187 FCC pull-up", "R187", 3.30e6), ("R188 FCC_ON top", "R188", 453e3),
              ("R189 FCC_ON bottom", "R189", 1.00e6), ("C129", "C129", 1.0e-9)]
    bad = [(n, CR_COMPS[r]) for n, r, v in checks if abs(val(r) - v) > 1e-6 * v]
    out("values used below, parsed from cr.net: %s" % ", ".join("%s %s" % (r, CR_COMPS[r]) for _, r, _ in checks))
    out("mismatches against the section H basis: %s" % (bad or "none"))
    topo = {
        "STAT: J1.3 (MB pin 6), J101.4, R107 to /3V3": on_net("/STAT", "J1", "3") and on_net("/STAT", "J101", "4")
        and on_net("/STAT", "R107") and on_net("/3V3", "R107", "2"),
        "CHG_ARM: J1.11 (pin 5), R108 to GND": on_net("/CHG_ARM", "J1", "11") and on_net("/GND", "R108", "2"),
        "QUAL: T10 -> R147 -> /QUAL, R123 to GND": on_net("/QUAL_TAP", "R147") and on_net("/QUAL", "R123") and on_net("/GND", "R123", "2"),
        "CHG_IIN: T17 -> R129 -> N_IMON (R105 to GND, U101 IMON), C129 at the tap side": on_net("/CHG_IIN", "R129")
        and on_net("/N_IMON", "R105") and on_net("/N_IMON", "U101", "13") and on_net("/CHG_IIN", "C129"),
        "FCC: T5 -> R122 -> /FCC -> R186 -> U119 IN- (R187 to 3V3) and R188 -> U120 IN+ (R189 to GND)":
            on_net("/FCC_TAP", "R122") and on_net("/FCC", "R186") and on_net("/N_FOM", "R187") and on_net("/3V3", "R187", "2")
            and on_net("/N_FNP", "R189") and on_net("/N_FOM", "U119", "4") and on_net("/N_FNP", "U120", "3"),
        "U119 IN+ = REF119 / 3 (R184 / R185, C130)": on_net("/N_FOP", "U119", "3") and on_net("/REF119", "R184"),
        "U120 IN- = own REF": on_net("/REF120", "U120", "4") and on_net("/REF120", "U120", "5"),
        "RFC_OFF: U106 2Y -> R132 -> J101.10; J101.9 GND": on_net("/RFC_OFF", "U106", "3") and on_net("/RFC_OFF_J", "J101", "10")
            and on_net("/GND", "J101", "9"),
        "ILIM_REL: U110 2Y -> R131A (J101.7) and R131B (J101.8)": on_net("/ILIM_REL", "U110", "3") and on_net("/ILIM_REL_B", "J101", "8"),
        "CE_DRV: U106 1Y -> R130 -> J101.5": on_net("/CE_DRV", "U106", "7") and on_net("/CE_DRV_J", "J101", "5"),
        "H1: U102 OUT -> R126 -> T13 (pin 34), R113 hysteresis, U118 1A": on_net("/H1", "R126") and on_net("/H1_RB", "J102", "5"),
        "UVB: U103 OUT -> R116, U118 1B": on_net("/UVB", "R116") and on_net("/UVB", "U118", "2"),
        "3V3: T6 -> R175 -> /3V3; R176/R177 -> J101.1/.2": on_net("/T6_3V3", "R175") and on_net("/J3V3_1", "J101", "1")
            and on_net("/J3V3_2", "J101", "2"),
        "FLT: U101 FLT -> R106s -> T16 (pin 35)": on_net("/N_FLT", "U101", "14") and on_net("/CHG_EFUSE_FLT", "J102", "9"),
        "EIB ribbon inputs: R250/R251/R253/R266 1.00k + R267-R270 47.0k to AGND": all(
            on_net(n, r, nets=EIB_NETS) for n, r in (("/N_CEIN", "R267"), ("/N_RAIN", "R268"), ("/N_RFIN", "R269"), ("/N_RBIN", "R270"))),
        "EIB STAT: J201.4 -> R275 -> E7": on_net("/STAT", "R275", nets=EIB_NETS) and on_net("/STAT_E", "E7", nets=EIB_NETS),
        "EIB 3V3 bleed R274 to AGND": on_net("/3V3", "R274", nets=EIB_NETS),
    }
    for k, v in topo.items():
        out("  topology %-92s %s" % (k, "OK" if v else "MISMATCH"))
    cr_3v3 = sorted({r for r, _ in CR_NETS["/3V3"]})
    out("  CR /3V3 net members: %s" % ", ".join(cr_3v3))
    RJ["netlist"] = dict(cr_parts=len(CR_COMPS), removed_present=present, value_mismatch=bad,
                         topology={k: bool(v) for k, v in topo.items()})


# ======================================================================================================================
# H.15 3V3 load and H.20 rail levels (needed first: other rows use the CR rail)
# ======================================================================================================================
def rail_load():
    """Worst-static CR + EIB 3V3 load (A) enumerated from the r9 netlists; returns (items_cr, items_eib)."""
    vr = 3.3
    cr = {
        "4 x TLV3012B (U102, U103, U119, U120), IQ 5 uA max": 4 * IQ_TLV,
        "5 x LVC (U105, U106, U107, U110, U118), ICC 10 uA max": 5 * ICC_LVC,
        "U119 REF/3 divider R184 + R185 (30.0 kOhm) at REF 1.260 V max": VREF[2] * (1 + REF_TC * 45) / (R184 + R185),
        "R107 STAT pull-up while STAT LOW (through EIB R275)": vr / (R107 + R275),
        "4 ribbon driver input paths while HIGH (CR 100 ohm + EIB 1.00k + 47.0k)": 4 * vr / (100.0 + R250 + R267),
        "H1 HIGH into pin 34 INPUT_PULLDOWN through R126 (100 kOhm ASSUMPTION)": vr / (R126 + R_PD_IMX),
        "R113 / R116 hysteresis feedback, R187 FCC pull-up (each < 1 uA)": vr / R113 + vr / R116 + vr / R187,
    }
    eib = {
        "R274 EIB 3V3 bleed 10.0 kOhm": vr / R274,
        "U201 SN74LVC3G06 + U202 SN74LVC1G06, ICC 10 uA max each": 2 * ICC_LVC,
    }
    return cr, eib


def sec_h15_h20():
    head("R9.H15 / R9.H20 CR + EIB 3V3 load and feed-limiter levels (r9 netlists; removed: U104, U108, U109, U111, U113-U116, "
         "U121-U123 and the EIB U203/U204 networks)")
    cr, eib = rail_load()
    for k, v in cr.items():
        out("  CR  %-86s %.3f mA" % (k, v * 1e3))
    for k, v in eib.items():
        out("  EIB %-86s %.3f mA" % (k, v * 1e3))
    i_cr_only, i_eib = sum(cr.values()), sum(eib.values())
    i_tot = i_cr_only + i_eib
    out("  total worst static: CR %.3f mA + EIB %.3f mA = %.3f mA through R175 (r6 figure ~1.86 mA, r5 1.79 mA)"
        % (i_cr_only * 1e3, i_eib * 1e3, i_tot * 1e3))
    v_cr = 3.30 - i_tot * R175
    v_eib2 = v_cr - i_eib * par(R176, R177)
    v_eib1 = v_cr - i_eib * R176
    out("  CR rail %.3f V (Teensy 3V3 3.30 V - %.3f mA x %.0f ohm; r4 3.176 V); EIB rail %.3f V with both ribbon 3V3 conductors, "
        "%.3f V with one open (r4 3.131 / 3.086 V)" % (v_cr, i_tot * 1e3, R175, v_eib2, v_eib1))
    v_cr_lo = V_IO[0] - i_tot * R175
    out("  at Teensy 3V3 %.3f V (-5 %%, ASSUMPTION): CR rail %.3f V; LVC 3.0-3.6 V row: %s"
        % (V_IO[0], v_cr_lo, "inside" if v_cr_lo >= 3.0 else "BELOW 3.0 V (LVC VOH/VIH rows at 3.0 V no longer apply)"))
    i_sh = 3.30 / R175
    out("  CR rail dead short: %.1f mA, %.0f mW in R175 (1206 0.25 W); ribbon 3V3 conductor to GND: %.1f mA, %.0f mW in one "
        "200 ohm 0603 before the R175 sag; with the sag (base load %.2f mA): %.1f mA, CR rail %.3f V; EIB rail short (both "
        "conductors): %.1f mA before the sag" % (i_sh * 1e3, 3.3 ** 2 / R175 * 1e3, v_cr / R176 * 1e3, v_cr ** 2 / R176 * 1e3,
                                                  i_cr_only * 1e3, *rail_short_sag(3.30, i_cr_only, R176), 2 * v_cr / R176 * 1e3))
    out("  C125 10 uF behind R175: inrush peak %.1f mA, tau %.2f ms (unchanged)" % (3.3 / R175 * 1e3, R175 * 10e-6 * 1e3))
    out("  retired: the U203/U204 ribbon drivers R264/R265 470 ohm (DNP, r9-2); the r6 additions U121-U123 and R179 (removed)")
    RJ["h15_h20"] = dict(i_cr_mA=r4(i_cr_only * 1e3), i_eib_mA=r4(i_eib * 1e3), i_total_mA=r4(i_tot * 1e3),
                         v_cr=r4(v_cr), v_eib_both=r4(v_eib2), v_eib_one=r4(v_eib1), v_cr_at_3v135=r4(v_cr_lo),
                         cr_short_mA=r4(i_sh * 1e3), ribbon_3v3_short_mA=r4(v_cr / R176 * 1e3),
                         ribbon_3v3_short_sag=[r4(x) for x in rail_short_sag(3.30, i_cr_only, R176)])
    return v_cr, i_cr_only, i_eib


def rail_short_sag(v_io, i_base, r_short):
    """CR rail behind R175 with a constant base load and a resistive short r_short: returns (I_short mA, V_rail)."""
    v = (v_io - R175 * i_base) / (1 + R175 / r_short)
    return v / r_short * 1e3, v


# ======================================================================================================================
def ilim_cases():
    """r3_calc.py H.4 (l.218-262) with the sense pull-up R258/R259 removed (U203 network DNP, r9-2)."""
    res = {}
    for name, legs in (("regen", (R23_EVM, R256_EVM)), ("fc", (R23_EVM, R256_EVM, R257))):
        vals, vpins = [], []
        for a, b in itertools.product((-1, 1), repeat=2):
            for regn in REGN:
                rb = par(*[l * (1 + b * 0.01) for l in legs])
                r_rel = R255 * (1 + a * 0.01)
                for leak in (-1, 1):
                    i_fet = -I_LEAK_FET * (2 if name == "regen" else 1)
                    i = leak * I_LEAK_PIN + (i_fet if leak < 0 else 0.0)
                    v = regn * rb / (r_rel + rb) + i * par(r_rel, rb)
                    vpins.append(v)
                    vals.append((v - 1.0) / 0.8)
        nom_rb = par(*legs)
        nom = (5.0 * nom_rb / (R255 + nom_rb) - 1.0) / 0.8
        res[name] = dict(clamp=(min(vals), max(vals)), nom=nom, pin=(min(vpins), max(vpins)))
    return res


def sec_h4_h5_h12_h13():
    head("R9.H4 ILIM_HIZ clamps without the U203 sense pull-up R258/R259 (r9-2 DNP); H.5, H.12, H.13 rows that use them")
    res = ilim_cases()
    for k, lab in (("regen", "regen (Q202 off)"), ("fc", "FC (Q202 on, R257 || EVM R23)")):
        r = res[k]
        out("  ILIM %-30s pin %.3f-%.3f V -> clamp %.3f-%.3f A (nominal %.3f A at REGN 5.0 V; pin leakage +-1.5 uA, FET 1 uA; "
            "no sense pull-up)" % (lab, r["pin"][0], r["pin"][1], r["clamp"][0], r["clamp"][1], r["nom"]))
    hiz = (I_LEAK_PIN + I_LEAK_FET) * par(R23_EVM, R256_EVM)
    hiz_open = (I_LEAK_PIN + I_LEAK_FET) * R256_EVM
    out("  held (Q203 off, Q201 failed open): ILIM <= %.3f V (pin 1.5 uA + PMOS 1 uA into R23 || R256; r8 <= 0.11 V with the "
        "0.3 uA sense term); with EVM R23 open (R256 alone): <= %.3f V (r8 0.57 V); VIL_ILIM_HIZ 0.75 V (DS p.16)" % (hiz, hiz_open))
    out("  r8 basis (sense pull-up in): regen 1.331-1.755 A, FC 0.648-0.947 A; the r9 bounds lie inside them")
    fmax, rmax = res["fc"]["clamp"][1], res["regen"]["clamp"][1]
    # H.5 eFuse limit vs regen clamp (r3_calc.py H.5: eFuse current-limit band 2.05-2.41 A)
    out("R9.H5 eFuse current limit min 2.05 A vs regen clamp max %.3f A: margin %.3f A (r8 0.30 A on 1.755 A)" % (rmax, 2.05 - rmax))
    # H.12 (r3_calc.py l.522-540)
    I_AUX = (0.09, 0.15)
    out("R9.H12 FC-window bus-side load (standstill): FC image IINDPM 0.90 A + aux %.2f-%.2f A = %.2f-%.2f A; hardware FC clamp max "
        "%.3f A + aux = %.2f-%.2f A (a charger POR in the window; r8 <= 1.10 A); regen clamp max %.3f A + aux = %.2f-%.2f A "
        "(r8 1.84-1.90 A); arm drop 1.20 A, P_MAX(bus) 1.247 A, OC_FC 1.4 A"
        % (I_AUX[0], I_AUX[1], 0.90 + I_AUX[0], 0.90 + I_AUX[1], fmax, fmax + I_AUX[0], fmax + I_AUX[1], rmax, rmax + I_AUX[0],
           rmax + I_AUX[1]))
    out("        r9 gate (B.1): RFC_OFF = FCC_OFF + H1.UVB, so in a window (FCC_OFF LOW) the EIB Q202 FC leg holds the FC clamp unless "
        "H1.UVB is HIGH; the regen-clamp row is reachable in a window only with H1.UVB HIGH (V-MOT > 1.089 x VBUS). FCCEIL and FR-09 "
        "are removed; OC_FC 1.4 A is the backstop for the regen-clamp row (%.2f A > 1.4 A)" % (rmax + I_AUX[1]))
    # H.7 capability with the new clamp minimum (r3_calc.py l.383-406: P = min(min(clamp_min, 1.70) x 0.88 x VINDPM_min,
    # ICHG x (1 - 6.5 %) x V_BATpin / 0.93), pack 7.40 V, V_BATpin = 7.40 + ICHG x (12.6 + 20) mOhm)
    cmin = res["regen"]["clamp"][0]
    cap = {}
    for lab, ichg, vmin, cl in (("regen image ICHG 2.50 A", 2.50, 19.0 * 0.98, cmin), ("regen image ICHG 3.10 A", 3.10, 19.0 * 0.98, cmin),
                                ("raised stage 1 (18.2 V), ICHG 3.10 A", 3.10, 18.2 * 0.98, cmin), ("FC image ICHG 1.60 A", 1.60, 14.5 * 0.974, 0.90)):
        p_in = min(cl, 1.70) * 0.88 * vmin
        p_ich = ichg * (1 - 0.065) * (7.40 + ichg * (21.0e-3 * 0.60 + 0.020)) / 0.93
        p = min(p_in, p_ich)
        cap[lab] = (p_in, p_ich, p)
        out("R9.H7 %-38s input limit %.2f W (clamp min %.3f A), ICHG limit %.2f W -> %.2f W (%+.1f %% vs 18.9 W)"
            % (lab, p_in, min(cl, 1.70), p_ich, p, (p / 18.9 - 1) * 100))
    RJ["h7"] = {k: [r4(x) for x in v] for k, v in cap.items()}
    # H.13 glitch immunity (r3_calc.py l.546-556): C252 2.2 nF, Q201/Q203 recovery 3 x 47k x 50 pF
    tau_q = 47e3 * 50e-12
    tau_ilim = par(R255, R23_EVM, R256_EVM) * 2.2e-9
    gl, gl_r3 = [], []
    for tg in (100e-9, 1e-6):
        gl.append(res["regen"]["pin"][1] * (1 - math.exp(-(tg + 3 * tau_q) / tau_ilim)))
        gl_r3.append(res["regen"]["pin"][0] * (1 - math.exp(-(tg + 3 * tau_q) / tau_ilim)))
    out("R9.H13 release glitch 0.1 / 1.0 us toward the highest released level %.3f V: ILIM_HIZ reaches <= %.3f / %.3f V against "
        "0.75 V; r3_calc.py H.13 charged toward the lowest released level (its res[...][3]), which gives %.3f / %.3f V here and gave "
        "the r8 0.28 / 0.32 V, a non-conservative basis" % (res["regen"]["pin"][1], gl[0], gl[1], gl_r3[0], gl_r3[1]))
    RJ["h4"] = dict(regen_A=[r4(x) for x in res["regen"]["clamp"]], regen_nom_A=r4(res["regen"]["nom"]),
                    fc_A=[r4(x) for x in res["fc"]["clamp"]], fc_nom_A=r4(res["fc"]["nom"]),
                    regen_pin_V=[r4(x) for x in res["regen"]["pin"]], fc_pin_V=[r4(x) for x in res["fc"]["pin"]],
                    held_V=r4(hiz), held_r23_open_V=r4(hiz_open))
    RJ["h5"] = dict(efuse_margin_A=r4(2.05 - rmax))
    RJ["h12"] = dict(fc_image_A=[0.99, 1.05], fc_clamp_plus_aux_A=[r4(fmax + I_AUX[0]), r4(fmax + I_AUX[1])],
                     regen_clamp_plus_aux_A=[r4(rmax + I_AUX[0]), r4(rmax + I_AUX[1])])
    RJ["h13"] = dict(glitch_V=[r4(x) for x in gl], glitch_r3_basis_V=[r4(x) for x in gl_r3])
    return res


# ======================================================================================================================
def sec_h19():
    head("R9.H19 /CE pull-ups R272 + R272b without the U204 divider R262/R263 (r9-2 DNP)")
    i_ce = 1e-6 + 10e-6     # IIN_BIAS_CE 1 uA (DS p.16) + U201 Ioff 10 uA (SCES364J, r3_calc.py l.735)
    both = REGN[0] - par(R272, R272) * i_ce
    one = REGN[0] - R272 * i_ce
    out("  /CE HIGH (REGN 4.8 V min, %.0f uA load): both fitted %.3f V, one open %.3f V (r8 with the U204 2.0 MOhm divider: "
        ">= 4.49 / >= 4.17 V); VIH_CE 1.3 V (DS p.16); both open: /CE floating, TODO(verify: SLUSDV2C IIN_BIAS_CE direction)"
        % (i_ce * 1e6, both, one))
    RJ["h19_ce"] = dict(both_V=r4(both), one_open_V=r4(one))


# ======================================================================================================================
def sec_h20_misc():
    head("R9.H20 26 AWG quantity and pin-22 keeper")
    taps = {"T1": 0.15, "T7b": 0.15, "T2": 0.10, "T5": 0.12, "T6": 0.12, "T10": 0.15, "T13": 0.15, "T16": 0.15, "T17": 0.15,
            "T17r": 0.15}   # A.4 maxima (r9-4: T10 0.15 m on J2.47)
    s = sum(taps.values())
    out("  ten taps (A.4 maxima): %.2f m in the J-TAP cable assembly conductors (gauge TODO(verify: Molex 2147581101)); "
        "loose 26 AWG serves W6 only: 0.60 m, %.2f m with the 50 %% strip/twist allowance (r8: 2.72 + 0.60 + 0.20 = 3.52 m, "
        "~5.3 m with allowance)" % (s, 0.60 * 1.5))
    rs = R105 + R129
    out("  CHG_IIN source %.1f kOhm (R105 + R129): 1 uA of pad keeper current = %.1f mV = %.1f mA at 0.764 V/A (%.1f-%.1f mA over "
        "the 0.703-0.826 V/A gain band)" % (rs / 1e3, rs * 1e-6 * 1e3, rs * 1e-6 / (IMON_GAIN[1] * R105) * 1e3,
                                            rs * 1e-6 / (IMON_GAIN[2] * R105) * 1e3, rs * 1e-6 / (IMON_GAIN[0] * R105) * 1e3))
    RJ["h20_misc"] = dict(tap_sum_m=round(s, 3), w6_26awg_m=0.60, w6_with_allowance_m=0.90,
                          keeper_mA_per_uA=r4(rs * 1e-6 / (IMON_GAIN[1] * R105) * 1e3))


# ======================================================================================================================
def sec_h21(v_cr):
    head("R9.H21 EIB R275 STAT series with CE_DRV driven push-pull by U106A (r9-1; was U114A)")
    out("  inputs: CR rail %.3f V (R9.H20), U106A output resistance %.1f-%.1f ohm (LVC bound), R130 %.0f ohm, R275 %.0f ohm, "
        "STAT sink 0-80 ohm, EIB U201 1A divider R250 %.0f ohm / R267 %.0f ohm" % (v_cr, ROUT_LVC[0], ROUT_LVC[1], R130, R275,
                                                                                 R250, R267))
    rows = {}
    for r275 in (0.0, R275):
        imax = v_cr / (ROUT_LVC[0] + R130 + r275 + RDS_STAT[0])
        imin = v_cr / (ROUT_LVC[1] + R130 + r275 + RDS_STAT[1])
        if r275:
            # lowest ribbon-5 node: highest driver resistance with the strongest sink (Rds 0)
            i_w = v_cr / (ROUT_LVC[1] + R130 + r275 + RDS_STAT[0])
            vnode = v_cr - i_w * (ROUT_LVC[1] + R130)
        else:
            vnode = v_cr * RDS_STAT[1] / (ROUT_LVC[1] + R130 + RDS_STAT[1])
        v1a = vnode * R267 / (R250 + R267)
        rows[r275] = (imin, imax, vnode, v1a)
        out("  4-5 short, STAT sinking, CE_DRV HIGH, R275 = %4.0f ohm: STAT current %.2f-%.2f mA (abs max 6 mA, DS); ribbon-5 "
            "node >= %.3f V -> U201 1A >= %.3f V (VIH 2.0 V at VCC 2.7-3.6 V)" % (r275, imin * 1e3, imax * 1e3, vnode, v1a))
    i_lo = (v_cr - 0.0) / (R107 + 0 + ROUT_LVC[0] + R130)
    out("  4-5 short, CE_DRV LOW (P5 LOW): the STAT net (pin 6) is pulled LOW through R130 (reads 'charging'; FR-44 plausibility); "
        "R107 current into the driver %.3f mA; U201 1A LOW -> /CE released HIGH (inhibited)" % (i_lo * 1e3))
    vol6 = (v_cr * (R275 + RDS_STAT[0]) / (R107 + R275 + RDS_STAT[0]), v_cr * (R275 + RDS_STAT[1]) / (R107 + R275 + RDS_STAT[1]))
    vil = VIL_FRAC * V_IO[0]
    out("  normal STAT LOW at pin 6 with R275: %.3f-%.3f V (STAT sink 0-80 ohm) against VIL %.3f V (0.30 x 3.135 V, ASSUMPTION); "
        "sink %.3f mA; 3-4 short: pin 6 stuck LOW, R275 limits the STAT-pin current to <= %.2f mA"
        % (vol6[0], vol6[1], vil, v_cr / (R107 + R275) * 1e3, v_cr / R275 * 1e3))
    RJ["h21_r275"] = dict(short_mA=[r4(rows[R275][0] * 1e3), r4(rows[R275][1] * 1e3)],
                          short_noR275_mA=[r4(rows[0.0][0] * 1e3), r4(rows[0.0][1] * 1e3)],
                          u201_1a_min_V=r4(rows[R275][3]), u201_1a_noR275_V=r4(rows[0.0][3]),
                          stat_low_pin6_V=[r4(vol6[0]), r4(vol6[1])], stat_sink_mA=r4(v_cr / (R107 + R275) * 1e3))
    return vol6


# ======================================================================================================================
def t2_nodes(vbus, vuvb_out):
    """r3_calc.py l.63-71: (H1 IN-, UVB IN+) for a VBUS and a UVB output voltage."""
    g = 1 / RT2; g1 = 1 / R111; g2 = 1 / R112; g4 = 1 / R114; g5 = 1 / R115; g6 = 1 / R116
    A = [[g + g1 + g4, -g1, -g4], [-g1, g1 + g2, 0.0], [-g4, 0.0, g4 + g5 + g6]]
    _, vhm, vup = solve3(A, [g * vbus, 0.0, g6 * vuvb_out])
    return vhm, vup


def h1_trips(vbus, voh, vol=0.0, hint=0.005, vuvb=None):
    """r3_calc.py l.73-86 nominal: (rise, fall) of V-MOT for the H1 comparator; output swing vol..voh through R113."""
    vhm, _ = t2_nodes(vbus, voh if vuvb is None else vuvb)
    ra1 = RT1 + R109
    g1, g2, g3 = 1 / ra1, 1 / R110, 1 / R113
    a, b = g1 / (g1 + g2 + g3), g3 / (g1 + g2 + g3)
    return (vhm + hint / 2 - b * vol) / a, (vhm - hint / 2 - b * voh) / a


def uvb_trips_nom(voh, vref=VREF[1], hint=0.005):
    out_ = []
    for vout, sign in ((0.0, +1), (voh, -1)):
        tgt = vref + sign * hint / 2
        _, v0 = t2_nodes(0.0, vout)
        _, v1 = t2_nodes(20.0, vout)
        out_.append((tgt - v0) / ((v1 - v0) / 20.0))
    return out_[0], out_[1]


def sec_h22(v_cr):
    head("R9.H22 FCC_OFF / FCC_ON at the pin-31 EN net (U119, U120; RGN_ON U121 and the RGN tap removed); rescue case (c)")
    # FCC_OFF (U119): IN+ = REF119 x R185/(R184 + R185); IN- = /FCC through R186, R187 3.30 MOhm pull-up to the CR rail
    lo, hi = 1e9, -1e9
    for vr in (VREF[0], VREF[2]):
        for dt in DT_CR:
            for tcs in (-1, 1):
                for s in (-1, 1):
                    vref = vr * (1 + tcs * REF_TC * dt)
                    v = vref * R185 * (1 + s * 0.01) / (R184 * (1 - s * 0.01) + R185 * (1 + s * 0.01))
                    lo, hi = min(lo, v), max(hi, v)
    off_in = (lo - VOS - VHYS[1] / 2, hi + VOS + VHYS[1] / 2)

    def en_from_inm(t, vrail):
        i_pu = (vrail - t) / R187
        v_fcc = t - i_pu * R186
        i_div = v_fcc / (R188 + R189)
        return v_fcc - (i_pu - i_div) * R122

    off_en = (min(en_from_inm(off_in[0], v) for v in (v_cr, V_IO[2])), max(en_from_inm(off_in[1], v) for v in (v_cr, V_IO[0] - 0.07)))
    out("  FCC_OFF (U119) threshold at IN-: %.3f-%.3f V (REF/3 by R184 20.0k / R185 10.0k 1 %%, REF drift 0-45 C, Vos 9 mV, VHYS/2); "
        "referred to the pin-31 EN net through R122 + R186 with the R187 current: %.3f-%.3f V (R187 shift %.1f mV); below VEN_F min "
        "%.1f V by >= %.3f V" % (off_in[0], off_in[1], off_en[0], off_en[1], (off_in[0] - en_from_inm(off_in[0], v_cr)) * 1e3,
                                 VEN_F_MIN, VEN_F_MIN - off_in[1]))
    # FCC_ON (U120): IN+ = /FCC x R189/(R188 + R189), IN- = own REF (r3_calc.py l.1146-1158 form)
    lo2, hi2 = 1e9, -1e9
    for vr in (VREF[0], VREF[2]):
        for dt in DT_CR:
            for tcs in (-1, 1):
                for s in (-1, 1):
                    vref = vr * (1 + tcs * REF_TC * dt)
                    k = R189 * (1 - s * 0.01) / (R188 * (1 + s * 0.01) + R189 * (1 - s * 0.01))
                    for vos in (-VOS, VOS):
                        for vh in (0.0, VHYS[1]):
                            v = (vref + vos + vh) / k
                            lo2, hi2 = min(lo2, v), max(hi2, v)
    shift_on = (v_cr - 1.8) / (R187 + R186) * R122 - 1.8 / (R188 + R189) * R122
    out("  FCC_ON (U120) trip at the /FCC node: %.3f-%.3f V (nominal %.3f V; R188 453k / R189 1.00M 1 %%, own REF) vs VEN_R max "
        "%.1f V: margin %.3f V; the R122 drop shifts the EN-net figure by %.2f mV" % (lo2, hi2, VREF[1] * (R188 + R189) / R189,
                                                                                    VEN_R_MAX, lo2 - VEN_R_MAX, shift_on * 1e3))
    v_open = v_cr * (R188 + R189) / (R187 + R186 + R188 + R189)
    out("  T5 conductor open: /FCC %.3f V (R187 + R186 against R188 + R189) -> FCC_OFF reads 'may be on' (> %.2f V), FCC_ON reads "
        "off (< %.3f V): FCCP LOW, QF LOW, RFC_OFF = H1.UVB (r8 0.97 V)" % (v_open, off_in[1], lo2))
    # pin 31 high-Z with the 10 kOhm bodge open: EN held by REN_PD against the CR network
    vth = v_cr * (R188 + R189) / (R187 + R186 + R188 + R189)
    rth = par(R187 + R186, R188 + R189) + R122
    hz = [vth * ren / (rth + ren) for ren in (REN_PD[0], REN_PD[2])]
    out("  pin 31 high-Z and the 10 kOhm EN bodge open: EN %.3f-%.3f V (CR Thevenin %.3f V / %.0f kOhm against REN_PD 475-985 kOhm) "
        "< VEN_F min %.1f V (r8 0.31-0.48 V)" % (hz[0], hz[1], vth, rth / 1e3, VEN_F_MIN))
    # rescue predicate case (c) (r3_calc.py H.22(g)): arithmetic only
    T17 = 16.0e-3 + 1.4e-3
    lhs = 14.16 - 0.005 * T17 * 1e3
    out("  rescue case (c), V_bus 14.16 V, zero slope (SAG_FLOOR 0.005 V/ms x %.1f ms): LHS %.3f V vs RHS 13.44 V (0.4 mF) -> admit, "
        "14.89 V (0.97 mF) -> refuse; the H2c classifier is withdrawn (r9-7), so the case survives only as the arithmetic of the "
        "open V_bus-sag branch (F.4, TODO(design: r9 audit))" % (T17 * 1e3, lhs))
    RJ["h22_fcc"] = dict(fcc_off_inm_V=[r4(off_in[0]), r4(off_in[1])], fcc_off_en_V=[r4(off_en[0]), r4(off_en[1])],
                         fcc_on_V=[r4(lo2), r4(hi2)], fcc_on_margin_V=r4(lo2 - VEN_R_MAX), t5_open_V=r4(v_open),
                         pin31_hiz_bodge_open_V=[r4(hz[0]), r4(hz[1])], rescue_c_lhs_V=r4(lhs))
    return off_in, off_en, (lo2, hi2)


# ======================================================================================================================
def sec_h23(v_cr):
    head("R9.H23(n) R106s FLT bridges on the J-TAP cavity map; H.23(x) rows (3)-(4); H.23(y) rows (1) and (7)")
    # J-TAP map (A.4 / A.8, r9-13): row A T2 T17 T17r T5 T13, row B T6 T1 T7b T16 T10; orthogonal neighbours of T16 (B4).
    # Superseded in r9-13: row A T1 T7b T17r T5 T13, row B T6 T2 T17 T16 T10 (T17 in B3). The T16-T17 bridge below is kept
    # as the record of that map (design A.8, history table of Table A.8-T2).
    R_FLT = (36.0, 70.0, 130.0)
    i_max = V_IO[2] / (0.0 + R106S * 0.99 + R_FLT[0])
    i_min = V_IO[0] / (R_DRV + R106S * 1.01 + R_FLT[2])
    v_en_min = min(v - v / (R_DRV + r + rf) * R_DRV for v in V_IO for r in (R106S * 0.99, R106S * 1.01) for rf in R_FLT)
    out("  T16 (B4) orthogonal neighbours (r9-13 map): A4 T5 (pin 31 push-pull), B5 T10 (pin 33 push-pull), B3 T7b (GND); "
        "the r9-12 map had B3 T17 (pin 22 analog), whose T16-T17 bridge stays below as history")
    out("  T5-T16 or T10-T16 bridge, output HIGH, FLT asserted: FLT current %.3f mA max (3V3 %.3f V, 0 ohm driver, R106s %.0f ohm, "
        "R(FLT) 36 ohm) = %.3f of the 10 mA abs max; %.3f mA min; the bridged output stays >= %.3f V (40 ohm driver), so the EN net "
        "(T5) or QUAL (T10, through R147) follows its command and pin 35 reads that output level (a fault is masked while it is HIGH); "
        "the figures equal the r8 F06-F17 case" % (i_max * 1e3, V_IO[2], R106S * 0.99, i_max / 10e-3, i_min * 1e3, v_en_min))
    # T16-T17: pin-35 pull-up into the CHG_IIN conductor (FLT released) and FLT into CHG_IIN (FLT asserted)
    rs = R105 + R129
    v_iin = [V_IO[1] * rs / (R_PU[1] + rs), V_IO[2] * rs / (R_PU[0] + rs), V_IO[0] * rs / (R_PU[2] + rs)]
    out("  T16-T17 bridge, FLT released: the pin-35 pull-up feeds R129 + R105 (%.1f kOhm): node %.3f V nominal (%.3f-%.3f V over "
        "11-33 kOhm), read on pin 22 as %.2f A at 0.764 V/A and on pin 35 inside the undefined band VIL %.2f-%.2f / VIH %.2f-%.2f V; "
        "FLT asserted: the node falls toward 0 V through R106s + R(FLT) (CHG_IIN reads ~0 A); the CHG_IIN/IBUS cross-check (FR-11) "
        "sees the FLT-released case only: FR-23 attempts no I2C with FLT asserted and no zero-current plausibility check "
        "exists, so the asserted case is latent until FLT releases (r9-12, audit run 002 ADV-R2-07)" % (rs / 1e3, v_iin[0], v_iin[2], v_iin[1], v_iin[0] / 0.764, VIL_FRAC * V_IO[0], VIL_FRAC * V_IO[2],
                             VIH_FRAC * V_IO[0], VIH_FRAC * V_IO[2]))
    out("  retired: the F17-F15 bridge (T14, pin 16 H2c, U108; r8 H.23(n) <= 1.719 mA and H.23(y) row (1) node 1.60-1.93 V): T14 "
        "and U108 are removed and no J-TAP cavity carries H2c")
    rb_typ = V_IO[1] * (R106S + R_FLT[1]) / (R_PU[1] + R106S + R_FLT[1])
    rb_max = V_IO[2] * (R106S * 1.01 + R_FLT[2]) / (R_PU[0] + R106S * 1.01 + R_FLT[2])
    out("  FLT readback LOW (no bridge): %.3f V typ, %.3f V max vs VIL %.3f V (unchanged from r8)" % (rb_typ, rb_max, VIL_FRAC * V_IO[0]))
    # (x)(3) and (y)(7): T1 increment in r9 (F.5 T1 step 8: QUAL LOW for >= one 1 kHz tick, then the FR-46 pre-edge read)
    rd = (5 * 9 + 3 + 5 * 9 + 3 + 4 * 9 + 3 + 5 * 9 + 3) / 100e3 + 4 * 4.7e-6    # four field reads, r7_calc.py i2c_bits_read
    inc = 1.0e-3 + rd
    out("  H.23(x)(3) / (y)(7) T1 increment (r9): the heartbeat pause, step 8b and step 8c are removed; step 8 adds <= one T_TICK_MAX "
        "(1.0 ms) of QUAL-LOW wait + the FR-46 pre-edge read %.3f ms at 100 kHz with four t_BUF = %.3f ms (r8 128.5 ms); QUAL "
        "normally falls at step 6, so the wait is usually already met" % (rd * 1e3, inc * 1e3))
    i_pu = V_IO[2] / R_PU[0]
    out("  H.23(x)(4) T-C-05c pad pull-up current with FLT released and pin 31 LOW (T5-T16 bridge; pin 30 in r8): %.3f mA "
        "(3.465 V into 11 kOhm), unchanged" % (i_pu * 1e3))
    RJ["h23"] = dict(bridge_mA=[r4(i_min * 1e3), r4(i_max * 1e3)], bridged_output_min_V=r4(v_en_min),
                     t16_t17_node_V=[r4(v_iin[2]), r4(v_iin[0]), r4(v_iin[1])], readback_low_V=[r4(rb_typ), r4(rb_max)],
                     t1_increment_ms=r4(inc * 1e3), pre_edge_read_ms=r4(rd * 1e3), tc05c_pullup_mA=r4(i_pu * 1e3))


# ======================================================================================================================
# r9-12 (netlist step, D-53): cr.net now carries R132 = R131B = 4.99 kOhm (ruling R2). H.24(a) stays the r9-9 record on
# the superseded 100 ohm basis, so it uses this constant instead of the netlist value; H.24(d) evaluates the new value.
R_SER_R9 = 100.0          # ohm, R132 / R131B before r9-12 (superseded in r9)


def sec_h24a(v_cr, i_cr_only, i_eib):
    head("R9.H24(a) Ribbon 9-10 (RFC_OFF, U106B) and 8-9 (ILIM_REL_B, U110B) shorts with the R175 sag (J.2 item 70(a))")
    out("  model: Teensy 3V3 -> R175 %.0f ohm -> CR rail (base load as a constant current) -> LVC driver (Rout %.1f-%.1f ohm, VCC = "
        "the CR rail) -> R132 / R131B %.0f ohm (r9-9 basis) -> J101 pin 9 (GND). The EIB rail follows the CR rail through R176 || R177."
        % (R175, ROUT_LVC[0], ROUT_LVC[1], R_SER_R9))
    base = {"CR + EIB worst static (R9.H15) less the shorted path's own EIB input": i_cr_only + i_eib - 3.3 / (100 + R250 + R267),
            "minimum: comparators, LVC, REF divider, R274 only (STAT HIGH, drivers LOW)": 4 * 1e-6 + 5 * 1e-6 + VREF[0] / (R184 + R185) + 3.0 / R274}
    rows = []
    for vio in V_IO:
        for bl, ib in base.items():
            for ro in ROUT_LVC:
                rsh = ro + R_SER_R9
                v = (vio - R175 * ib) / (1 + R175 / rsh)
                i = v / rsh
                rows.append((vio, bl, ro, i, v))
    i_all = [r[3] for r in rows]
    v_all = [r[4] for r in rows]
    nom = [r for r in rows if r[0] == V_IO[1] and r[2] == 0.0][0]
    out("  without R175 (the r9-2 finding's figure): 3.30 V / 100 ohm = %.1f mA" % (3.3 / R_SER_R9 * 1e3))
    for vio, bl, ro, i, v in rows:
        out("    3V3 %.3f V, %-78s Rout %4.1f ohm: short %.2f mA, CR rail %.3f V" % (vio, bl[:78], ro, i * 1e3, v))
    v_eib = min(v_all) - i_eib * par(R176, R177)
    out("  range: short current %.2f-%.2f mA; CR rail %.3f-%.3f V (EIB rail >= %.3f V); R132 / R131B dissipation <= %.1f mW (0603 0.1 W); "
        "R175 <= %.1f mW" % (min(i_all) * 1e3, max(i_all) * 1e3, min(v_all), max(v_all), v_eib, max(i_all) ** 2 * R_SER_R9 * 1e3,
                             max((r[0] - r[4]) ** 2 / R175 for r in rows) * 1e3))
    out("  limits (SCES201N, TODO(verify)): continuous output current abs max 50 mA -> not exceeded (factor %.1f); recommended IOH "
        "-24 mA at VCC 3.0 V, -8 mA at 2.3 V, -4 mA at 1.65 V: the driver sources %.1f-%.1f mA at VCC %.2f-%.2f V, above the "
        "recommended IOH for that VCC (interpolated %.1f-%.1f mA), so VOH is not specified there; VCC stays above the LVC 1.65 V "
        "and TLV3012 1.8 V minimums by >= %.3f V" % (LVC_IO_ABS / max(i_all), min(i_all) * 1e3, max(i_all) * 1e3, min(v_all),
                                                       max(v_all), interp_ioh(min(v_all)) * 1e3, interp_ioh(max(v_all)) * 1e3,
                                                       min(v_all) - TLV_VS_MIN))
    # consequences of the sag on the comparators (r3 H1/UVB model, nominal)
    vs = nom[4]
    h1n = h1_trips(16.0, v_cr)
    h1s = h1_trips(16.0, vs)
    ur, uf = uvb_trips_nom(v_cr)
    urs, ufs = uvb_trips_nom(vs)
    out("  sag effect at the nominal case (CR rail %.3f V): H1 hysteresis (R113 swing) %.3f -> %.3f V at VBUS 16.0 V (rise %.3f V "
        "unchanged, fall %.3f -> %.3f V: H1 drops earlier); UVB fall %.3f -> %.3f V, rise %.3f V (UVB drops earlier): both shifts "
        "remove the regen release earlier; REF 1.242 V needs VS >= 1.8 V (met); LVC VIH at VCC %.2f V falls with VCC, and the "
        "Teensy-driven inputs (P5, QUAL) are 5.5 V tolerant. Fail-safe ruling: audit run 002 (J.2 item 70(a))"
        % (vs, h1n[0] - h1n[1], h1s[0] - h1s[1], h1n[0], h1n[1], h1s[1], uf, ufs, ur, vs))
    out("  when each short draws current: 9-10 while RFC_OFF = FCC_OFF + H1.UVB is HIGH, i.e. whenever FC_CHARGE is off (most of "
        "Idle and Run); 8-9 while ILIM_REL (release) is HIGH. The converter side is safe in both (9-10: Q202 FC leg on, FC clamp; "
        "8-9: U202 holds ILIM_HIZ)")
    RJ["h24a"] = dict(no_r175_mA=r4(3.3 / R_SER_R9 * 1e3), short_mA=[r4(min(i_all) * 1e3), r4(max(i_all) * 1e3)],
                      cr_rail_V=[r4(min(v_all)), r4(max(v_all))], eib_rail_min_V=r4(v_eib), nominal=dict(mA=r4(nom[3] * 1e3), V=r4(nom[4])),
                      abs_max_factor=r4(LVC_IO_ABS / max(i_all)), h1_hyst_V=[r4(h1n[0] - h1n[1]), r4(h1s[0] - h1s[1])],
                      uvb_fall_V=[r4(uf), r4(ufs)])
    return min(i_all), max(i_all), min(v_all), max(v_all)


def interp_ioh(vcc):
    pts = sorted(LVC_IOH_REC.items())
    if vcc <= pts[0][0]:
        return pts[0][1]
    for (v0, i0), (v1, i1) in zip(pts, pts[1:]):
        if v0 <= vcc <= v1:
            return i0 + (i1 - i0) * (vcc - v0) / (v1 - v0)
    return pts[-1][1]


# ======================================================================================================================
# H.24(d) J.2 item 70(a) option (a): the R132 / R131B value that keeps the CR rail in the LVC VCC 3.0 V row during a
# ribbon 9-10 / 8-9 short and still meets the EIB input and timing requirements (r9-12, check-in 2 ruling R2)
# ======================================================================================================================
E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54,
       1.58, 1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49,
       2.55, 2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02,
       4.12, 4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49,
       6.65, 6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76]
LVC_VCC_ROW = 3.0          # V, SCES201N / SCES198N VCC 3.0 V row (IOH -24 mA recommended, VOH >= 2.4 V at -16 mA), TODO(verify)
LVC_VIH_EIB = 2.0          # V, SN74LVC3G06 / SN74LVC1G06 VIH at VCC 2.7-3.6 V, TODO(verify: SCES datasheets section 6.3)
LVC_VIL_EIB = 0.8          # V, same row, TODO(verify)
NOISE_MARGIN = 0.4         # V, the LVC family's own VOH (2.4 V) - VIH (2.0 V) margin at VCC 3.0 V, adopted as the HIGH margin
I_LEAK_LVC = 5e-6          # A, LVC input leakage II max, TODO(verify: SCES datasheets section 6.5)
C_RIBBON_PER_M = 150e-12   # F/m, 0.635 mm flat cable, conductor to both neighbours, ASSUMPTION (conservative), TODO(verify: W5 MPN, T-A-05)
L_RIBBON = 0.3048          # m, W5 factory cable 0.30 m (design document B.6, W5 row)
C_CONN = 10e-12            # F, J101 + J201 + traces, ASSUMPTION
C_IN_LVC = 5e-12           # F, LVC input capacitance, ASSUMPTION, TODO(verify: SCES datasheets section 6.5, Ci)
T_GATE_RC = 47.0e3 * 50e-12   # s, EIB R252 / R254 47.0 kOhm (eib.net) x Ciss 50 pF (H.13 assumption): the downstream gate edge
T_TICK = 1e-3              # s, the 1 kHz firmware tick
R_SEL = 4.99e3             # ohm, the selected E96 value (r9-12, ruling R2)
R253 = parse_value(EIB_COMPS["R253"]); R269 = parse_value(EIB_COMPS["R269"])   # EIB RFC_OFF input series / pull-down
assert parse_value(EIB_COMPS["R266"]) == R253 and parse_value(EIB_COMPS["R270"]) == R269   # ILIM_REL_B path identical


def h24d_case(r_ser, i_cr_only, i_eib):
    """Worst corners for one series value: short (min CR rail, max current), EIB input levels, ribbon RC edge."""
    path_own = 3.3 / (r_ser + R250 + R267)
    base_short = (i_cr_only + i_eib - 3.3 / (100 + R250 + R267),
                  4 * 1e-6 + 5 * 1e-6 + VREF[0] / (R184 + R185) + 3.0 / R274)
    v_min, i_max, sag_max = 1e9, 0.0, 0.0
    for vio in V_IO:
        for ib in base_short:
            for ro in ROUT_LVC:
                for tol in (-0.01, 0.01):
                    for t175 in (-0.01, 0.01):
                        r175 = R175 * (1 + t175)
                        rsh = ro + r_ser * (1 + tol)
                        v = (vio - r175 * ib) / (1 + r175 / rsh)
                        v_min, i_max = min(v_min, v), max(i_max, v / rsh)
                        sag_max = max(sag_max, (vio - r175 * ib) - v)
    # signal: Teensy 3V3 low corner, full worst static load with this path HIGH (100 ohm basis of R9.H15 + the delta)
    i_full = i_cr_only + i_eib - 3.3 / (100 + R250 + R267) + path_own
    v_cr_lo = V_IO[0] - R175 * 1.01 * i_full
    v_eib_lo = v_cr_lo - i_eib * R176 * 1.01      # one ribbon 3V3 conductor open
    rs_hi, rin_hi, rpd_lo = r_ser * 1.01, R253 * 1.01, R269 * 0.99
    i_path = v_cr_lo / (rs_hi + rin_hi + rpd_lo)
    v_drv = v_cr_lo - ROUT_LVC[1] * i_path
    v_in_hi = v_drv * rpd_lo / (rs_hi + rin_hi + rpd_lo) - I_LEAK_LVC * par(rs_hi + rin_hi, rpd_lo)
    v_in_lo = I_LEAK_LVC * par(rs_hi + rin_hi + ROUT_LVC[1], R269 * 1.01)
    c_tot = C_RIBBON_PER_M * L_RIBBON + C_CONN + C_IN_LVC
    tau = par(rs_hi + rin_hi, R269 * 1.01) * c_tot
    vf = v_in_hi + I_LEAK_LVC * par(rs_hi + rin_hi, rpd_lo)
    t_rise = tau * math.log(vf / max(vf - LVC_VIH_EIB, 1e-9))
    t_fall = tau * math.log(vf / LVC_VIL_EIB)
    return dict(v_min=v_min, i_max=i_max, sag_max=sag_max, v_cr_lo=v_cr_lo, v_eib_lo=v_eib_lo, v_in_hi=v_in_hi,
                v_in_lo=v_in_lo, tau=tau, t_rise=t_rise, t_fall=t_fall, c_tot=c_tot, p_short=i_max ** 2 * r_ser * 1.01,
                p_norm=(V_IO[2] / (r_ser + R250 + R267)) ** 2 * r_ser)


def h24d_ok(c):
    return dict(rail=c["v_min"] >= LVC_VCC_ROW, ioh=c["i_max"] <= LVC_IOH_REC[3.0],
                vih=c["v_in_hi"] >= LVC_VIH_EIB + NOISE_MARGIN, vil=c["v_in_lo"] <= LVC_VIL_EIB,
                timing=max(c["t_rise"], c["t_fall"]) <= T_GATE_RC)


def sec_h24d(v_cr, i_cr_only, i_eib):
    head("R9.H24(d) J.2 item 70(a) option (a): R132 / R131B value for a ribbon 9-10 / 8-9 short (ruling R2, r9-12)")
    out("  topology (eib.net): RFC_OFF_J (J201.10) -> R253 %.2fk -> /N_RFIN = U201 3A (SN74LVC3G06), R269 %.1fk to AGND; "
        "ILIM_REL_B (J201.8) -> R266 %.2fk -> /N_RBIN = U202 A (SN74LVC1G06), R270 %.1fk to AGND. No other EIB load; no "
        "CR-side consumer between U106B / U110B and R132 / R131B (cr.net /RFC_OFF, /ILIM_REL)."
        % (R253 / 1e3, R269 / 1e3, parse_value(EIB_COMPS["R266"]) / 1e3, parse_value(EIB_COMPS["R270"]) / 1e3))
    out("  criteria: (1) short: CR rail >= %.1f V at every corner (every CR LVC part stays in the VCC 3.0 V row; the TLV3012 "
        "1.8 V and LVC 1.65 V minimums are kept by >= 1.2 V), Teensy 3V3 3.135-3.465 V, both R9.H24(a) base loads, Rout "
        "0-37.5 ohm, R and R175 +-1 %%; (2) driver current <= the recommended IOH %.0f mA at VCC 3.0 V; (3) EIB HIGH input "
        ">= VIH %.1f V + %.1f V (the LVC VOH 2.4 V - VIH 2.0 V margin) at the Teensy 3V3 low corner, Rout 37.5 ohm, resistors "
        "at the adverse 1 %%, II %.0f uA; (4) LOW input <= VIL %.1f V; (5) the ribbon RC edge to VIH / VIL <= the downstream "
        "EIB gate RC %.2f us (R252 / R254 47.0k x Ciss 50 pF, H.13), which is %.3f %% of the 1 ms tick"
        % (LVC_VCC_ROW, LVC_IOH_REC[3.0] * 1e3, LVC_VIH_EIB, NOISE_MARGIN, I_LEAK_LVC * 1e6, LVC_VIL_EIB, T_GATE_RC * 1e6,
           T_GATE_RC / T_TICK * 100))
    out("  capacitance: ribbon %.0f pF/m x %.4f m + connectors %.0f pF + LVC Ci %.0f pF = %.1f pF (ASSUMPTION, "
        "TODO(verify: W5 flat-cable MPN in T-A-05; SCES Ci)); the 100 ohm basis edge is %.3f us"
        % (C_RIBBON_PER_M * 1e12, L_RIBBON, C_CONN * 1e12, C_IN_LVC * 1e12,
           (C_RIBBON_PER_M * L_RIBBON + C_CONN + C_IN_LVC) * 1e12, h24d_case(100.0, i_cr_only, i_eib)["t_rise"] * 1e6))
    feas = []
    for dec in (1e3, 1e4):
        for m in E96:
            r = m * dec
            if r > 20e3:
                continue
            if all(h24d_ok(h24d_case(r, i_cr_only, i_eib)).values()):
                feas.append(r)
    lo_r, hi_r = min(feas), max(feas)
    out("  feasible E96 window (1.00k-20.0k swept): %.2fk-%.2fk (%d values); below it criterion (1) fails, above it (3) or "
        "(5) fails" % (lo_r / 1e3, hi_r / 1e3, len(feas)))
    for r in sorted({100.0, 1.00e3, 2.00e3, lo_r, R_SEL, 10.0e3, hi_r, 20.0e3}):
        c = h24d_case(r, i_cr_only, i_eib)
        ok = h24d_ok(c)
        out("    R %7.0f ohm: short <= %6.3f mA, CR rail >= %.3f V (sag <= %5.1f mV); EIB HIGH >= %.3f V; LOW <= %.3f V; "
            "edge rise %.3f / fall %.3f us; %s"
            % (r, c["i_max"] * 1e3, c["v_min"], c["sag_max"] * 1e3, c["v_in_hi"], c["v_in_lo"], c["t_rise"] * 1e6,
               c["t_fall"] * 1e6, "PASS" if all(ok.values()) else "fail " + ",".join(k for k, v in ok.items() if not v)))
    c = h24d_case(R_SEL, i_cr_only, i_eib)
    ok = h24d_ok(c)
    assert all(ok.values()), ok
    ib = i_cr_only + i_eib - 3.3 / (100 + R250 + R267)
    vs = (3.30 - R175 * ib) / (1 + R175 / R_SEL)
    h1n, h1s = h1_trips(16.0, v_cr), h1_trips(16.0, vs)
    _, uf = uvb_trips_nom(v_cr)
    _, ufs = uvb_trips_nom(vs)
    pin34 = min((vio - R175 * 1.01 * ib) / (1 + R175 * 1.01 / (R_SEL * 0.99)) * R_PD_IMX / (R126 + R_PD_IMX) - VIH_FRAC * vio
                for vio in V_IO)
    d_load = 2 * (3.3 / (100 + R250 + R267) - 3.3 / (R_SEL + R250 + R267))
    out("  selected: R132 = R131B = %.2f kOhm 1 %% 0603 (E96; same R_0603_1608Metric footprint, top side, D-44; value change "
        "only): short <= %.3f mA (%.0f x below the 24 mA recommended IOH; r9 100 ohm basis 14.9-20.5 mA), CR rail >= %.3f V "
        "(%.0f mV above the 3.0 V row; TLV3012 1.8 V / LVC 1.65 V minimums kept by >= %.2f V); EIB rail (one 3V3 conductor "
        "open, no short) >= %.3f V"
        % (R_SEL / 1e3, c["i_max"] * 1e3, LVC_IOH_REC[3.0] / c["i_max"], c["v_min"], (c["v_min"] - LVC_VCC_ROW) * 1e3,
           c["v_min"] - TLV_VS_MIN, c["v_eib_lo"]))
    out("    signal: EIB HIGH >= %.3f V against VIH 2.0 V (margin %.3f V >= 0.4 V); LOW <= %.4f V; edge rise %.3f us / fall "
        "%.3f us at %.1f pF (tau %.3f us) against the %.2f us gate RC and the 1 ms tick; at twice the capacitance the edge is "
        "%.3f us"
        % (c["v_in_hi"], c["v_in_hi"] - LVC_VIH_EIB, c["v_in_lo"], c["t_rise"] * 1e6, c["t_fall"] * 1e6, c["c_tot"] * 1e12,
           c["tau"] * 1e6, T_GATE_RC * 1e6, 2 * max(c["t_rise"], c["t_fall"]) * 1e6))
    out("    dissipation: <= %.2f mW shorted, <= %.3f mW in normal HIGH (0603 0.1 W); the normal 3V3 load falls by %.1f uA "
        "(two paths; R9.H15 kept on the 100 ohm basis, conservative)" % (c["p_short"] * 1e3, c["p_norm"] * 1e3, d_load * 1e6))
    out("    sag effect at 3.30 V (CR rail %.4f -> %.4f V): H1 hysteresis %.4f -> %.4f V, UVB fall %.3f -> %.3f V; the pin-34 H1 "
        "readback HIGH exceeds 0.7 x OVDD by >= %.3f V at every Teensy 3V3 corner during the short (the SR-SR-02 undefined "
        "band does not occur; VIH fraction ASSUMPTION, TODO(verify: IMXRT1060CEC))"
        % (v_cr, vs, h1n[0] - h1n[1], h1s[0] - h1s[1], uf, ufs, pin34))
    out("    the larger series R adds a low-pass at the EIB input (tau %.3f us), so the H.13 0.1 / 1 us release-glitch rows are "
        "not worsened; R131A stays 100 ohm (conductor 7 neighbours: key position 6 and ILIM_REL_B 8; a 7-8 short ties one "
        "signal); a double fault 7-8 + 8-9 exposes R131A as in r9 (outside the single-fault scope)" % (c["tau"] * 1e6))
    RJ["h24d"] = dict(selected_ohm=R_SEL, part="4.99k 1% 0603 (R_0603_1608Metric, E96)", feasible_ohm=[lo_r, hi_r],
                      short_mA_max=r4(c["i_max"] * 1e3), cr_rail_min_V=r4(c["v_min"]), sag_max_mV=r4(c["sag_max"] * 1e3),
                      eib_high_min_V=r4(c["v_in_hi"]), eib_low_max_V=r4(c["v_in_lo"]), edge_rise_us=r4(c["t_rise"] * 1e6),
                      edge_fall_us=r4(c["t_fall"] * 1e6), c_total_pF=r4(c["c_tot"] * 1e12), gate_rc_us=r4(T_GATE_RC * 1e6),
                      p_short_mW=r4(c["p_short"] * 1e3), h1_hyst_V=[r4(h1n[0] - h1n[1]), r4(h1s[0] - h1s[1])],
                      uvb_fall_V=[r4(uf), r4(ufs)], pin34_margin_V=r4(pin34), viable=True)


# ======================================================================================================================
# R9.H21(r) (r9-12, audit run 002 ADV-R2-04): FR-41(iii) ramp-step transaction schedule and cadence, and the FR-41(vii)
# hold-deadline resolution on the FR-45 tick grid. Bit conventions copied from round4/calc/r7_calc.py H.23(o) (i2c_bits_write,
# i2c_bits_read, I2C_TBUF, I2C_CAP); the ramp model copied from round3/calc/r3_calc.py H.21(b) ff_ramp(), with the r3 fixed
# 0.5 ms "in force after its tick" replaced by the verified write-ACK instant and a one-step-in-flight rule (the next step
# is computed from the read-back IINDPM_now, FR-41(iii), so it starts only on the first tick after the read-back completes).
H21R_TBUF = {100e3: 4.7e-6, 400e3: 1.3e-6}   # s, t_BUF Sm / Fm (NXP UM10204, not in references/, ASSUMPTION as in r7_calc.py)
H21R_CAP = {100e3: 0.50e-3, 400e3: 0.35e-3}  # s, DOC FR-07 longest-transaction cap (the in-flight wait)
T_HOLD_ACK = {100e3: 1.5e-3, 400e3: 1.0e-3}  # s, DOC FR-41(vii) hold deadline
H21R_RACE = (0.448, 0.706)                   # A, DOC F.3 / H.20 race floor at 18.9 / 23 W, 0.4 mF
T_H1_EARLIEST = 0.74e-3                      # s, DOC F.3 item 2: earliest H1 rise after bus traction reaches zero


def h21r_wbits(n):
    return (2 + n) * 9 + 2


def h21r_rbits(n):
    return (3 + n) * 9 + 3


def h21r_ramp(i_tr0, t_dec, t_ack, t_rb, i0=0.30, aux=0.15, icap=1.20, mff=0.10, draw=0.89, dt=1e-5, tend=0.03):
    t, ii, pend, ifc_max, tz, i_at, next_tick, busy = 0.0, i0, [], 0.0, None, {}, 0.0, -1.0
    while t < tend:
        tr = max(0.0, i_tr0 * (1 - t / t_dec))
        if tr == 0.0 and tz is None:
            tz = t
        for (te, v) in list(pend):
            if t >= te:
                ii = v
                pend.remove((te, v))
        ifc = aux + tr + min(ii, draw)
        ifc_max = max(ifc_max, ifc)
        if t >= next_tick - 1e-12:
            if t >= busy:
                tgt = min(0.90, ii + (icap - mff - ifc))
                if tgt - ii >= 0.05 or tgt < ii:
                    pend.append((t + t_ack, max(0.0, tgt)))
                    busy = t + t_rb
            next_tick += T_TICK
        if tz is not None:
            for k in (T_H1_EARLIEST, 2e-3):
                if k not in i_at and t >= tz + k:
                    i_at[k] = ii
        t += dt
    return ifc_max, i_at


def sec_h21r():
    head("R9.H21(r) FR-41(iii) ramp-step schedule and cadence at 100 / 400 kHz; FR-41(vii) deadline on the FR-45 tick grid "
         "(r9-12, audit run 002 ADV-R2-04)")
    out("  one ramp step = W(REG06:07) %d bits + t_BUF + R(REG01:02) %d bits + t_BUF + R(REG06:07) %d bits (FR-41(iii) 'each "
        "read back'; FR-46 read of REG01:02 and the register just written) = %d bits; worst case behind one in-flight "
        "transaction at the FR-07 cap; IINDPM in force at the write ACK; the next step starts on the first tick after the "
        "read-back" % (h21r_wbits(2), h21r_rbits(2), h21r_rbits(2), h21r_wbits(2) + 2 * h21r_rbits(2)))
    res = {}
    for f in (400e3, 100e3):
        tb, cap = H21R_TBUF[f], H21R_CAP[f]
        w2, r2 = h21r_wbits(2) / f, h21r_rbits(2) / f
        step = w2 + tb + r2 + tb + r2
        t_ack = cap + tb + w2
        t_rb = t_ack + 2 * (tb + r2)
        cad = int(math.ceil(t_rb / T_TICK - 1e-9))
        dl = math.ceil(T_HOLD_ACK[f] / T_TICK - 1e-9) * T_TICK
        lab = "%.0f kHz" % (f / 1e3)
        out("  %s: step %.3f ms alone, %.3f ms behind a capped transaction (ACK at %.3f ms); cadence one step per %d tick(s); "
            "FR-41(vii) T_HOLD_ACK %.1f ms expires at the first FR-45 tick at or after it: %.1f ms after the post"
            % (lab, step * 1e3, (cap + tb + step) * 1e3, t_ack * 1e3, cad, T_HOLD_ACK[f] * 1e3, dl * 1e3))
        rows = {}
        for i_tr0 in (0.30, 0.50, 0.65):
            for t_dec in (2e-3, 5e-3, 10e-3):
                m, a = h21r_ramp(i_tr0, t_dec, t_ack, t_rb)
                rows["%.2f|%.0f" % (i_tr0, t_dec * 1e3)] = (r4(m), r4(a[T_H1_EARLIEST]), r4(a[2e-3]))
        lo = min(v[1] for v in rows.values())
        hi = max(v[1] for v in rows.values())
        lo2 = min(v[2] for v in rows.values())
        mx = max(v[0] for v in rows.values())
        out("    residual traction 0.30-0.65 A over 2-10 ms: IINDPM %.3f-%.3f A at the earliest H1 rise (+%.2f ms), >= %.3f A at "
            "+2 ms; max I_fc %.3f A (I_cap - m_ff 1.10 A); race floor %.3f / %.3f A (18.9 / 23 W, 0.4 mF): %s"
            % (lo, hi, T_H1_EARLIEST * 1e3, lo2, mx, H21R_RACE[0], H21R_RACE[1],
               "held" if lo >= H21R_RACE[1] else "NOT held at the earliest H1 rise"))
        # T4 restore (F.5 T4, ADV-R2-05): edge-posted at the queue head; in-flight term <= the FR-07 cap (a raising write
        # in flight completes, W(REG03-05) 0.470 / 0.117 ms <= cap); step 1 W(REG06:07) + W(REG03:04), then its FR-46 field
        # reads R(REG01:02), R(REG06:07), R(REG03:04); step 2 is a critical section with no bus time; step 3 W(REG05). The
        # step-3 read-back follows after the deadline, as for T3 (H.23(o)). ISR latency is not in the bus budget.
        t4 = cap + tb + w2 + tb + w2 + 3 * (tb + r2) + tb + h21r_wbits(1) / f
        out("    T4 restore, falling edge to the step-3 VINDPM write complete: %.3f ms (in-flight %.2f ms + W(REG06:07) + W(REG03:04) "
            "+ three field reads + W(REG05), t_BUF between; ISR latency excluded)" % (t4 * 1e3, cap * 1e3))
        res["%.0fk" % (f / 1e3)] = dict(step_ms=r4(step * 1e3), step_behind_cap_ms=r4((cap + tb + step) * 1e3), t4_edge_to_step3_ms=r4(t4 * 1e3),
                                        ack_ms=r4(t_ack * 1e3), cadence_ticks=cad, hold_deadline_ms=r4(dl * 1e3),
                                        iindpm_h1_A=[lo, hi], iindpm_2ms_min_A=lo2, ifc_max_A=mx, rows=rows)
    RJ["h21r"] = res


# ======================================================================================================================
def sec_h24b(v_cr):
    head("R9.H24(b) RT1987 EN-net level on pins 27-32 with the pad not driven (INPUT_PULLUP, high-Z, keeper), r9 pull-downs")
    out("  loads (MB .sch: each EN net is the Teensy pad + the RT1987 EN pin; + the 10 kOhm EN-to-GND bodge on every net): bodge "
        "10.0 kOhm +-5 %% (ASSUMPTION), REN_PD 475/730/985 kOhm (RT EC p.7). No CR load remains on pins 27, 28, 29, 30, 32 (T3 and T4 "
        "removed, r9-1); pin 31 keeps the T5 network (R122 -> R186 + R187 3.30 MOhm to the CR rail, R188 + R189 1.453 MOhm to GND). "
        "Band: below VEN_F min %.1f V = off; above VEN_R max %.1f V = on; between = undefined" % (VEN_F_MIN, VEN_R_MAX))

    def cr_thev(vrail):
        vth = vrail * (R188 + R189) / (R187 + R186 + R188 + R189)
        return vth, par(R187 + R186, R188 + R189) + R122

    def en_level(vio, rpu, rb, ren, cr, vrail):
        g = [(vio, rpu)] if rpu else []
        gnd = [rb, ren] if rb else [ren]
        if cr:
            vth, rth = cr_thev(vrail)
            g.append((vth, rth))
        num = sum(v / r for v, r in g)
        den = sum(1 / r for _, r in g) + sum(1 / r for r in gnd)
        return num / den

    def band(v):
        return "off" if v < VEN_F_MIN else ("ON" if v > VEN_R_MAX else "undefined")

    res = {}
    for pin, name, cr in ((27, "FC_BUS_ENABLE (D-FC-EN)", False), (28, "BT_BUS_ENABLE (D-BT-EN)", False),
                          (29, "MOT_PWR_ENABLE (D-MT-EN)", False), (30, "REGEN_ENABLE (D-BC-RG)", False),
                          (31, "FC_CHARGE_ENABLE (D-BC-FC)", True), (32, "BT_SEQUENCE_ENABLE (D-BT-SQ)", False)):
        nomv = en_level(V_IO[1], R_PU[1], R_BODGE[1], REN_PD[1], cr, v_cr)
        lo = min(en_level(V_IO[0], R_PU[2], R_BODGE[0], REN_PD[0], cr, v_cr), en_level(V_IO[0], R_PU[2], R_BODGE[0], REN_PD[0], cr, 3.0))
        hi = max(en_level(V_IO[2], R_PU[0], R_BODGE[2], REN_PD[2], cr, v_cr), en_level(V_IO[2], R_PU[0], R_BODGE[2], REN_PD[2], cr, 3.4))
        hz = (en_level(0, None, R_BODGE[0], REN_PD[0], cr, v_cr), en_level(0, None, R_BODGE[2], REN_PD[2], cr, 3.4))
        pu_open = (en_level(V_IO[0], R_PU[2], None, REN_PD[0], cr, v_cr), en_level(V_IO[2], R_PU[0], None, REN_PD[2], cr, v_cr))
        hz_open = (en_level(0, None, None, REN_PD[0], cr, v_cr), en_level(0, None, None, REN_PD[2], cr, 3.4))
        rload = par(R_BODGE[0], REN_PD[0]) if not cr else par(R_BODGE[0], REN_PD[0], cr_thev(v_cr)[1])
        k06, k14 = VEN_F_MIN / rload, VEN_R_MAX / rload
        res[pin] = dict(pullup_nom_V=r4(nomv), pullup_range_V=[r4(lo), r4(hi)], highz_V=[r4(hz[0]), r4(hz[1])],
                        pullup_bodge_open_V=[r4(pu_open[0]), r4(pu_open[1])], highz_bodge_open_V=[r4(hz_open[0]), r4(hz_open[1])],
                        keeper_uA_for_0V6=r4(k06 * 1e6), keeper_uA_for_1V4=r4(k14 * 1e6))
        out("  pin %d %-28s INPUT_PULLUP: %.3f V nominal (22k, 3.30 V, 10.0k, 730k) = %s; %.3f-%.3f V over the tolerance band "
            "(%s .. %s); high-Z: %.4f-%.4f V (off); INPUT_PULLUP with the bodge open: %.2f-%.2f V (ON); high-Z with the bodge "
            "open: %.3f-%.3f V; a pad keeper must source >= %.0f uA to reach 0.6 V and >= %.0f uA to reach 1.4 V against the 9.5 kOhm "
            "worst load (keeper strength TODO(verify: IMXRT1060RM))"
            % (pin, name, nomv, band(nomv), lo, hi, band(lo), band(hi), hz[0], hz[1], pu_open[0], pu_open[1], hz_open[0],
               hz_open[1], k06 * 1e6, k14 * 1e6))
    # pins 5 and 33 (J.2 item 69): keeper current to hold P5 / QUAL HIGH against the 47 kOhm pull-downs (LVC VIH 2.0 V)
    k5 = 2.0 / R108
    k33 = 2.0 / R123 + 0.0
    out("  related (J.2 item 69): to hold P5 (pin 5) above the LVC VIH 2.0 V against R108 %.1f kOhm a keeper must source >= %.1f uA; "
        "QUAL (pin 33) through R147 against R123: >= %.1f uA (VIH at U107 2.0 V, R147 drop %.2f mV)"
        % (R108 / 1e3, k5 * 1e6, k33 * 1e6, k33 * R147 * 1e3))
    RJ["h24b"] = dict(pins=res, keeper_uA_p5=r4(k5 * 1e6), keeper_uA_p33=r4(k33 * 1e6))
    return res


# ======================================================================================================================
def sec_h24c(v_cr, vol6, fcc, en):
    head("R9.H24(c) Figures quoted in the proposed IO CSV rows of design-document section D.3, against cr.net and the datasheets")
    off_in, off_en, on = fcc
    vbus = 16.0
    rise, fall = h1_trips(vbus, v_cr)
    rise33, fall33 = h1_trips(vbus, 3.3)
    gain = IMON_GAIN[1] * R105
    rs = R105 + R129
    rows = [
        ("5", "47 kOhm pull-down on the carrier", "confirmed", "R108 %s on /CHG_ARM to GND (cr.net)" % CR_COMPS["R108"]),
        ("6", "10 kOhm pull-up to 3V3 on the carrier", "confirmed", "R107 %s from /STAT to /3V3 (cr.net)" % CR_COMPS["R107"]),
        ("6", "1.00 kOhm in series at the EIB", "confirmed", "R275 %s between J201.4 and E7 (eib.net)" % EIB_COMPS["R275"]),
        ("6", "STAT LOW reads ~0.31 V", "confirmed", "%.3f-%.3f V at the r9 CR rail %.3f V (STAT sink 0-80 ohm; R9.H21)" % (vol6[0], vol6[1], v_cr)),
        ("6", "1 Hz blink = fault", "confirmed", "SLUSDV2C Table 7-11 p.48"),
        ("19", "I2C 0x6B", "confirmed", "SLUSDV2C sec 7.3.14 p.53-54, 7-bit address 0x6B"),
        ("19", "MB RSDA/RSCL 2.7 kOhm", "unverifiable", "a PM9 rework value on the MB, not on cr.net; design-document D.1 PM9 and H.16"),
        ("19/20", "WDOG1_B on AD_B1_00 ALT4 / AD_B1_10 ALT1", "unverifiable", "IMXRT1060RM is not in references/"),
        ("21", "EWM_OUT_B AD_B1_11 ALT1", "unverifiable", "TODO(verify: IMXRT1060RM) already in the row"),
        ("22", "27.9 uA/A into 27.4 kOhm = 0.764 V/A", "confirmed", "R105 %s; GAIN(IMON) 27.9 uA/A typ (25.66-30.14, 0.6-2 A only, "
         "tps2663.pdf sec 6.5): %.4f V/A (%.3f-%.3f)" % (CR_COMPS["R105"], gain, IMON_GAIN[0] * R105, IMON_GAIN[2] * R105)),
        ("22", "10 kOhm + 1 nF to the pin", "confirmed", "R129 %s, C129 %s on /CHG_IIN (cr.net)" % (CR_COMPS["R129"], CR_COMPS["C129"])),
        ("22", "37 kOhm source", "confirmed", "R105 + R129 = %.1f kOhm" % (rs / 1e3)),
        ("22", "1 uA of keeper current = 49 mA error", "confirmed", "%.1f mV / %.4f V/A = %.1f mA (keeper current magnitude itself "
         "unverified)" % (rs * 1e-3, gain, rs * 1e-6 / gain * 1e3)),
        ("27/29", "RT1987 EN may turn on anywhere up to 1.4 V", "confirmed", "VEN_R max 1.4 V, VEN_F min 0.6 V (RT1987 EC p.7)"),
        ("28", "INPUT_PULLUP lifts the EN net to ~1.02 V", "confirmed", "%.3f V nominal (R9.H24(b)); %.2f-%.2f V over the tolerance band"
         % (en[28]["pullup_nom_V"], en[28]["pullup_range_V"][0], en[28]["pullup_range_V"][1])),
        ("30", "~0.95 V (INPUT_PULLUP)", "changed", "%.3f V nominal with R133 removed (r8 0.95 V with R133 100 kOhm); %.2f-%.2f V over "
         "the band" % (en[30]["pullup_nom_V"], en[30]["pullup_range_V"][0], en[30]["pullup_range_V"][1])),
        ("31", "FCC_OFF comparator below 0.39-0.44 V", "confirmed", "U119 IN- threshold %.3f-%.3f V; referred to the pin-31 EN net "
         "%.3f-%.3f V (R187 shift)" % (off_in[0], off_in[1], off_en[0], off_en[1])),
        ("31", "FCC_ON comparator above 1.75-1.88 V", "confirmed", "U120 trip %.3f-%.3f V at /FCC (R188 453k / R189 1.00M, own REF)"
         % (on[0], on[1])),
        ("31", "~1.02 V (INPUT_PULLUP)", "confirmed", "%.3f V nominal with the T5 network (R9.H24(b)); %.2f-%.2f V over the band"
         % (en[31]["pullup_nom_V"], en[31]["pullup_range_V"][0], en[31]["pullup_range_V"][1])),
        ("33", "47 kOhm pull-down on the carrier", "confirmed", "R123 %s from /QUAL to GND behind R147 %s (cr.net)"
         % (CR_COMPS["R123"], CR_COMPS["R147"])),
        ("33", "T_QUAL_MAX 0.46 s", "unverifiable", "a firmware constant (r9-7); it equals the retired U111 band maximum 0.46 s of "
         "H.17 and has no r9 hardware basis; T-B-20 sets it"),
        ("34", "HIGH = V-MOT > 1.089 x VBUS", "confirmed", "rise/VBUS %.4f at VBUS 16.0 V (unchanged dividers R109-R112, R170/R171)"
         % (rise / vbus)),
        ("34", "+0.30 V hysteresis", "confirmed", "%.3f V with the U102 output swinging to the r9 CR rail %.3f V (%.3f V at 3.30 V)"
         % (rise - fall, v_cr, rise33 - fall33)),
        ("35", "carrier R106 not fitted", "confirmed", "no R106 on cr.net (R106s is the FLT series resistor)"),
    ]
    for r in rows:
        out("  row %-6s %-48s %-12s %s" % r)
    RJ["h24c"] = [dict(pin=r[0], claim=r[1], verdict=r[2], value=r[3]) for r in rows]
    return rows


# ======================================================================================================================
# H.25 (r9-15, LAYOUT_DECISIONS D-56, placement review r9b N-1/N-2): the VCHGIN L3 strap as the only J1.10 feed
# ======================================================================================================================
H25_I = 2.41            # A: the VCHGIN current basis, the eFuse I_OL maximum (H.5; A.8 Copper "VCHGIN ... <= 2.41 A")
H25_DT = 10.0           # degC: the A.8 Copper / H.22(c) rise basis of the CR power copper ("at 10 C rise")
H25_T_IN = 0.0175       # mm: 0.5 oz inner copper, 17.5 um (D-29 and stackup_fabrules_decisions_2026-11-12.md section 3:
                        # OSH Park 4-layer, 1 oz outer / 0.5 oz inner); finished thickness TODO(verify: OSH Park)
H25_MIL2 = 0.0254 ** 2  # mm2 per mil2
# narrowest strap sections on In2.Cu (vertical cut through the filled VCHGIN_L3_strap at the U101 thermal-via column,
# where the GND via at (42.80, 62.55) cuts the top edge at y 62.1455), board-measured with pcbnew on the D-56 pour stage
H25_NECKS = (("D-55 strap, y 60.15 (pad 10 also fed on L1)", 62.1455 - 60.15),
             ("review r9b trial 4, y 59.55", 62.1455 - 59.55),
             ("D-56 strap, y 58.50 (board-measured section 3.645 mm at x 42.75)", 3.645),
             # D-57 (route-race r9 R9-01): /GND pre-via (42.30, 59.30) cut out of the strap, extension box(41.95,
             # 57.00, 44.00, 58.50) below it; total vertical chord of the fill, board-measured on the D-57 pour stage
             ("D-57 strap, C102c GND via cut-out + extension (4.174 mm at x 42.535)", 4.174))
H25_THERMAL = (4, 0.6)  # superseded J1.10 thermal relief on In2: spokes x width (gen/route.py add_zone)
H25_DRILL = 1.10        # mm: J1 CHG hole (A.8)
H25_VIA = (0.30, 0.020)  # via drill and barrel plating (IPC-6012 class 2 minimum average 20 um, ASSUMPTION;
                         # TODO(verify: OSH Park plating thickness))
H25_VIAS = (("C102c end, D-55 (39.75, 60.35 / 61.05)", 2), ("C102c end, D-56 (+ 39.75, 59.65)", 3))


def ipc2152_area_mil2(i, dt):
    """IPC-2152 baseline chart (Figure 5-1, no modifiers) in a published curve-fit form; area in mil2.
    TODO(verify: IPC-2152 Figure 5-1 chart reading against this fit). No board-thickness or plane modifier is credited
    (the L2 GND plane lies about 0.2 mm from L3 and would lower the rise), so the figure is conservative."""
    return (117.555 * dt ** -0.913 + 1.15) * i ** (0.84 * dt ** -0.018 + 1.159)


def ipc2152_current(a_mil2, dt):
    lo, hi = 0.0, 100.0
    for _ in range(100):
        m = 0.5 * (lo + hi)
        lo, hi = (m, hi) if ipc2152_area_mil2(m, dt) < a_mil2 else (lo, m)
    return lo


def ipc2152_rise(a_mil2, i):
    lo, hi = 0.1, 200.0
    for _ in range(100):
        m = 0.5 * (lo + hi)
        lo, hi = (lo, m) if ipc2152_area_mil2(i, m) < a_mil2 else (m, hi)
    return hi


def ipc2221_current(a_mil2, dt, k):
    return k * dt ** 0.44 * a_mil2 ** 0.725


def sec_h25():
    head("R9.H25 VCHGIN L3 strap as the only J1.10 feed: IPC-2152 inner-layer width, the J1.10 joint and the via count "
         "(r9-15, D-56)")
    a_req = ipc2152_area_mil2(H25_I, H25_DT)
    w_req = a_req * H25_MIL2 / H25_T_IN
    a_2221i = (H25_I / (0.024 * H25_DT ** 0.44)) ** (1 / 0.725)
    a_2221e = (H25_I / (0.048 * H25_DT ** 0.44)) ** (1 / 0.725)
    out("  basis: I = %.2f A (eFuse I_OL max, H.5), rise %.0f degC (A.8 Copper, H.22(c)), inner copper %.1f um (D-29)"
        % (H25_I, H25_DT, H25_T_IN * 1e3))
    out("  required cross-section: IPC-2152 baseline fit %.1f mil2 = %.4f mm2 -> width %.3f mm at %.1f um; comparison "
        "IPC-2221 internal (k 0.024) %.1f mil2 -> %.3f mm, IPC-2221 external (k 0.048) %.1f mil2 -> %.3f mm"
        % (a_req, a_req * H25_MIL2, w_req, H25_T_IN * 1e3, a_2221i, a_2221i * H25_MIL2 / H25_T_IN, a_2221e,
           a_2221e * H25_MIL2 / H25_T_IN))
    necks = []
    for name, w in H25_NECKS:
        a = w * H25_T_IN / H25_MIL2
        i_cap = ipc2152_current(a, H25_DT)
        dt = ipc2152_rise(a, H25_I)
        ok = w >= w_req
        necks.append(dict(case=name, width_mm=r4(w), area_mil2=r4(a), i_cap_A=r4(i_cap), rise_at_I_degC=r4(dt),
                          ipc2221_internal_A=r4(ipc2221_current(a, H25_DT, 0.024)), ok=ok))
        out("  neck %-62s %.3f mm = %5.1f mil2: IPC-2152 %.2f A at %.0f degC, rise %.1f degC at %.2f A; IPC-2221 "
            "internal %.2f A -> %s" % (name, w, a, i_cap, H25_DT, dt, H25_I, ipc2221_current(a, H25_DT, 0.024),
                                       "pass" if ok else "FAIL"))
    # J1.10 barrel to the strap: the copper perimeter that carries the current into L3
    n_sp, w_sp = H25_THERMAL
    w_th = n_sp * w_sp
    w_solid = math.pi * H25_DRILL
    out("  J1.10 joint on In2: thermal relief %d x %.1f mm = %.2f mm of spoke (%s; superseded); solid connection "
        "(D-56): barrel perimeter pi x %.2f mm = %.3f mm -> %s (short-conductor case; the long-conductor chart is "
        "conservative here)" % (n_sp, w_sp, w_th, "pass" if w_th >= w_req else "FAIL", H25_DRILL, w_solid,
                                "pass" if w_solid >= w_req else "FAIL"))
    # via transitions L3 -> L1 at the C102c end
    d, t = H25_VIA
    a_via = math.pi * ((d / 2) ** 2 - (d / 2 - t) ** 2) / H25_MIL2
    i_via = ipc2152_current(a_via, H25_DT)
    vias = []
    for name, n in H25_VIAS:
        ok = n * i_via >= H25_I
        vias.append(dict(case=name, n=n, i_total_A=r4(n * i_via), margin=r4(n * i_via / H25_I), ok=ok))
        out("  vias %-44s %d x %.2f A = %.2f A (%.2f x the basis, equal sharing ASSUMPTION) -> %s"
            % (name, n, i_via, n * i_via, n * i_via / H25_I, "pass" if ok else "FAIL"))
    out("  per via: drill %.2f mm, plating %.0f um, barrel %.1f mil2 (%.4f mm2), IPC-2152 fit %.2f A at %.0f degC; "
        "the C102b-end vias (6) carry the C102b branch only, not the J1.10 DC path"
        % (d, t * 1e3, a_via, a_via * H25_MIL2, i_via, H25_DT))
    RJ["h25"] = dict(I_A=H25_I, rise_degC=H25_DT, t_inner_mm=H25_T_IN, area_req_mil2=r4(a_req), width_req_mm=r4(w_req),
                     width_req_ipc2221_internal_mm=r4(a_2221i * H25_MIL2 / H25_T_IN), necks=necks,
                     j110_thermal_mm=w_th, j110_solid_mm=r4(w_solid), via_A=r4(i_via), vias=vias)


# ======================================================================================================================
def sec_retired():
    head("R9 retired rows (whole subject removed in r9; history only, no re-run)")
    for k, why in (("H.3 BT_OK trip", "U104, R141-R144, taps T8/T9 removed (r9-1)"),
                   ("H.3 BTB_OFF threshold", "U115, R117-R120, tap T3 removed (r9-1); the pin-28 EN levels move to R9.H24(b)"),
                   ("H.4 ILIM sense threshold", "U203, R258-R261 DNP (r9-2); withdrawn in r9-2"),
                   ("H.17 monostables", "U111, U113, R150/C150, R151/C151 removed (r9-1); TW_HB_MAX / TW_QQ_MAX no longer exist"),
                   ("H.20 R264/R265 ribbon drivers", "U203/U204 DNP (r9-2)"),
                   ("H.22 RGN_ON trip and the pin-30 CR load", "U121, R121, R133 removed (r9-1)"),
                   ("H.23(n) F17-F15 bridge, H.23(y) row (1)", "T14 and U108 removed (r9-1, r9-4)"),
                   ("H.23(x) row (3), H.23(y) row (7) r8 increments", "heartbeat U113 and one-shot U111 removed; replaced by the r9 T1 "
                    "increment in R9.H23")):
        out("  %-48s %s" % (k, why))


def main():
    out("r9_calc.py - r9 re-run of the section H checks (change row r9-9). Netlists: %s, %s"
        % (os.path.relpath(CR_NET, REPO), os.path.relpath(EIB_NET, REPO)))
    sec_netlist()
    v_cr, i_cr_only, i_eib = sec_h15_h20()
    sec_h4_h5_h12_h13()
    sec_h19()
    sec_h20_misc()
    vol6 = sec_h21(v_cr)
    sec_h21r()
    fcc = sec_h22(v_cr)
    sec_h23(v_cr)
    sec_h24a(v_cr, i_cr_only, i_eib)
    sec_h24d(v_cr, i_cr_only, i_eib)
    en = sec_h24b(v_cr)
    sec_h24c(v_cr, vol6, fcc, en)
    sec_h25()
    sec_retired()
    with open(OUT_TXT, "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(LINES) + "\n")
    with open(OUT_JSON, "w") as f:
        json.dump(RJ, f, indent=1)


if __name__ == "__main__":
    main()
