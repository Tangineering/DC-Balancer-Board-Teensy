#!/usr/bin/env python3
"""compute_Su.py — input-sensitivity check S_u = (I + K G)^-1 for both
controllers, per Neoclassical Control (Assadian & Mallon, 2020 draft) §12.7.2
eqs. (12.86)-(12.87): whenever cond(G_p) != 1, sigma_max(S_y) alone is not a
sufficient robustness summary and sigma_max(S_u) must be checked at the plant
input node. Here cond(G_s) = 5.33 at DC (in-band peak ~2.8e3), so the check is
mandatory. Added 2026-08-04 for the internal report
papers/MIMO_Droop_Drive_Comparison/ (its S_u table row comes from this script).

Controller assembly mirrors compare_controllers.py exactly (continuous physical
controllers rebuilt from the emitted coefficient headers; d2c inverse-Tustin).
Result (also printed on run): the realized input sensitivities are modest for
both controllers despite the loose (12.86) bound — nominal 1.385 (dec) /
1.239 (MIMO); worst Tier-2 corner 1.864 (dec) / 1.475 (MIMO). The input node
raises no new concern, and the MIMO controller is again the better of the two.
Values updated 2026-08-04 for the +-20 A recalibration round: the decentralized
numbers are UNCHANGED (S_u is a linear frequency-domain quantity, and the dec
controller itself was not re-synthesized — only its clamp metadata moved), while
the MIMO numbers move because the MIMO controller was re-synthesized at the new
input scaling DU = diag(0.35, 20.0).  Previous (+-5 A) values: 1.309 nominal /
1.414 worst.

Run:  ctrl-venv/Scripts/python.exe compute_Su.py
"""

import os
import re
import numpy as np
from numpy.linalg import solve, inv

from hinf_mimo import SS, ss_parallel, ss_series, ss_lmul, ss_rmul, blkdiag_ss
from shipped_share import shipped_share_controller
import plant_mimo as pm

HERE = os.path.dirname(os.path.abspath(__file__))
TS = 2.0e-3


def d2c_tustin(sysd, Ts):
    # COPIED (logic) from compare_controllers.py d2c_tustin @ this repo
    I = np.eye(sysd.A.shape[0])
    Mi = inv(sysd.A + I)
    B = 2.0 / Ts * (Mi @ sysd.B)
    return SS(2.0 / Ts * (Mi @ (sysd.A - I)), B, 2.0 * (sysd.C @ Mi),
              sysd.D - (Ts / 2.0) * (sysd.C @ B))


def parse_arr(text, name):
    m = re.search(re.escape(name) + r"[^=]*=\s*\{(.*?)\};", text, re.S)
    rows = re.findall(r"\{([^{}]*)\}", m.group(1))
    if rows:
        return np.array([[float(x.strip().rstrip("f")) for x in r.split(",") if x.strip()]
                         for r in rows])
    return np.array([float(x.strip().rstrip("f")) for x in m.group(1).split(",") if x.strip()])


def build_controllers():
    with open(os.path.join(HERE, "mimo_controller_coeffs.h"), encoding="utf-8") as f:
        MH = f.read()
    A, B, C, D = (parse_arr(MH, n) for n in
                  ("MIMO_CTRL_A", "MIMO_CTRL_B", "MIMO_CTRL_C", "MIMO_CTRL_D"))
    KI = parse_arr(MH, "MIMO_CTRL_KI")
    DE = np.diag(parse_arr(MH, "MIMO_CTRL_DE"))
    DU = np.diag(parse_arr(MH, "MIMO_CTRL_DU"))
    Grem = d2c_tustin(SS(A, B, C, D), TS)
    K_mimo = ss_lmul(DU, ss_rmul(
        ss_parallel(SS(np.zeros((2, 2)), np.eye(2), KI, np.zeros((2, 2))), Grem), inv(DE)))

    Share_c = shipped_share_controller()["Gc_red"]
    with open(os.path.join(HERE, "drive_siso_coeffs.h"), encoding="utf-8") as f:
        DH = f.read()
    dkI = float(re.search(r"DRIVE_CTRL_KI\s*=\s*([-\d.eE+]+)f", DH).group(1))
    g = None
    for b0, b1, b2, a1, a2 in parse_arr(DH, "DRIVE_CTRL_SOS"):
        s = SS([[-a1, 1.0], [-a2, 0.0]], [[b1 - a1*b0], [b2 - a2*b0]],
               [[1.0, 0.0]], [[b0]])
        g = s if g is None else ss_series(g, s)
    Drive_c = ss_parallel(SS([[0.0]], [[1.0]], [[dkI]], [[0.0]]), d2c_tustin(g, TS))
    return blkdiag_ss(Share_c, Drive_c), K_mimo


def su_peak(G, K, w):
    pk, wpk = 0.0, 0.0
    for wi in w:
        s = 1j*wi
        Gz = G.C @ solve(s*np.eye(G.n) - G.A, G.B) + G.D
        Kz = K.C @ solve(s*np.eye(K.n) - K.A, K.B) + K.D
        sv = np.linalg.svd(inv(np.eye(2) + Kz @ Gz), compute_uv=False)[0]
        if sv > pk:
            pk, wpk = sv, wi
    return pk, wpk


def main():
    K_dec, K_mimo = build_controllers()
    w = np.logspace(-2, 5, 3000)
    op, p = pm.nominal_op(), pm.nominal_params()
    Gnom = pm.design_plant(op, p)
    # the exhaustive-sweep worst Tier-2 corner (MATLAB_mimo_results.txt §D)
    Gworst, _, _ = pm.corner_plant(
        op, dict(dV0=-0.4, Td=2e-3, taur=300e-6, tauf=0.8e-3),
        dict(K_v=2.0, pole_factor=2.0, tau_v=0.5e-3, Td_v=4e-3))
    ok = True
    # pinned to the +-20 A round (2026-08-04); +-5 A values were
    # mimo 1.3094 nominal / 1.4143 worst (dec identical).
    refs = {("nominal", "dec"): 1.3852, ("nominal", "mimo"): 1.2385,
            ("worst", "dec"): 1.8640, ("worst", "mimo"): 1.4749}
    for gname, G in (("nominal", Gnom), ("worst", Gworst)):
        for cname, K in (("dec", K_dec), ("mimo", K_mimo)):
            pk, wpk = su_peak(G, K, w)
            drift = abs(pk - refs[(gname, cname)])
            ok = ok and drift < 5e-3
            print(f"  {gname:8s} {cname:5s}: sigma(S_u) peak = {pk:.4f} "
                  f"at {wpk:.1f} rad/s   (report value {refs[(gname, cname)]:.4f})")
    print("S_u CHECK:", "PASS (matches report values)" if ok else "DRIFT vs report values")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
