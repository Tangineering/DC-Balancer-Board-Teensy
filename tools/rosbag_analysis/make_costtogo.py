"""
make_costtogo.py — value iteration for the scaled FCHEV SDP cost-to-go.

    python3 make_costtogo.py TPM.mat -o CostToGo_J_scaled_2026-10-26A.mat

Port of Compute_CostToGo.m, with three differences:

  1. CONSTANTS ARE THE NODE'S. The MATLAB version carried the full-scale plant
     (106 kW FC, 100 Ah, 720 V, demand +/-50 kW) and a 0.55-0.65 SOC band, while
     sdp_ems_node runs a 24 W FC on a 5.0 Ah / 7.2 V pack over 0.25-0.90. It also
     used eta_fc 0.5 and a 0.6 SOC reference against the node's 0.40 and 0.55 —
     which matters because the node REDOES the Bellman minimisation online using
     J as the terminal cost, so its stage cost must match the one baked in here.

  2. THE GRID IS SAVED INTO THE .mat. The node checks these against its own
     constants and refuses to start on a mismatch. A shape check alone cannot
     catch a re-banded grid: row i silently comes to mean a different SOC.

  3. VECTORISED. The MATLAB quadruple loop is ~31 M inner operations per sweep;
     this precomputes the transition index once and does each sweep as array ops.

Everything else is the same algorithm: Jacobi value iteration, infeasible actions
excluded, states with no feasible action left as +inf.
"""

import argparse, sys
import numpy as np
import scipy.io

# ── Must match sdp_ems_node.py ───────────────────────────────────────────────
SOC_MIN, SOC_MAX, SOC_BINS, SOC_REF = 0.25, 0.90, 250, 0.55
PDEM_MIN, PDEM_MAX = -54.0, 150.0
P_FC_MAX, P_BATT_MAX, P_BATT_MIN = 24.0, 125.0, -54.0
Em, Q_AH = 7.2, 5.0
ETA_FC, Q_LHV_H2 = 0.40, 120000.0
GAMMA, ALPHA, U_STEPS = 0.95, 500.0, 50


