#!/usr/bin/env python3
"""
make_costtogo_avg.py — AVERAGE-COST SDP for the FCHEV, with no SOC target.

    python3 make_costtogo_avg.py TPM.mat -o CostToGo_h_avg.mat [--rate-penalty R]

WHY THIS EXISTS
---------------
The discounted formulation needed an artificial SOC reference, and that
reference had to be re-tuned as the pack drained. Worse, with the pack below
the target the SOC term only ever asked for MORE fuel cell, which is what drove
P_fc onto its ceiling and latched OC_FC.

The reference was a crutch for a mis-specified horizon, not a modelling choice.
Measured on this plant, the battery takes 40,000-170,000 steps to cross the SOC
band, while gamma = 0.97 gives the value function a horizon of 33 steps. SOC
depletion is discounted into irrelevance, so inside the band charge is free and
SOMETHING has to price it. The target was that something.

Average cost removes the discount instead of papering over it:

    h(x) + rho = min_u [ g(x,u) + E_d'[ h(x') ] ]

rho is the optimal long-run average cost per step and h is the RELATIVE value
function. Nothing is discounted, so a policy that drains the pack reaches the
band and pays there forever, at full weight. Charge sustenance becomes a
consequence of the band -- a physical limit -- rather than a tuned setpoint.

The stage cost is then hydrogen only:

    g(u) = un + K_CONV*un**2          un = P_fc / P_FC_MAX

and -dh/dSOC is the equivalence factor, DERIVED rather than assumed. That is the
quantity ECMS hand-tunes.

OPTIONAL RATE PENALTY (--rate-penalty)
--------------------------------------
With K_CONV measured at 0.193 the fuel map is nearly linear, and a nearly-linear
cost optimises at a corner. Adding R*(P_fc - P_fc_prev)**2 makes the stage cost
strictly convex in u regardless, so interior splits exist for any plant. It is
also the power-follower behaviour written as a cost -- a PEM stack cannot follow
fast load steps, and chasing them degrades it.

The price is that P_fc_prev becomes a state: h is (SOC, demand, u_prev) rather
than (SOC, demand). Pass R = 0 for the 2-D version.

SOLVER
------
Relative value iteration: sweep, then subtract h at a reference state. Converged
on the SPAN of the residual (max - min), which is the right criterion here --
h is only defined up to an additive constant, so ||h_new - h|| never reaches
zero while rho is nonzero.
"""

import argparse
import sys

import numpy as np
import scipy.io

# ── Must match sdp_ems_node.py ───────────────────────────────────────────────
SOC_MIN, SOC_MAX, SOC_BINS = 0.25, 0.90, 250
# New build: road-load demand, non-negative, full UDDS to 5 m/s -> ~32 W.
PDEM_MIN, PDEM_MAX = 0.0, 35.0
# 17.4 W = 1.10 A at 15.8 V, the safety ceiling under LIMIT_I_FC_MAX 1.4.
# NOT 20 W: the H-20's second fuel-map kink at 18.60 W needs 1.18 A, which
# is over that ceiling, so only the first kink (13.95 W, 0.88 A) is
# reachable. Trying for the second means running at 1.18 A against a limit
# that latches on ONE raw sample, with 0.05 A of sensor noise. Not worth it.
P_FC_MAX, P_BATT_MAX, P_BATT_MIN = 17.4, 35.0, -17.4
Em, Q_AH = 7.2, 5.0
U_STEPS = 50
K_CONV = 0.193          # measured from the polarization fit
FC_MAY_CHARGE = False   # keep the stack capped at demand until hold-up exists
BAND_PENALTY = 1.0e3
RATE_PENALTY = 0.0      # R; > 0 switches on the 3-D (u_prev) formulation
U_PREV_STEPS = 25       # coarser grid for the u_prev axis, to keep h tractable
# DP DECISION INTERVAL, seconds. NOT the controller rate (20 Hz) -- the interval
# the value function reasons over. At 1 s the pack moves 0.036 of an SOC bin per
# step, so the chain is almost absorbing: discounting hid that (gamma 0.97 never
# looked far enough to care), but average cost has to propagate the band penalty
# ~1e5 steps inward and RVI crawls. At 60 s one step spans ~2.1 bins and the
# chain mixes. The demand TPM is raised to the matching power.
DT_DP = 60.0


