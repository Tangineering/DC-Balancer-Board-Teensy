#!/usr/bin/env python3
"""synthesize_drive_siso.py — Phase 3: SISO Youla-H DRIVE baseline (plan §5, bullet 1).

The papers' Youla-H recipe (H-inf mixed sensitivity + Youla DC-gain rescale so
T(0) = 1 exactly) applied to the SC001 drive channel G22 from `plant_mimo`.
Together with the SHIPPED share controller (`shipped_share.py`) this forms the
DECENTRALIZED baseline that Phase 5 closes against the coupled 2x2 plant.

Pipeline (mirrors controller_design/synthesize_controller.py @ 51b8962; every
stage gate-checked, non-zero exit on any failure):
  1. G22 at the nominal OP/params (plant_mimo.drive_plant -- single source of truth).
  2. Mixed-sensitivity weights at the papers' 24 rad/s bandwidth; hinfsyn_dgkf
     on AugPlantMIMO (1x1 blocks).
  3. Youla-H scalar DC correction: Y_YH = Y_H/T_H(0); rebuild Gc_YH.
  4. split_integrator_multi(k=1) + balanced truncation of the stable remainder.
  5. Margins, continuous corner sweep, Tustin at Ts = 2 ms (500 Hz motor channel),
     discrete corner sweep, clamped (+-I_CLAMP) time-domain sims.
  6. Emit drive_siso_metrics.txt and the coefficient header in TWO places from one
     emitter -- drive_siso_coeffs.h (study copy) and ../teensy_controller/
     drive_controller_coeffs.h (the FIRMWARE copy, fw v10+); both carry the biquad
     cascade and the Hanus state-space realization -- and
     figures/drive_siso_step.csv + figures/drive_siso_replay.csv (replay reference
     vectors for a firmware implementation of the Hanus form).

Plant status: the drive channel is CALIBRATED as of 2026-08-16
(calibration/motor_id_20260815.md).  Constants live in plant_mimo.py; this script is
downstream of them and must be re-run whenever they move.

Run:  ctrl-venv/Scripts/python.exe synthesize_drive_siso.py
"""

import os
import numpy as np
from numpy.linalg import eigvals, solve

from hinf_mimo import (SS, ss_series, ss_parallel, ss_scale,
                       makeweight, strictly_proper_2nd_order_weight,
                       AugPlantMIMO, hinfsyn_dgkf, hinf_norm, balanced_truncate,
                       split_integrator_multi, c2d_tustin, c2d_zoh,
                       dss_tf_coeffs, dfreqresp)
import plant_mimo as pm

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figures")

np.set_printoptions(precision=6, suppress=False, linewidth=120)
failures = []


