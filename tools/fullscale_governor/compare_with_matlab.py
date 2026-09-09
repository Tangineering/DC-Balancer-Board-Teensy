#!/usr/bin/env python3
"""compare_with_matlab.py - check the Python sweep against the MATLAB sweep.

Both JSON files must come from the SAME P_dem vector and TPM:
  MATLAB : scratchpad/run_sweep_synth.m  (OUT_JSON=...)  -> res struct array
  Python : sweep_governor_scale.py --json ...

Prints, per alpha and S_I, both values of every table column and the
difference.  Exit status 1 if any M_H2,eq differs by more than --tol grams or
any closed-loop / latched fraction by more than --tol-frac.
"""
import argparse
import json
import sys


def as_list(x):
    return list(x) if isinstance(x, (list, tuple)) else [x]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("matlab_json")
    ap.add_argument("python_json")
    ap.add_argument("--tol", type=float, default=0.05, help="grams of M_H2,eq")
    ap.add_argument("--tol-frac", type=float, default=0.005)
    a = ap.parse_args(argv)
    M = json.load(open(a.matlab_json))
    P = json.load(open(a.python_json))
    if isinstance(M, dict):
        M = [M]
    bad = 0
    for m in M:
        p = next((r for r in P if abs(r["alpha"] - m["alpha"]) < 1e-9), None)
        if p is None:
            print("alpha %g: no Python row" % m["alpha"])
            bad += 1
            continue
        print("\nalpha = %g   baseline M_H2,eq  MATLAB %.4f  Python %.4f  (d %.4f g)   SOC rms  %.4e / %.4e   starts %d / %d" % (
            m["alpha"], m["MH2_eq_base"], p["MH2_eq_base"], p["MH2_eq_base"] - m["MH2_eq_base"],
            m["SOCrms_base"], p["SOCrms_base"], m["starts_base"], p["starts_base"]))
        print("%8s | %10s %10s %8s | %8s %8s | %8s %8s | %8s %8s | %6s %6s" % (
            "S_I", "MH2eq M", "MH2eq P", "d[g]", "pen M%", "pen P%", "closed M", "closed P", "latch M", "latch P", "ev M", "ev P"))
        for key in ("SI", "MH2_eq", "penalty", "closed", "latched", "events"):
            m[key] = as_list(m[key])
            p[key] = as_list(p[key])
        for i, SI in enumerate(m["SI"]):
            d = p["MH2_eq"][i] - m["MH2_eq"][i]
            flag = ""
            if abs(d) > a.tol or abs(p["closed"][i] - m["closed"][i]) > a.tol_frac or abs(p["latched"][i] - m["latched"][i]) > a.tol_frac:
                flag = "  <-- MISMATCH"
                bad += 1
            print("%8.1f | %10.4f %10.4f %8.4f | %8.2f %8.2f | %8.4f %8.4f | %8.4f %8.4f | %6d %6d%s" % (
                SI, m["MH2_eq"][i], p["MH2_eq"][i], d, m["penalty"][i], p["penalty"][i],
                m["closed"][i], p["closed"][i], m["latched"][i], p["latched"][i], m["events"][i], p["events"][i], flag))
    print("\n%s" % ("ALL ROWS MATCH within tolerance" if bad == 0 else "%d mismatching row(s)" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
