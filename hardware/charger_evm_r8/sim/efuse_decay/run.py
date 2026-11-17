"""Sim 5 (efuse_decay): U101 UVLO/OVP band with pin leakage; FR-12(b1) V_chg decay; FR-12(a2) D-MT-EN ratio.

Regenerates every deck, CSV and PNG of this folder:
    C:\\Users\\ricky\\miniforge3\\python.exe run.py

Part A  U101 (TCKE1401NM) UVLO/OVP thresholds of the R102/R103/R104 string with the UVLO/OVP pin leakage:
        datasheet corners (exhaustive) and a Monte Carlo, both solved by ngspice (.dc, two points per copy,
        the network is linear) and cross-checked against the closed-form Thevenin solution.
Part B  Pin-38 V_chg (VCHG-IN) decay after both charger-path EN outputs go LOW (FR-12(b1)): ngspice transients of
        the VCHG-IN node with the pin-38 divider, the UVLO/OVP string, the U101 IN-side current, the EVM-side
        capacitance and standby draw, and the U101 FET body diode (states ON, LATCHED_BD, OVP_START, LATCHED_ISO);
        time to 12.0 V and to 3.0 V and the 0.2-0.4 s slope; an independent ODE model cross-checks every case and
        gives the joint C_evm x I_evm boundary and the RT1987 forward-leakage sensitivity.
Part C  FR-12(a2) D-MT-EN short check: ngspice DC sweep of the RGN-V node (R1-SNT/R2-SNT with the measured knee sink,
        V_rgn doc section 7.1 item 3) and the ratio dV_rgn/dV_bus over the P0-gate -> P2-dwell-end window of
        busBringupTick() for a shorted D-MT-EN, the as-built and repaired node, and the open (healthy) switch.

Every value carries its source in the comment beside it; ASSUMPTION marks a value without a source (it is swept).
Console output is ASCII only.
"""
from __future__ import annotations

import csv
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
from ngspice_run import run_deck, ngspice_version  # noqa: E402

