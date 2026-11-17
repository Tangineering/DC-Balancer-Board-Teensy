"""Sim 4: CR permit logic at power-up, brown-out, MCU reset, J-TAP unplug, EIB/REGN power loss and W5 bridges.

python run.py            regenerates every deck (decks/), CSV (results/) and PNG (figures/) of this simulation.
python run.py --quick    runs a reduced corner set (for development only; the committed results use the full set).

Entry point of hardware/charger_evm_r8/sim/permit; see RESULTS.md for the report.
"""
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ngspice_run import run_deck, ngspice_version  # noqa: E402
import deck as D  # noqa: E402
import analyse as A  # noqa: E402
import boolean_check as B  # noqa: E402
import floating as F  # noqa: E402
import od_check as OD  # noqa: E402

QUICK = "--quick" in sys.argv
FAMS = ("powerup", "reset", "brownout", "jtap", "t2race", "t2fix", "t2skew", "t2od", "t2fixskew", "eib", "bridge")
DECKS = os.path.join(HERE, "decks")
RES = os.path.join(HERE, "results")
FIG = os.path.join(HERE, "figures")
for d in (DECKS, RES, FIG):
    os.makedirs(d, exist_ok=True)

SAVE = ["m_t3v3", "c_t6_3v3", "c_3v3", "e_3v3", "c_h1", "c_uvb", "c_fccn", "c_fcc_on", "c_h1u", "c_fccp", "c_qf",
        "c_gate", "c_ilim_rel", "c_ce_drv", "c_rfc_off", "c_chg_arm", "c_qual", "c_fcc", "c_p5n", "c_fccnn",
        "c_ref103", "c_ref119", "c_ref120", "c_n_h1p", "c_n_h1m", "c_n_uvp", "c_n_fop", "c_n_fom", "c_n_fnp",
        "c_ce_drv_j", "c_ilim_rel_a", "c_ilim_rel_b", "c_rfc_off_j", "c_j3v3_1", "c_t2c", "c_t1_vmot",
        "e_n_cein", "e_n_rain", "e_n_rbin", "e_n_rfin", "e_nce_drv", "e_q201_g", "e_q202_g", "e_q203_g",
        "e_ilim_hold", "e_regn", "e_gnd_j", "m_t5", "m_p5", "m_t10"]

# ---------------------------------------------------------------------------------------------------------------
# corner sets
# ---------------------------------------------------------------------------------------------------------------
CORNERS = {
    # nominal: mid-band LVC thresholds, nominal comparator, full 1.9 ms POR
    "nom": dict(lvc=dict(f=0.5), cmp=dict()),
    # every comparator biased toward HIGH (unsafe direction), shortest POR (ASSUMPTION 10 us; the datasheet gives
    # 'up to 1.9 ms' and no minimum), POR at the Fig. 9-1 1.5 V mark, LVC inputs switching at VIL
    "early": dict(lvc=dict(f=0.0), cmp=dict(vos=9e-3, vhys=2e-3, vpor=1.5, tpor=10e-6)),
    # every comparator biased toward LOW, longest POR, LVC inputs switching at VIH
    "late": dict(lvc=dict(f=1.0), cmp=dict(vos=-9e-3, vhys=8e-3, vpor=1.65, tpor=1.9e-3)),
    # slow REF start (ASSUMPTION tau 100 us) with short POR on U120 (FCC_ON) and U102/U103, long POR on U119
    # (FCC_OFF): hunts for an FCCP or H1U glitch while a REF is still rising
    "skewref": dict(lvc=dict(f=0.0), cmp=dict(vos=9e-3, vhys=2e-3, vpor=1.5, tpor=10e-6, tref=100e-6),
                    cmp_per=dict(U119=dict(tpor=1.9e-3, vos=-9e-3))),
}
if QUICK:
    CORNERS = {k: CORNERS[k] for k in ("nom", "skewref")}

PRE = 5e-3   # warm-start preroll (deck.Case.preroll)
BUS = {"cold": (0.0, 0.0), "bus": (15.9, 15.9), "regen": (15.9, 18.0)}   # (VBUS, VMOT) in V


def corner_kw(name):
    c = CORNERS[name] if name in CORNERS else {"nom": dict(lvc=dict(f=0.5), cmp=dict())}[name]
    kw = dict(lvc=dict(c["lvc"]), cmp=dict(c["cmp"]))
    if "cmp_per" in c:
        kw["cmp_per"] = c["cmp_per"]
    return kw


def pin(en, lvl, ikeep=0.0):
    return dict(en=en, lvl=lvl, ikeep=ikeep)


def driven_then_hiz(level, t_hiz):
    """Teensy pin driven at 'level' until t_hiz, then high impedance."""
    return pin([(0, 1), (t_hiz, 1), (t_hiz + 1e-8, 0)], [(0, level)])


HIZ = pin([(0, 0)], [(0, 0)])

# Run-state Teensy outputs: (P5 pin 5, FCC pin 31, QUAL pin 33) and bus condition
STATES = {
    "cruise": dict(p5=1, p31=0, q=0, bus="bus", desc="Run cruise, regen armed (P5 1, FCC 0, QUAL 0, V-MOT = VBUS)"),
    "burst": dict(p5=1, p31=0, q=0, bus="regen", desc="Regen burst (P5 1, FCC 0, V-MOT 18.0 V > 1.089 x VBUS)"),
    "fcwin": dict(p5=1, p31=1, q=0, bus="bus", desc="FC window (P5 1, FCC 1, QUAL 0)"),
    "qual": dict(p5=0, p31=0, q=1, bus="bus", desc="Run-entry qualification (P5 0, QUAL 1, FCC 0)"),
    "idle": dict(p5=0, p31=0, q=0, bus="bus", desc="Idle (all pins LOW)"),
}

ALL_OUT = ("CE_pin", "CE_logic", "ILIM_pin", "REL_logic", "ILIM_REL_cr", "FCEN", "RFC_vs_FCEN")


def state_pins(st, t_hiz=None, ikeep=0.0):
    s = STATES[st]
    out = {}
    for p, lv in ((5, s["p5"]), (31, s["p31"]), (33, s["q"])):
        if t_hiz is None:
            out[p] = pin([(0, 1)], [(0, lv)], ikeep)
        else:
            d = driven_then_hiz(lv, t_hiz)
            d["ikeep"] = ikeep
            out[p] = d
    return out


# ---------------------------------------------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------------------------------------------
JOBS = []


def add(family, case, window, expect, info, allow_trans=100e-6, post=None):
    JOBS.append(dict(family=family, case=case, window=window, expect=expect, info=info, allow_trans=allow_trans,
                     post=post))


def _last_true(t, mask):
    """Time just after the last sample where mask is True (nan if never True)."""
    idx = np.where(mask)[0]
    if idx.size == 0:
        return float("nan")
    i = idx[-1]
    return float(t[min(i + 1, len(t) - 1)])


def _first_true(t, mask):
    idx = np.where(mask)[0]
    return float(t[idx[0]]) if idx.size else float("nan")


