#!/usr/bin/env python3
"""
fit_fc.py — fit the fuel-cell polarization curve, and from it the fuel map.

    python3 fit_fc.py ../../logs/rosbags/rosbag_sdp_2026-10-28_20-46-53

Why this exists
---------------
The SDP's fuel term is currently `un + K_CONV*un**2` with K_CONV guessed at 3.0.
The convexity is physically real -- hydrogen rate goes as stack CURRENT, bus
power is V*I, and V_fc droops under load, so the last watt costs more than the
first -- but the number should come from the stack, not from a guess.

V_fc(I_fc) is measured in every bag. Fit it, then:

    P_bus(I)  = V_fc(I) * I                       (what the SDP calls u)
    mdot(I)   proportional to I                   (Faraday: rate goes as current)

so expressing mdot against P gives the fuel map's true shape, and K_CONV is
whatever quadratic best matches it over 0..P_FC_MAX.

Reports the fit, the implied K_CONV, and how far the guessed 3.0 was off.
"""

import glob
import os
import sys

try:
    from mcap_ros2.reader import read_ros2_messages
    import numpy as np
except ImportError:
    sys.exit("pip install mcap mcap-ros2-support numpy")

IDX_V_FC, IDX_I_FC = 4, 5
I_FLOOR = 0.05          # ignore samples below this: V_fc is open-circuit there
P_FC_MAX_FIT = 12.0     # the SDP's ceiling, for normalising K_CONV


def find(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    h = glob.glob(os.path.join(p, "*.mcap"))
    if len(h) == 1:
        return h[0]
    sys.exit(f"Expected one .mcap in {p}, found {len(h)}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    V, I = [], []
    for m in read_ros2_messages(find(sys.argv[1])):
        if m.channel.topic != "/vehicle_state":
            continue
        d = list(m.ros_msg.data)
        if len(d) < 18:
            continue
        V.append(d[IDX_V_FC]); I.append(d[IDX_I_FC])
    V = np.array(V); I = np.array(I)
    if V.size == 0:
        sys.exit("No /vehicle_state in this bag.")

    keep = I > I_FLOOR
    print(f"samples {V.size}, loaded (I_fc > {I_FLOOR}) {keep.sum()}")
    if keep.sum() < 200:
        sys.exit("Too few loaded samples to fit. Use a bag where the FC ran.")

    Vl, Il = V[keep], I[keep]
    print(f"I_fc  {Il.min():.3f} .. {Il.max():.3f} A")
    print(f"V_fc  {Vl.min():.2f} .. {Vl.max():.2f} V")

    # ── polarization: V = V0 - R*I ───────────────────────────────────────────
    A = np.vstack([np.ones_like(Il), -Il]).T
    (V0, R), *_ = np.linalg.lstsq(A, Vl, rcond=None)
    resid = Vl - (V0 - R * Il)
    print(f"\npolarization fit   V_fc = {V0:.3f} - {R:.4f}*I_fc")
    print(f"  residual RMS {np.sqrt((resid**2).mean()):.4f} V")
    if R <= 0:
        print("  WARNING: non-positive slope — no measurable droop in this bag.")
        print("  The fuel map is then effectively LINEAR and K_CONV should be ~0,")
        print("  which makes the policy bang-bang. Collect a run with more FC range.")
        return

    # ── binned check, so the fit is not carried by one cluster ───────────────
    print("\n  binned mean V_fc (sanity — should fall as I rises):")
    edges = np.linspace(Il.min(), Il.max(), 7)
    for a, b in zip(edges[:-1], edges[1:]):
        s = (Il >= a) & (Il < b)
        if s.sum() > 20:
            print(f"    {a:.2f}-{b:.2f} A  n={s.sum():5d}  V_fc {Vl[s].mean():.3f}")

    # ── fuel map: mdot ~ I, P = V(I)*I, refit as quadratic in normalised P ───
    Igrid = np.linspace(0, Il.max(), 400)
    Pgrid = (V0 - R * Igrid) * Igrid
    ok = (Pgrid > 0) & (Pgrid <= P_FC_MAX_FIT)
    if ok.sum() < 20:
        print(f"\n  FC never reached enough power to span 0..{P_FC_MAX_FIT} W here.")
        print(f"  max P_fc in this bag {Pgrid.max():.2f} W — fit is an extrapolation.")
    Pn = Pgrid[ok] / P_FC_MAX_FIT
    mdot = Igrid[ok]
    mdot = mdot / mdot.max() if mdot.max() > 0 else mdot

    # least squares for mdot_n = a*Pn + b*Pn^2, then K_CONV = b/a
    B = np.vstack([Pn, Pn**2]).T
    (a, b), *_ = np.linalg.lstsq(B, mdot, rcond=None)
    print(f"\nfuel map over 0..{P_FC_MAX_FIT} W:  mdot_n = {a:.4f}*Pn + {b:.4f}*Pn^2")
    if a > 0:
        k = b / a
        print(f"  implied K_CONV = {k:.3f}   (currently using 3.000)")
        if abs(k) < 0.05:
            print("  Near zero: over THIS power range the map is almost linear, so a")
            print("  quadratic buys little and the policy will tend to bang-bang.")
        elif k < 0:
            print("  NEGATIVE: concave over this range. A convex penalty is then the")
            print("  wrong shape — do not just plug this in; say so and we rethink.")
        else:
            print(f"  Rebuild with:  --k-conv {k:.3f}")
    print("\nNOTE: this is the ELECTRICAL convexity only — it assumes hydrogen rate")
    print("is proportional to current. Purge losses are NOT in it. Your tank-weight")
    print("measurement is what folds those in, and it belongs in the same fit.")


if __name__ == "__main__":
    main()