DECKS = os.path.join(HERE, "decks")
OUT = os.path.join(HERE, "results")
os.makedirs(DECKS, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

RNG = np.random.default_rng(20261114)   # fixed seed: the Monte Carlo is reproducible
RNG_F = np.random.default_rng(20261115)  # separate generator for the falling-reference redraws (part A)


class _Tee:
    """Copy stdout to results/console_log.txt (check round, issue 7)."""

    def __init__(self, path):
        self.f = open(path, "w", encoding="ascii", errors="replace", newline="\n")
        self.s = sys.stdout

    def write(self, x):
        self.s.write(x)
        self.f.write(x)
        self.f.flush()

    def flush(self):
        self.s.flush()
        self.f.flush()


def write(path, text):
    with open(path, "w", newline="\n") as f:
        f.write(text)


def write_csv(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def check(r, label):
    if not r.ok:
        print("ERROR in %s:" % label)
        for e in r.errors[:20]:
            print("   ", e)
        raise SystemExit(1)


# =====================================================================================================================
# PART A - U101 UVLO/OVP band
# =====================================================================================================================
# String (hardware/charger_evm_r8/gen/netlist.py): R102 845k 0.1 % VCHGIN-N_UV (line 111), R103 64.9k 0.1 % N_UV-N_OV
# (line 115), R104 51.1k 0.1 % N_OV-GND (line 116). U101 pin 6 = UVLO = N_UV, pin 7 = OVP = N_OV (line 106).
R102, R103, R104 = 845e3, 64.9e3, 51.1e3
RTOL = 0.001
# TCKE1401NM DS Rev. 3.0 Table 10.1 (references/Datasheets/tcke1401nm.pdf p.14), Ta = -40..125 C limits:
VUVLOR = (1.142, 1.19, 1.224)    # min, typ(25 C), max  [V]  UVLO rising
VUVLOF = (1.039, 1.12, 1.15)     # UVLO falling
VOVPR = (1.18, 1.233, 1.298)     # OVP rising
VOVPF = (1.09, 1.15, 1.187)      # OVP falling
I_UVLO = (-320e-9, 8e-9, 320e-9)   # UVLO leak current, 0 V <= VUVLO <= 75 V (typ 8 nA at 25 C)
I_OVP = (-320e-9, 0.0, 320e-9)     # OVP leak current, 0 V <= VOVP <= 4 V (typ 0 nA at 25 C)
# Sign convention used here: a positive leak current flows OUT of the divider node INTO the pin (it loads the node).
# The datasheet does not define the sign, so both signs are covered by the corners and the Monte Carlo.
# Comparison levels (docs/charger_bq25798_wiring_design_2026-11-05.md):
FR30_V = 10.2           # FR-30 / chargerHasPower 10.2 V threshold (B.4 R102 row, line 1954)
DOC_UVR = (9.46, 10.14)  # D-67/B.4 UVLO rising band without leakage
DOC_UVF = (8.61, 9.53)  # F.5 T10 proof (b) UVLO falling band (line 3155)
DOC_OVR = (22.19, 24.41)  # D-67/B.4 OVP rising band
CLAMP = 22.28           # design clamp (B.4 R102 row; FR-12(b1) V0 set)
BQ_VBUS_REC = 24.0      # BQ25798 recommended VBUS maximum (SLUSDV2C 6.3), quoted in B.4
BQ_VBUS_OVP_MIN = 25.2  # BQ25798 VBUS_OVP minimum (B.4, H.15 line 3399)


def thevenin_thresholds(r1, r2, r3, iuv, iov, vr_uv, vr_ov):
    """Closed-form: VIN at which V(N_UV) = vr_uv and V(N_OV) = vr_ov, with pin sink currents iuv, iov."""
    # Node equations: (Vin - Vu)/r1 = (Vu - Vo)/r2 + iuv ; (Vu - Vo)/r2 = Vo/r3 + iov
    # Solve V(N_UV) and V(N_OV) as linear functions of Vin by superposition.
    def nodes(vin):
        g1, g2, g3 = 1 / r1, 1 / r2, 1 / r3
        A = np.array([[g1 + g2, -g2], [-g2, g2 + g3]])
        b = np.array([vin * g1 - iuv, -iov])
        return np.linalg.solve(A, b)
    u0, o0 = nodes(0.0)
    u1, o1 = nodes(1.0)
    vin_uv = (vr_uv - u0) / (u1 - u0)
    vin_ov = (vr_ov - o0) / (o1 - o0)
    return vin_uv, vin_ov


def part_a():
    print("\n=== PART A: U101 UVLO/OVP band with pin leakage ===")
    copies = []   # (label, r102, r103, r104, iuv, iov)
    copies.append(("nominal_noleak", R102, R103, R104, 0.0, 0.0))
    copies.append(("nominal_typleak", R102, R103, R104, I_UVLO[1], I_OVP[1]))
    for s1 in (-1, 1):
        for s2 in (-1, 1):
            for s3 in (-1, 1):
                for lu in (-1, 0, 1):
                    for lo in (-1, 0, 1):
                        copies.append(("corner_r%+d%+d%+d_iu%+d_io%+d" % (s1, s2, s3, lu, lo),
                                       R102 * (1 + s1 * RTOL), R103 * (1 + s2 * RTOL), R104 * (1 + s3 * RTOL),
                                       lu * I_UVLO[2], lo * I_OVP[2]))
    n_mc = 4000
    mc_par = []
    for k in range(n_mc):
        r = R102 * (1 + RNG.uniform(-RTOL, RTOL)), R103 * (1 + RNG.uniform(-RTOL, RTOL)), \
            R104 * (1 + RNG.uniform(-RTOL, RTOL))
        iu, io = RNG.uniform(I_UVLO[0], I_UVLO[2]), RNG.uniform(I_OVP[0], I_OVP[2])
        refs = (RNG.uniform(VUVLOR[0], VUVLOR[2]), RNG.uniform(VUVLOF[0], VUVLOF[2]),
                RNG.uniform(VOVPR[0], VOVPR[2]), RNG.uniform(VOVPF[0], VOVPF[2]))
        # Physical constraint (check round, issue 6): a falling reference cannot exceed its rising reference.
        # Table 10.1 gives no hysteresis limits (section 7.4 states 70 mV typ for UVLO only; the VSEL_UVLO/VSEL_OVP
        # rows are the internal-threshold select levels, not hysteresis), so a falling draw above its rising draw
        # is redrawn uniformly within [falling min, rising draw) from a separate generator. The rising draws, and
        # therefore every rising-threshold statistic, are unchanged.
        fu, fo = refs[1], refs[3]
        if fu >= refs[0]:
            fu = RNG_F.uniform(VUVLOF[0], refs[0])
        if fo >= refs[2]:
            fo = RNG_F.uniform(VOVPF[0], refs[2])
        refs = (refs[0], fu, refs[2], fo)
        copies.append(("mc%04d" % k,) + r + (iu, io))
        mc_par.append(refs)
    lines = ["* Sim 5 part A: TCKE1401NM UVLO/OVP string R102/R103/R104 with pin leak currents",
             "* generated by efuse_decay/run.py; %d copies share VIN; .dc at 10 V and 20 V (linear network)" % len(copies),
             "VIN vin 0 DC 10"]
    for i, (lab, r1, r2, r3, iu, io) in enumerate(copies):
        lines.append("* copy %d: %s" % (i, lab))
        lines.append("R102_%d vin uv%d %.9g" % (i, i, r1))
        lines.append("R103_%d uv%d ov%d %.9g" % (i, i, i, r2))
        lines.append("R104_%d ov%d 0 %.9g" % (i, i, r3))
        lines.append("IUV_%d uv%d 0 DC %.6e" % (i, i, iu))   # positive: current leaves the node into the pin
        lines.append("IOV_%d ov%d 0 DC %.6e" % (i, i, io))
    lines += [".dc VIN 10 20 10", ".end"]
    deck = "\n".join(lines) + "\n"
    write(os.path.join(DECKS, "a_uvlo_ovp_string.cir"), deck)
    r = run_deck(deck)
    check(r, "part A")
    res = []
    max_err = 0.0
    for i, (lab, r1, r2, r3, iu, io) in enumerate(copies):
        u = r["uv%d" % i]
        o = r["ov%d" % i]
        au, bu = (u[1] - u[0]) / 10.0, u[0] - 10.0 * (u[1] - u[0]) / 10.0
        ao, bo = (o[1] - o[0]) / 10.0, o[0] - 10.0 * (o[1] - o[0]) / 10.0
        res.append((lab, au, bu, ao, bo))
        # analytic cross-check at the typical references
        th_u, th_o = thevenin_thresholds(r1, r2, r3, iu, io, VUVLOR[1], VOVPR[1])
        max_err = max(max_err, abs((VUVLOR[1] - bu) / au - th_u), abs((VOVPR[1] - bo) / ao - th_o))
    print("ngspice vs closed form, max threshold difference over %d copies: %.3e V" % (len(copies), max_err))

    def thr(a, b, ref):
        return (ref - b) / a

    # corners: every resistor/leak corner x reference min/max
    corner_rows = []
    band = {}
    for key, idx, refs in (("UVLO_rise", 0, VUVLOR), ("UVLO_fall", 0, VUVLOF), ("OVP_rise", 1, VOVPR),
                           ("OVP_fall", 1, VOVPF)):
        for leak_on in (False, True):
            vals = []
            for (lab, au, bu, ao, bo) in res:
                if not lab.startswith("corner"):
                    continue
                if not leak_on and ("iu+0_io+0" not in lab):
                    continue
                a, b = (au, bu) if idx == 0 else (ao, bo)
                for ref in (refs[0], refs[2]):
                    vals.append(thr(a, b, ref))
            band[(key, leak_on)] = (min(vals), max(vals))
        nom = [x for x in res if x[0] == "nominal_noleak"][0]
        typl = [x for x in res if x[0] == "nominal_typleak"][0]
        a, b = (nom[1], nom[2]) if idx == 0 else (nom[3], nom[4])
        a2, b2 = (typl[1], typl[2]) if idx == 0 else (typl[3], typl[4])
        corner_rows.append((key, "%.4f" % thr(a, b, refs[1]), "%.4f" % thr(a2, b2, refs[1]),
                            "%.4f" % band[(key, False)][0], "%.4f" % band[(key, False)][1],
                            "%.4f" % band[(key, True)][0], "%.4f" % band[(key, True)][1]))
    write_csv("a_bands_corners.csv",
              ["threshold", "typ_noleak_V", "typ_typleak25C_V", "corner_min_noleak_V", "corner_max_noleak_V",
               "corner_min_leak320nA_V", "corner_max_leak320nA_V"], corner_rows)
    for row in corner_rows:
        print("  %-10s typ %s V (typ leak %s V); no leak %s-%s V; with +-320 nA %s-%s V" % row)

    # Monte Carlo
    mc = np.array([[thr(au, bu, p[0]), thr(au, bu, p[1]), thr(ao, bo, p[2]), thr(ao, bo, p[3])]
                   for (lab, au, bu, ao, bo), p in zip([x for x in res if x[0].startswith("mc")], mc_par)])
    names = ["UVLO_rise", "UVLO_fall", "OVP_rise", "OVP_fall"]
    mc_rows = []
    for j, nm in enumerate(names):
        x = mc[:, j]
        mc_rows.append((nm, "%.4f" % x.min(), "%.4f" % np.percentile(x, 0.135), "%.4f" % np.median(x),
                        "%.4f" % np.percentile(x, 99.865), "%.4f" % x.max()))
    p_uv_fr30 = float(np.mean(mc[:, 0] > FR30_V))
    p_ov_clamp = float(np.mean(mc[:, 2] < CLAMP))
    p_ov_24 = float(np.mean(mc[:, 2] > BQ_VBUS_REC))
    p_ov_252 = float(np.mean(mc[:, 2] > BQ_VBUS_OVP_MIN))
    write_csv("a_bands_montecarlo.csv", ["threshold", "min_V", "p0.135_V", "median_V", "p99.865_V", "max_V"], mc_rows)
    write_csv("a_mc_samples.csv", ["UVLO_rise_V", "UVLO_fall_V", "OVP_rise_V", "OVP_fall_V"],
              [["%.5f" % v for v in row] for row in mc])
    write_csv("a_mc_probabilities.csv", ["event", "fraction_of_4000"],
              [("UVLO_rise > 10.2 V (FR-30)", "%.4f" % p_uv_fr30), ("OVP_rise < 22.28 V (clamp)", "%.4f" % p_ov_clamp),
               ("OVP_rise > 24.0 V (BQ25798 rec. VBUS max)", "%.4f" % p_ov_24),
               ("OVP_rise > 25.2 V (BQ25798 VBUS_OVP min)", "%.4f" % p_ov_252)])
    print("  MC (uniform within limits, n=4000): P(UVLO_rise>10.2)=%.3f  P(OVP_rise<22.28)=%.3f  "
          "P(OVP_rise>24.0)=%.3f  P(OVP_rise>25.2)=%.3f" % (p_uv_fr30, p_ov_clamp, p_ov_24, p_ov_252))
    # leakage-only sensitivity at the nominal string and typical references
    nom = [x for x in res if x[0] == "nominal_noleak"][0]
    sens_u = 320e-9 * (R102 * (R103 + R104) / (R102 + R103 + R104)) / nom[1]   # first-order estimate, for the text
    # plot
    fig, axs = plt.subplots(2, 2, figsize=(10, 7))
    lims = {0: [(FR30_V, "FR-30 10.2 V"), (DOC_UVR[0], "D-67 band"), (DOC_UVR[1], None)],
            1: [(DOC_UVF[0], "doc band"), (DOC_UVF[1], None)],
            2: [(CLAMP, "22.28 V clamp"), (BQ_VBUS_REC, "BQ 24 V rec."), (BQ_VBUS_OVP_MIN, "BQ OVP 25.2 V min"),
                (DOC_OVR[0], "D-67 band"), (DOC_OVR[1], None)],
            3: []}
    for j, ax in enumerate(axs.flat):
        ax.hist(mc[:, j], bins=60, color="#4C72B0", alpha=0.8, label="Monte Carlo (n=4000)")
        lo, hi = band[(names[j], True)]
        ax.axvspan(lo, hi, color="#DD8452", alpha=0.15, label="corner band, +-320 nA")
        lo2, hi2 = band[(names[j], False)]
        ax.axvspan(lo2, hi2, color="#55A868", alpha=0.2, label="corner band, no leakage")
        for v, lab in lims[j]:
            ax.axvline(v, color="k" if lab and "D-67" not in lab and "doc" not in lab else "grey",
                       ls="--" if lab and ("D-67" in lab or "doc" in lab) or lab is None else "-", lw=1)
            if lab:
                ax.text(v, ax.get_ylim()[1] * 0.95, " " + lab, rotation=90, va="top", fontsize=7)
        ax.set_title(names[j].replace("_", " "))
        ax.set_xlabel("VCHG-IN threshold (V)")
        ax.set_ylabel("count")
    axs[0, 0].legend(fontsize=7, loc="upper left")
    fig.suptitle("U101 TCKE1401NM UVLO/OVP thresholds, R102/R103/R104 0.1 %, Table 10.1 limits")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "a_uvlo_ovp_bands.png"), dpi=130)
    plt.close(fig)
    return dict(band=band, mc=mc, p=(p_uv_fr30, p_ov_clamp, p_ov_24, p_ov_252), max_err=max_err, sens_u=sens_u)


