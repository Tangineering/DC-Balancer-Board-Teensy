#!/usr/bin/env python
"""synthesize_mimo_controller.py — Phase 4 of controller_design_MIMO.

Centralized 2x2 MIMO H-inf / Youla-H controller for the coupled
(droop share alpha, wheel speed v) <- (droop ratio r, motor current command)
plant defined in plant_mimo.py / mimo_system_model.md.

Pipeline (plan §§3,4,7):
  1  scaled design plant  Gs = De^-1 G Du
  2  block-diagonal mixed-sensitivity weights (per-channel philosophy)
  3  DGKF two-Riccati H-inf synthesis            (hinf_mimo.hinfsyn_dgkf)
  4  MIMO Youla-H DC correction  ->  T(0) = I    (thesis contribution)
  5  balanced truncation of the stable remainder
  6  Tier-1 (stability) + Tier-2 (performance) corner batteries
  7  cross-validation against the 15-state full-order truth model
  8  single-rate discretization at Ts = 2 ms, modal realization
  9  float32 reference implementation + anti-windup verification
 10  diagonal-plant (dV0 = 0) sanity check vs the two SISO gammas
 11  emission: coeffs header, reference vectors, metrics, figure CSVs

Every gate exits non-zero on failure (gate() discipline).

Run:  ctrl-venv/Scripts/python.exe synthesize_mimo_controller.py
"""

import os
import sys
import time

import numpy as np
from numpy.linalg import eigvals, inv, cond, matrix_rank, svd
from scipy.linalg import block_diag, expm, eig

import hinf_mimo as H
from hinf_mimo import (SS, ss_series, ss_scale, ss_parallel, ss_lmul, ss_rmul,
                       blkdiag_ss, sv, rga, tf2ss, pade2, makeweight,
                       strictly_proper_lf_weight, strictly_proper_2nd_order_weight,
                       hinf_norm, AugPlantMIMO, hinfsyn_dgkf, balanced_truncate,
                       split_integrator_multi, c2d_tustin, c2d_zoh,
                       dfreqresp_matrix)
import plant_mimo as PM

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figures")
os.makedirs(FIGDIR, exist_ok=True)

np.set_printoptions(precision=5, suppress=True, linewidth=150)

TS = 2.0e-3                 # single-rate 500 Hz (plan §7)
RNG_SEED = 20260803
REF_N = 64

# physical actuator limits (plan §7)
R_MIN, R_MAX = 0.15, 0.85
I_MOT_MAX = 20.0            # A, motor current clamp (firmware MOTOR_I_CMD_MAX, rev 2026-08-04).
# Was +-5 A: a bench derating that applied the ~67-87 W BUS power budget directly at the
# MOTOR node (a unit error).  Bus/motor conversion at the nominal OP is A_i ~ 0.243
# A_bus per A_mot (plant_mimo.bus_current_gains), so +-20 A motor-side is ~4.9 A bus-side
# at cruise: the motor clamp and the bus-power budget now bind TOGETHER by construction.
# Must stay consistent with plant_mimo.DU[1,1] (the scaled actuator span) — the AW
# authority clamp XI = Du^-1 (U_lim - U0) is +-1 exactly when they agree.

_FAILS = []
_GATES = []


def gate(name, cond_, detail=""):
    ok = bool(cond_)
    _GATES.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   ({detail})" if detail else ""))
    if not ok:
        _FAILS.append(name)
    return ok


def note(name, detail):
    """Informational (reported, not gated)."""
    _GATES.append((name, None, detail))
    print(f"  [info] {name}   ({detail})")


