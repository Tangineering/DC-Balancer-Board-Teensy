"""Sim 7 supplement: the FR-07 raise budget under the operator rulings of 2026-11-16 (RESULTS.md Section 11).

Rulings applied (RESULTS.md Section 11.1):
  - FR-07 budget 3.5 ms, pin-34 rising edge to REG03-05 write complete;
  - FC-window thresholds: close at G < 0.40 A, admit at G >= 0.50 A, so the IINDPM guaranteed at the H1 edge is 0.40 A;
  - criterion: no U101 OVP trip at the s5-lo corner, 21.588 V (rising minimum with leak);
  - C_VMOT,min = 1.0 mF until T-E-04 measures it;
  - regen-image VINDPM (REG05) 19.0 V -> 18.4 V; stage 1 stays 18.2 V.

The script loads run.py by importlib without calling main(), so it writes no file of run.py. It changes only module
attributes in memory (the VINDPM of the four charger corners and the ratchet trigger) and restores nothing, because
each A/B block sets both values explicitly.

Usage (about 15 min):
  PYTHONUTF8=1 /c/msys64/ucrt64/bin/python.exe rulings_2026-11-16.py </dev/null > rulings_2026-11-16_out.txt

Every boundary is a bisection of T_lat (run.bisect_tlat, upper end of a 1e-5 s interval, search limit 60 ms). Each
boundary is the minimum over the brakes named in the row and the charger corners named in the row; the printout names
the brake and corner that set it. 0.00 ms means that V-MOT crosses the threshold at T_lat = 0 (capacity-limited).
"""
import importlib.util
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sim7", os.path.join(HERE, "run.py"))
r7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r7)

# ---------------------------------------------------------------- ruled design point
C_VMOT = 1.0e-3            # ruling 5: C_VMOT,min 1.0 mF
I_EDGE = 0.40              # ruling 3: window close threshold = IINDPM guaranteed at the H1 edge
BUDGET = 3.5               # ruling 2: FR-07 edge-to-write-complete budget (ms)
T_DETECT = 1.0             # T-D-12 detect tick (<= 1 ms, design T-D-12 row)
THR_NOTRIP = 21.588        # ruling 4: U101 OVP rising minimum with leak (s5-lo)
THR_TEST = 20.5            # superseded test acceptance, printed for reference
V_H1_TCR = 18.127          # H1 rise maximum with resistor TCR (sim 3)
V_H1_OVBUS = 19.25         # H1 rise with VBUS at the 17.5 V OV_BUS limit
ACC_MIN = 0.83             # IINDPM accuracy at 500 mA: 415 mA minimum (SLUSDV2C)
R_PATH_MAX = 0.19          # R_PATH_RG maximum (H.19)
I_STATIC = 1.76            # current in the static-maximum construction of the false-restore start (design T-D-12)

TOL = {"lo": 1.02, "nom": 1.0, "d310": 1.0, "hi": 0.98}    # +-2 % VINDPM corners, as sim 6 (19.38 / 19.0 / 18.62 V)
CORN = list(r7.CHARGERS)
MEAS = r7.BB_MEAS
BMAP = {b[0]: b for b in r7.MECH + [(n, None, None, None) for n, _p, _d in r7.CP]}


def set_vindpm(vr):
    """Set the regen-image VINDPM of every corner to vr x (1 +- 2 %) and the T3 step-4 ratchet trigger to
    vr x 1.02 + 0.19 V, the construction of the 19.57 V trigger in run.py (RATCHET_V)."""
    for k in r7.CHARGERS:
        r7.CHARGERS[k]["vind2"] = round(vr * TOL[k], 4)
    r7.RATCHET_V = vr * 1.02 + 0.19
    print("VINDPM %.2f V: corners %s; ratchet trigger %.3f V; stage 1 %s" %
          (vr, {k: v["vind2"] for k, v in r7.CHARGERS.items()}, r7.RATCHET_V,
           {k: v["vind1"] for k, v in r7.CHARGERS.items()}), flush=True)


