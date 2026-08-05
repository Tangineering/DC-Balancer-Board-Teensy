#!/usr/bin/env python
"""compare_controllers.py — Phase 5 comparison harness (controller_design_MIMO/).

Evaluates the CENTRALIZED 2x2 MIMO H-inf/Youla-H controller against the
DECENTRALIZED baseline K_dec = blkdiag(shipped share Youla-H, Phase-3 SISO drive
Youla-H) on the SAME coupled 2x2 plants, the SAME corner sets and the SAME sims.

Every number quoted in mimo_comparison.md is emitted here into
comparison_metrics.txt (the Phase-5 gate) and/or figures/*.csv.

Run:  ctrl-venv/Scripts/python.exe compare_controllers.py

Design notes / deliberate choices (all repeated in mimo_comparison.md):

  * Both controllers are rebuilt from their EMITTED float32 headers
    (mimo_controller_coeffs.h, drive_siso_coeffs.h) plus the deterministic
    shipped-share pipeline in shipped_share.py.  The synthesis scripts are not
    importable (no __main__ guard: importing them would re-run synthesis and
    rewrite artefacts), and rebuilding from the headers additionally VALIDATES
    the emitted artefacts.  Cost: the MIMO controller carries float32 coefficient
    truncation (~1e-7 relative) into the frequency-domain metrics.  Irrelevant at
    the reported precision; stated for honesty.
  * Continuous-time metrics use inverse-Tustin (exact bilinear inverse) of the
    discrete remainders + the analytic KI/s integrator, so both controllers are
    compared as continuous physical-coordinate 2x2 systems
    K: e=[dalpha_err; dv_err]  ->  u=[dr; di_cmd].
  * Discrete/time-domain metrics run at NATIVE rates in a multirate simulator
    (base step 0.1 ms): share 1 kHz, drive 500 Hz, MIMO 500 Hz.  A 500 Hz-share
    K_dec variant is also run so the rate difference is not a confound
    (plan §5, last bullet).
  * All signals are SMALL-SIGNAL DEVIATIONS about the operating point.  Step
    amplitudes are stated in every sim and in the results doc; the drive channel
    is actuator-limited above e_sat = I_MOT_MAX / (LF gain of the drive
    controller's non-integral branch), which is a property of the PLANT/actuator,
    not of either controller.  At the 2026-08-04 recalibrated clamp of +-20 A
    (was +-5 A) e_sat = 54.4 mm/s (was 13.6 mm/s), so the step amplitudes below
    are DELIBERATELY UNCHANGED for old-vs-new comparability even though their
    saturation character changes: the 0.05 m/s "small-signal" step is now
    genuinely linear and the 2 m/s "large" step rails for less of the event.
    Rail fractions are emitted for every transient so the change is visible.
    I_MOT_MAX is parsed from the emitted headers, never hard-coded.
"""

import os
import re
import sys
import time

import numpy as np
from numpy.linalg import eigvals, inv, cond
from scipy.linalg import block_diag

from hinf_mimo import (SS, ss_series, ss_parallel, ss_scale, ss_lmul, ss_rmul,
                       blkdiag_ss, sv, rga, hinf_norm, c2d_zoh, c2d_tustin,
                       tf2ss)
import plant_mimo as PM
import full_model_mimo as FM
from shipped_share import shipped_share_controller

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figures")
os.makedirs(FIGDIR, exist_ok=True)

np.set_printoptions(precision=5, suppress=True, linewidth=150)

# ---- constants shared with the synthesis scripts (single source: their headers)
TS_MIMO = 2.0e-3            # 500 Hz
TS_DRIVE = 2.0e-3           # 500 Hz (VESC UART frame floor)
TS_SHARE = 1.0e-3           # 1 kHz  (shipped share loop native rate)
TS_SHARE_SLOW = 2.0e-3      # 500 Hz variant, for the rate-confound isolation
BASE_DT = 1.0e-4            # multirate simulator base step
R_MIN, R_MAX = 0.15, 0.85
# I_MOT_MAX is NOT hard-coded here: it is parsed from drive_siso_coeffs.h
# (DRIVE_CTRL_I_MAX) below, right after that header is read, and cross-checked
# against mimo_controller_coeffs.h MIMO_CTRL_U_MAX[1].  Single source of truth =
# the emitted headers, so a re-synthesis at a different clamp propagates here
# automatically (2026-08-04: +-5 A -> +-20 A recalibration).

_METRICS = []
_PROBLEMS = []


def emit(key, value, comment=""):
    """Record a number for comparison_metrics.txt.  EVERY table cell in
    mimo_comparison.md must come from one of these."""
    _METRICS.append((key, value, comment))
    return value


def problem(msg):
    _PROBLEMS.append(msg)
    print("  [RESULT-OF-NOTE] " + msg)


def hdr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# ═════════════════════════════════════════════════════════════════════════════
# 1. Rebuild both controllers
# ═════════════════════════════════════════════════════════════════════════════

def d2c_tustin(sysd, Ts):
    """Exact inverse of hinf_mimo.c2d_tustin.

        Ad = M(I + A Ts/2), M = (I - A Ts/2)^-1  =>  M = (Ad + I)/2
        A  = 2 (Ad+I)^-1 (Ad-I)/Ts ; B = 2 (Ad+I)^-1 Bd/Ts
        C  = 2 Cd (Ad+I)^-1        ; D = Dd - (Ts/2) Cd B
    """
    I = np.eye(sysd.A.shape[0])
    Mi = inv(sysd.A + I)
    A = 2.0 / Ts * (Mi @ (sysd.A - I))
    B = 2.0 / Ts * (Mi @ sysd.B)
    C = 2.0 * (sysd.C @ Mi)
    D = sysd.D - (Ts / 2.0) * (sysd.C @ B)
    return SS(A, B, C, D)


def _parse_c_array(text, name):
    """Pull a (possibly multi-dimensional) static float array out of a header."""
    m = re.search(re.escape(name) + r"[^=]*=\s*\{(.*?)\};", text, re.S)
    if not m:
        raise RuntimeError(f"could not parse {name}")
    body = m.group(1)
    rows = re.findall(r"\{([^{}]*)\}", body)
    if rows:
        return np.array([[float(x.strip().rstrip("f"))
                          for x in r.split(",") if x.strip()] for r in rows])
    return np.array([float(x.strip().rstrip("f"))
                     for x in body.split(",") if x.strip()])


def _parse_c_scalar(text, name):
    m = re.search(re.escape(name) + r"\s*=\s*([-\d.eE+]+)f", text)
    if not m:
        raise RuntimeError(f"could not parse scalar {name}")
    return float(m.group(1))


# ---- MIMO controller (from mimo_controller_coeffs.h) ------------------------
with open(os.path.join(HERE, "mimo_controller_coeffs.h"), encoding="utf-8") as f:
    _MH = f.read()

M_A = _parse_c_array(_MH, "MIMO_CTRL_A")
M_B = _parse_c_array(_MH, "MIMO_CTRL_B")
M_C = _parse_c_array(_MH, "MIMO_CTRL_C")
M_D = _parse_c_array(_MH, "MIMO_CTRL_D")
M_KI = _parse_c_array(_MH, "MIMO_CTRL_KI")
M_DE = np.diag(_parse_c_array(_MH, "MIMO_CTRL_DE"))
M_DU = np.diag(_parse_c_array(_MH, "MIMO_CTRL_DU"))
M_U0 = _parse_c_array(_MH, "MIMO_CTRL_U0")
M_UMIN = _parse_c_array(_MH, "MIMO_CTRL_U_MIN")
M_UMAX = _parse_c_array(_MH, "MIMO_CTRL_U_MAX")
M_XIMIN = _parse_c_array(_MH, "MIMO_CTRL_XI_MIN")
M_XIMAX = _parse_c_array(_MH, "MIMO_CTRL_XI_MAX")
M_DUI = inv(M_DU)
M_DEI = inv(M_DE)

Gremd_mimo = SS(M_A, M_B, M_C, M_D)                    # discrete (Tustin @ 2 ms)
Grem_mimo_c = d2c_tustin(Gremd_mimo, TS_MIMO)          # continuous remainder
_Int2 = SS(np.zeros((2, 2)), np.eye(2), M_KI, np.zeros((2, 2)))
K_mimo_scaled_c = ss_parallel(_Int2, Grem_mimo_c)      # KI/s + Grem(s), scaled
K_mimo_c = ss_lmul(M_DU, ss_rmul(K_mimo_scaled_c, M_DEI))   # PHYSICAL 2x2

# ---- shipped share half (deterministic re-derivation) -----------------------
_SH = shipped_share_controller()
SHARE_kI = _SH["kI"]
Share_rem_c = _SH["Gs_red"]                            # continuous remainder
Share_c = _SH["Gc_red"]                                # kI/s + remainder (cont.)
Share_remd_1k = _SH["Gsd"]                             # Tustin @ 1 ms (shipped)
Share_remd_500 = c2d_tustin(Share_rem_c, TS_SHARE_SLOW)   # 500 Hz variant

# ---- Phase-3 drive half (from drive_siso_coeffs.h) --------------------------
with open(os.path.join(HERE, "drive_siso_coeffs.h"), encoding="utf-8") as f:
    _DH = f.read()
DRIVE_kI = _parse_c_scalar(_DH, "DRIVE_CTRL_KI")
DRIVE_SOS = _parse_c_array(_DH, "DRIVE_CTRL_SOS")

