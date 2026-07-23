#!/usr/bin/env python3
"""hinf_synthesis.py — minimal state-space / H-infinity synthesis library.

Written for the droop power-share controller design (see system_model.md and
synthesize_controller.py). No MATLAB/slycot available on this machine, so the
S/KS/T mixed-sensitivity H-inf problem is solved directly:

  * Riccati equations via the Hamiltonian matrix + ordered real Schur
    decomposition (stable invariant subspace), the textbook method.
  * gamma-iteration (bisection) on the DGKF feasibility conditions.
  * Central controller for the regular problem with D11 = 0 (arranged by
    construction: Wp strictly proper, plant strictly proper), non-orthogonal
    cross terms handled with the shifted-ARE form (Zhou/Doyle/Glover ch. 14/16):
        X-ARE:  Ax' X + X Ax - X Rx X + Qx = 0,
                Ax = A - B2 D12^T C1, Qx = C1^T (I - D12 D12^T) C1,
                Rx = B2 B2^T - g^-2 B1 B1^T
        F = -(B2^T X + D12^T C1)
    For the S/KS/T structure here the dual (estimation) ARE degenerates:
    D21 = 1 makes Qy = B1 (I - D21^T D21) B1^T = 0 and Ay = A - B1 C2 stable,
    so Y = 0, Z = I, L = -B1, and the central controller reduces to
        xhat' = (Ay + B2 F) xhat + B1 e ,   u = F xhat.
    This degenerate structure is verified numerically (Ay stability is
    asserted), and EVERY synthesized controller is gate-checked a posteriori:
    closed-loop stability + ||Tzw||inf <= gamma via an independent Hamiltonian
    bisection. A formula error cannot pass the gate.

Self-tests: run this file directly (python hinf_synthesis.py).
"""

import numpy as np
from numpy.linalg import solve, inv, eigvals, matrix_rank
from scipy.linalg import schur, expm, solve_continuous_lyapunov, block_diag

# ─────────────────────────────────────────────────────────────────────────────
# State-space container + basic algebra (SISO-oriented, arrays throughout)
# ─────────────────────────────────────────────────────────────────────────────

class SS:
    def __init__(self, A, B, C, D):
        self.A = np.atleast_2d(np.asarray(A, float))
        self.B = np.atleast_2d(np.asarray(B, float))
        self.C = np.atleast_2d(np.asarray(C, float))
        self.D = np.atleast_2d(np.asarray(D, float))
        if self.A.size == 0:
            self.A = np.zeros((0, 0))
            self.B = np.zeros((0, self.D.shape[1]))
            self.C = np.zeros((self.D.shape[0], 0))

    @property
    def n(self): return self.A.shape[0]

    def freqresp(self, w):
        """Frequency response G(jw) for an array of frequencies (SISO -> complex array)."""
        out = np.empty(len(w), complex)
        I = np.eye(self.n)
        for i, wi in enumerate(w):
            out[i] = (self.C @ solve(1j*wi*I - self.A, self.B) + self.D)[0, 0]
        return out

    def dcgain(self):
        return (self.D - self.C @ solve(self.A, self.B))[0, 0] if self.n else self.D[0, 0]

    def poles(self):
        return eigvals(self.A)

    def is_stable(self, margin=0.0):
        return self.n == 0 or np.max(eigvals(self.A).real) < -margin


def ss_series(g1, g2):
    """u -> g1 -> g2 -> y  (i.e. G(s) = G2(s) G1(s))."""
    A = np.block([[g1.A, np.zeros((g1.n, g2.n))],
                  [g2.B @ g1.C, g2.A]]) if g1.n or g2.n else np.zeros((0, 0))
    B = np.vstack([g1.B, g2.B @ g1.D])
    C = np.hstack([g2.D @ g1.C, g2.C])
    D = g2.D @ g1.D
    return SS(A, B, C, D)


def ss_scale(g, k):
    return SS(g.A, g.B, k*g.C, k*g.D)


def ss_parallel(g1, g2):
    """G1 + G2."""
    A = block_diag(g1.A, g2.A)
    B = np.vstack([g1.B, g2.B])
    C = np.hstack([g1.C, g2.C])
    return SS(A, B, C, g1.D + g2.D)


