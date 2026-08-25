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

ESTIMATOR ROUND — 2026-08-16b.  The first closed-loop 'V' runs on fw v11 (ML0136-ML0139)
LIMIT CYCLED at 2.3-2.6 Hz = 14.5-16.3 rad/s -- the design crossover -- at every step size
(0.1, 0.5, 1.0 m/s).  Root cause: the firmware velocity estimator was a ~113 ms boxcar
(~56 ms group delay = 52-58 deg of phase at 16 rad/s, against this design's 49.6 deg phase
margin; measured cmd->v lag 63-73 ms; 0.0177 m/s quantization), and that element was ABSENT
from the synthesis plant.  The loop was closed around a lag the design never saw, so the
margin the design reported was never the margin the hardware had.
This round (a) models the REPLACEMENT edge-period estimator explicitly in plant_mimo
(Td_est(v0) = (N+1)*pitch/(2 v0), velocity-dependent) and sweeps it as a corner axis,
(b) folds in the measured drive-gain datapoint (plant_mimo.K_V_NOM), and (c) re-runs the
weight ladder and every gate on the resulting plant.  Two bench-evidence gates are ADDED:
the 0.5 m/s estimator corner must close with PM > 30 deg, and Td_est at the design speed
must consume < 10 deg at the achieved crossover.  Anti-windup (Hanus) is UNCHANGED and was
verified working on the hardware in those same runs (u_unsat hugged the rail, <= 0.4 A
typical excess, clean releases, ~150 saturation episodes).