# =====================================================================================================================
# PART B - FR-12(b1) pin-38 V_chg decay
# =====================================================================================================================
# VCHG-IN capacitance (IN side of U101): C-D8 10 uF + C-D10 10 uF (references/Scale_Car_Board_20260624.sch lines 5924,
# 5935, 0805, 35 V per the design doc) + C102a 1 uF (netlist.py:95) + C102b 4.7 uF (:96) + C102c 0.1 uF (:98)
# = 25.8 uF nominal; effective range 0.66x-1.10x = 17.0-28.4 uF (H.23(q) basis, r7_calc.py:5828-5830 ASSUMPTION,
# reused unchanged here; the upper value is the slow corner).
C_IN = (17.0e-6, 28.4e-6)
# Pin-38 divider R1-CHG 78.7k + R2-CHG 10k (Scale_Car_Board_20260624.sch lines 5976-5977) = 88.7 kOhm.
R_DIV38 = 88.7e3
R_STR = R102 + R103 + R104        # 961.0 kOhm (netlist.py:111-116)
RP = 1 / (1 / R_DIV38 + 1 / R_STR)  # 81.2 kOhm
# U101 IN-side current, TCKE1401NM DS Rev. 3.0 Table 10.1: IQ (ON state, VEN = 2 V) 0.5 mA typ, 1.2 mA max, no min;
# IQ(OFF) (VEN = 0 V) 41 uA typ, 79 uA max. No figure exists for the latched state or for UVLO/OVP. EN (pin 12) is
# open on the CR (netlist.py:105-108, internally pulled up), so the OFF state does not occur on the board; IQ(OFF) is
# used only as a candidate value for the unspecified latched-state current (review PWR-1).
IQ_ON = (0.0, 0.5e-3, 1.2e-3)
IQ_LATCH_SET = (0.0, 41e-6, 79e-6, 0.5e-3, 1.2e-3)
# EVM side: capacitance 51.4 uF nominal (EVM C11/C12/C29/C30/C31 5 x 10 uF + 4 x 0.1 uF + CR C103 1 uF; design doc
# B.4 C101 row, SLUUCB5E Fig 4-5 / Table 4-1). Effective fraction at 12-22 V: ASSUMPTION 0.40-1.00 (DC bias of 10 uF
# MLCCs; the doc says "effective value ... from T-A-04"), swept.
C_EVM_NOM = 51.4e-6
C_EVM_FRAC = (0.40, 1.00)
# EVM standby draw from VBUS with the charger not converting (design doc H.15 line 3390 itemisation):
#   FLOOR: BQ25798 ISD_VBUS 386 uA (SLUSDV2C 6.5, VBUS = 15 V, HIZ, ADC off, ACDRV off; a TYPICAL value with no
#          minimum, specified for "no battery") + D103 leakage 5 uA (H.15) = 0.391 mA.
#   TYP  : ILIM_HIZ held, REGN on: BQ25798 0.39 mA + EVM TS bias 0.39 mA + REGN pull-ups 0.30 mA (H.15) = 1.08 mA.
#   MAX  : BQ25798 1.0 mA + ADC adder 0.52 mA + TS 0.39 mA + pull-ups 0.30 mA + D103 0.10 mA (H.15) = 2.31 mA.
#   Below the floor (check round, issue 2): 0, 0.1 and 0.2 mA. ASSUMPTION: no datasheet minimum exists, so the draw
#   is swept down to zero.
I_EVM = {"zero": 0.0, "0.1mA": 0.1e-3, "0.2mA": 0.2e-3, "floor": 0.391e-3, "typ": 1.08e-3, "max": 2.31e-3}
# U101 internal FET body diode (check round, issue 1). TCKE1401NM DS Rev. 3.0 section 7.6 and Figure 7.1 (right): with
# VSYS tied to VIN and BGATE/DRV open (the CR wiring, netlist.py U101 row; cr.net /VCHGIN) there is no reverse-current
# blocking; the protection table (Note 6) assigns reverse-current protection to the external MOSFET only. The internal
# N-channel FET therefore conducts VOUT -> VIN through its body diode whenever VOUT exceeds VIN by a diode drop, in
# every state (ON below UVLO, latched, OVP). The datasheet gives no body-diode data: ASSUMPTION Vf 0.40-0.70 V at
# 1 mA (ideality 1, 27 C), swept.
VF_SET = (0.40, 0.55, 0.70)
VT27 = 8.617333262e-5 * 300.15
V0_SET = (12.5, 16.0, 19.38, 22.28)   # FR-12(b1) / T-C-04 start voltages (design doc line 3534)
V_CRIT = 12.0
DWELLS = (0.5, 1.5)                   # FR-12(b1) dwell and its 1.5 s fallback
UVLOF_TYP = 961.0 / 116.0 * VUVLOF[1]   # 9.28 V: the FET opens below this
UVLOR_TYP = 961.0 / 116.0 * VUVLOR[1]   # 9.86 V
# OVP-start case (check round, issue 5): at V0 = 22.28 V the OVP rising band (part A, 21.588-25.019 V) admits a unit
# that is in OVP, FET open, until VCHG-IN falls below its OVP falling threshold. Two falling thresholds below 22.28 V:
# the corner minimum and the typical value (from part A; the corner maximum 22.93 V lies above 22.28 V).
OVPF_TYP = R_STR / R104 * VOVPF[1]      # 21.627 V
V_BUS_IDLE = 15.9                       # Idle bus (CLAUDE.md section 6): VIN of D-BC-FC; V-MOT ~ bus for D-BC-RG
# RT1987 forward off-state leakage VIN -> VOUT into VCHG-IN (check round, issue 4): unspecified (RT1987_DS-00 EC gives
# IOUT_LK 45 typ / 60 max uA only at VOUT = 32 V, VIN = 0 V, EN = 0, i.e. a current INTO VOUT). ASSUMPTION sweep of a
# sourcing current per device x 2 devices, active while VCHG-IN < V_BUS_IDLE. Evaluated with the ODE model only.
I_SRC_SET = (0.0, 10e-6, 20e-6, 45e-6, 90e-6, 120e-6)
LSB38 = 3.3 * 88.7 / 10 / 4095          # 7.15 mV per count at pin 38 (SCALE_V_CHG assumed = R1-CHG/R2-CHG divider)


def b_cases(ovpf_set):
    cases = []
    for v0 in V0_SET:
        for cin in C_IN:
            for fr in C_EVM_FRAC:
                for ik, iev in I_EVM.items():
                    for vf in VF_SET:
                        for iq in IQ_ON:
                            cases.append(dict(state="ON", v0=v0, cin=cin, cevm=C_EVM_NOM * fr, cevm_frac=fr,
                                              ievm=iev, ievm_key=ik, iq=iq, vf=vf, ovpf=float("nan")))
                        for iq in IQ_LATCH_SET:
                            cases.append(dict(state="LATCHED_BD", v0=v0, cin=cin, cevm=C_EVM_NOM * fr, cevm_frac=fr,
                                              ievm=iev, ievm_key=ik, iq=iq, vf=vf, ovpf=float("nan")))
                        if v0 == 22.28:
                            for ov in ovpf_set:
                                for iq in IQ_ON:
                                    cases.append(dict(state="OVP_START", v0=v0, cin=cin, cevm=C_EVM_NOM * fr,
                                                      cevm_frac=fr, ievm=iev, ievm_key=ik, iq=iq, vf=vf, ovpf=ov))
            for iq in IQ_LATCH_SET:
                cases.append(dict(state="LATCHED_ISO", v0=v0, cin=cin, cevm=0.0, cevm_frac=0.0, ievm=0.0,
                                  ievm_key="-", iq=iq, vf=float("nan"), ovpf=float("nan")))
    return cases


def diode_is(vf):
    return 1e-3 / (math.exp(vf / VT27) - 1.0)


