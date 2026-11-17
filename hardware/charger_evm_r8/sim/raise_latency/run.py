"""Sim 7: T3 raise-latency budget sweep (FR-07). What is the largest edge-to-raised-image latency T_lat that causes no
hazard and no material harvest loss, and what does each larger budget cost?

T_lat is measured from the H1 rise (pin-34 rising edge, V-MOT = 18.05 V H1 rise maximum) to the raised image being in
force in the charger model. The firmware budget is T_lat minus the pin-34 ISR latency (TODO(calibrate: T-C-06)) minus
any pure BQ25798 register-to-loop dead time (TODO(verify: TI, not in SLUSDV2C; T-B-12, T-B-24)). After T_lat the
charger current follows its target through a first-order lag TAU_CHG (0.1 ms, the sim 2 assumption).

Model: one V-MOT node (C_VMOT), the sim 6 mechanical brake (imported), the sim 2 chopper static I-V (H corners, read
from ../chopper/results_static_iv.csv), the VESC 15 mA housekeeping, the U101 OVP trip (charger off for the rest of the
brake: sim 2 section 5.6), an optional VESC over-voltage cut (0.5 s fault stop; level unknown, swept), and the
charger draw of the FC image before T3 and of the raised image after it.

Code reuse: functions and constants of sim 6 (`../regen_nocut/run.py`) are imported by file path (main() is never
called, nothing is written there). The chopper I-V is read from sim 2's committed CSV. The node integrator is new: it
replaces sim 6 `transient()` (sim 6 assumption 1: no chopper; this model adds it, implicitly).

Writes only inside this folder. ASCII console output only. Run: C:/Users/ricky/miniforge3/python.exe run.py
"""
import csv
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sim6 = _load("sim6", os.path.join(SIM, "regen_nocut", "run.py"))

LOG = []


def log(s=""):
    print(s)
    LOG.append(s)


# ---------------------------------------------------------------- constants (sources in RESULTS.md Table 1)
K_F, M_EFF, R_PH = sim6.K_F, sim6.M_EFF, sim6.R_PH
F_COULOMB, B_EFF = sim6.F_COULOMB, sim6.B_EFF
ETA_GEAR, ETA_INV = sim6.ETA_GEAR, sim6.ETA_INV
I_REGEN_BATT_MAX = sim6.I_REGEN_BATT_MAX      # 1.5 A VESC battery regen cap
K_VINDPM = sim6.K_VINDPM                        # 10 A/V (sim 2 assumption)
V_H1R = sim6.V_H1_RISE                          # 18.05 V H1 rise maximum (VBUS 16.39 V)
VINDPM_FC = sim6.VINDPM_FC                      # 14.5 V FC image
VBUS = 16.39                                    # bus maximum (H1 rise maximum is referred to it)
I_HK = 0.015                                    # VESC housekeeping (sim 2 IHK; logged 14-20 mA)
ACC = 0.88                                      # IINDPM_ACC, absorbed current -12 % (H.4 r9-25, SLUSDV2C 6.5 at 1 A)
# FC-image ICHG-limited input power, pack 7.40 V, ICHG 1.60 A -6.5 %, R_BATLEAD 12.6 mOhm + RT1987 20 mOhm, eta_max 0.93
P_FC_ICHG = 1.60 * (1 - 0.065) * (7.40 + 1.60 * (0.0126 + 0.020)) / 0.93
R_PATH = 0.19                                   # R_PATH_RG maximum (H.19; VINDPM regulates the BQ VBUS pin)
TAU_CHG = 1.0e-4                                # charger current lag (sim 2: 1 ohm x 100 uF)
RATCHET_V = 19.0 * 1.02 + 0.19                  # T3 step 4: VINDPM 19.0 V once calibrated V_rgn > 19.57 V
RATCHET_DELAY = 1.5e-3                          # tick + one write; TODO(verify: firmware round)
T_VESC_STOP = 0.500                             # sim 2 assumption 5 (UNCONFIRMED)
T_REQUAL = 0.300                                # FR-23 provisional
I_FF = 0.90                                     # FR-41 feed-forward target (FC-image maximum)
I_FLOOR = 0.30                                  # governor floor
ADV_IINDPM = 0.475e-3                           # REG06:07 lands W(REG03-05)+t_BUF = 0.475 ms before REG03-05 (100 kHz)
# Review round: IINDPM-first is the design T3 write order (design line 3010: "IINDPM 1.70 A, then ICHG 3.10 A + VINDPM
# 18.2 V"), so it is the baseline. On an idle 100 kHz bus REG06:07 completes 0.475 of 0.859 ms before REG03-05; for a
# T_lat below 0.859 ms (not reachable at 100 kHz) the advance is scaled by that fraction so it never precedes the edge.
ADV_FRAC = 0.475 / 0.859
# CV-phase pack (FR-39 keeps windows open in CV): interim VREG 8.32 V (design r4-11); taper current swept (not sourced)
VREG_CV = 8.32
CV_TAPER_A = [1.2, 0.8, 0.4]


def p_cv(i_taper):
    """Charger input power in CV at taper current i_taper (VREG 8.32 V, 32.6 mOhm battery path, eta_max 0.93)."""
    return i_taper * (VREG_CV + i_taper * (0.0126 + 0.020)) / 0.93


P_FC_INPUT_H7 = 11.2                            # design H.7 FC-image input limit (pin clamp kept: UVB LOW or no re-read)
ISWEEP = [0.40, 0.45, 0.50, 0.60, 0.70]          # IINDPM at the edge, 100 kHz FR-41 ramp range 0.300-0.890 A (R9.H21(r))

# chargers: sim 2 corners (P_in, clamp) and stage-1 VINDPM (18.2 V +-2 %) before the 19.0 V ratchet
STAGE1 = {"lo": 18.2 * 1.02, "nom": 18.2, "d310": 18.2, "hi": 18.2 * 0.98}
CHARGERS = {k: dict(p=v["p"], ilim=v["ilim"], vind1=round(STAGE1[k], 4), vind2=v["vindpm"])
            for k, v in sim6.CHARGERS.items()}

# chopper static I-V (sim 2 Part A, results_static_iv.csv)
CHOP = {}
with open(os.path.join(SIM, "chopper", "results_static_iv.csv")) as f:
    for r in csv.DictReader(f):
        if r["chopper"] in ("H-lo", "H-typ", "H-hi"):
            xs = [float(r["v_onset_1mA"]), float(r["v_at_100mA"]), float(r["v_at_300mA"]),
                  float(r["v_at_470mA"]), float(r["v_at_740mA"]), float(r["v_at_850mA"])]
            ys = [0.0, 0.10, 0.30, 0.47, 0.74, 0.85]
            for k in range(1, len(xs)):
                xs[k] = max(xs[k], xs[k - 1] + 1e-3)
            CHOP[r["chopper"]] = (xs, ys)
CHOP["none"] = ([1e6, 1e6 + 1, 1e6 + 2, 1e6 + 3, 1e6 + 4, 1e6 + 5], [0.0, 0.1, 0.3, 0.47, 0.74, 0.85])

# U101 OVP rising corners (sim 5 Table 1; sim 6 Table 1)
OVP = {"s5-lo": 21.588, "noleak-min": 22.149, "typ": 23.188, "s5-hi": 25.019}

THR = [  # (key, volts, class, label)
    ("ceil20p5", 20.5, "test", "20.5 V test acceptance (T-B-12, T-G-02, T-D-12)"),
    ("chopHlo", 21.35, "harvest", "chopper onset H-lo 21.35 V (also the superseded VESC-cut premise)"),
    ("ovpS5lo", 21.588, "harvest", "U101 OVP rising min, with leak 21.588 V"),
    ("chopHtyp", 22.12, "harvest", "chopper onset H-typ 22.12 V"),
    ("ovpNoleak", 22.149, "harvest", "U101 OVP rising min, no leak 22.149 V"),
    ("chopHhi", 23.095, "harvest", "chopper onset H-hi 23.095 V"),
    ("ovpTyp", 23.188, "harvest", "U101 OVP rising typ 23.188 V"),
    ("ovchg", 24.15, "run_end", "FR-50 OV_CHG State 99 (pin 38 24.0 V / 0.994)"),
    ("ovpS5hi", 25.019, "harvest", "U101 OVP rising max 25.019 V"),
    ("bqOvp", 25.2, "harvest", "BQ25798 VBUS_OVP rising min 25.2 V"),
    ("bqAbs", 30.0, "hazard", "BQ25798 VBUS abs max 30 V"),
    ("rtOvp", 33.0, "hazard", "RT1987 OVP 33 V (D-BC-RG latch)"),
    ("cap35", 35.0, "hazard", "C-D8/C-D10 35 V rating"),
]
THR_V = np.array([t[1] for t in THR])

# brakes: mech = constant motor current from v0 until v <= v1; prof = prescribed power profile on a 1 ms grid
MECH = [(n, v0, v1, 12.0) for n, v0, v1, _a, _b in sim6.EVENTS] + \
       [(n, v0, v1, 12.0) for n, v0, v1 in sim6.REF_STEPS] + \
       [("trap25A 2.5->1", 2.5, 1.0, sim6.I_TRAP), ("trap25A 3.0->1", 3.0, 1.0, sim6.I_TRAP)]
CP = [("CP 18.9 W", 18.9, 0.58), ("CP 23 W", 23.0, 0.58)]
# Table 1 set: the eight measured brakes, the 2->1 and 3->1 steps and the 18.9 W constant-power brake
BB_MEAS = [m[0] for m in MECH if not m[0].startswith("trap")] + ["CP 18.9 W"]

DT_FINE = 2e-6
DT_COARSE = 1e-5
TAIL = 0.02


# ---------------------------------------------------------------- case construction
def drag(v):
    return F_COULOMB + B_EFF * v


PROFILES = []  # list of np arrays (W per ms)


def add_profile(arr):
    PROFILES.append(np.asarray(arr, float))
    return len(PROFILES) - 1


CP_IDX = {n: add_profile(np.full(int(round(d * 1000)), p)) for n, p, d in CP}


def base_case(**kw):
    c = dict(kind=0, v0=0.0, v1=0.0, icmd=12.0, prof=-1, C=0.4e-3, V0=V_H1R, trise=0.0, tlat=0.0, ipre=I_FLOOR,
             t_ramp=np.inf, acc=ACC, pcap_pre=P_FC_ICHG, pcap_post=np.inf, adv=ADV_IINDPM,
             ppost=CHARGERS["nom"]["p"],
             ilim=CHARGERS["nom"]["ilim"], vind1=CHARGERS["nom"]["vind1"], vind2=CHARGERS["nom"]["vind2"],
             tau=TAU_CHG, rpath=R_PATH, chop="H-hi", ovp=np.inf, vcut=np.inf, eg=ETA_GEAR, ei=ETA_INV, ihk=I_HK,
             stop_thr=np.inf, regen_armed=0)
    c.update(kw)
    return c