def boundary(label, brakes, corners=CORN, thr=(THR_TEST, THR_NOTRIP), speeds=(), ipre=I_EDGE, budget=True, **kw):
    """Bisect T_lat for every (threshold, corner, brake); print and return the minimum per threshold (ms).
    speeds: extra 12 A mechanical brakes (name, v0, v1) not in run.MECH."""
    probs, meta = [], []
    for th in thr:
        for ck in corners:
            for bn in brakes:
                probs.append(r7.base_case(C=C_VMOT, stop_thr=th, ipre=ipre, **r7.corner_kw(ck),
                                          **r7.brake_kw(BMAP[bn]), **kw))
                meta.append((th, ck, bn))
            for (bn, v0, v1) in speeds:
                probs.append(r7.base_case(C=C_VMOT, stop_thr=th, ipre=ipre, kind=0, v0=v0, v1=v1, icmd=12.0,
                                          **r7.corner_kw(ck), **kw))
                meta.append((th, ck, bn))
    t0 = time.time()
    res = r7.bisect_tlat(probs, hi=0.060, tol=1e-5)
    out, txt = {}, []
    for th in thr:
        vals = [(res[i] * 1e3, m[1], m[2]) for i, m in enumerate(meta) if m[0] == th]
        mn = min(vals)
        out[th] = mn[0]
        s = "%.3f V: %.2f ms (%s, %s)" % (th, mn[0], mn[1], mn[2])
        if budget and th == THR_NOTRIP:
            s += " margin %+.2f" % (mn[0] - BUDGET) if mn[0] > 0 else " margin -"
        txt.append(s)
    print("  %-58s %s   [%.0f s]" % (label, " | ".join(txt), time.time() - t0), flush=True)
    return out


def budget_table():
    """The margin table of RESULTS.md Table 16 (IINDPM 0.40 A at the edge, 1.0 mF)."""
    boundary("Nominal (eff 0.9/0.97, 0.1 ms lag)", MEAS)
    boundary("Acc 0.83 + TCR (H1 rise 18.127 V)", MEAS, V0=V_H1_TCR, acc=ACC_MIN)
    boundary("Acc 0.83 + TCR + 1 ms charger lag", MEAS, V0=V_H1_TCR, acc=ACC_MIN, tau=1e-3)
    boundary("12 A brake from 3.1 m/s", [], speeds=[("12A 3.1->1", 3.1, 1.0)])
    boundary("25 A State-98 brake 2.5 -> 1 m/s", ["trap25A 2.5->1"])
    boundary("VBUS 17.5 V at the edge (H1 rise 19.25 V)", MEAS, V0=V_H1_OVBUS)
    boundary("12 A from 3.5 m/s, acc 0.83 + TCR, nom/d310/hi", [], corners=["nom", "d310", "hi"],
             speeds=[("12A 3.5->1", 3.5, 1.0)], V0=V_H1_TCR, acc=ACC_MIN)
    boundary("eff 1.0 + 1 ms lag + acc 0.83 + TCR, d310", MEAS, corners=["d310"],
             eg=1.0, ei=1.0, tau=1e-3, acc=ACC_MIN, V0=V_H1_TCR)
    print("  capacity-limited cases (0.00 ms = crossing at T_lat = 0):", flush=True)
    boundary("12 A brake from 3.25 m/s", [], speeds=[("12A 3.25->1", 3.25, 1.0)])
    boundary("eff 1.0 + 1 ms lag + acc 0.83 + TCR, all corners", MEAS,
             eg=1.0, ei=1.0, tau=1e-3, acc=ACC_MIN, V0=V_H1_TCR)
    for ck in CORN:
        boundary("CP 23 W, %s corner" % ck, ["CP 23 W"], corners=[ck])


def regen_armed():
    """Regen-armed cruise (no T3): converter-release dead time t_d with the regen image in force throughout."""
    probs, meta = [], []
    for th in (THR_TEST, THR_NOTRIP):
        for ck in CORN:
            ch = r7.CHARGERS[ck]
            for bn in ("ML0157 47.30", "CP 18.9 W"):
                probs.append(r7.base_case(C=C_VMOT, stop_thr=th, regen_armed=1, adv=0.0, vind1=ch["vind2"],
                                          vind2=ch["vind2"], ppost=ch["p"], ilim=ch["ilim"],
                                          **r7.brake_kw(BMAP[bn])))
                meta.append((th, ck, bn))
    res = r7.bisect_tlat(probs, hi=0.060, tol=1e-5)
    for th in (THR_TEST, THR_NOTRIP):
        vals = [(res[i] * 1e3, m[1], m[2]) for i, m in enumerate(meta) if m[0] == th]
        print("  regen-armed t_d limit %.3f V: %.2f ms (%s, %s)" % ((th,) + min(vals)), flush=True)


