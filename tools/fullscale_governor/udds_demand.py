#!/usr/bin/env python3
"""udds_demand.py - synthesize the full-scale UDDS power demand the student's sweep needs.

sweep_governor_scale.m loads `simulink_pdem_output_UDDS.mat`, which is not in
the repository.  This script builds a stand-in:

1. Fit a road-load model to the stochastic Simulink cycles that ARE shipped
   (references/EMS/Pdem_cycles/*.mat log VehicleSpeed and P_req):
       F      = m_eff * a + k_drag * v^2 + f_roll
       P_req  = F * v / eta_trac      (F * v > 0)
              = F * v * eta_regen     (F * v < 0)
   by alternating least squares at 10 Hz.
2. Drive that model with the UDDS speed trace, i.e. the first 1369 s of the
   FTP-75 in references/drive_cycles/ftpcol.txt, and resample to whole seconds
   0..1369 exactly as the MATLAB does (interp1 linear).

The output is a stand-in, NOT the student's vector: it reproduces his tables
in shape and to within a few points of penalty, but his absolute baseline
(63.49 g at alpha 200) is ~15 % above ours (54.33 g) because his Simulink
vehicle demands more energy.  Drop his .mat into references/EMS/ and pass it
to sweep_governor_scale.py --pdem to get his exact numbers.

Usage
    python udds_demand.py [--out-npy PATH] [--out-mat PATH] [--cycles 1 3 5 8 9]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))

CYCLE_FMT = os.path.join(REPO, "references", "EMS", "Pdem_cycles", "simulink_pdem_output_stochastic_V%d.mat")
FTPCOL = os.path.join(REPO, "references", "drive_cycles", "ftpcol.txt")
UDDS_END_S = 1369.0
MPH = 0.44704
# V2 is a byte-duplicate of V1; V4 has no clean VehicleSpeed log; V6/V7/V10 never
# exceed 65 km/h so the drag term is ill-conditioned on them.
DEFAULT_CYCLES = (1, 3, 5, 8, 9)


def load_cycle(v: int):
    """(t10, vel_mps, accel, P_req) at 10 Hz for stochastic cycle v."""
    import tpm_generator as T
    meta = T._read_object_metadata(CYCLE_FMT % v)
    pairs = list(T._extract_timeseries_pairs(meta))
    P_pairs = [p for p in pairs if p[2].max() > 3e4 and p[2].min() < -1e4]
    S_pairs = [p for p in pairs if p[2].min() >= -1e-6 and 20 < p[2].max() < 160
               and np.all(np.abs(np.diff(p[2])) < 5)]
    if not P_pairs or not S_pairs:
        raise ValueError("cycle V%d: P=%d speed=%d candidate series" % (v, len(P_pairs), len(S_pairs)))
    tP, P = P_pairs[-1][1], P_pairs[-1][2]
    best = None
    for sp in S_pairs:          # pick the speed log that explains P_req best
        tg = np.arange(0, min(tP[-1], sp[1][-1]), 0.1)
        vel = np.interp(tg, sp[1], sp[2]) / 3.6
        Pg = np.interp(tg, tP, P)
        a = np.gradient(vel, tg)
        X = np.c_[a * vel, vel ** 3, vel]
        c, *_ = np.linalg.lstsq(X, Pg, rcond=None)
        rms = float(np.sqrt(np.mean((Pg - X @ c) ** 2)))
        if best is None or rms < best[0]:
            best = (rms, tg, vel, a, Pg)
    return best[1:]


def fit_road_load(cycles=DEFAULT_CYCLES, iters: int = 50):
    V, A, P = [], [], []
    for v in cycles:
        _, vel, a, Pg = load_cycle(v)
        V.append(vel); A.append(a); P.append(Pg)
    V = np.concatenate(V); A = np.concatenate(A); P = np.concatenate(P)
    Fv = np.c_[A * V, V ** 3, V]
    c3 = np.array([2242.0, 0.7, 150.0]); eta_t, eta_r = 0.9, 0.9
    for _ in range(iters):
        pos = (Fv @ c3) > 0
        scale = np.where(pos, 1.0 / eta_t, eta_r)
        c3, *_ = np.linalg.lstsq(Fv * scale[:, None], P, rcond=None)
        F = Fv @ c3
        pos = F > 0
        eta_t = np.sum(F[pos] ** 2) / np.sum(F[pos] * P[pos])
        eta_r = np.sum(F[~pos] * P[~pos]) / np.sum(F[~pos] ** 2)
    Pm = np.where(pos, F / eta_t, F * eta_r)
    res = P - Pm
    return dict(m_eff=float(c3[0]), k_drag=float(c3[1]), f_roll=float(c3[2]), eta_trac=float(eta_t),
                eta_regen=float(eta_r), rms_W=float(np.sqrt(np.mean(res ** 2))),
                R2=float(1 - np.var(res) / np.var(P)), n=int(len(P)))


def udds_speed():
    rows = [l.split() for l in open(FTPCOL, encoding="utf-8", errors="replace").read().splitlines()[2:]]
    t = np.array([float(r[0]) for r in rows if len(r) == 2])
    mph = np.array([float(r[1]) for r in rows if len(r) == 2])
    m = t <= UDDS_END_S
    return t[m], mph[m] * MPH


def synthesize(coef: dict) -> np.ndarray:
    t, vel = udds_speed()
    tg = np.arange(0, UDDS_END_S + 1e-4, 0.1)
    v10 = np.interp(tg, t, vel)
    a10 = np.gradient(v10, tg)
    F = coef["m_eff"] * a10 * v10 + coef["k_drag"] * v10 ** 3 + coef["f_roll"] * v10
    Pd = np.where(F > 0, F / coef["eta_trac"], F * coef["eta_regen"])
    return np.interp(np.arange(0, UDDS_END_S + 1.0), tg, Pd)      # whole seconds 0..1369


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cycles", type=int, nargs="+", default=list(DEFAULT_CYCLES))
    ap.add_argument("--out-npy", default=None)
    ap.add_argument("--out-mat", default=None)
    a = ap.parse_args(argv)
    coef = fit_road_load(a.cycles)
    print("road load: m_eff %.1f kg  0.5*rho*CdA %.3f kg/m  f_roll %.1f N  eta_trac %.3f  eta_regen %.3f  rms %.0f W  R2 %.4f  n %d"
          % (coef["m_eff"], coef["k_drag"], coef["f_roll"], coef["eta_trac"], coef["eta_regen"], coef["rms_W"], coef["R2"], coef["n"]))
    P = synthesize(coef)
    print("UDDS: N %d  range [%.1f, %.1f] kW  mean %.2f kW  traction %.3f kWh" % (len(P), P.min() / 1e3, P.max() / 1e3, P.mean() / 1e3, P[P > 0].sum() / 3.6e6))
    if a.out_npy:
        np.save(a.out_npy, P); print("wrote", a.out_npy)
    if a.out_mat:
        from scipy.io import savemat
        savemat(a.out_mat, {"P_dem1": P.reshape(1, -1)}); print("wrote", a.out_mat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