def _grids(tpm_path):
    TPM = np.asarray(scipy.io.loadmat(tpm_path)["TPM"], dtype=float)
    if TPM.shape[0] != TPM.shape[1]:
        sys.exit(f"TPM must be square, got {TPM.shape}")
    rs = TPM.sum(axis=1, keepdims=True)
    TPM = np.where(rs > 0, TPM / np.where(rs > 0, rs, 1.0), 1.0 / TPM.shape[0])
    if DT_DP > 1.0:
        TPM = np.linalg.matrix_power(TPM, int(round(DT_DP)))
        rs = TPM.sum(axis=1, keepdims=True)
        TPM = np.where(rs > 0, TPM / np.where(rs > 0, rs, 1.0), 1.0/TPM.shape[0])
    n_pd = TPM.shape[0]
    soc = np.linspace(SOC_MIN, SOC_MAX, SOC_BINS)
    pdem = np.linspace(PDEM_MIN, PDEM_MAX, n_pd)
    u = np.linspace(0.0, P_FC_MAX, U_STEPS)
    return TPM, n_pd, soc, pdem, u


def _transition(soc, pdem, u, n_pd):
    """Feasibility mask, interpolation weights, and the band penalty."""
    P_batt = pdem[:, None] - u[None, :]                      # (D,U)
    dsoc = (P_batt / Em) / (3600.0 * Q_AH) * DT_DP
    soc_next_raw = soc[:, None, None] - dsoc[None, :, :]     # (S,D,U)

    cap = (np.full_like(pdem, P_FC_MAX) if FC_MAY_CHARGE
           else np.maximum(pdem, 0.0))[:, None]
    feas = ((P_batt >= P_BATT_MIN) & (P_batt <= P_BATT_MAX)
            & (u[None, :] <= cap + 1e-9))[None, :, :] \
        & np.ones((SOC_BINS, 1, 1), dtype=bool)

    oob = (soc_next_raw < SOC_MIN) | (soc_next_raw > SOC_MAX)
    soc_next = np.clip(soc_next_raw, SOC_MIN, SOC_MAX)

    # Linear interpolation in SOC. With nearest-neighbour every action lands in
    # the same successor bin, h cancels out of the comparison, and the policy
    # collapses to a corner -- the original bang-bang.
    db = soc[1] - soc[0]
    pos = np.clip((soc_next - SOC_MIN) / db, 0.0, SOC_BINS - 1.0)
    nsi = np.minimum(np.floor(pos).astype(np.int32), SOC_BINS - 2)
    whi = pos - nsi
    wlo = 1.0 - whi
    return feas, nsi, wlo, whi, oob