def timeline(r, t_ev):
    """Rail-decay timeline after the event at t_ev (used for the T6-open cases): when the CR rail falls below the
    1.65 V device minimum, when each permit output reaches its safe state for good, and when the rail settles below
    0.45 V (B.7 upper figure). All times in ms from the event."""
    t = r["time"]
    k = t >= t_ev
    t, c3, e3 = t[k], r["c_3v3"][k], r["e_3v3"][k]
    ce = r["e_nce_drv"][k]
    rel = np.minimum(r["e_n_rain"][k], r["e_n_rbin"][k])
    ilr = r["c_ilim_rel"][k]
    cedrv = r["e_n_cein"][k]
    out = dict(
        tl_cr_below_1v65_ms=(_first_true(t, c3 < A.VCC_MIN) - t_ev) * 1e3,
        tl_ce_pin_high_ms=(_last_true(t, ce < A.VIH_CE) - t_ev) * 1e3,
        tl_ce_logic_safe_ms=(_last_true(t, cedrv > A.vil(e3)) - t_ev) * 1e3,
        tl_rel_logic_safe_ms=(_last_true(t, rel > A.vil(e3)) - t_ev) * 1e3,
        tl_ilim_rel_cr_safe_ms=(_last_true(t, ilr > A.vil(c3)) - t_ev) * 1e3,
        tl_cr_below_0v45_ms=(_last_true(t, c3 > 0.45) - t_ev) * 1e3,
        tl_c3v3_end=float(c3[-1]), tl_e3v3_end=float(e3[-1]), tl_t_end_ms=(float(t[-1]) - t_ev) * 1e3)
    last_drive = np.nanmax([out["tl_ce_logic_safe_ms"], out["tl_rel_logic_safe_ms"], out["tl_ilim_rel_cr_safe_ms"]])
    out["tl_below_1v65_driving_ms"] = max(0.0, last_drive - out["tl_cr_below_1v65_ms"])
    return out


def execute(job):
    case = job["case"]
    text = D.build(case, save=SAVE)
    path = os.path.join(DECKS, job["family"], case.name + ".cir")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    t0 = time.time()
    r = run_deck(text, timeout_s=900)
    dt = time.time() - t0
    row = dict(family=job["family"], case=case.name, **job["info"], sim_ok=int(bool(r.ok)), sim_s=round(dt, 2))
    if not r.ok:
        row["verdict"] = "SIM_FAIL"
        row["errors"] = " | ".join(r.errors[:3])
        return row, None
    if case.preroll:
        t = r["time"]
        k = t >= case.preroll - 1e-12
        for name in list(r.vec):
            v = r.vec[name]
            if isinstance(v, np.ndarray) and v.shape == t.shape:
                r.vec[name] = v[k]
        r.vec["time"] = r.vec["time"] - case.preroll
    w = (job["window"][0], min(job["window"][1], float(r["time"][-1])))
    m = A.checks(r, w, job["expect"], allow_trans=job["allow_trans"])
    row.update(m)
    if job.get("post") == "timeline":
        row.update(timeline(r, job["window"][0]))
    row["expect"] = ";".join("%s=%s" % kv for kv in job["expect"].items())
    keep = {k: r[k] for k in ["time"] + SAVE if k in r.vec}
    return row, keep


def run_all(jobs, keep_for_plot):
    results, waves = [], {}
    n = len(jobs)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (row, wv) in enumerate(ex.map(execute, jobs)):
            results.append(row)
            key = (row["family"], row["case"])
            if wv is not None and key in keep_for_plot:
                waves[key] = wv
            if (i + 1) % 20 == 0 or i + 1 == n:
                print("  %d/%d decks done (%.0f s)" % (i + 1, n, time.time() - t0))
    return results, waves


def write_csv(path, rows, first=None):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    if first:
        keys = [k for k in first if k in keys] + [k for k in keys if k not in first]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------------------------------------------
# case families
# ---------------------------------------------------------------------------------------------------------------
def fam_powerup():
    """(1a) cold 3V3 ramp 0 -> 3.3 V, Teensy pins high-Z throughout (MCU in reset/boot), MB 10k EN bodge fitted."""
    for tr in (0.1e-3, 1e-3, 10e-3):
        for bus, (vb, vm) in BUS.items():
            for regn in (0.0, 5.0):
                for cn in CORNERS:
                    name = "pu_%gms_%s_regn%g_%s" % (tr * 1e3, bus, regn, cn)
                    t_stop = tr + 4e-3
                    c = D.Case(name, t_stop, t_max=min(2e-6, t_stop / 4000), v3=[(0, 0), (tr, 3.3)],
                               vbus=[(0, vb)], vmot=[(0, vm)], regn=[(0, regn)],
                               pins={5: HIZ, 31: HIZ, 33: HIZ}, **corner_kw(cn))
                    exp = {k: "safe" for k in ALL_OUT}
                    if bus == "regen":     # H1U legitimately releases ILIM (B.7 'H1U only'; LOG-3)
                        for k in ("ILIM_pin", "REL_logic", "ILIM_REL_cr"):
                            exp[k] = "free"
                    add("powerup", c, (0, t_stop), exp,
                        dict(ramp_ms=tr * 1e3, bus=bus, regn=regn, corner=cn))


def fam_reset():
    """(1b) warm MCU reset: 3V3 steady, the Teensy pins go high-Z at 1 ms from four Run states."""
    t_hiz, t_stop = 1e-3, 4e-3
    for st in ("cruise", "burst", "fcwin", "qual"):
        vb, vm = BUS[STATES[st]["bus"]]
        for cn in CORNERS:
            name = "rst_%s_%s" % (st, cn)
            c = D.Case(name, t_stop, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)], regn=[(0, 5.0)],
                       pins=state_pins(st, t_hiz), **corner_kw(cn))
            exp = {k: "safe" for k in ALL_OUT}
            if st == "burst":
                for k in ("ILIM_pin", "REL_logic", "ILIM_REL_cr"):
                    exp[k] = "free"
            add("reset", c, (t_hiz, t_stop), exp, dict(state=st, corner=cn, fault="none", ikeep_uA=0))
    # i.MX RT1062 pad keeper (H.24(b), TODO(verify: IMXRT1060RM)): constant source current on pins 5, 31, 33
    for st in ("cruise", "fcwin", "qual"):
        vb, vm = BUS[STATES[st]["bus"]]
        for ik in (17e-6, 42.6e-6, 64e-6, 100e-6):
            name = "rst_%s_keeper%guA" % (st, ik * 1e6)
            c = D.Case(name, t_stop, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)], regn=[(0, 5.0)],
                       pins=state_pins(st, t_hiz, ik))
            add("reset", c, (t_hiz, t_stop), {k: "safe" for k in ALL_OUT},
                dict(state=st, corner="nom", fault="keeper", ikeep_uA=ik * 1e6))
    # fault rows: MB EN bodge open; R187 short (LOG-1); both
    faults = {"bodge_open": dict(ext=dict(R_BODGE=1e12)),
              "R187_short": dict(overrides=dict(R187=0.01)),
              "bodge_open+R187_short": dict(ext=dict(R_BODGE=1e12), overrides=dict(R187=0.01)),
              "renpd_min_bodge_open": dict(ext=dict(R_BODGE=1e12, REN_PD=475e3))}
    for st in ("cruise", "fcwin"):
        vb, vm = BUS[STATES[st]["bus"]]
        for fn, fk in faults.items():
            name = "rst_%s_%s" % (st, fn)
            c = D.Case(name, t_stop, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)], regn=[(0, 5.0)],
                       pins=state_pins(st, t_hiz), **fk)
            add("reset", c, (t_hiz, t_stop), {k: "safe" for k in ALL_OUT},
                dict(state=st, corner="nom", fault=fn, ikeep_uA=0))