def b_deck(cases, title, tstop=40.0):
    w = 0.05
    L = ["* Sim 5 part B: VCHG-IN decay after FC_CHARGE and REGEN EN go LOW (FR-12(b1)); %s" % title,
         "* generated by efuse_decay/run.py; %d independent copies; node in<k> = VCHG-IN (pin-38 sense), evm<k> = U101"
         " VOUT / EVM VBUS" % len(cases),
         "* States: ON = FET closed above UVLO (typ %.3f/%.3f V); LATCHED_BD = FET open, body diode VOUT->VIN;"
         % (UVLOR_TYP, UVLOF_TYP),
         "* OVP_START = FET open until VCHG-IN < OVP falling, then as ON; LATCHED_ISO = IN side alone (EVM side"
         " already below VIN)",
         "* Body diode: TCKE1401NM DS 7.6 / Fig 7.1 right (no reverse blocking with VSYS=VIN, BGATE/DRV open);"
         " Vf at 1 mA ASSUMPTION",
         ".model swu sw vt=%.4f vh=%.4f ron=0.0445 roff=1e9" % ((UVLOR_TYP + UVLOF_TYP) / 2,
                                                              (UVLOR_TYP - UVLOF_TYP) / 2),
         # OVP switch: control = OVPF - v(in); closes when v(in) < OVPF, reopens only above OVPF + 2*vh (vh 0.75 V,
         # about half the typical OVP hysteresis at VIN, 23.19 - 21.63 V); instance starts OFF (unit in OVP).
         ".model swo sw vt=-0.75 vh=0.75 ron=0.0445 roff=1e9"]
    for vf in VF_SET:
        L.append(".model dbd%03d d is=%.6e n=1" % (round(vf * 1000), diode_is(vf)))
    for k, c in enumerate(cases):
        L.append("* case %d: %s V0=%.2f Cin=%.1fu Cevm=%.1fu Ievm=%.3fm IQ=%.4fm Vf=%.2f OVPF=%.3f" %
                 (k, c["state"], c["v0"], c["cin"] * 1e6, c["cevm"] * 1e6, c["ievm"] * 1e3, c["iq"] * 1e3,
                  c["vf"], c["ovpf"]))
        L.append("Cin%d in%d 0 %.6e IC=%.4f" % (k, k, c["cin"], c["v0"]))
        L.append("Rdiv%d in%d 0 %.6g" % (k, k, R_DIV38))
        L.append("Rstr%d in%d 0 %.6g" % (k, k, R_STR))
        if c["iq"] > 0:
            # U101 IN-side current, constant above the 4.7 V operating minimum (Table 9.1), tapering below it
            L.append("Biq%d in%d 0 I = %.6e*0.5*(1+tanh((v(in%d)-4.7)/%.3f))" % (k, k, c["iq"], k, w * 4))
        if c["state"] == "LATCHED_ISO":
            continue
        L.append("Cev%d evm%d 0 %.6e IC=%.4f" % (k, k, c["cevm"], c["v0"]))
        if c["ievm"] > 0:
            # EVM standby draw, constant above ~3.5 V (BQ25798 VBUS UVLO region), tapering below
            L.append("Bev%d evm%d 0 I = %.6e*0.5*(1+tanh((v(evm%d)-3.5)/%.3f))" % (k, k, c["ievm"], k, w * 4))
        L.append("Dbd%d evm%d in%d dbd%03d" % (k, k, k, round(c["vf"] * 1000)))
        if c["state"] == "ON":
            L.append("S%d in%d evm%d in%d 0 swu" % (k, k, k, k))
        elif c["state"] == "OVP_START":
            L.append("S%d in%d mid%d in%d 0 swu" % (k, k, k, k))
            L.append("Cm%d mid%d 0 1p IC=%.4f" % (k, k, c["v0"]))
            L.append("Bovc%d ovc%d 0 V = %.5f - v(in%d)" % (k, k, c["ovpf"], k))
            L.append("So%d mid%d evm%d ovc%d 0 swo OFF" % (k, k, k, k))
    L.append(".tran 2m %g uic" % tstop)
    for k in range(len(cases)):
        L.append(".meas tran t12_%d WHEN v(in%d)=12 FALL=1" % (k, k))
        L.append(".meas tran t3_%d WHEN v(in%d)=3 FALL=1" % (k, k))
        L.append(".meas tran va_%d FIND v(in%d) AT=0.2" % (k, k))
        L.append(".meas tran vb_%d FIND v(in%d) AT=0.4" % (k, k))
    L.append(".options reltol=1e-4 temp=27 tnom=27")
    L.append(".end")
    return "\n".join(L) + "\n"


def b_ode_t(c, vstop=V_CRIT, i_src=0.0, tmax=60.0):
    """Independent ODE model of one case (scipy, Radau): time for VCHG-IN to fall to vstop.

    Same physics as the deck above 4.7 V: ON = one node (FET closed); LATCHED_BD = two nodes with the exponential body
    diode; OVP_START = two nodes until VCHG-IN < OVPF, then charge sharing and one node; LATCHED_ISO = IN node alone.
    i_src: RT1987 forward leakage sourced into VCHG-IN while VCHG-IN < V_BUS_IDLE (sensitivity only).
    """
    from scipy.integrate import solve_ivp
    v0 = c["v0"]
    if v0 <= vstop:
        return 0.0
    iq, iev, cin, cev = c["iq"], c["ievm"], c["cin"], c["cevm"]

    def src(v):
        return i_src * 0.5 * (1 + math.tanh((V_BUS_IDLE - v) / 0.01)) if i_src > 0 else 0.0

    def joined(t0, vstart):
        ct = cin + cev
        if i_src == 0.0:
            return t0 + ct * RP * math.log((vstart + (iq + iev) * RP) / (vstop + (iq + iev) * RP))
        ev = lambda t, y: y[0] - vstop
        ev.terminal, ev.direction = True, -1
        s = solve_ivp(lambda t, y: [(-y[0] / RP - iq - iev + src(y[0])) / ct], (0, tmax), [vstart], events=ev,
                      rtol=1e-10, atol=1e-10, max_step=0.01)
        return t0 + (s.t_events[0][0] if len(s.t_events[0]) else float("inf"))

    if c["state"] == "ON":
        return joined(0.0, v0)
    if c["state"] == "LATCHED_ISO":
        if i_src == 0.0:
            return cin * RP * math.log((v0 + iq * RP) / (vstop + iq * RP))
        cev = 0.0
        iev = 0.0
        return joined(0.0, v0)
    isd = diode_is(c["vf"])

    def idiode(vin, vev):
        x = min((vev - vin) / VT27, 200.0)
        return isd * (math.exp(x) - 1.0)

    def f(t, y):
        vin, vev = y
        idd = idiode(vin, vev)
        # same low-voltage tapers as the deck (IQ below 4.7 V, I_evm below 3.5 V): the EVM node can fall far
        # below VCHG-IN while the FET is open (OVP_START with a high EVM draw)
        tq = 0.5 * (1 + math.tanh((vin - 4.7) / 0.2))
        te = 0.5 * (1 + math.tanh((vev - 3.5) / 0.2))
        return [(-vin / RP - iq * tq + idd + src(vin)) / cin, (-iev * te - idd) / cev]

    def jac(t, y):
        vin, vev = y
        x = min((vev - vin) / VT27, 200.0)
        g = isd * math.exp(x) / VT27
        return [[(-1 / RP - g) / cin, g / cin], [g / cev, -g / cev]]

    evs = []
    e12 = lambda t, y: y[0] - vstop
    e12.terminal, e12.direction = True, -1
    evs.append(e12)
    if c["state"] == "OVP_START":
        eo = lambda t, y: y[0] - c["ovpf"]
        eo.terminal, eo.direction = True, -1
        evs.append(eo)
    s = solve_ivp(f, (0, tmax), [v0, v0], method="Radau", jac=jac, events=evs, rtol=1e-9, atol=1e-9)
    if len(s.t_events[0]):
        return s.t_events[0][0]
    if c["state"] == "OVP_START" and len(s.t_events[1]):
        t1 = s.t_events[1][0]
        vin1, vev1 = s.y_events[1][0]
        vsh = (cin * vin1 + cev * vev1) / (cin + cev)
        if vsh <= vstop:
            return t1
        return joined(t1, vsh)
    return float("inf")