def build(tpm_path, max_iter=1000, tol=1e-3, verbose=True):
    TPM = np.asarray(scipy.io.loadmat(tpm_path)["TPM"], dtype=float)
    n_pd = TPM.shape[0]
    if TPM.shape[0] != TPM.shape[1]:
        sys.exit(f"TPM must be square, got {TPM.shape}")

    soc  = np.linspace(SOC_MIN, SOC_MAX, SOC_BINS)
    pdem = np.linspace(PDEM_MIN, PDEM_MAX, n_pd)
    u    = np.linspace(0.0, P_FC_MAX, U_STEPS)

    rs = TPM.sum(axis=1)
    dead = np.where(rs < 1e-9)[0]
    if dead.size and verbose:
        print(f"  note: {dead.size} TPM rows sum to 0 (never-visited demand bins "
              f"{pdem[dead].min():.1f}..{pdem[dead].max():.1f} W); their future cost is 0")

    # P_batt[pd, u] and the resulting SOC step
    P_batt = pdem[:, None] - u[None, :]                      # (n_pd, U)
    dsoc   = (P_batt / Em) / (3600.0 * Q_AH)                 # (n_pd, U)
    soc_next_raw = soc[:, None, None] - dsoc[None, :, :]     # (S, n_pd, U)

    # Feasibility is the PHYSICAL limit only: what the battery can source/sink.
    feas = ((P_batt >= P_BATT_MIN) & (P_batt <= P_BATT_MAX))[None, :, :] \
           & np.ones((SOC_BINS, 1, 1), dtype=bool)

    # Leaving the SOC band is a SOFT constraint, not infeasibility.
    #
    # The MATLAB excluded any action whose successor left the band. On this
    # plant that makes value iteration ill-posed: one step moves SOC by at most
    # |P_batt|/Em/(3600*Q_AH) = 9.6e-4, against a bin width of 2.6e-3, so the
    # chain is nearly absorbing and a single excluded cell propagates through
    # the demand expectation across its entire SOC row — 94% of the table came
    # back poisoned. A large finite penalty keeps the policy away from the band
    # just as firmly while leaving every value finite and the sweep contractive.
    BAND_PENALTY = 1.0e4                 # ~57x the worst stage cost (ALPHA*0.35 = 175)
    out_of_band = (soc_next_raw < SOC_MIN) | (soc_next_raw > SOC_MAX)
    soc_next = np.clip(soc_next_raw, SOC_MIN, SOC_MAX)

    # Nearest grid index for each successor
    nsi = np.abs(soc_next[..., None] - soc).argmin(axis=-1).astype(np.int32)

    # Stage cost: hydrogen + SOC deviation + band penalty
    W_H2  = u / (ETA_FC * Q_LHV_H2)                          # (U,)
    stage = (W_H2[None, None, :]
             + ALPHA * np.abs(soc_next - SOC_REF)
             + BAND_PENALTY * out_of_band)
    BIG = 1.0e9
    stage = np.where(feas, stage, BIG)
    any_feas = feas.any(axis=2)

    if verbose:
        pct = 100.0 * feas.sum() / feas.size
        oob = 100.0 * out_of_band.sum() / out_of_band.size
        print(f"  grid: SOC {SOC_BINS} bins [{SOC_MIN},{SOC_MAX}], demand {n_pd} bins "
              f"[{PDEM_MIN},{PDEM_MAX}] W, {U_STEPS} actions")
        print(f"  max |dSOC| per step {np.abs(dsoc).max():.2e}, bin width "
              f"{soc[1]-soc[0]:.2e}")
        print(f"  power-feasible pairs {pct:.1f}%, band-penalised {oob:.1f}%")

    fmask = any_feas.astype(float)
    J = np.zeros((SOC_BINS, n_pd))
    for it in range(1, max_iter + 1):
        # E[J(s', d')] under the demand transition, over FEASIBLE successors only,
        # renormalised. You cannot transition into a state that has no feasible
        # action, so including it at BIG is wrong — and because one step barely
        # moves SOC, a single such cell otherwise contaminates its whole row.
        # (PDEM_MAX 150 W exceeds P_FC_MAX + P_BATT_MAX = 149 W, so the top
        # demand column is unservable and would do exactly that.)
        num = (J * fmask) @ TPM.T                            # (S, n_pd)
        den = fmask @ TPM.T                                  # (S, n_pd)
        EJ  = np.where(den > 1e-12, num / np.where(den > 1e-12, den, 1.0), 0.0)
        # fut[i, pd, u] = EJ[ nsi[i, pd, u], pd ]
        fut = EJ[nsi, np.arange(n_pd)[None, :, None]]
        total = np.where(feas, stage + GAMMA * fut, BIG)
        J_new = np.minimum(total.min(axis=2), BIG)

        delta = float(np.max(np.abs(J_new - J)))
        J = J_new
        if verbose and (it % 50 == 0 or it == 1):
            print(f"    iter {it:4d}   max|dJ| = {delta:.3e}")
        if delta < tol:
            if verbose: print(f"  converged after {it} iterations (tol {tol})")
            break
    else:
        if verbose: print(f"  WARNING: hit {max_iter} iterations without converging")

    # States with no feasible action are genuinely infeasible -> inf, which is
    # what sdp_ems_node tests for. Everything else keeps its finite value.
    J = np.where(any_feas, J, np.inf)
    n_inf = int(np.isinf(J).sum())
    fin = J[np.isfinite(J)]
    if verbose:
        print(f"  cost_J: shape {J.shape}, finite range "
              f"{fin.min():.4g}..{fin.max():.4g}, "
              f"{n_inf} infeasible cells ({100.0*n_inf/J.size:.2f}%)")
    return J, n_pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tpm", help="TPM.mat")
    ap.add_argument("-o", "--out", default="CostToGo_J_scaled_2026-10-26A.mat")
    ap.add_argument("--max-iter", type=int, default=1000)
    ap.add_argument("--tol", type=float, default=1e-3)
    a = ap.parse_args()

    print(f"Building cost-to-go from {a.tpm}")
    J, n_pd = build(a.tpm, a.max_iter, a.tol)

    scipy.io.savemat(a.out, {
        "cost_J": J,
        # Recorded so sdp_ems_node can verify the grid it was built on.
        "soc_min": SOC_MIN, "soc_max": SOC_MAX, "soc_bins": SOC_BINS,
        "soc_ref": SOC_REF,
        "pdem_min": PDEM_MIN, "pdem_max": PDEM_MAX, "pdem_bins": n_pd,
        "p_fc_max": P_FC_MAX, "p_batt_min": P_BATT_MIN, "p_batt_max": P_BATT_MAX,
        "em": Em, "q_ah": Q_AH, "eta_fc": ETA_FC, "q_lhv_h2": Q_LHV_H2,
        "gamma": GAMMA, "alpha": ALPHA, "u_steps": U_STEPS,
    })
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