def fam_brownout():
    """(2) Teensy 3V3 sags from 3.3 V to Vmin and recovers; Teensy pins either keep driving or go high-Z (MCU BOR)."""
    t1, tf, th, t_stop = 1e-3, 0.1e-3, 3e-3, 9e-3
    vmins = (2.5, 2.0, 1.8, 1.6, 1.5, 1.2) if not QUICK else (2.0, 1.5)
    for vmin in vmins:
        v3 = [(0, 3.3), (t1, 3.3), (t1 + tf, vmin), (t1 + tf + th, vmin), (t1 + 2 * tf + th, 3.3)]
        for st in ("cruise", "burst", "fcwin"):
            vb, vm = BUS[STATES[st]["bus"]]
            for mcu in ("driven", "bor_reset"):
                for cn in [k for k in CORNERS if k in ("nom", "early", "skewref")]:
                    name = "bo_%gV_%s_%s_%s" % (vmin, st, mcu, cn)
                    pins = state_pins(st, None if mcu == "driven" else t1 + tf / 2)
                    c = D.Case(name, t_stop, preroll=PRE, v3=v3, vbus=[(0, vb)], vmot=[(0, vm)], regn=[(0, 5.0)], pins=pins,
                               **corner_kw(cn))
                    exp = {k: "free" for k in ALL_OUT}
                    if mcu == "bor_reset":
                        exp.update({k: "safe" for k in ALL_OUT})
                        if st == "burst":
                            for k in ("ILIM_pin", "REL_logic", "ILIM_REL_cr"):
                                exp[k] = "free"
                    else:
                        # pins still command the state; only a NEW unsafe excursion of an output that was safe in
                        # that state counts: FC EN and the release in cruise, the regen clamp vs FC EN everywhere
                        if st == "cruise":
                            for k in ("ILIM_pin", "REL_logic", "ILIM_REL_cr"):
                                exp[k] = "safe"
                        exp["RFC_vs_FCEN"] = "safe" if st != "burst" else "free"
                        if st != "fcwin":
                            exp["FCEN"] = "safe"
                    add("brownout", c, (t1, t_stop), exp, dict(vmin=vmin, state=st, mcu=mcu, corner=cn))


def fam_jtap():
    """(3) J-TAP unplugged: all ten conductors at 1 ms (re-plugged at 200 ms), or one conductor at a time."""
    t_un, t_re, t_stop = 1e-3, 200e-3, 260e-3
    all_pins = ("1", "4", "5", "6", "7", "10")
    for st in ("cruise", "burst", "fcwin"):
        vb, vm = BUS[STATES[st]["bus"]]
        for regn in (5.0, 0.0):
            name = "jt_all_%s_regn%g" % (st, regn)
            jt = {p: [(0, 1), (t_un, 1), (t_un + 1e-8, 0), (t_re, 0), (t_re + 1e-8, 1)] for p in all_pins}
            c = D.Case(name, t_stop, t_max=20e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)],
                       regn=[(0, regn)], pins=state_pins(st), jtap=jt)
            exp = {k: "safe" for k in ALL_OUT}
            exp["FCEN"] = "free"   # pin 31 still drives the MB EN net in an FC window; the CR no longer sees it
            exp["RFC_vs_FCEN"] = "free"
            exp["CE_pin"] = exp["CE_logic"] = "free"   # CHG_ARM still arrives through J1 pin 11: /CE follows P5
            add("jtap", c, (t_un, t_re), exp, dict(state=st, regn=regn, opened="all", replug_ms=t_re * 1e3))
    single = [("6", "burst"), ("6", "fcwin"), ("4", "fcwin"), ("4", "cruise"), ("1", "burst"), ("1", "cruise"),
              ("7", "burst"), ("10", "qual"), ("5", "burst")]
    names = {"1": "T2", "4": "T5", "5": "T13", "6": "T6", "7": "T1", "10": "T10"}
    for p, st in single:
        vb, vm = BUS[STATES[st]["bus"]]
        name = "jt_%s_%s" % (names[p], st)
        # T6 open: the CR rail decays from C125 over about 0.5 s, so the run lasts 0.6 s (check round 2026-11-15)
        t_s = 600e-3 if p == "6" else 6e-3
        c = D.Case(name, t_s, t_max=min(20e-6, t_s / 3000), preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)],
                   regn=[(0, 5.0)], pins=state_pins(st), jtap={p: [(0, 1), (t_un, 1), (t_un + 1e-8, 0)]})
        exp = {k: "free" for k in ALL_OUT}
        # what must become / stay safe after the conductor opens
        if p in ("6",):                         # CR rail lost: everything must end safe
            exp.update({k: "safe" for k in ("CE_logic", "REL_logic", "ILIM_REL_cr")})
        if p == "1":                            # T2 open: H1 forced HIGH, UVB must drop the release
            exp.update({k: "safe" for k in ("REL_logic", "ILIM_pin", "ILIM_REL_cr")})
        if p == "7":                            # T1 open: H1 LOW
            exp.update({k: "safe" for k in ("REL_logic", "ILIM_pin", "ILIM_REL_cr")})
        if p == "10":                           # QUAL open: QF drops
            exp.update({k: "safe" for k in ("REL_logic", "ILIM_pin", "ILIM_REL_cr")})
        add("jtap", c, (t_un, t_s), exp, dict(state=st, regn=5.0, opened=names[p], replug_ms="", va=0.8),
            post="timeline" if p == "6" else None)
    # T6 open: the interval in which the CR and EIB logic drive below 1.65 V depends on the assumed output-stage alive
    # voltage va; sweep it
    # (and, with base_load none, on the assumed low-voltage behaviour of the part supply currents)
    for st in ("burst", "fcwin"):
        vb, vm = BUS[STATES[st]["bus"]]
        for va, bl in ((0.6, "parts"), (1.0, "parts"), (0.8, "none")):
            name = "jt_T6_%s_va%g_%s" % (st, va, bl)
            c = D.Case(name, 600e-3, t_max=20e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)],
                       regn=[(0, 5.0)], pins=state_pins(st), jtap={"6": [(0, 1), (t_un, 1), (t_un + 1e-8, 0)]},
                       lvc=dict(va=va), cmp=dict(va=va), base_load=bl)
            exp = {k: "free" for k in ALL_OUT}
            exp.update({k: "safe" for k in ("CE_logic", "REL_logic", "ILIM_REL_cr")})
            add("jtap", c, (t_un, 600e-3), exp, dict(state=st, regn=5.0, opened="T6", replug_ms="", va=va,
                                                      base_load=bl), post="timeline")


