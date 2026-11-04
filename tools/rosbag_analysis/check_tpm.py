#!/usr/bin/env python3
"""
check_tpm.py — does the demand TPM carry real memory, or just the marginal?

    python3 check_tpm.py /tmp/tpm_b10.mat /tmp/tpm_b20.mat ...

The diagonal of a transition matrix is often quoted as "persistence", but on its
own it means little: a process with no memory at all still lands in bin i with
probability p_i, so a concentrated demand distribution produces a high diagonal
for free.

The right baseline is an i.i.d. process with the SAME marginal. For row i that
predicts a diagonal of exactly p_i. So:

    excess = mean_i[ T(i,i) ] - mean_i[ p_i ]        over occupied rows

Excess near zero means the TPM is encoding the demand DISTRIBUTION and nothing
about its dynamics. The SDP still works -- it optimises against that
distribution -- but it is not using a Markov model of demand, and saying so is
more honest than quoting a diagonal.

Also reports the total-variation distance between each row and the marginal,
averaged over occupied rows, which measures the same thing without relying on
the diagonal alone.
"""

import sys

import numpy as np
from scipy.io import loadmat


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(f"{'file':<22} {'bins':>5} {'occ':>5} {'diag':>7} {'iid':>7} "
          f"{'excess':>8} {'TV dist':>8}")
    for path in sys.argv[1:]:
        d = loadmat(path)
        T = np.asarray(d["TPM"], dtype=float)
        occ = np.asarray(d["occupancy"]).ravel().astype(float)
        n = T.shape[0]
        seen = occ > 0
        if seen.sum() == 0:
            print(f"{path:<22} no occupied bins")
            continue
        p = occ / occ.sum()                       # marginal
        diag = float(np.mean([T[i, i] for i in range(n) if seen[i]]))
        iid = float(np.mean([p[i] for i in range(n) if seen[i]]))
        tv = float(np.mean([0.5 * np.abs(T[i] - p).sum()
                            for i in range(n) if seen[i]]))
        name = path.split("/")[-1]
        print(f"{name:<22} {n:5d} {int(seen.sum()):5d} {diag:7.3f} {iid:7.3f} "
              f"{diag-iid:+8.3f} {tv:8.3f}")

    print("\n  excess  = how much more persistent than an i.i.d. process with the")
    print("            same marginal. Near 0 -> no usable memory.")
    print("  TV dist = average total-variation distance between a row and the")
    print("            marginal. 0 means every row IS the marginal, i.e. the")
    print("            next demand does not depend on the current one at all.")
    print("            Above ~0.3 is worth keeping as a Markov model.")


if __name__ == "__main__":
    main()