Run:  ctrl-venv/Scripts/python.exe synthesize_drive_siso.py
"""

import math
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
TD_EST0 = pm.op_td_est(OP0, P0)
print(f"  K_v = {P0['K_v']:.3f} (evidence-centred nominal, plant_mimo.K_V_NOM); "
      f"effective K_F*K_v = {pm.force_per_amp(P0)*P0['K_v']:.5f} N/A")
print(f"  estimator: pitch = {pm.PITCH_M*1e3:.4f} mm, N = {P0['N_est']}, "
      f"Td_est(v0 = {OP0['v0']} m/s) = {TD_EST0*1e3:.3f} ms")
print("             corners: " + ", ".join(
    f"{v} m/s -> {pm.td_est(v)*1e3:.2f} ms" for v in pm.TD_EST_V0_SET)
    + f"   (design validity floor {pm.V0_VALID_MIN} m/s)")

# PLANT RE-IDENTIFIED 2026-08-16 (calibration/motor_id_20260815.md).  The drive channel
# is no longer a placeholder chain: k_t, R_m, m_eff, r_t, tau_v and the drag law are all
# measured.  That round moved the plant to G22(0) = 1.4112 (m/s)/A, pole -0.0914 rad/s,
# K_F = 0.4516 N/A (from 3.7085 / -0.1219 / 1.3338).
#
# TWO FURTHER CHANGES, 2026-08-16b (this round) -- both material, in OPPOSITE directions:
#   (1) VELOCITY-ESTIMATOR DELAY ADDED.  G22 now ends in Pade2(Td_est(v0)) on the
#       MEASURED speed (plant_mimo.speed_estimator_path).  Td_est = 2.99 ms at the design
#       speed, 11.97 ms at the 0.5 m/s validity floor.  This is phase the loop always had
#       and the design never counted; the ML0136-0139 limit cycle is what that omission
#       costs.  DC gain unaffected (Pade(0) = 1); phase only.
#   (2) DRIVE GAIN RE-CENTRED on measurement, via K_v (plant_mimo.K_V_NOM).
#       The two end-to-end gain measurements disagreed by ~2x at the time.
# Net: the narrowed gain axis pays for the added delay, and the achieved crossover is
# RECOVERED rather than lost (15.98 rad/s, PM 51.9 deg, vs 15.98 / 49.6 last round).
# The Youla-H correction factor remains tiny because the plant is still a near-integrator.
#
# ROUND 2026-08-16c -- K_F FORCE-AXIS CORRECTION (upstream, in plant_mimo.py).  The force
# chain carried the wrong gear ratio AND the wrong radius: PHI 9.49 -> 6.86 (as-fitted 29T
# pinion) and the force radius 0.0762 (flywheel) -> 0.033 (TIRE).  K_F 0.4516 -> 0.7538
# N/A, x1.669.  The drag law rescales with it (b_eff 0.32 -> 0.534 N*s/m, F_c 1.2 -> 2.00 N)
# because it was derived FROM hold currents THROUGH K_F, so i_m0 = 4.07 A is INVARIANT.
# The old ~2x ramp-vs-cruise contradiction DISSOLVES (ratios x1.11-1.21 vs x0.905), so K_v
# is re-centred 1.25 -> 1.00 and the corners narrow {0.85,1.25,1.85} -> {0.75,1.00,1.35}.
# Net plant gain still rises x1.34 (K_F*K_v 0.5645 -> 0.7538) and G22(0) lands at 1.4116.
# NO WEIGHT CHANGE WAS NEEDED: the shipped rung (WC = 60, Wu(0.25, 300, 12.5)) re-runs
# CLEAN on the corrected plant -- every gate passes.  The ladder table below was run on the
# PREVIOUS plant and was NOT re-run; the chosen rung's re-measured numbers are in the
# metrics file (crossover 17.52 rad/s, PM 50.8 deg, DM 50.6 ms, worst ||S|| 2.427 cont /
# 2.535 disc, PM@0.5 41.8 deg).  Every OTHER rung's row is therefore indicative only.
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
# LADDER RE-RUN 2026-08-16b on the ESTIMATOR plant.  The previous ladder is void twice
# over: the estimator delay adds phase at crossover, and the K_v re-centring moves the
# plant gain up 1.25x.  Ladder actually run (Wd break = 2.5*WC, Wu = makeweight(dc, 300,
# hf); PM and wc on the nominal loop, "PM@0.5" = phase margin at the 0.5 m/s estimator
# corner with nominal parameters, worst ||S|| over the 24 drive corners x 3 speeds = 72):
#   WC=24, Wu(0.3 ,300,20  ) -> g_opt 17.76, wc  8.78, PM 57.8, PM@0.5 53.2, ||S|| 1.589  (wc gate FAILS)
#   WC=24, Wu(0.1 ,300, 5  ) -> DGKF a-posteriori gate failed (conditioning) -- no controller
#   WC=30, Wu(0.1 ,300, 5  ) -> g_opt 12.38, wc 12.69, PM 46.4, PM@0.5 39.9, ||S|| 2.489
#   WC=40, Wu(0.1 ,300, 5  ) -> g_opt 15.77, wc 14.80, PM 44.8, PM@0.5 37.2, ||S|| 2.938  (PM FAILS)
#   WC=45, Wu(0.1 ,300, 5  ) -> g_opt 17.43, wc 15.73, PM 44.2, PM@0.5 36.1, ||S|| 3.178  (both FAIL)
#   WC=45, Wu(0.15,300, 7.5) -> g_opt 20.07, wc 15.02, PM 48.3, PM@0.5 40.6, ||S|| 2.608
#   WC=50, Wu(0.1 ,300, 5  ) -> g_opt 19.09, wc 16.73, PM 43.7, PM@0.5 35.0, ||S|| 3.441  (both FAIL)
#   WC=50, Wu(0.15,300, 7.5) -> g_opt 21.84, wc 15.98, PM 47.7, PM@0.5 39.4, ||S|| 2.789
#   WC=50, Wu(0.2 ,300,10  ) -> g_opt 24.67, wc 15.02, PM 50.7, PM@0.5 43.0, ||S|| 2.417
#   WC=50, Wu(0.25,300,12.5) -> g_opt 27.44, wc 14.35, PM 52.9, PM@0.5 45.5, ||S|| 2.187
#   WC=55, Wu(0.1 ,300, 5  ) -> g_opt 20.74, wc 17.52, PM 43.2, PM@0.5 34.2, ||S|| 3.724  (both FAIL)
#   WC=55, Wu(0.15,300, 7.5) -> g_opt 23.60, wc 16.73, PM 47.1, PM@0.5 38.5, ||S|| 2.980
#   WC=55, Wu(0.2 ,300,10  ) -> g_opt 26.56, wc 15.98, PM 50.1, PM@0.5 41.9, ||S|| 2.559
#   WC=60, Wu(0.1 ,300, 5  ) -> g_opt 22.39, wc 18.35, PM 42.8, PM@0.5 33.3, ||S|| 4.035  (both FAIL)
#   WC=60, Wu(0.2 ,300,10  ) -> g_opt 28.44, wc 16.73, PM 49.6, PM@0.5 41.0, ||S|| 2.711
#   WC=60, Wu(0.25,300,12.5) -> g_opt 31.50, wc 15.98, PM 51.9, PM@0.5 43.7, ||S|| 2.418  <-- CHOSEN
#   WC=60, Wu(0.05,300, 2.5) -> g_opt 20.31, wc 18.92, PM 38.8, PM@0.5 29.1, ||S|| 5.267  (all FAIL)
#   WC=65, Wu(0.2 ,300,10  ) -> g_opt 30.28, wc 17.52, PM 49.1, PM@0.5 40.1, ||S|| 2.868
#   WC=70, Wu(0.1 ,300, 5  ) -> g_opt 25.67, wc 19.81, PM 42.1, PM@0.5 31.9, ||S|| 4.752  (both FAIL)
#   WC=70, Wu(0.25,300,12.5) -> g_opt 35.44, wc 17.52, PM 51.0, PM@0.5 42.0, ||S|| 2.670
#   WC=80, Wu(0.05,300, 2.5) -> g_opt 26.82, wc 21.72, PM 38.3, PM@0.5 27.1, ||S|| 7.630  (all FAIL)
#
# CHOICE: WC=60, Wu(0.25, 300, 12.5).  It is the rung that maximizes crossover subject to
# BOTH the gates and the 2.5 worst-||S|| TARGET (not merely the 3.0 gate).  Every rung with
# a higher crossover -- WC=65/70 at Wu(0.2..0.25), WC=55 at Wu(0.15) -- breaks the 2.5
# target, and the ones that break it hardest also break PM.  Note the shape of the ladder
# has CHANGED from the previous round: the binding constraint is no longer phase margin
# alone but the worst-corner peak, because the worst corner is now the 0.5 m/s estimator
# corner rather than a parameter extreme.
#
# THE HEADLINE, stated plainly.  Adding a real 3 ms sensor delay did NOT cost bandwidth:
# achieved crossover 15.98 rad/s, identical to the previous round's 15.98, with MORE phase
# margin (51.9 vs 49.6 deg) and a slightly better worst corner (2.418 vs 2.152 on a corner
# family that is now 3x larger and includes a 12 ms delay).  The gain re-centring is what
# paid for it: K_v's span fell 4.0x -> 2.2x, which is a genuine reduction in what the
# controller must be robust to, bought with measurement rather than with conservatism.
# There is NO case for chasing bandwidth past this.  The ML0136-0139 limit cycle was a
# 16 rad/s loop meeting ~56 ms of unmodelled lag; the fix is to model the lag and keep the
# bandwidth, not to raise it.  The 12 ms low-speed corner is what bounds the design from
# above (PM@0.5 = 43.7 deg at the chosen rung, 27-33 deg at the failing rungs).
WC = 60.0                 # rad/s, Wp corner (see ladder above)
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
# HF shape matters.  dc = 0.25 allows ~4.0 A/(m/s) in band -- on a 0.5 m/s-scale error
# that is ~2.0 A of proportional effort, well inside the +-12 A clamp; hf = 12.5 forces Y
# down past the 300 rad/s break (papers' Y-weight break).  TIGHTENED 2026-08-16b from
# (0.15, 300, 7.5).  The previous round loosened Wu to buy back bandwidth lost to the
# calibrated plant's smaller DC gain; that round the gain came back up (via K_v) and
# the plant acquired real sensor delay, so effort must be re-restrained instead: rolling
# the controller off harder is what keeps the 12 ms low-speed estimator corner damped.
# The direction of this change IS the physics of the round -- delay is paid for with
# effort, not with gain.
# D = hf != 0 => D12 full column rank (AugPlantMIMO asserts this).
WU_DC, WU_WC, WU_HF = 0.25, 300.0, 12.5
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
# CROSSOVER GATE BAND RE-EXAMINED 2026-08-16b.  The old band was 12-48 rad/s, nominally
# "the vicinity of the papers' 24 rad/s".  The upper half of that band is unreachable on
# this plant -- the most aggressive rung in the ladder that produces a controller at all
# tops out at 21.7 rad/s, and it fails PM and ||S|| by a wide margin -- so 48 was never a
# constraint, it was decoration.  Narrowed to 12-30: 30 is ~2x the achieved crossover and
# still non-binding, but it is now within a factor of 1.4 of the reachable ceiling, so a
# future plant change that pushed the loop far past today's bandwidth would trip it and
# demand a look rather than passing silently.  The LOWER bound is the one that matters and
# is unchanged: below ~12 rad/s the drive loop is slower than the papers' driver model.
gate("achieved crossover in the vicinity of the papers' 24 rad/s (12-30)",
     12.0 <= wc_H <= 30.0, f"wc = {wc_H:.2f} rad/s")

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
# THE v0 SWEEP IS BACK, 2026-08-16b, and for a new reason.  The 2026-08-16 round DROPPED
# it as exactly degenerate: the calibrated b_eff is a measured local slope with no v0
# term, so v0 entered G22 nowhere.  It now enters in one place -- the velocity ESTIMATOR
# delay Td_est(v0) = (N+1)*pitch/(2 v0) -- and that dependence is strong (11.97 ms at
# 0.5 m/s vs 1.20 ms at 5 m/s, a 10x span across the operating range).  So the axis is
# reinstated as an ESTIMATOR-DELAY axis, not a drag axis, and the corner count goes
# 24 -> 72.  The drag-slope speed dependence it used to stand for stays where the previous
# round put it: pole_factor in {0.5, 3}.
# VALIDITY FLOOR.  The sweep bottoms out at plant_mimo.V0_VALID_MIN = 0.5 m/s.  Below it
# Td_est grows without bound (19.9 ms at 0.3 m/s, 59.8 ms at 0.1 m/s; below ~0.03 m/s the
# estimator times out and reports 0), and this design is NOT gate-checked there.  Closing
# the velocity loop below 0.5 m/s needs either a wider delay corner -- paid for in
# bandwidth -- or a gain schedule on v.  Stated as a limitation, not papered over.
V0_SET = pm.TD_EST_V0_SET
print(f"\n= 6. Continuous corner sweep ({len(pm.drive_corners())} drive corners x "
      f"{len(V0_SET)} estimator-delay speeds v0 = {V0_SET} m/s) ==")


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
# 6b. BENCH-EVIDENCE GATES (added 2026-08-16b)
# ─────────────────────────────────────────────────────────────────────────────
# These two gates exist because of ML0136-ML0139, not because of a specification.  The
# first one asks the question the previous design could not have answered: "how much of
# the phase margin does the velocity ESTIMATOR eat?"  The old estimator ate 52-58 deg of a
# 49.6 deg margin, and nothing in this script would have noticed.  Now it is measured, at
# the design speed, against a hard 10 deg budget.
# The second gate closes the loop at the WORST VALIDATED SPEED (0.5 m/s, Td_est = 12 ms)
# and requires a real margin there -- 30 deg rather than the nominal 45, because the
# low-speed corner is a boundary of the operating envelope, not the design point.
print("\n= 6b. Bench-evidence gates (velocity-estimator delay) ==")

phase_est_deg = np.degrees(wc_ach*TD_EST0)
print(f"  Td_est(v0 = {OP0['v0']} m/s) = {TD_EST0*1e3:.3f} ms consumes "
      f"{phase_est_deg:.2f} deg at the achieved crossover {wc_ach:.2f} rad/s")
print(f"  (for contrast: the RETIRED ~113 ms boxcar's ~56 ms group delay consumed "
      f"{np.degrees(wc_ach*56e-3):.0f} deg there -- more than the entire phase margin)")
gate("estimator delay consumes < 10 deg of phase at crossover (nominal speed)",
     phase_est_deg < 10.0, f"{phase_est_deg:.2f} deg")

OP_LOW = dict(OP0); OP_LOW['v0'] = pm.V0_VALID_MIN
G22_low = pm.drive_plant(OP_LOW, P0)
L_low, S_low, T_low, _ = loop_tfs(Gc_red, G22_low)
low_stable = np.max(eigvals(S_low.A).real) < 0
Lr_low = L_low.freqresp(w)
i_low = np.argmin(np.abs(np.abs(Lr_low) - 1.0))
pm_low = 180 + np.degrees(np.angle(Lr_low[i_low]))
print(f"  {pm.V0_VALID_MIN} m/s corner (Td_est = {pm.td_est(pm.V0_VALID_MIN)*1e3:.2f} ms): "
      f"stable = {low_stable}, PM = {pm_low:.1f} deg at {w[i_low]:.2f} rad/s, "
      f"||S||inf = {hinf_norm(S_low):.3f}")
gate(f"closed loop stable at the {pm.V0_VALID_MIN} m/s estimator corner", low_stable)
gate(f"phase margin > 30 deg at the {pm.V0_VALID_MIN} m/s estimator corner", pm_low > 30.0,
     f"PM = {pm_low:.1f} deg")

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
# ── ANTI-WINDUP CONDITIONING GAIN L (fw v18, 2026-08-25) ─────────────────────
# WHY THE SELF-CONDITIONED FORM HAD TO GO -- a structural defect, found by the fw v18
# test round's long constant-error saturation dwell and root-caused here.
#
# The Hanus SELF-conditioned form is the special case L = BD*DD^-1 of the general
# conditioning law
#     x[k+1] = AD x + BD e + L*(sat(u) - u),      u = CD x + DD e
# (substitute e = (u - CD x)/DD and it collapses to x[k+1] = AC x + BD*sat(u)/DD, the
# recursion shipped through fw v17).  Its SATURATED-mode matrix is therefore
# AC = AD - BD*CD/DD, whose eigenvalues are the discrete controller's transmission ZEROS.
#
# Those zeros contain one at EXACTLY z = -1, and it is structural, not incidental:
# the controller is a PARALLEL sum of two TUSTIN-discretized branches, and Tustin of the
# integrator is (kI*Ts/2)(z+1)/(z-1) while Tustin of the strictly proper remainder carries
# its own (z+1) factor, so
#     Gc(z) = (z+1)*[N1(z)(z-1) + (kI*Ts/2)*D1(z)] / [D1(z)(z-1)]
# retains (z+1) EXACTLY for any continuous controller, at any weight rung.  The saturated
# recursion consequently has ZERO damping at Nyquist, which is the enabling condition for a
# sustained relay oscillation against the clamp.
# MEASURED (float32 coefficients, double state -- the shipped arithmetic), constant-error
# dwells e in [0.25, 12.0] step 0.25, 2000 ticks, peak-to-peak over the last 200:
#     fw v17 coefficients: 14 of 48 dwells fail (e = 8.25 .. 11.75), tail p-p = 24.0 A
#     fw v18 coefficients: 15 of 48 dwells fail (the same band, plus e = 5.00)
# i.e. the defect shipped from fw v10 onward and is NOT a v18 regression -- the v18
# coefficients merely moved a basin boundary onto the e = 5 probe the tests happened to use.
# The observed cycle is a period-4 (++--) square wave, 125 Hz at Ts = 2 ms, rail to rail.
# It is reachable on hardware wherever a large error persists at the rail without the
# vehicle responding -- e.g. the documented ML0151 ~428 ms VESC post-reversal dead window,
# which drive_controller.h's departure #1 (the clamp is a MODEL, not measured current)
# already flags as invisible to the conditioning.
#
# THE FIX: choose L by POLE PLACEMENT instead of accepting BD/DD, so the saturated-mode
# matrix (AD - L*CD) is strictly stable with real margin.  Two properties make this cheap:
#   * while UNSATURATED sat(u) - u == 0 identically, so the law is bit-identical to
#     x[k+1] = AD x + BD e in exact arithmetic -- every linear synthesis gate, the whole
#     corner sweep and the unsaturated replay episode are untouched by this change;
#   * only the SATURATED trajectory moves, which is precisely what was broken.
#
# PLACEMENT METHOD: standard SISO observer pole placement on the dual pair, via
# scipy.signal.place_poles(AD^T, CD^T, poles) -> K, with L = K^T, so that
# eig(AD - L*CD) == the requested set.  (Placement acts on the FLOAT64 design matrices;
# rounding to float32 is an emission concern, as everywhere else in this script.  The
# GATES below are evaluated on the rounded, shipped set.)
#
# POLE CHOICE — MINIMAL PERTURBATION of the self-conditioned spectrum, not a free design.
# This was arrived at empirically and the failed attempt is worth recording, because the
# obvious choice is wrong.  Placing all five modes at a "nicely damped" set well inside the
# disc (tried: 0.55-0.75) DOES kill the limit cycle -- the dwell sweep goes clean -- but it
# also drags the controller's INTEGRATOR mode from z = 1 down to ~0.75 while saturated,
# which destroys the integral memory the conditioning exists to preserve.  Measured on that
# attempt: L[0] = 234.5, the 0->2 m/s step left a -1.13 m/s standing error, and both the
# step and regen sims fell into a slow 89 mm/s limit cycle (six §8 gates failed).
#
# The self-conditioned form's saturated spectrum is not arbitrary: it is what makes the
# conditioning BUMPLESS (while saturated the state tracks the achievable input, so release
# is clean).  Its ONLY defect is the single mode at z = -1.  So the target here is the
# self-conditioned spectrum eig(AC) itself, perturbed AS LITTLE AS POSSIBLE:
#   1. any eigenvalue at or outside the unit circle is scaled radially to
#      AW_POLE_RADIUS_MAX (a safety net -- fw v17's own -1.0000009 lands here); and
#   2. any eigenvalue that is poorly damped near Nyquist (Re < 0 and
#      |lambda| > AW_NYQUIST_MAX_RADIUS) is REPLACED by the real, damped
#      AW_NYQUIST_REPLACEMENT.  This is the one that matters: it is the z = -1 mode.
# Everything else is left EXACTLY where the self-conditioned form put it.
#
# SECOND FAILED ATTEMPT, recorded because it is the subtle one.  An earlier version of rule
# 1 also pulled the two SLOW modes (~0.99970, ~0.98399) inward to 0.998, to buy a 2e-3
# spectral-radius margin.  That is a tiny perturbation and it looks harmless.  It is not:
# the ~0.9997 mode is the conditioning counterpart of the controller's EXACT INTEGRATOR,
# and shortening its memory from tau ~ 6.6 s to ~ 1.0 s leaves the integrator state
# inconsistent at rail release.  Measured: 0->2 m/s step standing error -0.227 m/s with a
# 17.9 mm/s sustained hunting cycle; the regen sim mirrored it (six §8 gates failed).
# Leaving those modes alone -- moving ONLY the Nyquist one -- passes every §8 gate with the
# margins the fw v17 design had (step settle 1.034 s, final error 3.5e-08, tail 2.7e-09).
# CONSEQUENCE, and it is a deliberate deviation from the round's brief: the saturated-mode
# SPECTRAL RADIUS stays at ~0.99970, so a plain "max|eig| < 1 - 1e-3" gate is unachievable
# without breaking the controller.  See gate (a) in §8e for what is gated instead and why
# that version still catches the fw v10-v17 defect.
AW_POLE_RADIUS_MAX = 0.99999    # safety net for modes AT or outside the circle
AW_NYQUIST_MAX_RADIUS = 0.75    # Re<0 modes beyond this radius are the z=-1 pathology
AW_NYQUIST_REPLACEMENT = 0.5    # real, damped: tau = Ts/-ln(0.5) = 2.9 ms


def aw_target_poles(Ac):
    """Minimal-perturbation saturated-mode target set, from the self-conditioned eig(Ac).

    See the block above for the two projection rules and why the target is anchored on
    eig(Ac) rather than chosen freely.
    """
    out = []
    for lam in np.linalg.eigvals(np.asarray(Ac, dtype=float)):
        if abs(lam) >= AW_POLE_RADIUS_MAX:
            lam = lam*(AW_POLE_RADIUS_MAX/abs(lam))
        if lam.real < 0 and abs(lam) > AW_NYQUIST_MAX_RADIUS:
            lam = complex(AW_NYQUIST_REPLACEMENT, 0.0)
        out.append(lam)
    out = np.array(out)
    # The target set must be closed under conjugation for place_poles; it is, because the
    # projections above are applied to a real matrix's spectrum and map conjugate pairs
    # identically.  Drop numerically-zero imaginary parts so an all-real set stays real.
    return out.real.copy() if np.allclose(out.imag, 0.0) else out


def conditioning_gain(Ad, Cd, poles):
    """Anti-windup gain L placing eig(Ad - L*Cd) at `poles` (observer dual)."""
    from scipy.signal import place_poles
    n = Ad.shape[0]
    res = place_poles(np.asarray(Ad, dtype=float).T,
                      np.asarray(Cd, dtype=float).T,
                      np.asarray(poles, dtype=float)[:n])
    return res.gain_matrix.T.reshape(n)


_AC_DESIGN = ctrl_d.A - ctrl_d.B @ ctrl_d.C/ctrl_d.D[0, 0]   # the fw v10-v17 saturated mode
AW_POLES = aw_target_poles(_AC_DESIGN)
L_DESIGN = conditioning_gain(ctrl_d.A, ctrl_d.C, AW_POLES)
_ev_aw_design = np.linalg.eigvals(ctrl_d.A - np.outer(L_DESIGN, ctrl_d.C[0]))
print("\n= 7b. Anti-windup conditioning gain L (fw v18) ==")
print(f"  self-conditioned eig(AC) (fw v10-v17, the defect) = "
      f"{np.array2string(np.sort_complex(np.linalg.eigvals(_AC_DESIGN)), precision=6)}")
print(f"  requested saturated-mode poles = {np.array2string(AW_POLES, precision=6)}")
print(f"  achieved   (float64 design)    = "
      f"{np.array2string(np.sort_complex(_ev_aw_design), precision=6)}")
print(f"  L (float64) = {np.array2string(L_DESIGN, precision=6)}")
print(f"  max|eig(AD - L*CD)| = {np.max(np.abs(_ev_aw_design)):.9f}   "
      f"(self-conditioned L = BD/DD gives "
      f"{np.max(np.abs(np.linalg.eigvals(ctrl_d.A - ctrl_d.B @ ctrl_d.C/ctrl_d.D[0, 0]))):.9f}"
      f" -- the defect)")


class ConditionedController:
    """Hanus-conditioned discrete controller with output clamp.

    GENERAL conditioning form (fw v18): the state update is driven by the conditioning
    error (sat(u) - u) through a POLE-PLACED gain L.  The fw v10-v17 self-conditioned
    special case L = BD/DD is what the block above retired; see it for why.
    While unsaturated sat(u) == u, so this reduces EXACTLY to x[k+1] = AD x + BD e.
    """

    def __init__(self, cd, umin=-I_CLAMP, umax=I_CLAMP, L=None):
        self.Ad, self.Bd = cd.A, cd.B
        self.Cd, self.Dd = cd.C, float(cd.D[0, 0])
        assert abs(self.Dd) > 1e-9, "conditioning needs an invertible D"
        self.L = (L_DESIGN if L is None else np.asarray(L, dtype=float)).reshape(cd.n, 1)
        self.x = np.zeros((cd.n, 1))
        self.umin, self.umax = umin, umax

    def step(self, e, sat=True):
        uu = float((self.Cd @ self.x).item()) + self.Dd*e
        u = min(self.umax, max(self.umin, uu)) if sat else uu
        self.x = self.Ad @ self.x + self.Bd*e + self.L*(u - uu)
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
# The SHIPPED anti-windup gain.  Rounded from the float64 placement, exactly like every
# other coefficient, so header / replay CSV / compiled constant table hold one bit-identical
# set.  The two gates below are evaluated on THIS rounded L against the rounded AD/CD --
# the design-matrix placement is not evidence about what the firmware runs.
L_H = _f32(L_DESIGN).reshape(-1)
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
        self.L = L_H.reshape(-1, 1)
        self.x = np.zeros((AD_H.shape[0], 1))
        self.umin, self.umax = umin, umax


# ── §8e. SATURATED-MODE GATES (fw v18) ───────────────────────────────────────
# Two gates, both mandatory, both on the SHIPPED float32 set.  They exist because the
# fw v10-v17 self-conditioned realization was marginally stable in saturation (a Tustin
# zero at exactly z = -1; full account at the L block in §7b) and NOTHING in this script
# looked at the saturated-mode dynamics -- every gate here was either linear or a short
# transient sim, so a sustained rail dwell was never exercised and the defect shipped for
# eight firmware versions.
print(f"\n= 8e. Saturated-mode stability (anti-windup conditioning) ==")
_ev_aw = np.linalg.eigvals(AD_H - np.outer(L_H, CD_H[0]))
_aw_rad = float(np.max(np.abs(_ev_aw)))
AW_EIG_MARGIN = 1.0e-3      # required margin for OSCILLATORY modes -- see below
# GATE (a), and a DELIBERATE DEVIATION from "max|eig| < 1 - 1e-3" as briefed.
# A flat spectral-radius margin is unachievable here for a documented reason: the
# conditioned dynamics of a controller carrying an EXACT INTEGRATOR necessarily retain a
# slow POSITIVE-REAL mode (~0.99970 here), and forcing it inward destroys the integral
# memory -- measured, see the second failed attempt at §7b.  But a slow positive-real mode
# is a decaying exponential: it cannot sustain an oscillation, and it is not what broke.
# What broke was an OSCILLATORY mode sitting on the unit circle (z = -1).  So the gate is
# applied where the pathology lives:
#     every eigenvalue that is NOT on the positive real axis must satisfy
#     |lambda| < 1 - AW_EIG_MARGIN;  and no eigenvalue anywhere may reach the circle.
# ACCEPTANCE CHECK for the gate itself: it FAILS the shipped fw v17 spectrum (-1.0000009,
# not positive real, |lambda| = 1.0000009) and the fw v18 self-conditioned spectrum
# (-0.9999990) -- i.e. it catches the exact defect this round found, which a plain
# "max|eig| < 1" test does NOT (0.9999990 passes that and still limit-cycles).
_ev_osc = [e for e in _ev_aw if not (abs(e.imag) < 1e-12 and e.real > 0.0)]
_osc_rad = max((abs(e) for e in _ev_osc), default=0.0)
print(f"  L (float32, shipped) = {np.array2string(L_H, precision=6)}")
print(f"  eig(AD - L*CD) = {np.array2string(np.sort_complex(_ev_aw), precision=6)}")
print(f"  spectral radius = {_aw_rad:.9f} (slow positive-real integrator mode -- benign)")
print(f"  worst NON-positive-real (oscillatory) mode = {_osc_rad:.9f}  "
      f"(gate: < {1.0 - AW_EIG_MARGIN})")
gate(f"saturated-mode: every oscillatory eigenvalue < 1 - {AW_EIG_MARGIN:g}",
     _osc_rad < 1.0 - AW_EIG_MARGIN and _aw_rad < 1.0,
     f"worst oscillatory |eig| = {_osc_rad:.9f}, spectral radius = {_aw_rad:.9f}")

# THE LOAD-BEARING GATE.  The eigenvalue test alone is NOT sufficient and would not have
# caught the shipped defect: the fw v18 self-conditioned coefficients had
# max|eig(AC)| = 0.9999990 -- strictly inside the unit circle -- and still limit-cycled
# rail to rail, because 1e-6 of damping does not suppress a relay oscillation.  Only the
# dwell sweep catches that, so it is the gate that matters; the eigenvalue gate is the
# cheap explanatory companion.
_DWELL_TICKS, _DWELL_TAIL, _DWELL_TOL = 2000, 200, 1.0e-6
_dwell_errs = np.arange(0.25, 12.0 + 1e-9, 0.25)
_dwell_bad, _dwell_worst = [], 0.0
for _e in _dwell_errs:
    _c = HeaderController()
    _us = np.array([_c.step(float(_e), sat=True) for _ in range(_DWELL_TICKS)])
    _pp = float(np.ptp(_us[-_DWELL_TAIL:]))
    _dwell_worst = max(_dwell_worst, _pp)
    if _pp > _DWELL_TOL:
        _dwell_bad.append((round(float(_e), 2), round(_pp, 3)))
print(f"  constant-error dwell sweep: e in [{_dwell_errs[0]:.2f}, {_dwell_errs[-1]:.2f}] "
      f"step 0.25 ({_dwell_errs.size} cases), {_DWELL_TICKS} ticks, "
      f"peak-to-peak over the last {_DWELL_TAIL}")
print(f"  worst tail p-p = {_dwell_worst:.3e} A; non-settling cases: "
      f"{_dwell_bad if _dwell_bad else 'none'}")
gate("LOAD-BEARING: every constant-error rail dwell settles (no saturated limit cycle)",
     _dwell_worst <= _DWELL_TOL,
     f"worst tail p-p = {_dwell_worst:.3e} A over {_dwell_errs.size} dwells "
     f"(tol {_DWELL_TOL:.0e} A); {len(_dwell_bad)} non-settling")


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

# The regen episode is generated CLOSED-LOOP through the shipped float32 coefficients.
#
# CHANGED 2026-08-16b, and the reason is worth recording because it cost a review round.
# The previous construction took the §8b closed-loop error sequence (r2 - y2, produced by
# the FLOAT64 controller) and replayed it OPEN-LOOP through the float32 HeaderController.
# Those are two different trajectories: the float32 controller fed a float64 controller's
# error sequence is not on its own closed-loop path, so its output sat ON the clamp
# BOUNDARY and CHATTERED -- u toggled -12 A / -4 A from k = 1 onward.  The emitted vectors
# were still internally exact (header -> CSV replays bit-identically, both ways, and the
# validator's check2 reported 0.0), but they were NUMERICALLY KNIFE-EDGED: at a boundary
# sample an arbitrarily small perturbation flips the clamp decision, and each flip is an
# ~8 A step into the state update.  Any consumer that perturbs the stimulus even slightly
# -- a reader parsing e_in at %.9e instead of %.17e, a float32 C++ harness -- diverges by
# tens of mA for reasons that have nothing to do with implementing the controller
# correctly.  That is a bad conformance vector: it fails honest implementations.
# (Measured on the previous emission: %.9e stimulus truncation -> 5.4e-2 A divergence
# first appearing at k = 22; float32 stimulus -> 3.4e-2 A at k = 10.  The 'small' episode
# was unaffected either way, because it never approaches the clamp.)
#
# Generating the episode closed-loop with the SAME controller that will replay it makes
# the trajectory self-consistent: the loop drives itself hard onto the rail, sits there
# for a sustained interval, and crosses the boundary essentially once, at release.  It is
# also the more faithful test -- it is what the firmware actually does.
_c_sat = HeaderController()
_y_sat, _u_sat, _r_sat = simulate(_c_sat, G22, regen_ref, N2, v_init=2.0)
_e_sat = _r_sat - _y_sat        # exactly the sequence fed to .step() above
gate("replay (b) is genuinely saturated", np.min(_u_sat) <= -I_CLAMP + 1e-9,
     f"{int(np.sum(_u_sat <= -I_CLAMP + 1e-9))} samples on the rail")

# The vectors must be reproducible by replaying e_in open-loop -- that is how every
# consumer uses them -- so gate that explicitly rather than trusting the construction.
_chk = HeaderController()
_u_chk = np.array([_chk.step(float(v), sat=True) for v in _e_sat])
gate("replay (b) reproduces open-loop from e_in alone (bit-exact)",
     np.max(np.abs(_u_chk - _u_sat)) == 0.0,
     f"max |du| = {np.max(np.abs(_u_chk - _u_sat)):.3e} A")

# REPLAY-SENSITIVITY SUITE + DERIVED CONSUMER TOLERANCE (rewritten 2026-08-16d).
#
# The vectors are self-consistent (the bit-exact gate above), so nothing about the EMISSION
# tells a consumer how tight a comparison is achievable.  That number is a property of the
# PLANT+CONTROLLER trajectory, not of the emission, and it must be MEASURED here and shipped
# with the artifacts -- never hand-written into a comment, because it changes with every
# re-synthesis.  (It did: the fw v12 coefficients' figure was inherited verbatim into the
# K_F-corrected round and under-stated the true sensitivity by 3.5x, failing a correct C++
# implementation at 86 mA against a stale 50 mA gate.)
#
# WHY THE SENSITIVITY IS NONZERO.  During the saturated 2 -> 0 m/s transient this controller
# DITHERS across the +-I_CLAMP boundary at close to the sample rate: the non-integral branch
# carries a ~545 A/(m/s) LF gain at a 2 ms sample period, so u alternates rail / part-rail
# for tens of ms.  Some sample therefore sits arbitrarily close to the decision boundary
# (measured below), and ANY perturbation -- text truncation, float32 storage, a different
# but equally valid summation order -- can flip that one decision, which is worth ~8 A of
# state drive through the ~0.9999 mode.  No emission removes this.  The 'small' episode
# never approaches the clamp and carries the tight-tolerance check instead.
#
# THE THREE PERTURBATIONS BELOW ARE THE ONES REAL CONSUMERS APPLY, and the third is the one
# the previous version of this block MISSED:
#   (1) %.9e stimulus truncation   -- a reader parsing the CSV/header text at 10 sig digits.
#   (2) float32 stimulus storage   -- drive_replay_vectors.h stores e_in as `static const
#                                     float`, so the firmware replay sees float32 e AND a
#                                     float32-rounded reference u.
#   (3) SCALAR-ORDER ARITHMETIC    -- driveControllerStep() accumulates Cd.x and Ad.x with
#                                     sequential C loops; numpy sums the same dot products
#                                     with BLAS pairwise/FMA order.  The reassociation is
#                                     ~1e-16 relative, but on a boundary approach measured
#                                     in microamps it flips clamp decisions, and it DOMINATES
#                                     (1) and (2).  Perturbing only the stimulus while
#                                     keeping numpy's summation order measures the wrong
#                                     thing and reports a tolerance several times too tight.
# The shipped consumer tolerance is derived from the worst of the three with 2x headroom.
_ad_h = np.asarray(AD_H, float)
_bd_h = np.asarray(BD_H, float).reshape(-1)
_cd_h = np.asarray(CD_H, float).reshape(-1)
_l_h = np.asarray(L_H, float).reshape(-1)
_n_h = _ad_h.shape[0]


def _replay_scalar_order(e_seq, f32_out=False):
    """Replay e_seq with SCALAR, left-to-right accumulation and a double state vector.

    Byte-for-byte the arithmetic of teensy_controller/drive_controller.h
    driveControllerStep(): output equation first, clamp, then the Hanus state update driven
    by the clamped u.  f32_out additionally rounds the returned command to float32, which is
    what the firmware's `float` return does.
    """
    x = [0.0]*_n_h
    out = []
    for e in e_seq:
        uu = float(DD_H)*float(e)
        for j in range(_n_h):
            uu += _cd_h[j]*x[j]
        u = min(float(I_CLAMP), max(-float(I_CLAMP), uu))
        dcond = u - uu                      # conditioning error; identically 0 unsaturated
        xn = [0.0]*_n_h
        for i in range(_n_h):
            acc = _bd_h[i]*float(e) + _l_h[i]*dcond
            for j in range(_n_h):
                acc += _ad_h[i][j]*x[j]
            xn[i] = acc
        x = xn
        out.append(float(np.float32(u)) if f32_out else u)
    return np.array(out)


# Closest approach to a clamp DECISION BOUNDARY -- the physical reason a tolerance exists.
# This is the smallest distance from the PRE-clamp output to either rail, over the whole
# episode: the sample at which the smallest perturbation flips a decision.  (It is NOT the
# depth into the rail -- a deeply-railed sample is insensitive, not fragile.)  The pre-clamp
# sequence is taken from the ACTUAL trajectory, so it is regenerated with sat=True and the
# unclamped value captured, not re-run open loop with sat=False (which would leave the
# controller's own path and measure a different trajectory's margins).
_c_marg = HeaderController()
_u_pre = []
for _v in _e_sat:
    _u_pre.append(float((_c_marg.Cd @ _c_marg.x).item()) + _c_marg.Dd*float(_v))
    _c_marg.step(float(_v), sat=True)
_u_pre = np.array(_u_pre)
_boundary_uA = float(np.min(np.minimum(np.abs(_u_pre - I_CLAMP),
                                       np.abs(_u_pre + I_CLAMP))))*1e6
# Clamp-state transitions in the shipped vectors themselves (NOT in the float64 sim: the
# vectors are what consumers replay, so the count must describe them).
_clamp_state = np.sign(np.where(np.abs(_u_sat) >= I_CLAMP - 1e-12, _u_sat, 0.0))
_n_clamp_trans = int(np.sum(np.diff(_clamp_state) != 0))

_SENS = {}   # label -> max |du| in A
_c1 = HeaderController()
_SENS["%.9e stimulus truncation"] = float(np.max(np.abs(
    np.array([_c1.step(float(f"{v:.9e}"), sat=True) for v in _e_sat]) - _u_sat)))
_c2 = HeaderController()
_SENS["float32 stimulus storage"] = float(np.max(np.abs(
    np.array([_c2.step(float(np.float32(v)), sat=True) for v in _e_sat]) - _u_sat)))
# (3) is the firmware path exactly: float32 stimulus text -> float32 storage -> scalar-order
# double recursion -> float32 return, compared against the float32-rounded reference column.
_e_fw = [float(np.float32(float(f"{v:.9e}"))) for v in _e_sat]
_u_ref_fw = np.array([float(np.float32(float(f"{v:.9e}"))) for v in _u_sat])
_SENS["scalar-order arithmetic (firmware path)"] = float(np.max(np.abs(
    _replay_scalar_order(_e_fw, f32_out=True) - _u_ref_fw)))
# Isolate the reassociation term alone, so the report attributes it correctly.
_SENS["scalar-order arithmetic (full-precision stimulus)"] = float(np.max(np.abs(
    _replay_scalar_order([float(v) for v in _e_sat]) - _u_sat)))

_sens_worst = max(_SENS.values())
_sens_worst_label = max(_SENS, key=_SENS.get)


def _round_up_tol(x, sig=2):
    """Round a tolerance UP to `sig` significant digits, so the shipped number is quotable.

    Rounding UP (never to-nearest) keeps the shipped tolerance a true upper bound on the
    headroom multiple; two significant digits keeps it from ballooning (1 digit would turn
    a 172 mA bound into 200 mA, which is slack nobody measured).
    """
    if x <= 0:
        return 0.0
    mag = 10.0**(math.floor(math.log10(x)) - (sig - 1))
    return math.ceil(x/mag)*mag


# 2x headroom over the worst measured sensitivity, rounded up to 1 sig digit.  The headroom
# covers consumer arithmetic we do not enumerate here (a different compiler's contraction of
# the same scalar loop, x87 excess precision, a fused multiply-add) which perturbs the same
# boundary decisions by the same class of amount.
REPLAY_TOL_SMALL = 1.0e-4
# FLOOR (fw v18).  The measured sensitivity is a property of the trajectory, and the fw v18
# anti-windup fix made the regen trajectory dramatically better conditioned: clamp-state
# transitions fell 60 -> 2, the closest boundary approach rose 20 uA -> 13.3 mA, and every
# perturbation in the suite now measures ~0.  Taken literally that yields a NANOAMP
# tolerance, which is not a usable conformance bound -- it would fail honest implementations
# for reasons the suite does not model (a different compiler's FMA contraction, x87 excess
# precision).  So the derived figure is floored at the linear-recursion tolerance: the
# saturated episode can never be required to match TIGHTER than the unsaturated one, since
# the same float32 storage and arithmetic-order effects apply to both.
REPLAY_TOL_REGEN = max(_round_up_tol(2.0*_sens_worst), REPLAY_TOL_SMALL)
print(f"  replay sensitivity ({_n_clamp_trans} clamp-state transitions in the emitted "
      f"vectors; closest boundary approach {_boundary_uA:.1f} uA):")
for _lbl, _dv in sorted(_SENS.items(), key=lambda kv: -kv[1]):
    print(f"    {_lbl:52s} {_dv*1e3:8.2f} mA")
print(f"    -> shipped consumer tolerance 'regen' = {REPLAY_TOL_REGEN*1e3:.2f} mA "
      f"({'2x worst, rounded up' if REPLAY_TOL_REGEN > REPLAY_TOL_SMALL else 'FLOORED at the small-episode tolerance'}"
      f"), 'small' = {REPLAY_TOL_SMALL*1e3:.2f} mA")

# The 'small' episode must hold the TIGHT tolerance under every one of the same
# perturbations -- that is what makes it the linear-recursion check.
_e_small_fw = [float(np.float32(float(f"{v:.9e}"))) for v in _e_small]
_u_small_ref_fw = np.array([float(np.float32(float(f"{v:.9e}"))) for v in _u_small])
_small_dev = float(np.max(np.abs(
    _replay_scalar_order(_e_small_fw, f32_out=True) - _u_small_ref_fw)))
gate(f"replay (a) holds the tight tolerance on the firmware arithmetic path "
     f"(< {REPLAY_TOL_SMALL*1e3:.2f} mA)", _small_dev < REPLAY_TOL_SMALL,
     f"max |du| = {_small_dev*1e3:.2e} mA")
gate("replay (b) firmware-path deviation is inside the shipped tolerance",
     _SENS["scalar-order arithmetic (firmware path)"] < REPLAY_TOL_REGEN,
     f"max |du| = {_SENS['scalar-order arithmetic (firmware path)']*1e3:.2f} mA "
     f"< {REPLAY_TOL_REGEN*1e3:.0f} mA")
# Sanity bound: if the sensitivity ever runs away, the episode has stopped being a
# boundary-dither test and become a divergence, and that must not be papered over by a
# generated tolerance.  1 A is ~8 % of the clamp span.
gate("replay (b) sensitivity is boundary-dither class, not divergence (< 1 A)",
     _sens_worst < 1.0,
     f"worst = {_sens_worst*1e3:.2f} mA ({_sens_worst_label})")
# ... and it must not GROW: a boundary flip is a transient re-convergence, so the tail of
# the episode must be quiet even though the mid-transient is not.
_dev_fw = np.abs(_replay_scalar_order(_e_fw, f32_out=True) - _u_ref_fw)
_tail_dev = float(np.max(_dev_fw[-200:]))
gate("replay (b) deviation decays into the tail (not accumulating)",
     _tail_dev < max(0.1*_sens_worst, REPLAY_TOL_SMALL),
     f"last 200 samples max |du| = {_tail_dev*1e3:.2f} mA vs peak "
     f"{_sens_worst*1e3:.2f} mA")

print(f"  float32-coefficient closed-loop regen vs the float64 sim: max |dv| = "
      f"{np.max(np.abs(_y_sat - y2)):.3e} m/s, on the rail "
      f"{int(np.sum(_u_sat <= -I_CLAMP + 1e-9))*TS*1e3:.0f} ms")

# ── replay episode (c): the RAIL DWELL (fw v18) ──────────────────────────────
# A third episode, added with the anti-windup fix, because neither existing episode can
# detect the defect that fix addresses.  'small' never approaches the clamp; 'regen' does
# saturate but releases after ~0.8 s, and the fw v10-v17 limit cycle needs a LONG
# uninterrupted dwell to establish itself.  A firmware replay test that passes 'small' and
# 'regen' therefore proves nothing about saturated-mode stability -- which is precisely how
# the defect shipped for eight versions.
#
# Construction is deliberately trivial: a CONSTANT error held for many ticks.  There is no
# plant in the loop, so there is nothing to make it knife-edged -- a conforming
# implementation drives to +I_CLAMP and STAYS, and the entire tail is a single repeated
# value.  Its tolerance is correspondingly tight (the 'small' figure, not the 'regen' one):
# no clamp-boundary dither exists to justify slack.
# The error VALUE is one that the fw v18 self-conditioned coefficients demonstrably failed
# (e = 5.0 was the case the test round found), so the vector is a regression test for the
# exact reported defect, not merely a generic dwell.
DWELL_REPLAY_E = 5.0            # m/s, constant velocity error
DWELL_REPLAY_N = 600            # ticks (1.2 s at Ts = 2 ms) -- the fw v17/v18 cycle is
                                # fully established within ~100 ticks
DWELL_REPLAY_TAIL = 200         # samples that must be identical in a conforming replay
_c_dwell = HeaderController()
_e_dwell = np.full(DWELL_REPLAY_N, float(DWELL_REPLAY_E))
_u_dwell = np.array([_c_dwell.step(float(v), sat=True) for v in _e_dwell])
_dwell_tail_pp = float(np.ptp(_u_dwell[-DWELL_REPLAY_TAIL:]))
print(f"  replay (c) rail dwell: e = {DWELL_REPLAY_E} m/s x {DWELL_REPLAY_N} ticks, "
      f"final u = {_u_dwell[-1]:.6f} A, tail p-p = {_dwell_tail_pp:.3e} A")
gate("replay (c) dwell reaches the rail and stays (the fw v10-v17 regression)",
     _dwell_tail_pp <= 1e-9 and abs(_u_dwell[-1] - I_CLAMP) < 1e-9,
     f"final u = {_u_dwell[-1]:.6f} A of {I_CLAMP:.0f} A, "
     f"last {DWELL_REPLAY_TAIL} samples p-p = {_dwell_tail_pp:.3e} A")
# Same firmware-arithmetic check the other two episodes get.
_e_dwell_fw = [float(np.float32(float(f"{v:.9e}"))) for v in _e_dwell]
_u_dwell_ref_fw = np.array([float(np.float32(float(f"{v:.9e}"))) for v in _u_dwell])
_dwell_dev = float(np.max(np.abs(
    _replay_scalar_order(_e_dwell_fw, f32_out=True) - _u_dwell_ref_fw)))
REPLAY_TOL_DWELL = REPLAY_TOL_SMALL
gate(f"replay (c) holds the tight tolerance on the firmware arithmetic path "
     f"(< {REPLAY_TOL_DWELL*1e3:.2f} mA)", _dwell_dev < REPLAY_TOL_DWELL,
     f"max |du| = {_dwell_dev*1e3:.2e} mA")

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
    f.write("# episode 'regen' : the 2->0 m/s regen event, generated CLOSED-LOOP through "
            "these same\n#                   float32 coefficients, clamp ACTIVE, "
            "controller state starts at zero.\n")
    f.write(f"# episode 'dwell' : NEW in fw v18.  A CONSTANT velocity error of "
            f"{DWELL_REPLAY_E:.2f} m/s held for\n"
            f"#                   {DWELL_REPLAY_N} ticks -- a long, uninterrupted dwell "
            f"against the +{I_CLAMP:.0f} A rail.\n"
            f"#                   This is the episode that the fw v10-v17 self-conditioned "
            f"realization\n"
            f"#                   FAILED: it entered a period-4, rail-to-rail (24 A p-p) "
            f"relay limit\n"
            f"#                   cycle instead of settling, because its saturated-mode "
            f"matrix\n"
            f"#                   AC = AD - BD*CD/DD carries a Tustin zero at exactly "
            f"z = -1.  A\n"
            f"#                   conforming implementation reaches +{I_CLAMP:.0f} A and "
            f"STAYS there; the last\n"
            f"#                   {DWELL_REPLAY_TAIL} samples must be identical.  Short "
            f"episodes cannot detect this,\n"
            f"#                   which is why the regen episode above did not.\n")
    # *** EVERY NUMBER BELOW IS MEASURED AND INTERPOLATED, NOT WRITTEN BY HAND. ***
    # Hand-written figures survived a re-synthesis once and understated the true
    # sensitivity by 3.5x; do not reintroduce a literal here.
    f.write("#\n"
            "# *** COMPARISON TOLERANCES - READ BEFORE WRITING A REPLAY TEST. ***\n"
            "# The two 'tol' rows below are MACHINE-READABLE: tools/gen_drive_replay_header"
            ".py turns\n"
            "# them into DRIVE_REPLAY_<EPISODE>_TOL_A, and the firmware replay tests gate on"
            " those\n"
            "# macros.  Never copy these numbers into a consumer; read them.\n")
    f.write(f"# tol,small,{REPLAY_TOL_SMALL:.17e}\n")
    f.write(f"# tol,regen,{REPLAY_TOL_REGEN:.17e}\n")
    f.write(f"# tol,dwell,{REPLAY_TOL_DWELL:.17e}\n")
    f.write(f"#   episode 'small' : compare at {REPLAY_TOL_SMALL:.0e} A or tighter.  It "
            f"never approaches the clamp, so\n"
            f"#                     it is a clean test of the linear state recursion.  "
            f"Measured on the\n"
            f"#                     firmware arithmetic path (float32 stimulus + scalar-"
            f"order double\n"
            f"#                     recursion): {_small_dev*1e3:.2e} mA.\n")
    f.write(f"#   episode 'regen' : compare at {REPLAY_TOL_REGEN*1e3:.0f} mA.  NOT tighter -"
            f" and this is not slack for sloppy\n"
            f"#                     implementations.  During the saturated transient the "
            f"controller\n"
            f"#                     DITHERS across the +-{I_CLAMP:.0f} A boundary "
            f"({_n_clamp_trans} clamp-state transitions in\n"
            f"#                     THESE vectors), and its closest approach to the decision"
            f" boundary is\n"
            f"#                     {_boundary_uA:.1f} uA, so any perturbation can flip one "
            f"decision for ~8 A of\n"
            f"#                     state drive.  Measured sensitivity of THESE vectors:\n")
    for _lbl, _dv in sorted(_SENS.items(), key=lambda kv: -kv[1]):
        f.write(f"#                       {_dv*1e3:8.2f} mA  {_lbl}\n")
    f.write(f"#                     The shipped tolerance is 2x the worst of those, rounded "
            f"up.  Note\n"
            f"#                     the ARITHMETIC-ORDER term: a scalar C accumulation of "
            f"the same dot\n"
            f"#                     products is a valid implementation and is the LARGEST "
            f"perturbation\n"
            f"#                     here - a tolerance derived from stimulus truncation "
            f"alone is wrong.\n"
            f"#                     Deviation decays into the tail ({_tail_dev*1e3:.2f} mA "
            f"over the last 200\n"
            f"#                     samples): it is boundary dither, not divergence.\n")
    f.write("#   A float32 ARITHMETIC recursion costs ~1 A on 'regen' (validate_drive_siso"
            " check 4).\n"
            "#   THAT one is a real inadequacy, not a boundary flip: use double.\n")
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
    for k, (e_, u_) in enumerate(zip(_e_dwell, _u_dwell)):
        f.write(f"dwell,{k},{e_:.17e},{u_:.17e}\n")
print(f"  replay vectors: {len(_e_small)} unsaturated + {len(_e_sat)} saturated "
      f"+ {len(_e_dwell)} rail-dwell samples")


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
// controller state (Hanus conditioning, used in the synthesis sims):
//     u_unsat = Cd x + Dd e ;  u = clamp(u_unsat) ;
//     x[k+1]  = Ad x + Bd e + L*(u - u_unsat)          (Dd = {ctrl_d.D[0, 0]:.9e})
//
// *** fw v18: DO NOT USE THE SELF-CONDITIONED FORM L = Bd/Dd (i.e. AC) ***
// fw v10-v17 shipped the special case L = Bd*Dd^-1, whose saturated-mode matrix is
// AC = Ad - Bd*Cd/Dd.  The eigenvalues of AC are the controller's transmission ZEROS, and
// one of them sits at EXACTLY z = -1 for a structural reason: this controller is a
// PARALLEL sum of two TUSTIN-discretized branches, and both numerators carry a (z+1)
// factor (the integrator's Tustin form is (kI*Ts/2)(z+1)/(z-1)), so the sum retains (z+1)
// exactly -- at any weight rung, on any plant.  The saturated recursion therefore had ZERO
// damping at Nyquist and could sustain a rail-to-rail relay oscillation.
// MEASURED on constant-error dwells (e in [0.25, 12.0] step 0.25, 2000 ticks, p-p over the
// last 200): the fw v17 coefficients fail 14 of 48 cases (e = 8.25..11.75) and the fw v18
// coefficients fail 15 of 48, all at a full 24 A peak-to-peak, in a period-4 (++--) square
// wave at 125 Hz.  It is reachable on hardware wherever a large error persists at the rail
// without the vehicle responding -- e.g. the ML0151 ~428 ms VESC post-reversal dead window.
// The fix is the general L above, pole-placed for damping; §8e gates it two ways.
// L is emitted below as DRIVE_CTRL_L.  AC is still emitted, but ONLY as an identity
// cross-check -- implementing with it reintroduces the defect.
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
//   AD is n x n, BD is n x 1, CD is 1 x n, DD is scalar, L is n x 1.
// All arrays are ROW-MAJOR.
//
// Update law, once per DRIVE_CTRL_TS_US, with e = v_ref - v_actual [m/s]:
//   u_unsat   = sum_j CD[0][j]*x[j] + DD*e
//   u         = clamp(u_unsat, DRIVE_CTRL_I_MIN, DRIVE_CTRL_I_MAX)   -> i_cmd [A]
//   x_next[i] = sum_j AD[i][j]*x[j] + BD[i][0]*e + L[i][0]*(u - u_unsat)
//   x <- x_next
// Note the conditioning term L*(u - u_unsat): it is IDENTICALLY ZERO while unsaturated, so
// the law is then exactly x_next = AD x + BD e -- the linear controller, unmodified.  Once
// the clamp is active it de-winds every state, integrator and lag alike, with saturated-
// mode dynamics (AD - L*CD) that are gated for damping in §8e.
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
//   * ARITHMETIC.  The replay vectors assume a float64 (double) state recursion, and the
//     firmware uses one.  RE-MEASURED at the fw v18 anti-windup change: a float32 state
//     recursion now costs only ~1e-5 A on the saturated regen episode
//     (validate_drive_siso.py check 4), down from the ~1e-2 A that the fw v10–v17
//     self-conditioned form produced.  The improvement is real and has a cause — the
//     retired form drove the trajectory along the clamp boundary, where a rounding
//     difference flips clamp decisions, whereas the conditioned form crosses the boundary
//     essentially once — but it is NOT a licence to drop to float32.  The realization still
//     integrates its own rounding through the exact integrator, the margin is only ~2
//     decades, and no gate bounds float32 behaviour on trajectories other than these two.
//     Use double (or fixed point with equivalent headroom).
// Replay comparisons should be toleranced on the OUTPUT (i_cmd), never on the individual
// states — and the two episodes need DIFFERENT tolerances:
//     'small' (unsaturated) : {REPLAY_TOL_SMALL:.0e} A or tighter.  Clean test of the linear recursion
//                             (measured on the firmware arithmetic path: {_small_dev*1e3:.2e} mA).
//     'regen' (saturated)   : {REPLAY_TOL_REGEN*1e3:.0f} mA.  During the saturated transient this controller
//                             dithers across the +-{I_CLAMP:.0f} A clamp boundary ({_n_clamp_trans} clamp-state
//                             transitions in the emitted vectors, closest boundary
//                             approach {_boundary_uA:.1f} uA), so one flipped decision — which any
//                             perturbation can cause — is worth ~8 A of state drive.
//                             Measured worst sensitivity {_sens_worst*1e3:.2f} mA
//                             ({_sens_worst_label});
//                             the shipped tolerance is 2x that, rounded up.  A tighter
//                             tolerance fails correct implementations.  NOTE the largest
//                             perturbation is the ARITHMETIC ORDER of the dot products
//                             (scalar C loop vs BLAS), not stimulus precision.
// These tolerances are MEASURED per synthesis run and shipped machine-readably as
// DRIVE_REPLAY_<EPISODE>_TOL_A in controller_design_MIMO/drive_replay_vectors.h — read
// those macros, do not copy the numbers above into a test.
// Full detail in the figures/drive_siso_replay.csv header.
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
                     f"AC [{_n}][{_n}] = AD - BD*CD/DD — the fw v10–v17 self-conditioned "
                     f"state matrix. RETIRED as a runtime coefficient in fw v18 (its "
                     f"eigenvalues are the controller's zeros, one of which is the Tustin "
                     f"zero at z = -1 — see the ANTI-WINDUP warning above). Emitted only "
                     f"as a cross-check of the AD/BD/CD/DD identity; DO NOT implement with it"))
        f.write("\n")
        f.write(cmat("DRIVE_CTRL_L", L_H.reshape(-1, 1),
                     f"L [{_n}][1] — anti-windup CONDITIONING GAIN (fw v18). "
                     f"USE THIS ONE: x_next = AD*x + BD*e + L*(u - u_unsat). "
                     f"Placed so eig(AD - L*CD) = "
                     f"{np.array2string(np.sort(AW_POLES.real), precision=6)}"))


_emit_coeffs(os.path.join(HERE, "drive_siso_coeffs.h"), _BANNER_STUDY)
_emit_coeffs(os.path.join(HERE, os.pardir, "teensy_controller",
                          "drive_controller_coeffs.h"), _BANNER_FW)

with open(os.path.join(HERE, "drive_siso_metrics.txt"), "w", encoding="utf-8") as f:
    f.write(f"""SISO Youla-H DRIVE baseline — synthesis metrics (GENERATED by
controller_design_MIMO/synthesize_drive_siso.py; plan Phase 3 / §5 bullet 1)