def tf2ss(num, den):
    """SISO transfer function -> controllable canonical SS. num/den: descending powers."""
    num = np.atleast_1d(np.asarray(num, float))
    den = np.atleast_1d(np.asarray(den, float))
    num = num / den[0]; den = den / den[0]
    n = len(den) - 1
    num = np.concatenate([np.zeros(n + 1 - len(num)), num])
    d = num[0]
    b = num[1:] - d*den[1:]              # strictly-proper numerator coefficients
    if n == 0:
        return SS(np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0)), [[d]])
    A = np.zeros((n, n)); A[:-1, 1:] = np.eye(n - 1); A[-1, :] = -den[1:][::-1]
    B = np.zeros((n, 1)); B[-1, 0] = 1.0
    C = b[::-1].reshape(1, n)
    return SS(A, B, C, [[d]])


def pade2(Td):
    """2nd-order Pade approximation of exp(-Td s)."""
    if Td <= 0:
        return tf2ss([1.0], [1.0])
    num = [Td**2, -6*Td, 12.0]
    den = [Td**2,  6*Td, 12.0]
    return tf2ss(num, den)


def makeweight(dc, wc, hf):
    """First-order weight |W(0)|=dc, |W(jwc)|=1, |W(inf)|=hf (MATLAB makeweight)."""
    a = wc*np.sqrt((1.0 - hf**2)/(dc**2 - 1.0))
    return tf2ss([hf, dc*a], [1.0, a])


def strictly_proper_lf_weight(dc, wc):
    """W(s) = dc*a/(s+a), a = wc/dc: DC gain dc, |W| = 1 at ~wc, ->0 at HF.
    Strictly proper on purpose: keeps D11 = 0 in the augmented plant."""
    a = wc/np.sqrt(dc**2 - 1.0)
    return tf2ss([dc*a], [1.0, a])


# ─────────────────────────────────────────────────────────────────────────────
# Riccati via Hamiltonian + ordered Schur
# ─────────────────────────────────────────────────────────────────────────────

def care_hamiltonian(A, R, Q, imag_tol=1e-9):
    """Solve A'X + XA - X R X + Q = 0 (stabilizing X) via the stable invariant
    subspace of H = [[A, -R], [-Q, -A']]. Returns (X, ok)."""
    n = A.shape[0]
    H = np.block([[A, -R], [-Q, -A.T]])
    ev = eigvals(H)
    if np.min(np.abs(ev.real)) < imag_tol*max(1.0, np.max(np.abs(ev))):
        return None, False                      # eigenvalues on the imaginary axis
    T, Z, sdim = schur(H, output='real', sort=lambda x, y: x < 0)
    if sdim != n:
        return None, False
    U1, U2 = Z[:n, :n], Z[n:, :n]
    if np.linalg.cond(U1) > 1e12:
        return None, False
    X = U2 @ inv(U1)
    X = 0.5*(X + X.T)                            # symmetrize
    return X, True


def hinf_norm(sys, tol=1e-4, gmax=1e6):
    """||G||inf for stable G via Hamiltonian bisection (Boyd/Balakrishnan).
    Handles D != 0."""
    A, B, C, D = sys.A, sys.B, sys.C, sys.D
    if sys.n == 0:
        return float(np.linalg.norm(D, 2))
    if not sys.is_stable():
        return np.inf
    # initial bracket from a frequency sweep + D
    w = np.logspace(-4, 7, 400)
    lo = max(float(np.linalg.norm(D, 2)),
             float(np.max(np.abs(sys.freqresp(w)))) if B.shape[1] == 1 and C.shape[0] == 1
             else _mimo_sweep_max(sys, w))
    lo = max(lo, 1e-12); hi = max(2*lo, 1e-6)

    def no_imag_eigs(g):
        R = g*g*np.eye(D.shape[1]) - D.T @ D
        try:
            Ri = inv(R)
        except np.linalg.LinAlgError:
            return False
        Ah = A + B @ Ri @ D.T @ C
        H = np.block([[Ah, B @ Ri @ B.T],
                      [-C.T @ (np.eye(D.shape[0]) + D @ Ri @ D.T) @ C, -Ah.T]])
        ev = eigvals(H)
        scale = max(1.0, np.max(np.abs(ev)))
        return np.min(np.abs(ev.real)) > 1e-8*scale

    while not no_imag_eigs(hi):
        hi *= 2
        if hi > gmax:
            return np.inf
    while (hi - lo)/hi > tol:
        mid = 0.5*(lo + hi)
        if no_imag_eigs(mid):
            hi = mid
        else:
            lo = mid
    return hi