def fam_t2race():
    """Additional study: the VBUS tap (T2) opens while the bus is healthy and V-MOT = VBUS. H1's IN- collapses
    (H1 forced HIGH) before UVB's IN+ falls below REF, so H1U = H1 AND UVB can pulse HIGH. Also T1 and T2 together
    (whole J-TAP pulled) and a 50 us T2 intermittency (connector fretting)."""
    t_ev, t_stop = 1e-3, 3e-3
    for vbus in (14.5, 15.9, 16.4):
        for st in ("cruise", "idle"):
            for cn in CORNERS:
                for what in ("T2", "T2+T1", "T2_50us"):
                    if what == "T2":
                        jt = {"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)]}
                    elif what == "T2+T1":
                        jt = {p: [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)] for p in ("1", "7")}
                    else:
                        jt = {"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0), (t_ev + 50e-6, 0), (t_ev + 50e-6 + 1e-8, 1)]}
                    name = "t2_%s_%gV_%s_%s" % (what.replace("+", ""), vbus, st, cn)
                    c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vbus)], vmot=[(0, vbus)],
                               regn=[(0, 5.0)], pins=state_pins(st), jtap=jt, **corner_kw(cn))
                    exp = {k: "safe" for k in ("ILIM_pin", "REL_logic", "ILIM_REL_cr")}
                    add("t2race", c, (t_ev, t_stop), exp, dict(opened=what, vbus=vbus, state=st, corner=cn))


def fam_t2fix():
    """Additional study: candidate mitigations of the T2-open H1U race, checked on the worst T2 case (VBUS 16.4 V,
    early and late corners) and on the H1 response to a V-MOT step (15.9 -> 18.0 V in 1 us at 1 ms; the latency of
    the release is the cost). Options: C106 and C107 (H1 IN+/IN- filters) raised together from 470 pF; C108 (UVB
    IN+ filter) lowered from 1.0 nF."""
    t_ev, t_stop = 1e-3, 3e-3
    opts = {"base": {}, "C106C107_2n2": dict(C106=2.2e-9, C107=2.2e-9),
            "C106C107_4n7": dict(C106=4.7e-9, C107=4.7e-9), "C106C107_10n": dict(C106=10e-9, C107=10e-9),
            "C108_470p": dict(C108=470e-12), "C107_4n7_only": dict(C107=4.7e-9)}
    for on, ov in opts.items():
        for cn in ("early", "late", "nom"):
            name = "fix_%s_T2open_%s" % (on, cn)
            c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, 16.4)], vmot=[(0, 16.4)],
                       regn=[(0, 5.0)], pins=state_pins("cruise"), jtap={"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)]},
                       overrides=dict(ov), **corner_kw(cn))
            add("t2fix", c, (t_ev, t_stop), {k: "safe" for k in ("ILIM_pin", "REL_logic", "ILIM_REL_cr")},
                dict(option=on, test="T2 open, VBUS 16.4 V, cruise", corner=cn))
            name = "fix_%s_regenstep_%s" % (on, cn)
            c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, 15.9)],
                       vmot=[(0, 15.9), (t_ev, 15.9), (t_ev + 1e-6, 18.0)], regn=[(0, 5.0)],
                       pins=state_pins("cruise"), overrides=dict(ov), **corner_kw(cn))
            add("t2fix", c, (t_ev, t_stop), {}, dict(option=on, test="V-MOT step 15.9 -> 18.0 V (H1 latency)",
                                                     corner=cn))


T2_OUT = ("ILIM_pin", "REL_logic", "ILIM_REL_cr")


def _tpd_kw(cn, h1=None, uvb=None, tpd100=None, h1_100=None, uvb_100=None):
    """corner_kw(cn) with per-comparator propagation delays: fixed tpd on U102 (H1) / U103 (UVB), or the
    overdrive-dependent model on all four comparators (tpd100) or on U102 / U103 separately."""
    kw = corner_kw(cn)
    per = dict(kw.get("cmp_per", {}))
    if tpd100 is not None:
        kw["cmp"]["tpd100"] = tpd100
    for ref, fixed, od in (("U102", h1, h1_100), ("U103", uvb, uvb_100)):
        d = dict(per.get(ref, {}))
        if fixed is not None:
            d["tpd"] = fixed
        if od is not None:
            d["tpd100"] = od
        if d:
            per[ref] = d
    if per:
        kw["cmp_per"] = per
    return kw


TPD_PAIRS = ((2e-6, 2e-6), (4e-6, 4e-6), (2e-6, 4e-6), (2e-6, 6e-6), (2e-6, 8e-6), (2e-6, 10e-6), (2e-6, 12e-6),
             (4e-6, 14e-6))
OD_SETS = {"od1.3": dict(tpd100=1.3e-6), "od2": dict(tpd100=2e-6), "od4": dict(tpd100=4e-6),
           "od_H1fast_UVBmax": dict(tpd100=2e-6, h1_100=1.3e-6, uvb_100=4e-6)}
FIX_OPTS = {"base": {}, "C106C107_2n2": dict(C106=2.2e-9, C107=2.2e-9),
            "C106C107_4n7": dict(C106=4.7e-9, C107=4.7e-9), "C106C107_10n": dict(C106=10e-9, C107=10e-9),
            "C108_470p": dict(C108=470e-12), "C107_4n7_only": dict(C107=4.7e-9)}


def fam_t2skew():
    """Check round: the T2 race with the fixed-delay comparator model at the SBOS300C Table 6.10 maximum (4 us) and
    with UVB slower than H1 by 0-10 us (UVB's IN+ crosses REF slowly, i.e. at low overdrive)."""
    t_ev, t_stop = 1e-3, 3e-3
    for vbus in (14.5, 15.9, 16.4):
        for cn in ("early", "nom", "late"):
            for h1, uvb in TPD_PAIRS:
                name = "skew_%gV_%s_H1_%gus_UVB_%gus" % (vbus, cn, h1 * 1e6, uvb * 1e6)
                c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vbus)], vmot=[(0, vbus)],
                           regn=[(0, 5.0)], pins=state_pins("cruise"), jtap={"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)]},
                           **_tpd_kw(cn, h1=h1, uvb=uvb))
                add("t2skew", c, (t_ev, t_stop), {k: "safe" for k in T2_OUT},
                    dict(vbus=vbus, corner=cn, tpd_H1_us=h1 * 1e6, tpd_UVB_us=uvb * 1e6, skew_us=(uvb - h1) * 1e6))