def part_b(a):
    print("\n=== PART B: FR-12(b1) pin-38 V_chg decay ===")
    ovpf_set = (round(a["band"][("OVP_fall", True)][0], 3), round(OVPF_TYP, 3))
    cases = b_cases(ovpf_set)
    for fn in os.listdir(DECKS):
        if fn.startswith("b_") and fn.endswith(".cir"):
            os.remove(os.path.join(DECKS, fn))
    chunk = 400
    nchunks = (len(cases) + chunk - 1) // chunk
    for j in range(nchunks):
        sub = cases[j * chunk:(j + 1) * chunk]
        deck = b_deck(sub, "chunk %d of %d (cases %d-%d)" % (j + 1, nchunks, j * chunk, j * chunk + len(sub) - 1))
        write(os.path.join(DECKS, "b_vchg_decay_%02d.cir" % (j + 1)), deck)
        r = run_deck(deck, vectors=["time"])
        check(r, "part B chunk %d" % (j + 1))
        for k, c in enumerate(sub):
            t12 = r.meas.get("t12_%d" % k, float("nan"))
            t3 = r.meas.get("t3_%d" % k, float("nan"))
            if c["v0"] <= V_CRIT:
                t12 = 0.0
            if not np.isfinite(t12):
                t12 = float("inf")
            if not np.isfinite(t3):
                t3 = float("inf")
            va, vb = r.meas.get("va_%d" % k, float("nan")), r.meas.get("vb_%d" % k, float("nan"))
            c.update(t12=t12, t3=t3, va=va, vb=vb, slope=(vb - va) / 0.2)
    print("  %d cases in %d decks" % (len(cases), nchunks))
    # independent ODE cross-check of every case's t(12 V)
    max_rel = {}
    max_abs = {}
    for c in cases:
        ta = b_ode_t(c)
        c["t12_ode"] = ta
        if np.isfinite(c["t12"]) and c["t12"] > 0:
            # relative difference for t >= 0.05 s; below that the 2 ms print step dominates, so the absolute
            # difference is tracked separately
            if ta >= 0.05:
                rel = abs(c["t12"] - ta) / ta
                max_rel[c["state"]] = max(max_rel.get(c["state"], 0.0), rel)
            else:
                max_abs[c["state"]] = max(max_abs.get(c["state"], 0.0), abs(c["t12"] - ta))
    for st, v in max_rel.items():
        print("  ngspice vs independent model t(12 V), %-11s max relative difference (t >= 50 ms): %.2e; "
              "max absolute difference (t < 50 ms): %.2e s" % (st, v, max_abs.get(st, 0.0)))
    rows = []
    for c in cases:
        rows.append((c["state"], "%.2f" % c["v0"], "%.1f" % (c["cin"] * 1e6), "%.2f" % c["cevm_frac"],
                     "%.1f" % (c["cevm"] * 1e6), c["ievm_key"], "%.3f" % (c["ievm"] * 1e3), "%.3f" % (c["iq"] * 1e3),
                     "%.2f" % c["vf"], "%.3f" % c["ovpf"], "%.4f" % c["t12"], "%.4f" % c["t12_ode"],
                     "%.3f" % c["t3"], "%.3f" % c["slope"],
                     "PASS" if c["t12"] <= 0.5 else "FAIL", "PASS" if c["t12"] <= 1.5 else "FAIL"))
    write_csv("b_decay_cases.csv",
              ["state", "V0_V", "C_in_uF", "C_evm_frac", "C_evm_uF", "I_evm_case", "I_evm_mA", "IQ_U101_mA",
               "Vf_bodydiode_V", "OVPF_V", "t_to_12V_s_ngspice", "t_to_12V_s_odemodel", "t_to_3V_s",
               "slope_0p2_0p4s_Vps", "dwell_0p5s", "dwell_1p5s"], rows)

    # summaries: per state and V0, all I_evm, and I_evm >= floor (the H.15 itemisation)
    summ = []
    needed = {}
    for st in ("ON", "LATCHED_BD", "OVP_START", "LATCHED_ISO"):
        for v0 in V0_SET:
            for sub, tag in ((lambda c: True, "all I_evm"), (lambda c: c["ievm"] >= 0.391e-3 or
                                                               c["state"] == "LATCHED_ISO", "I_evm >= floor")):
                sel = [c for c in cases if c["state"] == st and c["v0"] == v0 and sub(c)]
                if not sel:
                    continue
                worst = max(sel, key=lambda c: c["t12"])
                tmax = worst["t12"]
                needed[(st, v0, tag)] = tmax
                summ.append((st, "%.2f" % v0, tag, "%.3f" % min(c["t12"] for c in sel), "%.3f" % tmax,
                             "%d/%d" % (sum(c["t12"] > 0.5 for c in sel), len(sel)),
                             "%d/%d" % (sum(c["t12"] > 1.5 for c in sel), len(sel)),
                             "Cin %.1fu Cevm %.1fu Ievm %.3fm IQ %.3fm Vf %.2f OVPF %.3f" % (
                                 worst["cin"] * 1e6, worst["cevm"] * 1e6, worst["ievm"] * 1e3, worst["iq"] * 1e3,
                                 worst["vf"], worst["ovpf"])))
                print("  %-11s V0 %5s V %-14s t(12 V) %s-%s s; >0.5 s in %s, >1.5 s in %s; worst: %s" % summ[-1])
    write_csv("b_decay_summary.csv", ["state", "V0_V", "I_evm_subset", "t12_min_s", "t12_max_s", "cases_over_0p5s",
                                      "cases_over_1p5s", "worst_case"], summ)

    # FR-12(b2): time to 3 V
    t3rows = []
    for st in ("ON", "LATCHED_BD", "OVP_START", "LATCHED_ISO"):
        for sub, tag in ((lambda c: True, "all I_evm"), (lambda c: c["ievm"] >= 0.391e-3 or
                                                         c["state"] == "LATCHED_ISO", "I_evm >= floor")):
            sel = [c for c in cases if c["state"] == st and sub(c)]
            worst = max(sel, key=lambda c: c["t3"])
            t3rows.append((st, tag, "%.3f" % worst["t3"], "%d/%d" % (sum(c["t3"] > 5.0 for c in sel), len(sel)),
                           "%d/%d" % (sum(c["t3"] > 6.5 for c in sel), len(sel)),
                           "V0 %.2f Cin %.1fu Cevm %.1fu Ievm %.3fm IQ %.3fm Vf %.2f" % (
                               worst["v0"], worst["cin"] * 1e6, worst["cevm"] * 1e6, worst["ievm"] * 1e3,
                               worst["iq"] * 1e3, worst["vf"])))
            print("  t(3 V) %-11s %-14s worst %s s; >5 s %s; >6.5 s %s; %s" % t3rows[-1])
    write_csv("b_t3_summary.csv", ["state", "I_evm_subset", "t3_max_s", "cases_over_5s", "cases_over_6p5s",
                                   "worst_case"], t3rows)

    # break-even constant current (one-node closed form, FET closed: ON) and latched without EVM side
    be = []
    for dwell in DWELLS:
        for v0 in V0_SET[1:]:
            for label, ctot in (("LATCHED_ISO Cin 28.4u", C_IN[1]),
                                ("ON Cin 28.4u + Cevm 51.4u", C_IN[1] + C_EVM_NOM),
                                ("ON Cin 28.4u + Cevm 20.6u", C_IN[1] + C_EVM_NOM * 0.4)):
                lo, hi = 0.0, 20e-3
                for _ in range(60):
                    mid = 0.5 * (lo + hi)
                    t = ctot * RP * math.log((v0 + mid * RP) / (V_CRIT + mid * RP))
                    if t <= dwell:
                        hi = mid
                    else:
                        lo = mid
                be.append(("%.1f" % dwell, "%.2f" % v0, label, "%.4f" % (hi * 1e3)))
    write_csv("b_breakeven_current.csv", ["dwell_s", "V0_V", "node", "min_total_constant_current_mA"], be)

    # joint C_evm x I_evm boundary (ODE model): V0 22.28 V, C_in 28.4 uF, U101 IQ 0, Vf 0.40 V (slow), worst of
    # ON, LATCHED_BD and the two OVP_START thresholds. Minimum EVM draw for t(12 V) <= dwell.
    fr_grid = np.round(np.linspace(0.0, 1.0, 11), 3)
    bnd_rows = []
    bnd = {}
    base = dict(v0=22.28, cin=C_IN[1], iq=0.0, vf=VF_SET[0])
    variants = [("ON", float("nan")), ("LATCHED_BD", float("nan"))] + [("OVP_START", ov) for ov in ovpf_set]
    for dwell in DWELLS:
        for st, ov in variants:
            for fr in fr_grid:
                c = dict(base, state=st, ovpf=ov, cevm=max(fr, 1e-4) * C_EVM_NOM)
                c["ievm"] = 0.0
                c10 = dict(c, ievm=10e-3)
                if b_ode_t(c) <= dwell:
                    need = 0.0
                elif b_ode_t(c10) > dwell:
                    # infeasible: the IN node alone (C_in, the dividers) is slower than the dwell, and an EVM-side
                    # draw cannot speed it up through the body diode (LATCHED_BD with IQ 0)
                    need = float("inf")
                else:
                    lo, hi = 0.0, 10e-3
                    for _ in range(26):
                        mid = 0.5 * (lo + hi)
                        c["ievm"] = mid
                        if b_ode_t(c) <= dwell:
                            hi = mid
                        else:
                            lo = mid
                    need = hi
                bnd[(dwell, st, ov, fr)] = need
                bnd_rows.append(("%.1f" % dwell, st, "%.3f" % ov, "%.2f" % fr, "%.2f" % (fr * C_EVM_NOM * 1e6),
                                 "%.4f" % (need * 1e3)))
    write_csv("b_joint_cevm_ievm_boundary.csv", ["dwell_s", "state", "OVPF_V", "C_evm_frac", "C_evm_eff_uF",
                                                 "min_I_evm_mA"], bnd_rows)
    env = {}
    for dwell in DWELLS:
        env[dwell] = [max(bnd[(dwell, st, ov, fr)] for st, ov in variants) for fr in fr_grid]
    # envelope of the variants that can meet the dwell at all (for the plot of the 0.5 s case)
    env_fin = {}
    for dwell in DWELLS:
        env_fin[dwell] = [max([bnd[(dwell, st, ov, fr)] for st, ov in variants
                               if np.isfinite(bnd[(dwell, st, ov, fr)])] or [float("nan")]) for fr in fr_grid]
    # largest C_evm with zero EVM draw that still meets 1.5 s (bisection on the fraction, worst variant)
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        ok = all(b_ode_t(dict(base, state=st, ovpf=ov, cevm=max(mid, 1e-6) * C_EVM_NOM, ievm=0.0)) <= 1.5
                 for st, ov in variants)
        if ok:
            lo = mid
        else:
            hi = mid
    cevm_max_zero_draw = lo * C_EVM_NOM
    print("  1.5 s boundary at full C_evm 51.4 uF: I_evm >= %.3f mA (worst variant); at I_evm = 0: C_evm <= %.1f uF"
          % (env[1.5][-1] * 1e3, cevm_max_zero_draw * 1e6))

    # RT1987 forward-leakage sensitivity (ODE model), worst slow corner
    src_rows = []
    for st, ov in variants:
        for ik in ("zero", "floor"):
            c = dict(base, state=st, ovpf=ov, cevm=C_EVM_NOM, ievm=I_EVM[ik])
            for isrc in I_SRC_SET:
                t = b_ode_t(c, i_src=isrc)
                src_rows.append((st, "%.3f" % ov, ik, "%.0f" % (isrc * 1e6), "%.4f" % t))
    write_csv("b_rt1987_leak_sensitivity.csv", ["state", "OVPF_V", "I_evm_case", "I_src_total_uA", "t12_s"], src_rows)

    # slope test re-derivation: healthy cases still above 12 V at 0.4 s
    und = [c for c in cases if np.isfinite(c["vb"]) and c["vb"] > V_CRIT]
    slope_rows = []
    for tag, flt in (("all I_evm", lambda c: True), ("I_evm >= floor", lambda c: c["ievm"] >= 0.391e-3),
                     ("I_evm = 0", lambda c: c["ievm"] == 0.0)):
        sel = [c for c in und if flt(c)]
        if sel:
            w_ = max(sel, key=lambda c: c["slope"])
            slope_rows.append((tag, len(sel), "%.3f" % w_["slope"], "%s V0 %.2f Cin %.1fu Cevm %.1fu Ievm %.3fm IQ %.3fm"
                               " Vf %.2f" % (w_["state"], w_["v0"], w_["cin"] * 1e6, w_["cevm"] * 1e6,
                                             w_["ievm"] * 1e3, w_["iq"] * 1e3, w_["vf"])))
            print("  slope 0.2-0.4 s, undecided healthy cases (%s, n=%d): slowest %s V/s (%s)" % slope_rows[-1])
    slope_bound_12 = -(V_CRIT / RP) / (C_IN[1] + C_EVM_NOM)
    noise_slope = 4 * LSB38 / 0.2
    write_csv("b_slope_test.csv", ["subset", "n_cases_above_12V_at_0p4s", "slowest_slope_Vps", "case"],
              slope_rows + [("closed-form bound at 12 V, no current sinks, 79.8 uF", "-", "%.3f" % slope_bound_12, "-"),
                            ("stuck path (held at V_bus) +-2 counts each end over 0.2 s", "-",
                             "+-%.3f" % noise_slope, "-")])

    # plots: traces of selected cases, re-simulated with vectors kept
    picks = []
    for v0 in (16.0, 22.28):
        for st in ("ON", "LATCHED_BD", "LATCHED_ISO", "OVP_START"):
            sel = [c for c in cases if c["state"] == st and c["v0"] == v0]
            if not sel:
                continue
            picks.append((v0, st, "slowest", max(sel, key=lambda c: c["t12"])))
            fl = [c for c in sel if c["ievm"] >= 0.391e-3 or st == "LATCHED_ISO"]
            picks.append((v0, st, "slowest, I_evm >= floor", max(fl, key=lambda c: c["t12"])))
    pcases = [p[3] for p in picks]
    deck = b_deck(pcases, "selected cases for the trace figure")
    write(os.path.join(DECKS, "b_vchg_decay_traces.cir"), deck)
    r = run_deck(deck, vectors=["time"] + ["in%d" % k for k in range(len(pcases))])
    check(r, "part B traces")
    t = r["time"]
    cols = {"ON": "#4C72B0", "LATCHED_BD": "#C44E52", "LATCHED_ISO": "#8172B3", "OVP_START": "#DD8452"}
    fig, axs = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, v0 in zip(axs, (16.0, 22.28)):
        for k, (pv, st, tag, c) in enumerate(picks):
            if pv != v0:
                continue
            if st == "LATCHED_ISO" and tag != "slowest":
                continue
            ax.plot(t, r["in%d" % k], color=cols[st], ls="-" if tag == "slowest" else "--",
                    label="%s %s (C %.0f uF, I_evm %.2f mA, IQ %.2f mA)" % (
                        st, tag, (c["cin"] + c["cevm"]) * 1e6, c["ievm"] * 1e3, c["iq"] * 1e3))
        ax.axhline(12.0, color="k", lw=0.8)
        ax.axhline(3.0, color="k", lw=0.5, ls=":")
        for d in DWELLS:
            ax.axvline(d, color="grey", ls="--", lw=0.8)
        ax.axhspan(DOC_UVF[0], DOC_UVF[1], color="#DD8452", alpha=0.12)
        ax.set_xlim(0, 4)
        ax.set_xlabel("time after both EN read LOW (s)")
        ax.set_title("V0 = %.2f V" % v0)
        ax.legend(fontsize=6)
    axs[0].set_ylabel("V_chg = VCHG-IN (V)")
    fig.suptitle("FR-12(b1): VCHG-IN decay with the U101 body diode; 12.0 V criterion, 0.5 s / 1.5 s dwells "
                 "(window 0-4 s of a 40 s run)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "b_decay_traces.png"), dpi=130)
    plt.close(fig)

    # plot: t12 vs V0 (ngspice points) and the joint boundary
    fig, axs = plt.subplots(1, 2, figsize=(12, 5))
    ax = axs[0]
    for st in ("ON", "LATCHED_BD", "OVP_START", "LATCHED_ISO"):
        xs = [c["v0"] + {"ON": -0.15, "LATCHED_BD": 0.0, "OVP_START": 0.15, "LATCHED_ISO": 0.3}[st]
              for c in cases if c["state"] == st]
        ys = [c["t12"] for c in cases if c["state"] == st]
        ax.plot(xs, ys, ".", color=cols[st], ms=3, alpha=0.5, label=st)
    for d in DWELLS:
        ax.axhline(d, color="k", lw=0.8, ls="--")
    ax.set_xlabel("V_chg when both EN go LOW (V) (states offset for legibility)")
    ax.set_ylabel("time to 12.0 V (s)")
    ax.set_ylim(0, 5)
    ax.legend(fontsize=7)
    ax.set_title("ngspice cases (all I_evm, including 0-0.2 mA)")
    ax = axs[1]
    cev_uF = fr_grid * C_EVM_NOM * 1e6
    for dwell, ls in ((1.5, "-"), (0.5, "--")):
        for st, ov in variants:
            yv = np.array([bnd[(dwell, st, ov, fr)] * 1e3 for fr in fr_grid])
            yv[~np.isfinite(yv)] = np.nan
            ax.plot(cev_uF, yv, ls=ls,
                    color=cols[st], lw=0.8, alpha=0.7)
        lab = ("worst of the four variants, dwell %.1f s" % dwell if dwell == 1.5 else
               "worst of ON / OVP_START, dwell 0.5 s (LATCHED_BD with IQ 0 cannot meet 0.5 s at any I_evm)")
        ax.plot(cev_uF, np.array(env_fin[dwell]) * 1e3, ls=ls, color="k", lw=1.6, label=lab)
    ax.axhline(0.391, color="grey", lw=0.8)
    ax.text(1, 0.40, "H.15 floor 0.391 mA (typical ISD_VBUS)", fontsize=7, color="grey")
    ax.set_xlabel("C_evm effective (uF)")
    ax.set_ylabel("minimum EVM VBUS draw for t(12 V) <= dwell (mA)")
    ax.set_title("V0 22.28 V, C_in 28.4 uF, U101 IQ 0, Vf 0.40 V")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "b_t12_and_boundary.png"), dpi=130)
    plt.close(fig)
    for old in ("b_t12_vs_v0.png",):
        p = os.path.join(OUT, old)
        if os.path.exists(p):
            os.remove(p)
    return dict(cases=cases, needed=needed, be=be, max_rel=max_rel, env=env, fr_grid=fr_grid,
                cevm_max_zero_draw=cevm_max_zero_draw, src_rows=src_rows, slope_rows=slope_rows,
                slope_bound_12=slope_bound_12, noise_slope=noise_slope, t3rows=t3rows, ovpf_set=ovpf_set)