# motor-current clamp: single source of truth = the emitted headers.
I_MOT_MAX = _parse_c_scalar(_DH, "DRIVE_CTRL_I_MAX")
_I_MOT_MIN = _parse_c_scalar(_DH, "DRIVE_CTRL_I_MIN")
assert abs(_I_MOT_MIN + I_MOT_MAX) < 1e-9, "asymmetric drive clamp not supported"
assert abs(M_UMAX[1] - I_MOT_MAX) < 1e-9 and abs(M_UMIN[1] + I_MOT_MAX) < 1e-9, (
    f"clamp mismatch: drive header +-{I_MOT_MAX} A vs MIMO header "
    f"[{M_UMIN[1]}, {M_UMAX[1]}] A — the two controllers must be compared at "
    "the SAME actuator limit")


def sos_to_ssd(sos):
    """DF2T biquad cascade -> discrete SS.  Mirrors the firmware inner loop:
        y = b0*x + s0 ; s0' = b1*x - a1*y + s1 ; s1' = b2*x - a2*y
    => A=[[-a1,1],[-a2,0]], B=[[b1-a1*b0],[b2-a2*b0]], C=[[1,0]], D=[[b0]]."""
    g = None
    for b0, b1, b2, a1, a2 in sos:
        s = SS([[-a1, 1.0], [-a2, 0.0]],
               [[b1 - a1 * b0], [b2 - a2 * b0]], [[1.0, 0.0]], [[b0]])
        g = s if g is None else ss_series(g, s)
    return g


Drive_remd = sos_to_ssd(DRIVE_SOS)                             # discrete @ 2 ms
Drive_rem_c = d2c_tustin(Drive_remd, TS_DRIVE)                 # continuous
Drive_c = ss_parallel(SS([[0.0]], [[1.0]], [[DRIVE_kI]], [[0.0]]), Drive_rem_c)

# full discrete drive controller (remainder + Tustin integrator), for Hanus AW
_IntD = SS([[1.0]], [[TS_DRIVE * DRIVE_kI]], [[1.0]], [[DRIVE_kI * TS_DRIVE / 2.0]])
Drive_d_full = ss_parallel(Drive_remd, _IntD)

# ---- the decentralized controller, PHYSICAL 2x2 -----------------------------
K_dec_c = blkdiag_ss(Share_c, Drive_c)

hdr("1. CONTROLLERS REBUILT")
print(f"  MIMO   : {K_mimo_c.n} states (2 integrator + {Grem_mimo_c.n} remainder), "
      f"Ts = {TS_MIMO*1e3:.0f} ms")
print(f"  K_dec  : {K_dec_c.n} states  = share {Share_c.n} (Ts = {TS_SHARE*1e3:.0f} ms) "
      f"+ drive {Drive_c.n} (Ts = {TS_DRIVE*1e3:.0f} ms)")
emit("ctrl.mimo.n_states_continuous", K_mimo_c.n,
     f"2 integrator + {Grem_mimo_c.n} modal remainder")
emit("ctrl.dec.n_states_continuous", K_dec_c.n, "share + drive, block diagonal")
emit("ctrl.dec.share.n_states", Share_c.n, "shipped Youla-H share controller")
emit("ctrl.dec.drive.n_states", Drive_c.n, "Phase-3 Youla-H drive controller")
emit("ctrl.dec.share.kI", SHARE_kI, "shipped share integrator residue")
emit("ctrl.dec.drive.kI", DRIVE_kI, "drive integrator residue, A per (m/s)/s")

# sanity: the rebuilt drive Dd must match the value printed in the header banner
_Dd_hdr = float(re.search(r"Dd = ([-\d.eE+]+)\)", _DH).group(1))
_Dd_reb = float(Drive_d_full.D[0, 0])
emit("check.drive.Dd_header_vs_rebuilt", abs(_Dd_reb - _Dd_hdr),
     f"rebuilt {_Dd_reb:.9f} vs header {_Dd_hdr:.9f}")
assert abs(_Dd_reb - _Dd_hdr) < 1e-6, "drive header rebuild mismatch"

# sanity: MIMO controller off-diagonal weight (Phase-4, +-20 A round: K12/K11 ~ 2 %)
_wq = np.logspace(-2, 4, 1200)
_Kfr = K_mimo_scaled_c.freqresp_matrix(_wq)
_k12_ratio = float(np.max(np.abs(_Kfr[:, 0, 1])) / np.max(np.abs(_Kfr[:, 0, 0])))
emit("ctrl.mimo.K12_over_K11_peak_scaled", _k12_ratio,
     "off-diagonal (drive-error -> droop) authority, scaled coords")
_k21_ratio = float(np.max(np.abs(_Kfr[:, 1, 0])) / np.max(np.abs(_Kfr[:, 1, 1])))
emit("ctrl.mimo.K21_over_K22_peak_scaled", _k21_ratio,
     "off-diagonal (share-error -> motor current) authority, scaled coords")
print(f"  MIMO off-diagonal authority: |K12|/|K11| = {100*_k12_ratio:.2f} %, "
      f"|K21|/|K22| = {100*_k21_ratio:.2f} %")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Closed-loop assembly helpers (identical for both controllers)
# ═════════════════════════════════════════════════════════════════════════════

def loop_matrices(G, K):
    """COPIED from synthesize_mimo_controller.py:86 — identical closed-loop
    assembly for both controllers is the whole point of this harness.
    y = G u, u = K(w - y), G strictly proper.  Returns (Acl, S_o)."""
    Ag, Bg, Cg = G.A, G.B, G.C
    Ak, Bk, Ck, Dk = K.A, K.B, K.C, K.D
    Acl = np.block([[Ag - Bg @ Dk @ Cg, Bg @ Ck],
                    [-Bk @ Cg, Ak]])
    Bcl = np.vstack([Bg @ Dk, Bk])
    Ccl = np.hstack([-Cg, np.zeros((Cg.shape[0], Ak.shape[0]))])
    return Acl, SS(Acl, Bcl, Ccl, np.eye(Cg.shape[0]))


def comp_sens(G, K):
    """T = GK(I+GK)^-1 : reference -> output."""
    Acl, So = loop_matrices(G, K)
    Cg = G.C
    Ccl = np.hstack([Cg, np.zeros((Cg.shape[0], K.A.shape[0]))])
    return SS(Acl, So.B, Ccl, np.zeros((Cg.shape[0], Cg.shape[0])))


_W_SWEEP = np.logspace(-3, 6, 2000)


def hnorm(sys):
    """COPIED from synthesize_mimo_controller.py:135 (dense-sweep fallback)."""
    v = hinf_norm(sys)
    if np.isfinite(v):
        return v, False
    return float(np.max(sv(sys, _W_SWEEP))), True


CTRLS = [("dec", K_dec_c), ("mimo", K_mimo_c)]


# ═════════════════════════════════════════════════════════════════════════════
# 3. Metric 1 — coupling quantification (plant only)
# ═════════════════════════════════════════════════════════════════════════════
hdr("2. METRIC 1 — COUPLING QUANTIFICATION (plant only)")

p0 = PM.nominal_params()
op0 = PM.nominal_op()
W_C = np.logspace(-2, 5, 700)
# IN-BAND window for the condition number.  cond(Gs(jw)) -> inf as w -> inf for
# ANY strictly-proper plant whose two channels roll off at different orders (here
# 3rd/4th order share vs 4th/5th order drive), so the full-sweep maximum measures
# roll-off asymmetry, not coupling.  The control-relevant window is DC up to just
# past the faster loop's crossover (~110 rad/s share, ~21 rad/s drive).
W_INBAND = W_C <= 200.0

COUPLING_CASES = [
    ("nominal", dict(op0)),
    ("light_load_0p5A", dict(op0, I_tot0=0.5)),
    ("fc_cruise_r0p85", dict(op0, I_tot0=2.0, r0=0.85)),
]

coup_cols = {"w_rad_s": W_C}
for name, op in COUPLING_CASES:
    Gs = PM.scaled_plant(op=op, params=p0)
    Fr = Gs.freqresp_matrix(W_C)
    ratio = np.abs(Fr[:, 0, 1]) / np.maximum(np.abs(Fr[:, 0, 0]), 1e-300)
    svs = np.array([np.linalg.svd(Fr[i], compute_uv=False) for i in range(len(W_C))])
    cnd = svs[:, 0] / np.maximum(svs[:, -1], 1e-300)
    coup_cols[f"ratio12_{name}"] = ratio
    coup_cols[f"cond_{name}"] = cnd
    coup_cols[f"sigmax_{name}"] = svs[:, 0]
    coup_cols[f"sigmin_{name}"] = svs[:, -1]
    emit(f"coupling.{name}.max_G12_over_G11", float(np.max(ratio)),
         "peak scaled coupling-to-direct magnitude ratio over 1e-2..1e5 rad/s")
    emit(f"coupling.{name}.G12_over_G11_at_dc", float(ratio[0]), "w = 0.01 rad/s")
    emit(f"coupling.{name}.max_cond_Gs_inband", float(np.max(cnd[W_INBAND])),
         "peak condition number of the scaled 2x2 plant, DC..200 rad/s")
    emit(f"coupling.{name}.cond_Gs_at_dc", float(cnd[0]), "w = 0.01 rad/s")
    emit(f"coupling.{name}.max_cond_Gs_full_sweep", float(np.max(cnd)),
         "DC..1e5 rad/s; dominated by unequal channel roll-off, NOT by coupling")
    emit(f"coupling.{name}.dalpha_dItot", PM.dalpha_dItot(op, p0),
         "static share-per-amp coupling gain at this OP")
    print(f"  {name:18s} max|G12/G11| = {np.max(ratio):.4f}   "
          f"cond(Gs) in-band = {np.max(cnd[W_INBAND]):.4f} (DC {cnd[0]:.4f})   "
          f"dalpha/dItot = {PM.dalpha_dItot(op, p0):+.5f}")