── plant (plant_mimo.drive_plant, nominal OP/params) ──
states               = {G22.n}  (Pade(2) VESC delay + tau_v lag + 1st-order mechanics
                       + Pade(2) VELOCITY-ESTIMATOR delay on the measured output)
G22(0)               = {G22.dcgain():.6f} (m/s)/A
mechanical pole      = {-pm.b_eff(OP0, P0)/P0['m_eff']:.6f} rad/s  (near-integrator)
b_eff                = {pm.b_eff(OP0, P0):.6f} N*s/m   force/amp = {pm.force_per_amp(P0):.6f} N/A
i_m0 at the OP       = {pm.bus_current_gains(OP0, P0)[2]:.4f} A   vs a measured cruise hold of
                       4.5 +- 0.4 A: the model runs ~9 % below the band's centre and just
                       under its lower edge, NOT inside it.  Consistent with the unmeasured
                       eta_dt = 0.85, which scales every absolute force.  The claim this
                       supports is a factor-of-4 correction (the retired model gave 0.973 A),
                       not agreement to within the measurement.

VELOCITY ESTIMATOR — MODELLED FOR THE FIRST TIME, 2026-08-16b.  Element:
      Td_est(v0) = (N_est + 1)*pitch/(2 v0),  pitch = 2*pi*R_FLY/120 = {pm.PITCH_M*1e3:.4f} mm, N_est = {P0['N_est']}
      = {TD_EST0*1e3:.3f} ms at the design speed v0 = {OP0['v0']:g} m/s
        {pm.td_est(0.5)*1e3:.2f} ms at 0.5 m/s (validity floor)   {pm.td_est(5.0)*1e3:.2f} ms at 5 m/s