def build_2d(tpm_path, max_iter, tol, verbose=True):
    global DT_DP
    TPM, n_pd, soc, pdem, u = _grids(tpm_path)
    feas, nsi, wlo, whi, oob = _transition(soc, pdem, u, n_pd)

    # ── FUEL TERM FROM THE DATASHEET, NOT A FITTED QUADRATIC ─────────────────
    # H-20 manual section 5, "H20 H2 flow": ml/min against STACK watts. Referred
    # to the bus through the boost efficiency, the marginal cost is
    #
    #     0    -> 13.95 W   about 10.1-10.8 ml/min per bus-W   (flat)
    #    13.95 -> 18.60 W                17.2
    #    18.60 -> 21.86 W                30.7
    #
    # A quadratic cannot represent that. Fitted over 0..12 W it gave K_CONV
    # 0.193 from the polarization curve and 0.000 from this chart -- both
    # correct, because the whole 0..12 W range IS the flat segment, which is
    # why every earlier formulation came out bang-bang. The convexity is real
    # and lives at 15-24 W; the old P_FC_MAX simply never reached it.
    #
    # Interpolating the measured curve directly means the optimum lands where
    # marginal flow crosses the battery's shadow price -- at a KINK. The stack
    # then holds a fixed power while the battery absorbs demand swings, which
    # is load-levelling, and it is derived rather than tuned.
    FLOW_P_STACK = np.array([0.0, 5.0, 10.0, 15.0, 20.0, 23.5])
    FLOW_ML_MIN  = np.array([3.0, 50.0, 100.0, 150.0, 230.0, 330.0])
    ETA_BOOST = 0.93
    flow_u = np.interp(u / ETA_BOOST, FLOW_P_STACK, FLOW_ML_MIN)
    flow_u = flow_u / FLOW_ML_MIN.max()          # normalise to ~0..1
    stage = flow_u[None, None, :] + BAND_PENALTY * oob
    BIG = 1.0e9
    stage = np.where(feas, stage, BIG)
    any_feas = feas.any(axis=2)
    fmask = any_feas.astype(float)

    if verbose:
        print(f"  grid SOC {SOC_BINS} x demand {n_pd} x actions {U_STEPS}")
        print(f"  feasible pairs {100.0*feas.sum()/feas.size:.1f}%, "
              f"band-penalised {100.0*oob.sum()/oob.size:.1f}%")
        print("  stage cost: H-20 DATASHEET H2 flow, interpolated. No SOC term.")
        kb = [13.95, 18.60]
        print(f"  fuel-map kinks (bus): {kb[0]:.2f} W = {kb[0]/15.8:.2f} A, "
              f"{kb[1]:.2f} W = {kb[1]/15.8:.2f} A "
              f"({'both' if P_FC_MAX >= kb[1] else 'only the first'} reachable "
              f"at P_FC_MAX {P_FC_MAX} W)")

    h = np.zeros((SOC_BINS, n_pd))
    ref = (SOC_BINS // 2, n_pd // 2)
    pdx = np.arange(n_pd)[None, :, None]
    rho = 0.0
    for it in range(1, max_iter + 1):
        num = (h * fmask) @ TPM.T
        den = fmask @ TPM.T
        Eh = np.where(den > 1e-12, num / np.where(den > 1e-12, den, 1.0), 0.0)
        fut = wlo * Eh[nsi, pdx] + whi * Eh[nsi + 1, pdx]
        total = np.where(feas, stage + fut, BIG)        # NO discount
        h_new = np.minimum(total.min(axis=2), BIG)

        rho = h_new[ref]
        h_new -= rho
        resid = h_new - h
        span = float(resid.max() - resid.min())         # h is defined up to a constant
        h = h_new
        if verbose and (it % 100 == 0 or it == 1):
            print(f"    iter {it:5d}   span {span:.3e}   rho {rho:.6f}")
        if span < tol:
            if verbose:
                print(f"  converged after {it} iterations (span tol {tol})")
            break
    else:
        if verbose:
            print(f"  WARNING: hit {max_iter} iterations, span {span:.3e}")

    h = np.where(any_feas, h, np.inf)
    return h, rho, n_pd


def build_3d(tpm_path, max_iter, tol, verbose=True):
    global DT_DP
    """Average cost with R*(u - u_prev)^2; h is (SOC, demand, u_prev)."""
    TPM, n_pd, soc, pdem, u = _grids(tpm_path)
    feas, nsi, wlo, whi, oob = _transition(soc, pdem, u, n_pd)
    uprev = np.linspace(0.0, P_FC_MAX, U_PREV_STEPS)

    FLOW_P_STACK = np.array([0.0, 5.0, 10.0, 15.0, 20.0, 23.5])
    FLOW_ML_MIN  = np.array([3.0, 50.0, 100.0, 150.0, 230.0, 330.0])
    ETA_BOOST = 0.93
    flow_u = np.interp(u / ETA_BOOST, FLOW_P_STACK, FLOW_ML_MIN) / FLOW_ML_MIN.max()
    fuel = flow_u[None, None, :] + BAND_PENALTY * oob                  # (S,D,U)
    rate = RATE_PENALTY * (u[None, :] - uprev[:, None])**2             # (Up,U)
    BIG = 1.0e9
    any_feas = feas.any(axis=2)
    fmask = any_feas.astype(float)

    if verbose:
        print(f"  grid SOC {SOC_BINS} x demand {n_pd} x u_prev {U_PREV_STEPS} "
              f"x actions {U_STEPS}")
        print(f"  stage cost: hydrogen + {RATE_PENALTY}*(P_fc - P_fc_prev)^2")

    h = np.zeros((SOC_BINS, n_pd, U_PREV_STEPS))
    ref = (SOC_BINS // 2, n_pd // 2, U_PREV_STEPS // 2)
    pdx = np.arange(n_pd)[None, :, None]
    # successor's u_prev is this step's u -> nearest index on the coarse axis
    u_to_uprev = np.abs(u[:, None] - uprev[None, :]).argmin(axis=1)     # (U,)
    rho = 0.0
    for it in range(1, max_iter + 1):
        # expectation over d' for each u_prev slice
        Eh = np.empty_like(h)
        for k in range(U_PREV_STEPS):
            num = (h[:, :, k] * fmask) @ TPM.T
            den = fmask @ TPM.T
            Eh[:, :, k] = np.where(den > 1e-12,
                                   num / np.where(den > 1e-12, den, 1.0), 0.0)
        # fut[s,d,u] = Eh[ nsi[s,d,u], d, u_to_uprev[u] ]
        fut = (wlo * Eh[nsi, pdx, u_to_uprev[None, None, :]]
               + whi * Eh[nsi + 1, pdx, u_to_uprev[None, None, :]])
        base = np.where(feas, fuel + fut, BIG)                   # (S,D,U)
        total = base[:, :, None, :] + rate[None, None, :, :]     # (S,D,Up,U)
        total = np.where(feas[:, :, None, :], total, BIG)
        h_new = np.minimum(total.min(axis=3), BIG)

        rho = h_new[ref]
        h_new -= rho
        resid = h_new - h
        span = float(resid.max() - resid.min())
        h = h_new
        if verbose and (it % 50 == 0 or it == 1):
            print(f"    iter {it:5d}   span {span:.3e}   rho {rho:.6f}")
        if span < tol:
            if verbose:
                print(f"  converged after {it} iterations (span tol {tol})")
            break
    else:
        if verbose:
            print(f"  WARNING: hit {max_iter} iterations, span {span:.3e}")

    h = np.where(any_feas[:, :, None], h, np.inf)
    return h, rho, n_pd, uprev


def main():
    global K_CONV, FC_MAY_CHARGE, RATE_PENALTY, DT_DP
    ap = argparse.ArgumentParser()
    ap.add_argument("tpm")
    ap.add_argument("-o", "--out", default="CostToGo_h_avg.mat")
    ap.add_argument("--max-iter", type=int, default=20000)
    ap.add_argument("--tol", type=float, default=1e-4)
    ap.add_argument("--k-conv", type=float, default=None)
    ap.add_argument("--rate-penalty", type=float, default=0.0)
    ap.add_argument("--dt-dp", type=float, default=None)
    ap.add_argument("--fc-charge", action="store_true")
    a = ap.parse_args()
    if a.k_conv is not None:
        K_CONV = a.k_conv
    FC_MAY_CHARGE = bool(a.fc_charge)
    RATE_PENALTY = a.rate_penalty
    if a.dt_dp is not None: DT_DP = a.dt_dp

    print(f"Average-cost SDP from {a.tpm}  (K_CONV={K_CONV}, R={RATE_PENALTY}, "
          f"fc_may_charge={FC_MAY_CHARGE})")
    out = {
        "soc_min": SOC_MIN, "soc_max": SOC_MAX, "soc_bins": SOC_BINS,
        "pdem_min": PDEM_MIN, "pdem_max": PDEM_MAX,
        "p_fc_max": P_FC_MAX, "p_batt_min": P_BATT_MIN, "p_batt_max": P_BATT_MAX,
        "em": Em, "q_ah": Q_AH, "k_conv": K_CONV, "u_steps": U_STEPS,
        "fc_may_charge": int(FC_MAY_CHARGE),
        "cost_form": "average_cost_no_soc_target",
        "fuel_form": "h20_datasheet_flow",
        "gamma": 1.0, "rate_penalty": RATE_PENALTY, "dt_dp": DT_DP,
    }
    if RATE_PENALTY > 0:
        h, rho, n_pd, uprev = build_3d(a.tpm, a.max_iter, a.tol)
        out["u_prev_grid"] = uprev
        out["u_prev_steps"] = U_PREV_STEPS
    else:
        h, rho, n_pd = build_2d(a.tpm, a.max_iter, a.tol)
    out["cost_J"] = h          # same key the node reads
    out["rho"] = rho
    out["pdem_bins"] = n_pd
    fin = h[np.isfinite(h)]
    print(f"  h: shape {h.shape}, finite range {fin.min():.4g}..{fin.max():.4g}, "
          f"rho {rho:.6f}")
    scipy.io.savemat(a.out, out)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