# =====================================================================================================================
# PART C - FR-12(a2) D-MT-EN short check, dV_rgn / dV_bus
# =====================================================================================================================
# RGN-V node: R1-SNT 78.7k V-MOT -> tap, R2-SNT 10k tap -> GND (Scale_Car_Board_20260624.sch lines 5979-5980; V_rgn doc
# section 1). Teensy pin 39 reads the tap with SCALE_V_RGN = 3.3 x 88.7/10 / 4095 (teensy_controller.ino:2032).
# Knee sink (V_rgn doc section 7.1 item 3): I = (V_node - V_on)/R for V_node > V_on, ~0 below; dips give V_on 1.19-1.25 V,
# R 9.2-9.5 kOhm; the November small-signal gain implies 13-17 kOhm; the physics reviewer's open-cathode estimate is
# 3.5-4 kOhm (section 7.3). For R values without a measured V_on, V_on is solved so that the static ratio at 15.93 V is
# 0.848 (ML0226, section 2).
R1SNT, R2SNT = 78.7e3, 10e3
ADC_LSB_RGN = 3.3 * 88.7 / 10 / 4095      # 7.15 mV per count  (teensy_controller.ino:2032)
ADC_LSB_BUS = 3.3 * 56.4 / 10 / 4095      # 4.55 mV per count  (teensy_controller.ino:2028)
V_FC_READ_MAX = 3.3 * 37.4 / 10           # 12.342 V: SCALE_V_FC full scale (27.4k/10k, teensy_controller.ino:2024)
PRECHARGE_DROP_MAX = 1.5                  # teensy_controller.ino:2326
V_PRECHARGE_MIN = 5.0                     # :2328
V_BUS_P2 = (15.8, 15.9, 16.0)             # end of the P2 dwell: regulated bus, 15.9 V no-load (CLAUDE.md section 6)
STATIC_RATIO = 0.848
V_STATIC = 15.93