def brake_kw(b):
    if b[0] in CP_IDX:
        return dict(kind=1, prof=CP_IDX[b[0]])
    return dict(kind=0, v0=b[1], v1=b[2], icmd=b[3])


def corner_kw(k):
    ch = CHARGERS[k]
    return dict(ppost=ch["p"], ilim=ch["ilim"], vind1=ch["vind1"], vind2=ch["vind2"])


# ---------------------------------------------------------------- the integrator
OUT_KEYS = ["Vmax", "Vmax_lat", "E_reg", "E_chg", "E_bus", "E_chop", "E_hk", "ichop_max", "t_chop_hi", "ncut",
            "t_trip", "t_edge", "t_end", "V_T3"]


def simulate(cases, t_max=1.0, record=None, rec_every=5):
    """Vectorised forward integration of all cases together. Returns a dict of output arrays (len N) and the
    threshold-crossing-time matrix tc (N x len(THR), seconds after the H1 edge; inf = never)."""
    N = len(cases)
    P = {k: np.array([c[k] for c in cases], dtype=float) for k in cases[0] if k != "chop"}
    chop_x = np.array([CHOP[c["chop"]][0] for c in cases])
    chop_y = np.array([CHOP[c["chop"]][1] for c in cases])
    slope = np.diff(chop_y, axis=1) / np.diff(chop_x, axis=1)
    slope = np.concatenate([slope, slope[:, -1:]], axis=1)
    P["chop_x"], P["chop_y"], P["chop_s"] = chop_x, chop_y, slope
    plen = np.array([len(p) for p in PROFILES]) if PROFILES else np.zeros(1)
    L = int(plen.max())
    ptab = np.zeros((len(PROFILES), L + 1))
    for i, p in enumerate(PROFILES):
        ptab[i, :len(p)] = p
    P["plen"] = np.where(P["prof"] >= 0, plen[np.maximum(P["prof"], 0).astype(int)], 0)
    P["prof"] = np.maximum(P["prof"], 0).astype(int)

    S = dict(V=P["V0"].copy(), v=P["v0"].copy(), tripped=np.zeros(N, bool), cut_until=np.full(N, -np.inf),
             t_rat=np.full(N, np.inf), done=np.zeros(N, bool))
    S["t_edge"] = np.where(S["V"] >= V_H1R - 1e-9, 0.0, np.inf)
    O = {k: np.zeros(N) for k in OUT_KEYS}
    O["Vmax"] = S["V"].copy()
    O["Vmax_lat"] = S["V"].copy()
    O["t_trip"][:] = np.inf
    O["t_end"][:] = np.inf
    O["V_T3"][:] = np.nan
    tc = np.full((N, len(THR)), np.inf)
    tstop = np.full(N, np.inf)    # crossing of the case's own stop threshold (bisection)
    # initial charger current = pre-image target at the start voltage
    V = S["V"]
    S["ich"] = np.minimum(P["ipre"] * P["acc"], P["pcap_pre"] / V)
    S["ich"] = np.where(P["regen_armed"] > 0, 0.0, S["ich"])
    S["Vprev"] = V.copy()
    gidx = np.arange(N)
    rec = {i: [] for i in (record or [])}
    t = 0.0
    step = 0
    while t < t_max:
        T3 = S["t_edge"] + P["tlat"]
        fine = np.any(t < T3 + 5e-3)
        dt = DT_FINE if fine else DT_COARSE
        V, v = S["V"], S["v"]
        incut = t < S["cut_until"]
        # --- source: mechanical brake
        icm = P["icmd"] * np.where(P["trise"] > 0, np.minimum(1.0, t / np.where(P["trise"] > 0, P["trise"], 1.0)), 1.0)
        mech_on = (P["kind"] == 0) & (v > P["v1"])
        pm = P["ei"] * (P["eg"] * K_F * icm * v - 1.5 * icm * icm * R_PH)
        capv = I_REGEN_BATT_MAX * V
        bq = P["eg"] * K_F * v
        disc = bq * bq - 6.0 * R_PH * capv / P["ei"]
        over = (pm > capv) & (disc >= 0)
        ieff = np.where(over, (bq - np.sqrt(np.maximum(disc, 0.0))) / (3.0 * R_PH), icm)
        pm = np.where(over, capv, pm)
        # --- source: profile
        k = int(t * 1000.0)
        prof_on = (P["kind"] == 1) & (k < P["plen"])
        pp = np.minimum(ptab[P["prof"], min(k, L)], capv)
        on = np.where(P["kind"] == 0, mech_on, prof_on)
        p = np.where(P["kind"] == 0, pm, pp)
        p = np.where(on & ~incut, np.maximum(p, 0.0), 0.0)
        ieff = np.where(on & ~incut & (P["kind"] == 0), ieff, 0.0)
        i_in = p / V
        # --- charger target
        post = t >= T3
        mid = (t >= T3 - np.minimum(P["adv"], ADV_FRAC * P["tlat"])) & ~post
        ipre = np.where(t >= S["t_edge"] + P["t_ramp"], I_FF, P["ipre"])
        tgt_pre = np.minimum(ipre * P["acc"], P["pcap_pre"] / V)
        tgt_pre = np.minimum(tgt_pre, K_VINDPM * np.maximum(V - VINDPM_FC, 0.0))
        tgt_pre = np.where(P["regen_armed"] > 0, 0.0, tgt_pre)   # regen-armed: converter held until release
        tgt_mid = np.minimum(P["ilim"] * P["acc"], P["pcap_pre"] / V)
        vind = np.where(t >= S["t_rat"], P["vind2"], P["vind1"])
        tgt_post = np.minimum(np.minimum(P["ilim"] * P["acc"], np.minimum(P["ppost"], P["pcap_post"]) / V),
                              K_VINDPM * (V - S["ich"] * P["rpath"] - vind))
        tgt_post = np.maximum(tgt_post, 0.0)
        tgt = np.where(post, tgt_post, np.where(mid, tgt_mid, tgt_pre))
        tgt = np.where(S["tripped"], 0.0, tgt)
        newrat = post & np.isinf(S["t_rat"]) & (V > RATCHET_V)
        S["t_rat"] = np.where(newrat, t + RATCHET_DELAY, S["t_rat"])
        a = np.where(P["tau"] > 0, np.minimum(1.0, dt / np.where(P["tau"] > 0, P["tau"], 1.0)), 1.0)
        ich = S["ich"] + (tgt - S["ich"]) * a
        ich = np.where(S["tripped"], 0.0, ich)
        S["ich"] = ich
        # --- node: implicit chopper, bus clamp
        I_other = i_in - ich - P["ihk"]
        Cdt = P["C"] / dt
        Vfree = V + I_other / Cdt
        X, Y, Sl = P["chop_x"], P["chop_y"], P["chop_s"]
        g = Cdt[:, None] * (X - V[:, None]) + Y - I_other[:, None]
        kk = np.clip((g <= 0).sum(axis=1) - 1, 0, X.shape[1] - 1)
        xk = np.take_along_axis(X, kk[:, None], 1)[:, 0]
        yk = np.take_along_axis(Y, kk[:, None], 1)[:, 0]
        sk = np.take_along_axis(Sl, kk[:, None], 1)[:, 0]
        Vimp = (I_other + Cdt * V - yk + sk * xk) / (Cdt + sk)
        conducting = Vfree > X[:, 0]
        Vn = np.where(conducting, Vimp, Vfree)
        ichop = np.where(conducting, yk + sk * (Vn - xk), 0.0)
        ibus = np.where(Vn < VBUS, Cdt * (VBUS - Vn), 0.0)
        Vn = np.maximum(Vn, VBUS)
        live = ~S["done"]
        O["E_reg"] += np.where(live, p * dt, 0.0)
        O["E_chg"] += np.where(live, V * ich * dt, 0.0)
        O["E_bus"] += np.where(live, VBUS * ibus * dt, 0.0)
        O["E_chop"] += np.where(live, Vn * ichop * dt, 0.0)
        O["E_hk"] += np.where(live, V * P["ihk"] * dt, 0.0)
        O["ichop_max"] = np.maximum(O["ichop_max"], ichop)
        O["t_chop_hi"] += np.where(ichop > 0.47, dt, 0.0)
        # --- mechanics
        S["v"] = np.where(P["kind"] == 0, np.maximum(v - (K_F * ieff + drag(v)) / M_EFF * dt, 0.0), v)
        S["Vprev"] = V
        S["V"] = Vn
        tn = t + dt
        # --- events
        newtrip = (~S["tripped"]) & (Vn >= P["ovp"])
        O["t_trip"] = np.where(newtrip, tn - S["t_edge"], O["t_trip"])
        S["tripped"] |= newtrip
        newcut = (Vn >= P["vcut"]) & ~incut
        S["cut_until"] = np.where(newcut, tn + T_VESC_STOP, S["cut_until"])
        O["ncut"] += newcut
        newedge = np.isinf(S["t_edge"]) & (Vn >= V_H1R)
        S["t_edge"] = np.where(newedge, tn, S["t_edge"])
        T3 = S["t_edge"] + P["tlat"]
        O["V_T3"] = np.where(np.isnan(O["V_T3"]) & (tn >= T3), Vn, O["V_T3"])
        O["Vmax"] = np.where(live, np.maximum(O["Vmax"], Vn), O["Vmax"])
        O["Vmax_lat"] = np.where(live & (tn <= T3), np.maximum(O["Vmax_lat"], Vn), O["Vmax_lat"])
        cross = (Vn[:, None] >= THR_V[None, :]) & np.isinf(tc) & live[:, None]
        if cross.any():
            tc = np.where(cross, (tn - S["t_edge"])[:, None], tc)
        sc = live & np.isinf(tstop) & (Vn >= P["stop_thr"])
        tstop = np.where(sc, tn - S["t_edge"], tstop)
        # --- end of event
        ended = ~on & ~(tn < S["cut_until"]) & np.isinf(O["t_end"])
        ended &= ~((P["kind"] == 0) & (S["v"] > P["v1"]))
        O["t_end"] = np.where(ended, tn, O["t_end"])
        fin = tn > O["t_end"] + TAIL
        if np.isfinite(P["stop_thr"]).any():
            # resolved FALSE once the raise is in force, V-MOT is falling below the threshold and any ratchet has
            # landed: brake power only falls (12 A brakes) or is constant (CP), so V-MOT cannot climb back
            falling = (tn >= T3 + 3e-3) & (Vn < S["Vprev"]) & (Vn < P["stop_thr"] - 0.05) & \
                (np.isinf(S["t_rat"]) | (tn > S["t_rat"] + 2e-3))
            resolved = np.isfinite(tstop) | falling
            fin |= np.isfinite(P["stop_thr"]) & resolved
        S["done"] |= fin
        if record:
            if step % rec_every == 0:
                for i in record:
                    rec[i].append((tn - (S["t_edge"][i] if np.isfinite(S["t_edge"][i]) else 0.0), Vn[i], ich[i],
                                   ichop[i], i_in[i]))
        t = tn
        step += 1
        if S["done"].all():
            break
    O["tc"] = tc
    O["tstop"] = tstop
    O["t_edge"] = S["t_edge"]
    O["V_end"] = S["V"]
    # Harvest = charger input energy drawn from the motor side, plus the node energy above VBUS left at the end of the
    # run (after the brake the T4 restore puts the FC image back and the charger draws V-MOT down to VBUS), less the
    # node energy above VBUS at the start (identical for every latency). After a U101 trip the charger is off, so the
    # left-over node energy goes to the chopper and the housekeeping draw and is not credited.
    C = P["C"]
    e_end = np.where(np.isfinite(O["t_trip"]), 0.0, 0.5 * C * (S["V"] ** 2 - VBUS ** 2))
    O["E_harv"] = O["E_chg"] - O["E_bus"] + e_end - 0.5 * C * (P["V0"] ** 2 - VBUS ** 2)
    if record:
        O["rec"] = {i: np.array(v) for i, v in rec.items()}
    return O