def peaks_at_budget():
    """V-MOT peak and harvested energy at T_lat = 3.5 ms (nominal model, every corner)."""
    cs, mt = [], []
    for ck in CORN:
        for bn in ("ML0157 47.30", "CP 18.9 W", "step 2->1"):
            cs.append(r7.base_case(C=C_VMOT, tlat=BUDGET * 1e-3, ipre=I_EDGE, **r7.corner_kw(ck),
                                   **r7.brake_kw(BMAP[bn])))
            mt.append((ck, bn))
    O = r7.simulate(cs, t_max=0.7)
    print("  T_lat 3.5 ms peaks (V):", ", ".join("%s/%s %.3f" % (ck, bn.split()[0], O["Vmax"][i])
                                                for i, (ck, bn) in enumerate(mt)), flush=True)
    print("  T_lat 3.5 ms E_harv (J):", ", ".join("%s/%s %.4f" % (ck, bn.split()[0], O["E_harv"][i])
                                                 for i, (ck, bn) in enumerate(mt)), flush=True)


def tdd12(vr, v0):
    """T-D-12 false restore: start at the V-MOT static maximum v0, charger dropped to the FC image at IINDPM 0.40 A;
    the time to 21.588 V less the detect tick is the re-raise deadline."""
    for lab, kw in (("nominal", {}), ("acc 0.83 + 1 ms lag", dict(acc=ACC_MIN, tau=1e-3))):
        b = boundary("T-D-12, VINDPM %.1f V, start %.3f V, %s" % (vr, v0, lab), MEAS, thr=(THR_NOTRIP,),
                     budget=False, V0=v0, **kw)[THR_NOTRIP]
        print("    -> re-raise deadline after the %.1f ms detect tick: %.2f ms" % (T_DETECT, b - T_DETECT),
              flush=True)


def i_floor_design_form():
    """H.20 backstop race floor, design form re-derived at the ruled point:
    I_floor = (P / V_H1R - (V_thr - V_H1R) x C / T_lat) / 0.88."""
    vh = r7.V_H1R
    for p in (18.9, 23.0):
        i = (p / vh - (THR_NOTRIP - vh) * C_VMOT / (BUDGET * 1e-3)) / 0.88
        print("  I_floor at %.1f W, %.3f V, %.1f mF, %.1f ms: (%.1f/%.2f - %.3f x %.1e / %.1e) / 0.88 = %.4f A"
              % (p, THR_NOTRIP, C_VMOT * 1e3, BUDGET, p, vh, THR_NOTRIP - vh, C_VMOT, BUDGET * 1e-3, max(i, 0.0)),
              flush=True)


if __name__ == "__main__":
    T0 = time.time()
    print("Sim 7 supplement, rulings 2026-11-16: C_VMOT %.1f mF, IINDPM at the edge %.2f A, budget %.1f ms, "
          "V_H1R %.2f V" % (C_VMOT * 1e3, I_EDGE, BUDGET, r7.V_H1R), flush=True)

    # 1. VINDPM A/B: the full budget table, regen-armed limit and 3.5 ms snapshot under both images.
    for vr in (19.0, 18.4):
        print("\n=== Budget table at VINDPM %.1f V ===" % vr, flush=True)
        set_vindpm(vr)
        budget_table()
        regen_armed()
        peaks_at_budget()
        print("  VESC cut reference (threshold 21.35 V, nominal):", flush=True)
        boundary("Nominal, cut at 21.35 V", MEAS, thr=(21.35,), budget=False)

    # 2. T-D-12 from both static maxima (VINDPM_max + 1.76 A x 0.19 ohm); 19.72 V is the design figure.
    print("\n=== T-D-12 false restore ===", flush=True)
    set_vindpm(19.0)
    print("  static maximum, VINDPM 19.0 V: %.4f V (design figure 19.72 V used)" % (19.0 * 1.02 + I_STATIC * R_PATH_MAX))
    tdd12(19.0, 19.72)
    set_vindpm(18.4)
    v184 = 18.4 * 1.02 + I_STATIC * R_PATH_MAX
    print("  static maximum, VINDPM 18.4 V: %.4f V" % v184)
    tdd12(18.4, v184)

    # 3. Floor comparison at 1.0 mF (VINDPM 18.4 V): the superseded 0.30 A floor and a 0.50 A floor.
    print("\n=== IINDPM at the edge, comparison (VINDPM 18.4 V) ===", flush=True)
    boundary("0.30 A, nominal", MEAS, ipre=0.30)
    boundary("0.50 A, nominal", MEAS, ipre=0.50)
    boundary("0.50 A, eff 1.0 + 1 ms lag + acc 0.83 + TCR, d310", MEAS, ipre=0.50, corners=["d310"],
             eg=1.0, ei=1.0, tau=1e-3, acc=ACC_MIN, V0=V_H1_TCR)

    # 4. H.20 design-form race floor at the ruled point.
    print("\n=== H.20 I_floor design form ===", flush=True)
    i_floor_design_form()
    print("\nTotal %.0f s" % (time.time() - T0))