def solve_von(R):
    """V_on such that the static ratio at V_STATIC is STATIC_RATIO."""
    vn = STATIC_RATIO * V_STATIC * R2SNT / (R1SNT + R2SNT)
    i_sink = (V_STATIC - vn) / R1SNT - vn / R2SNT
    return vn - i_sink * R


def r_for_gain(g):
    """Knee slope R such that the small-signal reading gain above the knee is g (gain = 8.87 g1/(g1+g2+1/R))."""
    g1, g2 = 1 / R1SNT, 1 / R2SNT
    return 1.0 / (g1 * (R1SNT + R2SNT) / R2SNT / g - g1 - g2)


R_G048 = r_for_gain(0.48)   # lowest measured small-signal gain, V_rgn doc 7.1 item 2 / REVIEW VR-3 (check round, issue 3)

NODE_SETS = [
    # label, kind, V_on, R_sink
    ("as-built, gain fit 0.48 R %.2fk" % (R_G048 / 1e3), "knee", solve_von(R_G048), R_G048),
    ("as-built, dip fit V_on 1.19 V R 9.2k", "knee", 1.19, 9.2e3),
    ("as-built, dip fit V_on 1.25 V R 9.5k", "knee", 1.25, 9.5e3),
    ("as-built, gain fit R 13k", "knee", solve_von(13e3), 13e3),
    ("as-built, gain fit R 17k", "knee", solve_von(17e3), 17e3),
    ("as-built, open-cathode est. R 3.5k (ASSUMPTION)", "knee", solve_von(3.5e3), 3.5e3),
    ("repaired, healthy TL431 REF 4 uA", "const", 0.0, 4e-6),   # TL431 REF 2 typ / 4 max uA (V_rgn doc 7.2 table)
]