It sits on the MEASURED speed only (the bus-current coupling in the 2x2 plant taps the
undelayed speed).  Modelled as a pure transport delay: the estimator averages N periods
over one slot pitch each and latches once per pitch, giving a mean-value delay
N*pitch/(2v) plus a mean latch staleness pitch/(2v).
WHY IT IS HERE.  The first closed-loop 'V' runs (ML0136-ML0139, fw v11) limit cycled at
2.3-2.6 Hz = 14.5-16.3 rad/s = this design's crossover, at every step size.  The shipped
estimator was a ~113 ms boxcar: ~56 ms group delay, {np.degrees(wc_ach*56e-3):.0f} deg at the crossover, against a
49.6 deg phase margin.  The element was absent from the synthesis plant, so the reported
margin was never the margin the hardware had.  This gate battery now measures it (§6b).

K_F FORCE-AXIS CORRECTION, 2026-08-16c (upstream, plant_mimo.py).  The force chain carried
the wrong gear ratio and the wrong radius.  PHI 9.49 -> 6.86 (the as-fitted 29T pinion; the
9.49 was a stock-gearing web figure) and the FORCE radius 0.0762 m (flywheel) -> 0.033 m
(TIRE).  The rig is motor -> gearbox -> TIRE -> roller -> FLYWHEEL: torque acts on the
tire, while the encoder and the inertia belong to the flywheel, so the two radii are
different quantities and were being conflated.
      K_F  0.4516 -> {pm.force_per_amp(P0):.4f} N/A   (x1.669)
      b_eff 0.32 -> {pm.b_eff(OP0, P0):.3f} N*s/m,  F_c 1.2 -> 2.00 N  (the drag law was derived
      FROM hold currents THROUGH K_F, so it rescales with it and i_m0 is INVARIANT at 4.07 A)
      G22(0)  1.7641 -> {G22.dcgain():.4f} (m/s)/A   effective K_F*K_v = {pm.force_per_amp(P0)*P0['K_v']:.4f} N/A (x1.34)
      mechanical pole  -0.0914 -> {-pm.b_eff(OP0, P0)/P0['m_eff']:.4f} rad/s
