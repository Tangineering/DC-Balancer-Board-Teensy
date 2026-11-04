#!/usr/bin/env python3
"""
fit_pdemand.py — fit a real road-load model for P_demand from measured bags.

    python3 fit_pdemand.py ../../logs/rosbags/rosbag_sdp_2026-10-29_19-51-48 [more bags ...]

WHY
---
drive_cycle_node currently publishes P_demand = mass * v * a, inertial power
only. On rosbag_sdp_2026-10-29_19-51-48 that peaked at 3.9 W while the MEASURED
bus power, V_bus * (I_fc + I_batt), averaged 6.4 W and peaked near 23 W. The
model is missing roughly three quarters of the load: rolling resistance,
drivetrain and boost losses, and the standing aux draw.

That mis-scaling is not cosmetic. The H-20's hydrogen flow is dead linear below
15 W (datasheet: 10.0 ml/min/W from 0 to 15 W, rising to 28.6 above 20 W), so an
EMS optimising a 4 W problem never reaches the part of the curve where the split
matters, and every formulation degenerates to bang-bang. Feeding it the real
load puts the stack where the curve bends.

THE MODEL
---------
Standard coastdown road load plus inertia, referred to the bus:

    P_bus = a0  +  a1*v  +  a2*v^2  +  a3*v^3  +  a4*(m*a*v)

  a0  standing draw: controller, Teensy, sensors (W)
  a1  rolling / bearing drag -> F = a1 gives P = a1*v
  a2  viscous term
  a3  aerodynamic: F ~ v^2 gives P ~ v^3 (small at these speeds, kept for the fit)
  a4  effective inertia multiplier. > 1 means the flywheel's rotating inertia
      adds to the 5 kg translational mass, which it does.

Linear in the coefficients, so ordinary least squares.

TRACTION ONLY
-------------
Fitted on samples where the model's mechanical power is positive. During braking
the car has no regen path, so the bus cannot absorb power and measured draw
decouples from the model entirely -- including braking samples would bias every
coefficient. Those samples are reported separately so you can see what the bus
actually does while decelerating.
"""

import glob
import os
import sys

try:
    from mcap_ros2.reader import read_ros2_messages
    import numpy as np
except ImportError:
    sys.exit("pip install mcap mcap-ros2-support numpy")

# Effective translational mass, INCLUDING the flywheel's rotating inertia
# referred to translation. Sid measured 3.5 kg at the current flywheel position
# (2026-10-29); drive_cycle_node still has vehicle_mass = 5.0, so its inertial
# term is overstated by 5.0/3.5 = 1.43x. Override with --mass.
MASS = 3.5
USE_AERO = False      # v^3 is collinear with v and v^2 at these speeds
USE_I2R  = False      # --i2r adds a force^2 copper-loss term
A1_GUESS, A2_GUESS = 4.03, 0.47   # drag force seed for the F^2 term
IDX_V_ACT, IDX_I_BATT, IDX_I_FC, IDX_V_BUS = 0, 2, 5, 6
V_MOVING = 0.15          # m/s below which we treat the car as stopped