def fam_t2od():
    """Check round: the T2 race with the overdrive-dependent comparator model (tlv3012b_od), at the figure-typical,
    table-typical and table-maximum delay and with a fast H1 part beside a maximum-delay UVB part; also the
    mitigation options and the H1 release latency under the same model."""
    t_ev, t_stop = 1e-3, 3e-3
    for vbus in (14.5, 15.9, 16.4):
        for cn in ("early", "nom", "late"):
            for on, od in OD_SETS.items():
                name = "od_%gV_%s_%s" % (vbus, cn, on)
                c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vbus)], vmot=[(0, vbus)],
                           regn=[(0, 5.0)], pins=state_pins("cruise"), jtap={"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)]},
                           **_tpd_kw(cn, **od))
                add("t2od", c, (t_ev, t_stop), {k: "safe" for k in T2_OUT},
                    dict(test="T2 open", option="base", vbus=vbus, corner=cn, od_set=on))
    for fo in ("base", "C108_470p", "C107_4n7_only", "C106C107_4n7", "C106C107_10n"):
        for cn in ("early", "nom", "late"):
            for on in ("od4", "od_H1fast_UVBmax"):
                name = "odfix_%s_%s_%s" % (fo, cn, on)
                c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, 16.4)], vmot=[(0, 16.4)],
                           regn=[(0, 5.0)], pins=state_pins("cruise"), jtap={"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)]},
                           overrides=dict(FIX_OPTS[fo]), **_tpd_kw(cn, **OD_SETS[on]))
                add("t2od", c, (t_ev, t_stop), {k: "safe" for k in T2_OUT},
                    dict(test="T2 open", option=fo, vbus=16.4, corner=cn, od_set=on))
        for cn in ("early", "late"):
            name = "odfix_%s_regenstep_%s_od4" % (fo, cn)
            c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, 15.9)],
                       vmot=[(0, 15.9), (t_ev, 15.9), (t_ev + 1e-6, 18.0)], regn=[(0, 5.0)], pins=state_pins("cruise"),
                       overrides=dict(FIX_OPTS[fo]), **_tpd_kw(cn, **OD_SETS["od4"]))
            add("t2od", c, (t_ev, t_stop), {}, dict(test="V-MOT step 15.9 -> 18.0 V (H1 latency)", option=fo, vbus=15.9,
                                                    corner=cn, od_set="od4"))


def fam_t2fixskew():
    """Check round: the mitigation options under the fixed-delay model at the 4 us maximum with UVB slower than H1 by
    0-15 us (VBUS 16.4 V, early corner = the worst case of t2race)."""
    t_ev, t_stop = 1e-3, 3e-3
    for fo in ("base", "C108_470p", "C107_4n7_only", "C106C107_4n7", "C106C107_10n"):
        for uvb in (4e-6, 6e-6, 8e-6, 10e-6, 12e-6, 14e-6, 19e-6):
            name = "fixskew_%s_UVB_%gus" % (fo, uvb * 1e6)
            c = D.Case(name, t_stop, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, 16.4)], vmot=[(0, 16.4)],
                       regn=[(0, 5.0)], pins=state_pins("cruise"), jtap={"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)]},
                       overrides=dict(FIX_OPTS[fo]), **_tpd_kw("early", h1=4e-6, uvb=uvb))
            add("t2fixskew", c, (t_ev, t_stop), {k: "safe" for k in T2_OUT},
                dict(option=fo, vbus=16.4, corner="early", tpd_H1_us=4.0, tpd_UVB_us=uvb * 1e6,
                     skew_us=uvb * 1e6 - 4.0))


def fam_eib():
    """(4) EIB 3V3 lost with the CR powered; REGN absent / arriving late; CR unpowered with REGN present;
    single W5 conductor open."""
    t_ev, t_stop = 1e-3, 12e-3
    for st in ("burst", "fcwin", "cruise"):
        vb, vm = BUS[STATES[st]["bus"]]
        name = "eib_3v3lost_%s" % st
        c = D.Case(name, t_stop, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)], regn=[(0, 5.0)],
                   pins=state_pins(st), w5={"1": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)],
                                            "2": [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)]})
        exp = {k: "safe" for k in ("CE_pin", "ILIM_pin")}
        add("eib", c, (t_ev, t_stop), exp, dict(state=st, event="EIB 3V3 lost (W5 1 and 2 open)"),
            allow_trans=10e-3)
        # REGN arrives after the CR is up (charger powers up into an armed CR)
        name = "eib_regn_late_%s" % st
        c = D.Case(name, t_stop, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)],
                   regn=[(0, 0), (t_ev, 0), (t_ev + 1e-3, 5.0)], pins=state_pins(st))
        add("eib", c, (t_ev, t_stop), {}, dict(state=st, event="REGN ramps 0 -> 5 V in 1 ms at 1 ms"))
    for st in ("idle", "burst"):
        vb, vm = BUS[STATES[st]["bus"]]
        # CR rail lost (T6 open from t=0) while REGN is present (EIB-4: REGN from the pack with ADC_EN = 1)
        name = "eib_crdead_regn_%s" % st
        c = D.Case(name, t_stop, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)],
                   regn=[(0, 0), (t_ev, 0), (t_ev + 1e-3, 5.0)], pins=state_pins(st), jtap={"6": [(0, 0)]})
        add("eib", c, (t_ev, t_stop), {k: "safe" for k in ("CE_pin", "ILIM_pin")},
            dict(state=st, event="CR unpowered (T6 open), REGN ramps in at 1 ms"))
    for wp, sig in (("5", "CE_DRV_J"), ("7", "ILIM_REL_A"), ("8", "ILIM_REL_B"), ("10", "RFC_OFF_J"),
                    ("3+9", "GND (both)"), ("4", "STAT")):
        for st in ("burst", "fcwin"):
            vb, vm = BUS[STATES[st]["bus"]]
            name = "eib_w5open_%s_%s" % (wp.replace("+", "_"), st)
            w5 = {p: [(0, 1), (t_ev, 1), (t_ev + 1e-8, 0)] for p in wp.split("+")}
            c = D.Case(name, 6e-3, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)], vmot=[(0, vm)], regn=[(0, 5.0)],
                       pins=state_pins(st), w5=w5)
            add("eib", c, (t_ev, 6e-3), {}, dict(state=st, event="W5 %s (%s) open" % (wp, sig)))


BRIDGES = [  # (side, pad A, pad B, label, finding)
    ("c", "5", "9", "CR 5-9 CE_DRV_J-GND", "INT-0/EIB-1"),
    ("c", "7", "3", "CR 7-3 ILIM_REL_A-GND", "INT-0/EIB-1"),
    ("c", "1", "5", "CR 1-5 J3V3_1-CE_DRV_J", "EIB-0"),
    ("c", "5", "7", "CR 5-7 CE_DRV_J-ILIM_REL_A", "EIB-0 list"),
    ("c", "1", "3", "CR 1-3 J3V3_1-GND", "B.6/H.20 accepted"),
    ("c", "8", "9", "CR 8-9 ILIM_REL_B-GND", "r9-12 reference (4.99k)"),
    ("e", "1", "5", "EIB 1-5 3V3-CE_DRV_J", "EIB-0"),
    ("e", "2", "5", "EIB 2-5 3V3-CE_DRV_J", "EIB-0"),
    ("e", "2", "10", "EIB 2-10 3V3-RFC_OFF_J", "EIB-0"),
    ("e", "5", "7", "EIB 5-7 CE_DRV_J-ILIM_REL_A", "EIB-0 list"),
    ("e", "2", "3", "EIB 2-3 3V3-GND_J", "EIB-0/INT-0"),
    ("e", "9", "10", "EIB 9-10 GND_J-RFC_OFF_J", "r9-12 reference (4.99k)"),
]