def part_c():
    print("\n=== PART C: FR-12(a2) D-MT-EN short check ===")
    L = ["* Sim 5 part C: RGN-V node transfer V-MOT -> tap (R1-SNT 78.7k, R2-SNT 10k) with the knee sink",
         "* generated by efuse_decay/run.py; copies share V-MOT", "VMOT vmot 0 DC 0"]
    wk = 0.004   # V, softplus width of the knee
    for i, (lab, kind, von, rs) in enumerate(NODE_SETS):
        L.append("* set %d: %s" % (i, lab))
        L.append("R1_%d vmot tap%d %.6g" % (i, i, R1SNT))
        L.append("R2_%d tap%d 0 %.6g" % (i, i, R2SNT))
        if kind == "knee":
            L.append("B%d tap%d 0 I = %.6e*ln(1+exp((v(tap%d)-%.5f)/%.4f))" % (i, i, wk / rs, i, von, wk))
        else:
            # healthy REF current, constant once the node is biased (tapers to 0 below 0.1 V)
            L.append("B%d tap%d 0 I = %.3e*0.5*(1+tanh((v(tap%d)-0.1)/0.02))" % (i, i, rs, i))
    L += [".dc VMOT 0 24 0.005", ".end"]
    deck = "\n".join(L) + "\n"
    write(os.path.join(DECKS, "c_rgnv_transfer.cir"), deck)
    r = run_deck(deck)
    check(r, "part C")
    vm = r.vec.get("v-sweep", r.vec.get("vmot"))
    taps = [r["tap%d" % i] for i in range(len(NODE_SETS))]

    def read_rgn(i, v):
        vt = np.interp(v, vm, taps[i])
        return np.round(vt / 3.3 * 4095) * ADC_LSB_RGN

    def read_rgn_ideal(i, v):
        return np.interp(v, vm, taps[i]) * 88.7 / 10

    def read_bus(v):
        return np.round(v / ADC_LSB_BUS) * ADC_LSB_BUS

    # validation rows: static ratio and small-signal gain at 15.93 V
    val = []
    for i, (lab, kind, von, rs) in enumerate(NODE_SETS):
        ratio = read_rgn_ideal(i, V_STATIC) / V_STATIC
        g = (read_rgn_ideal(i, V_STATIC + 0.05) - read_rgn_ideal(i, V_STATIC - 0.05)) / 0.1
        val.append((lab, "%.4f" % von if kind == "knee" else "-", "%.0f" % rs if kind == "knee" else "-",
                    "%.4f" % ratio, "%.4f" % g))
        print("  node set %-48s V_on %s R %s: static ratio %s at 15.93 V, small-signal gain %s" % val[-1])
    write_csv("c_node_sets.csv", ["node_set", "V_on_V", "R_sink_ohm", "static_ratio_15p93V", "smallsignal_gain_15p93V"],
              val)

    # window cases
    rows = []
    scen = []
    for vb in (7.4, 7.9, 8.4):
        v_src_read = vb      # V_batt reads up to 8.646 V (SCALE_V_BATT), unclipped
        lo = max(V_PRECHARGE_MIN, v_src_read - PRECHARGE_DROP_MAX)
        hi = vb - 0.3        # ASSUMPTION: settled pre-charge = source - 0.3 V (body diode + RT1987 at light load)
        scen.append(("V_fc 0, V_batt %.1f" % vb, lo, hi))
    vfc = 13.0
    v_src_read = min(vfc, V_FC_READ_MAX)   # V_fc reading clips at 12.34 V
    scen.append(("V_fc 13.0 (reads %.2f), V_batt 7.4-8.4" % v_src_read, v_src_read - PRECHARGE_DROP_MAX, vfc - 0.3))
    ratio_tab = {}
    for sname, lo, hi in scen:
        for vb0 in np.linspace(lo, hi, 9):
            for vb1 in V_BUS_P2:
                dvb = read_bus(vb1) - read_bus(vb0)
                for i, (lab, kind, von, rs) in enumerate(NODE_SETS):
                    dr = read_rgn(i, vb1) - read_rgn(i, vb0)
                    ratio = dr / dvb
                    ratio_tab.setdefault((sname, lab), []).append(ratio)
                    rows.append((sname, "%.3f" % vb0, "%.2f" % vb1, "shorted", lab, "%.4f" % dvb, "%.4f" % dr,
                                 "%.4f" % ratio))
    # open (healthy) switch: V-MOT isolated by back-to-back FETs (RT1987_DS-00 p.? section 17: back-to-back MOSFETs);
    # V-MOT decays with tau 105-122 s (V_rgn doc 7.3) over the window. Window length: P0 gate (40-300 ms) to P2 end
    # (<= 800 ms boost ramp + 50-500 ms dwell): 0.09-1.6 s (teensy_controller.ino:2318-2334).
    open_rows = []
    worst_open = 0.0
    for vmot0 in (0.0, 5.0, 10.0, 15.9):
        for tau in (105.0, 122.0):
            for tw in (0.09, 1.6):
                vmot1 = vmot0 * math.exp(-tw / tau)
                for sname, lo, hi in scen:
                    for vb0 in (lo, hi):
                        dvb = read_bus(15.9) - read_bus(vb0)
                        for i, (lab, kind, von, rs) in enumerate(NODE_SETS):
                            dr = read_rgn(i, vmot1) - read_rgn(i, vmot0)
                            # +-2 LSB per reading on each channel (ASSUMPTION: averaged reading noise)
                            err = (4 * ADC_LSB_RGN + abs(dr) * 4 * ADC_LSB_BUS / max(dvb, 1e-6)) / dvb
                            ratio = dr / dvb
                            worst_open = max(worst_open, ratio + err)
                            open_rows.append((sname, "%.3f" % vb0, "15.90", "open, V-MOT0 %.1f V tau %.0f s tw %.2f s"
                                              % (vmot0, tau, tw), lab, "%.4f" % dvb, "%.4f" % dr, "%.4f" % ratio,
                                              "%.4f" % err))
    write_csv("c_ratio_cases.csv", ["scenario", "V_bus_P0gate_V", "V_bus_P2end_V", "switch", "node_set", "dV_bus_V",
                                    "dV_rgn_V", "ratio"], rows)
    write_csv("c_ratio_open_switch.csv", ["scenario", "V_bus_P0gate_V", "V_bus_P2end_V", "switch", "node_set",
                                          "dV_bus_V", "dV_rgn_V", "ratio", "ratio_noise_bound"], open_rows)
    summ = []
    for (sname, lab), v in ratio_tab.items():
        summ.append((sname, lab, "%.3f" % min(v), "%.3f" % max(v)))
    write_csv("c_ratio_summary.csv", ["scenario", "node_set", "ratio_min_shorted", "ratio_max_shorted"], summ)
    for s in summ:
        print("  shorted  %-38s %-48s ratio %s-%s" % s)
    print("  open switch: worst ratio + noise bound = %.4f" % worst_open)
    # ADC noise bound on the shorted ratio at the smallest window
    min_dvb = min(float(x[5]) for x in rows)
    noise_short = 4 * ADC_LSB_RGN / min_dvb + 4 * ADC_LSB_BUS / min_dvb
    # extra sweep: ratio vs window start for every node set (V_bus1 = 15.9)
    vb0s = np.linspace(5.0, 15.0, 201)
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.8))
    ax = axs[0]
    vv = np.linspace(0, 24, 481)
    for i, (lab, kind, von, rs) in enumerate(NODE_SETS):
        ax.plot(vv, read_rgn_ideal(i, vv), label=lab)
    ax.plot(vv, vv, "k:", lw=0.8, label="ideal (reading = V-MOT)")
    ax.set_xlabel("V-MOT true (V)")
    ax.set_ylabel("V_rgn reading (V)")
    ax.set_title("RGN-V transfer (pin 39)")
    ax.legend(fontsize=7)
    ax = axs[1]
    for i, (lab, kind, von, rs) in enumerate(NODE_SETS):
        rr = [(read_rgn_ideal(i, 15.9) - read_rgn_ideal(i, v0)) / (15.9 - v0) for v0 in vb0s]
        ax.plot(vb0s, rr, label=lab)
    ax.axhline(0.5, color="grey", ls="--", lw=0.8)
    ax.axhline(0.3, color="k", ls="--", lw=0.8)
    ax.axhline(worst_open, color="#C44E52", ls=":", lw=1.0)
    ax.text(5.1, worst_open + 0.01, "open switch worst (with ADC noise)", fontsize=7, color="#C44E52")
    for sname, lo, hi in scen:
        ax.axvspan(lo, hi, color="#55A868" if "V_fc 0" in sname else "#DD8452", alpha=0.08)
    ax.text(6.0, 1.03, "battery only P0 gate", fontsize=7)
    ax.text(10.9, 1.03, "V_fc 13 V P0 gate", fontsize=7)
    ax.set_ylim(0, 1.1)
    ax.set_xlabel("V_bus at the P0 gate (V); window ends at 15.9 V")
    ax.set_ylabel("dV_rgn / dV_bus, shorted D-MT-EN")
    ax.set_title("FR-12(a2) ratio vs window start; k = 0.5 and 0.3 dashed")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "c_ratio.png"), dpi=130)
    plt.close(fig)
    return dict(summ=summ, worst_open=worst_open, noise_short=noise_short, val=val, scen=scen)


def main():
    tee = _Tee(os.path.join(OUT, "console_log.txt"))
    sys.stdout = tee
    try:
        print("Sim 5 efuse_decay - simulator: %s" % ngspice_version())
        a = part_a()
        b = part_b(a)
        c = part_c()
        # headline file for RESULTS.md
        with open(os.path.join(OUT, "headline.txt"), "w") as f:
            f.write("A bands (V): %r\n" % {"%s leak=%s" % k: tuple(round(x, 3) for x in v)
                                          for k, v in a["band"].items()})
            f.write("A MC probabilities UVr>10.2, OVr<22.28, OVr>24, OVr>25.2: %r\n" % (a["p"],))
            f.write("A ngspice-vs-closed-form max error V: %.3e\n" % a["max_err"])
            f.write("B max t12 by state/V0/subset: %r\n" % {"%s %.2f %s" % k: round(v, 3)
                                                           for k, v in b["needed"].items()})
            f.write("B ngspice-vs-ODE max rel diff by state: %r\n" % {k: float("%.3e" % v)
                                                                    for k, v in b["max_rel"].items()})
            f.write("B 1.5 s boundary: min I_evm at C_evm 51.4 uF %.4f mA; max C_evm at I_evm 0 %.2f uF\n"
                    % (b["env"][1.5][-1] * 1e3, b["cevm_max_zero_draw"] * 1e6))
            f.write("B slope test rows: %r\n" % (b["slope_rows"],))
            f.write("B t3 rows: %r\n" % (b["t3rows"],))
            f.write("C open-switch worst ratio incl. noise: %.4f; shorted ratio ADC noise bound at min window: %.4f\n"
                    % (c["worst_open"], c["noise_short"]))
        print("\nDone. Outputs in %s" % OUT)
    finally:
        sys.stdout = tee.s
        tee.f.close()


if __name__ == "__main__":
    main()