def _mimo_sweep_max(sys, w):
    mx = 0.0
    I = np.eye(sys.n)
    for wi in w:
        G = sys.C @ solve(1j*wi*I - sys.A, sys.B) + sys.D
        mx = max(mx, np.linalg.norm(G, 2))
    return mx


# ─────────────────────────────────────────────────────────────────────────────
# Mixed-sensitivity augmented plant + hinfsyn
# ─────────────────────────────────────────────────────────────────────────────

class AugPlant:
    """P for the S/KS/T stack: w = reference, u = control,
    z = [Wp*(w - G u); Wu*u; Wd*G u], e = w - G u.
    Requires: G strictly proper (D=0), Wp strictly proper (D=0) -> D11 = 0, D22 = 0."""
    def __init__(self, G, Wp, Wu, Wd):
        assert abs(G.D[0, 0]) < 1e-14, "plant must be strictly proper"
        assert abs(Wp.D[0, 0]) < 1e-14, "Wp must be strictly proper (keeps D11 = 0)"
        ng, npp, nu, nd = G.n, Wp.n, Wu.n, Wd.n
        n = ng + npp + nu + nd
        sl_g = slice(0, ng); sl_p = slice(ng, ng+npp)
        sl_u = slice(ng+npp, ng+npp+nu); sl_d = slice(ng+npp+nu, n)
        A = np.zeros((n, n))
        A[sl_g, sl_g] = G.A; A[sl_p, sl_p] = Wp.A
        A[sl_u, sl_u] = Wu.A; A[sl_d, sl_d] = Wd.A
        A[sl_p, sl_g] = -Wp.B @ G.C          # Wp driven by (w - y_g)
        A[sl_d, sl_g] = Wd.B @ G.C           # Wd driven by y_g
        B1 = np.zeros((n, 1)); B1[sl_p] = Wp.B
        B2 = np.zeros((n, 1)); B2[sl_g] = G.B; B2[sl_u] = Wu.B
        C1 = np.zeros((3, n))
        C1[0, sl_p] = Wp.C
        C1[1, sl_u] = Wu.C
        C1[2, sl_g] = (Wd.D @ G.C); C1[2, sl_d] = Wd.C
        D11 = np.zeros((3, 1))
        D12 = np.zeros((3, 1)); D12[1, 0] = Wu.D[0, 0]
        C2 = np.zeros((1, n)); C2[0, sl_g] = -G.C
        D21 = np.ones((1, 1)); D22 = np.zeros((1, 1))
        self.A, self.B1, self.B2 = A, B1, B2
        self.C1, self.C2 = C1, C2
        self.D11, self.D12, self.D21, self.D22 = D11, D12, D21, D22

    def closed_loop(self, K):
        """Tzw = LFT(P, K) as an SS (3 outputs z, 1 input w). D22 = 0 assumed."""
        A, B1, B2, C1, C2 = self.A, self.B1, self.B2, self.C1, self.C2
        Ak, Bk, Ck, Dk = K.A, K.B, K.C, K.D
        # u = Ck xk + Dk e, e = C2 x + D21 w
        Acl = np.block([[A + B2 @ Dk @ C2, B2 @ Ck],
                        [Bk @ C2,          Ak]])
        Bcl = np.vstack([B1 + B2 @ Dk @ self.D21, Bk @ self.D21])
        Ccl = np.hstack([C1 + self.D12 @ Dk @ C2, self.D12 @ Ck])
        Dcl = self.D11 + self.D12 @ Dk @ self.D21
        return SS(Acl, Bcl, Ccl, Dcl)


