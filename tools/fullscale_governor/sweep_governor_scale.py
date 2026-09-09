#!/usr/bin/env python3
"""sweep_governor_scale.py - port of references/EMS/sweep_governor_scale.m.

Sweeps the governor current scale S_I (Class-2 constants only) for the SDP EMS
on the UDDS cycle at alpha in {200, 500} and prints the student's table:
S_I, closed-loop entry [kW], M_H2,eq governed [g], penalty vs the ungoverned
baseline, SoC RMS degradation ratio, closed-loop fraction.

Usage
    python sweep_governor_scale.py --pdem <file> [--tpm <mat>] [--alpha 200 500]
                                   [--si 1 10 25 50 100 127.8] [--json out.json]

--pdem accepts a .npy (1-D W at 1 Hz), a .mat with variable P_dem1, or the
student's simulink_pdem_output_UDDS.mat (decoded through tools/tpm_generator's
MCOS reader; resampled to whole seconds 0..1369 like the MATLAB).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools"))

from sdp_governor3 import sdp_governor3, mh2_eq, EM_V, Q_AH  # noqa: E402

DEFAULT_TPM = os.path.join(REPO, "references", "EMS", "TPM_fullsize.mat")
SOC_INITIAL = 0.6
FIXED_CFG = dict(
    n_subticks=880, P_fc_ramp_W_per_s=50000.0, h2_model="convex", h2_a0=0.05,
    h2_P_peak_W=35000.0, h2_eta_peak=0.50, h2_start_cost_g=0.5,
    h2_s_eq_fixed=1.0 / (0.50 * 120000.0), verbose=False,
)


def load_pdem(path: str) -> np.ndarray:
    if path.endswith(".npy"):
        return np.load(path).astype(float).ravel()
    from scipy.io import loadmat
    m = loadmat(path)
    if "P_dem1" in m:
        return np.asarray(m["P_dem1"], dtype=float).ravel()
    # Simulink output: decode the opaque timeseries like tools/tpm_generator.py
    import tpm_generator as T
    meta = T._read_object_metadata(path)
    pairs = list(T._extract_timeseries_pairs(meta))
    P_pairs = [p for p in pairs if p[2].max() > 3e4 and p[2].min() < -1e4]
    if not P_pairs:
        raise ValueError("no P_dem-like timeseries in %s" % path)
    t, d = P_pairs[-1][1], P_pairs[-1][2]
    whole = np.arange(0, 1370.0)
    return np.interp(whole, t, d)          # interp1 linear onto 0:1:1369


def load_tpm(path: str) -> np.ndarray:
    from scipy.io import loadmat
    m = loadmat(path)
    key = [k for k in m if not k.startswith("__")][0]
    return np.asarray(m[key], dtype=float)


def run_sweep(P_dem, TPM, alphas, sweep_SI, log=print):
    res = []
    for a in alphas:
        log("\n===== alpha = %g =====" % a)
        cfg_b = dict(FIXED_CFG, alpha=a, governor_enabled=False)
        t0 = time.time()
        rb = sdp_governor3(P_dem, SOC_INITIAL, TPM, cfg_b)
        log("  baseline ... %.1f s (value iteration %d sweeps)" % (time.time() - t0, rb.vi_sweeps))
        row = dict(alpha=a, MH2_base=rb.summary["M_H2_total"], SOC_end_base=float(rb.SOC[-1]),
                   MH2_eq_base=mh2_eq(rb, SOC_INITIAL), SOCrms_base=rb.summary["SOC_rms_dev"],
                   starts_base=rb.n_starts, vi_sweeps=rb.vi_sweeps,
                   SI=[], entry_kW=[], MH2=[], SOC_end=[], MH2_eq=[], penalty=[], SOCrms=[], SOCratio=[],
                   closed=[], latched=[], events=[], mean_dPfc=[], starts=[], sat=[])
        for SI in sweep_SI:
            cfg_g = dict(FIXED_CFG, alpha=a, governor_enabled=True, S_I=SI, policy_cache=rb.policy_cache)
            t0 = time.time()
            rg = sdp_governor3(P_dem, SOC_INITIAL, TPM, cfg_g)
            log("  S_I = %6.1f ... %.1f s" % (SI, time.time() - t0))
            eq = mh2_eq(rg, SOC_INITIAL)
            row["SI"].append(SI)
            row["entry_kW"].append(2 * rg.C.MINORITY_I_MIN_A * EM_V / 1e3)
            row["MH2"].append(rg.summary["M_H2_total"])
            row["SOC_end"].append(float(rg.SOC[-1]))
            row["MH2_eq"].append(eq)
            row["penalty"].append(100.0 * (eq - row["MH2_eq_base"]) / row["MH2_eq_base"])
            row["SOCrms"].append(rg.summary["SOC_rms_dev"])
            row["SOCratio"].append(rg.summary["SOC_rms_dev"] / row["SOCrms_base"])
            row["closed"].append(rg.summary["frac_closed_loop"])
            row["latched"].append(rg.summary["frac_latched"])
            row["events"].append(rg.n_latch_events)
            row["mean_dPfc"].append(rg.summary["mean_abs_dP_fc"])
            row["starts"].append(rg.n_starts)
            row["sat"].append(rg.summary["frac_saturated"])
        res.append(row)
    return res


def print_tables(res, log=print):
    for r in res:
        log("\n========== SDP, UDDS, alpha = %g: governor scale sweep ==========" % r["alpha"])
        log("baseline M_H2,eq = %.2f g,  SOC RMS = %.3e,  starts = %d\n" % (r["MH2_eq_base"], r["SOCrms_base"], r["starts_base"]))
        log("%8s %10s %10s %9s %8s %8s %8s %8s %9s" % ("S_I", "entry kW", "MH2eq [g]", "penalty", "SOC x", "closed", "latched", "events", "md|dPfc|"))
        for i in range(len(r["SI"])):
            log("%8.1f %10.1f %10.2f %8.2f%% %8.2f %7.1f%% %7.1f%% %8d %9.0f" % (
                r["SI"][i], r["entry_kW"][i], r["MH2_eq"][i], r["penalty"][i], r["SOCratio"][i],
                100 * r["closed"][i], 100 * r["latched"][i], r["events"][i], r["mean_dPfc"][i]))
        log("=" * 64)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdem", required=True)
    ap.add_argument("--tpm", default=DEFAULT_TPM)
    ap.add_argument("--alpha", type=float, nargs="+", default=[200.0, 500.0])
    ap.add_argument("--si", type=float, nargs="+", default=[1, 10, 25, 50, 100, 127.8])
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    P_dem = load_pdem(a.pdem)
    TPM = load_tpm(a.tpm)
    print("UDDS: P_dem range [%.1f, %.1f] kW, N = %d" % (P_dem.min() / 1e3, P_dem.max() / 1e3, len(P_dem)))
    res = run_sweep(P_dem, TPM, a.alpha, a.si)
    print_tables(res)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print("wrote", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