THE FACTOR-OF-2 GAIN CONTRADICTION IS RESOLVED.  Recomputed in the corrected axis:
      ML0136-0139 +12 A ramps -> implied K_F 0.836-0.914 N/A = x1.109 to x1.213
      4.5 +- 0.4 A cruise hold -> implied K_F 0.682 N/A      = x0.905 (band x0.83-x0.99)
The cruise-implied gain scales WITH the drag law and the ramp-implied one does not, so
correcting K_F moves only the ramps and the two land 1.09-1.34x apart, not ~2x.  m_eff =
3.5 kg is vindicated by the same arithmetic (the 1.6-2.4 kg inferences were F/a fits made
through the understated force axis).  K_v = {P0['K_v']:g} is the geometric mean of the two
evidence centres; corners {{0.85, 1.25, 1.85}} -> {{0.75, 1.00, 1.35}}, span 2.2x -> 1.8x.
eta_dt stays 0.85: the ramp residual is now only x1.11-1.21, no longer the unphysical
eta_dt >= 1.0, but raising it would move i_m0 and the coupling gains that nothing measures.

PLANT RE-IDENTIFIED 2026-08-16 (calibration/motor_id_20260815.md).  k_t (4.266e-3 N*m/A
from the measured flux linkage), R_m (22.6 mOhm), m_eff (3.5 kg), the radii (0.033 m tire
for force, 0.0762 m flywheel for encoder/inertia), tau_v (1.0 ms) and the drag law
(b_eff 0.534 N*s/m local slope + F_c 2.00 N Coulomb) are all MEASURED.  Effect on the
design plant:
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