def hinfsyn_mixed(P, gmin=1e-3, gmax=1e4, tol=1e-3, backoff=1.05, verbose=False):
    """gamma-iteration for the AugPlant structure above. Returns (K, gamma_used,
    gamma_opt). Central controller built at gamma_used = backoff*gamma_opt and
    gate-checked: closed loop stable and ||Tzw||inf <= gamma_used (+small slack)."""
    A, B1, B2 = P.A, P.B1, P.B2
    C1, C2 = P.C1, P.C2
    D12, D21 = P.D12, P.D21

    # normalize D12 (scalar column): u' = du*u
    du = float(np.linalg.norm(D12, 2))
    assert du > 0, "D12 must be nonzero (Wu with nonzero HF gain)"
    B2n, D12n = B2/du, D12/du

    # dual degenerate structure checks (see module docstring)
    Ay = A - B1 @ D21 @ C2                     # D21 = 1
    assert np.max(eigvals(Ay).real) < 0, \
        "Ay = A - B1*C2 must be stable for the degenerate estimator (Y=0)"

    Dt = D12n.T @ C1                           # 1 x n cross term
    Ax = A - B2n @ Dt
    Qx = C1.T @ (np.eye(3) - D12n @ D12n.T) @ C1

    def try_gamma(g):
        Rx = B2n @ B2n.T - (1.0/g**2) * (B1 @ B1.T)
        X, ok = care_hamiltonian(Ax, Rx, Qx)
        if not ok or X is None:
            return None
        if np.min(np.linalg.eigvalsh(X)) < -1e-6*max(1.0, np.max(np.abs(X))):
            return None
        return X

    # establish feasible upper bound
    g_hi = 1.0
    while try_gamma(g_hi) is None:
        g_hi *= 2
        if g_hi > gmax:
            raise RuntimeError("no feasible gamma <= gmax — check weights")
    g_lo = gmin
    while (g_hi - g_lo)/g_hi > tol:
        g_mid = np.sqrt(g_lo*g_hi)
        if try_gamma(g_mid) is not None:
            g_hi = g_mid
        else:
            g_lo = g_mid
        if verbose:
            print(f"    gamma in [{g_lo:.5f}, {g_hi:.5f}]")
    g_opt = g_hi

    def build_K(g):
        X = try_gamma(g)
        if X is None:
            return None
        F = -(B2n.T @ X + Dt)                  # 1 x n
        Ak = Ay + B2n @ F \
             + (1.0/g**2) * (B1 @ B1.T @ X - B1 @ (B1.T @ X))  # = Ay + B2n F (kept explicit)
        # NOTE: for this structure Z = I, L = -B1, and the g^-2 B1 B1' X terms of the
        # general formula cancel exactly (see module docstring derivation).
        Kss = SS(Ak, B1, F/du, [[0.0]])        # u = u'/du
        return Kss

    # back off from optimum, then gate-check; widen back-off if needed
    for bo in (backoff, 1.2, 1.5, 2.0):
        g_use = bo*g_opt
        K = build_K(g_use)
        if K is None:
            continue
        Tzw = P.closed_loop(K)
        if not Tzw.is_stable():
            continue
        nrm = hinf_norm(Tzw)
        if nrm <= g_use*(1 + 5e-3):
            return K, g_use, g_opt, nrm
    raise RuntimeError("central controller failed the a-posteriori gate — formula/conditioning issue")


# ─────────────────────────────────────────────────────────────────────────────
# Model reduction, decomposition, discretization
# ─────────────────────────────────────────────────────────────────────────────

def balanced_truncate(sys, order=None, tol=1e-6):
    """Balanced truncation of a STABLE system. Returns (sys_red, hsv)."""
    if sys.n == 0:
        return sys, np.array([])
    assert sys.is_stable(), "balanced truncation needs a stable system"
    Wc = solve_continuous_lyapunov(sys.A, -sys.B @ sys.B.T)
    Wo = solve_continuous_lyapunov(sys.A.T, -sys.C.T @ sys.C)
    # square roots via eigh (gramians are PSD)
    def psd_sqrt(M):
        w, V = np.linalg.eigh(0.5*(M + M.T))
        w = np.clip(w, 0, None)
        return V @ np.diag(np.sqrt(w)) @ V.T
    Lc, Lo = psd_sqrt(Wc), psd_sqrt(Wo)
    U, s, Vt = np.linalg.svd(Lo @ Lc)
    hsv = s
    if order is None:
        order = int(np.sum(s > tol*s[0]))
    order = max(1, min(order, sys.n))
    s_r = s[:order]
    T = Lc @ Vt.T[:, :order] @ np.diag(s_r**-0.5)
    Ti = np.diag(s_r**-0.5) @ U[:, :order].T @ Lo
    return SS(Ti @ sys.A @ T, Ti @ sys.B, sys.C @ T, sys.D), hsv