def fam_bridges():
    """(5) W5 solder bridges (0.01 ohm) present from power-up (assembly defect), in three states, over supply and
    driver corners; the window starts 1 ms after the preroll, when the rail and the POR have settled."""
    t_b, t_stop = 1e-3, 4e-3
    vts = (3.135, 3.465)
    rss = (0.25, 1.0)
    for side, a, b, label, fnd in BRIDGES:
        for st in ("burst", "idle", "fcwin"):
            vb, vm = BUS[STATES[st]["bus"]]
            for vt in vts:
                for rs in rss:
                    for bl in ("parts", "max"):
                        name = "br_%s%s-%s_%s_vt%g_rs%g_%s" % (side, a, b, st, vt, rs, bl)
                        c = D.Case(name, t_stop, preroll=PRE, v3=[(0, vt)], vbus=[(0, vb)], vmot=[(0, vm)],
                                   regn=[(0, 5.0)], pins=state_pins(st), bridges=[(side, a, b, 0.01, None)],
                                   lvc=dict(rs=rs), base_load=bl)
                        add("bridge", c, (t_b, t_stop), {}, dict(bridge=label, finding=fnd, state=st, vt=vt, rs=rs,
                                                                  va=0.8, base_load=bl))
    # EIB-0: U201 below its 1.65 V minimum; sweep the assumed output-stage alive voltage
    for side, a, b in (("e", "1", "5"), ("c", "1", "5")):
        for va in (0.6, 1.0, 1.3):
            name = "br_%s%s-%s_idle_va%g" % (side, a, b, va)
            c = D.Case(name, t_stop, preroll=PRE, v3=[(0, 3.135)], vbus=[(0, 15.9)], vmot=[(0, 15.9)], regn=[(0, 5.0)],
                       pins=state_pins("idle"), bridges=[(side, a, b, 0.01, None)], lvc=dict(rs=0.25, va=va),
                       base_load="max")
            add("bridge", c, (t_b, t_stop), {}, dict(bridge="%s %s-%s (va sweep)" % ("CR" if side == "c" else "EIB",
                                                                                     a, b),
                                                      finding="EIB-0", state="idle", vt=3.135, rs=0.25, va=va,
                                                      base_load="max"))
    # healthy board (no bridge) with both base loads: the reference rail for every bridge row
    for bl in ("parts", "max"):
        for vt in vts:
            name = "br_none_idle_vt%g_%s" % (vt, bl)
            c = D.Case(name, t_stop, preroll=PRE, v3=[(0, vt)], vbus=[(0, 15.9)], vmot=[(0, 15.9)], regn=[(0, 5.0)],
                       pins=state_pins("burst"), base_load=bl)
            add("bridge", c, (t_b, t_stop), {}, dict(bridge="none (healthy board)", finding="reference", state="burst",
                                                      vt=vt, rs=1.0, va=0.8, base_load=bl))


def fam_logic_xcheck():
    """SPICE cross-check of the 64-row truth table: comparators replaced by ideal sources, Teensy pins driven."""
    slot = 400e-6
    tt = B.truth_table()
    seq = {k: [] for k in B.PRIMARY}
    for i, row in enumerate(tt):
        for k in B.PRIMARY:
            seq[k].append((i * slot, row[k]))
    def pts(k, scale):
        out = []
        for t, v in seq[k]:
            out.append((t + 1e-7 if t > 0 else 0.0, v * scale))
            out.append((t + slot, v * scale))
        return out
    lo = {"U102": pts("H1", 3.3), "U103": pts("UVB", 3.3), "U119": pts("FCCN", 3.3), "U120": pts("FCC_ON", 3.3)}
    p5 = pin([(0, 1)], pts("CHG_ARM", 1))
    q = pin([(0, 1)], pts("QUAL", 1))
    t_stop = slot * len(tt)
    c = D.Case("xcheck_64", t_stop, t_max=2e-6, v3=[(0, 3.3)], regn=[(0, 5.0)], pins={5: p5, 33: q, 31: HIZ},
               logic_only=lo)
    return c, tt, slot


# ---------------------------------------------------------------------------------------------------------------
# plotting
# ---------------------------------------------------------------------------------------------------------------
TRACES = [("c_3v3", "CR 3V3"), ("e_3v3", "EIB 3V3"), ("c_h1", "H1"), ("c_uvb", "UVB"), ("c_fccn", "FCC_OFF"),
          ("c_fcc_on", "FCC_ON"), ("c_ilim_rel", "ILIM_REL"), ("c_ce_drv", "CE_DRV"), ("c_rfc_off", "RFC_OFF"),
          ("e_nce_drv", "/CE (EVM)"), ("e_ilim_hold", "ILIM_HIZ (EVM)"), ("m_t5", "FC_CHARGE EN")]