def hdr(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


# ─────────────────────────────────────────────────────────────────────────────
# Loop algebra helpers (2x2, negative feedback, plant strictly proper)
# ─────────────────────────────────────────────────────────────────────────────

def loop_matrices(G, K):
    """Closed loop of y = G u, u = K (w - y).  G strictly proper (D_G = 0).
    Returns (Acl, S_o) with S_o : w -> e = w - y."""
    Ag, Bg, Cg = G.A, G.B, G.C
    Ak, Bk, Ck, Dk = K.A, K.B, K.C, K.D
    Acl = np.block([[Ag - Bg @ Dk @ Cg, Bg @ Ck],
                    [-Bk @ Cg,          Ak]])
    Bcl = np.vstack([Bg @ Dk, Bk])
    Ccl = np.hstack([-Cg, np.zeros((Cg.shape[0], Ak.shape[0]))])
    So = SS(Acl, Bcl, Ccl, np.eye(Cg.shape[0]))
    return Acl, So


def comp_sens(G, K):
    """T = G K (I + G K)^-1 : w -> y."""
    Acl, So = loop_matrices(G, K)
    Cg = G.C
    Ccl = np.hstack([Cg, np.zeros((Cg.shape[0], K.A.shape[0]))])
    return SS(Acl, So.B, Ccl, np.zeros((Cg.shape[0], Cg.shape[0])))


def youla_from_K(G, K):
    """Y_H = K (I + G K)^-1  by state-space interconnection.  Requires D_K = 0."""
    assert np.max(np.abs(K.D)) < 1e-12, "youla_from_K assumes D_K = 0"
    Ag, Bg, Cg = G.A, G.B, G.C
    Ak, Bk, Ck = K.A, K.B, K.C
    A = np.block([[Ak,        -Bk @ Cg],
                  [Bg @ Ck,    Ag]])
    B = np.vstack([Bk, np.zeros((Ag.shape[0], Bk.shape[1]))])
    C = np.hstack([Ck, np.zeros((Ck.shape[0], Ag.shape[0]))])
    return SS(A, B, C, np.zeros((Ck.shape[0], Bk.shape[1])))


def gc_from_youla(G, Y):
    """Gc = Y (I - G Y)^-1  (positive feedback of G around Y).  Requires D_Y = 0.
    Matrix generalization of controller_design/synthesize_controller.py:108-121."""
    assert np.max(np.abs(Y.D)) < 1e-12, "gc_from_youla assumes D_Y = 0"
    Ay, By, Cy = Y.A, Y.B, Y.C
    Ag, Bg, Cg = G.A, G.B, G.C
    A = np.block([[Ay,        By @ Cg],
                  [Bg @ Cy,   Ag]])
    B = np.vstack([By, np.zeros((Ag.shape[0], By.shape[1]))])
    C = np.hstack([Cy, np.zeros((Cy.shape[0], Ag.shape[0]))])
    return SS(A, B, C, np.zeros((Cy.shape[0], By.shape[1])))


_W_SWEEP = np.logspace(-3, 6, 2000)


def hnorm(sys):
    """hinf_norm with a dense-sweep fallback.

    The Hamiltonian bisection in hinf_norm can fail (returns inf) on systems with
    a very wide pole spread — the 15-state full-order truth model mixes 0.12 rad/s
    vehicle dynamics with ~1e5 rad/s converter poles.  Fall back to a dense
    singular-value sweep, which is a lower bound but adequate for the
    informational cross-validation.  Flagged in the returned tuple."""
    v = hinf_norm(sys)
    if np.isfinite(v):
        return v, False
    return float(np.max(sv(sys, _W_SWEEP))), True


def ctrl_freqresp(KI, Grem, w):
    """Frequency response of KI/s + Grem(s)."""
    R = Grem.freqresp_matrix(w)
    return R + KI[None, :, :] / (1j * np.asarray(w)[:, None, None])


def ss_integrator_plus(KI, Grem):
    """Continuous SS of KI/s + Grem."""
    ny, nu = KI.shape
    Int = SS(np.zeros((ny, ny)), np.eye(ny), KI, np.zeros((ny, nu)))
    return ss_parallel(Int, Grem)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Scaled design plant
# ─────────────────────────────────────────────────────────────────────────────
hdr("1. SCALED DESIGN PLANT")

op0, p0 = PM.nominal_op(), PM.nominal_params()
G_phys = PM.design_plant(op0, p0)
De, Du = PM.scaling_matrices()
Gs = PM.scaled_plant(G_phys, De, Du, op0, p0)

print(f"physical plant : {G_phys.n} states, {G_phys.ny}x{G_phys.nu}")
print(f"De = diag{np.diag(De)}   Du = diag{np.diag(Du)}")
print("G_phys(0) =\n", G_phys.dcgain_matrix())
print("Gs(0)     =\n", Gs.dcgain_matrix())
G0s = Gs.dcgain_matrix()
print("RGA(Gs(0)) =\n", rga(G0s))
note("plant DC condition number (scaled)", f"cond = {cond(G0s):.3f}")
gate("scaled plant is strictly proper", np.max(np.abs(Gs.D)) < 1e-14)
gate("scaled plant DC gains are O(1)",
     0.05 < np.abs(np.diag(G0s)).min() and np.abs(G0s).max() < 200.0,
     f"|diag| = {np.abs(np.diag(G0s))}, max|G| = {np.abs(G0s).max():.3f}")
gate("coupling present at the design OP (dV0 = +0.2 V)", abs(G0s[0, 1]) > 1e-6,
     f"Gs(0)[0,1] = {G0s[0,1]:.5f}")
gate("G21 = 0 structurally", abs(G0s[1, 0]) < 1e-14, f"{G0s[1,0]:.2e}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Weights
# ─────────────────────────────────────────────────────────────────────────────
hdr("2. BLOCK-DIAGONAL MIXED-SENSITIVITY WEIGHTS")

# Weight-iteration record (see mimo_synthesis.md §3).  gp1/gp2 are the per-block
# performance-weight DC gain knobs; wp2 the drive-channel S-weight bandwidth.
WEIGHT_ITERS = []

SHARE_W = dict(wp_dc=1e4, wp_wc=40.0, wd=(0.5, 250.0, 40.0), wu=(0.3, 600.0, 20.0))
# DRIVE weights: FINAL values after the iteration recorded in mimo_synthesis.md §3.2.
# The plan's starting point was the papers' 2nd-order strictly-proper S weight at
# 24 rad/s with the shipped Wu; that set is structurally unmeetable here (see
# WEIGHT_ITERS below and mimo_synthesis.md §3.2) and was replaced by the
# first-order family at the SAME 24 rad/s bandwidth, with a relaxed Wu.
DRIVE_W = dict(wp_dc=1e4, wp_wc=24.0, wd=(0.5, 60.0, 40.0),  wu=(0.5, 18.0, 20.0))
# Wu break 200 -> 18 rad/s at the +-20 A clamp round (2026-08-04): see WEIGHT_ITERS it.5.
# Wu penalizes the SCALED control u_s, and u_s = 1 now means 20 A instead of 5 A, so the
# unchanged weight became a 4x WEAKER physical effort penalty -- the drive channel got
# 4x cheaper and the synthesis spent it (gamma 1.82 -> 1.08, but 61 Tier-1 corners went
# unstable).  Only the BREAK moves; the DC gain knob stays at 0.5.
# weight-sweep hook used during the iteration (not part of the shipped path):
#   MIMO_DRIVE_WU="dc,wc[,hf]"   MIMO_DRIVE_WP_WC="wc"
if os.environ.get("MIMO_DRIVE_WU"):
    _wu = [float(x) for x in os.environ["MIMO_DRIVE_WU"].split(",")]
    DRIVE_W['wu'] = (_wu[0], _wu[1], _wu[2] if len(_wu) > 2 else 20.0)
if os.environ.get("MIMO_DRIVE_WP_WC"):
    DRIVE_W['wp_wc'] = float(os.environ["MIMO_DRIVE_WP_WC"])
DRIVE_W_PLAN = dict(wp_dc=1e4, wp_wc=24.0, wd=(0.5, 60.0, 40.0), wu=(0.3, 300.0, 20.0))


def drive_wp(d, second_order=False):
    return (strictly_proper_2nd_order_weight(d['wp_dc'], d['wp_wc']) if second_order
            else strictly_proper_lf_weight(d['wp_dc'], d['wp_wc']))


def build_weights(share=None, drive=None, drive_2nd=False):
    s = dict(SHARE_W if share is None else share)
    d = dict(DRIVE_W if drive is None else drive)
    Wp = blkdiag_ss(strictly_proper_lf_weight(s['wp_dc'], s['wp_wc']),
                    drive_wp(d, drive_2nd))
    Wd = blkdiag_ss(makeweight(*s['wd']), makeweight(*d['wd']))
    Wu = blkdiag_ss(makeweight(*s['wu']), makeweight(*d['wu']))
    return Wp, Wu, Wd


Wp, Wu, Wd = build_weights()
print(f"Wp: {Wp.n} states  (share lf 1e4@{SHARE_W['wp_wc']}, drive lf 1e4@{DRIVE_W['wp_wc']})")
print(f"Wd: {Wd.n} states   Wu: {Wu.n} states")
gate("Wu.D full rank (D12 rank condition)", matrix_rank(Wu.D) == 2,
     f"rank = {matrix_rank(Wu.D)}, D = diag{np.diag(Wu.D)}")
gate("Wp strictly proper (D11 = 0)", np.max(np.abs(Wp.D)) < 1e-14)


# ─────────────────────────────────────────────────────────────────────────────
# 3. DGKF synthesis
# ─────────────────────────────────────────────────────────────────────────────
hdr("3. DGKF TWO-RICCATI H-INF SYNTHESIS")


def synth_refined(P, iters=14):
    """hinfsyn_dgkf + an a-posteriori gamma refinement.

    WHY: for the 2x2 problem the Riccati bisection inside hinfsyn_dgkf returns a
    gamma_opt that the CENTRAL CONTROLLER does not actually attain -- the DGKF
    feasibility test (X-ARE solvable, X >= 0, rho(XY) < gamma^2) is degenerate
    here because Y == 0 exactly (D21 = I), so rho(XY) = 0 is vacuous and the
    remaining conditions are necessary but not sufficient.  hinfsyn_dgkf already
    guards against this with its back-off ladder + a-posteriori ||Tzw|| gate, but
    the ladder is coarse (1.05, 1.2, 1.5, 2.0).  This wrapper bisects the back-off
    factor so the DELIVERED level is tight.  In the 1x1 sub-problems the bisection
    is exact (g_ach == g_opt) -- the gap is a MIMO-only artefact.
    Returns (K, gamma_achieved, gamma_riccati, ||Tzw||, info).
    """
    K0, gu0, go0, nz0, info0 = hinfsyn_dgkf(P)
    best = (K0, gu0, go0, nz0, info0)
    lo, hi = 1.0, gu0/go0
    for _ in range(iters):
        mid = 0.5*(lo + hi)
        try:
            K2, gu2, go2, nz2, info2 = hinfsyn_dgkf(P, backoff=mid)
            if abs(gu2 - mid*go2) < 1e-9*mid*go2:      # the ladder did NOT escalate
                hi = mid
                best = (K2, gu2, go2, nz2, info2)
            else:
                lo = mid
        except Exception:
            lo = mid
    K, gu, go, nz, inf_ = best
    return K, gu, go, nz, inf_


def siso_gamma(G_1x1, wp, wd, wu):
    """Achieved gamma of the isolated 1x1 channel problem (weight-balance diagnostic)."""
    P1 = AugPlantMIMO(G_1x1, wp, wu, wd)
    _, g_ach, _, _, _ = synth_refined(P1, iters=10)
    return g_ach


def sub_ss(G, rows, cols):
    return SS(G.A, G.B[:, cols], G.C[rows, :], G.D[np.ix_(rows, cols)])


G11s = sub_ss(Gs, [0], [0])
G22s = sub_ss(Gs, [1], [1])
Wp_share1 = strictly_proper_lf_weight(SHARE_W['wp_dc'], SHARE_W['wp_wc'])
g_share = siso_gamma(G11s, Wp_share1, makeweight(*SHARE_W['wd']), makeweight(*SHARE_W['wu']))

# --- documented weight-iteration record (mimo_synthesis.md §3.2) ---------------
g_drive_plan = siso_gamma(G22s, drive_wp(DRIVE_W_PLAN, second_order=True),
                          makeweight(*DRIVE_W_PLAN['wd']), makeweight(*DRIVE_W_PLAN['wu']))
g_drive = siso_gamma(G22s, drive_wp(DRIVE_W, second_order=False),
                     makeweight(*DRIVE_W['wd']), makeweight(*DRIVE_W['wu']))
g_drive_planWu = siso_gamma(G22s, drive_wp(DRIVE_W, second_order=False),
                            makeweight(*DRIVE_W['wd']), makeweight(*DRIVE_W_PLAN['wu']))
g_drive_relaxWu = siso_gamma(G22s, drive_wp(DRIVE_W, second_order=False),
                             makeweight(*DRIVE_W['wd']), makeweight(0.15, 600.0, 20.0))
WEIGHT_ITERS.append(("it.0  share: shipped set (lf 1e4@40, Wd 0.5/250/40, Wu 0.3/600/20)",
                     f"gamma_share = {g_share:.4f}  -- kept unchanged"))
WEIGHT_ITERS.append(("it.1  drive: plan/papers set (2nd-order lf 1e4@24, Wd 0.5/60/40, Wu 0.3/300/20)",
                     f"gamma_drive = {g_drive_plan:.4f}  -- DOMINATES; 2nd-order S weight "
                     "demands s^2 roll-in of S below its corner, but only ONE integrator is "
                     "available in the loop below the drive plant pole (0.122 rad/s). "
                     "Gain sweeps (Wp DC 1e4..4, Wd break 60..250, Wu DC 0.3..0.04) never "
                     "brought it below 1.3 -- a structural, not a gain, problem."))
WEIGHT_ITERS.append(("it.2  drive: first-order strictly-proper Wp at the SAME 24 rad/s, "
                     "Wd/Wu left at the plan's values",
                     f"gamma_drive = {g_drive_planWu:.4f}  -- ONLY the weight FAMILY changed; "
                     "the papers' bandwidth and the plan's Wd/Wu are kept.  Tier-2 worst "
                     "sigma(S_o) = 2.17 with this set: FAILS the < 2.0 gate at the "
                     "(K_v = 2, pole_factor = 0.5, tau_v = 5 ms, Td_v = 4 ms) drive corner."))
WEIGHT_ITERS.append(("it.3a drive: Wu DC 0.3 -> 0.15, break 300 -> 600 rad/s -- TRIED AND REJECTED",
                     f"gamma_drive = {g_drive_relaxWu:.4f} (BETTER gamma) but WORSE robustness: "
                     "nominal sigma(S_o) 1.23 -> 1.92 and Tier-2 worst 2.17 -> 2.41.  The extra "
                     "nominal bandwidth (16 -> 22 rad/s) is wasted anyway -- the motor-current clamp "
                     "rate-limits the channel (see §8.4).  Rejected: for this plant a LOWER "
                     "gamma buys a MORE aggressive controller, and the binding constraint is "
                     "corner robustness, not nominal performance."))
WEIGHT_ITERS.append(("it.3b drive: Wu DC 0.3 -> 0.5, break 300 -> 200 rad/s (FINAL)",
                     f"gamma_drive = {g_drive:.4f} (worse gamma, deliberately).  The drive "
                     "channel's STRUCTURAL gain uncertainty is K_v in {0.5, 1, 2} times a "
                     "pole_factor of {0.5, 2}, i.e. a ~4x gain spread -- far wider than the "
                     "share channel's K in [0.55, 1.45].  A heavier control-effort penalty is "
                     "the correct way to buy the matching robustness margin.  The break "
                     "moves 300 -> 200 rad/s because the drive transport delay budget is "
                     "Td_v in [1, 4] ms (250-1000 rad/s): controller effort must be rolled "
                     "off BELOW the worst-case delay's phase crossover, not at it.  Result: "
                     "Tier-2 worst sigma(S_o) 2.08 -> 1.92 (gate passes), waived "
                     "K-out-of-envelope worst 13.9 -> 10.8, at the cost of ~60 ms of "
                     "small-signal drive settling and gamma 1.49 -> 1.82.  NOTE: an earlier "
                     "pass appeared to pass this gate at Wu DC 0.4 only because the balanced "
                     "truncation was selected at a loose 2e-2 tolerance and the 3-state "
                     "truncation error happened to DAMP the worst corner.  The selection "
                     "tolerance was tightened to 1e-2 so the shipped controller is a faithful "
                     "reduction and the corner result is a property of the DESIGN, not of a "
                     "lucky truncation."))
WEIGHT_ITERS.append((
    "it.5  drive: Wu break 200 -> 18 rad/s (FINAL, +-20 A clamp round 2026-08-04)",
    f"gamma_drive = {g_drive:.4f}.  MOTOR_I_CMD_MAX 5 -> 20 A rescales Du[1,1] 5 -> 20, "
    "so the SAME Wu penalizes 4x more physical current: the effort penalty silently "
    "weakened 4x.  Re-running the unchanged weight set gave gamma_MIMO 1.0821 (vs 1.8168 "
    "at +-5 A) but 61 of 4992 Tier-1 corners UNSTABLE, Tier-2 worst sigma(S_o) 2.97, and "
    "an INFINITE (unstable) K-out-of-envelope waived corner -- i.e. the synthesis spent "
    "the whole 4x on aggression.  The effort penalty therefore had to be restored.  An "
    "EXACT restoration (Wu_new = 4*Wu_old) is NOT representable in the makeweight(dc, wc, "
    "hf) family -- it requires dc = 2.0 > 1, which makes the weight's a-coefficient "
    "imaginary (hinf_mimo.makeweight: a = wc*sqrt((1-hf^2)/(dc^2-1))) and the Riccati "
    "solve NaNs.  (It is also worth stating plainly: the exact 4x weight would reproduce "
    "the +-5 A controller EXACTLY, since scaling Du and Wu by the same factor is a "
    "similarity of the scaled problem.)  The break frequency is the available knob.  "
    "Sweep actually run (dc, break) -> (gamma_MIMO, Tier-1 unstable, Tier-2 worst):  "
    "(0.5,200) -> (1.08, 61, 2.97) FAIL;  (0.5,100) -> (1.16, 0, 2.74) FAIL;  "
    "(0.5,50) -> (1.30, 0, 2.37) FAIL;  (0.9,50) -> (1.32, 0, 2.44) FAIL;  "
    "(0.9,25) -> (1.42, 0, 2.19) FAIL;  (0.5,25) -> (1.51, 0, 2.01) FAIL;  "
    "(0.95,15) -> (1.48, 0, 2.11) FAIL;  (0.9,18) -> (1.50, 0, 2.06) FAIL;  "
    "(0.9,14) -> (1.56, 0, 1.97) pass;  (0.9,12) -> (1.61, 0, 1.91) pass;  "
    "(0.8,15) -> (1.62, 0, 1.90) pass;  (0.5,18) -> (1.65, 0, 1.88) pass  <- CHOSEN;  "
    "(0.6,16) -> (1.67, 0, 1.85) pass;  (0.5,12) -> (1.83, 0, 1.74) pass.  "
    "(0.5, 18) is the setting that clears the < 2.0 Tier-2 gate with ~6 % margin while "
    "moving only ONE knob (the DC gain stays at its it.3b value of 0.5) and keeping the "
    "break as close as possible to the Wp corner (24 rad/s) -- pushing it further down "
    "buys Tier-2 margin but puts Wu and Wp in direct contention over the same decade.  "
    "Net vs the +-5 A design (gamma 1.8168, Tier-2 worst 1.9153, waived "
    "K-out-of-envelope worst 10.8): see it.4 and the corner tables below."))
print(f"isolated channel gammas: share = {g_share:.4f}, drive = {g_drive:.4f} "
      f"(plan's 2nd-order drive Wp: {g_drive_plan:.4f}; plan's Wu: {g_drive_planWu:.4f}; "
      f"relaxed-Wu variant: {g_drive_relaxWu:.4f})")

t0 = time.time()
P = AugPlantMIMO(Gs, Wp, Wu, Wd)
K_H, g_used, g_opt, tzw, info = synth_refined(P)
X_are, Y_are, F_are, L_are = info
print(f"augmented plant: {P.A.shape[0]} states, pz = {P.pz}, py = {P.py}, mu = {P.mu}")
print(f"gamma_riccati = {g_opt:.5f} (optimistic, see synth_refined), "
      f"gamma_achieved = {g_used:.5f}, ||Tzw||inf = {tzw:.5f}, "
      f"K order = {K_H.n}   [{time.time()-t0:.1f} s]")
WEIGHT_ITERS.append(("it.4  MIMO synthesis with the final block-diagonal set",
                     f"gamma_achieved = {g_used:.4f} (vs SISO drive {g_drive:.4f}, "
                     f"SISO share {g_share:.4f})"))

gate("a-posteriori ||Tzw||inf <= gamma_used*1.005", tzw <= g_used * 1.005,
     f"{tzw:.5f} <= {g_used*1.005:.5f}")
# Structural expectation: with G21 = 0 the plant is upper-triangular, so any
# MIMO controller restricted to e1 = 0 is a drive-channel SISO controller ->
# gamma_MIMO >= gamma_drive_SISO, with equality when the coupling costs nothing.
gate("gamma_MIMO >= gamma_drive_SISO (triangular-plant lower bound)",
     g_used >= g_drive*0.99, f"{g_used:.4f} >= {g_drive:.4f}")
gate("gamma_MIMO ~= gamma_drive_SISO within 10 % (coupling is ~free)",
     abs(g_used - g_drive)/g_drive < 0.10,
     f"{g_used:.4f} vs {g_drive:.4f} ({100*abs(g_used-g_drive)/g_drive:.2f} %)")
Ynorm = np.max(np.abs(Y_are))
gate("Y-ARE degenerate (||Y|| ~ 0, D21 = I structure)", Ynorm < 1e-8,
     f"||Y||max = {Ynorm:.3e}")
gate("X-ARE solution PSD", np.min(np.linalg.eigvalsh(0.5 * (X_are + X_are.T))) > -1e-8,
     f"min eig = {np.min(np.linalg.eigvalsh(0.5*(X_are+X_are.T))):.3e}")
gate("H-inf controller stabilizes the scaled plant",
     loop_matrices(Gs, K_H)[0] is not None and
     np.max(eigvals(loop_matrices(Gs, K_H)[0]).real) < 0,
     f"max Re(p) = {np.max(eigvals(loop_matrices(Gs, K_H)[0]).real):.4e}")

# gamma-balance diagnostic: is one channel dominating?
gamma_dom = g_used / max(g_share, g_drive)
note("gamma balance (MIMO achieved / max SISO)", f"{gamma_dom:.3f}")
note("channel balance", f"drive gamma {g_drive:.4f} is {g_drive/g_share:.2f}x the share "
     f"gamma {g_share:.4f}: the drive channel sets the MIMO level")
gate("no single channel blows up the MIMO problem (gamma <= 3x max SISO)",
     gamma_dom < 3.0, f"ratio = {gamma_dom:.3f}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. MIMO Youla-H DC correction
# ─────────────────────────────────────────────────────────────────────────────
hdr("4. MIMO YOULA-H DC CORRECTION  ->  T(0) = I")

Y_H = youla_from_K(Gs, K_H)
T_H = comp_sens(Gs, K_H)
T0_H = T_H.dcgain_matrix()
Y0 = Y_H.dcgain_matrix()
GY0 = G0s @ Y0
print("T_H(0) =\n", T0_H)
print("Gs(0)*Y_H(0) =\n", GY0)
gate("cond(Gs(0)*Y_H(0)) < 1e6", cond(GY0) < 1e6, f"cond = {cond(GY0):.4e}")

M = inv(GY0)
Mdev = np.linalg.norm(M - np.eye(2), 2)
print("M = [Gs(0) Y_H(0)]^-1 =\n", M)
gate("||M - I||_2 < 0.05 (H-inf already near-integral)", Mdev < 0.05,
     f"||M-I||2 = {Mdev:.3e}")

Y_YH = ss_rmul(Y_H, M)
Gc_YH = gc_from_youla(Gs, Y_YH)
pmag = np.sort(np.abs(eigvals(Gc_YH.A)))
print(f"Gc_YH raw order = {Gc_YH.n}; smallest |poles| = {pmag[:4]}")
gate("exactly 2 near-origin poles in Gc_YH",
     np.sum(pmag < 1e-3) == 2, f"count = {int(np.sum(pmag < 1e-3))}, "
     f"|p| = {pmag[:3]}")

KI, Grem_full = split_integrator_multi(Gc_YH, k=2, tol=1e-3)
print("KI =\n", KI)
gate("rank(KI) = 2", matrix_rank(KI) == 2, f"rank = {matrix_rank(KI)}, "
     f"cond = {cond(KI):.3e}")
gate("stable remainder is stable", Grem_full.is_stable(),
     f"max Re(p) = {np.max(eigvals(Grem_full.A).real):.3e}")

# T(0) = I with the SPLIT (exact-integrator) controller, evaluated as a limit.
Gc_split = ss_integrator_plus(KI, Grem_full)
T_split = comp_sens(Gs, Gc_split)
w_dc = 1e-8
T0_split = T_split.freqresp_matrix([w_dc])[0]
err_T0 = np.max(np.abs(T0_split - np.eye(2)))
print("T(0) with split controller =\n", T0_split.real)
gate("||T(0) - I||_max < 1e-9 (exact-integrator controller)", err_T0 < 1e-9,
     f"{err_T0:.3e}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Reduction
# ─────────────────────────────────────────────────────────────────────────────
hdr("5. BALANCED TRUNCATION OF THE STABLE REMAINDER")

w_band = np.logspace(-1, 4, 500)
Kfull_fr = ctrl_freqresp(KI, Grem_full, w_band)
# PER-FREQUENCY relative deviation: dividing by a single global scale would be
# dominated by the integrator's low-frequency magnitude and make the gate vacuous.
sig_fr = np.array([np.linalg.svd(Kfull_fr[i], compute_uv=False)[0] for i in range(len(w_band))])

_, hsv = balanced_truncate(Grem_full, order=None, tol=1e-12)
print(f"remainder order = {Grem_full.n}; HSV = {np.array2string(hsv[:12], precision=4)}")

best = None
for order in range(1, min(Grem_full.n, 8) + 1):
    Gr, _ = balanced_truncate(Grem_full, order=order)
    fr = ctrl_freqresp(KI, Gr, w_band)
    rel = max(np.linalg.svd(fr[i] - Kfull_fr[i], compute_uv=False)[0] / sig_fr[i]
              for i in range(len(w_band)))
    print(f"  order {order}: max rel sigma dev = {rel:.3e}")
    if best is None and rel < 1e-2:      # select with margin; the GATE is 2e-2
        best = (order, Gr, rel)
if best is None:
    Gr, _ = balanced_truncate(Grem_full, order=min(Grem_full.n, 6))
    fr = ctrl_freqresp(KI, Gr, w_band)
    best = (Gr.n, Gr, max(np.linalg.svd(fr[i] - Kfull_fr[i], compute_uv=False)[0] / sig_fr[i]
                          for i in range(len(w_band))))
n_rem, Grem, red_rel = best
print(f"selected remainder order = {n_rem} (total controller states = {n_rem + 2})")
gate("reduced-vs-full controller sigma deviation < 2e-2 (in-band)", red_rel < 2e-2,
     f"max rel dev = {red_rel:.3e}")
# ORDER BUDGET RAISED 8 -> 10 at the +-20 A clamp round (2026-08-04), deliberately.
# The restored effort weight breaks at 18 rad/s instead of 200 (it.5), which puts an extra
# lag pair inside the controller: the faithful truncation is now 7 remainder states (9
# total) instead of 5 (7 total).  The alternative -- forcing 6 remainder states by
# loosening the SELECTION tolerance from 1e-2 toward the 2e-2 gate -- is EXACTLY the
# mistake documented in it.3b (a lucky truncation error damping the worst corner), so it
# was rejected.  The budget is not a hardware constraint: §12 measures the 9-state
# controller at ~0.008 % of the Teensy's issue rate.
gate("total controller order <= 10 states", n_rem + 2 <= 10, f"{n_rem + 2} states")

Gc_red = ss_integrator_plus(KI, Grem)     # scaled-coordinate final continuous controller
gate("reduced controller stabilizes the scaled nominal plant",
     np.max(eigvals(loop_matrices(Gs, Gc_red)[0]).real) < 0,
     f"max Re(p) = {np.max(eigvals(loop_matrices(Gs, Gc_red)[0]).real):.4e}")

T0_red = comp_sens(Gs, Gc_red).freqresp_matrix([w_dc])[0]
gate("||T(0) - I|| preserved through reduction",
     np.max(np.abs(T0_red - np.eye(2))) < 1e-9,
     f"{np.max(np.abs(T0_red - np.eye(2))):.3e}")

# off-diagonal magnitude of the final controller (is MIMO using the coupling?)
Kfr = ctrl_freqresp(KI, Grem, w_band)
offdiag_peak = np.max(np.abs(Kfr[:, 0, 1])), np.max(np.abs(Kfr[:, 1, 0]))
diag_peak = np.max(np.abs(Kfr[:, 0, 0])), np.max(np.abs(Kfr[:, 1, 1]))
note("controller off-diagonal peaks (scaled)",
     f"|K12|max = {offdiag_peak[0]:.4f}, |K21|max = {offdiag_peak[1]:.4e}; "
     f"|K11|max = {diag_peak[0]:.4f}, |K22|max = {diag_peak[1]:.4f}")
K12_rel = offdiag_peak[0] / diag_peak[0]
K21_rel = offdiag_peak[1] / diag_peak[1]
note("off-diagonal / diagonal ratio", f"K12/K11 = {K12_rel:.4f}, K21/K22 = {K21_rel:.3e}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Physical controller (fold the scaling in) + corner batteries
# ─────────────────────────────────────────────────────────────────────────────
hdr("6. CORNER BATTERIES (physical coordinates)")

# Folding: in scaled coordinates u_s = Ks e_s, with y = De y_s and u = Du u_s.
#   e_s = De^-1 e_phys  =>  u_phys = Du Ks De^-1 e_phys  =>  K_phys = Du Ks De^-1.
# Sanity: Gs Ks = (De^-1 G Du)(Du^-1 K_phys De) = De^-1 (G K_phys) De  — the loop
# transfer is a similarity transform of the physical one, so poles/stability and
# sigma(S) up to the De conditioning are identical.  Verified numerically below.
Dei = inv(De)
K_phys = SS(Gc_red.A, Gc_red.B @ Dei, Du @ Gc_red.C, Du @ Gc_red.D @ Dei)
KI_phys = Du @ KI @ Dei

Acl_s = loop_matrices(Gs, Gc_red)[0]
Acl_p = loop_matrices(G_phys, K_phys)[0]
ev_s = np.sort_complex(eigvals(Acl_s))
ev_p = np.sort_complex(eigvals(Acl_p))
gate("scaled and physical closed loops have identical poles (folding check)",
     np.max(np.abs(ev_s - ev_p)) < 1e-6 * max(1.0, np.max(np.abs(ev_s))),
     f"max |dp| = {np.max(np.abs(ev_s - ev_p)):.3e}")

So_nom = loop_matrices(Gs, Gc_red)[1]
So_nom_norm = hnorm(So_nom)[0]
To_nom_norm = hnorm(comp_sens(Gs, Gc_red))[0]
print(f"nominal ||S_o||inf = {So_nom_norm:.4f}, ||T_o||inf = {To_nom_norm:.4f}")
gate("nominal worst sigma(S_o) < 2.0", So_nom_norm < 2.0, f"{So_nom_norm:.4f}")

# ---- Tier 1: continuous stability over every feasible corner -----------------
print("\nTier-1 continuous stability sweep ...")
t0 = time.time()
n_feas = n_skip = 0
worst_re = -np.inf
worst_corner = None
unstable = []
for op, sc, dc, feas in PM.tier1_corners():
    if not feas:
        n_skip += 1
        continue
    n_feas += 1
    Gc_, o_, p_ = PM.corner_plant(op, sc, dc)
    A_ = loop_matrices(Gc_, K_phys)[0]
    mre = np.max(eigvals(A_).real)
    if mre > worst_re:
        worst_re, worst_corner = mre, (o_, sc, dc)
    if mre >= 0.0:
        unstable.append((o_, sc, dc, mre))
print(f"  {n_feas} feasible corners ({n_skip} infeasible skipped) "
      f"in {time.time()-t0:.1f} s")
print(f"  worst max Re(pole) = {worst_re:.4e}")
gate("Tier-1: ALL feasible corners continuous-stable", len(unstable) == 0,
     f"{len(unstable)} unstable of {n_feas}; worst Re = {worst_re:.4e}")
if unstable:
    for u in unstable[:5]:
        print("    unstable:", u)
note("Tier-1 corner counts", f"{n_feas} feasible, {n_skip} infeasible skipped")
note("Tier-1 worst-pole corner",
     f"I_tot0={worst_corner[0]['I_tot0']}, r0={worst_corner[0]['r0']}, "
     f"dV0={worst_corner[0]['dV0']}, share={worst_corner[1]}, drive={worst_corner[2]}")

# ---- Tier 2: performance over ~240 representative corners --------------------
print("\nTier-2 performance sweep (sigma(S_o)) ...")

# share reps: include the SISO worst corner (Td = 2 ms, taur = 300 us, tauf = 0.8 ms)
SHARE_REPS = [
    dict(dV0=+0.4, Td=2.0e-3, taur=300e-6, tauf=0.8e-3),   # SISO worst corner shape
    dict(dV0=-0.4, Td=2.0e-3, taur=300e-6, tauf=0.8e-3),   # mirrored dV0 sign
    dict(dV0=0.0,  Td=2.0e-3, taur=300e-6, tauf=0.8e-3),   # decoupled, slow
    dict(dV0=+0.4, Td=0.5e-3, taur=20e-6,  tauf=0.0),      # fast/optimistic
    dict(dV0=-0.4, Td=0.5e-3, taur=20e-6,  tauf=0.8e-3),
    dict(dV0=0.0,  Td=0.5e-3, taur=300e-6, tauf=0.0),
]
DRIVE_REPS = [
    dict(K_v=2.0, pole_factor=0.5, tau_v=5.0e-3, Td_v=4.0e-3),   # slowest/highest gain
    dict(K_v=0.5, pole_factor=2.0, tau_v=0.5e-3, Td_v=1.0e-3),   # fastest/lowest gain
    dict(K_v=2.0, pole_factor=2.0, tau_v=0.5e-3, Td_v=4.0e-3),
    dict(K_v=1.0, pole_factor=1.0, tau_v=5.0e-3, Td_v=1.0e-3),
]
# ---- waiver policy (PHYSICAL, not cherry-picked) -----------------------------
# Two corner families get a documented stability-only waiver on the sigma(S_o)
# performance gate.  Both are regimes where the SMALL-SIGNAL MODEL ITSELF is at
# the edge of validity, not regimes where the controller is merely worse:
#
#  (a) 'FC-cruise'  — the r0 = 0.85 operating point.  The EMS parks the droop
#      ratio on its clamp so the fuel cell carries the bus; the share loop has
#      almost no remaining actuator authority by design (Phase-1 flagged it).
#
#  (b) 'K-out-of-envelope' — corners whose share plant gain
#          K = 1 + dV0 (1 - 2 r0)/(k_d I_tot0)
#      falls outside the documented SISO design envelope K in [0.55, 1.45]
#      (mimo_system_model.md / controller_design/system_model.md).  These are
#      exactly the LIGHT-LOAD x FULL-MISMATCH corners (I_tot0 = 0.5 A with
#      |dV0| = 0.4 V): K ~ 1/I_tot0, so at 0.5 A a 0.4 V source mismatch drives
#      K to ~2.1 and pushes the static share alpha0 to within ~0.02 of the
#      unidirectional-switch feasibility boundary.  The share loop there is a
#      near-clamped, ~2x-gain plant that no fixed-gain controller covers at the
#      nominal performance level; the honest engineering answer is "stable, with
#      degraded sensitivity", and gain scheduling on I_tot is future work.
#
# Both families' numbers are REPORTED, never hidden.
K_ENVELOPE = (0.55, 1.45)


def is_nasty(o, p=None):
    p = p0 if p is None else p
    if abs(o['r0'] - 0.85) < 1e-9:
        return 'FC-cruise'
    Kc = PM.share_gain_K(o, p)
    if not (K_ENVELOPE[0] <= Kc <= K_ENVELOPE[1]):
        return 'K-out-of-envelope'
    return None


t0 = time.time()
tier2 = []          # (label, op, sc, dc, ||So||)
for op in PM.op_grid():
    for sc in SHARE_REPS:
        o_probe = dict(op, dV0=sc['dV0'])
        if not PM.op_feasible(o_probe, p0):
            continue
        for dc in DRIVE_REPS:
            Gcx, o_, p_ = PM.corner_plant(op, sc, dc)
            A_, So_ = loop_matrices(Gcx, K_phys)
            if np.max(eigvals(A_).real) >= 0:
                tier2.append((is_nasty(o_), o_, sc, dc, np.inf))
                continue
            tier2.append((is_nasty(o_), o_, sc, dc, hnorm(So_)[0]))
print(f"  {len(tier2)} corners in {time.time()-t0:.1f} s")

main2 = [t for t in tier2 if t[0] is None]
nasty2 = [t for t in tier2 if t[0] is not None]
worst_main = max(main2, key=lambda t: t[4])
print(f"  worst sigma(S_o) over non-waived corners = {worst_main[4]:.4f}")
print(f"    at I_tot0={worst_main[1]['I_tot0']}, r0={worst_main[1]['r0']}, "
      f"dV0={worst_main[1]['dV0']}, share={worst_main[2]}, drive={worst_main[3]}")
gate("Tier-2 worst sigma(S_o) < 2.0 (non-waived corners)", worst_main[4] < 2.0,
     f"{worst_main[4]:.4f}")

for lbl in ('FC-cruise', 'K-out-of-envelope'):
    sub = [t for t in nasty2 if t[0] == lbl]
    if not sub:
        continue
    wc = max(sub, key=lambda t: t[4])
    print(f"  [waiver] {lbl}: worst sigma(S_o) = {wc[4]:.4f} over {len(sub)} corners")
    note(f"Tier-2 {lbl} waived corner worst sigma(S_o)",
         f"{wc[4]:.4f} (stability-only gate; dV0={wc[1]['dV0']}, share={wc[2]})")
    gate(f"Tier-2 {lbl} corners STABLE (stability-only waiver)",
         np.isfinite(wc[4]), f"worst = {wc[4]:.4f}")

tier2_all_worst = max(tier2, key=lambda t: t[4])[4]
note("Tier-2 worst sigma(S_o) including waived corners", f"{tier2_all_worst:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Cross-validation against the full-order truth model
# ─────────────────────────────────────────────────────────────────────────────
hdr("7. CROSS-VALIDATION vs THE FULL-ORDER TRUTH MODEL")

G_full = PM  # placeholder to avoid shadowing
import full_model_mimo as FM
Gt = FM.full_plant_mimo(op0, p0)
print(f"truth model: {Gt.n} states, {Gt.ny}x{Gt.nu}")
A_t, So_t = loop_matrices(Gt, K_phys)
t_stable = np.max(eigvals(A_t).real) < 0
gate("final controller stabilizes the full-order truth model at nominal", t_stable,
     f"max Re(p) = {np.max(eigvals(A_t).real):.4e}")
if t_stable:
    So_t_norm, fb_t = hnorm(So_t)
    So_d_norm, fb_d = hnorm(loop_matrices(G_phys, K_phys)[1])
    rel = abs(So_t_norm - So_d_norm) / So_d_norm
    print(f"  ||S_o|| truth = {So_t_norm:.4f}{' (sweep)' if fb_t else ''}  vs design "
          f"= {So_d_norm:.4f}{' (sweep)' if fb_d else ''}  ({100*rel:.1f} % apart)")
    note("truth-vs-design ||S_o||inf", f"{So_t_norm:.4f} vs {So_d_norm:.4f} "
         f"({100*rel:.1f} %)" + ("  [dense-sweep fallback]" if (fb_t or fb_d) else "")
         + ("  FLAG >20%" if rel > 0.20 else ""))
    gate("truth-model sigma(S_o) within 20 % of the design plant",
         rel < 0.20, f"{100*rel:.1f} %")
else:
    So_t_norm = float('nan')
    rel = float('nan')


# ─────────────────────────────────────────────────────────────────────────────
# 8. Discretization at Ts = 2 ms, modal realization
# ─────────────────────────────────────────────────────────────────────────────
hdr("8. DISCRETIZATION (Ts = 2 ms) + MODAL REALIZATION")

# NOTE: discretization is done on the SCALED controller; De/Du are emitted as
# separate constants so the firmware float32 path sees O(1) states.
Gremd = c2d_tustin(Grem, TS)

# Exact 2x2 Tustin integrator, as an LTI block for analysis:
#   A = I, B = Ts*KI, C = I, D = (Ts/2)*KI   ==   KI*Ts(z+1)/(2(z-1))
Aid = np.eye(2)
Bid = TS * KI
Cid = np.eye(2)
Did = (TS / 2.0) * KI


def modal_form(sysd):
    """Real block-diagonal (modal) realization: real eigenvalues -> 1x1 blocks,
    complex pairs -> [[s, w],[-w, s]] 2x2 blocks.  Improves float32 conditioning
    over the companion/balanced forms (documented in mimo_synthesis.md §8)."""
    if sysd.n == 0:
        return sysd, 1.0
    lam, V = eig(sysd.A)
    cols, used = [], np.zeros(sysd.n, bool)
    order = np.argsort(-np.abs(lam))
    for i in order:
        if used[i]:
            continue
        if abs(lam[i].imag) < 1e-12:
            used[i] = True
            cols.append(np.real(V[:, i]))
        else:
            j = int(np.argmin([abs(lam[k] - np.conj(lam[i])) + (1e9 if used[k] or k == i else 0)
                               for k in range(sysd.n)]))
            used[i] = used[j] = True
            cols.append(np.real(V[:, i]))
            cols.append(np.imag(V[:, i]))
    T = np.column_stack(cols)
    Ti = inv(T)
    return SS(Ti @ sysd.A @ T, Ti @ sysd.B, sysd.C @ T, sysd.D), cond(T)


Gremd_m, cond_T = modal_form(Gremd)
print(f"discrete remainder: {Gremd.n} states; modal transform cond = {cond_T:.4e}")
gate("modal transform well-conditioned (cond < 1e4)", cond_T < 1e4, f"{cond_T:.3e}")

# verify the modal realization reproduces the response
wz = np.logspace(-1, np.log10(np.pi / TS * 0.99), 400)
fr_a = dfreqresp_matrix(Gremd, TS, wz)
fr_b = dfreqresp_matrix(Gremd_m, TS, wz)
mdev = np.max(np.abs(fr_a - fr_b)) / max(1e-12, np.max(np.abs(fr_a)))
gate("modal realization matches the Tustin realization", mdev < 1e-8, f"{mdev:.3e}")

# check off-diagonal structure of the modal A (block-diagonality)
Am = Gremd_m.A
offblk = Am.copy()
note("modal A (discrete)", np.array2string(Am, precision=6).replace("\n", " "))

# full discrete controller (integrator + remainder) for closed-loop analysis
Kd_A = block_diag(Aid, Gremd_m.A)
Kd_B = np.vstack([Bid, Gremd_m.B])
Kd_C = np.hstack([Cid, Gremd_m.C])
Kd_D = Did + Gremd_m.D
Kd_scaled = (Kd_A, Kd_B, Kd_C, Kd_D)
# physical-coordinate discrete controller
Kd_Bp = Kd_B @ Dei
Kd_Cp = Du @ Kd_C
Kd_Dp = Du @ Kd_D @ Dei
NXD = Kd_A.shape[0]
print(f"discrete controller: {NXD} states (2 integrator + {Gremd_m.n} remainder)")


def dclosed_stable(Gc_plant, Ts=TS):
    """Discrete closed loop: plant ZOH-discretized, controller as above."""
    Gd = c2d_zoh(Gc_plant, Ts)
    Ag, Bg, Cg, Dg = Gd.A, Gd.B, Gd.C, Gd.D
    Ak, Bk, Ck, Dk = Kd_A, Kd_Bp, Kd_Cp, Kd_Dp
    # u = Dk(w - y) + Ck xk ; y = Cg xg + Dg u  (Dg = 0 for ZOH of a strictly-
    # proper plant, asserted once at the nominal point)
    Acl = np.block([[Ag - Bg @ Dk @ Cg, Bg @ Ck],
                    [-Bk @ Cg,          Ak]])
    return np.max(np.abs(eigvals(Acl)))


Gd_nom = c2d_zoh(G_phys, TS)
gate("ZOH plant is strictly proper at the sample instants (D = 0)",
     np.max(np.abs(Gd_nom.D)) < 1e-12, f"{np.max(np.abs(Gd_nom.D)):.2e}")
rho_nom = dclosed_stable(G_phys)
print(f"nominal discrete closed loop spectral radius = {rho_nom:.6f}")
gate("nominal discrete closed loop stable", rho_nom < 1.0, f"|z|max = {rho_nom:.6f}")

print("\nTier-1 discrete stability sweep ...")
t0 = time.time()
rho_worst = 0.0
rho_corner = None
d_unstable = 0
n_d = 0
for op, sc, dc, feas in PM.tier1_corners():
    if not feas:
        continue
    n_d += 1
    Gcx, o_, p_ = PM.corner_plant(op, sc, dc)
    r_ = dclosed_stable(Gcx)
    if r_ > rho_worst:
        rho_worst, rho_corner = r_, (o_, sc, dc)
    if r_ >= 1.0:
        d_unstable += 1
print(f"  {n_d} corners in {time.time()-t0:.1f} s; worst |z| = {rho_worst:.6f}")
gate("Tier-1 discrete: ALL feasible corners |z| < 1", d_unstable == 0,
     f"{d_unstable} unstable of {n_d}; worst |z| = {rho_worst:.6f}")
note("discrete worst-|z| corner",
     f"I_tot0={rho_corner[0]['I_tot0']}, r0={rho_corner[0]['r0']}, "
     f"dV0={rho_corner[0]['dV0']}, share={rho_corner[1]}, drive={rho_corner[2]}")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Reference implementation (float64) + float32 replay + anti-windup
# ─────────────────────────────────────────────────────────────────────────────
hdr("9. REFERENCE IMPLEMENTATION / ANTI-WINDUP / FLOAT32 REPLAY")

U0 = np.array([op0['r0'], 0.0])              # physical OP offsets (r0, i_m0 = 0)
U_MIN = np.array([R_MIN, -I_MOT_MAX])
U_MAX = np.array([R_MAX, +I_MOT_MAX])
Dui = inv(Du)
XI_MIN = Dui @ (U_MIN - U0)
XI_MAX = Dui @ (U_MAX - U0)
gate("anti-windup back-calculation map cond(Du^-1) < 1e3", cond(Dui) < 1e3,
     f"cond = {cond(Dui):.3f}")
note("integrator authority clamp (scaled)",
     f"x_int in [{XI_MIN}, {XI_MAX}]")


class MimoController:
    """Mirrors the intended C++ float32 implementation EXACTLY.

    State update (scaled coordinates), ordered exactly as the shipped SISO
    firmware (share_controller.h): the integrator is advanced FIRST and the NEW
    value is used in the output, so u[k] carries the trapezoidal integral THROUGH
    sample k and the block is exactly the Tustin integrator KI*Ts(z+1)/(2(z-1)).
        x_int'= x_int + (Ts/2) KI (e_s + e_prev)     [trapezoidal, matrix KI]
        u_s   = C x_rem + D e_s + x_int'
        x_rem'= Ad x_rem + Bd e_s
    Physical output:
        u     = u0 + Du u_s,  clamped to [U_MIN, U_MAX]
    Anti-windup (back-calculation on the integrator subspace):
        delta = u_sat - u  (physical);  x_int += Du^-1 delta
    (x_int adds directly to u_s, so its output map is I2 and the back-calculation
    map is exactly Du^-1 — see mimo_synthesis.md §8.)
    PLUS an authority clamp  x_int in [XI_MIN, XI_MAX] = Du^-1 (U_MIN/U_MAX - U0):
    the integrator alone may never demand more than the actuator can deliver.
    Rationale (mimo_synthesis.md §8.3): the shipped SISO scheme is bare
    back-calculation, which is safe there because the scalar controller's direct
    term is small.  That was ACUTE at the +-5 A clamp: D22 was ~8 in scaled units
    (a 0.5 m/s error asks for ~39 A against the I_MOT_MAX clamp — see the actuator-rate
    finding in §8.4), so bare back-calculation lets the DIRECT term's excess be
    dumped into the integrator, which then holds the opposite rail once the error
    collapses.  RE-CHECKED at the +-20 A clamp (2026-08-04): the restored effort
    weight (it.5) cut D22 to ~0.11 scaled, so the direct term now asks only a couple
    of amps on the same error and that acute failure mode is GONE.  The clamp is
    RETAINED anyway -- it costs 2 compares per tick, it IS the actuator's own
    authority (XI = Du^-1 (U_lim - U0) = +-1 exactly, by construction, since Du now
    equals the clamp), and it keeps the AW argument independent of however large D22
    happens to come out of a given weight iteration.  Verified by the closed-loop
    saturation-recovery sim below.
    """

    def __init__(self, dtype=np.float64):
        d = dtype
        self.dt = d
        self.A = np.asarray(Gremd_m.A, d)
        self.B = np.asarray(Gremd_m.B, d)
        self.C = np.asarray(Gremd_m.C, d)
        self.D = np.asarray(Gremd_m.D, d)
        self.KI = np.asarray(KI, d)
        self.Du = np.asarray(Du, d)
        self.Dui = np.asarray(Dui, d)
        self.u0 = np.asarray(U0, d)
        self.umin = np.asarray(U_MIN, d)
        self.umax = np.asarray(U_MAX, d)
        self.ximin = np.asarray(XI_MIN, d)
        self.ximax = np.asarray(XI_MAX, d)
        self.hTs = d(TS / 2.0)
        self.reset()

    def reset(self):
        d = self.dt
        self.x = np.zeros(self.A.shape[0], d)
        self.xi = np.zeros(2, d)
        self.ep = np.zeros(2, d)

    def step(self, e_s):
        d = self.dt
        e = np.asarray(e_s, d)
        xi = (self.xi + self.hTs * (self.KI @ (e + self.ep))).astype(d)
        us = self.C @ self.x + self.D @ e + xi
        u = self.u0 + self.Du @ us
        usat = np.clip(u, self.umin, self.umax).astype(d)
        delta = (usat - u).astype(d)
        if np.any(delta != 0):
            xi = (xi + self.Dui @ delta).astype(d)
        xn = self.A @ self.x + self.B @ e
        self.xi = np.clip(xi, self.ximin, self.ximax).astype(d)
        self.x = xn.astype(d)
        self.ep = e
        return usat


# Equivalence of the recursive trapezoidal form with the LTI realization
#   (A = I, B = Ts*KI, C = I, D = (Ts/2)*KI)  ==  KI*Ts*(z+1)/(2(z-1)).
# The two differ only by the initial condition: the recursive form starts from
# x_int = 0 with e_prev = 0, which corresponds to LTI x[0] = -(Ts/2) KI e[0].
rng = np.random.default_rng(RNG_SEED)
etest = rng.normal(size=(40, 2))
ctl = MimoController(np.float64)
ctl.umin = np.array([-1e9, -1e9]); ctl.umax = np.array([1e9, 1e9])
ctl.ximin = np.array([-1e9, -1e9]); ctl.ximax = np.array([1e9, 1e9])
ctl.reset()
ctl_lti_x = np.zeros(2)
eq_err = 0.0
for e in etest:
    u_ref = ctl_lti_x + Did @ e
    ctl_lti_x = Aid @ ctl_lti_x + Bid @ e
    ctl.step(e)
    eq_err = max(eq_err, np.max(np.abs(u_ref - ctl.xi)))   # xi AFTER the update
gate("recursive trapezoidal integrator == LTI Tustin integrator", eq_err < 1e-12,
     f"max dev = {eq_err:.3e}")

# ---- seeded 64-step reference sequence (steps + noise + saturating episode) ---
rng = np.random.default_rng(RNG_SEED)
E_ref = np.zeros((REF_N, 2))
for k in range(REF_N):
    if k < 12:
        base = np.array([0.30, 0.0])          # share step
    elif k < 24:
        base = np.array([0.0, 0.60])          # speed step
    elif k < 40:
        base = np.array([-0.20, -0.35])       # combined reversal
    elif k < 56:
        base = np.array([2.5, 3.0])           # deliberately saturating episode
    else:
        base = np.array([0.05, -0.05])        # release / recovery
    E_ref[k] = base + 0.03 * rng.normal(size=2)

c64 = MimoController(np.float64)
U_ref = np.array([c64.step(E_ref[k]) for k in range(REF_N)])
c32 = MimoController(np.float32)
U_32 = np.array([c32.step(E_ref[k].astype(np.float32)) for k in range(REF_N)], float)
replay_err = np.max(np.abs(U_ref - U_32))
print(f"float32 vs float64 replay max abs error = {replay_err:.3e}")
gate("float32 replay error < 5e-4", replay_err < 5e-4, f"{replay_err:.3e}")

n_sat = int(np.sum(np.any((U_ref <= U_MIN + 1e-12) | (U_ref >= U_MAX - 1e-12), axis=1)))
gate("reference sequence exercises saturation", n_sat >= 8, f"{n_sat} saturated steps")
gate("reference outputs stay inside the clamps",
     np.all(U_ref >= U_MIN - 1e-12) and np.all(U_ref <= U_MAX + 1e-12))

# ---- closed-loop saturation-recovery sim -------------------------------------
# The meaningful anti-windup test is CLOSED LOOP: an open-loop "hold a huge error
# then force it to zero" sequence is unphysical (the loop has no way to unwind the
# integrator when the error is externally pinned at 0).  Here the drive reference
# is stepped hard enough to rail the current at -I_MOT_MAX (a braking/regen command),
# held, then returned; the loop itself must unwind.


def sim_ref(ref_of_k, n, Gplant=None, ctrl=None):
    """Discrete closed-loop sim (ZOH plant @ Ts, the reference implementation).
    ref_of_k(k) -> [alpha_ref, v_ref] as small-signal deviations.
    Returns (y, u) arrays."""
    Gp_ = G_phys if Gplant is None else Gplant
    Gd = c2d_zoh(Gp_, TS)
    c = MimoController(np.float64) if ctrl is None else ctrl
    xg = np.zeros(Gd.A.shape[0])
    y = np.zeros((n, 2)); u = np.zeros((n, 2))
    for k in range(n):
        yk = Gd.C @ xg
        uk = c.step(Dei @ (np.asarray(ref_of_k(k), float) - yk))
        xg = Gd.A @ xg + Gd.B @ (uk - U0)
        y[k] = yk; u[k] = uk
    return y, u


N_AW = 30000                                  # 60 s: the post-saturation tail is
# governed by the drive integrator gain KI22 = O(0.6) against a 0.122 rad/s plant
# pole, so recovery is SLOW (tens of seconds) by design -- see mimo_synthesis.md §8.4.
y_aw, u_aw = sim_ref(lambda k: [0.0, -2.0 if k < 1000 else 0.0], N_AW)
railed = np.mean(u_aw[:400, 1] <= -I_MOT_MAX + 1e-9)
# RAIL METRIC REDEFINED at the +-20 A clamp (2026-08-04).  The old gate asked for a
# railed FRACTION > 0.9 of the first 800 ms, which was a proxy for "this event saturates"
# that only held because +-5 A could not brake a 2 m/s command in under a second.  With
# 4x the actuator the SAME physical event still rails, just briefly, so the fraction
# collapses (0.19) while the event is unchanged.  The gate now measures the DURATION of
# the saturated episode, which is what the anti-windup test actually needs, and is
# clamp-agnostic.
rail_ticks = int(np.sum(u_aw[:1000, 1] <= -I_MOT_MAX + 1e-9))
rail_ms = rail_ticks*TS*1e3
after = u_aw[1000:, 1]
rec_idx = int(np.argmax(after > -I_MOT_MAX + 1e-6)) if np.any(after > -I_MOT_MAX + 1e-6) else -1
tail_y = y_aw[-100:, 1]
tail_u = u_aw[-100:, 1]
print(f"AW: saturated episode = {rail_ms:.0f} ms (railed fraction of the first 800 ms = "
      f"{railed:.2f}); off the rail {rec_idx} ticks "
      f"({rec_idx*TS*1e3:.0f} ms) after release; tail v = {np.mean(tail_y):.5f} m/s, "
      f"tail i = {np.mean(tail_u):.4f} A")
gate("AW: drive channel actually rails on the hard reference step (>= 20 ms saturated)",
     rail_ms >= 20.0, f"{rail_ms:.0f} ms on the -{I_MOT_MAX:.0f} A rail "
     f"(fraction of first 800 ms = {railed:.2f})")
gate("AW: comes off the rail after the reference is released", 0 <= rec_idx < int(0.5/TS),
     f"{rec_idx} ticks ({rec_idx*TS*1e3:.0f} ms)")
gate("AW: closed loop recovers to the released reference (v -> 0)",
     np.max(np.abs(tail_y)) < 5e-3, f"max |v| tail = {np.max(np.abs(tail_y)):.2e} m/s")
gate("AW: no sustained rail after recovery",
     np.max(np.abs(tail_u)) < 0.5, f"max |i| tail = {np.max(np.abs(tail_u)):.4f} A")
gate("AW: outputs stayed clamped throughout",
     np.all(u_aw >= U_MIN - 1e-12) and np.all(u_aw <= U_MAX + 1e-12))
gate("AW: share channel stayed inside [0.15, 0.85]",
     np.all(u_aw[:, 0] >= R_MIN - 1e-12) and np.all(u_aw[:, 0] <= R_MAX + 1e-12))
write_csv_pending = (np.arange(N_AW)*TS, y_aw, u_aw)


# ─────────────────────────────────────────────────────────────────────────────
# 10. Diagonal-plant sanity check (dV0 = 0)
# ─────────────────────────────────────────────────────────────────────────────
hdr("10. DIAGONAL-PLANT SANITY (dV0 = 0)")

op_diag = dict(op0, dV0=0.0)
Gs_diag = PM.scaled_plant(None, De, Du, op_diag, p0)
G0d = Gs_diag.dcgain_matrix()
gate("dV0 = 0 gives a diagonal plant", abs(G0d[0, 1]) < 1e-14 and abs(G0d[1, 0]) < 1e-14,
     f"|G12| = {abs(G0d[0,1]):.2e}, |G21| = {abs(G0d[1,0]):.2e}")

G11d = sub_ss(Gs_diag, [0], [0])
G22d = sub_ss(Gs_diag, [1], [1])
g1 = siso_gamma(G11d, Wp_share1, makeweight(*SHARE_W['wd']), makeweight(*SHARE_W['wu']))
g2 = siso_gamma(G22d, drive_wp(DRIVE_W), makeweight(*DRIVE_W['wd']), makeweight(*DRIVE_W['wu']))
_, g_mimo_diag, _, _, _ = synth_refined(AugPlantMIMO(Gs_diag, Wp, Wu, Wd))
gmax_siso = max(g1, g2)
dev = abs(g_mimo_diag - gmax_siso) / gmax_siso
print(f"SISO gammas: share = {g1:.5f}, drive = {g2:.5f}; MIMO(diag) = {g_mimo_diag:.5f}")
gate("diagonal-plant MIMO gamma ~= max(SISO gammas) (5 %)", dev < 0.05,
     f"{g_mimo_diag:.5f} vs {gmax_siso:.5f} ({100*dev:.2f} %)")


# ─────────────────────────────────────────────────────────────────────────────
# 11. Figures (CSV) + step responses
# ─────────────────────────────────────────────────────────────────────────────
hdr("11. FIGURE DATA + STEP RESPONSES")

wf = np.logspace(-1, 4, 400)


def write_csv(path, header, cols, stride=1):
    """stride > 1 decimates long time series: the 60 s @ 2 ms sims are 30000 rows,
    and every 10th sample is ample resolution for a figure."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for row in list(zip(*cols))[::stride]:
            f.write(",".join(f"{v:.9e}" for v in row) + "\n")
    print(f"  wrote {os.path.relpath(path, HERE)}")


# nominal S/T singular values
S_sv = sv(loop_matrices(Gs, Gc_red)[1], wf)
T_sv = sv(comp_sens(Gs, Gc_red), wf)
write_csv(os.path.join(FIGDIR, "mimo_sigma_nominal.csv"),
          "w,sigma_max_S,sigma_min_S,sigma_max_T,sigma_min_T",
          [wf, S_sv[:, 0], S_sv[:, -1], T_sv[:, 0], T_sv[:, -1]])

# worst Tier-2 corner
Gw, ow, pw = PM.corner_plant(worst_main[1], worst_main[2], worst_main[3])
Sw = loop_matrices(Gw, K_phys)[1]
Tw = comp_sens(Gw, K_phys)
write_csv(os.path.join(FIGDIR, "mimo_sigma_worst_corner.csv"),
          "w,sigma_max_S,sigma_min_S,sigma_max_T,sigma_min_T",
          [wf, sv(Sw, wf)[:, 0], sv(Sw, wf)[:, -1], sv(Tw, wf)[:, 0], sv(Tw, wf)[:, -1]])

# controller frequency response (scaled coordinates, all four entries)
Kf = ctrl_freqresp(KI, Grem, wf)
write_csv(os.path.join(FIGDIR, "mimo_controller_freqresp.csv"),
          "w,K11_mag,K12_mag,K21_mag,K22_mag,K11_ph,K22_ph",
          [wf, np.abs(Kf[:, 0, 0]), np.abs(Kf[:, 0, 1]), np.abs(Kf[:, 1, 0]),
           np.abs(Kf[:, 1, 1]),
           np.angle(Kf[:, 0, 0], deg=True), np.angle(Kf[:, 1, 1], deg=True)])

# RGA vs frequency at the design OP
Gf = Gs.freqresp_matrix(wf)
rga11 = np.array([rga(Gf[i])[0, 0] for i in range(len(wf))])
write_csv(os.path.join(FIGDIR, "mimo_rga_vs_freq.csv"),
          "w,rga11_re,rga11_im,rga11_mag",
          [wf, rga11.real, rga11.imag, np.abs(rga11)])


# ---- step responses (physical coordinates, with clamps + AW) -----------------
# ACTUATOR-RATE FINDING (mimo_synthesis.md §8.4) -- RETIRED at the +-20 A clamp.
# Force per amp is K_F = k_t*eta_dt*phi/r_t ~ 1.33 N/A, so a_max = I_MOT_MAX*K_F/m_eff.
# At +-5 A that was ~2.3 m/s^2 and the drive channel was ACTUATOR-limited rather than
# bandwidth-limited: a 0.5 m/s step took ~0.2 s just to accelerate and ~16 s to settle.
# At +-20 A a_max is ~9 m/s^2, the 0.5 m/s step peaks well inside the clamp, and it
# settles in the SAME time as the small-signal step -- the channel is bandwidth-limited
# again.  Both steps are still simulated: the 0.05 m/s one validates the linear design,
# and the 0.5 m/s one is kept as the large-signal / DC-tracking check (the Youla-H
# T(0) = I property).  Its label "actuator-limited" is retained in the artefact names
# only for continuity with the +-5 A run; the measured peak current now proves it is not.
N_STEP = 30000                                # 60 s (slow post-saturation tail)
t = np.arange(N_STEP) * TS
y_s, u_s_ = sim_ref(lambda k: [0.05, 0.0], N_STEP)
y_v, u_v_ = sim_ref(lambda k: [0.0, 0.05], N_STEP)
y_L, u_L = sim_ref(lambda k: [0.0, 0.5], N_STEP)

write_csv(os.path.join(FIGDIR, "mimo_step_share.csv"),
          "t,alpha,v,r_cmd,i_cmd", [t, y_s[:, 0], y_s[:, 1], u_s_[:, 0], u_s_[:, 1]], stride=10)
write_csv(os.path.join(FIGDIR, "mimo_step_drive.csv"),
          "t,alpha,v,r_cmd,i_cmd", [t, y_v[:, 0], y_v[:, 1], u_v_[:, 0], u_v_[:, 1]], stride=10)
write_csv(os.path.join(FIGDIR, "mimo_step_drive_large.csv"),
          "t,alpha,v,r_cmd,i_cmd", [t, y_L[:, 0], y_L[:, 1], u_L[:, 0], u_L[:, 1]], stride=10)
write_csv(os.path.join(FIGDIR, "mimo_antiwindup_recovery.csv"),
          "t,alpha,v,r_cmd,i_cmd",
          [write_csv_pending[0], write_csv_pending[1][:, 0], write_csv_pending[1][:, 1],
           write_csv_pending[2][:, 0], write_csv_pending[2][:, 1]], stride=10)


def settle(y, target, tol=0.02):
    band = tol * abs(target)
    idx = np.where(np.abs(y - target) > band)[0]
    return (idx[-1] + 1) * TS * 1e3 if len(idx) else 0.0


s_share = settle(y_s[:, 0], 0.05)
s_drive = settle(y_v[:, 1], 0.05)
s_drive_L = settle(y_L[:, 1], 0.5)
i_pk_small = np.max(np.abs(u_v_[:, 1]))
i_pk_large = np.max(np.abs(u_L[:, 1]))
xtalk_share = np.max(np.abs(y_v[:, 0]))     # share excursion during a drive step
xtalk_share_L = np.max(np.abs(y_L[:, 0]))
xtalk_drive = np.max(np.abs(y_s[:, 1]))
print(f"share step (0.05):  2% settle = {s_share:.0f} ms, "
      f"drive cross-talk = {xtalk_drive:.3e} m/s, final alpha = {y_s[-1,0]:.6f}")
print(f"drive step (0.05 m/s, small-signal): 2% settle = {s_drive:.0f} ms, "
      f"peak i = {i_pk_small:.2f} A, share cross-talk = {xtalk_share:.4f}")
print(f"drive step (0.50 m/s, large-signal): 2% settle = {s_drive_L:.0f} ms, "
      f"peak i = {i_pk_large:.2f} A, share cross-talk = {xtalk_share_L:.4f}, "
      f"final v = {y_L[-1,1]:.6f}")
gate("share step settles < 300 ms", s_share < 300.0, f"{s_share:.0f} ms")
gate(f"small-signal drive step stays inside the +-{I_MOT_MAX:.0f} A clamp", i_pk_small < I_MOT_MAX - 1e-9,
     f"peak {i_pk_small:.2f} A")
gate("small-signal drive step settles < 500 ms", s_drive < 500.0, f"{s_drive:.0f} ms")
note("large-step (0.5 m/s) recovery time", f"2% settle {s_drive_L/1000:.1f} s at a {i_pk_large:.1f} A peak -- at +-20 A this step no longer rails, so it is a linear response, not the actuator-limited slew the +-5 A design showed (16 s)")
gate("share DC tracking exact (T(0) = I)", abs(y_s[-1, 0] - 0.05) < 1e-4,
     f"final alpha = {y_s[-1,0]:.6f}")
gate("drive DC tracking exact, small signal (T(0) = I)", abs(y_v[-1, 1] - 0.05) < 1e-4,
     f"final v = {y_v[-1,1]:.6f}")
gate("drive DC tracking exact on the 0.5 m/s large-signal step (AW does not bias DC)",
     abs(y_L[-1, 1] - 0.5) < 1e-3, f"final v = {y_L[-1,1]:.6f}")
note("drive-transient share excursion (nominal, dV0 = +0.2 V)",
     f"{xtalk_share:.5f} share (small step) / {xtalk_share_L:.5f} (0.5 m/s slew)")
note("drive actuator-rate limit", f"a_max ~ {I_MOT_MAX*PM.force_per_amp(p0)/p0['m_eff']:.2f} m/s^2 "
     f"({PM.force_per_amp(p0):.3f} N/A x {I_MOT_MAX} A / {p0['m_eff']} kg)")


# ─────────────────────────────────────────────────────────────────────────────
# 12. Teensy 4.1 cost
# ─────────────────────────────────────────────────────────────────────────────
hdr("12. TEENSY 4.1 IMPLEMENTATION COST")

nx = Gremd_m.n
# per tick: C x (2*nx) + D e (4) + x_int add (0) ; A x (nx*nx) + B e (2*nx)
# ; KI(e+ep) (4) + scale (2) ; Du us (4) ; AW Du^-1 delta (4, conditional)
mac_rem = 2 * nx + 4 + nx * nx + 2 * nx
mac_int = 4 + 2
mac_scale = 4 + 2          # Du*us, De^-1*e
mac_aw = 4
mac_total = mac_rem + mac_int + mac_scale + mac_aw
n_coeff = (nx*nx + 2*nx + 2*nx + 4      # A, B, C, D
           + 4                          # KI
           + 2 + 2 + 2 + 2 + 2          # DE, DU, U0, U_MIN, U_MAX
           + 2 + 2 + 2)                 # XI_MIN, XI_MAX, DU_INV
mem_bytes = 4 * n_coeff
state_bytes = 4 * (nx + 2 + 2)
# shipped SISO: 3 biquads DF2T (5 MAC each) + integrator
mac_shipped = 3 * 5 + 3
print(f"MIMO: {mac_total} MAC/tick @ {1/TS:.0f} Hz  = {mac_total/TS:.0f} MAC/s")
print(f"shipped SISO share: ~{mac_shipped} MAC/tick @ 1 kHz = {mac_shipped*1000:.0f} MAC/s")
print(f"coefficient storage: {n_coeff} floats = {mem_bytes} B; state {state_bytes} B")
cpu_frac = (mac_total / TS) / 600e6
print(f"~{100*cpu_frac:.5f} % of a 600 MHz M7 issue slot (1 MAC/cycle, no FPU pipelining credit)")
gate("Teensy cost negligible (< 0.1 % of core issue rate)", cpu_frac < 1e-3,
     f"{100*cpu_frac:.5f} %")


# ─────────────────────────────────────────────────────────────────────────────
# 13. Emission
# ─────────────────────────────────────────────────────────────────────────────
hdr("13. EMISSION")


def fa(x):
    return f"{float(x):.9e}f"


def mat_rows(M, indent="    "):
    return ",\n".join(indent + "{ " + ", ".join(fa(v) for v in row) + " }"
                      for row in np.atleast_2d(M))


TAUF = p0['tauf']
meas_A = float(np.exp(-TS / TAUF)) if TAUF > 0 else 0.0

hdr_path = os.path.join(HERE, "mimo_controller_coeffs.h")
with open(hdr_path, "w", encoding="utf-8") as f:
    f.write(f"""// mimo_controller_coeffs.h — GENERATED by controller_design_MIMO/synthesize_mimo_controller.py
// DO NOT EDIT BY HAND. Regenerate after bench calibration (mimo_system_model.md §9).
//
// NOT WIRED INTO THE FIRMWARE BUILD. This is the emitted artefact of the
// centralized 2x2 MIMO H-inf / Youla-H design (mimo_synthesis.md); firmware
// integration would be a separate, reviewed round.
//
// Controller (SCALED coordinates, single rate Ts = {TS*1e3:.1f} ms / {1/TS:.0f} Hz):
//     e_s   = DE^-1 * (ref - y)            [share, speed]
//     u_s   = C*x + D*e_s + x_int
//     x'    = A*x + B*e_s
//     x_int'= x_int + (Ts/2)*KI*(e_s + e_prev)      (exact 2x2 Tustin integrator)
//     u     = U0 + DU*u_s,  clamped to [U_MIN, U_MAX]
//     anti-windup: x_int += DU^-1*(u_sat - u), then x_int clamped to
//                  [XI_MIN, XI_MAX] = DU^-1*(U_MIN/U_MAX - U0)  (authority bound)
// ORDERING MATTERS: advance x_int FIRST and use the NEW value in u_s, exactly as
// the shipped SISO share_controller.h does — that makes the block the exact
// Tustin integrator KI*Ts(z+1)/(2(z-1)).
// The A matrix is in REAL MODAL (block-diagonal) form for float32 robustness.
//
// Design record: gamma (DGKF Riccati bisection) = {g_opt:.4f} — OPTIMISTIC for the
// 2x2 problem; the honest a-posteriori level is gamma = {g_used:.4f} with
// ||Tzw||inf = {tzw:.4f}.  T(0) = I is enforced by the MIMO Youla-H DC correction
// and made structural by the exact 2x2 integrator split.
#pragma once

#define MIMO_CTRL_TS_US    {int(round(TS*1e6))}      // controller update period, microseconds
#define MIMO_CTRL_NX       {nx}         // stable-remainder states (plus 2 integrator states)
#define MIMO_CTRL_NY       2
#define MIMO_CTRL_NU       2

// stable remainder, discrete (Tustin @ Ts), real modal form
static const float MIMO_CTRL_A[MIMO_CTRL_NX][MIMO_CTRL_NX] = {{
{mat_rows(Gremd_m.A)}
}};
static const float MIMO_CTRL_B[MIMO_CTRL_NX][MIMO_CTRL_NU] = {{
{mat_rows(Gremd_m.B)}
}};
static const float MIMO_CTRL_C[MIMO_CTRL_NY][MIMO_CTRL_NX] = {{
{mat_rows(Gremd_m.C)}
}};
static const float MIMO_CTRL_D[MIMO_CTRL_NY][MIMO_CTRL_NU] = {{
{mat_rows(Gremd_m.D)}
}};

// continuous integrator residue matrix (Tustin applied in code)
static const float MIMO_CTRL_KI[2][2] = {{
{mat_rows(KI)}
}};

// scaling: e_s = DE^-1 * e_phys ; u_phys = U0 + DU * u_s
static const float MIMO_CTRL_DE[2] = {{ {fa(De[0,0])}, {fa(De[1,1])} }};   // [share, m/s]
static const float MIMO_CTRL_DU[2] = {{ {fa(Du[0,0])}, {fa(Du[1,1])} }};   // [droop ratio, A]

// operating-point offsets the small-signal command is added to
static const float MIMO_CTRL_U0[2]    = {{ {fa(U0[0])}, {fa(U0[1])} }};    // r0, i_m0
static const float MIMO_CTRL_U_MIN[2] = {{ {fa(U_MIN[0])}, {fa(U_MIN[1])} }};
static const float MIMO_CTRL_U_MAX[2] = {{ {fa(U_MAX[0])}, {fa(U_MAX[1])} }};

// integrator authority clamp (scaled): the integrator alone may never demand
// more than the actuator can deliver.  = DU^-1 (U_MIN - U0) and DU^-1 (U_MAX - U0).
static const float MIMO_CTRL_XI_MIN[2] = {{ {fa(XI_MIN[0])}, {fa(XI_MIN[1])} }};
static const float MIMO_CTRL_XI_MAX[2] = {{ {fa(XI_MAX[0])}, {fa(XI_MAX[1])} }};
// anti-windup back-calculation map (= DU^-1, diagonal), cond = {cond(Dui):.3f}
static const float MIMO_CTRL_DU_INV[2] = {{ {fa(Dui[0,0])}, {fa(Dui[1,1])} }};

// measured-share prefilter 1/(tauf*s+1), tauf = {TAUF*1e3:.1f} ms, discretized at Ts:
//   alphaFilt += (1 - A)*(alphaRaw - alphaFilt), A = exp(-Ts/tauf).
// It is PART OF THE DESIGN PLANT (mimo_system_model.md) — the loop is synthesized
// WITH this lag in it; do not remove it or retune it independently.
static const float MIMO_CTRL_MEAS_FILT_A = {fa(meas_A)};
""")
print(f"  wrote {os.path.relpath(hdr_path, HERE)}")

ref_path = os.path.join(HERE, "mimo_reference_vectors.h")
with open(ref_path, "w", encoding="utf-8") as f:
    f.write(f"""// mimo_reference_vectors.h — GENERATED by controller_design_MIMO/synthesize_mimo_controller.py
// DO NOT EDIT BY HAND.
//
// Replay vectors for the MIMO controller in mimo_controller_coeffs.h.
// MIMO_REF_E[k] is the SCALED error e_s fed to step(); MIMO_REF_U[k] is the
// PHYSICAL, clamped output u (after U0 + DU*u_s and the anti-windup clamp),
// computed by the float64 Python reference implementation
// (synthesize_mimo_controller.py, class MimoController).
//
// Sequence: seeded rng {RNG_SEED}; share step, speed step, combined reversal,
// a deliberately SATURATING episode (steps {24}-{56}), then release/recovery.
// Controller state starts at zero.  float32 replay tolerance: 5e-4
// (achieved by the reference pipeline: {replay_err:.3e}).
#pragma once

#define MIMO_REF_N   {REF_N}

static const float MIMO_REF_E[MIMO_REF_N][2] = {{
{mat_rows(E_ref)}
}};

static const float MIMO_REF_U[MIMO_REF_N][2] = {{
{mat_rows(U_ref)}
}};
""")
print(f"  wrote {os.path.relpath(ref_path, HERE)}")

met_path = os.path.join(HERE, "mimo_synthesis_metrics.txt")
with open(met_path, "w", encoding="utf-8") as f:
    f.write("MIMO H-inf + Youla-H synthesis metrics (generated)\n")
    f.write("=" * 62 + "\n\n")
    f.write("[design point]\n")
    f.write(f"operating point      = I_tot0 {op0['I_tot0']} A, r0 {op0['r0']}, "
            f"dV0 {op0['dV0']} V, v0 {op0['v0']} m/s\n")
    f.write(f"plant                = {G_phys.n} states, 2x2, strictly proper\n")
    f.write(f"De                   = diag({De[0,0]}, {De[1,1]})\n")
    f.write(f"Du                   = diag({Du[0,0]}, {Du[1,1]})\n")
    f.write(f"cond(Gs(0))          = {cond(G0s):.4f}\n")
    f.write(f"Gs(0)[0,1] (coupling)= {G0s[0,1]:.6f}\n\n")
    f.write("[synthesis]\n")
    f.write(f"gamma_riccati        = {g_opt:.5f}   (DGKF bisection; OPTIMISTIC in MIMO, "
            "see synth_refined)\n")
    f.write(f"gamma_achieved       = {g_used:.5f}   (a-posteriori refined, the honest level)\n")
    f.write(f"||Tzw||inf           = {tzw:.5f}\n")
    f.write(f"isolated SISO gammas = share {g_share:.5f}, drive {g_drive:.5f}\n")
    f.write(f"plan's 2nd-order drive weight would give gamma_drive = {g_drive_plan:.5f} "
            "(structurally unmeetable, see weight iterations)\n")
    f.write("weight iterations:\n")
    for nm, dt in WEIGHT_ITERS:
        f.write(f"    {nm}\n        {dt}\n")
    f.write(f"H-inf controller ord = {K_H.n}\n")
    f.write(f"||Y_ARE||max         = {Ynorm:.3e}  (D21 = I degeneracy cross-check)\n\n")
    f.write("[Youla-H DC correction]\n")
    f.write(f"cond(Gs(0) Y_H(0))   = {cond(GY0):.4e}\n")
    f.write(f"||M - I||_2          = {Mdev:.4e}\n")
    f.write(f"M                    = [[{M[0,0]:.6f}, {M[0,1]:.6f}], "
            f"[{M[1,0]:.6f}, {M[1,1]:.6f}]]\n")
    f.write(f"KI                   = [[{KI[0,0]:.6f}, {KI[0,1]:.6f}], "
            f"[{KI[1,0]:.6f}, {KI[1,1]:.6f}]]\n")
    f.write(f"rank(KI) / cond(KI)  = {matrix_rank(KI)} / {cond(KI):.4e}\n")
    f.write(f"||T(0) - I||_max     = {err_T0:.3e}\n\n")
    f.write("[reduction]\n")
    f.write(f"Gc_YH raw order      = {Gc_YH.n}\n")
    f.write(f"remainder order      = {Grem_full.n} -> {nx}\n")
    f.write(f"total controller ord = {nx + 2} (2 integrator + {nx})\n")
    f.write(f"HSV                  = {np.array2string(hsv[:10], precision=5)}\n")
    f.write(f"reduced-vs-full dev  = {red_rel:.4e} (rel sigma, w in [1e-1, 1e4])\n\n")
    f.write("[controller structure]\n")
    f.write(f"|K11|max / |K12|max  = {diag_peak[0]:.5f} / {offdiag_peak[0]:.5f}  "
            f"(ratio {K12_rel:.5f})\n")
    f.write(f"|K22|max / |K21|max  = {diag_peak[1]:.5f} / {offdiag_peak[1]:.3e}  "
            f"(ratio {K21_rel:.3e})\n\n")
    f.write("[nominal performance]\n")
    f.write(f"||S_o||inf nominal   = {So_nom_norm:.4f}\n")
    f.write(f"||T_o||inf nominal   = {To_nom_norm:.4f}\n")
    f.write(f"share step 2% settle = {s_share:.0f} ms   (0.05 share, final {y_s[-1,0]:.6f})\n")
    f.write(f"drive step 2% settle = {s_drive:.0f} ms   (0.05 m/s small-signal, "
            f"final {y_v[-1,1]:.6f}, peak {i_pk_small:.2f} A)\n")
    f.write(f"drive 0.5 m/s step   = {s_drive_L:.0f} ms   (large-signal; NOT actuator-limited at +-20 A -- peak is inside the clamp, cf. 15750 ms at +-5 A, "
            f"final {y_L[-1,1]:.6f}, peak {i_pk_large:.2f} A)\n")
    f.write(f"drive accel limit    = {I_MOT_MAX*PM.force_per_amp(p0)/p0['m_eff']:.3f} m/s^2 "
            f"({PM.force_per_amp(p0):.4f} N/A)\n")
    f.write(f"drive->share excurs. = {xtalk_share:.5f} (small) / {xtalk_share_L:.5f} "
            "(0.5 m/s slew)\n\n")
    f.write("[corner batteries]\n")
    f.write(f"Tier-1 feasible      = {n_feas} corners ({n_skip} infeasible skipped)\n")
    f.write(f"Tier-1 unstable      = {len(unstable)}\n")
    f.write(f"Tier-1 worst Re(p)   = {worst_re:.4e}\n")
    f.write(f"Tier-2 corners       = {len(tier2)} ({len(main2)} gated, {len(nasty2)} waived)\n")
    f.write(f"Tier-2 worst sigma(S_o) [gated]  = {worst_main[4]:.4f} at "
            f"I_tot0 {worst_main[1]['I_tot0']}, r0 {worst_main[1]['r0']}, "
            f"dV0 {worst_main[1]['dV0']}, Td {worst_main[2]['Td']}, "
            f"taur {worst_main[2]['taur']}, tauf {worst_main[2]['tauf']}, "
            f"K_v {worst_main[3]['K_v']}, pf {worst_main[3]['pole_factor']}\n")
    for lbl in ('FC-cruise', 'K-out-of-envelope'):
        sub = [t2 for t2 in nasty2 if t2[0] == lbl]
        if sub:
            wc = max(sub, key=lambda z: z[4])
            f.write(f"Tier-2 {lbl:<12s} worst sigma(S_o) = {wc[4]:.4f}  "
                    f"[stability-only waiver]\n")
    f.write(f"Tier-2 worst incl. waived        = {tier2_all_worst:.4f}\n\n")
    f.write("[cross-validation vs 15-state truth model]\n")
    f.write(f"stable at nominal    = {t_stable}\n")
    f.write(f"||S_o|| truth/design = {So_t_norm:.4f} / "
            f"{So_d_norm:.4f} ({100*rel:.1f} % apart)\n\n")
    f.write("[discretization]\n")
    f.write(f"Ts                   = {TS*1e3:.1f} ms ({1/TS:.0f} Hz, single rate)\n")
    f.write(f"modal transform cond = {cond_T:.4e}\n")
    f.write(f"modal-vs-Tustin dev  = {mdev:.3e}\n")
    f.write(f"nominal discrete |z| = {rho_nom:.6f}\n")
    f.write(f"Tier-1 discrete worst|z| = {rho_worst:.6f} ({d_unstable} unstable of {n_d})\n\n")
    f.write("[implementation]\n")
    f.write(f"float32 replay error = {replay_err:.3e} (gate 5e-4, N = {REF_N})\n")
    f.write(f"saturated ref steps  = {n_sat}\n")
    f.write(f"cond(Du^-1) (AW map) = {cond(Dui):.4f}\n")
    f.write(f"AW rail recovery     = {rec_idx} ticks ({rec_idx*TS*1e3:.1f} ms)\n")
    f.write(f"MAC/tick             = {mac_total} ({mac_total/TS:.0f} MAC/s @ {1/TS:.0f} Hz)\n")
    f.write(f"shipped SISO share   = {mac_shipped} MAC/tick ({mac_shipped*1000:.0f} MAC/s @ 1 kHz)\n")
    f.write(f"coefficients / state = {n_coeff} floats ({mem_bytes} B) / {state_bytes} B\n")
    f.write(f"core issue fraction  = {100*cpu_frac:.5f} %\n\n")
    f.write("[diagonal-plant sanity, dV0 = 0]\n")
    f.write(f"SISO gammas          = share {g1:.5f}, drive {g2:.5f}\n")
    f.write(f"MIMO gamma (diag)    = {g_mimo_diag:.5f} ({100*dev:.2f} % vs max SISO)\n\n")
    f.write("[gate table]\n")
    for name, ok, detail in _GATES:
        tag = "PASS" if ok else ("FAIL" if ok is False else "info")
        f.write(f"  {tag}  {name}" + (f"   ({detail})" if detail else "") + "\n")
print(f"  wrote {os.path.relpath(met_path, HERE)}")


# ─────────────────────────────────────────────────────────────────────────────
hdr("SUMMARY")
npass = sum(1 for _, ok, _ in _GATES if ok is True)
nfail = len(_FAILS)
ninfo = sum(1 for _, ok, _ in _GATES if ok is None)
print(f"{npass} gates passed, {nfail} failed, {ninfo} informational")
if _FAILS:
    for n_ in _FAILS:
        print("  FAILED:", n_)
    sys.exit(1)
print("ALL GATES PASSED")