LADDER RE-RUN 2026-08-16b on the ESTIMATOR plant.  The previous ladder (and the one
before it) is VOID: the estimator delay adds phase at crossover and the K_v re-centring
raises the plant gain.
NOT RE-RUN 2026-08-16c.  The K_F force-axis correction raises the nominal plant gain a
further x1.34, so every NON-CHOSEN row below is indicative only.  The CHOSEN rung was
re-run in full and passes every gate on the corrected plant; its re-measured numbers are
in the margins/robustness sections below, not in the table.  Ladder as originally run (Wd break = 2.5*WC,
Wu = makeweight(dc, 300, hf); "PM@0.5" = phase margin at the 0.5 m/s estimator corner;
worst ||S|| over the 24 drive corners x 3 estimator speeds = 72 plants):
    WC=24, Wu(0.3 ,300,20  ) -> g_opt 17.76, wc  8.78, PM 57.8, PM@0.5 53.2, ||S|| 1.589  (wc < 12: FAILS)
    WC=24, Wu(0.1 ,300, 5  ) -> DGKF a-posteriori gate failed (conditioning) -- no controller
    WC=30, Wu(0.1 ,300, 5  ) -> g_opt 12.38, wc 12.69, PM 46.4, PM@0.5 39.9, ||S|| 2.489
    WC=40, Wu(0.1 ,300, 5  ) -> g_opt 15.77, wc 14.80, PM 44.8, PM@0.5 37.2, ||S|| 2.938  (PM < 45: FAILS)
    WC=45, Wu(0.1 ,300, 5  ) -> g_opt 17.43, wc 15.73, PM 44.2, PM@0.5 36.1, ||S|| 3.178  (both FAIL)
    WC=45, Wu(0.15,300, 7.5) -> g_opt 20.07, wc 15.02, PM 48.3, PM@0.5 40.6, ||S|| 2.608
    WC=50, Wu(0.1 ,300, 5  ) -> g_opt 19.09, wc 16.73, PM 43.7, PM@0.5 35.0, ||S|| 3.441  (both FAIL)
    WC=50, Wu(0.15,300, 7.5) -> g_opt 21.84, wc 15.98, PM 47.7, PM@0.5 39.4, ||S|| 2.789
    WC=50, Wu(0.2 ,300,10  ) -> g_opt 24.67, wc 15.02, PM 50.7, PM@0.5 43.0, ||S|| 2.417
    WC=50, Wu(0.25,300,12.5) -> g_opt 27.44, wc 14.35, PM 52.9, PM@0.5 45.5, ||S|| 2.187
    WC=55, Wu(0.1 ,300, 5  ) -> g_opt 20.74, wc 17.52, PM 43.2, PM@0.5 34.2, ||S|| 3.724  (both FAIL)
    WC=55, Wu(0.15,300, 7.5) -> g_opt 23.60, wc 16.73, PM 47.1, PM@0.5 38.5, ||S|| 2.980
    WC=55, Wu(0.2 ,300,10  ) -> g_opt 26.56, wc 15.98, PM 50.1, PM@0.5 41.9, ||S|| 2.559
    WC=60, Wu(0.1 ,300, 5  ) -> g_opt 22.39, wc 18.35, PM 42.8, PM@0.5 33.3, ||S|| 4.035  (both FAIL)
    WC=60, Wu(0.2 ,300,10  ) -> g_opt 28.44, wc 16.73, PM 49.6, PM@0.5 41.0, ||S|| 2.711
    WC=60, Wu(0.25,300,12.5) -> g_opt 31.50, wc 15.98, PM 51.9, PM@0.5 43.7, ||S|| 2.418  <- CHOSEN
    WC=60, Wu(0.05,300, 2.5) -> g_opt 20.31, wc 18.92, PM 38.8, PM@0.5 29.1, ||S|| 5.267  (all FAIL)
    WC=65, Wu(0.2 ,300,10  ) -> g_opt 30.28, wc 17.52, PM 49.1, PM@0.5 40.1, ||S|| 2.868
    WC=70, Wu(0.1 ,300, 5  ) -> g_opt 25.67, wc 19.81, PM 42.1, PM@0.5 31.9, ||S|| 4.752  (both FAIL)
    WC=70, Wu(0.25,300,12.5) -> g_opt 35.44, wc 17.52, PM 51.0, PM@0.5 42.0, ||S|| 2.670
    WC=80, Wu(0.05,300, 2.5) -> g_opt 26.82, wc 21.72, PM 38.3, PM@0.5 27.1, ||S|| 7.630  (all FAIL)