# ---------------------------------------------------------------- bisection on T_lat
def bisect_tlat(problems, hi=0.060, tol=1e-5, t_max=1.0):
    """problems: list of case dicts with stop_thr set. Returns the smallest T_lat (s) that makes V-MOT reach stop_thr;
    0.0 = reaches it even with an instant raise; inf = not reached at `hi`."""
    n = len(problems)
    lo_a = np.zeros(n)
    hi_a = np.full(n, hi)

    def crosses(tl):
        cs = [dict(p, tlat=float(x)) for p, x in zip(problems, tl)]
        O = simulate(cs, t_max=t_max)
        return np.isfinite(O["tstop"])
    c_hi = crosses(hi_a)
    c_lo = crosses(lo_a)
    res = np.where(c_lo, 0.0, np.where(c_hi, np.nan, np.inf))
    open_ = np.isnan(res)
    while open_.any() and np.max(hi_a[open_] - lo_a[open_]) > tol:
        idx = np.where(open_ & (hi_a - lo_a > tol))[0]
        mid = 0.5 * (lo_a[idx] + hi_a[idx])
        c = crosses_sub(problems, idx, mid, t_max)
        hi_a[idx] = np.where(c, mid, hi_a[idx])
        lo_a[idx] = np.where(c, lo_a[idx], mid)
    res = np.where(open_, hi_a, res)
    return res


def crosses_sub(problems, idx, mid, t_max):
    cs = [dict(problems[i], tlat=float(x)) for i, x in zip(idx, mid)]
    O = simulate(cs, t_max=t_max)
    return np.isfinite(O["tstop"])


