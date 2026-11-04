#!/usr/bin/env python3
"""
make_tpm_newbuild.py — build the demand transition matrix from YOUR bags.

    python3 make_tpm_newbuild.py -o TPM_newbuild.mat ../../logs/rosbags/rosbag_a ../../logs/rosbags/rosbag_b ...

WHY A NEW TPM
-------------
TPM.mat came from the full-scale MATLAB work. Its row i means "demand was in
bin i", and bin i meant a specific wattage on the OLD grid (-54..150 W, later
relabelled -10..15 W). The new build redefines P_demand entirely: a fitted road
load spanning 0..35 W instead of inertial-only power spanning 0..3.9 W.

Reusing the old matrix would mean applying transition probabilities estimated
for one set of physical demands to a completely different set. A TPM mostly
encodes "demand tends to stay near where it was", so it partly survives -- but
the diagonal dominance would be wrong, and that is the part the SDP leans on.

Estimated from your own bags it is also defensible in a way the inherited one is
not: the stochastic model is the only component of the SDP claiming to describe
how THIS vehicle's demand behaves.

METHOD
------
Replay each bag's speed trace through the same road-load model drive_cycle_node
now publishes, bin the result on the cost-to-go's demand grid, and count
transitions at the DP decision interval (not the sample rate -- the value
function reasons at DT_DP seconds, so transitions must be counted over that
same interval or the chain looks far more persistent than it is).

Rows with no observations fall back to staying put, which is the right prior
for an unvisited demand level and keeps the matrix stochastic.
"""

import argparse
import glob
import os
import sys

import numpy as np
import scipy.io

# Must match the cost-to-go and drive_cycle_node_newbuild
PDEM_MIN, PDEM_MAX, PDEM_BINS = 0.0, 35.0, 50
DT_DP = 60.0
MASS = 3.5
A0, A1, A2, A4 = 0.0000, 4.0297, 0.4658, 1.1695
IDX_V_ACT = 0
V_MOVING = 0.15


def find(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    h = glob.glob(os.path.join(p, "*.mcap"))
    if len(h) == 1:
        return h[0]
    sys.exit(f"Expected one .mcap in {p}, found {len(h)}")


def demand_series(path):
    try:
        from mcap_ros2.reader import read_ros2_messages
    except ImportError:
        sys.exit("pip install mcap mcap-ros2-support")
    t, v = [], []
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
    if len(t) < 100:
        return None, None
    t = np.array(t); v = np.array(v)
    vs = np.convolve(v, np.ones(11) / 11, mode="same")
    a = np.gradient(vs, t)
    P = A0 + A1 * vs + A2 * vs**2 + np.maximum(A4 * MASS * vs * a, 0.0)
    return t, np.clip(P, PDEM_MIN, PDEM_MAX)


def main():
    global PDEM_BINS
    ap = argparse.ArgumentParser()
    ap.add_argument("bags", nargs="+")
    ap.add_argument("-o", "--out", default="TPM_newbuild.mat")
    ap.add_argument("--dt-dp", type=float, default=DT_DP)
    ap.add_argument("--bins", type=int, default=PDEM_BINS,
                    help="demand bins. 50 gives 0.7 W bins, finer than the\n"
                         "demand moves in one step, so persistence collapses.")
    a = ap.parse_args()
    PDEM_BINS = a.bins

    edges = np.linspace(PDEM_MIN, PDEM_MAX, PDEM_BINS + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    C = np.zeros((PDEM_BINS, PDEM_BINS))
    total_pairs = 0
    occupancy = np.zeros(PDEM_BINS)

    for b in a.bags:
        t, P = demand_series(b)
        if t is None:
            print(f"  skipping {os.path.basename(b)}: too few samples")
            continue
        dt = float(np.median(np.diff(t)))
        step = max(1, int(round(a.dt_dp / dt)))
        idx = np.clip(np.digitize(P, edges) - 1, 0, PDEM_BINS - 1)
        occupancy += np.bincount(idx, minlength=PDEM_BINS)
        pairs = 0
        for i in range(0, len(idx) - step):
            C[idx[i], idx[i + step]] += 1
            pairs += 1
        total_pairs += pairs
        print(f"  {os.path.basename(b.rstrip('/'))}: {len(t)} samples at {dt*1000:.0f} ms, "
              f"step {step} = {step*dt:.0f} s, {pairs} transitions, "
              f"P_dem {P.min():.1f}..{P.max():.1f} W")

    if total_pairs == 0:
        sys.exit("No transitions counted.")

    seen = (C.sum(axis=1) > 0).sum()
    print(f"\n  {total_pairs} transitions over {seen}/{PDEM_BINS} occupied bins")
    if seen < PDEM_BINS * 0.5:
        print("  NOTE: over half the demand grid was never visited. Those rows get a")
        print("  stay-put prior, which is honest but means the SDP has no evidence")
        print("  about them. Run a cycle that reaches the full speed range for a")
        print("  TPM that covers the grid the cost-to-go is built on.")

    rs = C.sum(axis=1, keepdims=True)
    TPM = np.where(rs > 0, C / np.where(rs > 0, rs, 1.0), 0.0)
    for i in range(PDEM_BINS):
        if rs[i, 0] == 0:
            TPM[i, i] = 1.0          # unvisited: stay put

    diag = float(np.mean([TPM[i, i] for i in range(PDEM_BINS) if rs[i, 0] > 0]))
    print(f"  mean diagonal (persistence) over occupied rows: {diag:.3f}")

    scipy.io.savemat(a.out, {
        "TPM": TPM,
        "pdem_min": PDEM_MIN, "pdem_max": PDEM_MAX, "pdem_bins": PDEM_BINS,
        "pdem_centers": centers, "dt_dp": a.dt_dp,
        "occupancy": occupancy, "n_transitions": total_pairs,
        "road_coeffs": np.array([A0, A1, A2, A4]), "mass": MASS,
    })
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