def split_integrator(sys, tol=1e-4):
    """Split G = kI/s + G_stable, where the near-origin pole is snapped to an
    exact integrator. Returns (kI, G_stable). Uses ordered Schur to separate the
    eigenvalue closest to the origin."""
    ev = eigvals(sys.A)
    i0 = np.argmin(np.abs(ev))
    lam0 = ev[i0]
    assert np.abs(lam0) < tol, f"no near-origin pole found (closest: {lam0})"
    # sort the near-origin eigenvalue to the top-left
    T, Z, sdim = schur(sys.A, output='real', sort=lambda x, y: np.hypot(x, y) < tol)
    assert sdim == 1, f"expected exactly 1 near-origin pole, got {sdim}"
    # block-diagonalize: solve Sylvester for the coupling  [l0 M; 0 A22]
    l0 = T[0, 0]
    A22 = T[1:, 1:]
    M = T[0:1, 1:]
    from scipy.linalg import solve_sylvester
    Sy = solve_sylvester(np.array([[l0]]) , -A22, -M)       # l0*S - S*A22 + M = 0
    W = np.eye(sys.n); W[0:1, 1:] = Sy
    Wi = np.eye(sys.n); Wi[0:1, 1:] = -Sy
    Ab = Wi @ T @ W                                          # block diagonal
    Bt = Wi @ Z.T @ sys.B
    Ct = sys.C @ Z @ W
    kI = float(Ct[0, 0]*Bt[0, 0])                            # residue -> exact 1/s gain
    Gs = SS(Ab[1:, 1:], Bt[1:], Ct[:, 1:], sys.D)
    return kI, Gs


def c2d_tustin(sys, Ts):
    """Bilinear (Tustin) discretization."""
    I = np.eye(sys.n)
    M = inv(I - sys.A*Ts/2)
    Ad = M @ (I + sys.A*Ts/2)
    Bd = M @ sys.B * Ts
    Cd = sys.C @ M
    Dd = sys.D + sys.C @ M @ sys.B * Ts/2
    return SS(Ad, Bd, Cd, Dd)      # note: discrete SS reusing the container


def c2d_zoh(sys, Ts):
    n, m = sys.n, sys.B.shape[1]
    M = np.zeros((n+m, n+m)); M[:n, :n] = sys.A; M[:n, n:] = sys.B
    E = expm(M*Ts)
    return SS(E[:n, :n], E[:n, n:], sys.C, sys.D)


def dss_tf_coeffs(sysd):
    """Discrete SISO SS -> (num, den) in descending powers of z (den monic)."""
    den = np.poly(sysd.A) if sysd.n else np.array([1.0])
    if sysd.n:
        num = np.poly(sysd.A - sysd.B @ sysd.C/1.0) if False else None
        # numerator via Leverrier-free route: num(z) = den(z)*(C (zI-A)^-1 B + D)
        # evaluate at n+1 points and interpolate exactly
        n = sysd.n
        zs = np.exp(1j*np.linspace(0.1, 2.9, n+1))
        vals = []
        for z in zs:
            vals.append((sysd.C @ solve(z*np.eye(n) - sysd.A, sysd.B) + sysd.D)[0, 0]
                        * np.polyval(den, z))
        num = np.polyfit(zs, np.array(vals), n)
        num = np.real_if_close(num, tol=1e6).real
    else:
        num = np.array([sysd.D[0, 0]])
    return num, den


def dfreqresp(sysd, Ts, w):
    """Discrete frequency response at continuous frequencies w (rad/s)."""
    out = np.empty(len(w), complex)
    I = np.eye(sysd.n)
    for i, wi in enumerate(w):
        z = np.exp(1j*wi*Ts)
        out[i] = (sysd.C @ solve(z*I - sysd.A, sysd.B) + sysd.D)[0, 0]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Self-tests
# ─────────────────────────────────────────────────────────────────────────────