CHOICE: WC={WC:g}, Wu({WU_DC}, 300, {WU_HF}) — the rung that maximizes crossover subject to
BOTH the gates and the 2.5 worst-||S|| TARGET (not merely the 3.0 gate).  Every rung with a
higher crossover (WC=65/70 at Wu(0.2..0.25); WC=55 at Wu(0.15)) breaks the 2.5 target, and
the rungs that break it hardest break PM as well.  The SHAPE of the ladder has changed from
the previous round: the binding constraint is no longer phase margin alone but the
worst-corner peak, because the worst corner is now the 0.5 m/s ESTIMATOR corner rather than
a parameter extreme (worst ||S|| {worstS:.3f} at K_v 1.35 / pole_factor 0.5 / tau_v 5 ms /
Td_v 4 ms / v0 0.5 m/s).

THE HEADLINE.  Adding a real 3 ms sensor delay did NOT cost bandwidth, and neither did the
x1.34 force-axis gain correction that followed it.  Achieved crossover {wc_ach:.2f} rad/s
against the previous round's 15.98, with phase margin {pm_deg:.1f} deg (49.6 two rounds ago) and a
comparable worst corner ({worstS:.3f}) on a corner family that is 3x larger than the
pre-estimator one and contains a 12 ms delay.  Measurement paid for both: K_v's span fell
4.0x -> 2.2x -> 1.8x across the two rounds, each narrowing bought with a datapoint rather
than with conservatism.
There is NO case for chasing bandwidth past this.  The ML0136-ML0139 limit cycle was a
16 rad/s loop meeting ~56 ms of unmodelled lag; the fix is to model the lag and KEEP the
bandwidth, not to raise it.  What bounds the design from above is now the 12 ms low-speed
corner: PM@0.5 is {pm_low:.1f} deg at the chosen rung and 27-33 deg at the failing rungs.

CROSSOVER GATE BAND NARROWED 12-48 -> 12-30.  Nothing above 21.7 rad/s is reachable on
this plant (and what reaches it fails PM and ||S|| badly), so the old upper bound could
never bind.  30 is still non-binding but within 1.4x of the reachable ceiling, so a future
plant change that pushed the loop far past today's bandwidth would trip it.

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
corner family        = {len(pm.drive_corners())} drive_corners() x v0 in {V0_SET} m/s = {n_corner} plants
                       (K_v in {{0.75, 1.00, 1.35}} x pole_factor in {{0.5, 3}} x tau_v in
                        {{0.5, 5}} ms x Td_v in {{1, 4}} ms, x the ESTIMATOR-DELAY axis
                        Td_est(v0) in {{11.97, 2.99, 1.20}} ms.
                        The v0 axis is REINSTATED (2026-08-16b) for a new reason: the
                        calibrated b_eff has no v0 term, so the axis was degenerate last
                        round, but Td_est(v0) = (N+1)*pitch/(2 v0) is strongly speed
                        dependent, a 10x span across the operating range.  The drag-slope
                        speed dependence it used to stand for stays on pole_factor's
                        upper corner.
                        K_v is RE-CENTRED, not merely re-scaled: nominal {P0['K_v']:g} is
                        the geometric mean of the two end-to-end gain measurements,
                        recomputed 2026-08-16c in the corrected force axis, and the span
                        narrows 2.2x -> 1.8x.)