# RGA at DC and at the share crossover — the design plant is upper-triangular,
# so RGA must be exactly I at every frequency; report the departure as a number.
_rga_dev = 0.0
for name, op in COUPLING_CASES:
    G = PM.design_plant(op, p0)
    for wq in (1e-3, 110.0):
        M = G.freqresp_matrix(np.array([wq]))[0]
        _rga_dev = max(_rga_dev, float(np.max(np.abs(rga(M) - np.eye(2)))))
emit("coupling.max_RGA_departure_from_I", _rga_dev,
     "design plant is structurally upper-triangular (G21 == 0) => RGA == I exactly")
print(f"  max |RGA - I| over all cases/frequencies = {_rga_dev:.2e}")

# ---- dalpha_dItot table over the OP grid at dV0 = +-0.4 ---------------------
dad_rows = []
for op in PM.op_grid():
    for dV0 in (-0.4, 0.0, +0.4):
        o = dict(op, dV0=dV0)
        feas = PM.op_feasible(o, p0)
        dad_rows.append((o['I_tot0'], o['r0'], dV0, PM.dalpha_dItot(o, p0),
                         PM.share_gain_K(o, p0), PM.op_alpha0(o, p0), int(feas)))
with open(os.path.join(FIGDIR, "coupling_dalpha_dItot.csv"), "w", encoding="utf-8") as f:
    f.write("I_tot0_A,r0,dV0_V,dalpha_dItot_per_A,K_share,alpha0,feasible\n")
    for r in dad_rows:
        f.write(f"{r[0]},{r[1]},{r[2]},{r[3]:.8e},{r[4]:.6f},{r[5]:.6f},{r[6]}\n")
_feas_rows = [r for r in dad_rows if r[6]]
emit("coupling.dalpha_dItot.max_abs_feasible",
     float(max(abs(r[3]) for r in _feas_rows)),
     "largest |dalpha/dItot| over the feasible OP x dV0 grid")
emit("coupling.dalpha_dItot.n_feasible", len(_feas_rows), f"of {len(dad_rows)} grid points")
_wc = max(_feas_rows, key=lambda r: abs(r[3]))
emit("coupling.dalpha_dItot.argmax_I_tot0", _wc[0], "")
emit("coupling.dalpha_dItot.argmax_r0", _wc[1], "")
emit("coupling.dalpha_dItot.argmax_dV0", _wc[2], "")

# ---- cond(Gs) over the whole feasible OP x dV0 grid (Phase-1 reported 5.11) --
cond_rows = []
for op in PM.op_grid():
    for dV0 in (-0.4, 0.0, +0.2, +0.4):
        o = dict(op, dV0=dV0)
        if not PM.op_feasible(o, p0):
            continue
        Fr = PM.scaled_plant(op=o, params=p0).freqresp_matrix(W_C)
        svs = np.array([np.linalg.svd(Fr[i], compute_uv=False) for i in range(len(W_C))])
        cnd = svs[:, 0] / np.maximum(svs[:, -1], 1e-300)
        cmax = float(np.max(cnd[W_INBAND]))
        rmax = float(np.max(np.abs(Fr[:, 0, 1]) / np.maximum(np.abs(Fr[:, 0, 0]), 1e-300)))
        cond_rows.append((o['I_tot0'], o['r0'], dV0, cmax, rmax, float(cnd[0])))
with open(os.path.join(FIGDIR, "coupling_cond_grid.csv"), "w", encoding="utf-8") as f:
    f.write("I_tot0_A,r0,dV0_V,max_cond_Gs_inband,max_G12_over_G11,cond_Gs_dc\n")
    for r in cond_rows:
        f.write(f"{r[0]},{r[1]},{r[2]},{r[3]:.6f},{r[4]:.6f},{r[5]:.6f}\n")
_cw = max(cond_rows, key=lambda r: r[3])
emit("coupling.grid.max_cond_Gs_inband", _cw[3],
     f"DC..200 rad/s, at I_tot0={_cw[0]} A, r0={_cw[1]}, dV0={_cw[2]} V")
emit("coupling.grid.max_cond_Gs_at_dc", max(r[5] for r in cond_rows),
     "worst DC condition number over the feasible OP x dV0 grid")
emit("coupling.grid.max_cond_I_tot0", _cw[0], "")
emit("coupling.grid.max_cond_r0", _cw[1], "")
emit("coupling.grid.max_cond_dV0", _cw[2], "")
_rw = max(cond_rows, key=lambda r: r[4])
emit("coupling.grid.max_G12_over_G11", _rw[4],
     f"at I_tot0={_rw[0]} A, r0={_rw[1]}, dV0={_rw[2]} V")
print(f"  OP-grid worst in-band cond(Gs) = {_cw[3]:.4f} at I_tot0={_cw[0]} A, r0={_cw[1]}, "
      f"dV0={_cw[2]} V   ({len(cond_rows)} feasible grid points)")

