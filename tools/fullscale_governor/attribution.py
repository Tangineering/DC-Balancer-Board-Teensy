#!/usr/bin/env python3
"""attribution.py - WHY the full-scale governor penalty exists, by ablation.

Runs the SDP + governor at S_I in {1, 127.8} for alpha in {200, 500} under
four configurations and prints, for each, the equivalent-hydrogen penalty
together with the quantities that separate the two candidate mechanisms:

  * FC energy delivered [kWh] and its change  - the ENERGY-SHIFT mechanism
    (governor moves load onto the battery; priced back by the s_eq correction)
  * hydrogen per kWh of FC energy and the mean stack efficiency - the
    OPERATING-POINT mechanism (governor makes the stack run where the convex
    map is less efficient)

Configurations
  default            convex H2 map (a0 parasitic, peak eta 0.50 at 35 kW), 50 kW/s ramp
  no-slew            ramp limit removed (P_fc_ramp 1e9 W/s)
  linear-map         constant-efficiency map, eta 0.5, no start cost - the
                     accounting the bench HIL tooling uses
  no-start-cost      convex map, h2_start_cost_g = 0

Reading: if the penalty vanishes under `linear-map` while the FC energy and
the FC-off fraction still move, the penalty is the operating-point effect and
nothing else.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sdp_governor3 import sdp_governor3, mh2_eq, h2_rate, Q_LHV_H2   # noqa: E402
from sweep_governor_scale import load_pdem, load_tpm, FIXED_CFG, DEFAULT_TPM, SOC_INITIAL  # noqa: E402

VARIANTS = (
    ("default", {}),
    ("no-slew", {"P_fc_ramp_W_per_s": 1e9}),
    ("linear-map", {"h2_model": "constant", "h2_start_cost_g": 0.0}),
    ("no-start-cost", {"h2_start_cost_g": 0.0}),
)


def fc_metrics(r):
    E = r.P_fc_applied.sum() / 3.6e6
    on = r.P_fc_applied > 0
    eta = r.P_fc_applied[on].sum() / (h2_rate(r.P_fc_applied[on], r.h2).sum() * Q_LHV_H2) if on.any() else float("nan")
    return E, (r.summary["M_H2_total"] / E if E > 0 else float("nan")), eta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdem", required=True)
    ap.add_argument("--tpm", default=DEFAULT_TPM)
    ap.add_argument("--alpha", type=float, nargs="+", default=[200.0, 500.0])
    ap.add_argument("--si", type=float, nargs="+", default=[1.0, 127.8])
    ap.add_argument("--variants", nargs="+", default=[v[0] for v in VARIANTS])
    a = ap.parse_args(argv)
    P = load_pdem(a.pdem)
    TPM = load_tpm(a.tpm)
    for name, extra in VARIANTS:
        if name not in a.variants:
            continue
        print("\n##### %s" % name)
        for al in a.alpha:
            cfgb = dict(FIXED_CFG, alpha=al, governor_enabled=False, **extra)
            rb = sdp_governor3(P, SOC_INITIAL, TPM, cfgb)
            base = mh2_eq(rb, SOC_INITIAL)
            E0, g0, eta0 = fc_metrics(rb)
            sp = rb.sp_cmd
            print("  alpha %g baseline: eq %.2f g  FC energy %.3f kWh  %.1f g/kWh  eta_mean %.3f  stack-off %.1f%% of samples  "
                  "commands in band %.1f%%  starts %d"
                  % (al, base, E0, g0, eta0, 100 * np.mean(rb.P_fc_cmd == 0),
                     100 * np.mean((sp >= 0.15) & (sp <= 0.85)), rb.n_starts))
            for SI in a.si:
                rg = sdp_governor3(P, SOC_INITIAL, TPM, dict(cfgb, governor_enabled=True, S_I=SI, policy_cache=rb.policy_cache))
                eq = mh2_eq(rg, SOC_INITIAL)
                E1, g1, eta1 = fc_metrics(rg)
                print("    S_I %6.1f: eq %.2f g (%+.2f%%)  FC energy %.3f kWh (%+.1f%%)  %.1f g/kWh (%+.1f%%)  eta_mean %.3f  "
                      "closed %.1f%%  FC-off %.1f%%  BT-off %.1f%%  P_fc on-mean %.1f kW"
                      % (SI, eq, 100 * (eq - base) / base, E1, 100 * (E1 / E0 - 1), g1, 100 * (g1 / g0 - 1), eta1,
                         100 * rg.summary["frac_closed_loop"], 100 * np.mean(rg.latchFC | rg.isoFC),
                         100 * np.mean(rg.latchBT | rg.isoBT), rg.P_fc_applied[rg.P_fc_applied > 0].mean() / 1e3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