def find(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    h = glob.glob(os.path.join(p, "*.mcap"))
    if len(h) == 1:
        return h[0]
    sys.exit(f"Expected one .mcap in {p}, found {len(h)}")


def load(path):
    t, v, pb = [], [], []
    t0 = None
    for m in read_ros2_messages(find(path)):
        if m.channel.topic != "/vehicle_state":
            continue
        d = list(m.ros_msg.data)
        if len(d) < 18:
            continue
        ts = m.log_time_ns / 1e9
        if t0 is None:
            t0 = ts
        t.append(ts - t0)
        v.append(d[IDX_V_ACT])
        pb.append(d[IDX_V_BUS] * (abs(d[IDX_I_FC]) + abs(d[IDX_I_BATT])))
    return np.array(t), np.array(v), np.array(pb)


def main():
    global MASS, USE_AERO, USE_I2R
    args = [a for a in sys.argv[1:]]
    if "--i2r" in args:
        USE_I2R = True; args.remove("--i2r")
    if "--aero" in args:
        USE_AERO = True; args.remove("--aero")
    if "--mass" in args:
        i = args.index("--mass")
        MASS = float(args[i+1]); del args[i:i+2]
    if not args:
        sys.exit(__doc__)
    print(f"  effective mass {MASS} kg (flywheel inertia included)")
    T, V, PB = [], [], []
    for p in args:
        t, v, pb = load(p)
        if t.size < 100:
            print(f"  skipping {os.path.basename(p)}: only {t.size} samples")
            continue
        print(f"  {os.path.basename(p.rstrip('/'))}: {t.size} samples, "
              f"{t[-1]:.0f} s, v max {v.max():.2f} m/s, P_bus max {pb.max():.1f} W")
        T.append(t); V.append(v); PB.append(pb)
    if not T:
        sys.exit("No usable bags.")

    # ── MODEL STRUCTURE (revised 2026-10-29 after the first fit) ─────────────
    # Three changes, each forced by what the first fit returned:
    #
    #  1. NO v^3 TERM. Over 0.15-2.9 m/s, v / v^2 / v^3 are nearly collinear, so
    #     least squares traded them off freely and returned a NEGATIVE aero
    #     coefficient (-0.84). Aero is negligible at these speeds anyway; the
    #     term bought nothing and destabilised the others. --aero puts it back.
    #
    #  2. RECTIFIED INERTIA. This car has no working regen path, so braking
    #     returns nothing to the bus -- measured draw while braking (9.43 W mean)
    #     was almost identical to traction (10.78 W). A signed m*v*a term cannot
    #     represent that. max(m*v*a, 0) can: inertia costs power going up and
    #     gives none back coming down, while the drag terms apply throughout.
    #     That also lets the braking samples back into the fit instead of
    #     discarding 6254 of them.
    #
    #  3. NON-NEGATIVE COEFFICIENTS. Every term here is a loss or an inertia;
    #     none can be negative physically. NNLS enforces it rather than hoping.
    rows, y = [], []
    brake_pb = []
    for t, v, pb in zip(T, V, PB):
        k = 11
        vs = np.convolve(v, np.ones(k) / k, mode="same")
        a = np.gradient(vs, t)
        pm = np.maximum(MASS * vs * a, 0.0)     # rectified: no regen on this car
        moving = vs > V_MOVING
        brake_pb.append(pb[moving & (MASS * vs * a < 0)])
        cols = [np.ones(moving.sum()), vs[moving], vs[moving] ** 2]
        if USE_AERO:
            cols.append(vs[moving] ** 3)
        cols.append(pm[moving])
        if USE_I2R:
            # Motor + VESC copper loss goes as current^2, and current goes as
            # TORQUE, i.e. as tractive force. So the loss is ~ F^2 with
            # F = m*a + drag. Linear terms cannot represent it: it is small at
            # cruise and large during acceleration, which is exactly where the
            # first two fits left their residual.
            F = np.maximum(MASS * a[moving], 0.0) + A1_GUESS + A2_GUESS * vs[moving]
            cols.append(F ** 2)
        rows.append(np.vstack(cols).T)
        y.append(pb[moving])
    A = np.vstack(rows); y = np.concatenate(y)
    print(f"\n  fitting on {A.shape[0]} moving samples "
          f"(braking included, inertia rectified)")

    try:
        from scipy.optimize import nnls
        coef, _ = nnls(A, y)
        print("  non-negative least squares")
    except ImportError:
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        print("  scipy unavailable — plain least squares, coefficients may go negative")
    pred = A @ coef
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    names = ["a0 standing draw        (W)",
             "a1 rolling / bearing    (W per m/s)",
             "a2 viscous              (W per (m/s)^2)"]
    if USE_AERO:
        names.append("a3 aero                 (W per (m/s)^3)")
    names.append("a4 inertia multiplier   (-)")
    if USE_I2R:
        names.append("a5 copper loss          (W per N^2)")
    print("\n  P_bus = a0 + a1*v + a2*v^2" + (" + a3*v^3" if USE_AERO else "")
          + " + a4*max(m*v*a, 0)\n")
    for n, c in zip(names, coef):
        print(f"    {n}  {c:+10.4f}")
    print(f"\n    R^2 {r2:.4f}   residual RMS {np.sqrt(ss_res/len(y)):.3f} W")

    _ia = 3 + (1 if USE_AERO else 0)
    if coef[_ia] < 0.5:
        print("\n    a4 below 0.5 — the inertia term is not being identified. The")
        print("    cycle may be too gentle to separate it from the speed terms.")
    elif coef[_ia] > 1.0:
        print(f"\n    a4 = {coef[_ia]:.2f} > 1: the flywheel's rotating inertia adds to")
        print("    the 5 kg translational mass, as expected.")

    old = A[:, 3 + (1 if USE_AERO else 0)]   # the current model, rectified m*v*a
    print(f"\n  current model (mass*v*a) vs measured, same samples:")
    print(f"    current mean {old.mean():6.2f} W   max {old.max():6.2f} W")
    print(f"    measured mean {y.mean():6.2f} W   max {y.max():6.2f} W")
    print(f"    understated by {y.mean()/max(old.mean(),1e-9):.1f}x on the mean")

    idle = []
    for t, v, pb in zip(T, V, PB):
        k = 11
        vs = np.convolve(v, np.ones(k) / k, mode="same")
        idle.append(pb[vs <= V_MOVING])
    idle = np.concatenate(idle) if any(i.size for i in idle) else np.array([])
    if idle.size:
        print(f"\n  measured draw while STOPPED ({idle.size} samples): "
              f"mean {idle.mean():.2f} W")
        print(f"    a0 fitted at {coef[0]:.2f} W. NNLS only sees moving samples, so if")
        print( "    these disagree, a0 has been absorbed into a1*v -- harmless for")
        print( "    prediction above walking pace, wrong near zero speed.")
    bp = np.concatenate(brake_pb) if any(b.size for b in brake_pb) else np.array([])
    if bp.size:
        print(f"\n  while braking ({bp.size} samples): bus still draws "
              f"mean {bp.mean():.2f} W, max {bp.max():.2f} W")
        print("    (no regen path, so the bus sources rather than absorbs — these")
        print("     samples are excluded from the fit on purpose)")

    print("\n  --- paste into drive_cycle_node ---")
    aero = f" + {coef[3]:.4f}*v*v*v" if USE_AERO else ""
    print(f"    P = ({coef[0]:.4f} + {coef[1]:.4f}*v + {coef[2]:.4f}*v*v{aero}")
    print(f"         + max({coef[_ia]:.4f}*self._mass*v*acc, 0.0))")
    print(f"\n  ALSO set drive_cycle_node's vehicle_mass to {MASS} (it is 5.0), or the")
    print("  inertial term is counted twice over at the wrong scale.")
    print("\n  Then rebuild the cost-to-go on the new demand range and raise")
    print("  P_FC_MAX toward 20 W (1.27 A at 15.8 V, inside LIMIT_I_FC_MAX 1.4).")


if __name__ == "__main__":
    main()