def _selftest():
    ok = True
    def chk(name, cond, detail=""):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" ({detail})" if detail else ""))
        ok = ok and cond

    # tf2ss vs direct polynomial evaluation
    num, den = [2.0, 3.0], [1.0, 4.0, 5.0]
    g = tf2ss(num, den)
    w = np.logspace(-2, 3, 50)
    ref = np.polyval(num, 1j*w)/np.polyval(den, 1j*w)
    chk("tf2ss freq response", np.allclose(g.freqresp(w), ref, rtol=1e-9))

    # series
    g2 = tf2ss([1.0], [0.5, 1.0])
    ser = ss_series(g, g2)
    ref2 = ref * (1.0/np.polyval([0.5, 1.0], 1j*w))
    chk("ss_series", np.allclose(ser.freqresp(w), ref2, rtol=1e-9))

    # pade2 approximates delay at low frequency
    Td = 1e-3
    p = pade2(Td)
    wl = np.logspace(0, 2.7, 30)   # up to 500 rad/s << 2/Td
    chk("pade2 phase", np.allclose(np.angle(p.freqresp(wl)), -wl*Td, atol=2e-3))

    # makeweight endpoints
    Wu = makeweight(0.5, 300.0, 100.0)
    chk("makeweight DC/HF/crossover",
        abs(Wu.dcgain() - 0.5) < 1e-9 and abs(Wu.D[0, 0] - 100.0) < 1e-9
        and abs(abs(Wu.freqresp(np.array([300.0]))[0]) - 1.0) < 1e-6)

    # CARE: compare with scipy for a definite case (LQR-type)
    from scipy.linalg import solve_continuous_are
    A = np.array([[0., 1.], [-2., -3.]]); B = np.array([[0.], [1.]])
    Q = np.eye(2); R = np.eye(1)
    Xref = solve_continuous_are(A, B, Q, R)
    X, okc = care_hamiltonian(A, B @ inv(R) @ B.T, Q)
    chk("care_hamiltonian vs scipy ARE", okc and np.allclose(X, Xref, rtol=1e-8))

    # hinf norm vs dense sweep on a resonant system
    gr = tf2ss([1.0], [1.0, 0.2, 1.0])          # peak ~ 1/(0.2) at w=1
    nrm = hinf_norm(gr)
    sweep = np.max(np.abs(gr.freqresp(np.linspace(0.8, 1.2, 20001))))
    chk("hinf_norm vs sweep", abs(nrm - sweep)/sweep < 1e-3, f"{nrm:.5f} vs {sweep:.5f}")

    # c2d_tustin vs scipy
    from scipy.signal import cont2discrete
    Ad, Bd, Cd, Dd, _ = cont2discrete((g.A, g.B, g.C, g.D), 0.01, method='bilinear')
    gd = c2d_tustin(g, 0.01)
    chk("c2d_tustin vs scipy", np.allclose(gd.A, Ad) and np.allclose(gd.B, Bd)
        and np.allclose(gd.C, Cd) and np.allclose(gd.D, Dd))

    # balanced truncation keeps response
    big = ss_parallel(tf2ss([1.0], [1.0, 1.0]), tf2ss([1e-6], [1.0, 100.0]))
    red, hsv = balanced_truncate(big, order=1)
    chk("balanced_truncate", np.allclose(red.freqresp(w), big.freqresp(w), atol=1e-5))

    # split_integrator: G = 3/s + 1/(s+2)
    gi = ss_parallel(SS([[0.0]], [[1.0]], [[3.0]], [[0.0]]), tf2ss([1.0], [1.0, 2.0]))
    kI, gs = split_integrator(gi, tol=1e-8)
    chk("split_integrator", abs(kI - 3.0) < 1e-9 and
        np.allclose(gs.freqresp(w), 1.0/(1j*w + 2.0), rtol=1e-8))

    # dss_tf_coeffs round-trip
    numz, denz = dss_tf_coeffs(gd)
    zz = np.exp(1j*np.linspace(0.05, 3.0, 40))
    tf_val = np.polyval(numz, zz)/np.polyval(denz, zz)
    ss_val = np.array([(gd.C @ solve(z*np.eye(gd.n) - gd.A, gd.B) + gd.D)[0, 0] for z in zz])
    chk("dss_tf_coeffs round-trip", np.allclose(tf_val, ss_val, rtol=1e-7))

    print("SELF-TEST:", "ALL PASS" if ok else "FAILURES")
    return ok


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(0 if _selftest() else 1)