with open(os.path.join(FIGDIR, "coupling_freq.csv"), "w", encoding="utf-8") as f:
    keys = list(coup_cols.keys())
    f.write(",".join(keys) + "\n")
    for i in range(len(W_C)):
        f.write(",".join(f"{coup_cols[k][i]:.8e}" for k in keys) + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# 4. Metric 2 — worst-corner sigma(S_o) on the identical Tier-2 rep set
# ═════════════════════════════════════════════════════════════════════════════
hdr("3. METRIC 2 — TIER-2 PERFORMANCE (identical rep set, both controllers)")

# COPIED VERBATIM from synthesize_mimo_controller.py:549-596 so the two
# controllers are judged on exactly the same corners with exactly the same
# waiver policy.  See that file (and mimo_synthesis.md) for the physical
# justification of the two waived families.
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
K_ENVELOPE = (0.55, 1.45)


def is_nasty(o, p=None):
    """COPIED from synthesize_mimo_controller.py:589."""
    p = p0 if p is None else p
    if abs(o['r0'] - 0.85) < 1e-9:
        return 'FC-cruise'
    Kc = PM.share_gain_K(o, p)
    if not (K_ENVELOPE[0] <= Kc <= K_ENVELOPE[1]):
        return 'K-out-of-envelope'
    return None


W_S = np.logspace(-2, 5, 500)

t0 = time.time()
tier2 = []          # dicts, one per corner, holding BOTH controllers' numbers
for op in PM.op_grid():
    for sc in SHARE_REPS:
        o_probe = dict(op, dV0=sc['dV0'])
        if not PM.op_feasible(o_probe, p0):
            continue
        for dc in DRIVE_REPS:
            G, o_, p_ = PM.corner_plant(op, sc, dc)
            row = dict(label=is_nasty(o_), op=o_, sc=sc, dc=dc)
            for nm, K in CTRLS:
                Acl, So = loop_matrices(G, K)
                if np.max(eigvals(Acl).real) >= 0:
                    row[nm] = dict(So=np.inf, S11=np.inf, S22=np.inf, Tav=np.inf,
                                   stable=False)
                    continue
                Sfr = So.freqresp_matrix(W_S)
                T = comp_sens(G, K)
                Tfr = T.freqresp_matrix(W_S)
                row[nm] = dict(So=hnorm(So)[0],
                               S11=float(np.max(np.abs(Sfr[:, 0, 0]))),
                               S22=float(np.max(np.abs(Sfr[:, 1, 1]))),
                               Tav=float(np.max(np.abs(Tfr[:, 0, 1]))),
                               stable=True)
            tier2.append(row)
print(f"  {len(tier2)} Tier-2 corners x 2 controllers in {time.time()-t0:.1f} s")
emit("tier2.n_corners", len(tier2), "identical rep set for both controllers")

main2 = [t for t in tier2 if t['label'] is None]
emit("tier2.n_corners_in_envelope", len(main2), "non-waived corners")

for nm, _ in CTRLS:
    unst = [t for t in tier2 if not t[nm]['stable']]
    emit(f"tier2.{nm}.n_unstable", len(unst), "of the Tier-2 rep set")
    if unst:
        problem(f"{nm}: {len(unst)} Tier-2 corners CONTINUOUS-UNSTABLE")
    wm = max(main2, key=lambda t: t[nm]['So'])
    emit(f"tier2.{nm}.worst_sigma_So_in_envelope", wm[nm]['So'],
         f"I_tot0={wm['op']['I_tot0']} A, r0={wm['op']['r0']}, dV0={wm['op']['dV0']} V")
    emit(f"tier2.{nm}.worst_sigma_So_all_corners",
         max(t[nm]['So'] for t in tier2), "including waived corners")
    emit(f"tier2.{nm}.worst_S11_peak_in_envelope",
         max(t[nm]['S11'] for t in main2), "share-channel |S11| peak")
    emit(f"tier2.{nm}.worst_S22_peak_in_envelope",
         max(t[nm]['S22'] for t in main2), "drive-channel |S22| peak")
    wt = max(main2, key=lambda t: t[nm]['Tav'])
    emit(f"tier2.{nm}.worst_T_alpha_from_vref_in_envelope", wt[nm]['Tav'],
         "peak |T(alpha <- v_ref)|, share per (m/s) — THE cross-coupling metric; "
         f"I_tot0={wt['op']['I_tot0']} A, r0={wt['op']['r0']}, dV0={wt['op']['dV0']} V")
    emit(f"tier2.{nm}.worst_T_alpha_from_vref_all_corners",
         max(t[nm]['Tav'] for t in tier2), "including waived corners")
    for lbl in ('FC-cruise', 'K-out-of-envelope'):
        sub = [t for t in tier2 if t['label'] == lbl]
        if sub:
            emit(f"tier2.{nm}.waived_{lbl.replace('-','_')}_worst_sigma_So",
                 max(t[nm]['So'] for t in sub), f"{len(sub)} waived corners")
    print(f"  {nm:5s}: worst sigma(S_o) in-envelope = {wm[nm]['So']:.4f} | "
          f"|S11| {max(t[nm]['S11'] for t in main2):.4f} | "
          f"|S22| {max(t[nm]['S22'] for t in main2):.4f} | "
          f"|T_a<-vref| {wt[nm]['Tav']:.4e}")

# nominal-point numbers (both controllers)
G_nom = PM.design_plant(op0, p0)
nom_fr = {}
for nm, K in CTRLS:
    Acl, So = loop_matrices(G_nom, K)
    T = comp_sens(G_nom, K)
    Sfr = So.freqresp_matrix(W_S)
    Tfr = T.freqresp_matrix(W_S)
    svS = np.array([np.linalg.svd(Sfr[i], compute_uv=False) for i in range(len(W_S))])
    nom_fr[nm] = dict(svmax=svS[:, 0], S11=np.abs(Sfr[:, 0, 0]),
                      S22=np.abs(Sfr[:, 1, 1]), Tav=np.abs(Tfr[:, 0, 1]))
    emit(f"nominal.{nm}.sigma_So_peak", hnorm(So)[0], "nominal design plant")
    emit(f"nominal.{nm}.S11_peak", float(np.max(np.abs(Sfr[:, 0, 0]))), "")
    emit(f"nominal.{nm}.S22_peak", float(np.max(np.abs(Sfr[:, 1, 1]))), "")
    emit(f"nominal.{nm}.T_alpha_from_vref_peak", float(np.max(np.abs(Tfr[:, 0, 1]))),
         "share per (m/s) of speed reference")
    emit(f"nominal.{nm}.max_real_cl_pole", float(np.max(eigvals(Acl).real)), "")
    print(f"  nominal {nm:5s}: sigma(S_o) = {hnorm(So)[0]:.4f}, "
          f"|T_a<-vref| = {np.max(np.abs(Tfr[:, 0, 1])):.4e}")

with open(os.path.join(FIGDIR, "sigma_nominal_both.csv"), "w", encoding="utf-8") as f:
    f.write("w_rad_s,dec_sigma_So,mimo_sigma_So,dec_S11,mimo_S11,dec_S22,mimo_S22,"
            "dec_T_alpha_vref,mimo_T_alpha_vref\n")
    for i, w in enumerate(W_S):
        f.write(f"{w:.8e},{nom_fr['dec']['svmax'][i]:.8e},{nom_fr['mimo']['svmax'][i]:.8e},"
                f"{nom_fr['dec']['S11'][i]:.8e},{nom_fr['mimo']['S11'][i]:.8e},"
                f"{nom_fr['dec']['S22'][i]:.8e},{nom_fr['mimo']['S22'][i]:.8e},"
                f"{nom_fr['dec']['Tav'][i]:.8e},{nom_fr['mimo']['Tav'][i]:.8e}\n")

# worst in-envelope corner (per controller, plus the shared worst-for-MIMO corner)
worst_corner_mimo = max(main2, key=lambda t: t['mimo']['So'])
Gw, _, _ = PM.corner_plant(dict(worst_corner_mimo['op']), worst_corner_mimo['sc'],
                           worst_corner_mimo['dc'])
with open(os.path.join(FIGDIR, "sigma_worst_corner_both.csv"), "w", encoding="utf-8") as f:
    f.write("# worst in-envelope corner for the MIMO controller: "
            f"I_tot0={worst_corner_mimo['op']['I_tot0']} r0={worst_corner_mimo['op']['r0']} "
            f"dV0={worst_corner_mimo['op']['dV0']} share={worst_corner_mimo['sc']} "
            f"drive={worst_corner_mimo['dc']}\n")
    f.write("w_rad_s,dec_sigma_So,mimo_sigma_So\n")
    cols = {}
    for nm, K in CTRLS:
        _, So = loop_matrices(Gw, K)
        Sfr = So.freqresp_matrix(W_S)
        cols[nm] = np.array([np.linalg.svd(Sfr[i], compute_uv=False)[0]
                             for i in range(len(W_S))])
    for i, w in enumerate(W_S):
        f.write(f"{w:.8e},{cols['dec'][i]:.8e},{cols['mimo'][i]:.8e}\n")

with open(os.path.join(FIGDIR, "tier2_corner_scatter.csv"), "w", encoding="utf-8") as f:
    f.write("label,I_tot0_A,r0,dV0_V,Td_s,taur_s,tauf_s,K_v,pole_factor,tau_v_s,Td_v_s,"
            "dec_sigma_So,mimo_sigma_So,dec_S11,mimo_S11,dec_S22,mimo_S22,"
            "dec_T_alpha_vref,mimo_T_alpha_vref\n")
    for t in tier2:
        f.write(f"{t['label'] or 'in-envelope'},{t['op']['I_tot0']},{t['op']['r0']},"
                f"{t['op']['dV0']},{t['sc']['Td']},{t['sc']['taur']},{t['sc']['tauf']},"
                f"{t['dc']['K_v']},{t['dc']['pole_factor']},{t['dc']['tau_v']},"
                f"{t['dc']['Td_v']},"
                f"{t['dec']['So']:.6f},{t['mimo']['So']:.6f},"
                f"{t['dec']['S11']:.6f},{t['mimo']['S11']:.6f},"
                f"{t['dec']['S22']:.6f},{t['mimo']['S22']:.6f},"
                f"{t['dec']['Tav']:.8e},{t['mimo']['Tav']:.8e}\n")

# head-to-head counts
_better = sum(1 for t in main2 if t['mimo']['So'] < t['dec']['So'])
emit("tier2.mimo_better_sigma_So_count", _better,
     f"of {len(main2)} in-envelope corners where MIMO sigma(S_o) < decentralized")
# Cross-coupling ratio statistics are taken ONLY over corners with dV0 != 0.
# At dV0 = 0 the coupling gain dalpha/dItot is EXACTLY zero, so both controllers'
# |T(alpha<-v_ref)| is zero to machine precision and their ratio is 0/0 noise
# (it produced a 1e299 "worst case" before this restriction).
coupled2 = [t for t in main2 if abs(t['op']['dV0']) > 1e-12]
emit("tier2.n_coupled_corners_in_envelope", len(coupled2),
     f"of {len(main2)} in-envelope corners with dV0 != 0 (nonzero coupling)")
_bettT = sum(1 for t in coupled2 if t['mimo']['Tav'] < t['dec']['Tav'])
emit("tier2.mimo_better_T_alpha_vref_count", _bettT,
     f"of {len(coupled2)} COUPLED in-envelope corners where MIMO "
     "|T(alpha<-v_ref)| is smaller")
_ratios = [t['mimo']['Tav'] / t['dec']['Tav'] for t in coupled2]
emit("tier2.T_alpha_vref_mimo_over_dec_median", float(np.median(_ratios)),
     "median ratio of the cross-coupling transfer peaks (MIMO / decentralized), "
     "coupled corners only")
emit("tier2.T_alpha_vref_mimo_over_dec_best", float(np.min(_ratios)), "")
emit("tier2.T_alpha_vref_mimo_over_dec_worst", float(np.max(_ratios)), "")
# split by the SIGN of dV0: the MIMO feedforward was synthesized at dV0 = +0.2 V,
# so this split IS the sign-uncertainty finding.
for sgn, lbl in ((+1, "dV0_pos"), (-1, "dV0_neg")):
    sub = [t for t in coupled2 if np.sign(t['op']['dV0']) == sgn]
    if sub:
        rr = [t['mimo']['Tav'] / t['dec']['Tav'] for t in sub]
        emit(f"tier2.T_alpha_vref_mimo_over_dec_median_{lbl}", float(np.median(rr)),
             f"{len(sub)} corners; dV0 sign {'MATCHES' if sgn > 0 else 'OPPOSES'} "
             "the +0.2 V synthesis point")


# ═════════════════════════════════════════════════════════════════════════════
# 5. Metric 3 — Tier-1 continuous + discrete corner stability
# ═════════════════════════════════════════════════════════════════════════════
hdr("4. METRIC 3 — TIER-1 CORNER STABILITY (5760 corners, feasible subset)")

# ---- discrete closed loops --------------------------------------------------
# MIMO: single-rate 2 ms (matches its emitted header).
Kd_mimo_A = block_diag(np.eye(2), M_A)
Kd_mimo_B = np.vstack([TS_MIMO * M_KI, M_B]) @ M_DEI
Kd_mimo_C = M_DU @ np.hstack([np.eye(2), M_C])
Kd_mimo_D = M_DU @ ((TS_MIMO / 2.0) * M_KI + M_D) @ M_DEI


def dclosed_rho_mimo(G, Ts=TS_MIMO):
    Gd = c2d_zoh(G, Ts)
    Ag, Bg, Cg = Gd.A, Gd.B, Gd.C
    Ak, Bk, Ck, Dk = Kd_mimo_A, Kd_mimo_B, Kd_mimo_C, Kd_mimo_D
    Acl = np.block([[Ag - Bg @ Dk @ Cg, Bg @ Ck],
                    [-Bk @ Cg, Ak]])
    return float(np.max(np.abs(eigvals(Acl))))


# K_dec: genuinely MULTIRATE (share 1 kHz, drive 500 Hz).  Stability is assessed
# on the 2-step MONODROMY of the 1 ms-lifted loop: two 1 ms plant steps, the
# share controller updating on both, the drive controller updating on the first
# only and its output HELD through the second.  This is exact for the periodic
# multirate loop — not an approximation.
def _share_ssd(Ts):
    rem = Share_remd_1k if abs(Ts - TS_SHARE) < 1e-12 else Share_remd_500
    A = block_diag(np.array([[1.0]]), rem.A)
    B = np.vstack([[[Ts * SHARE_kI]], rem.B])
    C = np.hstack([[[1.0]], rem.C])
    D = np.array([[SHARE_kI * Ts / 2.0]]) + rem.D
    return SS(A, B, C, D)


Share_d_full_1k = _share_ssd(TS_SHARE)
Share_d_full_500 = _share_ssd(TS_SHARE_SLOW)


def dclosed_rho_dec_multirate(G, Ts_base=TS_SHARE):
    """2-step monodromy spectral radius of the multirate decentralized loop."""
    Gd = c2d_zoh(G, Ts_base)
    Ag, Bg, Cg = Gd.A, Gd.B, Gd.C
    ng = Ag.shape[0]
    As, Bs, Cs, Ds = (Share_d_full_1k.A, Share_d_full_1k.B,
                      Share_d_full_1k.C, Share_d_full_1k.D)
    Ad_, Bd_, Cd_, Dd_ = (Drive_d_full.A, Drive_d_full.B,
                          Drive_d_full.C, Drive_d_full.D)
    ns, nd = As.shape[0], Ad_.shape[0]
    n = ng + ns + nd + 1                      # +1 = the held drive output
    ig, isx, idx, iu = (slice(0, ng), slice(ng, ng + ns),
                        slice(ng + ns, ng + ns + nd), ng + ns + nd)
    c0 = Cg[0:1, :]                           # alpha row
    c1 = Cg[1:2, :]                           # v row

    def step(update_drive):
        M = np.zeros((n, n))
        # u1 = Cs xs - Ds c0 xg     (share, updates every base step)
        u1 = np.zeros((1, n)); u1[:, isx] = Cs; u1[:, ig] = -Ds @ c0
        if update_drive:
            u2 = np.zeros((1, n)); u2[:, idx] = Cd_; u2[:, ig] = -Dd_ @ c1
        else:
            u2 = np.zeros((1, n)); u2[0, iu] = 1.0
        M[ig, ig] = Ag
        M[ig, :] += Bg[:, 0:1] @ u1 + Bg[:, 1:2] @ u2
        M[isx, isx] = As
        M[isx, ig] += -Bs @ c0
        if update_drive:
            M[idx, idx] = Ad_
            M[idx, ig] += -Bd_ @ c1
        else:
            M[idx, idx] = np.eye(nd)
        M[iu, :] = u2
        return M

    return float(np.max(np.abs(eigvals(step(False) @ step(True)))))


def dclosed_rho_dec_singlerate(G, Ts=TS_MIMO):
    """K_dec with BOTH halves at 500 Hz (the rate-confound isolation variant)."""
    Kd = blkdiag_ss(Share_d_full_500, Drive_d_full)
    Gd = c2d_zoh(G, Ts)
    Ag, Bg, Cg = Gd.A, Gd.B, Gd.C
    Acl = np.block([[Ag - Bg @ Kd.D @ Cg, Bg @ Kd.C],
                    [-Kd.B @ Cg, Kd.A]])
    return float(np.max(np.abs(eigvals(Acl))))


t0 = time.time()
n_feas = n_skip = 0
res = {nm: dict(c_unst=0, c_worst=-1e9, c_corner=None,
                d_unst=0, d_worst=0.0, d_corner=None) for nm, _ in CTRLS}
res['dec500'] = dict(d_unst=0, d_worst=0.0, d_corner=None)
for op, sc, dc, feas in PM.tier1_corners():
    if not feas:
        n_skip += 1
        continue
    n_feas += 1
    G, o_, p_ = PM.corner_plant(op, sc, dc)
    for nm, K in CTRLS:
        Acl, _ = loop_matrices(G, K)
        mx = float(np.max(eigvals(Acl).real))
        if mx > res[nm]['c_worst']:
            res[nm]['c_worst'], res[nm]['c_corner'] = mx, (o_, sc, dc)
        if mx >= 0.0:
            res[nm]['c_unst'] += 1
    rm = dclosed_rho_mimo(G)
    if rm > res['mimo']['d_worst']:
        res['mimo']['d_worst'], res['mimo']['d_corner'] = rm, (o_, sc, dc)
    if rm >= 1.0:
        res['mimo']['d_unst'] += 1
    rd = dclosed_rho_dec_multirate(G)
    if rd > res['dec']['d_worst']:
        res['dec']['d_worst'], res['dec']['d_corner'] = rd, (o_, sc, dc)
    if rd >= 1.0:
        res['dec']['d_unst'] += 1
    r5 = dclosed_rho_dec_singlerate(G)
    if r5 > res['dec500']['d_worst']:
        res['dec500']['d_worst'], res['dec500']['d_corner'] = r5, (o_, sc, dc)
    if r5 >= 1.0:
        res['dec500']['d_unst'] += 1
print(f"  {n_feas} feasible corners ({n_skip} infeasible skipped) in {time.time()-t0:.1f} s")
emit("tier1.n_feasible", n_feas, "of 5760 (10 OP x 24 share x 24 drive)")
emit("tier1.n_infeasible_skipped", n_skip,
     "alpha0 outside (0.02, 0.98): unidirectional-switch clamped OPs")

for nm in ('dec', 'mimo'):
    r = res[nm]
    emit(f"tier1.{nm}.continuous_unstable_count", r['c_unst'], f"of {n_feas} feasible")
    emit(f"tier1.{nm}.continuous_worst_real_pole", r['c_worst'],
         f"I_tot0={r['c_corner'][0]['I_tot0']} r0={r['c_corner'][0]['r0']} "
         f"dV0={r['c_corner'][0]['dV0']} share={r['c_corner'][1]} drive={r['c_corner'][2]}")
    emit(f"tier1.{nm}.discrete_unstable_count", r['d_unst'], f"of {n_feas} feasible")
    emit(f"tier1.{nm}.discrete_worst_abs_z", r['d_worst'],
         f"I_tot0={r['d_corner'][0]['I_tot0']} r0={r['d_corner'][0]['r0']} "
         f"dV0={r['d_corner'][0]['dV0']} share={r['d_corner'][1]} drive={r['d_corner'][2]}")
    print(f"  {nm:5s}: continuous {r['c_unst']} unstable (worst Re = {r['c_worst']:.4e}); "
          f"discrete {r['d_unst']} unstable (worst |z| = {r['d_worst']:.6f})")
    if r['c_unst'] or r['d_unst']:
        problem(f"{nm}: Tier-1 instabilities — continuous {r['c_unst']}, "
                f"discrete {r['d_unst']} of {n_feas}")
emit("tier1.dec500.discrete_unstable_count", res['dec500']['d_unst'],
     f"of {n_feas} feasible; K_dec with BOTH halves at 500 Hz")
emit("tier1.dec500.discrete_worst_abs_z", res['dec500']['d_worst'], "")
print(f"  dec500: discrete {res['dec500']['d_unst']} unstable "
      f"(worst |z| = {res['dec500']['d_worst']:.6f})")
if res['dec500']['d_unst']:
    problem(f"dec500 (500 Hz share): {res['dec500']['d_unst']} discrete Tier-1 "
            f"instabilities of {n_feas}")


# ═════════════════════════════════════════════════════════════════════════════
# 6. Multirate discrete simulator + controller implementations
# ═════════════════════════════════════════════════════════════════════════════
hdr("5. TIME-DOMAIN SIMS (multirate, base step 0.1 ms)")


class ShareD:
    """Shipped share-controller firmware pattern: stable remainder (DF2T in
    firmware, state-space here — identical LTI) + trapezoidal integrator with
    back-calculation anti-windup ON THE INTEGRATOR ONLY, output clamped to
    [R_MIN, R_MAX] about the operating r0.
    ADAPTED from controller_design/synthesize_controller.py's DiscreteController
    via shipped_share.py; the AW scheme is the SHIPPED one, deliberately."""

    def __init__(self, remd, Ts, r0):
        self.A, self.B, self.C, self.D = remd.A, remd.B, remd.C, remd.D
        self.Ts, self.kI, self.r0 = Ts, SHARE_kI, r0
        self.reset()

    def reset(self):
        self.x = np.zeros(self.A.shape[0])
        self.integ = 0.0
        self.ep = 0.0

    def step(self, e):
        integ = self.integ + self.kI * self.Ts * 0.5 * (e + self.ep)
        us = float((self.C @ self.x)[0]) + float(self.D[0, 0]) * e + integ
        u = self.r0 + us
        usat = min(R_MAX, max(R_MIN, u))
        integ += usat - u                       # back-calculation
        self.x = self.A @ self.x + self.B.ravel() * e
        self.integ, self.ep = integ, e
        return usat


class DriveD:
    """Hanus self-conditioned realization of the Phase-3 drive controller.
    COPIED (structure) from synthesize_drive_siso.py:419 ConditionedController —
    that file documents WHY integrator-only AW is insufficient for this
    controller (the non-integral branch has a 367.7 A/(m/s) LF gain, so the
    biquad states wind up on their own above e_sat = I_MOT_MAX/367.7 of error —
    13.6 mm/s at the old +-5 A clamp, 54.4 mm/s at the 2026-08-04 +-20 A clamp.
    At +-20 A integrator-only AW is clean to ~0.2 m/s steps but still fails the
    0->2 m/s gate, so the Hanus form remains REQUIRED for this baseline)."""

    def __init__(self, cd):
        self.Ad, self.Bd = cd.A, cd.B
        self.Cd, self.Dd = cd.C, float(cd.D[0, 0])
        self.Ac = self.Ad - self.Bd @ self.Cd / self.Dd
        self.reset()

    def reset(self):
        self.x = np.zeros((self.Ad.shape[0], 1))

    def step(self, e):
        uu = float((self.Cd @ self.x).item()) + self.Dd * e
        u = min(I_MOT_MAX, max(-I_MOT_MAX, uu))
        self.x = self.Ac @ self.x + self.Bd * (u / self.Dd)
        return u


class MimoD:
    """COPIED from synthesize_mimo_controller.py:801 MimoController, rebuilt from
    mimo_controller_coeffs.h.  Integrator advanced FIRST, back-calculation on the
    integrator subspace (map Du^-1) plus the authority clamp."""

    def __init__(self, r0=None):
        self.A, self.B, self.C, self.D = M_A, M_B, M_C, M_D
        self.KI, self.Du, self.Dui = M_KI, M_DU, M_DUI
        self.u0 = M_U0.copy() if r0 is None else np.array([r0, 0.0])
        self.umin = np.array([R_MIN, -I_MOT_MAX])
        self.umax = np.array([R_MAX, I_MOT_MAX])
        self.ximin = self.Dui @ (self.umin - self.u0)
        self.ximax = self.Dui @ (self.umax - self.u0)
        self.hTs = TS_MIMO / 2.0
        self.reset()

    def reset(self):
        self.x = np.zeros(self.A.shape[0])
        self.xi = np.zeros(2)
        self.ep = np.zeros(2)

    def step(self, e_s):
        e = np.asarray(e_s, float)
        xi = self.xi + self.hTs * (self.KI @ (e + self.ep))
        us = self.C @ self.x + self.D @ e + xi
        u = self.u0 + self.Du @ us
        usat = np.clip(u, self.umin, self.umax)
        d = usat - u
        if np.any(d != 0):
            xi = xi + self.Dui @ d
        xn = self.A @ self.x + self.B @ e
        self.xi = np.clip(xi, self.ximin, self.ximax)
        self.x = xn
        self.ep = e
        return usat


class DecBundle:
    """K_dec at native (or forced) rates.  Physical absolute output [r, i_cmd]."""
    name = "dec"

    def __init__(self, r0, share_Ts=TS_SHARE):
        self.share = ShareD(Share_remd_1k if abs(share_Ts - TS_SHARE) < 1e-12
                            else Share_remd_500, share_Ts, r0)
        self.drive = DriveD(Drive_d_full)
        self.ns = int(round(share_Ts / BASE_DT))
        self.nd = int(round(TS_DRIVE / BASE_DT))
        self.u = np.array([r0, 0.0])
        self.r0 = r0

    def update(self, k, y, ref):
        if k % self.ns == 0:
            self.u[0] = self.share.step(ref[0] - y[0])
        if k % self.nd == 0:
            self.u[1] = self.drive.step(ref[1] - y[1])
        return self.u


class MimoBundle:
    name = "mimo"

    def __init__(self, r0):
        self.c = MimoD(r0)
        self.nm = int(round(TS_MIMO / BASE_DT))
        self.u = np.array([r0, 0.0])
        self.r0 = r0

    def update(self, k, y, ref):
        if k % self.nm == 0:
            self.u = self.c.step(M_DEI @ (np.asarray(ref, float) - y))
        return self.u


def make_bundles(r0):
    """The three controller configurations compared in every sim."""
    return [("dec", DecBundle(r0, TS_SHARE)),
            ("dec500", DecBundle(r0, TS_SHARE_SLOW)),
            ("mimo", MimoBundle(r0))]


def simulate(G, bundle, ref_fn, T, r0, dist_fn=None, tauf_meas=None, n_out=2):
    """Multirate closed-loop sim of the small-signal plant G (physical coords).

    G outputs are DEVIATIONS about the OP; u passed to the plant is
    (u_physical - [r0, 0]).  dist_fn(t) adds a plant-INPUT disturbance [dr; di].
    tauf_meas (s), if given, applies a 1-pole measured-share prefilter at the
    BASE rate on y[0] — used with the full-order truth model, which by
    convention carries no tau_f (see full_model_mimo.py docstring).
    Returns dict of arrays.
    """
    Gd = c2d_zoh(G, BASE_DT)
    Ag, Bg, Cg = Gd.A, Gd.B, Gd.C
    n = int(round(T / BASE_DT))
    xg = np.zeros(Ag.shape[0])
    u0 = np.array([r0, 0.0])
    af = 0.0 if tauf_meas is None else float(np.exp(-BASE_DT / tauf_meas))
    yf0 = 0.0
    t = np.arange(n) * BASE_DT
    Y = np.zeros((n, n_out)); U = np.zeros((n, 2)); Rf = np.zeros((n, 2))
    for k in range(n):
        yk = Cg @ xg
        ymeas = yk[:2].copy()
        if tauf_meas is not None:
            yf0 = af * yf0 + (1.0 - af) * ymeas[0]
            ymeas[0] = yf0
        rk = np.asarray(ref_fn(k * BASE_DT), float)
        uk = bundle.update(k, ymeas, rk)
        ug = uk - u0
        if dist_fn is not None:
            ug = ug + np.asarray(dist_fn(k * BASE_DT), float)
        xg = Ag @ xg + Bg @ ug
        Y[k] = yk[:n_out]; U[k] = uk; Rf[k] = rk
    return dict(t=t, y=Y, u=U, ref=Rf)


def settle_time(t, y, target, band):
    out = np.where(np.abs(y - target) > band)[0]
    if len(out) == 0:
        return 0.0
    if out[-1] + 1 >= len(t):
        return float('inf')        # never settled inside the horizon
    return float(t[out[-1] + 1])


def write_csv(path, header, cols, stride=1):
    cols = [np.asarray(c) for c in cols]
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for i in range(0, len(cols[0]), stride):
            f.write(",".join(f"{c[i]:.7e}" for c in cols) + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# 7. Metric 4 — drive-transient share excursion
# ═════════════════════════════════════════════════════════════════════════════
print("\n-- Metric 4: drive-transient share excursion --")

# Horizons.  The LARGE step still saturates the actuator (now +-20 A), and the MIMO
# controller's post-saturation recovery is slow BY DESIGN (drive integrator
# residue KI22 = O(0.6) against a 0.122 rad/s vehicle pole — see
# mimo_synthesis.md §8.4, where the same effect needed a 60 s AW sim).  A 12 s
# horizon would report "never settled" as a horizon artefact, so the large case
# gets 60 s; the small (linear, unsaturated) case settles in under a second.
T_TRANS = {"large": 60.0, "small": 12.0}
DRIVE_STEPS = [("large", 2.0), ("small", 0.05)]   # STATE (deviation) amplitudes
DV0_CASES = [("dV0p", +0.4), ("dV0m", -0.4)]

trans_store = {}
for amp_name, amp in DRIVE_STEPS:
    for dv_name, dV0 in DV0_CASES:
        op = dict(op0, dV0=dV0)
        if not PM.op_feasible(op, p0):
            problem(f"drive transient OP infeasible at dV0={dV0}")
            continue
        G = PM.design_plant(op, p0)
        for nm, bnd in make_bundles(op['r0']):
            out = simulate(G, bnd, lambda tt: (0.0, amp if tt >= 0.05 else 0.0),
                           T_TRANS[amp_name], op['r0'])
            da = np.max(np.abs(out['y'][:, 0]))
            i_pk = float(np.max(np.abs(out['u'][:, 1])))
            rail = float(np.mean(np.abs(out['u'][:, 1]) >= I_MOT_MAX - 1e-9))
            ts_a = settle_time(out['t'], out['y'][:, 0], 0.0, 0.002)
            ts_v = settle_time(out['t'], out['y'][:, 1], amp, 0.02 * abs(amp))
            key = f"{amp_name}.{dv_name}.{nm}"
            emit(f"transient.{key}.max_abs_dalpha", float(da),
                 f"v_ref deviation step {amp:+.2f} m/s, dV0={dV0:+.1f} V, "
                 f"horizon {T_TRANS[amp_name]:.0f} s")
            emit(f"transient.{key}.dalpha_settle_2mshare_s", ts_a,
                 "time to re-enter |dalpha| < 0.002 (inf = not settled in horizon)")
            emit(f"transient.{key}.v_settle_2pct_s", ts_v, "")
            emit(f"transient.{key}.peak_abs_i_cmd_A", i_pk, "")
            emit(f"transient.{key}.i_rail_fraction", rail,
                 f"fraction of the horizon on the +-{I_MOT_MAX:.0f} A clamp (actuator-limited)")
            emit(f"transient.{key}.r_min", float(np.min(out['u'][:, 0])), "")
            emit(f"transient.{key}.r_max", float(np.max(out['u'][:, 0])), "")
            trans_store[key] = out
            print(f"  {amp_name:5s} {dv_name} {nm:6s}: max|da| = {da:.5f}  "
                  f"peak|i| = {i_pk:.3f} A  rail {100*rail:4.1f}%  "
                  f"v settle = {ts_v:.3f} s")
        # cross-controller ratios
        d_ = trans_store[f"{amp_name}.{dv_name}.dec"]
        m_ = trans_store[f"{amp_name}.{dv_name}.mimo"]
        s_ = trans_store[f"{amp_name}.{dv_name}.dec500"]
        emit(f"transient.{amp_name}.{dv_name}.mimo_over_dec_dalpha",
             float(np.max(np.abs(m_['y'][:, 0])) /
                   max(np.max(np.abs(d_['y'][:, 0])), 1e-300)),
             "share-excursion ratio MIMO / decentralized (native rates)")
        emit(f"transient.{amp_name}.{dv_name}.dec500_over_dec_dalpha",
             float(np.max(np.abs(s_['y'][:, 0])) /
                   max(np.max(np.abs(d_['y'][:, 0])), 1e-300)),
             "RATE CONFOUND ISOLATION: decentralized at 500 Hz share / at 1 kHz share")

for amp_name, _ in DRIVE_STEPS:
    for dv_name, _ in DV0_CASES:
        ks = [f"{amp_name}.{dv_name}.{nm}" for nm in ('dec', 'dec500', 'mimo')]
        if not all(k in trans_store for k in ks):
            continue
        o = trans_store[ks[0]]
        write_csv(os.path.join(FIGDIR, f"transient_{amp_name}_{dv_name}.csv"),
                  "t_s,v_ref,dec_v,dec_alpha,dec_i,dec_r,"
                  "dec500_v,dec500_alpha,dec500_i,dec500_r,"
                  "mimo_v,mimo_alpha,mimo_i,mimo_r",
                  [o['t'], o['ref'][:, 1]] +
                  [c for k in ks for c in (trans_store[k]['y'][:, 1],
                                           trans_store[k]['y'][:, 0],
                                           trans_store[k]['u'][:, 1],
                                           trans_store[k]['u'][:, 0])],
                  stride=10 if amp_name == "small" else 50)


# ═════════════════════════════════════════════════════════════════════════════
# 8. Metric 5 — regen event on the FULL-ORDER TRUTH MODEL
# ═════════════════════════════════════════════════════════════════════════════
print("\n-- Metric 5: regen event (15-state truth model, v_bus output) --")

# The truth model carries no tau_f (firmware-side filter), so the sim applies the
# 0.8 ms prefilter digitally at the base rate — the same filter that is part of
# the design plant.  Convention per full_model_mimo.py / full_order_validation.md.
G_truth = FM.full_plant_mimo(op0, dict(p0, tauf=0.0), with_bus_output=True)
emit("regen.truth_model_states", G_truth.n, "15-state full-order graft")
emit("regen.truth_model_stable_open_loop", int(G_truth.is_stable()), "")

T_REGEN = 60.0   # s — long enough for the MIMO controller's slow post-saturation recovery
regen_store = {}
for nm, bnd in make_bundles(op0['r0']):
    out = simulate(G_truth, bnd,
                   lambda tt: (0.0, -2.0 if tt >= 0.05 else 0.0),
                   T_REGEN, op0['r0'], tauf_meas=p0['tauf'], n_out=3)
    vb = out['y'][:, 2]
    key = nm
    emit(f"regen.{nm}.max_abs_dv_bus_V", float(np.max(np.abs(vb))),
         "bus excursion, truth-model v_bus output; 2 m/s -> standstill (dv_ref = -2 m/s)")
    emit(f"regen.{nm}.peak_pos_dv_bus_V", float(np.max(vb)), "")
    emit(f"regen.{nm}.max_abs_dalpha", float(np.max(np.abs(out['y'][:, 0]))), "")
    emit(f"regen.{nm}.peak_neg_i_cmd_A", float(np.min(out['u'][:, 1])), "")
    emit(f"regen.{nm}.i_rail_fraction", float(np.mean(out['u'][:, 1] <= -I_MOT_MAX + 1e-9)),
         f"fraction of the horizon on the -{I_MOT_MAX:.0f} A regen rail")
    emit(f"regen.{nm}.v_settle_2pct_s",
         settle_time(out['t'], out['y'][:, 1], -2.0, 0.04), "")
    emit(f"regen.{nm}.dalpha_settle_s",
         settle_time(out['t'], out['y'][:, 0], 0.0, 0.002), "")
    # The bus settles at a NEW operating point (the vehicle stopped, so the bus
    # load changed), so recovery must be measured against the FINAL value, not
    # against zero — measuring against zero reports "inf" for every controller.
    emit(f"regen.{nm}.dv_bus_final_V", float(vb[-1]),
         "post-event steady-state bus deviation (new load operating point)")
    emit(f"regen.{nm}.v_bus_recovery_s",
         settle_time(out['t'], vb, float(vb[-1]),
                     0.02 * max(np.max(np.abs(vb - vb[-1])), 1e-12)),
         "time for dv_bus to settle inside 2 % of its own excursion about the final value")
    emit(f"regen.{nm}.final_abs_dv_error", float(abs(out['y'][-1, 1] + 2.0)), "")
    regen_store[nm] = out
    print(f"  {nm:6s}: max|dv_bus| = {np.max(np.abs(vb)):.5f} V, "
          f"max|da| = {np.max(np.abs(out['y'][:, 0])):.5f}, "
          f"peak i = {np.min(out['u'][:, 1]):.3f} A, "
          f"final v err = {abs(out['y'][-1, 1] + 2.0):.2e} m/s")

_o = regen_store['dec']
write_csv(os.path.join(FIGDIR, "regen_truth.csv"),
          "t_s,v_ref,dec_v,dec_alpha,dec_i,dec_vbus,"
          "dec500_v,dec500_alpha,dec500_i,dec500_vbus,"
          "mimo_v,mimo_alpha,mimo_i,mimo_vbus",
          [_o['t'], _o['ref'][:, 1]] +
          [c for k in ('dec', 'dec500', 'mimo')
           for c in (regen_store[k]['y'][:, 1], regen_store[k]['y'][:, 0],
                     regen_store[k]['u'][:, 1], regen_store[k]['y'][:, 2])],
          stride=50)
emit("regen.mimo_over_dec_dv_bus",
     float(np.max(np.abs(regen_store['mimo']['y'][:, 2])) /
           max(np.max(np.abs(regen_store['dec']['y'][:, 2])), 1e-300)),
     "bus-excursion ratio MIMO / decentralized")
emit("regen.dec500_over_dec_dv_bus",
     float(np.max(np.abs(regen_store['dec500']['y'][:, 2])) /
           max(np.max(np.abs(regen_store['dec']['y'][:, 2])), 1e-300)),
     "RATE CONFOUND ISOLATION")


# ═════════════════════════════════════════════════════════════════════════════
# 9. Metric 6 — FC-charge cruise (r_ref = 0.85) + drive transient
# ═════════════════════════════════════════════════════════════════════════════
print("\n-- Metric 6: FC-charge cruise (OP 2 A / r0 = 0.85) + drive transient --")

op_fc = dict(op0, I_tot0=2.0, r0=0.85)
emit("fccruise.alpha0", PM.op_alpha0(op_fc, p0), "static share at the FC-cruise OP")
emit("fccruise.feasible", int(PM.op_feasible(op_fc, p0)), "")
G_fc = PM.design_plant(op_fc, p0)

T_FC = 60.0   # s — matched to the large-step horizon (MIMO recovery is slow by design)
fc_store = {}
for nm, bnd in make_bundles(op_fc['r0']):
    # r_ref parked ON the clamp (dalpha_ref = 0 at r0 = 0.85 = R_MAX) and then a
    # +0.5 m/s drive step: the share loop has NO upward droop authority left, so
    # this is the graceful-authority-loss / windup-interaction test.
    out = simulate(G_fc, bnd, lambda tt: (0.0, 0.5 if tt >= 0.05 else 0.0),
                   T_FC, op_fc['r0'])
    rr = out['u'][:, 0]
    emit(f"fccruise.{nm}.max_abs_dalpha", float(np.max(np.abs(out['y'][:, 0]))), "")
    emit(f"fccruise.{nm}.r_rail_fraction_upper",
         float(np.mean(rr >= R_MAX - 1e-9)),
         "fraction of the horizon with the droop ratio pinned at 0.85")
    emit(f"fccruise.{nm}.r_min", float(np.min(rr)),
         "downward authority actually used (the only direction available)")
    emit(f"fccruise.{nm}.final_abs_dalpha", float(abs(out['y'][-1, 0])),
         "residual share error at the end of the horizon (windup hang indicator)")
    emit(f"fccruise.{nm}.final_abs_dv_error", float(abs(out['y'][-1, 1] - 0.5)), "")
    emit(f"fccruise.{nm}.v_settle_2pct_s",
         settle_time(out['t'], out['y'][:, 1], 0.5, 0.01), "")
    emit(f"fccruise.{nm}.tail_r_ptp_last_2s",
         float(np.ptp(rr[-int(2.0 / BASE_DT):])),
         "peak-to-peak droop ratio over the last 2 s (limit-cycle indicator)")
    emit(f"fccruise.{nm}.r_within_clamp",
         int(np.all(rr >= R_MIN - 1e-9) and np.all(rr <= R_MAX + 1e-9)), "")
    fc_store[nm] = out
    print(f"  {nm:6s}: max|da| = {np.max(np.abs(out['y'][:, 0])):.5f}, "
          f"r pinned {100*np.mean(rr >= R_MAX - 1e-9):.1f}% of horizon, "
          f"r_min = {np.min(rr):.4f}, final |da| = {abs(out['y'][-1, 0]):.2e}")

_o = fc_store['dec']
write_csv(os.path.join(FIGDIR, "fccruise.csv"),
          "t_s,v_ref,dec_v,dec_alpha,dec_i,dec_r,dec500_v,dec500_alpha,dec500_i,dec500_r,"
          "mimo_v,mimo_alpha,mimo_i,mimo_r",
          [_o['t'], _o['ref'][:, 1]] +
          [c for k in ('dec', 'dec500', 'mimo')
           for c in (fc_store[k]['y'][:, 1], fc_store[k]['y'][:, 0],
                     fc_store[k]['u'][:, 1], fc_store[k]['u'][:, 0])],
          stride=50)


# ═════════════════════════════════════════════════════════════════════════════
# 10. Metric 7 — 30 s drive-cycle profile
# ═════════════════════════════════════════════════════════════════════════════
print("\n-- Metric 7: 30 s drive-cycle profile --")

# ABSOLUTE speed profile; the plant is linearized about v0 = 2 m/s, so the
# reference passed to the loop is (v_abs - v0).  Standstill is therefore a
# dv = -2 m/s deviation and is a LARGE-SIGNAL, actuator-limited excursion —
# stated as a caveat in mimo_comparison.md.
V0 = op0['v0']


def cycle_v_abs(t):
    if t < 2.0:
        return 0.0
    if t < 7.0:
        return 2.0 * (t - 2.0) / 5.0                 # 0 -> 2 m/s over 5 s
    if t < 17.0:
        return 2.0                                   # cruise
    if t < 20.0:
        return 2.0 - 1.5 * (t - 17.0) / 3.0          # coast 2 -> 0.5
    if t < 26.0:
        return 0.5                                   # hold
    if t < 28.0:
        return 0.5 * (1.0 - (t - 26.0) / 2.0)        # -> 0
    return 0.0


def cycle_ref(t):
    # share setpoint step 0.5 -> 0.7 (absolute) mid-cruise, back at t = 15 s
    da = 0.2 if 11.0 <= t < 15.0 else 0.0
    return (da, cycle_v_abs(t) - V0)


def cycle_dist(t):
    # load disturbance: a -1.0 A step at the plant input (drive channel) from
    # 22 s to 25 s — a grade/rolling-resistance step during the 0.5 m/s hold.
    return (0.0, -1.0 if 22.0 <= t < 25.0 else 0.0)


T_CYCLE = 30.0
cyc_store = {}
for nm, bnd in make_bundles(op0['r0']):
    out = simulate(G_nom, bnd, cycle_ref, T_CYCLE, op0['r0'], dist_fn=cycle_dist)
    ev = out['y'][:, 1] - out['ref'][:, 1]
    ea = out['y'][:, 0] - out['ref'][:, 0]
    emit(f"cycle.{nm}.rms_speed_error_m_s", float(np.sqrt(np.mean(ev ** 2))), "")
    emit(f"cycle.{nm}.rms_share_error", float(np.sqrt(np.mean(ea ** 2))), "")
    emit(f"cycle.{nm}.max_abs_speed_error_m_s", float(np.max(np.abs(ev))), "")
    emit(f"cycle.{nm}.max_abs_share_error", float(np.max(np.abs(ea))), "")
    emit(f"cycle.{nm}.peak_abs_i_cmd_A", float(np.max(np.abs(out['u'][:, 1]))), "")
    emit(f"cycle.{nm}.i_rail_fraction", float(np.mean(np.abs(out['u'][:, 1]) >=
                                                      I_MOT_MAX - 1e-9)), "")
    emit(f"cycle.{nm}.r_min", float(np.min(out['u'][:, 0])), "")
    emit(f"cycle.{nm}.r_max", float(np.max(out['u'][:, 0])), "")
    # cruise-only (steady) segment, excluding the actuator-limited ramps
    seg = (out['t'] >= 8.0) & (out['t'] < 11.0)
    emit(f"cycle.{nm}.rms_speed_error_cruise_m_s",
         float(np.sqrt(np.mean(ev[seg] ** 2))), "8-11 s cruise window, not actuator-limited")
    emit(f"cycle.{nm}.rms_share_error_cruise",
         float(np.sqrt(np.mean(ea[seg] ** 2))), "8-11 s cruise window")
    segd = (out['t'] >= 22.0) & (out['t'] < 26.0)
    emit(f"cycle.{nm}.max_abs_speed_error_load_step_m_s",
         float(np.max(np.abs(ev[segd]))), "-1 A input load step, 22-25 s")
    emit(f"cycle.{nm}.max_abs_share_error_load_step",
         float(np.max(np.abs(ea[segd]))), "-1 A input load step, 22-25 s")
    cyc_store[nm] = out
    print(f"  {nm:6s}: RMS v err = {np.sqrt(np.mean(ev**2)):.4f} m/s, "
          f"RMS share err = {np.sqrt(np.mean(ea**2)):.5f}, "
          f"peak |i| = {np.max(np.abs(out['u'][:, 1])):.3f} A, "
          f"rail {100*np.mean(np.abs(out['u'][:, 1]) >= I_MOT_MAX-1e-9):.1f}%")

_o = cyc_store['dec']
write_csv(os.path.join(FIGDIR, "drive_cycle.csv"),
          "t_s,v_ref,alpha_ref,dec_v,dec_alpha,dec_i,dec_r,"
          "dec500_v,dec500_alpha,dec500_i,dec500_r,mimo_v,mimo_alpha,mimo_i,mimo_r",
          [_o['t'], _o['ref'][:, 1], _o['ref'][:, 0]] +
          [c for k in ('dec', 'dec500', 'mimo')
           for c in (cyc_store[k]['y'][:, 1], cyc_store[k]['y'][:, 0],
                     cyc_store[k]['u'][:, 1], cyc_store[k]['u'][:, 0])],
          stride=20)


# ═════════════════════════════════════════════════════════════════════════════
# 11. Teensy cost datapoints (analytic; cross-referenced in mimo_comparison.md)
# ═════════════════════════════════════════════════════════════════════════════
hdr("6. IMPLEMENTATION COST")


def mac_count(nx, ny, nu, integ=0):
    """MAC per controller tick for u = Cx + De + (integrator); x' = Ax + Be."""
    return nx * nx + nx * nu + ny * nx + ny * nu + integ


mimo_mac = mac_count(M_A.shape[0], 2, 2, integ=2 * 2 * 2)
emit("cost.mimo.states_total", M_A.shape[0] + 2,
     f"{M_A.shape[0]} modal remainder + 2 integrator")
emit("cost.mimo.mac_per_tick", mimo_mac,
     f"dense A ({M_A.shape[0]}x{M_A.shape[0]}) + B/C/D (2x) + 2x2 Tustin integrator; "
     "NOTE: excludes the DE^-1/DU scaling and the back-calculation AW ops that "
     "synthesize_mimo_controller.py counts -- its figure is 97 MAC/tick")
emit("cost.mimo.rate_hz", 1.0 / TS_MIMO, "")
emit("cost.mimo.mac_per_second", mimo_mac / TS_MIMO, "")
emit("cost.mimo.coeff_floats", M_A.size + M_B.size + M_C.size + M_D.size + M_KI.size
     + 2 * 6, "A,B,C,D,KI + DE,DU,U0,U_MIN,U_MAX,XI clamps")

dec_share_nx = Share_remd_1k.A.shape[0]
dec_drive_nx = Drive_d_full.A.shape[0]
share_mac = mac_count(dec_share_nx, 1, 1, integ=2)
drive_mac = mac_count(dec_drive_nx, 1, 1, integ=2) + dec_drive_nx * dec_drive_nx
emit("cost.dec.share.states", dec_share_nx + 1, "remainder + integrator (shipped)")
emit("cost.dec.share.mac_per_tick", share_mac, "biquad cascade + trapezoidal integrator")
emit("cost.dec.share.rate_hz", 1.0 / TS_SHARE, "")
emit("cost.dec.drive.states", dec_drive_nx + 1,
     "Phase-3 baseline needs the HANUS SELF-CONDITIONED state-space form, not biquads")
emit("cost.dec.drive.mac_per_tick", drive_mac,
     "includes the Hanus Ac = Ad - Bd Cd/Dd product")
emit("cost.dec.drive.rate_hz", 1.0 / TS_DRIVE, "")
emit("cost.dec.mac_per_second", share_mac / TS_SHARE + drive_mac / TS_DRIVE, "")
emit("cost.mimo_over_dec_mac_per_second",
     (mimo_mac / TS_MIMO) / (share_mac / TS_SHARE + drive_mac / TS_DRIVE), "")
print(f"  MIMO   : {M_A.shape[0]+2} states, {mimo_mac} MAC/tick @ 500 Hz "
      f"= {mimo_mac/TS_MIMO:.0f} MAC/s")
print(f"  K_dec  : {dec_share_nx+1}+{dec_drive_nx+1} states, "
      f"{share_mac} MAC/tick @ 1 kHz + {drive_mac} MAC/tick @ 500 Hz "
      f"= {share_mac/TS_SHARE + drive_mac/TS_DRIVE:.0f} MAC/s")


# ═════════════════════════════════════════════════════════════════════════════
# 12. Emit comparison_metrics.txt
# ═════════════════════════════════════════════════════════════════════════════
hdr("7. EMIT comparison_metrics.txt")

path = os.path.join(HERE, "comparison_metrics.txt")
with open(path, "w", encoding="utf-8") as f:
    f.write("# comparison_metrics.txt — GENERATED by "
            "controller_design_MIMO/compare_controllers.py\n"
            "# DO NOT EDIT BY HAND.  Every table cell in mimo_comparison.md is one of\n"
            "# these keys (the Phase-5 gate).\n"
            "#\n"
            "# Controllers:\n"
            "#   dec    = decentralized blkdiag(shipped share Youla-H @ 1 kHz,\n"
            "#            Phase-3 SISO drive Youla-H @ 500 Hz), closed against the\n"
            "#            SAME coupled 2x2 plant as the MIMO controller\n"
            "#   dec500 = the same decentralized pair with the share half\n"
            "#            re-discretized at 500 Hz (rate-confound isolation)\n"
            "#   mimo   = centralized 2x2 H-inf/Youla-H controller @ 500 Hz\n"
            "# All time-domain quantities are SMALL-SIGNAL DEVIATIONS about the OP;\n"
            "# step amplitudes are named in each key's comment.\n"
            f"#\n# generated {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    for k, v, c in _METRICS:
        if isinstance(v, (int, np.integer)):
            s = str(int(v))
        elif isinstance(v, float) and not np.isfinite(v):
            s = "inf" if v > 0 else "-inf"
        else:
            s = f"{float(v):.6g}"
        f.write(f"{k} = {s}" + (f"    # {c}" if c else "") + "\n")
    if _PROBLEMS:
        f.write("\n# ---- results of note (logged, NOT gate failures) ----\n")
        for p in _PROBLEMS:
            f.write(f"# {p}\n")
    else:
        f.write("\n# no decentralized instabilities or anomalies found\n")
print(f"  wrote {len(_METRICS)} metrics -> {os.path.relpath(path, HERE)}")
print(f"  figures/CSVs in {os.path.relpath(FIGDIR, HERE)}/")
if _PROBLEMS:
    print("\n  RESULTS OF NOTE (logged, not gate failures):")
    for p in _PROBLEMS:
        print("   - " + p)
print("\nDONE.")