def gate(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Design plant: G22 at the nominal OP (plan §1 / mimo_system_model.md §3)
# ─────────────────────────────────────────────────────────────────────────────
TS = 2.0e-3               # s, motor-channel sample period (500 Hz; UART frame floor)
I_CLAMP = 12.0            # A, motor current clamp (firmware MOTOR_I_CMD_MAX, rev 2026-08-15)
# History: +-5 A (a bench derating that applied the ~67-87 W BUS power budget directly at
# the MOTOR node -- a unit error), then +-20 A, now +-12 A to track the firmware constant
# (operator decision 2026-08-15, Castle 1406 1900KV fitted).  The bus/motor conversion at
# the MEASURED nominal OP is A_i ~ 0.092 A_bus per A_mot (plant_mimo.bus_current_gains --
# down from 0.243 because the calibrated k_t/r_t chain lowers omega0), so +-12 A motor-side
# is only ~1.1 A bus-side at cruise.  The motor clamp is therefore now the BINDING limit
# and is no longer coincident with the bus-power budget.  Only the motor clamp is enforced
# in these sims (no bus-current constraint is modeled); the bus-side limits live in the
# VESC configuration (docs/VESC_MOTOR_INTEGRATION.md §4).

OP0 = pm.nominal_op()
P0 = pm.nominal_params()
G22 = pm.drive_plant(OP0, P0)

print("== 1. Drive plant G22 (di_cmd [A] -> dv [m/s]) ==")
print(f"  states = {G22.n}, DC gain = {G22.dcgain():.6f} (m/s)/A")
print(f"  poles  = {np.sort_complex(G22.poles())}")
print(f"  mechanical pole = -b_eff/m_eff = {-pm.b_eff(OP0, P0)/P0['m_eff']:.6f} rad/s"
      f"   (near-integrator)")
print(f"  force/amp = {pm.force_per_amp(P0):.5f} N/A, b_eff = {pm.b_eff(OP0, P0):.5f} N*s/m")

# PLANT RE-IDENTIFIED 2026-08-16 (calibration/motor_id_20260815.md).  The drive channel
# is no longer a placeholder chain: k_t, R_m, m_eff, r_t, tau_v and the drag law are all
# measured.  The design plant moved substantially, so this whole synthesis was re-run:
#   G22(0)   3.7085 -> 1.4112 (m/s)/A     (x0.38: k_t x0.78, r_t x2.31, b_eff x0.89)
#   pole    -0.1219 -> -0.0914 rad/s      (b_eff/m_eff, still a near-integrator)
#   K_F      1.3338 -> 0.4516 N/A
# The earlier note here recorded that b_eff was DOMINATED by a modelled motor free-run
# loss (0.3596 of 0.3719 N*s/m).  That decomposition is RETIRED: b_eff is now a single
# measured local slope (0.32 N*s/m at v0 = 2.0 m/s), and the measured drag curve is
# Coulomb-dominated rather than viscous-dominated, so the loss attribution in the old
# note was not merely imprecise, it was the wrong shape.  The Youla-H correction factor
# remains tiny (see §3) because the plant is still a near-integrator.
gate("G22 is strictly proper (AugPlantMIMO precondition)", np.max(np.abs(G22.D)) < 1e-14)
gate("G22 DC gain positive (positive current -> positive speed)", G22.dcgain() > 0,
     f"G22(0) = {G22.dcgain():.4f} (m/s)/A")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Weights + H-inf synthesis  (plan §3, drive channel)
# ─────────────────────────────────────────────────────────────────────────────
# Papers' philosophy (Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control):
#   Wp  2nd-order strictly proper S-weight at the 24 rad/s target bandwidth
#   Wd  1st-order T-rolloff weight
#   Wu  1st-order Y (control-effort) weight breaking at 300 rad/s
WC_TARGET = 24.0          # rad/s, the papers' driver-model bandwidth (the TARGET)
# The Wp corner is placed ABOVE the target because on this plant the achieved S/T
# crossover lands consistently below the Wp corner (the loop cannot be pushed to the
# weight; gamma_opt >> 1 throughout, i.e. the specs are shaped, not met).
#
# LADDER RE-RUN 2026-08-16 on the CALIBRATED plant.  The old ladder is void: the plant
# DC gain fell x2.6 and the pole moved, so every rung's achieved crossover and margins
# changed and the previously CHOSEN rung (WC=50, Wu(0.2,300,10)) now lands at 14.4 rad/s
# instead of 20.7.  Ladder actually run (Wd break = 2.5*WC, Wu = makeweight(dc, 300, hf);
# worst ||S|| over the 24 drive corners, now with pole_factor in {0.5, 3}):
#   WC=24, Wu(0.3 ,300,20 ) -> g_opt 20.17, wc  8.25, PM 59.4, worst ||S|| 1.451  (wc gate FAILS, < 12)
#   WC=24, Wu(0.1 ,300, 5 ) -> g_opt 11.53, wc 10.55, PM 49.6, worst ||S|| 1.925  (wc gate FAILS, < 12)
#   WC=30, Wu(0.1 ,300, 5 ) -> g_opt 13.77, wc 11.93, PM 48.4, worst ||S|| 2.043  (wc gate FAILS, < 12)
#   WC=40, Wu(0.3 ,300,20 ) -> g_opt 28.84, wc 11.22, PM 57.7, worst ||S|| 1.592  (wc gate FAILS, < 12)
#   WC=40, Wu(0.1 ,300, 5 ) -> g_opt 17.40, wc 14.13, PM 46.9, worst ||S|| 2.224
#   WC=45, Wu(0.1 ,300, 5 ) -> g_opt 19.19, wc 15.02, PM 46.4, worst ||S|| 2.309
#   WC=50, Wu(0.2 ,300,10 ) -> g_opt 27.47, wc 14.35, PM 53.2, worst ||S|| 1.890  (the OLD choice)
#   WC=50, Wu(0.12,300, 6 ) -> g_opt 22.22, wc 15.49, PM 47.7, worst ||S|| 2.253
#   WC=50, Wu(0.1 ,300, 5 ) -> g_opt 20.95, wc 15.98, PM 45.9, worst ||S|| 2.392
#   WC=50, Wu(0.08,300, 4 ) -> g_opt 19.78, wc 16.22, PM 43.9  (PM gate FAILS)
#   WC=55, Wu(0.15,300,7.5) -> g_opt 26.07, wc 15.98, PM 49.6, worst ||S|| 2.152  <-- CHOSEN
#   WC=55, Wu(0.1 ,300, 5 ) -> g_opt 22.71, wc 16.73, PM 45.4, worst ||S|| 2.474
#   WC=60, Wu(0.1 ,300, 5 ) -> g_opt 24.45, wc 17.52, PM 45.1, worst ||S|| 2.555  (over the 2.5 target)
#   WC=60, Wu(0.05,300,2.5) -> g_opt 21.93, wc 18.07, PM 40.6  (PM gate FAILS)
#   WC=70, Wu(0.1 ,300, 5 ) -> g_opt 27.91, wc 18.92, PM 44.4  (PM gate FAILS)
#   WC=80, Wu(0.05,300,2.5) -> g_opt 28.74, wc 20.75, PM 40.3, worst ||S|| 3.238  (both gates FAIL)
#
# CHOICE, and a deliberate DEVIATION from a literal "most aggressive rung that clears the
# gates".  That literal rule selects WC=55, Wu(0.1,300,5): wc 16.73 rad/s, PM 45.4 deg,
# worst ||S|| 2.474.  It clears PM > 45 by 0.4 deg and the 2.5 ||S|| target by 0.026 -- on
# a plant whose damping slope carries +-15 % and a documented thermal spread, that is not
# a margin, it is a rounding error.  WC=55, Wu(0.15,300,7.5) buys 4.2 deg of phase margin
# and 0.32 of worst-corner peak for 4.5 % of crossover (15.98 vs 16.73 rad/s).  The
# aggressive rung is recorded above so the trade is auditable rather than hidden.
#
# The achieved crossover is now BELOW the papers' 24 rad/s (15.98 vs the old design's
# 20.7) and the gate band's lower half.  This is the calibration's honest consequence: at
# the measured plant gain, pushing past ~17 rad/s costs phase margin faster than the old
# (over-estimated) plant suggested.  The clamp is not what selects the rung -- the ladder
# is decided entirely by phase margin and worst-corner ||S||, which are linear properties
# and see no clamp at all.  The clamp does bind the LARGE-SIGNAL response: the 0->2 m/s
# step in §8a rails at 12 A and is inertia-limited (a_max = K_F*12/m_eff = 1.55 m/s^2),
# which is a separate statement about actuator range, not about loop shaping.
WC = 55.0                 # rad/s, Wp corner (see ladder above)
WP_DC = 1e4               # S weight DC gain (integral-like low-frequency demand)

Wp = strictly_proper_2nd_order_weight(WP_DC, WC)
# Wd break at 2.5x the Wp corner.  DEVIATION from the papers' 18 rad/s break: that
# number is tied to THEIR plant/bandwidth pairing; placing the T-rolloff weight BELOW
# the S-weight corner makes Wp and Wd contend over the same decade, inflating gamma
# and collapsing the achieved crossover.  2.5x preserves the papers' INTENT (T rolled
# off just above crossover) at this plant's bandwidth.
WD_WC = 2.5*WC
Wd = makeweight(0.5, WD_WC, 40.0)
# Wu on Y = Gc*S [A per m/s].  Y(0) is unbounded (integrator) so only the in-band /
# HF shape matters.  dc = 0.15 allows ~6.7 A/(m/s) in band -- on a 0.5 m/s-scale error
# that is ~3.3 A of proportional effort, inside the +-12 A clamp; hf = 7.5 forces Y down
# past the 300 rad/s break (papers' Y-weight break).  Loosened from the previous
# (0.2, 300, 10) because the calibrated plant's DC gain is 2.6x smaller: the SAME speed
# error now needs 2.6x the current, so holding the old effort weight would have cost
# bandwidth for no physical reason.
# D = hf != 0 => D12 full column rank (AugPlantMIMO asserts this).
WU_DC, WU_WC, WU_HF = 0.15, 300.0, 7.5
Wu = makeweight(WU_DC, WU_WC, WU_HF)

print("\n= 2. Weights + H-inf (DGKF) ==")
print(f"  Wp = strictly_proper_2nd_order_weight(dc={WP_DC:g}, wc={WC:g} rad/s)")
print(f"  Wd = makeweight(0.5, {WD_WC:g}, 40)   [papers' break scaled -> 2.5*Wp corner]")
print(f"  Wu = makeweight({WU_DC}, {WU_WC:g}, {WU_HF:g})")

P = AugPlantMIMO(G22, Wp, Wu, Wd)
K_H, g_used, g_opt, tzw_norm, _info = hinfsyn_dgkf(P, verbose=False)
print(f"  gamma_opt = {g_opt:.4f}, built at gamma = {g_used:.4f}, "
      f"||Tzw||inf = {tzw_norm:.4f}, K order = {K_H.n}")
gate("Tzw norm consistent with gamma (a-posteriori gate)", tzw_norm <= g_used*1.005,
     f"{tzw_norm:.4f} <= {g_used:.4f}")


def loop_tfs(Gc, G):
    """L, S, T, Y for the SISO negative-feedback loop (D_L = 0)."""
    L = ss_series(Gc, G)
    assert abs(L.D[0, 0]) < 1e-12
    S = SS(L.A - L.B @ L.C, L.B, -L.C, [[1.0]])
    T = SS(L.A - L.B @ L.C, L.B, L.C, [[0.0]])
    Y = ss_series(S, Gc)
    return L, S, T, Y


L_H, S_H, T_H, Y_H = loop_tfs(K_H, G22)
T0_H = T_H.dcgain()
w = np.logspace(-3, 5, 1200)
Smag = np.abs(S_H.freqresp(w)); Tmag = np.abs(T_H.freqresp(w))
wc_H = w[np.argmin(np.abs(Smag - Tmag))]
print(f"  T_H(0) = {T0_H:.10f}  (deficiency {abs(1-T0_H):.2e} -- the Youla-H target)")
print(f"  achieved S/T crossover ~ {wc_H:.2f} rad/s;  ||S||inf = {hinf_norm(S_H):.3f}, "
      f"||T||inf = {hinf_norm(T_H):.3f}")
gate("achieved crossover in the vicinity of the papers' 24 rad/s (12-48)",
     12.0 <= wc_H <= 48.0, f"wc = {wc_H:.2f} rad/s")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Youla-H DC correction (papers' scalar recipe): Y_YH = Y_H / T_H(0)
# ─────────────────────────────────────────────────────────────────────────────
print("\n= 3. Youla-H DC correction ==")
Y_YH = ss_scale(Y_H, 1.0/T0_H)
assert abs(Y_YH.D[0, 0]) < 1e-12
# Gc_YH = Y_YH (1 - G Y_YH)^-1: positive feedback of G around Y (D_Y = 0 => well posed).
# Mirrors controller_design/synthesize_controller.py:108-121 @ 51b8962.
A_gc = np.block([[Y_YH.A, Y_YH.B @ G22.C],
                 [G22.B @ Y_YH.C, G22.A]])
Gc_YH_full = SS(A_gc,
                np.vstack([Y_YH.B, np.zeros((G22.n, 1))]),
                np.hstack([Y_YH.C, np.zeros((1, G22.n))]),
                [[0.0]])
corr = 1.0/T0_H
print(f"  gain scale 1/T_H(0) = {corr:.10f}  (|1 - 1/T0| = {abs(1-corr):.2e})")
print(f"  raw Gc_YH order = {Gc_YH_full.n}")
gate("Youla-H correction is a small perturbation (near-integrator plant => T_H(0) ~ 1)",
     abs(1.0 - corr) < 1e-2, f"|1 - 1/T_H(0)| = {abs(1-corr):.2e}")

pole_min = np.min(np.abs(eigvals(Gc_YH_full.A)))
gate("Gc_YH contains the enforced integrator (pole ~ 0)", pole_min < 1e-3,
     f"|p|min = {pole_min:.2e}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Integrator split + balanced truncation
# ─────────────────────────────────────────────────────────────────────────────
print("\n= 4. Integrator split + reduction ==")
KI, Gs_full = split_integrator_multi(Gc_YH_full, k=1, tol=1e-3)
kI = float(KI[0, 0])
# Sign chain (printed end-to-end, per the brief):
#   e = v_ref - v  [m/s]  ->  Gc  ->  i_cmd [A]  ->  force_per_amp > 0 [N/A]
#   ->  1/(m_eff s + b_eff) > 0  ->  v.   G22(0) = +3.709 (m/s)/A > 0, so a POSITIVE
#   velocity error must command POSITIVE current => the integrator residue kI > 0.
print(f"  sign chain: e[m/s] -> Gc -> i_cmd[A] -> F/A = {pm.force_per_amp(P0):+.5f} N/A"
      f" -> 1/(m s + b), b = {pm.b_eff(OP0, P0):+.5f} -> G22(0) = {G22.dcgain():+.4f} > 0"
      f"  ==> require kI > 0;  got kI = {kI:+.6f}")
gate("kI sign consistent with loop sign (positive v-error -> positive current)",
     kI > 0, f"kI = {kI:.6f}")
gate("stable remainder is stable", Gs_full.is_stable(),
     f"max Re(p) = {np.max(eigvals(Gs_full.A).real):.3e}")

Gs_red, hsv = balanced_truncate(Gs_full, order=None, tol=1e-5)


def Gc_freq(Gs, w_):
    return Gs.freqresp(w_) + kI/(1j*w_)


def relerr_of(Gs):
    full = Gc_freq(Gs_full, w)
    return float(np.max(np.abs(Gc_freq(Gs, w) - full)/np.maximum(np.abs(full), 1e-12)))


# target <= 4 states (2 biquads), matching the shipped firmware realization budget
if Gs_red.n > 4:
    cand, _ = balanced_truncate(Gs_full, order=4)
    if relerr_of(cand) < 2e-2:
        Gs_red = cand
print(f"  reduction: {Gs_full.n} -> {Gs_red.n} states; HSV = "
      f"{np.array2string(hsv[:8], precision=3)}")
relerr = relerr_of(Gs_red)
gate("reduced controller matches full (freq resp)", relerr < 2e-2,
     f"max rel err = {relerr:.2e}")

Gc_red = ss_parallel(SS([[0.0]], [[1.0]], [[kI]], [[0.0]]), Gs_red)

nomL, nomS, nomT, nomY = loop_tfs(Gc_red, G22)
T0_red = nomT.dcgain()
gate("T(0) = 1 with reduced controller (exact integrator)", abs(T0_red - 1) < 1e-9,
     f"T(0) = {T0_red:.12f}")
Smag_r = np.abs(nomS.freqresp(w)); Tmag_r = np.abs(nomT.freqresp(w))
wc_ach = w[np.argmin(np.abs(Smag_r - Tmag_r))]
S_nom = hinf_norm(nomS)
print(f"  reduced-controller crossover = {wc_ach:.2f} rad/s, ||S||inf = {S_nom:.3f}, "
      f"||T||inf = {hinf_norm(nomT):.3f}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Margins on the nominal loop
# ─────────────────────────────────────────────────────────────────────────────
print("\n= 5. Nominal margins ==")
Lresp = nomL.freqresp(w)
idx_c = np.argmin(np.abs(np.abs(Lresp) - 1.0))
pm_deg = 180 + np.degrees(np.angle(Lresp[idx_c]))
dm = np.radians(pm_deg)/w[idx_c]
gate("phase margin > 45 deg", pm_deg > 45, f"PM = {pm_deg:.1f} deg at {w[idx_c]:.2f} rad/s")
gate("delay margin > 2*Ts (4 ms)", dm > 2*TS, f"DM = {dm*1e3:.2f} ms")

# gain margin: lowest |L| crossing of the -180 deg phase
ph = np.unwrap(np.angle(Lresp))
gm_db = float('inf')
for i in range(len(w)-1):
    if (ph[i] + np.pi)*(ph[i+1] + np.pi) < 0:
        mag = np.abs(Lresp[i])
        if mag > 0:
            gm_db = min(gm_db, -20*np.log10(mag))
print(f"  gain margin = {'inf' if not np.isfinite(gm_db) else f'{gm_db:.1f} dB'}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Continuous corner robustness
# ─────────────────────────────────────────────────────────────────────────────
# plant_mimo parameterizes the DRIVE plant by (K_v, pole_factor, tau_v, Td_v) from
# drive_corners().  DEVIATION from the brief's "24 corners x feasible OPs": op_grid()
# varies (I_tot0, r0), neither of which enters G22, so sweeping it would repeat the same
# plant 10x.
# CHANGED 2026-08-16: the previous run also swept v0 in {0.5, 2, 5} m/s, because b_eff
# then carried an explicit aero term rho*C_dA*v0.  The calibrated b_eff is a MEASURED
# LOCAL SLOPE with no v0 dependence (plant_mimo.b_eff), so that sweep is now exactly
# degenerate -- it would report 72 plants of which only 24 differ.  The speed dependence
# it used to represent has not disappeared; it has moved into pole_factor in {0.5, 3},
# whose upper corner is sized to cover the measured doubling of the slope below
# ~1.5 m/s.  Sweeping a single v0 and widening the pole corner is the same coverage,
# honestly counted.
V0_SET = (2.0,)
print("\n= 6. Continuous corner sweep (24 drive corners; v0 does not enter G22) ==")


def corner_drive_plant(dc, v0):
    o = dict(OP0); o['v0'] = v0
    p = dict(P0); p.update(dc)
    return pm.drive_plant(o, p), o, p


worstS, worstS_corner, n_corner = 0.0, None, 0
n_unstable = 0
for dc in pm.drive_corners():
    for v0 in V0_SET:
        Gc_p, _, _ = corner_drive_plant(dc, v0)
        _, Sc, _, _ = loop_tfs(Gc_red, Gc_p)
        n_corner += 1
        if np.max(eigvals(Sc.A).real) >= 0:
            n_unstable += 1
            print(f"    UNSTABLE at {dc}, v0 = {v0}")
            continue
        Sn = hinf_norm(Sc)
        if Sn > worstS:
            worstS, worstS_corner = Sn, (dict(dc), v0)
gate(f"all {n_corner} continuous corners closed-loop stable", n_unstable == 0,
     f"{n_unstable} unstable")
gate("worst-corner ||S||inf < 3", worstS < 3.0,
     f"||S||inf = {worstS:.3f} at {worstS_corner}")
print(f"  worst-corner ||S||inf = {worstS:.4f}  (target < 2.5, gate < 3)")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Discretization (Tustin, Ts = 2 ms) + discrete corner sweep
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n= 7. Discretization at Ts = {TS*1e3:.1f} ms (500 Hz) ==")
Gsd = c2d_tustin(Gs_red, TS)
numz, denz = dss_tf_coeffs(Gsd)


def to_sos(num, den):
    """SOS factorization -> list of (b[3], a[3]) with a0 = 1, matching the shipped
    DF2T biquad header format.

    NOTE: this is deliberately NOT the copy of controller_design/synthesize_controller.py's
    `to_sos` @ 51b8962.  That routine pads the ZERO section list up to the pole section
    count but never handles the reverse, so when the numerator factors into MORE
    sections than the denominator (here: 4 real zeros -> 4 first-order sections vs
    2 real + 1 complex pole pair -> 3 sections) `zip` silently DROPS a zero and the
    biquad cascade no longer equals the transfer function.  The shipped share design
    never hit that case (3 real zeros, 3 poles), so the bug is latent there, not live.
    scipy.signal.tf2sos does the pairing correctly; the product is gate-checked against
    the state-space response below either way.
    """
    import scipy.signal as _sig
    rows = _sig.tf2sos(np.asarray(num, float), np.asarray(den, float))
    out = []
    for r in rows:
        a0 = r[3]
        out.append((np.array(r[0:3])/a0, np.array(r[3:6])/a0))
    return out


sos = to_sos(numz, denz)
print(f"  discrete remainder: order {len(denz)-1}, {len(sos)} SOS section(s)")
zz = np.exp(1j*np.linspace(0.01, 3.0, 200))
sos_val = np.ones_like(zz)
for b, a in sos:
    sos_val *= np.polyval(b, zz)/np.polyval(a, zz)
ss_val = np.array([(Gsd.C @ solve(z*np.eye(Gsd.n) - Gsd.A, Gsd.B) + Gsd.D)[0, 0]
                   for z in zz])
gate("SOS factorization matches discrete SS", np.allclose(sos_val, ss_val, rtol=1e-6))

int_d = SS([[1.0]], [[1.0]], [[kI*TS]], [[kI*TS/2.0]])   # Tustin of kI/s
ctrl_d = ss_parallel(int_d, Gsd)


def discrete_cl_poles(Gpc, cd):
    Gpd = c2d_zoh(Gpc, TS)
    D_k = cd.D[0, 0]
    A = np.block([[Gpd.A - Gpd.B*D_k @ Gpd.C, Gpd.B @ cd.C],
                  [-cd.B @ Gpd.C, cd.A]])
    return eigvals(A)


def disc_S_peak(Gpc, cd):
    Gpd = c2d_zoh(Gpc, TS)
    wg = np.logspace(-2, np.log10(np.pi/TS*0.999), 800)
    Lz = dfreqresp(Gpd, TS, wg)*dfreqresp(cd, TS, wg)
    return float(np.max(np.abs(1.0/(1.0 + Lz))))


worst_rad, worstSd, worstSd_corner = 0.0, 0.0, None
for dc in pm.drive_corners():
    for v0 in V0_SET:
        Gc_p, _, _ = corner_drive_plant(dc, v0)
        worst_rad = max(worst_rad, np.max(np.abs(discrete_cl_poles(Gc_p, ctrl_d))))
        Sp = disc_S_peak(Gc_p, ctrl_d)
        if Sp > worstSd:
            worstSd, worstSd_corner = Sp, (dict(dc), v0)
gate("discrete closed loop stable on ALL corners (|z| < 1)", worst_rad < 1.0,
     f"max |z| = {worst_rad:.4f}")
print(f"  discrete worst-corner ||S||inf = {worstSd:.4f} at {worstSd_corner}")

# ─────────────────────────────────────────────────────────────────────────────
# 8. Time-domain sims (discrete, +-I_CLAMP clamp, back-calculation anti-windup)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n= 8. Time-domain sims (Ts = 2 ms, clamp +-{I_CLAMP:.0f} A) ==")


class BiquadController:
    """The shipped firmware pattern verbatim: DF2T biquad cascade + trapezoidal
    integrator with back-calculation anti-windup ON THE INTEGRATOR ONLY.
    ADAPTED from controller_design/synthesize_controller.py:207-233 @ 51b8962 (motor
    CURRENT output clamped to +-I_CLAMP; no r0 offset, no [0.15, 0.85] rails).

    Kept for the UNSATURATED equivalence gate and to DOCUMENT why it is not the
    scheme the sims use -- see the ConditionedController note below."""

    def __init__(self, sos, kI, Ts, umin=-I_CLAMP, umax=I_CLAMP):
        self.sos = [(list(b), list(a)) for b, a in sos]
        self.st = [[0.0, 0.0] for _ in sos]
        self.kI, self.Ts = kI, Ts
        self.umin, self.umax = umin, umax
        self.integ, self.eprev = 0.0, 0.0

    def step(self, e, sat=True):
        x = e
        for (b, a), s in zip(self.sos, self.st):
            y = b[0]*x + s[0]
            s[0] = b[1]*x - a[1]*y + s[1]
            s[1] = b[2]*x - a[2]*y
            x = y
        integ_new = self.integ + self.kI*self.Ts*0.5*(e + self.eprev)
        u = x + integ_new
        if sat:
            if u > self.umax:
                integ_new -= (u - self.umax); u = self.umax
            elif u < self.umin:
                integ_new += (self.umin - u); u = self.umin
        self.integ, self.eprev = integ_new, e
        return u


# DEVIATION from the brief ("simple clamped-integrator anti-windup mirroring the
# DiscreteController pattern"), forced by a measured property of this design:
#
#   the NON-INTEGRAL branch of the Youla-H drive controller has a low-frequency gain
#   of Gs_red(0) = <printed below> A per (m/s) of error (745 A/(m/s) as synthesized
#   2026-08-16).  With the +-12 A actuator that branch ALONE saturates at
#   |e| > I_CLAMP/Gs_red(0) ~ 16 mm/s, so on a 2 m/s step the lag states of the biquad
#   cascade wind up just as hard as the integrator does.  Back-calculating only the
#   integrator therefore does NOT de-wind the controller: measured with BiquadController
#   the 0->2 m/s step leaves a -0.48 m/s standing error and a 22 mm/s peak-to-peak limit
#   cycle (both gate failures).  The inline figures here are indicative -- the values the
#   run actually measured are printed by §8/§8c and written to drive_siso_metrics.txt.
#
# The sims below therefore use HANUS CONDITIONING on the state-space realization of
# the SAME controller (self-conditioned form; Hanus/Kinnaert/Henrotte 1987):
#   u_unsat = Cd x + Dd e ; u = sat(u_unsat)
#   x[k+1]  = (Ad - Bd Dd^-1 Cd) x + Bd Dd^-1 u
# which is EXACTLY equivalent to x[k+1] = Ad x + Bd e whenever unsaturated (gated
# below), and de-winds every controller state, not just the integrator.  Dd is a
# nonzero scalar here (Dd = Gsd.D + kI*Ts/2), so the inverse is trivial.
# CONSEQUENCE FOR FIRMWARE: a Teensy implementation of this baseline needs the
# state-space/conditioned form, not the shipped biquad+integrator AW pattern.  This
# is noted in drive_siso_coeffs.h and is itself a Phase-6 "Teensy cost" datapoint.
class ConditionedController:
    """Hanus self-conditioned discrete controller with output clamp."""

    def __init__(self, cd, umin=-I_CLAMP, umax=I_CLAMP):
        self.Ad, self.Bd = cd.A, cd.B
        self.Cd, self.Dd = cd.C, float(cd.D[0, 0])
        assert abs(self.Dd) > 1e-9, "Hanus conditioning needs an invertible D"
        self.Ac = self.Ad - self.Bd @ self.Cd/self.Dd
        self.x = np.zeros((cd.n, 1))
        self.umin, self.umax = umin, umax

    def step(self, e, sat=True):
        uu = float((self.Cd @ self.x).item()) + self.Dd*e
        u = min(self.umax, max(self.umin, uu)) if sat else uu
        self.x = self.Ac @ self.x + self.Bd*(u/self.Dd)
        return u


def simulate(ctrl, Gpc, ref_fn, n_steps, v_init=0.0, sat=True):
    Gpd = c2d_zoh(Gpc, TS)
    xg = np.zeros((Gpd.n, 1))
    ys, us, rs = [], [], []
    for k in range(n_steps):
        v = (Gpd.C @ xg).item() + v_init
        r = ref_fn(k*TS)
        u = ctrl.step(r - v, sat=sat)
        xg = Gpd.A @ xg + Gpd.B*u
        ys.append(v); us.append(u); rs.append(r)
    return np.array(ys), np.array(us), np.array(rs)


def settle_time(y, target, band, t0_idx=0):
    out = np.where(np.abs(y[t0_idx:] - target) > band)[0]
    return (out[-1] + 1 + t0_idx)*TS if len(out) else t0_idx*TS


GS_DC = Gs_red.dcgain()
print(f"  non-integral branch LF gain Gs_red(0) = {GS_DC:.1f} A/(m/s) "
      f"=> the biquad branch alone saturates at |e| > {I_CLAMP/abs(GS_DC)*1e3:.1f} mm/s")

# unsaturated equivalence: the shipped biquad+integrator realization and the Hanus
# state-space realization must be the SAME linear controller.
_e = np.concatenate([np.full(30, 0.3), np.full(30, -0.2),
                     0.1*np.random.default_rng(20260804).standard_normal(40)])
_cb = BiquadController(sos, kI, TS); _cc = ConditionedController(ctrl_d)
_ub = np.array([_cb.step(float(v), sat=False) for v in _e])
_uc = np.array([_cc.step(float(v), sat=False) for v in _e])
gate("biquad+integrator and conditioned state-space realizations agree (unsaturated)",
     np.max(np.abs(_ub - _uc)) < 1e-8*max(1.0, np.max(np.abs(_ub))),
     f"max |diff| = {np.max(np.abs(_ub - _uc)):.2e} A")

# documented evidence for the AW deviation: the shipped scheme on the same step
_yb, _ub2, _ = simulate(BiquadController(sos, kI, TS), G22,
                        lambda t: 2.0 if t >= 0.02 else 0.0, 2500)
print(f"  [reference] shipped integrator-only AW on the same step: final err = "
      f"{_yb[-1]-2.0:+.3f} m/s, tail p-p = {np.ptp(_yb[-250:]):.2e} m/s  "
      f"(this is why the sims use Hanus conditioning)")

# 8a. velocity step 0 -> 2 m/s
N1 = 2500                                   # 5 s
step_ref = lambda t: 2.0 if t >= 0.02 else 0.0
y1, u1, r1 = simulate(ConditionedController(ctrl_d), G22, step_ref, N1)
t_set1 = settle_time(y1, 2.0, 0.02*2.0, t0_idx=10) - 0.02
ovs1 = (np.max(y1) - 2.0)/2.0*100
print(f"  step 0->2 m/s: peak i = {np.max(np.abs(u1)):.3f} A, "
      f"2% settle = {t_set1:.3f} s, overshoot = {ovs1:.1f} %, "
      f"final err = {y1[-1]-2.0:.2e}")
gate("step: settles < 3 s to 2%", t_set1 < 3.0, f"{t_set1:.3f} s")
gate("step: zero steady-state error", abs(y1[-1] - 2.0) < 1e-4,
     f"final err = {y1[-1]-2.0:.2e}")
gate(f"step: current inside the +-{I_CLAMP:.0f} A clamp", np.max(np.abs(u1)) <= I_CLAMP + 1e-9,
     f"peak |i| = {np.max(np.abs(u1)):.3f} A")
# no limit cycle: the tail must be quiescent
tail = y1[-250:]
gate("step: no limit cycle (quiescent tail)", np.ptp(tail) < 1e-5,
     f"tail p-p = {np.ptp(tail):.2e} m/s")

# 8b. regen event 2 -> 0 m/s, forced onto the negative current rail
# The reference is stepped to 0 from a 2 m/s initial condition; the controller
# saturates negative (braking / regen) and must recover cleanly with no windup hang.
N2 = 2500
regen_ref = lambda t: 0.0
y2, u2, r2 = simulate(ConditionedController(ctrl_d), G22, regen_ref, N2, v_init=2.0)
neg_peak = float(np.min(u2))
t_set2 = settle_time(y2, 0.0, 0.02*2.0)
on_rail = np.sum(u2 <= -I_CLAMP + 1e-9)
print(f"  regen 2->0 m/s: peak i = {neg_peak:.3f} A, on the -{I_CLAMP:.0f} A rail for "
      f"{on_rail*TS*1e3:.0f} ms, 2% settle = {t_set2:.3f} s, "
      f"final v = {y2[-1]:.2e} m/s")
gate(f"regen: hits the -{I_CLAMP:.0f} A rail (a genuine saturated episode)", neg_peak <= -I_CLAMP + 1e-9,
     f"min i = {neg_peak:.3f} A")
gate(f"regen: current inside the +-{I_CLAMP:.0f} A clamp", np.min(u2) >= -I_CLAMP - 1e-9)
gate("regen: recovers (2% settle < 3 s, no windup hang)", t_set2 < 3.0, f"{t_set2:.3f} s")
gate("regen: zero steady-state error after saturation", abs(y2[-1]) < 1e-4,
     f"final v = {y2[-1]:.2e} m/s")
tail2 = y2[-250:]
gate("regen: no limit cycle (quiescent tail)", np.ptp(tail2) < 1e-5,
     f"tail p-p = {np.ptp(tail2):.2e} m/s")
# Windup check.  GATE REDEFINED at the +-20 A clamp (2026-08-04), and the redefinition
# is the honest one: the old gate was an ABSOLUTE bound (reverse excursion < 0.10 m/s =
# 5 % of the 2 m/s transient), which was only meetable because at +-5 A the regen
# transient was RAIL-LIMITED for ~1 s and the loop's own linear undershoot never
# developed.  At +-20 A the same (unchanged) controller runs close to its linear
# response, whose undershoot is 14.8 % -- IDENTICAL to the 0->2 m/s step's 14.8 %
# overshoot and consistent with ||T||inf = 1.36.  That is loop shaping, not windup, and
# an absolute bound would be measuring the wrong thing.
# The gate now measures WINDUP DIRECTLY: run the same event with the clamp REMOVED and
# require that saturation adds no extra reverse excursion.  A windup hang shows up as a
# saturated excursion materially deeper than the unsaturated one; loop overshoot cancels
# out of the comparison, so the gate is clamp-agnostic.
_y2u, _u2u, _ = simulate(ConditionedController(ctrl_d), G22, regen_ref, N2,
                         v_init=2.0, sat=False)
exc_sat, exc_lin = float(np.min(y2)), float(np.min(_y2u))
windup_excess = exc_lin - exc_sat          # > 0 means saturation deepened the excursion
print(f"  regen undershoot: saturated {exc_sat:.4f} m/s vs unsaturated (linear) "
      f"{exc_lin:.4f} m/s  =>  windup excess = {windup_excess:+.4f} m/s "
      f"(step overshoot for reference: {ovs1:.1f} % = {ovs1/100*2.0:.4f} m/s)")
gate("regen: no windup (saturated undershoot within 2% of the unsaturated linear one)",
     windup_excess < 0.02*2.0, f"excess = {windup_excess:+.4f} m/s "
     f"(sat {exc_sat:.4f} vs lin {exc_lin:.4f})")

# ─────────────────────────────────────────────────────────────────────────────
# 8c. Integrator-only AW vs Hanus: where is the boundary at this clamp?
# ─────────────────────────────────────────────────────────────────────────────
# e_sat = I_CLAMP/|Gs_red(0)| is the error at which the NON-INTEGRAL branch alone
# rails the actuator; above it the biquad lag states wind up and integrator-only
# back-calculation cannot de-wind them.  e_sat scales LINEARLY with the clamp, so the
# question "is Hanus still needed?" must be re-answered on every clamp change, not
# assumed.  RE-RUN 2026-08-16 at the firmware's 12 A clamp (was 20 A): e_sat drops x0.6
# from the clamp alone, and Gs_red(0) has also moved with the re-identified plant, so
# both terms changed.  The scan below is the answer, printed rather than argued.
E_SAT = I_CLAMP/abs(GS_DC)
print(f"\n= 8c. integrator-only AW boundary (e_sat = I_CLAMP/|Gs_red(0)| = "
      f"{E_SAT*1e3:.1f} mm/s) ==")
aw_scan = []
for amp in (0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0):
    yb, _, _ = simulate(BiquadController(sos, kI, TS), G22,
                        (lambda a: (lambda t: a if t >= 0.02 else 0.0))(amp), 2500)
    ok = abs(yb[-1] - amp) < 1e-4 and np.ptp(yb[-250:]) < 1e-5
    aw_scan.append((amp, float(yb[-1] - amp), float(np.ptp(yb[-250:])), ok))
    print(f"   step {amp:5.2f} m/s: final err = {yb[-1]-amp:+.3e} m/s, "
          f"tail p-p = {np.ptp(yb[-250:]):.2e} m/s  -> "
          f"{'integrator-only AW OK' if ok else 'integrator-only AW FAILS'}")
_ok = [a for a, _, _, o in aw_scan if o]
_bad = [a for a, _, _, o in aw_scan if not o]
AW_BOUNDARY = (max(_ok) if _ok else None, min(_bad) if _bad else None)
print(f"   boundary: integrator-only AW holds up to ~{AW_BOUNDARY[0]} m/s and fails "
      f"from ~{AW_BOUNDARY[1]} m/s (vs e_sat = {E_SAT*1e3:.1f} mm/s)")

# ─────────────────────────────────────────────────────────────────────────────
# 9. Emit artifacts
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs(FIGDIR, exist_ok=True)

with open(os.path.join(FIGDIR, "drive_siso_step.csv"), "w", encoding="utf-8") as f:
    f.write("t_s,v_ref,v,i_cmd,regen_v_ref,regen_v,regen_i_cmd\n")
    n = max(len(y1), len(y2))
    for k in range(n):
        t = k*TS
        a = (f"{r1[k]:.6f},{y1[k]:.6f},{u1[k]:.6f}" if k < len(y1) else "nan,nan,nan")
        b = (f"{r2[k]:.6f},{y2[k]:.6f},{u2[k]:.6f}" if k < len(y2) else "nan,nan,nan")
        f.write(f"{t:.4f},{a},{b}\n")


# ── the SHIPPED (float32) realization ────────────────────────────────────────
# The header emits `static const float` arrays, so what a firmware implementation
# actually computes with is the float32 ROUNDING of the synthesis matrices, not the
# float64 matrices themselves.  Those are not interchangeable here: the realization
# carries an exact integrator (an eigenvalue at 1) and a second mode at ~0.9999, so a
# ~1e-7 coefficient perturbation is integrated rather than damped.  Replaying the float64
# matrices produced reference vectors that no implementation of this header could
# reproduce (measured: 1.7e-2 A divergence over the regen episode).
# Therefore: the coefficients are rounded to float32 ONCE, here; the header text and the
# replay vectors are both generated from that single rounded set, so header, CSV and a
# compiled Teensy constant table all hold bit-identical values.  The state RECURSION stays
# in float64 -- that is a statement about the implementation's arithmetic, which the header
# does not fix, and §check4 of validate_drive_siso.py measures what float32 arithmetic
# would cost on top.
# NOTE the synthesis and every gate above remain on the float64 matrices: rounding is an
# emission concern, not a design concern.
def _f32(M):
    """Round to float32 and widen back, so subsequent arithmetic is exact in float64."""
    return np.asarray(np.float32(np.asarray(M, dtype=float)), dtype=np.float64)


AD_H = _f32(ctrl_d.A)
BD_H = _f32(ctrl_d.B)
CD_H = _f32(ctrl_d.C)
DD_H = float(np.float32(ctrl_d.D[0, 0]))
# AC is derived from the ALREADY-ROUNDED AD/BD/CD/DD and then rounded itself, so the
# identity AC == AD - BD*CD/DD holds to a float32 rounding of the largest entry (~1e-6)
# rather than to the difference of two independently-rounded quantities (~4e-6).
AC_H = _f32(AD_H - BD_H @ CD_H/DD_H)
_ac_resid = float(np.max(np.abs(AC_H - (AD_H - BD_H @ CD_H/DD_H))))
print(f"\n= 8d. shipped float32 realization ==")
print(f"  AC identity residual after rounding = {_ac_resid:.3e} "
      f"(float32 half-ulp of max|AC| = {np.max(np.abs(AC_H)):.1f})")


class HeaderController(ConditionedController):
    """ConditionedController driven by the SHIPPED float32 coefficients.

    Identical recursion; only the constants differ.  This is what the replay vectors are
    generated with, and what an implementation reading drive_siso_coeffs.h reproduces.
    """

    def __init__(self, umin=-I_CLAMP, umax=I_CLAMP):
        self.Ad, self.Bd, self.Cd, self.Dd = AD_H, BD_H, CD_H, DD_H
        self.Ac = AC_H
        self.x = np.zeros((AD_H.shape[0], 1))
        self.umin, self.umax = umin, umax


# ── replay reference vectors for the firmware round ──────────────────────────
# The firmware implements the HANUS form, so the vectors replayed against it must be
# generated by the Hanus recursion (not the biquad cascade -- the two agree only while
# unsaturated, an equivalence gated in §8) and with the SHIPPED float32 coefficients
# (HeaderController above, not ConditionedController).  Two episodes:
#   (a) unsaturated small-signal: mixed steps + seeded noise, |u| well inside the clamp,
#       which exercises the linear state recursion and nothing else;
#   (b) saturated: the §8b regen 2->0 error sequence verbatim, where the clamp is active
#       for a sustained interval, which exercises the conditioning term Bd*u/Dd.
# FIXED SEED (20260816) so the vectors are reproducible byte for byte.
_rng = np.random.default_rng(20260816)
_e_small = np.concatenate([
    np.zeros(10),
    np.full(40, 1.0), np.full(30, -0.6), np.zeros(20),
    np.full(35, 0.35), np.full(35, -0.25), np.zeros(30),
])
_e_small = _e_small + 0.15*_rng.standard_normal(_e_small.size)
# scale so the unsaturated peak lands at ~40 % of the clamp: "well inside", with enough
# amplitude that float32 replay error is measured against a real signal, not against noise.
_probe = HeaderController()
_u_probe = np.array([_probe.step(float(v), sat=False) for v in _e_small])
_e_small = _e_small*(0.40*I_CLAMP/np.max(np.abs(_u_probe)))
_c_small = HeaderController()
_u_small = np.array([_c_small.step(float(v), sat=True) for v in _e_small])
gate("replay (a) is genuinely unsaturated", np.max(np.abs(_u_small)) < I_CLAMP - 1e-9,
     f"peak |u| = {np.max(np.abs(_u_small)):.3f} A of {I_CLAMP:.0f} A")

# The regen episode's STIMULUS is the §8b closed-loop error sequence; its RESPONSE is
# re-derived here through the shipped float32 coefficients (u2 came from the float64
# controller, so it is not the right target for a header-replay check).
_e_sat = r2 - y2
_c_sat = HeaderController()
_u_sat = np.array([_c_sat.step(float(v), sat=True) for v in _e_sat])
gate("replay (b) is genuinely saturated", np.min(_u_sat) <= -I_CLAMP + 1e-9,
     f"{int(np.sum(_u_sat <= -I_CLAMP + 1e-9))} samples on the rail")
print(f"  float32-coefficient replay vs the float64 sim (regen): max |du| = "
      f"{np.max(np.abs(_u_sat - u2)):.3e} A  -- this is the divergence the rounded "
      f"emission removes from the reference vectors")

with open(os.path.join(FIGDIR, "drive_siso_replay.csv"), "w", encoding="utf-8") as f:
    f.write("# drive_siso_replay.csv — GENERATED by synthesize_drive_siso.py.  "
            "DO NOT EDIT BY HAND.\n")
    f.write(f"# Hanus-conditioned controller reference vectors, Ts = {TS*1e3:.1f} ms, "
            f"clamp +-{I_CLAMP:.1f} A, seed 20260816.\n")
    f.write("# Generated with the FLOAT32-ROUNDED coefficients exactly as emitted in "
            "drive_siso_coeffs.h\n")
    f.write("# (not the float64 synthesis matrices), because the realization contains an\n"
            "# integrator and a mode at ~0.9999, which integrate a 1e-7 coefficient "
            "rounding into\n"
            "# ~1e-2 A over this episode.  The state recursion is float64: these vectors "
            "are the\n"
            "# target for an implementation that reads the header's floats and computes in "
            "double.\n")
    f.write("# episode 'small' : unsaturated small-signal (mixed steps + noise), "
            "controller state starts at zero.\n")
    f.write("# episode 'regen' : the 2->0 m/s regen event, clamp ACTIVE, "
            "controller state starts at zero.\n")
    f.write("# Replay: u_out[k] = clamp(Cd x[k] + Dd e_in[k]); "
            "x[k+1] = Ac x[k] + Bd u_out[k]/Dd.\n")
    # Columns are written at FULL float64 round-trip precision (%.17e), not at the
    # header's %.9e.  e_in is the recursion's input: this realization integrates its
    # input, so truncating the stimulus to 10 significant digits injects a perturbation
    # that grows to ~1e-2 A over the regen episode -- larger than any implementation
    # difference the vectors are meant to expose.  The precision here is about the
    # STIMULUS being reproducible; the coefficients remain float32 (above).
    f.write("episode,k,e_in,u_out\n")
    for k, (e_, u_) in enumerate(zip(_e_small, _u_small)):
        f.write(f"small,{k},{e_:.17e},{u_:.17e}\n")
    for k, (e_, u_) in enumerate(zip(_e_sat, _u_sat)):
        f.write(f"regen,{k},{e_:.17e},{u_:.17e}\n")
print(f"  replay vectors: {len(_e_small)} unsaturated + {len(_e_sat)} saturated samples")


def carr(v):
    return ", ".join(f"{x:.9e}f" for x in v)


def carr17(v):
    """Round-trip-exact formatting.

    The values are already float32 (see _f32), so a C compiler rounds this text back to
    exactly the same float32.  The extra digits exist for the READERS of this header that
    parse it in double precision -- the replay validator, chiefly.  %.9e is enough to
    round-trip a float32 only if the parser targets float32; parsed as a double it lands
    ~1e-10 away, which this integrating realization amplifies into a clamp-timing flip and
    ~1e-2 A of apparent replay mismatch.  Measured, not hypothesised.
    """
    return ", ".join(f"{x:.17e}f" for x in v)


def cmat(name, M, comment):
    """Emit a row-major static const float array (2-D) for the firmware."""
    M = np.atleast_2d(np.asarray(M, float))
    rows, cols = M.shape
    s = f"// {comment}\nstatic const float {name}[{rows}][{cols}] = {{\n"
    for r in M:
        s += f"    {{ {carr17(r)} }},\n"
    return s + "};\n"


# ── Coefficient-header emission ─────────────────────────────────────────────
# TWO files are written from ONE emitter, so the study copy and the firmware copy can
# never drift:
#   controller_design_MIMO/drive_siso_coeffs.h   — study artifact (MIMO comparison)
#   teensy_controller/drive_controller_coeffs.h  — the FIRMWARE copy, included by
#                                                  teensy_controller/drive_controller.h
# Only the top banner differs; every coefficient below it is byte-identical.

_BANNER_STUDY = """// drive_siso_coeffs.h — GENERATED by controller_design_MIMO/synthesize_drive_siso.py
// DO NOT EDIT BY HAND.  Regenerate after bench calibration (mimo_system_model.md §9).
//
// *** STUDY COPY — NOT INCLUDED BY ANY FIRMWARE SOURCE. ***  This is the Phase-3
// DECENTRALIZED BASELINE drive controller for the MIMO study (controller_design_MIMO/),
// emitted in the shipped share-controller header format so the Teensy implementation
// cost is quantified on equal terms.
// The FIRMWARE copy of these same coefficients EXISTS as of fw v10 and is written by
// this same script to teensy_controller/drive_controller_coeffs.h; the runtime that
// consumes it is teensy_controller/drive_controller.h (Hanus form, double states),
// enabled by USE_YOULA_DRIVE_CONTROLLER.  Both files are emitted from one code path —
// do not hand-edit either.
"""

_BANNER_FW = """// drive_controller_coeffs.h — GENERATED by
// controller_design_MIMO/synthesize_drive_siso.py.  DO NOT EDIT BY HAND.
// Regenerate after bench calibration (mimo_system_model.md §9), or after any change to
// the motor-current clamp (MOTOR_I_CMD_MAX in teensy_controller.ino must equal
// DRIVE_CTRL_I_MAX below — the anti-windup design depends on it).
//
// *** THIS IS THE FIRMWARE COPY. ***  Included by teensy_controller/drive_controller.h
// and compiled into the Teensy build when USE_YOULA_DRIVE_CONTROLLER is 1 (fw v10+).
// The study copy of the same coefficients is controller_design_MIMO/drive_siso_coeffs.h;
// both are written from one emitter in the generating script, so they cannot drift.
"""


def _emit_coeffs(path, banner):
    with open(path, "w", encoding="utf-8") as f:
        f.write(banner)
        f.write(f"""//
// SISO Youla-H velocity controller for the SC001 drive channel:
//   Gc(z) = R(z) + kI*Ts/2*(z+1)/(z-1),  e = v_ref - v [m/s]  ->  i_cmd [A]
// H-inf mixed sensitivity (gamma = {g_used:.4f}) + Youla-H DC rescale (T(0) = 1 exact),
// Tustin at Ts = {TS*1e3:.1f} ms (500 Hz motor channel; VESC UART frame floor).
// R(z) is {len(sos)} DF2T biquad section(s); the integrator is kept separate to match the
// shipped share-controller header layout byte for byte.
//
// *** ANTI-WINDUP WARNING (differs from share_controller.h) ***
// The shipped share controller de-winds by back-calculating ONLY the integrator.  That
// is NOT sufficient here: the non-integral branch R has a low-frequency gain of
// {GS_DC:.1f} A/(m/s), so against the +-{I_CLAMP:.0f} A clamp the biquad cascade alone saturates for
// |e| > {I_CLAMP/abs(GS_DC)*1e3:.1f} mm/s and its lag states wind up independently of the integrator.
// Measured on the 0->2 m/s step: integrator-only AW leaves a {_yb[-1]-2.0:+.2f} m/s standing error
// and a {np.ptp(_yb[-250:])*1e3:.1f} mm/s limit cycle.
// RE-CHECKED at the firmware's +-{I_CLAMP:.0f} A clamp (2026-08-15 operator decision) on the
// re-identified plant (2026-08-16 calibration): e_sat scales with the clamp, so it must be
// re-answered on every clamp change.  Integrator-only AW is CLEAN for steps up to
// ~{AW_BOUNDARY[0]} m/s (final error < 1e-4 m/s, no limit cycle) and breaks from ~{AW_BOUNDARY[1]} m/s upward.
// It still FAILS the 0->2 m/s gate, so the Hanus form remains REQUIRED for this baseline.
// A correct implementation must condition the FULL
// controller state (Hanus self-conditioned form, used in the synthesis sims):
//     u_unsat = Cd x + Dd e ;  u = clamp(u_unsat) ;
//     x[k+1]  = (Ad - Bd*Cd/Dd) x + Bd*u/Dd            (Dd = {ctrl_d.D[0, 0]:.9e})
// i.e. this baseline costs a {ctrl_d.n}-state state-space realization on the Teensy, not a
// biquad cascade.  Recorded as a Phase-6 "Teensy implementation cost" datapoint.
// The realization is emitted below (DRIVE_CTRL_AD/BD/CD/DD/AC); replay reference vectors
// for a firmware implementation are in figures/drive_siso_replay.csv.
#pragma once

#define DRIVE_CTRL_TS_US   {int(TS*1e6)}      // controller update period, microseconds
#define DRIVE_CTRL_NSOS    {len(sos)}
static const float DRIVE_CTRL_KI = {kI:.9e}f;   // integrator gain (continuous kI, Tustin in code)
// constexpr (not plain const) so the firmware can static_assert these against its own
// MOTOR_I_CMD_MAX: a namespace-scope `const float` is NOT a constant expression in C++17, so
// the clamp-pairing guard would not compile against it.  Same float32 values either way.
static constexpr float DRIVE_CTRL_I_MIN = {-I_CLAMP:.9e}f;   // A, motor current clamp (regen rail)
static constexpr float DRIVE_CTRL_I_MAX = {I_CLAMP:.9e}f;    // A, motor current clamp (drive rail)

// biquad sections: b0 b1 b2 a1 a2 (a0 = 1)
static const float DRIVE_CTRL_SOS[DRIVE_CTRL_NSOS][5] = {{
""")
        for b, a in sos:
            f.write(f"    {{ {carr(b)}, {a[1]:.9e}f, {a[2]:.9e}f }},\n")
        f.write("};\n")

        # ── Hanus state-space realization (what the firmware actually runs) ──
        _n = ctrl_d.n
        _Dd = DD_H
        _Ac = AC_H
        f.write(f"""
// ── Hanus self-conditioned state-space realization ──────────────────────────
// This is the FULL controller Gc(z) = R(z) + kI*Ts/2*(z+1)/(z-1) realized as one
// {_n}-state discrete system, NOT a second copy of the biquads above.  DRIVE_CTRL_SOS is
// retained only for the unsaturated-equivalence test; the state-space form below is the
// one to implement, because it is the only one that de-winds correctly (see the
// anti-windup warning at the top of this file).
//
// Dimensions: n = {_n} states, 1 input (velocity error e [m/s]), 1 output (i_cmd [A]).
//   AD is n x n, BD is n x 1, CD is 1 x n, DD is scalar, AC = AD - BD*CD/DD is n x n.
// All arrays are ROW-MAJOR.
//
// Update law, once per DRIVE_CTRL_TS_US, with e = v_ref - v_actual [m/s]:
//   u_unsat = sum_j CD[0][j]*x[j] + DD*e
//   u       = clamp(u_unsat, DRIVE_CTRL_I_MIN, DRIVE_CTRL_I_MAX)     -> i_cmd [A]
//   x_next[i] = sum_j AC[i][j]*x[j] + BD[i][0]*(u/DD)
//   x <- x_next
// Note the conditioning: the state update is driven by the CLAMPED u, not by e.  While
// unsaturated this is algebraically identical to x_next = AD x + BD e (that identity is
// what makes AD useful as a cross-check); once clamped it is what prevents windup.
// Replay vectors for both regimes: figures/drive_siso_replay.csv.
//
// NUMERICAL CAUTION — read before implementing.
// This realization contains an exact integrator (an AD eigenvalue at 1) and a second mode
// at ~0.9999, alongside CD entries of order 50.  Perturbations are INTEGRATED, not damped,
// so coefficient precision and arithmetic precision both matter more than usual here.
//   * COEFFICIENTS.  The values below are the exact float32 roundings of the synthesis
//     matrices, and figures/drive_siso_replay.csv was generated from these same rounded
//     values.  Header, replay vectors and a compiled constant table therefore hold
//     bit-identical coefficients.  (Emitting float64 text instead put the reference
//     vectors 1.7e-2 A away from anything this header can reproduce.)  AC is derived from
//     the rounded AD/BD/CD/DD and then rounded, so AC == AD - BD*CD/DD holds to
//     {_ac_resid:.1e} — a float32 rounding of AC's largest entry, not a compounding error.
//   * ARITHMETIC.  The replay vectors assume a float64 (double) state recursion.  Running
//     the recursion in float32 costs a further ~1e-2 A on the saturated regen episode —
//     measured, not estimated (validate_drive_siso.py check 4).  The divergence appears
//     at rail RELEASE rather than by slow accumulation, so it is not bounded by shortening
//     the run.  A float32 state recursion is NOT adequate for this controller; use double
//     (or fixed point with equivalent headroom).
// Replay comparisons should be toleranced on the OUTPUT (a few mA of i_cmd), never on the
// individual states.
#define DRIVE_CTRL_NSTATES {_n}
static const float DRIVE_CTRL_DD = {_Dd:.17e}f;   // direct feedthrough, A per (m/s)

""")
        f.write(cmat("DRIVE_CTRL_AD", AD_H,
                     f"AD [{_n}][{_n}] — unconditioned state matrix (cross-check only)"))
        f.write("\n")
        f.write(cmat("DRIVE_CTRL_BD", BD_H, f"BD [{_n}][1] — input matrix"))
        f.write("\n")
        f.write(cmat("DRIVE_CTRL_CD", CD_H, f"CD [1][{_n}] — output matrix"))
        f.write("\n")
        f.write(cmat("DRIVE_CTRL_AC", _Ac,
                     f"AC [{_n}][{_n}] = AD - BD*CD/DD — the CONDITIONED state matrix "
                     f"(use this one)"))


_emit_coeffs(os.path.join(HERE, "drive_siso_coeffs.h"), _BANNER_STUDY)
_emit_coeffs(os.path.join(HERE, os.pardir, "teensy_controller",
                          "drive_controller_coeffs.h"), _BANNER_FW)

with open(os.path.join(HERE, "drive_siso_metrics.txt"), "w", encoding="utf-8") as f:
    f.write(f"""SISO Youla-H DRIVE baseline — synthesis metrics (GENERATED by
controller_design_MIMO/synthesize_drive_siso.py; plan Phase 3 / §5 bullet 1)

── plant (plant_mimo.drive_plant, nominal OP/params) ──
states               = {G22.n}  (Pade(2) VESC delay + tau_v lag + 1st-order mechanics)
G22(0)               = {G22.dcgain():.6f} (m/s)/A
mechanical pole      = {-pm.b_eff(OP0, P0)/P0['m_eff']:.6f} rad/s  (near-integrator)
b_eff                = {pm.b_eff(OP0, P0):.6f} N*s/m   force/amp = {pm.force_per_amp(P0):.6f} N/A
i_m0 at the OP       = {pm.bus_current_gains(OP0, P0)[2]:.4f} A   vs a measured cruise hold of
                       4.5 +- 0.4 A: the model runs ~9 % below the band's centre and just
                       under its lower edge, NOT inside it.  Consistent with the unmeasured
                       eta_dt = 0.85, which scales every absolute force.  The claim this
                       supports is a factor-of-4 correction (the retired model gave 0.973 A),
                       not agreement to within the measurement.

PLANT RE-IDENTIFIED 2026-08-16 (calibration/motor_id_20260815.md).  k_t (4.266e-3 N*m/A
from the measured flux linkage), R_m (22.6 mOhm), m_eff (3.5 kg), r_t (0.0762 m flywheel
rolling radius), tau_v (1.0 ms) and the drag law (b_eff 0.32 N*s/m local slope + F_c
1.2 N Coulomb) are all MEASURED.  Effect on the design plant:
      G22(0)  3.7085 -> {G22.dcgain():.4f} (m/s)/A      pole  -0.1219 -> {-pm.b_eff(OP0, P0)/P0['m_eff']:.4f} rad/s
      K_F     1.3338 -> {pm.force_per_amp(P0):.4f} N/A
The previous note here attributed b_eff to a modelled motor free-run loss (0.3596 of
0.3719 N*s/m).  That attribution is RETIRED: the measured drag curve is Coulomb-dominated
and concave, and pure viscous is excluded at chi^2 x1400, so the old decomposition had the
wrong shape, not merely the wrong number.  The Youla-H correction stays tiny because the
plant is still a near-integrator.

── weights (plan §3, drive channel; papers' philosophy, target bandwidth {WC_TARGET:g} rad/s) ──
Wp = strictly_proper_2nd_order_weight(dc = {WP_DC:g}, wc = {WC:g} rad/s)
Wd = makeweight(0.5, {WD_WC:g}, 40)
Wu = makeweight({WU_DC}, {WU_WC:g}, {WU_HF:g})

DEVIATION 1 (Wd break).  The papers' Wd break is 18 rad/s.  Placing the T-rolloff
weight BELOW the Wp corner makes Wp and Wd contend over the same decade, inflating
gamma and collapsing the achieved crossover.  Break set to 2.5x the Wp corner, which
preserves the papers' intent (T rolled off just above crossover).

DEVIATION 2 (Wp corner above the target).  On this plant the achieved S/T crossover
lands consistently BELOW the Wp corner (gamma_opt >> 1 throughout: the specs are being
shaped, not met).  Wp is therefore cornered at {WC:g} rad/s.

LADDER RE-RUN 2026-08-16 on the CALIBRATED plant.  The previous ladder is VOID: the plant
DC gain fell x2.6 and the pole moved, so the old CHOSEN rung (WC=50, Wu(0.2,300,10)) now
achieves 14.35 rad/s instead of 20.7.  Ladder actually run (Wd break = 2.5*WC,
Wu = makeweight(dc, 300, hf); worst ||S|| over the 24 drive corners at pole_factor
in {{0.5, 3}}):
    WC=24, Wu(0.3 ,300,20 ) -> g_opt 20.17, wc  8.25, PM 59.4, worst ||S|| 1.451  (wc < 12: FAILS)
    WC=24, Wu(0.1 ,300, 5 ) -> g_opt 11.53, wc 10.55, PM 49.6, worst ||S|| 1.925  (wc < 12: FAILS)
    WC=30, Wu(0.1 ,300, 5 ) -> g_opt 13.77, wc 11.93, PM 48.4, worst ||S|| 2.043  (wc < 12: FAILS)
    WC=40, Wu(0.3 ,300,20 ) -> g_opt 28.84, wc 11.22, PM 57.7, worst ||S|| 1.592  (wc < 12: FAILS)
    WC=40, Wu(0.1 ,300, 5 ) -> g_opt 17.40, wc 14.13, PM 46.9, worst ||S|| 2.224
    WC=45, Wu(0.1 ,300, 5 ) -> g_opt 19.19, wc 15.02, PM 46.4, worst ||S|| 2.309
    WC=50, Wu(0.2 ,300,10 ) -> g_opt 27.47, wc 14.35, PM 53.2, worst ||S|| 1.890  (the OLD choice)
    WC=50, Wu(0.12,300, 6 ) -> g_opt 22.22, wc 15.49, PM 47.7, worst ||S|| 2.253
    WC=50, Wu(0.1 ,300, 5 ) -> g_opt 20.95, wc 15.98, PM 45.9, worst ||S|| 2.392
    WC=50, Wu(0.08,300, 4 ) -> g_opt 19.78, wc 16.22, PM 43.9  (PM < 45: FAILS)
    WC=55, Wu(0.15,300,7.5) -> g_opt 26.07, wc 15.98, PM 49.6, worst ||S|| 2.152  <- CHOSEN
    WC=55, Wu(0.1 ,300, 5 ) -> g_opt 22.71, wc 16.73, PM 45.4, worst ||S|| 2.474
    WC=60, Wu(0.1 ,300, 5 ) -> g_opt 24.45, wc 17.52, PM 45.1, worst ||S|| 2.555  (over the 2.5 target)
    WC=60, Wu(0.05,300,2.5) -> g_opt 21.93, wc 18.07, PM 40.6  (PM < 45: FAILS)
    WC=70, Wu(0.1 ,300, 5 ) -> g_opt 27.91, wc 18.92, PM 44.4  (PM < 45: FAILS)
    WC=80, Wu(0.05,300,2.5) -> g_opt 28.74, wc 20.75, PM 40.3, worst ||S|| 3.238  (both FAIL)

CHOICE (a documented deviation from a literal "most aggressive rung that clears every
gate").  The literal rule selects WC=55, Wu(0.1,300,5): wc 16.73 rad/s, PM 45.4 deg,
worst ||S|| 2.474 — clearing the PM gate by 0.4 deg and the 2.5 ||S|| target by 0.026.
On a plant whose damping slope carries +-15 % and a documented thermal spread, those are
rounding errors, not margins.  WC=55, Wu(0.15,300,7.5) buys 4.2 deg of phase margin and
0.32 of worst-corner peak for 4.5 % of crossover.  The rejected rung is tabulated above so
the trade is auditable.

CONSEQUENCE OF THE CALIBRATION.  The achieved crossover ({wc_ach:.2f} rad/s) is now below the
papers' {WC_TARGET:g} rad/s, where the pre-calibration design reported 20.7.  This is not a
regression in the design; it is the correction of an over-estimated plant gain.  Pushing
past ~17 rad/s on the measured plant costs phase margin quickly.  The rung is selected by
PM and worst-corner ||S|| alone, both linear properties that never see the clamp; the
clamp binds the LARGE-SIGNAL response instead (the 0->2 m/s step rails, below).

── H-inf (DGKF, hinf_mimo.hinfsyn_dgkf on AugPlantMIMO 1x1 blocks) ──
gamma_opt            = {g_opt:.4f}
gamma_used           = {g_used:.4f}
||Tzw||inf           = {tzw_norm:.4f}
H-inf controller ord = {K_H.n}

── Youla-H DC correction (papers' scalar recipe) ──
T_H(0)               = {T0_H:.10f}
gain scale 1/T_H(0)  = {corr:.10f}   (|1 - 1/T_H(0)| = {abs(1-corr):.3e})
Gc_YH raw order      = {Gc_YH_full.n}

── reduction / realization ──
kI                   = {kI:.9f}   (sign gate: positive v-error -> positive current)
remainder order      = {Gs_full.n} -> {Gs_red.n}
HSV (first 8)        = {np.array2string(hsv[:8], precision=4)}
reduced-vs-full relerr = {relerr:.3e}   (gate < 2e-2)
T(0) reduced         = {T0_red:.12f}   (gate |T(0)-1| < 1e-9)

── loop shape / margins (nominal, reduced controller) ──
S/T crossover        = {wc_ach:.2f} rad/s   (H-inf full order: {wc_H:.2f})
||S||inf nominal     = {S_nom:.4f}
||T||inf nominal     = {hinf_norm(nomT):.4f}
phase margin         = {pm_deg:.1f} deg at {w[idx_c]:.2f} rad/s
delay margin         = {dm*1e3:.2f} ms   (gate > 4 ms = 2*Ts)
gain margin          = {'inf' if not np.isfinite(gm_db) else f'{gm_db:.1f} dB'}

── robustness ──
corner family        = 24 drive_corners() x v0 in {V0_SET} = {n_corner} plants
                       (K_v in {{0.5, 1, 2}} x pole_factor in {{0.5, 3}} x tau_v in
                        {{0.5, 5}} ms x Td_v in {{1, 4}} ms.  The calibrated b_eff is a
                        MEASURED LOCAL SLOPE with no v0 term, so v0 no longer enters G22
                        at all and the previous 3-point v0 sweep is exactly degenerate;
                        the speed dependence it stood for — the slope roughly doubles
                        below 1.5 m/s — is now carried by pole_factor's upper corner,
                        widened 2 -> 3 for exactly that reason.)
continuous unstable  = {n_unstable}
worst ||S||inf cont. = {worstS:.4f} at {worstS_corner}
discrete max |z|     = {worst_rad:.4f}
worst ||S||inf disc. = {worstSd:.4f} at {worstSd_corner}

── discretization ──
Ts                   = {TS*1e3:.1f} ms (500 Hz motor channel)
SOS sections         = {len(sos)}  (discrete remainder order {len(denz)-1})
clamp                = +-{I_CLAMP:.1f} A

── anti-windup (DEVIATION 3, forced by a measured property of this design) ──
Gs_red(0)            = {GS_DC:.1f} A/(m/s)  -- the NON-INTEGRAL branch alone saturates the
                       +-{I_CLAMP:.0f} A actuator for |e| > {I_CLAMP/abs(GS_DC)*1e3:.1f} mm/s, so its lag states wind up
                       independently of the integrator.
shipped scheme       = integrator-only back-calculation (share_controller.h pattern).
                       Measured on the 0->2 m/s step: standing error {_yb[-1]-2.0:+.3f} m/s and a
                       {np.ptp(_yb[-250:])*1e3:.1f} mm/s limit cycle -> FAILS the sim gates.
AW boundary RE-RUN 2026-08-16 at the firmware clamp +-{I_CLAMP:.0f} A (2026-08-15 operator
decision; the previous run used +-20 A) and on the re-identified plant.  e_sat scales
linearly with the clamp and inversely with Gs_red(0), and BOTH moved this round, so the
boundary is re-measured rather than rescaled: e_sat = {I_CLAMP/abs(GS_DC)*1e3:.1f} mm/s.  Step-amplitude
scan of the SHIPPED integrator-only scheme (pass = final error < 1e-4 m/s AND tail
p-p < 1e-5 m/s):
""" + "".join(
        f"    step {a:5.2f} m/s: final err {fe:+.3e} m/s, tail p-p {tp:.2e} m/s -> "
        f"{'OK' if o else 'FAILS'}\n" for a, fe, tp, o in aw_scan) + f"""VERDICT: integrator-only AW is CLEAN up to ~{AW_BOUNDARY[0]} m/s steps and breaks from
~{AW_BOUNDARY[1]} m/s.  It STILL fails the 0->2 m/s gate, so the Hanus form remains REQUIRED for
this baseline -- the honest restatement is "needed for large transients", not "needed
always".  Note the direction of travel: lowering the clamp 20 -> 12 A lowers e_sat
proportionally and therefore moves this boundary DOWN, toward the small-signal end.
scheme used          = Hanus self-conditioning on the {ctrl_d.n}-state discrete realization:
                         u_unsat = Cd x + Dd e ; u = clamp(u_unsat)
                         x[k+1]  = (Ad - Bd Cd/Dd) x + Bd u/Dd,  Dd = {ctrl_d.D[0, 0]:.9e}
                       Exactly equivalent to the biquad+integrator form when unsaturated
                       (gated: max |diff| = {np.max(np.abs(_ub - _uc)):.2e} A over an 100-sample sequence).
Teensy cost note     = this baseline needs a {ctrl_d.n}-state state-space realization, NOT the
                       shipped biquad cascade.  Phase-6 implementation-cost datapoint.

── time-domain (discrete, clamped, Hanus-conditioned) ──
step 0->2 m/s : peak i = {np.max(np.abs(u1)):.3f} A, 2% settle = {t_set1:.3f} s,
                overshoot = {ovs1:.1f} %, final err = {y1[-1]-2.0:.2e} m/s,
                tail p-p = {np.ptp(tail):.2e} m/s (no limit cycle)
                NOTE: +-{I_CLAMP:.0f} A gives a_max = K_F*I/m = {pm.force_per_amp(P0)*I_CLAMP/P0['m_eff']:.3f} m/s^2, so 0->2 m/s
                cannot physically take less than ~{2.0/(pm.force_per_amp(P0)*I_CLAMP/P0['m_eff']):.2f} s however the loop is
                shaped.  The {wc_ach:.1f} rad/s design bandwidth is a SMALL-SIGNAL spec; this is
                a large-signal event.  Time on the rail this run: {np.sum(np.abs(u1) >= I_CLAMP - 1e-9)*TS*1e3:.0f} ms.
                The calibration cuts a_max hard (K_F 1.3338 -> {pm.force_per_amp(P0):.4f} N/A and the
                clamp 20 -> {I_CLAMP:.0f} A both push the same way), so large-signal velocity
                moves are now inertia-limited, not loop-limited.
regen 2->0 m/s: peak i = {neg_peak:.3f} A, on the -{I_CLAMP:.0f} A rail {on_rail*TS*1e3:.0f} ms,
                2% settle = {t_set2:.3f} s, final v = {y2[-1]:.2e} m/s,
                reverse excursion = {np.min(y2):.5f} m/s, tail p-p = {np.ptp(tail2):.2e} m/s
                WINDUP GATE (redefined at the 2026-08-04 clamp change, retained here):
                an ABSOLUTE excursion bound only looks meetable when the clamp is low
                enough to rail-limit the transient and suppress the loop's own linear
                undershoot, which makes it a measure of the clamp, not of windup.
                The undershoot now
                measured ({exc_sat:.4f} m/s = {abs(exc_sat)/2.0*100:.1f} %) equals the step's {ovs1:.1f} % overshoot and is
                loop shaping, not windup.  The gate now compares the SATURATED event
                against the SAME event with the clamp removed (linear undershoot
                {exc_lin:.4f} m/s): saturation must add no excursion.  Measured excess
                = {windup_excess:+.4f} m/s (negative = saturation REDUCED the excursion).

── artifacts ──
drive_siso_coeffs.h        (shipped biquad format + the {ctrl_d.n}-state Hanus realization
                            AD/BD/CD/DD/AC; DRIVE_CTRL_ prefix -- study copy)
../teensy_controller/drive_controller_coeffs.h
                            (same content, firmware copy: included by drive_controller.h
                            and compiled in when USE_YOULA_DRIVE_CONTROLLER is 1)
figures/drive_siso_step.csv
figures/drive_siso_replay.csv  ({len(_e_small)} unsaturated + {len(_e_sat)} saturated (e_in, u_out)
                            samples from the Hanus controller, seed 20260816 — the
                            reference vectors a firmware implementation replays against)
""")

print(f"\nartifacts: drive_siso_coeffs.h, "
      f"../teensy_controller/drive_controller_coeffs.h, drive_siso_metrics.txt, "
      f"figures/drive_siso_step.csv, figures/drive_siso_replay.csv")
print("\n" + ("ALL GATES PASSED" if not failures else "FAILURES: " + "; ".join(failures)))
raise SystemExit(1 if failures else 0)