def plot_waves(w, title, path, t_unit=1e-3, xlabel="time (ms)", xlim=None):
    t = w["time"] / t_unit
    fig, axs = plt.subplots(4, 1, figsize=(9, 9), sharex=True)
    groups = [[("m_t3v3", "Teensy 3V3"), ("c_3v3", "CR 3V3"), ("e_3v3", "EIB 3V3")],
              [("c_h1", "H1"), ("c_uvb", "UVB"), ("c_fccn", "FCC_OFF (FCCN)"), ("c_fcc_on", "FCC_ON")],
              [("c_h1u", "H1U"), ("c_fccp", "FCCP"), ("c_qf", "QF"), ("c_ilim_rel", "ILIM_REL"), ("c_ce_drv", "CE_DRV"),
               ("c_rfc_off", "RFC_OFF")],
              [("e_nce_drv", "/CE at EVM"), ("e_ilim_hold", "ILIM_HIZ at EVM"), ("m_t5", "FC_CHARGE EN (MB)"),
               ("e_regn", "REGN")]]
    ylabels = ["supply (V)", "comparator out (V)", "gate out (V)", "EVM / MB (V)"]
    for ax, grp, yl in zip(axs, groups, ylabels):
        for k, lab in grp:
            if k in w:
                ax.plot(t, w[k], lw=1.1, label=lab)
        ax.set_ylabel(yl)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=7, ncol=3)
    axs[3].axhline(A.VIL_ILIM, color="k", ls=":", lw=0.8)
    axs[3].axhline(A.VIH_CE, color="k", ls="--", lw=0.8)
    axs[-1].set_xlabel(xlabel)
    if xlim:
        axs[-1].set_xlim(*xlim)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_bridges(rows, path):
    """Horizontal range bars: settled CR and EIB 3V3 per bridge and state, over Vt 3.135-3.465 V and driver Rout
    x0.25-x1 (va 0.8 V rows only)."""
    rows = [r for r in rows if r["family"] == "bridge" and str(r.get("va")) in ("0.8", "0.8000") and "c3v3_end" in r]
    labels, cr, eib = [], [], []
    for side, a, b, label, fnd in BRIDGES:
        for st in ("burst", "idle", "fcwin"):
            sel = [r for r in rows if r["bridge"] == label and r["state"] == st]
            if not sel:
                continue
            labels.append("%s (%s)" % (label, st))
            cv = [float(r["c3v3_end"]) for r in sel]
            ev = [float(r["e3v3_end"]) for r in sel]
            cr.append((min(cv), max(cv)))
            eib.append((min(ev), max(ev)))
    y = np.arange(len(labels))[::-1]
    fig, ax = plt.subplots(figsize=(10, 11))
    for yi, (c0, c1), (e0, e1) in zip(y, cr, eib):
        ax.plot([c0, max(c1, c0 + 0.01)], [yi + 0.15, yi + 0.15], color="#2b6cb0", lw=5, solid_capstyle="butt")
        ax.plot([e0, max(e1, e0 + 0.01)], [yi - 0.15, yi - 0.15], color="#d97706", lw=5, solid_capstyle="butt")
    ax.plot([], [], color="#2b6cb0", lw=5, label="CR 3V3 (settled)")
    ax.plot([], [], color="#d97706", lw=5, label="EIB 3V3 (settled)")
    ax.axvline(3.0, color="#2a9d4b", ls="--", lw=1, label="H.24(d) criterion: CR rail >= 3.0 V (LVC_VCC_ROW)")
    ax.axvline(1.65, color="#c0392b", ls=":", lw=1, label="LVC / TLV3012B minimum 1.65 V")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlim(0, 3.6)
    ax.set_xlabel("settled rail voltage with the bridge present (V)")
    ax.grid(axis="x", alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title("W5 bridges: CR and EIB 3V3 over Vt 3.135-3.465 V, LVC Rout x0.25-x1 and both base loads (bar = range)",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_od(rows, path):
    """Step delay of the tlv3012b_od model against the values read from SBOS300C Figures 8-12 / 8-13."""
    fig, axs = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, d, ttl in ((axs[0], "hl", "tPHL (Fig. 8-12)"), (axs[1], "lh", "tPLH (Fig. 8-13)")):
        for tp in OD.TPD100:
            sel = [r for r in rows if r["direction"] == d and r["input"] == "step" and r["tpd100_us"] == tp * 1e6]
            ax.loglog([r["vod_mV"] for r in sel], [r["delay_us"] for r in sel], "o-", lw=1,
                      label="model, tpd100 %.1f us" % (tp * 1e6))
        fig_pts = OD.FIG_HL if d == "hl" else OD.FIG_LH
        ax.loglog([v * 1e3 for v in fig_pts], [v * 1e6 for v in fig_pts.values()], "ks", ms=6, mfc="none",
                  label="SBOS300C figure (3.3 V, 25 C)")
        ax.set_xlabel("input overdrive (mV)")
        ax.set_title(ttl, fontsize=9)
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=7)
    axs[0].set_ylabel("propagation delay (us)")
    fig.suptitle("Overdrive-dependent TLV3012B model (tlv3012b_od) against SBOS300C", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_t2skew(rows, path):
    """ILIM_HIZ peak at the EVM pin against the UVB - H1 delay skew (fixed-delay model), per VBUS and corner, and the
    mitigation options at the 4 us maximum."""
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    sk = [r for r in rows if r["family"] == "t2skew" and r.get("verdict") != "SIM_FAIL"]
    for vbus in (14.5, 15.9, 16.4):
        for cn, mk in (("early", "o-"), ("nom", "s--"), ("late", "^:")):
            sel = sorted([r for r in sk if float(r["vbus"]) == vbus and r["corner"] == cn and float(r["tpd_H1_us"]) == 2.0],
                         key=lambda r: float(r["skew_us"]))
            if sel:
                axs[0].plot([float(r["skew_us"]) for r in sel], [float(r["ILIM_pin_max"]) for r in sel], mk, lw=1, ms=3,
                            label="%.1f V %s" % (vbus, cn))
    fx = [r for r in rows if r["family"] == "t2fixskew" and r.get("verdict") != "SIM_FAIL"]
    for fo in ("base", "C108_470p", "C107_4n7_only", "C106C107_4n7", "C106C107_10n"):
        sel = sorted([r for r in fx if r["option"] == fo], key=lambda r: float(r["skew_us"]))
        axs[1].plot([float(r["skew_us"]) for r in sel], [float(r["ILIM_pin_max"]) for r in sel], "o-", lw=1, ms=3,
                    label=fo)
    for ax in axs:
        ax.axhline(A.VIL_ILIM, color="k", ls=":", lw=0.8)
        ax.axhline(A.VIH_ILIM, color="#c0392b", ls="--", lw=0.8)
        ax.set_xlabel("UVB delay - H1 delay (us)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=6, ncol=2)
    axs[0].set_ylabel("ILIM_HIZ peak at the EVM pin (V)")
    axs[0].set_title("T2 opened, cruise: H1 tPD 2 us, UVB tPD 2-12 us", fontsize=9)
    axs[1].set_title("T2 opened, 16.4 V, early: H1 tPD 4 us, mitigation options", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_xcheck(t, w, tt, slot, path):
    fig, axs = plt.subplots(3, 1, figsize=(11, 7), sharex=True)
    tt_ms = t * 1e3
    for k, lab in (("c_gate", "GATE"), ("c_ilim_rel", "ILIM_REL"), ("c_ce_drv", "CE_DRV"), ("c_rfc_off", "RFC_OFF")):
        axs[0].plot(tt_ms, w[k], lw=0.9, label=lab)
    axs[1].plot(tt_ms, w["e_nce_drv"], lw=0.9, label="/CE at EVM")
    axs[1].axhline(A.VIH_CE, color="k", ls="--", lw=0.8)
    axs[2].plot(tt_ms, w["e_ilim_hold"], lw=0.9, label="ILIM_HIZ at EVM")
    axs[2].axhline(A.VIL_ILIM, color="k", ls=":", lw=0.8)
    for ax in axs:
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(alpha=0.3)
    axs[0].set_ylabel("CR gate out (V)")
    axs[1].set_ylabel("V")
    axs[2].set_ylabel("V")
    axs[2].set_xlabel("time (ms); one truth-table row per %.1f ms slot" % (slot * 1e3))
    fig.suptitle("SPICE cross-check of the 64-row permit truth table (REGN 5.0 V present)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------------------------------------------------------
def main():
    t_all = time.time()
    print("ngspice: %s" % ngspice_version())
    # remove the outputs of an earlier run so that no stale deck, CSV or figure survives a change of the case list
    for d, ext in ((DECKS, ".cir"), (RES, ".csv"), (FIG, ".png")):
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith(ext):
                    os.remove(os.path.join(root, f))
    # ---- 1. Boolean
    chain = B.check_chain()
    write_csv(os.path.join(RES, "chain_check.csv"),
              [dict(driver=a, cr_R=b, pad_net=c, w5_pin=d, eib_R=e, eib_input=f, netlist_ok=int(g))
               for a, b, c, d, e, f, g in chain])
    tt = B.truth_table()
    write_csv(os.path.join(RES, "truth_table.csv"), tt)
    mt = B.mode_table()
    write_csv(os.path.join(RES, "mode_table.csv"), mt)
    nmis = sum(1 - r["match_B1"] for r in tt)
    nF2 = sum(1 for r in mt if r["F2_agrees"] == "NO")
    print("Boolean: 64 rows, %d mismatches vs B.1; %d F.2 mode rows disagree with the netlist" % (nmis, nF2))
    # ---- 2. floating inputs
    fl = F.analyse()
    write_csv(os.path.join(RES, "floating_inputs.csv"), fl)
    print("Floating-input scan: %d scenario x input findings" % len(fl))
    # ---- 3. SPICE truth-table cross-check
    cx, tt2, slot = fam_logic_xcheck()
    text = D.build(cx, save=SAVE)
    os.makedirs(os.path.join(DECKS, "xcheck"), exist_ok=True)
    with open(os.path.join(DECKS, "xcheck", cx.name + ".cir"), "w", encoding="utf-8") as fh:
        fh.write(text)
    r = run_deck(text, timeout_s=900)
    assert r.ok, r.errors
    t = r["time"]
    xrows = []
    for i, row in enumerate(tt2):
        ts = (i + 0.95) * slot
        g = {k: float(np.interp(ts, t, r[k])) for k in SAVE if k in r.vec}
        lv = {k: int(g["c_" + k.lower()] > 1.65) for k in ("GATE", "ILIM_REL", "CE_DRV", "RFC_OFF", "QF", "H1U",
                                                            "FCCP")}
        il = g["e_ilim_hold"]
        ilim = "HELD" if il < A.VIL_ILIM else ("REL_FC" if il < 1.9 else "REL_REGEN")
        agree = all(lv[k] == row[k] for k in lv) and (int(g["e_nce_drv"] > A.VIH_CE) == row["nCE"]) and \
            ((ilim == row["ILIM"]) or (row["ILIM"] == "HELD_NOFEED" and ilim == "HELD"))
        xrows.append(dict({k: row[k] for k in B.PRIMARY}, **{"spice_" + k: v for k, v in lv.items()},
                          spice_nCE_V=round(g["e_nce_drv"], 4), spice_ILIM_V=round(il, 4), spice_ILIM=ilim,
                          bool_ILIM=row["ILIM"], bool_nCE=row["nCE"], agree=int(agree)))
    write_csv(os.path.join(RES, "truth_table_spice.csv"), xrows)
    nx = sum(1 - x["agree"] for x in xrows)
    print("SPICE cross-check: %d of 64 rows disagree with the Boolean evaluation" % nx)
    plot_xcheck(t, r, tt2, slot, os.path.join(FIG, "xcheck_truth_table.png"))
    # ---- 3b. overdrive-dependent comparator model characterisation
    od_rows = OD.characterise()
    write_csv(os.path.join(RES, "od_characterisation.csv"), od_rows)
    plot_od(od_rows, os.path.join(FIG, "od_model_vs_sbos300c.png"))
    print("Overdrive model characterised: %d points" % len(od_rows))
    # ---- 4. transient families
    fam_powerup()
    fam_reset()
    fam_brownout()
    fam_jtap()
    fam_t2race()
    fam_t2fix()
    fam_t2skew()
    fam_t2od()
    fam_t2fixskew()
    fam_eib()
    fam_bridges()
    plot_keys = {("powerup", "pu_1ms_regen_regn5_nom"), ("powerup", "pu_0.1ms_bus_regn5_skewref"),
                 ("powerup", "pu_10ms_cold_regn0_nom"), ("reset", "rst_fcwin_nom"), ("reset", "rst_cruise_nom"),
                 ("reset", "rst_fcwin_R187_short"), ("brownout", "bo_1.5V_fcwin_driven_nom"),
                 ("brownout", "bo_1.5V_burst_bor_reset_nom"), ("brownout", "bo_2V_cruise_driven_early"),
                 ("jtap", "jt_all_fcwin_regn5"), ("jtap", "jt_all_burst_regn5"), ("jtap", "jt_T2_burst"),
                 ("jtap", "jt_T2_cruise"), ("t2race", "t2_T2_15.9V_cruise_nom"), ("t2race", "t2_T2_16.4V_cruise_early"),
                 ("t2fix", "fix_C106C107_10n_T2open_early"), ("t2fix", "fix_C106C107_10n_regenstep_nom"),
                 ("t2fix", "fix_base_regenstep_nom"),
                 ("jtap", "jt_all_cruise_regn5"),
                 ("eib", "eib_3v3lost_fcwin"), ("eib", "eib_crdead_regn_burst"),
                 ("bridge", "br_c7-3_burst_vt3.135_rs0.25"), ("bridge", "br_e1-5_idle_vt3.135_rs0.25"),
                 ("bridge", "br_e2-10_fcwin_vt3.135_rs0.25"), ("bridge", "br_c5-9_burst_vt3.135_rs0.25"),
                 ("reset", "rst_cruise_keeper42.6uA"), ("reset", "rst_qual_keeper64uA"),
                 ("jtap", "jt_T6_burst"), ("jtap", "jt_T6_fcwin"),
                 ("t2od", "od_16.4V_early_od4"), ("t2od", "od_16.4V_early_od_H1fast_UVBmax"),
                 ("t2skew", "skew_16.4V_early_H1_2us_UVB_8us"), ("t2fixskew", "fixskew_C106C107_10n_UVB_19us")}
    print("Running %d transient decks" % len(JOBS))
    rows, waves = run_all(JOBS, plot_keys)
    for fam in FAMS:
        fr = [x for x in rows if x["family"] == fam]
        write_csv(os.path.join(RES, "%s.csv" % fam), fr,
                  first=["family", "case", "verdict", "violations"])
        nfail = sum(1 for x in fr if x.get("verdict", "").startswith("SIM_FAIL"))
        nuns = sum(1 for x in fr if x.get("verdict", "").startswith("UNSAFE"))
        print("  %-9s %3d decks, %d unsafe verdicts, %d simulator failures" % (fam, len(fr), nuns, nfail))
    for (fam, name), w in waves.items():
        plot_waves(w, "%s / %s" % (fam, name), os.path.join(FIG, "%s__%s.png" % (fam, name)),
                   t_unit=1e-3, xlabel="time (ms)")
        zoom = {"t2race": (0.99, 1.06), "t2fix": (0.95, 1.8), "reset": (0.99, 1.2), "t2skew": (0.99, 1.08),
                "t2od": (0.99, 1.08), "t2fixskew": (0.99, 1.08)}.get(fam)
        if zoom:
            plot_waves(w, "%s / %s (zoom)" % (fam, name), os.path.join(FIG, "%s__%s_zoom.png" % (fam, name)),
                       t_unit=1e-3, xlabel="time (ms)", xlim=zoom)
    plot_bridges(rows, os.path.join(FIG, "bridge_rail_minimum.png"))
    plot_t2skew(rows, os.path.join(FIG, "t2_skew_ilim_peak.png"))
    summary = dict(ngspice=ngspice_version(), decks=len(JOBS) + 1, truth_rows=64, b1_mismatch=nmis,
                   f2_disagree_rows=nF2, spice_xcheck_disagree=nx,
                   unsafe={fam: [x["case"] for x in rows if x["family"] == fam and
                                 str(x.get("verdict", "")).startswith("UNSAFE")]
                           for fam in FAMS},
                   sim_fail=[x["case"] for x in rows if x.get("verdict") == "SIM_FAIL"],
                   wall_s=round(time.time() - t_all, 1), quick=QUICK)
    with open(os.path.join(RES, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    import summarise
    summarise.main()
    print("Done in %.0f s; summary in results/summary.json" % (time.time() - t_all))


if __name__ == "__main__":
    main()