def write_csv(name, rows):
    with open(os.path.join(HERE, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def r4(x):
    return None if x is None or (isinstance(x, float) and (math.isnan(x))) else (
        "inf" if isinstance(x, float) and math.isinf(x) else round(float(x), 4))


# ---------------------------------------------------------------- drive-cycle brake segments (sim 6 Part C basis)
def cycle_segments(fn, eg=ETA_GEAR, ei=ETA_INV):
    with open(os.path.join(REPO, "references", "drive_cycles", fn)) as f:
        rd = list(csv.DictReader(f))
    t = np.array([float(r["time_s"]) for r in rd])
    v = np.array([float(r["v_mps"]) for r in rd])
    tg = np.arange(0.0, t[-1], 1e-3)
    vg = np.interp(tg, t, v)
    a_dec = -np.gradient(vg, 1e-3)
    # sim 6 uses the segment slope; the 1 ms gradient of the linear interpolation is the same inside each segment
    f_brake = M_EFF * a_dec - drag(vg)
    i = np.where(f_brake > 0, np.minimum(f_brake / K_F, 12.0), 0.0)
    p = np.maximum(0.0, ei * (eg * K_F * i * vg - 1.5 * i * i * R_PH))
    p = np.where(vg > 0, p, 0.0)
    segs = []
    on = p > 0.05
    k = 0
    n = len(p)
    while k < n:
        if on[k]:
            j = k
            while j < n and (on[j] or (j + 50 < n and on[j:j + 50].any())):
                j += 1
            segs.append((tg[k], p[k:j].copy()))
            k = j
        else:
            k += 1
    return segs, float(p.sum() * 1e-3)


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    summary = {"constants": dict(V_H1R=V_H1R, VBUS=VBUS, ACC=ACC, P_FC_ICHG=round(P_FC_ICHG, 4), R_PATH=R_PATH,
                                 TAU_CHG=TAU_CHG, I_HK=I_HK, RATCHET_V=RATCHET_V, chargers=CHARGERS, ovp=OVP,
                                 chop={k: v for k, v in CHOP.items() if k != "none"})}
    log("Sim 7 raise latency. P_FC_ICHG = %.3f W; stage-1 VINDPM corners %s" % (P_FC_ICHG, STAGE1))

    # ---------------- Part 0: cross-check against sim 6 Part E (results_staged.csv)
    xs = []
    with open(os.path.join(SIM, "regen_nocut", "results_staged.csv")) as f:
        ref = list(csv.DictReader(f))
    modes = {"400kHz": (0.85, 1.5e-3), "100kHz": (0.30, 1.5e-3), "100kHz_2ms": (0.30, 2.0e-3)}
    cs, keys = [], []
    for r in ref:
        if r["mode"] not in modes:
            continue
        for ck, ch in sim6.CHARGERS.items():
            ip, tl = modes[r["mode"]]
            cs.append(base_case(kind=0, v0=3.00, v1=0.5, icmd=12.0, C=sim6.C_NODE[r["c"]], tlat=tl, ipre=ip,
                                acc=1.0, adv=0.0, pcap_pre=ch["p"], ppost=ch["p"], ilim=ch["ilim"], vind1=ch["vindpm"],
                                vind2=ch["vindpm"], tau=0.0, rpath=0.0, chop="none", ihk=0.0,
                                eg=float(r["eta_gear"]), ei=float(r["eta_inv"])))
            keys.append((r, ck))
    O = simulate(cs, t_max=1.5)
    worst = 0.0
    for (r, ck), vm in zip(keys, O["Vmax"]):
        d = vm - float(r["vmax_3mps_%s_V" % ck])
        worst = max(worst, abs(d))
        xs.append(dict(eta_gear=r["eta_gear"], eta_inv=r["eta_inv"], c=r["c"], mode=r["mode"], charger=ck,
                       vmax_sim6_V=r["vmax_3mps_%s_V" % ck], vmax_sim7_V=round(vm, 4), diff_mV=round(1e3 * d, 2)))
    write_csv("results_crosscheck_sim6.csv", xs)
    log("Part 0 cross-check vs sim 6 Part E: %d cases, worst |dV| = %.1f mV" % (len(xs), 1e3 * worst))
    summary["crosscheck_worst_mV"] = round(1e3 * worst, 2)

    # ---------------- Part A: peak / crossing grid (no trips, no cut, H-hi chopper), every corner
    TL = [0.0, 0.25e-3, 0.5e-3, 0.75e-3, 1.0e-3, 1.25e-3, 1.36e-3, 1.5e-3, 1.75e-3, 2.0e-3, 2.5e-3, 3.0e-3, 3.5e-3,
          4.0e-3, 5.0e-3, 6.0e-3, 7.0e-3, 10e-3, 15e-3, 20e-3, 30e-3, 50e-3]
    PRE = {"FF0.90": dict(ipre=I_FF), "floor0.30": dict(ipre=I_FLOOR)}
    BRAKES = MECH + [(n, None, None, None) for n, _p, _d in CP]
    cs, meta = [], []
    for tl in TL:
        for pk, pkw in PRE.items():
            for cn, c in sim6.C_NODE.items():
                for ck in CHARGERS:
                    for b in BRAKES:
                        cs.append(base_case(C=c, tlat=tl, **pkw, **corner_kw(ck), **brake_kw(b)))
                        meta.append((tl, pk, cn, ck, b[0]))
    log("Part A: %d cases" % len(cs))
    O = simulate(cs, t_max=0.7)
    rows_a = []
    for i, (tl, pk, cn, ck, bn) in enumerate(meta):
        r = dict(t_lat_ms=round(1e3 * tl, 3), pre=pk, c=cn, charger=ck, brake=bn, vmax_V=round(O["Vmax"][i], 4),
                 vmax_during_lat_V=round(O["Vmax_lat"][i], 4), v_at_T3_V=r4(O["V_T3"][i]),
                 e_regen_J=round(O["E_reg"][i], 4), e_harv_J=round(O["E_harv"][i], 4),
                 e_chop_mJ=round(1e3 * O["E_chop"][i], 3), ichop_max_A=round(O["ichop_max"][i], 4))
        for j, th in enumerate(THR):
            r["t_" + th[0] + "_ms"] = r4(1e3 * O["tc"][i, j])
        rows_a.append(r)
    write_csv("results_peak_grid.csv", rows_a)
    log("  Part A done (%.0f s)" % (time.time() - t0))

    # ---------------- Part B: boundaries by bisection (0.01 ms), baseline model
    BTH = [("ceil20p5", 20.5), ("chopHlo", 21.35), ("ovpS5lo", 21.588), ("ovpNoleak", 22.149), ("ovpTyp", 23.188),
           ("ovchg", 24.15)]
    BB = BB_MEAS + ["CP 23 W", "trap25A 2.5->1", "trap25A 3.0->1"]
    bmap = {b[0]: b for b in BRAKES}
    probs, pmeta = [], []
    for thk, thv in BTH:
        for pk, pkw in PRE.items():
            for cn, c in sim6.C_NODE.items():
                for ck in CHARGERS:
                    for bn in BB:
                        probs.append(base_case(C=c, stop_thr=thv, **pkw, **corner_kw(ck), **brake_kw(bmap[bn])))
                        pmeta.append(("baseline", thk, thv, pk, cn, ck, bn))
    # IINDPM at the edge (100 kHz FR-41 ramp race), every measured brake and corner; and the combined worst case
    for thk, thv in BTH[:3]:
        for cn, c in sim6.C_NODE.items():
            for ck in CHARGERS:
                for bn in BB_MEAS:
                    for ie in ISWEEP:
                        probs.append(base_case(C=c, stop_thr=thv, ipre=ie, **corner_kw(ck), **brake_kw(bmap[bn])))
                        pmeta.append(("iedge", thk, thv, "I%.2f" % ie, cn, ck, bn))
                    for pk, pkw in PRE.items():
                        probs.append(base_case(C=c, stop_thr=thv, eg=1.0, ei=1.0, tau=1e-3, **pkw, **corner_kw(ck),
                                               **brake_kw(bmap[bn])))
                        pmeta.append(("worst_eff1_lag1ms", thk, thv, pk, cn, ck, bn))
    # CV phase: absorption bounded by the taper current before and after the raise (latency-independent capacity)
    for it in CV_TAPER_A:
        for thk, thv in (BTH[0], BTH[2]):
            for pk, pkw in PRE.items():
                for cn, c in sim6.C_NODE.items():
                    for bn in ("ML0157 47.30", "ML0151 41.36", "step 2->1"):
                        probs.append(base_case(C=c, stop_thr=thv, pcap_pre=p_cv(it), pcap_post=p_cv(it), **pkw,
                                               **corner_kw("nom"), **brake_kw(bmap[bn])))
                        pmeta.append(("cv_taper_%.1fA" % it, thk, thv, pk, cn, "nom", bn))
    # variants (nominal charger, two thresholds, two brakes)
    VAR = {
        "iindpm_with_reg03": dict(adv=0.0),
        "sim6_basis_acc1_nocap": dict(acc=1.0, pcap_pre=np.inf),
        "eff_1p0": dict(eg=1.0, ei=1.0),
        "climb_from_vbus": dict(V0=VBUS, trise=5e-3),
        "lag_1ms": dict(tau=1e-3),
        "ichg_cap_pack8V": dict(pcap_pre=1.60 * (1 - 0.065) * (8.0 + 1.60 * 0.0326) / 0.93),
        "fc_input_11p2W": dict(pcap_pre=P_FC_INPUT_H7),
    }
    for vk, vkw in VAR.items():
        for thk, thv in BTH[:3]:
            for pk, pkw in PRE.items():
                for cn, c in sim6.C_NODE.items():
                    for bn in ("ML0157 47.30", "CP 23 W"):
                        kw = dict(C=c, stop_thr=thv, **corner_kw("nom"), **brake_kw(bmap[bn]))
                        kw.update(pkw)
                        kw.update(vkw)
                        probs.append(base_case(**kw))
                        pmeta.append((vk, thk, thv, pk, cn, "nom", bn))
    log("Part B: %d bisection problems" % len(probs))
    bnd = bisect_tlat(probs, hi=0.060, tol=1e-5, t_max=0.7)
    rows_b = []
    for (vk, thk, thv, pk, cn, ck, bn), x in zip(pmeta, bnd):
        rows_b.append(dict(variant=vk, threshold=thk, v_thr=thv, pre=pk, c=cn, charger=ck, brake=bn,
                           t_lat_boundary_ms=("never<=60" if math.isinf(x) else round(1e3 * x, 3))))
    write_csv("results_boundaries.csv", rows_b)
    log("  Part B done (%.0f s)" % (time.time() - t0))

    # ---------------- Part C: consequences (trip, chopper, VESC cut) -> harvest loss per brake
    SCN = {
        "nom": dict(chop="H-typ", ovp=OVP["typ"], vcut=np.inf),
        "early_trip": dict(chop="H-hi", ovp=OVP["s5-lo"], vcut=np.inf),
        "early_chop": dict(chop="H-lo", ovp=OVP["s5-hi"], vcut=np.inf),
        "cut21.35": dict(chop="H-typ", ovp=OVP["typ"], vcut=21.35),
        "cut22": dict(chop="H-typ", ovp=OVP["typ"], vcut=22.0),
        "cut23": dict(chop="H-typ", ovp=OVP["typ"], vcut=23.0),
        "cut24": dict(chop="H-typ", ovp=OVP["typ"], vcut=24.0),
    }
    TLC = [0.0, 0.5e-3, 1.0e-3, 1.36e-3, 1.5e-3, 2.0e-3, 2.5e-3, 3.0e-3, 4.0e-3, 5.0e-3, 7.0e-3, 10e-3, 15e-3,
           20e-3, 30e-3, 50e-3]
    cs, meta = [], []
    for tl in TLC:
        for pk, pkw in PRE.items():
            for cn, c in sim6.C_NODE.items():
                for sk, skw in SCN.items():
                    for b in BRAKES:
                        cs.append(base_case(C=c, tlat=tl, **pkw, **corner_kw("nom"), **brake_kw(b), **skw))
                        meta.append((tl, pk, cn, sk, b[0]))
    log("Part C: %d cases" % len(cs))
    O = simulate(cs, t_max=1.3)
    ref = {}
    for i, (tl, pk, cn, sk, bn) in enumerate(meta):
        if tl == 0.0:
            ref[(pk, cn, sk, bn)] = (O["E_harv"][i], O["E_reg"][i])
    rows_c = []
    for i, (tl, pk, cn, sk, bn) in enumerate(meta):
        eh0, er0 = ref[(pk, cn, sk, bn)]
        loss = eh0 - O["E_harv"][i]
        rows_c.append(dict(t_lat_ms=round(1e3 * tl, 3), pre=pk, c=cn, scenario=sk, brake=bn,
                           vmax_V=round(O["Vmax"][i], 4), e_regen_ref_J=round(er0, 4), e_regen_J=round(O["E_reg"][i], 4),
                           e_harv_ref_J=round(eh0, 4), e_harv_J=round(O["E_harv"][i], 4), loss_J=round(loss, 4),
                           loss_pct_of_regen=round(100 * loss / er0, 3) if er0 > 0 else 0.0,
                           e_chop_mJ=round(1e3 * O["E_chop"][i], 3), ichop_max_A=round(O["ichop_max"][i], 4),
                           t_chop_above_0p47A_ms=round(1e3 * O["t_chop_hi"][i], 3),
                           u101_trip=int(np.isfinite(O["t_trip"][i])), t_trip_ms=r4(1e3 * O["t_trip"][i]),
                           vesc_cuts=int(O["ncut"][i]), ovchg_state99=int(np.isfinite(O["tc"][i, 7])),
                           ge30V=int(O["Vmax"][i] >= 30.0), ge33V=int(O["Vmax"][i] >= 33.0)))
    write_csv("results_consequence.csv", rows_c)
    log("  Part C done (%.0f s)" % (time.time() - t0))

    # ---------------- Part D: 12 A start-speed sweep (1.0-4.5 m/s, to 1.0 m/s; v0 = 1.0 is no brake), crossing grid
    V0S = [round(1.0 + 0.25 * k, 2) for k in range(15)]
    TLD = [0.0, 1.0e-3, 1.36e-3, 1.5e-3, 2.0e-3, 3.0e-3, 5.0e-3, 10e-3, 20e-3]
    cs, meta = [], []
    for tl in TLD:
        for pk, pkw in PRE.items():
            for cn, c in sim6.C_NODE.items():
                for v0 in V0S:
                    cs.append(base_case(C=c, tlat=tl, kind=0, v0=v0, v1=min(1.0, v0), **pkw, **corner_kw("nom")))
                    meta.append((tl, pk, cn, v0))
    log("Part D: %d cases" % len(cs))
    O = simulate(cs, t_max=1.3)
    rows_d = []
    for i, (tl, pk, cn, v0) in enumerate(meta):
        rows_d.append(dict(t_lat_ms=round(1e3 * tl, 3), pre=pk, c=cn, v0=v0,
                           p0_W=round(sim6.brake_p(v0, 12.0, V_H1R)[0], 3), vmax_V=round(O["Vmax"][i], 4)))
    write_csv("results_speed_sweep.csv", rows_d)
    log("  Part D done (%.0f s)" % (time.time() - t0))

    # ---------------- Part E: drive cycles (sim 6 Part C cycles, ideal tracking), harvest loss per cycle
    cyc = {}
    for fn in sorted(os.listdir(os.path.join(REPO, "references", "drive_cycles"))):
        if fn.endswith(".csv"):
            segs, etot = cycle_segments(fn)
            cyc[fn] = (segs, etot)
            log("  cycle %-28s regen %.3f J, %d brake segments, peak %.2f W" %
                (fn, etot, len(segs), max([s[1].max() for s in segs]) if segs else 0.0))
    seg_idx = {}
    for fn, (segs, _e) in cyc.items():
        for j, (ts, arr) in enumerate(segs):
            seg_idx[(fn, j)] = add_profile(arr)
    SCE = {k: SCN[k] for k in ("nom", "early_trip", "cut21.35")}
    cs, meta = [], []
    for tl in TLC:
        for pk, pkw in PRE.items():
            for cn, c in sim6.C_NODE.items():
                for sk, skw in SCE.items():
                    for (fn, j), pi in seg_idx.items():
                        cs.append(base_case(C=c, tlat=tl, kind=1, prof=pi, V0=VBUS, **pkw, **corner_kw("nom"), **skw))
                        meta.append((tl, pk, cn, sk, fn, j))
    log("Part E: %d cases" % len(cs))
    rows_e = []
    if cs:
        tmax = max(len(PROFILES[i]) for i in seg_idx.values()) * 1e-3 + 0.1
        O = simulate(cs, t_max=tmax)
        agg = {}
        for i, (tl, pk, cn, sk, fn, j) in enumerate(meta):
            a = agg.setdefault((tl, pk, cn, sk, fn), dict(eh=0.0, er=0.0, vmax=0.0, trips=0, cuts=0, s99=0, nedge=0))
            a["eh"] += O["E_harv"][i]
            a["er"] += O["E_reg"][i]
            a["vmax"] = max(a["vmax"], O["Vmax"][i])
            a["trips"] += int(np.isfinite(O["t_trip"][i]))
            a["cuts"] += int(O["ncut"][i])
            a["s99"] += int(np.isfinite(O["tc"][i, 7]))
            a["nedge"] += int(np.isfinite(O["t_edge"][i]))
        for (tl, pk, cn, sk, fn), a in agg.items():
            a0 = agg[(0.0, pk, cn, sk, fn)]
            loss = a0["eh"] - a["eh"]
            rows_e.append(dict(t_lat_ms=round(1e3 * tl, 3), pre=pk, c=cn, scenario=sk, cycle=fn,
                               e_regen_cycle_J=round(cyc[fn][1], 3), e_regen_sim_J=round(a["er"], 4),
                               e_harv_J=round(a["eh"], 4), loss_J=round(loss, 4),
                               loss_pct_of_cycle_regen=round(100 * loss / cyc[fn][1], 3) if cyc[fn][1] > 0 else 0.0,
                               vmax_V=round(a["vmax"], 4), h1_edges=a["nedge"], u101_trips=a["trips"],
                               vesc_cuts=a["cuts"], ovchg_state99=a["s99"]))
        write_csv("results_drive_cycles.csv", rows_e)
    summary["cycles"] = {fn: dict(e_regen_J=round(e, 3), n_segments=len(s)) for fn, (s, e) in cyc.items()}
    log("  Part E done (%.0f s)" % (time.time() - t0))

    # ---------------- Part F: regen-armed cruise (no T3): converter-release dead time t_d from the H1 rise
    cs, meta = [], []
    for td in TL:
        for cn, c in sim6.C_NODE.items():
            for b in ("ML0157 47.30", "CP 18.9 W", "CP 23 W"):
                ch = CHARGERS["nom"]
                cs.append(base_case(C=c, tlat=td, regen_armed=1, vind1=ch["vind2"], vind2=ch["vind2"],
                                    **{k: v for k, v in corner_kw("nom").items() if k not in ("vind1", "vind2")},
                                    **brake_kw(bmap[b])))
                meta.append((td, cn, b))
    O = simulate(cs, t_max=0.7)
    rows_f = [dict(dead_time_ms=round(1e3 * td, 3), c=cn, brake=b, vmax_V=round(O["Vmax"][i], 4))
              for i, (td, cn, b) in enumerate(meta)]
    write_csv("results_regen_armed.csv", rows_f)
    log("  Part F done (%.0f s)" % (time.time() - t0))

    # ---------------- Part G: design rows as functions of T_lat (closed forms and a pre-raise ODE)
    rows_g = design_rows()
    write_csv("results_design_rows.csv", rows_g)
    summary["tdd12_ms_from_false_restore_to_20p5V"] = tdd12_time_to_ceiling()
    log("T-D-12 time from false restore to 20.5 V (ms): %s" % summary["tdd12_ms_from_false_restore_to_20p5V"])
    summary["i_floor_none_beyond_ms"] = i_floor_limit()
    log("Pre-raise phase, IINDPM 0.90 A with the ICHG cap: time from the H1 rise to 20.5 V (ms): %s"
        % summary["i_floor_none_beyond_ms"])

    # ---------------- Part H: architecture table (100 kHz, existing pull-ups; bus terms from i2c_facts_100k_out.txt)
    arch = [
        ("a  pin-34 ISR + r8 queue priority + 0.50 ms cap (current design)", 1.359, 1.539),
        ("a' as (a), in-flight term = W(REG03-05)", 1.329, 1.505),
        ("a'' as (a), idle bus", 0.859, 0.973),
        ("b1 ISR + priority, no cap/abort, R(REG1B-21) in flight", 1.789, 2.027),
        ("b2 ISR + priority, no cap/abort, R(REG00-0A) unsplit", 2.149, 2.435),
        ("e  ISR, FIFO, one FR-41 ramp group ahead", 2.329, 2.638),
        ("c1 no pin ISR, pin 34 polled in the 1 kHz FR-45 timer", 2.359, 2.539),
        ("d  blocking Wire from loop() (5.0 ms FR-27 budget)", 5.859, 5.973),
        ("c2 pin 34 polled in loop() (5.0 ms FR-27 budget)", 6.359, 6.539),
    ]
    summary["architectures"] = [dict(name=a, bus_ms=b, bus_stretched_ms=s) for a, b, s in arch]

    # ---------------- figures and digests
    import pickle
    with open(os.path.join(os.environ.get("RL_CACHE", HERE), "_rows_cache.pkl"), "wb") as f:
        pickle.dump(dict(rows_a=rows_a, rows_b=rows_b, rows_c=rows_c, rows_d=rows_d, rows_e=rows_e, rows_f=rows_f,
                         rows_g=rows_g, arch=arch, summary=summary), f)
    figures(rows_a, rows_b, rows_c, rows_e, rows_f, bmap)
    digest(summary, rows_a, rows_b, rows_c, rows_d, rows_e, rows_f, rows_g, arch)
    with open(os.path.join(HERE, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, default=str)
    log("Total %.0f s" % (time.time() - t0))
    with open(os.path.join(HERE, "run_log.txt"), "w") as f:
        f.write("\n".join(LOG) + "\n")


def pre_raise_ode(P, C, I, t_end, v0=V_H1R, pcap=P_FC_ICHG, acc=ACC, dt=1e-6):
    """Constant-power brake, constant pre-raise IINDPM I (vectorised over arrays), no chopper. V at t_end."""
    V = np.full(np.broadcast(P, C, I, t_end).shape, v0, float)
    P = np.broadcast_to(P, V.shape)
    C = np.broadcast_to(C, V.shape)
    I = np.broadcast_to(I, V.shape)
    te = np.broadcast_to(t_end, V.shape)
    n = int(np.max(te) / dt) + 1
    for k in range(n):
        live = k * dt < te
        dv = (P / V - np.minimum(I * acc, pcap / V) - I_HK) / C * dt
        V = np.where(live, np.maximum(V + dv, VBUS), V)
    return V


def design_rows():
    rows = []
    TLG = np.array([0.5, 1.0, 1.359, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 20.0, 50.0]) * 1e-3
    for P in (18.9, 23.0):
        for cn, C in (("0.4mF", 0.4e-3), ("0.97mF", 0.97e-3)):
            # I_floor, doc linear form (H.20 / line 2768)
            i_doc = np.maximum(0.0, (P / V_H1R - (20.5 - V_H1R) * C / TLG) / 0.88)
            # I_floor, pre-raise ODE with the FC-image ICHG cap: bisection on I in [0, 0.90]
            lo = np.zeros_like(TLG)
            hi = np.full_like(TLG, 0.90)
            v_hi = pre_raise_ode(P, C, hi, TLG)
            feasible = v_hi < 20.5
            for _ in range(14):
                mid = 0.5 * (lo + hi)
                vm = pre_raise_ode(P, C, mid, TLG)
                ok = vm < 20.5
                hi = np.where(ok, mid, hi)
                lo = np.where(ok, lo, mid)
            i_ode = np.where(feasible, hi, np.nan)
            i_ode = np.where(pre_raise_ode(P, C, np.zeros_like(TLG), TLG) < 20.5, 0.0, i_ode)
            # I_ff upper bound (H.21(a)): P_allow = V_H1R (0.30 x 0.88 + 2.45 C / t); I_ff,max = 12 A x P_allow / 23 W
            p_allow = V_H1R * (0.30 * 0.88 + (20.5 - V_H1R) * C / TLG)
            iff_max = 12.0 * p_allow / 23.0
            # T-D-12 false restore from V_hold 19.72 V, FC image 0.90 A absorbing, detect tick 1.0 ms + T_lat
            vtd_doc = pre_raise_ode(P, C, 0.90, 1.0e-3 + TLG, v0=19.72, pcap=np.inf)
            vtd_cap = pre_raise_ode(P, C, 0.90, 1.0e-3 + TLG, v0=19.72)
            # H.19 sag drain while the FC image runs from V-MOT
            sag = 0.9 * TLG / C
            for k, tl in enumerate(TLG):
                rows.append(dict(p_W=P, c=cn, t_lat_ms=round(1e3 * tl, 3), i_floor_doc_A=round(i_doc[k], 4),
                                 i_floor_ode_capped_A=("none<=0.90" if np.isnan(i_ode[k]) else round(i_ode[k], 4)),
                                 window_impossible_doc=int(i_doc[k] + 0.10 > 1.05),
                                 p_allow_W=round(p_allow[k], 3), i_ff_max_A=round(iff_max[k], 3),
                                 tdd12_vpeak_doc_V=round(vtd_doc[k], 3), tdd12_vpeak_capped_V=round(vtd_cap[k], 3),
                                 sag_drain_V=round(sag[k], 3)))
    return rows


def tdd12_time_to_ceiling():
    """T-D-12: time from the false restore (V_hold 19.72 V, FC image absorbing) to 20.5 V; doc form (0.90 A x 0.88)
    and with the FC-image ICHG cap. The detect tick (<= 1 ms) plus T_lat must stay below it."""
    out = {}
    tg = np.arange(0.0, 20e-3, 1e-5)
    for P in (18.9, 23.0):
        for cn, C in (("0.4mF", 0.4e-3), ("0.97mF", 0.97e-3)):
            for lab, pc in (("doc", np.inf), ("capped", P_FC_ICHG)):
                v = pre_raise_ode(P, C, 0.90, tg, v0=19.72, pcap=pc)
                k = np.argmax(v >= 20.5)
                out["%g W %s %s" % (P, cn, lab)] = round(1e3 * tg[k], 3) if v[k] >= 20.5 else ">20"
    return out


def i_floor_limit():
    """Latency beyond which no pre-raise IINDPM <= 0.90 A keeps V-MOT below 20.5 V during the latency (pre-raise phase
    only, constant-power brake, FC-image ICHG cap): the time from the H1 rise to 20.5 V at IINDPM 0.90 A."""
    out = {}
    tg = np.arange(0.0, 20e-3, 1e-5)
    for P in (18.9, 23.0):
        for cn, C in (("0.4mF", 0.4e-3), ("0.97mF", 0.97e-3)):
            v = pre_raise_ode(P, C, 0.90, tg)
            k = np.argmax(v >= 20.5)
            out["%g W %s" % (P, cn)] = round(1e3 * tg[k], 2) if v[k] >= 20.5 else ">20"
    return out


# ---------------------------------------------------------------- figures
COL ={"FF0.90": "#2F6B2A", "floor0.30": "#C00000"}


def figures(rows_a, rows_b, rows_c, rows_e, rows_f, bmap):
    # (a) V-MOT peak vs T_lat, nominal charger, per pre-case and C; worst over brakes and selected brakes
    fig, axs = plt.subplots(2, 2, figsize=(13, 9), sharex=True)
    sel = [("ML0157 47.30", "-"), ("ML0151 41.36", "--"), ("step 2->1", ":"), ("CP 23 W", "-."),
           ("trap25A 2.5->1", (0, (1, 1)))]
    for a, pk in enumerate(("FF0.90", "floor0.30")):
        for b, cn in enumerate(("0.4mF", "0.97mF")):
            ax = axs[a][b]
            ax.axhspan(21.35, 23.095, color="#F4B183", alpha=0.35, lw=0)
            ax.axhspan(21.588, 25.019, color="#9DC3E6", alpha=0.30, lw=0)
            ax.axhline(20.5, color="k", lw=1.0, ls="--")
            ax.axhline(24.15, color="#7030A0", lw=1.0, ls="--")
            for bn, ls in sel:
                rr = [r for r in rows_a if r["pre"] == pk and r["c"] == cn and r["charger"] == "nom" and r["brake"] == bn]
                ax.plot([max(r["t_lat_ms"], 0.1) for r in rr], [r["vmax_V"] for r in rr], ls=ls, lw=1.5,
                        label="%s (%.1f W)" % (bn, sim6.brake_p(bmap[bn][1], bmap[bn][3], V_H1R)[0] if bmap[bn][1]
                                                 else float(bn.split()[1])))
            rr = [r for r in rows_a if r["pre"] == pk and r["c"] == cn and r["charger"] == "lo" and r["brake"] == "ML0157 47.30"]
            ax.plot([max(r["t_lat_ms"], 0.1) for r in rr], [r["vmax_V"] for r in rr], color="grey", lw=1.0,
                    label="ML0157, charger lo corner")
            ax.set_xscale("log")
            ax.set_ylim(17.8, 31)
            ax.grid(alpha=0.3, which="both")
            ax.set_title("pre-raise %s (IINDPM written first), C_VMOT %s, charger nom (H-hi chopper, no trip/cut)"
                         % (pk, cn), fontsize=9)
            ax.text(0.11, 20.6, "20.5 V test acceptance", fontsize=8)
            ax.text(0.11, 22.2, "chopper onset band 21.35-23.10 V", fontsize=8, color="#843C0C")
            ax.text(0.11, 24.3, "OV_CHG State 99 24.15 V; U101 OVP band 21.59-25.02 V (blue)", fontsize=8,
                    color="#7030A0")
            if a == 1:
                ax.set_xlabel("raise latency T_lat, H1 edge to raised image (ms, log; 0 plotted at 0.1)")
            if b == 0:
                ax.set_ylabel("V-MOT peak (V)")
            if a == 0 and b == 0:
                ax.legend(fontsize=7.5, loc="lower right")
    fig.suptitle("Figure 1: V-MOT peak over the whole brake vs raise latency (baseline model)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig1_vpeak_vs_latency.png"), dpi=140)
    plt.close(fig)

    # (b) harvest loss vs T_lat
    fig, axs = plt.subplots(1, 3, figsize=(16.5, 4.8))
    for ax, (bn, cn) in zip(axs[:2], (("ML0157 47.30", "0.4mF"), ("ML0157 47.30", "0.97mF"))):
        for sk, ls in (("nom", "-"), ("early_trip", "--"), ("early_chop", ":"), ("cut21.35", "-."), ("cut23", (0, (3, 1, 1, 1)))):
            for pk in ("FF0.90", "floor0.30"):
                rr = [r for r in rows_c if r["brake"] == bn and r["c"] == cn and r["scenario"] == sk and r["pre"] == pk]
                ax.plot([max(r["t_lat_ms"], 0.1) for r in rr], [r["loss_pct_of_regen"] for r in rr], ls=ls,
                        color=COL[pk], lw=1.4, label="%s, %s" % (pk, sk))
        ax.set_xscale("log")
        ax.set_ylabel("harvest loss (% of the brake's regen energy)")
        ax.set_xlabel("T_lat (ms, log)")
        ax.grid(alpha=0.3, which="both")
        ax.set_title("(%s) ML0157 3.00->1.90 m/s, 12 A, %s" % ("a" if cn == "0.4mF" else "b", cn), fontsize=9.5)
    axs[0].legend(fontsize=7, loc="upper left")
    ax = axs[2]
    for sk, ls in (("nom", "-"), ("early_trip", "--"), ("cut21.35", "-.")):
        for pk in ("FF0.90", "floor0.30"):
            for cn, mk in (("0.4mF", "o"), ("0.97mF", "s")):
                rr = [r for r in rows_e if r["cycle"].startswith("RegenTest_decel") and r["scenario"] == sk
                      and r["pre"] == pk and r["c"] == cn]
                ax.plot([max(r["t_lat_ms"], 0.1) for r in rr], [r["loss_pct_of_cycle_regen"] for r in rr], ls=ls,
                        marker=mk, ms=3, color=COL[pk], lw=1.2, label="%s %s %s" % (pk, cn, sk))
    ax.set_xscale("log")
    ax.set_xlabel("T_lat (ms, log)")
    ax.set_ylabel("harvest loss (% of the cycle's regen energy)")
    ax.grid(alpha=0.3, which="both")
    ax.set_title("(c) RegenTest_decel_sweep, every brake inside an FC window", fontsize=9.5)
    ax.legend(fontsize=6.5, loc="upper left")
    fig.suptitle("Figure 2: harvest loss vs raise latency (charger nom, loss against T_lat = 0)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig2_harvest_loss_vs_latency.png"), dpi=140)
    plt.close(fig)

    # (c) time traces of the worst case at 1.5 ms vs the boundary latency (bisection result)
    def bnd(pk, thk, cn="0.4mF", bn="ML0157 47.30"):
        for r in rows_b:
            if (r["variant"] == "baseline" and r["pre"] == pk and r["threshold"] == thk and r["c"] == cn
                    and r["charger"] == "nom" and r["brake"] == bn):
                return r["t_lat_boundary_ms"]
    traces = []   # (pre, T_lat ms, role): 1.5 ms; the 20.5 V boundary; 0.05 ms past the U101 s5-lo boundary
    for pk in ("floor0.30", "FF0.90"):
        traces.append((pk, 1.5, "1.5 ms"))
        traces.append((pk, bnd(pk, "ceil20p5"), "20.5 V boundary"))
        traces.append((pk, round(bnd(pk, "ovpS5lo") + 0.05, 3), "0.05 ms past U101 boundary"))
    ROLE_LS = {"1.5 ms": "-", "20.5 V boundary": ":", "0.05 ms past U101 boundary": "--"}
    cs = [base_case(C=0.4e-3, tlat=tl * 1e-3, ipre=(I_FF if pk == "FF0.90" else I_FLOOR), chop="H-hi",
                    ovp=OVP["s5-lo"], **corner_kw("nom"), **brake_kw(bmap["ML0157 47.30"]))
          for pk, tl, _r in traces]
    O = simulate(cs, t_max=0.08, record=list(range(len(cs))), rec_every=5)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    for i, (pk, tl, role) in enumerate(traces):
        tr = O["rec"][i]
        m = tr[:, 0] <= 0.020
        lab = "%s, T_lat %.2f ms, %s (peak %.2f V)" % (pk, tl, role, O["Vmax"][i])
        ax1.plot(1e3 * tr[m, 0], tr[m, 1], color=COL[pk], lw=1.3, ls=ROLE_LS[role], label=lab)
        ax2.plot(1e3 * tr[m, 0], tr[m, 2], color=COL[pk], lw=1.3, ls=ROLE_LS[role], label=lab)
    for v, txt in ((20.5, "20.5 V"), (21.588, "U101 OVP s5-lo 21.588 V"), (23.095, "H-hi chopper onset")):
        ax1.axhline(v, color="k", lw=0.8, ls=":")
        ax1.text(8.0, v + 0.05, txt, fontsize=8)
    ax1.set_xlabel("time from the H1 edge (ms)")
    ax1.set_ylabel("V-MOT (V)")
    ax1.set_xlim(0, 20)
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=6.5, loc="upper left")
    ax1.set_ylim(17.5, 32)
    ax1.set_title("(a) V-MOT, ML0157 18.95 W brake, 0.4 mF, nominal charger, H-hi + OVP s5-lo", fontsize=9.5)
    ax2.set_xlabel("time from the H1 edge (ms)")
    ax2.set_ylabel("charger input current (A)")
    ax2.set_xlim(0, 20)
    ax2.grid(alpha=0.3)
    ax2.set_title("(b) charger input current (drops to 0 at a U101 trip)", fontsize=9.5)
    fig.suptitle("Figure 3: time traces, 0-20 ms of a 0.31 s brake (the run continues to the brake end)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig3_traces.png"), dpi=140)
    plt.close(fig)

    # (d) regen-armed dead-time line
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for b in ("ML0157 47.30", "CP 18.9 W", "CP 23 W"):
        for cn, ls in (("0.4mF", "-"), ("0.97mF", "--")):
            rr = [r for r in rows_f if r["brake"] == b and r["c"] == cn]
            ax.plot([max(r["dead_time_ms"], 0.1) for r in rr], [r["vmax_V"] for r in rr], ls=ls, lw=1.3,
                    label="%s %s" % (b, cn))
    ax.axhline(20.5, color="k", ls="--", lw=0.9)
    ax.set_xscale("log")
    ax.set_ylim(18, 31)
    ax.set_xlabel("converter release dead time after H1 (ms, log); not the I2C latency")
    ax.set_ylabel("V-MOT peak (V)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7)
    ax.set_title("Figure 4: regen-armed cruise, no T3; peak vs converter dead time", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig4_regen_armed_deadtime.png"), dpi=140)
    plt.close(fig)

    # (e) boundary latency against IINDPM at the edge (min over the measured brakes and the four corners)
    def bmin_e(vk, pk, thk, cn):
        xs = [r["t_lat_boundary_ms"] for r in rows_b if r["variant"] == vk and r["pre"] == pk and r["threshold"] == thk
              and r["c"] == cn and r["brake"] in BB_MEAS]
        xs = [x for x in xs if not isinstance(x, str)]
        return min(xs) if xs else np.nan
    LV = [(0.30, "baseline", "floor0.30")] + [(ie, "iedge", "I%.2f" % ie) for ie in ISWEEP] + \
        [(0.90, "baseline", "FF0.90")]
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.8))
    for ax, cn in zip(axs, ("0.4mF", "0.97mF")):
        for thk, lab, ls in (("ceil20p5", "20.5 V test acceptance", "-"), ("chopHlo", "21.35 V chopper H-lo onset", ":"),
                             ("ovpS5lo", "21.588 V U101 OVP s5-lo (first trip)", "--")):
            ax.plot([lv[0] for lv in LV], [bmin_e(vk, pk, thk, cn) for _i, vk, pk in LV], ls=ls, marker="o", ms=4,
                    lw=1.5, color="k", label=lab)
        for name, s, col in (("a (current design)", 1.539, "#C00000"), ("c1 (1 kHz poll)", 2.539, "#2F6B2A"),
                             ("a'' (idle bus)", 0.973, "#1F4E79")):
            ax.axhline(s, color=col, lw=1.0, ls="-.")
            ax.text(0.305, s + 0.05, "%s, stretched %.3f ms" % (name, s), fontsize=7.5, color=col)
        ax.set_xlabel("IINDPM in force at the H1 edge (A); ICHG (11.99 W) binds above about 0.72 A")
        ax.set_ylabel("boundary latency T_lat (ms)")
        ax.grid(alpha=0.3)
        ax.set_title("(%s) C_VMOT %s, minimum over the measured brakes and the four corners"
                     % ("a" if cn == "0.4mF" else "b", cn), fontsize=9.5)
        ax.legend(fontsize=7.5, loc="lower right")
    fig.suptitle("Figure 5: boundary latency against IINDPM at the edge (IINDPM written first, efficiency 0.9 / 0.97)",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig5_boundary_vs_iindpm_at_edge.png"), dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------- digest
def digest(summary, rows_a, rows_b, rows_c, rows_d, rows_e, rows_f, rows_g, arch):
    """Digest of every table quoted in RESULTS.md. Markdown tables are logged verbatim and written to tables.md."""
    MD = []

    def md(s=""):
        MD.append(s)
        log(s)

    def B(variant, thk, pk, cn, ck="nom", bn="ML0157 47.30"):
        for r in rows_b:
            if (r["variant"], r["threshold"], r["pre"], r["c"], r["charger"], r["brake"]) == (variant, thk, pk, cn, ck, bn):
                return r["t_lat_boundary_ms"]

    def bmin(variant, thk, pk, cn, brakes=None, chargers=None):
        """min boundary over brakes x corners; returns (value or inf, argmin brake, argmin corner)."""
        best = (math.inf, None, None)
        for r in rows_b:
            if r["variant"] != variant or r["threshold"] != thk or r["pre"] != pk or r["c"] != cn:
                continue
            if brakes is not None and r["brake"] not in brakes:
                continue
            if chargers is not None and r["charger"] not in chargers:
                continue
            x = r["t_lat_boundary_ms"]
            x = math.inf if isinstance(x, str) else x
            if x < best[0] or best[1] is None:
                best = (x, r["brake"], r["charger"])
        return best

    def fmt(x):
        return "never (<= 60)" if math.isinf(x) else ("%.2f" % x)

    THK_ALL = ["ceil20p5", "chopHlo", "ovpS5lo", "ovpNoleak", "ovpTyp", "ovchg"]
    THL = {"ceil20p5": "20.5 V test acceptance", "chopHlo": "21.35 V chopper H-lo onset",
           "ovpS5lo": "21.588 V U101 OVP rising min, with leak", "ovpNoleak": "22.149 V U101 OVP rising min, no leak",
           "ovpTyp": "23.188 V U101 OVP typical", "ovchg": "24.15 V FR-50 OV_CHG, no prior U101 trip"}
    THS = {"ceil20p5": "20.5 V", "chopHlo": "21.35 V", "ovpS5lo": "U101 s5-lo", "ovpNoleak": "U101 no-leak min",
           "ovpTyp": "U101 typ", "ovchg": "OV_CHG"}

    # ---------------- Table 1
    T1 = {}
    md("")
    md("=== TABLE 1 (min over BB_MEAS x 4 corners)")
    md("| First crossing of | FF landed 0.4 mF | FF landed 0.97 mF | Floor 0.30 A 0.4 mF | Floor 0.30 A 0.97 mF | "
       "Worst case FF 0.4 mF | Worst case floor 0.4 mF |")
    md("|---|---|---|---|---|---|---|")
    for thk in THK_ALL:
        cells = []
        for pk in ("FF0.90", "floor0.30"):
            for cn in ("0.4mF", "0.97mF"):
                x, bn, ck = bmin("baseline", thk, pk, cn, BB_MEAS)
                T1["%s|%s|%s" % (thk, pk, cn)] = dict(min_ms=x, brake=bn, corner=ck)
                cells.append(fmt(x))
        for pk in ("FF0.90", "floor0.30"):
            x, bn, ck = bmin("worst_eff1_lag1ms", thk, pk, "0.4mF", BB_MEAS)
            T1["worst|%s|%s|0.4mF" % (thk, pk)] = dict(min_ms=x, brake=bn, corner=ck)
            cells.append(fmt(x) if bn is not None else "-")
        md("| %s | %s |" % (THL[thk], " | ".join(cells)))
    md("argmin brake/corner:")
    for k, v in T1.items():
        md("  %-30s %s %s %s" % (k, fmt(v["min_ms"]), v["brake"], v["corner"]))
    for cn in ("0.97mF",):
        for pk in ("FF0.90", "floor0.30"):
            for thk in THK_ALL[:3]:
                x, bn, ck = bmin("worst_eff1_lag1ms", thk, pk, cn, BB_MEAS)
                T1["worst|%s|%s|%s" % (thk, pk, cn)] = dict(min_ms=x, brake=bn, corner=ck)
                md("  worst-case %s %s %s: %s (%s, %s)" % (thk, pk, cn, fmt(x), bn, ck))
    summary["table1"] = {k: dict(v, min_ms=("never" if math.isinf(v["min_ms"]) else v["min_ms"])) for k, v in T1.items()}

    # ---------------- Table: boundary vs IINDPM at the edge
    LV = [(0.30, "baseline", "floor0.30")] + [(ie, "iedge", "I%.2f" % ie) for ie in ISWEEP] + [(0.90, "baseline", "FF0.90")]
    TI = {}
    md("")
    md("=== TABLE IEDGE (min over BB_MEAS x 4 corners); 20.5 V / 21.35 V / 21.588 V")
    md("| IINDPM at the edge (A) | 0.4 mF | 0.97 mF |")
    md("|---|---|---|")
    for ie, vk, pk in LV:
        cells = []
        for cn in ("0.4mF", "0.97mF"):
            vals = []
            for thk in ("ceil20p5", "chopHlo", "ovpS5lo"):
                x = bmin(vk, thk, pk, cn, BB_MEAS)[0]
                TI[(ie, thk, cn)] = x
                vals.append(fmt(x))
            cells.append(" / ".join(vals))
        md("| %.2f | %s |" % (ie, " | ".join(cells)))
    summary["iedge_boundaries"] = {"%.2f|%s|%s" % k: ("never" if math.isinf(v) else v) for k, v in TI.items()}

    def i_needed(X, thk, cn):
        L = [lv[0] for lv in LV]
        b = [TI[(i, thk, cn)] for i in L]
        if b[0] >= X:
            return "0.30 (floor)"
        if b[-1] < X:
            return "none <= 0.90"
        for k in range(1, len(L)):
            if b[k] >= X:
                if math.isinf(b[k]):
                    return "%.2f" % L[k]
                return "%.2f" % (L[k - 1] + (X - b[k - 1]) / (b[k] - b[k - 1]) * (L[k] - L[k - 1]))

    # ---------------- excluded and capacity-limited cases
    md("")
    md("=== EXCLUDED CASES (baseline, per corner) 20.5 V / 21.588 V")
    md("| Brake | Pre | C | lo | nom | d310 | hi |")
    md("|---|---|---|---|---|---|---|")
    exc = {}
    for bn in ("CP 23 W", "trap25A 2.5->1", "trap25A 3.0->1"):
        for pk in ("FF0.90", "floor0.30"):
            for cn in ("0.4mF", "0.97mF"):
                cells = []
                for ck in CHARGERS:
                    a = B("baseline", "ceil20p5", pk, cn, ck, bn)
                    b = B("baseline", "ovpS5lo", pk, cn, ck, bn)
                    exc["%s|%s|%s|%s" % (bn, pk, cn, ck)] = (a, b)
                    cells.append("%s / %s" % (a, b))
                md("| %s | %s | %s | %s |" % (bn, pk, cn, " | ".join(cells)))
    summary["excluded_cases"] = exc

    # ---------------- CV
    md("")
    md("=== CV PHASE (nom charger) 20.5 V / 21.588 V boundary (ms)")
    md("| Taper current (A) | P_in (W) | Brake | FF 0.4 mF | Floor 0.4 mF | FF 0.97 mF | Floor 0.97 mF |")
    md("|---|---|---|---|---|---|---|")
    cvd = {}
    for it in CV_TAPER_A:
        vk = "cv_taper_%.1fA" % it
        for bn in ("ML0157 47.30", "ML0151 41.36", "step 2->1"):
            cells = []
            for cn in ("0.4mF", "0.97mF"):
                for pk in ("FF0.90", "floor0.30"):
                    a = B(vk, "ceil20p5", pk, cn, "nom", bn)
                    b = B(vk, "ovpS5lo", pk, cn, "nom", bn)
                    cvd["%s|%s|%s|%s" % (vk, bn, pk, cn)] = (a, b)
                    cells.append("%s / %s" % (a, b))
            md("| %.1f | %.2f | %s | %s |" % (it, p_cv(it), bn, " | ".join([cells[0], cells[1], cells[2], cells[3]])))
    summary["cv"] = cvd

    # ---------------- variants
    md("")
    md("=== VARIANTS ML0157 nom 0.4 mF 20.5 / 21.35 / 21.588 (FF | floor)")
    md("| Variant | FF landed | Floor 0.30 A |")
    md("|---|---|---|")
    var = {}
    for vk in ["baseline", "iindpm_with_reg03", "sim6_basis_acc1_nocap", "eff_1p0", "lag_1ms", "climb_from_vbus",
               "ichg_cap_pack8V", "fc_input_11p2W"]:
        cells = []
        for pk in ("FF0.90", "floor0.30"):
            cells.append(" / ".join(str(B(vk, t, pk, "0.4mF")) for t in ("ceil20p5", "chopHlo", "ovpS5lo")))
        md("| %s | %s |" % (vk, " | ".join(cells)))
    for r in rows_b:
        if r["variant"] not in ("baseline", "iedge", "worst_eff1_lag1ms") and not r["variant"].startswith("cv_"):
            var.setdefault(r["variant"], []).append(r)
            log("  %-22s %-9s %-9s %-6s %-14s %s" % (r["variant"], r["threshold"], r["pre"], r["c"], r["brake"],
                                                     r["t_lat_boundary_ms"]))
    summary["variants"] = var

    # ---------------- stats quoted in the text
    st = {}
    # corner spread per brake
    spread = 0.0
    for thk in THK_ALL[:4]:
        for pk in ("FF0.90", "floor0.30"):
            for cn in ("0.4mF", "0.97mF"):
                for bn in BB_MEAS:
                    xs = [B("baseline", thk, pk, cn, ck, bn) for ck in CHARGERS]
                    xs = [x for x in xs if isinstance(x, (int, float))]
                    if len(xs) == 4:
                        spread = max(spread, max(xs) - min(xs))
    st["corner_spread_max_ms"] = round(spread, 3)
    # efficiency 1.0 fall, climb gain (ML0157 nom, both C)
    falls, climbs = [], []
    for pk in ("FF0.90", "floor0.30"):
        for cn in ("0.4mF", "0.97mF"):
            for thk in ("ceil20p5", "chopHlo", "ovpS5lo"):
                b0 = B("baseline", thk, pk, cn)
                be = B("eff_1p0", thk, pk, cn)
                bc = B("climb_from_vbus", thk, pk, cn)
                if isinstance(b0, (int, float)) and isinstance(be, (int, float)) and b0 > 0:
                    falls.append(100 * (1 - be / b0))
                if isinstance(b0, (int, float)) and isinstance(bc, (int, float)):
                    climbs.append(bc - b0)
    st["eff1_fall_pct"] = [round(min(falls), 1), round(max(falls), 1)]
    st["climb_gain_ms"] = [round(min(climbs), 3), round(max(climbs), 3)]
    # losses
    meas = BB_MEAS
    cc = [r for r in rows_c if r["brake"] in meas]
    for pk in ("FF0.90", "floor0.30"):
        for lim in (5.0, 20.0):
            xx = [r for r in cc if r["pre"] == pk and r["t_lat_ms"] <= lim + 1e-9 and not r["u101_trip"]
                  and not r["vesc_cuts"]]
            m = max(xx, key=lambda r: r["loss_pct_of_regen"])
            st["noTripNoCut_%s_le%gms" % (pk, lim)] = dict(pct=m["loss_pct_of_regen"], brake=m["brake"],
                                                           scenario=m["scenario"], c=m["c"], t=m["t_lat_ms"])
    tr = [r for r in cc if r["u101_trip"] and not r["vesc_cuts"]]
    st["trip_noCut_loss_pct"] = [min(r["loss_pct_of_regen"] for r in tr), max(r["loss_pct_of_regen"] for r in tr)]
    st["trip_noCut_vmax_V"] = [min(r["vmax_V"] for r in tr), max(r["vmax_V"] for r in tr)]
    for sk in ("nom", "early_trip", "early_chop"):
        xx = [r for r in tr if r["scenario"] == sk]
        st["trip_noCut_%s_n" % sk] = len(xx)
        st["trip_noCut_%s_ovchg_n" % sk] = sum(r["ovchg_state99"] for r in xx)
        if xx:
            st["trip_noCut_%s_vmax_V" % sk] = [min(r["vmax_V"] for r in xx), max(r["vmax_V"] for r in xx)]
    ct = [r for r in cc if r["vesc_cuts"] and r["t_lat_ms"] > 0]
    st["cut_loss_pct"] = [min(r["loss_pct_of_regen"] for r in ct), max(r["loss_pct_of_regen"] for r in ct)]
    ct157 = [r for r in ct if r["brake"] == "ML0157 47.30"]
    st["cut_loss_pct_ML0157"] = [min(r["loss_pct_of_regen"] for r in ct157), max(r["loss_pct_of_regen"] for r in ct157)]
    ee = [r for r in rows_e if not r["u101_trips"] and not r["vesc_cuts"] and r["t_lat_ms"] <= 20.0 + 1e-9]
    m = max(ee, key=lambda r: r["loss_pct_of_cycle_regen"])
    st["cycle_noTripNoCut_le20ms"] = dict(pct=m["loss_pct_of_cycle_regen"], cycle=m["cycle"], pre=m["pre"], c=m["c"],
                                          scenario=m["scenario"], t=m["t_lat_ms"])
    e157 = [r for r in rows_c if r["brake"] == "ML0157 47.30"]
    st["ML0157_regen_J"] = [min(r["e_regen_ref_J"] for r in e157), max(r["e_regen_ref_J"] for r in e157)]
    summary["stats"] = st
    md("")
    md("=== STATS " + json.dumps(st))

    # ---------------- regen-armed warm-response reconciliation (H.7 start state)
    wr = {}
    for cn, C in sim6.C_NODE.items():
        v_start = 19.38 + 1.1 * R_PATH
        wr[cn] = dict(h7_1p1A_ms=round(1e3 * (20.5 - v_start) * C / 1.1, 3),
                      ml0157_from_vindpm_ms=round(1e3 * (20.5 - v_start) * C / (18.955 / 19.95 - I_HK), 3))
    summary["warm_response_reconciliation"] = wr
    md("=== WARM RESPONSE " + json.dumps(wr))

    # ---------------- decision table
    CAND = [1.0, 1.36, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0]

    def crossed(key, X):
        hit = [THS[t] for t in THK_ALL if key % t in T1 and T1[key % t]["min_ms"] <= X + 1e-9]
        return hit[-1] if hit else "none"

    def vpk(tl, pk, cn):
        rr = [r for r in rows_a if abs(r["t_lat_ms"] - tl) < 1e-6 and r["pre"] == pk and r["c"] == cn
              and r["brake"] in meas]
        return max(r["vmax_V"] for r in rr)

    def loss(tl, pk):
        xx = [r for r in rows_c if abs(r["t_lat_ms"] - tl) < 1e-6 and r["pre"] == pk and r["c"] == "0.4mF"
              and r["brake"] in meas and r["scenario"] in ("nom", "early_trip", "early_chop")]
        m = max(xx, key=lambda r: r["loss_pct_of_regen"])
        s = "%.1f %%" % m["loss_pct_of_regen"]
        if m["u101_trip"]:
            s += " trip" + (" + Run end" if m["ovchg_state99"] else "")
        ee = [r for r in rows_e if abs(r["t_lat_ms"] - tl) < 1e-6 and r["pre"] == pk and r["c"] == "0.4mF"
              and r["cycle"].startswith("RegenTest_decel") and r["scenario"] in ("nom", "early_trip")]
        me = max(ee, key=lambda r: r["loss_pct_of_cycle_regen"])
        return s + " (%.2f %%%s)" % (me["loss_pct_of_cycle_regen"], " T" if me["u101_trips"] else "")

    md("")
    md("=== DECISION TABLE")
    md("| Budget T_lat (ms) | Peak FF 0.4 / 0.97 mF (V) | Peak floor 0.4 / 0.97 mF (V) | IINDPM at edge needed, 0.4 mF: "
       "20.5 V / no U101 trip (A) | Highest threshold crossed, 0.4 mF: FF / floor / worst-case FF | "
       "Worst brake loss, FF (cycle) | Worst brake loss, floor (cycle) | Architectures with stretched time <= budget |")
    md("|---|---|---|---|---|---|---|---|")
    dec = []
    for tl in CAND:
        fit = [a.split()[0] for a, b, s in arch if s <= tl + 1e-9]
        row = dict(t_lat_ms=tl,
                   pk_ff="%.2f / %.2f" % (vpk(tl, "FF0.90", "0.4mF"), vpk(tl, "FF0.90", "0.97mF")),
                   pk_fl="%.2f / %.2f" % (vpk(tl, "floor0.30", "0.4mF"), vpk(tl, "floor0.30", "0.97mF")),
                   ineed="%s / %s" % (i_needed(tl, "ceil20p5", "0.4mF"), i_needed(tl, "ovpS5lo", "0.4mF")),
                   crossed="%s / %s / %s" % (crossed("%s|FF0.90|0.4mF", tl), crossed("%s|floor0.30|0.4mF", tl),
                                             crossed("worst|%s|FF0.90|0.4mF", tl)),
                   loss_ff=loss(tl, "FF0.90"), loss_fl=loss(tl, "floor0.30"),
                   fit=", ".join(fit) if fit else "none")
        dec.append(row)
        md("| %g | %s | %s | %s | %s | %s | %s | %s |" % (tl, row["pk_ff"], row["pk_fl"], row["ineed"], row["crossed"],
                                                         row["loss_ff"], row["loss_fl"], row["fit"]))
    summary["decision"] = dec

    # ---------------- architecture margins
    LIM = [("floor 20.5 V 0.4 mF", T1["ceil20p5|floor0.30|0.4mF"]["min_ms"]),
           ("floor U101 0.4 mF", T1["ovpS5lo|floor0.30|0.4mF"]["min_ms"]),
           ("FF 20.5 V 0.4 mF", T1["ceil20p5|FF0.90|0.4mF"]["min_ms"]),
           ("FF U101 0.4 mF", T1["ovpS5lo|FF0.90|0.4mF"]["min_ms"]),
           ("worst-case FF 20.5 V 0.4 mF", T1["worst|ceil20p5|FF0.90|0.4mF"]["min_ms"]),
           ("FF 20.5 V 0.97 mF", T1["ceil20p5|FF0.90|0.97mF"]["min_ms"])]
    md("")
    md("=== ARCHITECTURE MARGINS (limit - stretched, ms; negative = does not fit)")
    md("| Architecture | Bus | Stretched | " + " | ".join("%s (%s)" % (n, fmt(x)) for n, x in LIM) + " |")
    md("|---|---|---|" + "---|" * len(LIM))
    for a, b, s in arch:
        md("| %s | %.3f | %.3f | %s |" % (a, b, s, " | ".join("%+.2f" % (x - s) for _n, x in LIM)))

    summary["design_rows"] = rows_g
    log("=== design rows (Part G)")
    for r in rows_g:
        log("  " + json.dumps(r))
    log("=== regen-armed dead time (Part F): peaks")
    for r in rows_f:
        if r["dead_time_ms"] in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0):
            log("  td %.2f ms %s %-14s %.3f V" % (r["dead_time_ms"], r["c"], r["brake"], r["vmax_V"]))
    log("=== drive cycles (Part E), loss % of cycle regen")
    for r in rows_e:
        if r["t_lat_ms"] in (1.5, 2.0, 2.5, 3.0, 5.0, 7.0, 10.0, 20.0):
            log("  %-28s %-9s %-6s %-10s T %.2f ms loss %.3f J (%.2f %%) vmax %.2f trips %d cuts %d S99 %d edges %d"
                % (r["cycle"], r["pre"], r["c"], r["scenario"], r["t_lat_ms"], r["loss_J"],
                   r["loss_pct_of_cycle_regen"], r["vmax_V"], r["u101_trips"], r["vesc_cuts"], r["ovchg_state99"],
                   r["h1_edges"]))
    log("=== speed sweep (Part D): highest v0 with peak < 20.5 / < 21.588 V")
    for tl in sorted(set(r["t_lat_ms"] for r in rows_d)):
        for pk in ("FF0.90", "floor0.30"):
            for cn in ("0.4mF", "0.97mF"):
                rr = [r for r in rows_d if r["t_lat_ms"] == tl and r["pre"] == pk and r["c"] == cn]
                a = max([r["v0"] for r in rr if r["vmax_V"] < 20.5], default=None)
                b = max([r["v0"] for r in rr if r["vmax_V"] < 21.588], default=None)
                log("  T %.2f ms %-9s %-6s v0 max (20.5 V) %s m/s, (21.588 V) %s m/s" % (tl, pk, cn, a, b))
    with open(os.path.join(HERE, "tables.md"), "w") as f:
        f.write("Generated by run.py digest(); RESULTS.md quotes these tables.\n\n" + "\n".join(MD) + "\n")


if __name__ == "__main__":
    main()