VALIDITY FLOOR       = v0 >= {pm.V0_VALID_MIN} m/s.  Below it Td_est grows without bound
                       (19.9 ms at 0.3 m/s, 59.8 ms at 0.1 m/s; the estimator times out and
                       reports 0 below ~{pm.V_EST_MIN} m/s) and this design is NOT gate-checked
                       there.  Closing the velocity loop below the floor needs a wider delay
                       corner (paid for in bandwidth) or a gain schedule on v.
continuous unstable  = {n_unstable}
worst ||S||inf cont. = {worstS:.4f} at {worstS_corner}
discrete max |z|     = {worst_rad:.4f}
worst ||S||inf disc. = {worstSd:.4f} at {worstSd_corner}

── bench-evidence gates (NEW 2026-08-16b; §6b) ──
Td_est at design v0  = {TD_EST0*1e3:.3f} ms, consuming {phase_est_deg:.2f} deg of phase at the achieved
                       crossover {wc_ach:.2f} rad/s   (GATE < 10 deg)
                       For contrast, the RETIRED ~113 ms boxcar estimator's ~56 ms group
                       delay consumed {np.degrees(wc_ach*56e-3):.0f} deg there — more than the entire phase
                       margin, which is the ML0136-ML0139 limit cycle in one number.
0.5 m/s corner       = stable, PM = {pm_low:.1f} deg at {w[i_low]:.2f} rad/s, ||S||inf = {hinf_norm(S_low):.3f}
                       (GATE: stable AND PM > 30 deg.  30, not 45, because this is a
                        boundary of the validated envelope, not the design point.)

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
scheme used          = Hanus CONDITIONING (general-L form, fw v18) on the {ctrl_d.n}-state
                       discrete realization:
                         u_unsat = Cd x + Dd e ; u = clamp(u_unsat)
                         x[k+1]  = Ad x + Bd e + L (u - u_unsat),  Dd = {ctrl_d.D[0, 0]:.9e}
                       The conditioning term is IDENTICALLY ZERO while unsaturated, so the
                       law is then exactly x[k+1] = Ad x + Bd e -- the linear controller.
                       Exactly equivalent to the biquad+integrator form when unsaturated
                       (gated: max |diff| = {np.max(np.abs(_ub - _uc)):.2e} A over an 100-sample sequence).
                       L (shipped float32)  = {np.array2string(L_H, precision=9, max_line_width=200)}
                       eig(Ad - L Cd)       = {np.array2string(np.sort_complex(_ev_aw).real, precision=9, max_line_width=200)}
RETIRED fw v10-v17   = the Hanus SELF-conditioned special case L = Bd/Dd, i.e.
                         x[k+1] = (Ad - Bd Cd/Dd) x + Bd u/Dd
                       Its saturated-mode matrix AC = Ad - Bd Cd/Dd has eigenvalues equal to
                       the controller's transmission ZEROS, and one sits at EXACTLY z = -1:
                       the controller is a PARALLEL sum of two TUSTIN branches and both
                       numerators carry (z+1) (Tustin of the integrator is
                       (kI Ts/2)(z+1)/(z-1)), so the factor survives at ANY weight rung on
                       ANY plant.  Zero damping at Nyquist let a relay limit cycle live
                       against the clamp: constant-error rail dwells went rail-to-rail at
                       24 A p-p in a period-4 (++--) square wave at 125 Hz.  Measured over
                       the sweep below: fw v17 coefficients fail 14 of 48 dwells
                       (e = 8.25..11.75), fw v18 pre-fix 15 of 48.  The defect shipped from
                       fw v10 and was NOT a v18 regression.
                       eig(AC) (the defect)  = {np.array2string(np.sort_complex(np.linalg.eigvals(_AC_DESIGN)).real, precision=9, max_line_width=200)}
saturated-mode gates = (a) every OSCILLATORY (non-positive-real) eigenvalue of (Ad - L Cd)
                           must satisfy |lambda| < 1 - {AW_EIG_MARGIN:g}.
                           Worst measured: {_osc_rad:.9f}.  Spectral radius {_aw_rad:.9f}
                           (the slow positive-real integrator mode -- exempt by design: a
                           decaying exponential cannot oscillate, and forcing it inward
                           destroys the integrator's conditioning memory).
                           Acceptance-checked to FAIL both retired spectra above.
                       (b) LOAD-BEARING -- constant-error dwell sweep, e in [0.25, 12.00]
                           step 0.25 ({_dwell_errs.size} cases), {_DWELL_TICKS} ticks, p-p over the last
                           {_DWELL_TAIL}, through the SHIPPED float32 coefficients.
                           Result: {_dwell_errs.size - len(_dwell_bad)}/{_dwell_errs.size} settle, worst tail p-p = {_dwell_worst:.3e} A
                           (tol {_DWELL_TOL:.0e} A).  Gate (a) alone is NOT sufficient and would
                           have passed the fw v18 pre-fix coefficients (max|eig(AC)| =
                           0.9999990, strictly inside the circle, and still limit-cycling).
Teensy cost note     = this baseline needs a {ctrl_d.n}-state state-space realization, NOT the
                       shipped biquad cascade.  Phase-6 implementation-cost datapoint.

── time-domain (discrete, clamped, Hanus-conditioned general-L form) ──
step 0->2 m/s : peak i = {np.max(np.abs(u1)):.3f} A, 2% settle = {t_set1:.3f} s,
                overshoot = {ovs1:.1f} %, final err = {y1[-1]-2.0:.2e} m/s,
                tail p-p = {np.ptp(tail):.2e} m/s (no limit cycle)
                NOTE: +-{I_CLAMP:.0f} A gives a_max = K_F*K_v*I/m = {pm.force_per_amp(P0)*P0['K_v']*I_CLAMP/P0['m_eff']:.3f} m/s^2, so 0->2 m/s
                cannot physically take less than ~{2.0/(pm.force_per_amp(P0)*P0['K_v']*I_CLAMP/P0['m_eff']):.2f} s however the loop is
                shaped.  The {wc_ach:.1f} rad/s design bandwidth is a SMALL-SIGNAL spec; this is
                a large-signal event.  Time on the rail this run: {np.sum(np.abs(u1) >= I_CLAMP - 1e-9)*TS*1e3:.0f} ms.
                The calibration cut a_max hard (K_F 1.3338 -> {pm.force_per_amp(P0):.4f} N/A and the
                clamp 20 -> {I_CLAMP:.0f} A both push the same way); the 2026-08-16b gain
                re-centring gives {P0['K_v']:g}x of it back, but large-signal velocity moves remain
                inertia-limited, not loop-limited.  Sanity check against the bench: at
                K_v = {P0['K_v']:g} the model's NET 12 A acceleration is
                {(pm.force_per_amp(P0)*P0['K_v']*I_CLAMP - P0['F_c'])/P0['m_eff']/I_CLAMP:.3f} (m/s^2)/A against the ML0136-0139 measured
                0.186-0.204 — the design plant is still {(1 - (pm.force_per_amp(P0)*P0['K_v']*I_CLAMP - P0['F_c'])/P0['m_eff']/I_CLAMP/0.195)*100:.0f} % conservative on large-signal
                authority.  That is deliberate: K_v's nominal is the geometric mean of the
                ramp and cruise-hold evidence, and the ramps are the optimistic half.  It
                is also the safe direction — it costs settling time, not stability.
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
                            AD/BD/CD/DD/L, plus AC as an identity cross-check ONLY --
                            implementing with AC reintroduces the retired defect above;
                            DRIVE_CTRL_ prefix -- study copy)
../teensy_controller/drive_controller_coeffs.h
                            (same content, firmware copy: included by drive_controller.h
                            and compiled in when USE_YOULA_DRIVE_CONTROLLER is 1)
figures/drive_siso_step.csv
figures/drive_siso_replay.csv  ({len(_e_small)} unsaturated + {len(_e_sat)} saturated (e_in, u_out)
                            samples from the Hanus controller, seed 20260816 — the
                            reference vectors a firmware implementation replays against.
                            CHANGED 2026-08-16b: the 'regen' episode is now generated
                            CLOSED-LOOP through the shipped float32 coefficients.  It was
                            previously the float64 sim's error sequence replayed OPEN-LOOP
                            through the float32 controller — self-consistent, but off its
                            own trajectory and therefore sitting ON the clamp boundary,
                            which made the vectors knife-edged: a consumer parsing e_in at
                            %.9e instead of %.17e diverged 54 mA (a HISTORICAL figure from
                            the 2026-08-16b emission — the only hardcoded number in this
                            block, kept because it describes a construction that no longer
                            exists).  Closed-loop generation
                            cuts that to {_SENS['%.9e stimulus truncation']*1e3:.2f} mA, and gates bound it.
                            TOLERANCES (MEASURED this run, shipped machine-readably as
                            DRIVE_REPLAY_<EPISODE>_TOL_A in drive_replay_vectors.h):
                              'small' {REPLAY_TOL_SMALL:.0e} A  (firmware-path deviation {_small_dev*1e3:.2e} mA)
                              'regen' {REPLAY_TOL_REGEN*1e3:.0f} mA   (2x the worst measured sensitivity,
                                                rounded up)
                            Regen sensitivity breakdown:
{chr(10).join(f"                              {v*1e3:8.2f} mA  {k}" for k, v in sorted(_SENS.items(), key=lambda kv: -kv[1]))}
                            The regen figure is irreducible, not slack — the controller
                            makes {_n_clamp_trans} clamp-state transitions during the saturated
                            transient (2 ms sample rate, 545 A/(m/s) non-integral branch)
                            and approaches the decision boundary to within {_boundary_uA:.1f} uA, so a
                            boundary sample always exists and one flipped decision is ~8 A
                            of state drive.  Deviation decays to {_tail_dev*1e3:.2f} mA over the last
                            200 samples: boundary dither, not divergence.)
""")

print(f"\nartifacts: drive_siso_coeffs.h, "
      f"../teensy_controller/drive_controller_coeffs.h, drive_siso_metrics.txt, "
      f"figures/drive_siso_step.csv, figures/drive_siso_replay.csv")
print("\n" + ("ALL GATES PASSED" if not failures else "FAILURES: " + "; ".join(failures)))
raise SystemExit(1 if failures else 0)
