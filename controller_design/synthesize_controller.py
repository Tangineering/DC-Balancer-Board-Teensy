#!/usr/bin/env python3
"""synthesize_controller.py — H-inf + Youla-H design for the droop power-share loop.

Pipeline (each stage gate-checked; see controller_synthesis.md for the writeup):
  1. Design plant Gp(s) from system_model.md §6d (nominal parameters).
  2. Mixed-sensitivity H-inf synthesis (S/KS/T) via hinf_synthesis.hinfsyn_mixed.
  3. Youla-H post-synthesis gain adjustment: scale Y so T(0) = 1 exactly
     (Tan/Yadav/Assadian 2026, Eq. 5 numeric form), rebuild Gc = Y/(1 - Gp Y).
  4. Split the exact integrator out of Gc_YH, balanced-truncate the stable
     remainder -> implementable order.
  5. Tustin discretization at Ts = 1 ms; factor remainder into SOS biquads.
  6. Validation: continuous + discrete closed loops over the §6d parameter
     corners (stability, ||S||inf), time-domain step/ramp sims, legacy-PI
     comparison.
  7. Emit: ../teensy_controller/share_controller_coeffs.h, reference I/O vectors
     for the C++ unit test, CSV data for figures, and a metrics summary.

Run:  <venv-python> synthesize_controller.py
"""

import os
import numpy as np
from numpy.linalg import eigvals, solve

from hinf_synthesis import (SS, tf2ss, pade2, makeweight, strictly_proper_lf_weight,
                            ss_series, ss_parallel, ss_scale, AugPlant, hinfsyn_mixed,
                            hinf_norm, balanced_truncate, split_integrator,
                            c2d_tustin, c2d_zoh, dss_tf_coeffs, dfreqresp)

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figures")
FW_HEADER = os.path.join(HERE, "..", "teensy_controller", "share_controller_coeffs.h")

np.set_printoptions(precision=6, suppress=False, linewidth=120)
failures = []


def gate(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Design plant (system_model.md §6d)
# ─────────────────────────────────────────────────────────────────────────────
TS      = 1.0e-3          # s, share-loop sample period (proposed §6c)
K_NOM   = 1.0
TD_NOM  = 1.0e-3          # s   TODO(calibrate): bench step test, §9
TAUR_NOM = 100e-6         # s   TODO(calibrate)
TAUF    = 0.8e-3          # s   200 Hz measurement prefilter (implemented in firmware)

# corner grid: §6d ranges, gain widened per the validate_model.py envelope
K_SET    = (0.55, 0.75, 1.0, 1.25, 1.45)
TD_SET   = (0.5e-3, 1.0e-3, 2.0e-3)
TAUR_SET = (20e-6, 300e-6)
TAUF_SET = (0.0, 0.8e-3)


def plant(K=K_NOM, Td=TD_NOM, taur=TAUR_NOM, tauf=TAUF):
    g = pade2(Td)
    g = ss_series(g, tf2ss([1.0], [taur, 1.0]))
    if tauf > 0:
        g = ss_series(g, tf2ss([1.0], [tauf, 1.0]))
    return ss_scale(g, K)


Gp = plant()
print(f"Design plant: n = {Gp.n} states, dc = {Gp.dcgain():.6f}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Weights + H-inf synthesis
# ─────────────────────────────────────────────────────────────────────────────
# Targets (system_model.md §7): wc ~ 40 rad/s, ||S||inf < 2, Y rolled off HF.
WC = 40.0
Wp = strictly_proper_lf_weight(1e4, WC)     # on S: integrator-like, unity at ~40
Wd = makeweight(0.5, 250.0, 40.0)           # on T: allow 2 at DC, force rolloff > 250
Wu = makeweight(0.3, 600.0, 20.0)           # on Y: allow ~3 in-band, roll off > 600

P = AugPlant(Gp, Wp, Wu, Wd)
K_H, g_used, g_opt, tzw_norm = hinfsyn_mixed(P, verbose=False)
print(f"\nH-inf synthesis: gamma_opt = {g_opt:.4f}, controller built at "
      f"gamma = {g_used:.4f}, ||Tzw||inf = {tzw_norm:.4f}, order = {K_H.n}")
gate("Tzw norm consistent with gamma (a-posteriori gate)", tzw_norm <= g_used*1.005,
     f"{tzw_norm:.4f} <= {g_used:.4f}")

# closed-loop transfer functions (continuous, nominal)
def loop_tfs(Gc, G):
    L = ss_series(Gc, G)                    # r -> y open loop (D_L = 0: G strictly proper)
    assert abs(L.D[0, 0]) < 1e-12
    S = SS(L.A - L.B @ L.C, L.B, -L.C, [[1.0]])
    T = SS(L.A - L.B @ L.C, L.B,  L.C, [[0.0]])
    Y = ss_series(S, Gc)                    # Y = Gc*S
    return L, S, T, Y

L_H, S_H, T_H, Y_H = loop_tfs(K_H, Gp)
T0_H = T_H.dcgain()
print(f"T_H(0) = {T0_H:.8f}  (deficiency {abs(1-T0_H):.2e} — the Youla-H target)")
w = np.logspace(-2, 5, 900)
Smag = np.abs(S_H.freqresp(w)); Tmag = np.abs(T_H.freqresp(w))
wc_ach = w[np.argmin(np.abs(Smag - Tmag))]  # S/T crossover
print(f"achieved S/T crossover ~ {wc_ach:.1f} rad/s;  ||S||inf = {hinf_norm(S_H):.3f}, "
      f"||T||inf = {hinf_norm(T_H):.3f}, ||Y||inf = {hinf_norm(Y_H):.3f}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Youla-H gain adjustment (paper Eq. 5, numeric): Y_YH = Y_H / T_H(0)
# ─────────────────────────────────────────────────────────────────────────────
Y_YH = ss_scale(Y_H, 1.0/T0_H)
# Gc_YH = Y_YH (1 - Gp Y_YH)^-1  — positive feedback of Gp around Y (D_Y = 0)
assert abs(Y_YH.D[0, 0]) < 1e-12
A_gc = np.block([[Y_YH.A, Y_YH.B @ Gp.C],
                 [Gp.B @ Y_YH.C, Gp.A]])
Gc_YH_full = SS(A_gc,
                np.vstack([Y_YH.B, np.zeros((Gp.n, 1))]),
                np.hstack([Y_YH.C, np.zeros((1, Gp.n))]),
                [[0.0]])
print(f"\nYoula-H: gain scale 1/T0 = {1.0/T0_H:.8f}; raw Gc_YH order = {Gc_YH_full.n}")

pole_min = np.min(np.abs(eigvals(Gc_YH_full.A)))
gate("Gc_YH contains the enforced integrator (pole ~ 0)", pole_min < 1e-3,
     f"|p|min = {pole_min:.2e}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Integrator split + balanced truncation of the stable remainder
# ─────────────────────────────────────────────────────────────────────────────
kI, Gs_full = split_integrator(Gc_YH_full, tol=1e-3)
gate("integrator residue positive (integral action pushes r toward the error)",
     kI > 0, f"kI = {kI:.4f}")
gate("stable remainder is stable", Gs_full.is_stable(),
     f"max Re(p) = {np.max(eigvals(Gs_full.A).real):.3e}")

Gs_red, hsv = balanced_truncate(Gs_full, order=None, tol=1e-5)
# cap the firmware order at 4 (2 biquads) unless accuracy demands more
if Gs_red.n > 4:
    Gs_red4, _ = balanced_truncate(Gs_full, order=4)
    err4 = np.max(np.abs(Gs_red4.freqresp(w) - Gs_full.freqresp(w)))
    scale = np.max(np.abs(Gs_full.freqresp(w)))
    if err4 < 5e-3*scale:
        Gs_red = Gs_red4
print(f"reduction: {Gs_full.n} -> {Gs_red.n} states; HSV = "
      f"{np.array2string(hsv[:8], precision=3)}")

def Gc_red_freq(w_):
    return Gs_red.freqresp(w_) + kI/(1j*w_)

relerr = np.max(np.abs((Gc_red_freq(w) -
                        (Gs_full.freqresp(w) + kI/(1j*w))))
                / np.maximum(np.abs(Gs_full.freqresp(w) + kI/(1j*w)), 1e-9))
gate("reduced controller matches full (freq resp)", relerr < 2e-2,
     f"max rel err = {relerr:.2e}")

# continuous reduced controller as SS: kI/s + Gs_red
Gc_red = ss_parallel(SS([[0.0]], [[1.0]], [[kI]], [[0.0]]), Gs_red)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Discretization at Ts = 1 ms
# ─────────────────────────────────────────────────────────────────────────────
Gsd = c2d_tustin(Gs_red, TS)                # stable remainder -> biquads
# integrator: Tustin of kI/s: u_i[k] = u_i[k-1] + kI*Ts/2*(e[k]+e[k-1])
numz, denz = dss_tf_coeffs(Gsd)

# factor into SOS biquads (pair complex roots)
def to_sos(num, den):
    z = np.roots(num) if len(num) > 1 else np.array([])
    p = np.roots(den) if len(den) > 1 else np.array([])
    k = num[0]/den[0]
    def pair(roots):
        roots = sorted(roots, key=lambda r: (abs(r.imag) < 1e-10, -abs(r)))
        secs, used = [], [False]*len(roots)
        for i, r in enumerate(roots):
            if used[i]:
                continue
            used[i] = True
            if abs(r.imag) > 1e-10:
                for j in range(i+1, len(roots)):
                    if not used[j] and abs(roots[j] - np.conj(r)) < 1e-8*max(1, abs(r)):
                        used[j] = True
                        break
                secs.append(np.real(np.poly([r, np.conj(r)])))
            else:
                secs.append(np.array([1.0, -r.real]))
        return secs
    zs, ps = pair(list(z)), pair(list(p))
    while len(zs) < len(ps):
        zs.append(np.array([1.0]))
    sos = []
    for zi, pi in zip(zs, ps):
        b = np.concatenate([zi, np.zeros(3 - len(zi))]) if len(zi) < 3 else zi
        a = np.concatenate([pi, np.zeros(3 - len(pi))]) if len(pi) < 3 else pi
        sos.append((b, a))
    sos[0] = (sos[0][0]*k, sos[0][1])
    return sos

sos = to_sos(numz, denz)
print(f"\ndiscrete remainder: order {len(denz)-1}, {len(sos)} SOS section(s)")

# verify SOS product == state-space response
zz = np.exp(1j*np.linspace(0.01, 3.0, 200))
sos_val = np.ones_like(zz)
for b, a in sos:
    sos_val *= np.polyval(b, zz)/np.polyval(a, zz)
ss_val = np.array([(Gsd.C @ solve(z*np.eye(Gsd.n) - Gsd.A, Gsd.B) + Gsd.D)[0, 0]
                   for z in zz])
gate("SOS factorization matches discrete SS", np.allclose(sos_val, ss_val, rtol=1e-6))


class DiscreteController:
    """Reference implementation mirroring the C++ code exactly (DF2T biquads +
    trapezoidal integrator with output-clamp anti-windup)."""
    def __init__(self, sos, kI, Ts, rmin=0.15, rmax=0.85, r0=0.5):
        self.sos = [(list(b), list(a)) for b, a in sos]
        self.st = [[0.0, 0.0] for _ in sos]
        self.kI, self.Ts = kI, Ts
        self.rmin, self.rmax, self.r0 = rmin, rmax, r0
        self.integ, self.eprev = 0.0, 0.0

    def step(self, e, sat=True):
        x = e
        for (b, a), s in zip(self.sos, self.st):
            y = b[0]*x + s[0]
            s[0] = b[1]*x - a[1]*y + s[1]
            s[1] = b[2]*x - a[2]*y
            x = y
        integ_new = self.integ + self.kI*self.Ts*0.5*(e + self.eprev)
        u = self.r0 + x + integ_new
        if sat:
            lo, hi = self.rmin, self.rmax
            if u > hi:
                integ_new -= (u - hi); u = hi     # back-calculation AW
            elif u < lo:
                integ_new += (lo - u); u = lo
        self.integ, self.eprev = integ_new, e
        return u


# ─────────────────────────────────────────────────────────────────────────────
# 6. Validation
# ─────────────────────────────────────────────────────────────────────────────
print("\n─ Continuous-domain corner sweep (reduced controller) ─")
worstM2, worst_corner = np.inf, None
for K in K_SET:
    for Td in TD_SET:
        for taur in TAUR_SET:
            for tauf in TAUF_SET:
                Gpc = plant(K, Td, taur, tauf)
                Lc, Sc, Tc, Yc = loop_tfs(Gc_red, Gpc)
                # stability: S poles (marginal integrator sits in L, closed loop must be strict)
                stab = np.max(eigvals(Sc.A).real) < 0
                M2 = 1.0/hinf_norm(Sc) if stab else 0.0
                if M2 < worstM2:
                    worstM2, worst_corner = M2, (K, Td, taur, tauf)
                if not stab:
                    gate(f"corner stable K={K} Td={Td*1e3}ms taur={taur*1e6}us tauf={tauf*1e3}ms",
                         False)
gate("all 60 corners closed-loop stable", not any('corner stable' in f for f in failures))
gate("worst-corner M2 acceptable (> 0.30)", worstM2 > 0.30,
     f"M2 = {worstM2:.3f} at K,Td,taur,tauf = {worst_corner}")

nomL, nomS, nomT, nomY = loop_tfs(Gc_red, Gp)
M2_nom = 1.0/hinf_norm(nomS)
T0_red = nomT.dcgain()
gate("T(0) = 1 with reduced controller (exact integrator)", abs(T0_red - 1) < 1e-9,
     f"T(0) = {T0_red:.12f}")
print(f"nominal M2 = {M2_nom:.3f}  (H-inf full-order M2 = {1.0/hinf_norm(S_H):.3f})")

# gain/phase/delay margins from the nominal loop
Lresp = nomL.freqresp(w)
idx_c = np.argmin(np.abs(np.abs(Lresp) - 1.0))
pm = 180 + np.degrees(np.angle(Lresp[idx_c]))
dm = np.radians(pm)/w[idx_c]
gate("phase margin > 45 deg", pm > 45, f"PM = {pm:.1f} deg at {w[idx_c]:.1f} rad/s")
gate("delay margin > 2*Ts", dm > 2*TS, f"DM = {dm*1e3:.2f} ms")

print("\n─ Discrete-domain validation (the controller as implemented) ─")
def discrete_cl_poles(Gpc, ctrl_ss_d):
    Gpd = c2d_zoh(Gpc, TS)
    # negative feedback: e = r - y
    A = np.block([[Gpd.A, Gpd.B @ ctrl_ss_d.C],
                  [-ctrl_ss_d.B @ Gpd.C, ctrl_ss_d.A]])
    D_k = ctrl_ss_d.D[0, 0]
    if abs(D_k) > 0:   # include controller feedthrough u = Ck xk + Dk(r - y)
        A = np.block([[Gpd.A - Gpd.B*D_k @ Gpd.C, Gpd.B @ ctrl_ss_d.C],
                      [-ctrl_ss_d.B @ Gpd.C, ctrl_ss_d.A]])
    return eigvals(A)

int_d = SS([[1.0]], [[1.0]], [[kI*TS]], [[kI*TS/2.0]])   # Tustin kI/s
ctrl_d = ss_parallel(int_d, Gsd)
worst_rad = 0.0
for K in K_SET:
    for Td in TD_SET:
        for taur in TAUR_SET:
            for tauf in TAUF_SET:
                pl = discrete_cl_poles(plant(K, Td, taur, tauf), ctrl_d)
                worst_rad = max(worst_rad, np.max(np.abs(pl)))
gate("discrete closed loop stable on ALL corners (|z| < 1)", worst_rad < 1.0,
     f"max |z| = {worst_rad:.4f}")

# time-domain: step + ramp on the nominal discrete loop, via simulation of the
# reference controller class against the ZOH plant
def simulate(ctrl, Gpc, ref_fn, n_steps, alpha0=0.5):
    Gpd = c2d_zoh(Gpc, TS)
    xg = np.zeros((Gpd.n, 1))
    out, us = [], []
    # operating-point convention: plant maps (r - r0) -> (alpha - alpha0)
    for k in range(n_steps):
        alpha = (Gpd.C @ xg).item() + alpha0
        r_ref = ref_fn(k*TS)
        e = r_ref - alpha
        u = ctrl.step(e)
        xg = Gpd.A @ xg + Gpd.B*(u - ctrl.r0)
        out.append(alpha); us.append(u)
    return np.array(out), np.array(us)

ctrl = DiscreteController(sos, kI, TS)
step_ref = lambda t: 0.7 if t >= 0.01 else 0.5
y_step, u_step = simulate(DiscreteController(sos, kI, TS), Gp, step_ref, 400)
sett = np.where(np.abs(y_step[10:] - 0.7) > 0.02*0.2)[0]
t_settle = (sett[-1]+1)*TS if len(sett) else 0.0
ovs = (np.max(y_step) - 0.7)/0.2*100
gate("step: settles < 250 ms", t_settle < 0.25, f"2% settle = {t_settle*1e3:.0f} ms")
gate("step: overshoot < 20%", ovs < 20.0, f"overshoot = {ovs:.1f}%")
gate("step: zero steady-state error", abs(y_step[-1] - 0.7) < 1e-4,
     f"final err = {y_step[-1]-0.7:.2e}")

ramp_ref = lambda t: 0.5 + min(0.3, 0.05*max(0.0, t - 0.01))   # 0.05/s EMS blend
y_ramp, _ = simulate(DiscreteController(sos, kI, TS), Gp, ramp_ref, 8000)
ramp_err_tail = np.abs(y_ramp[6000] - ramp_ref(6000*TS))
gate("ramp: tracking error -> 0 (Youla-H selling point)", ramp_err_tail < 1e-3,
     f"err @ t=6 s = {ramp_err_tail:.2e}")

# anti-windup: big reference step into saturation and back
def satref(t):
    return 0.98 if 0.01 <= t < 0.5 else 0.5    # forces r to the 0.85 rail
y_aw, u_aw = simulate(DiscreteController(sos, kI, TS), Gp, satref, 1500)
recov = np.where(np.abs(y_aw[520:] - 0.5) < 0.02)[0]
gate("anti-windup: recovers from a saturated episode quickly",
     len(recov) and recov[0]*TS < 0.15, f"recovery = {recov[0]*TS*1e3:.0f} ms")
gate("anti-windup: output clamped to [0.15, 0.85]",
     np.max(u_aw) <= 0.85 + 1e-9 and np.min(u_aw) >= 0.15 - 1e-9)

# legacy PI comparison (Kp = Ki = 1, as in the current firmware)
pi_sos = [( [0.0, 0.0, 0.0], [1.0, 0.0, 0.0] )]   # zero remainder
class PIController(DiscreteController):
    def step(self, e, sat=True):
        integ_new = self.integ + 1.0*self.Ts*0.5*(e + self.eprev)
        u = self.r0 + 1.0*e + integ_new
        if sat:
            if u > self.rmax: integ_new -= (u - self.rmax); u = self.rmax
            elif u < self.rmin: integ_new += (self.rmin - u); u = self.rmin
        self.integ, self.eprev = integ_new, e
        return u
y_pi, _ = simulate(PIController(sos, 1.0, TS), Gp, step_ref, 400)

# worst corner comparison: discrete sensitivity peaks
def disc_S_peak(Gpc, controller_ss):
    Gpd = c2d_zoh(Gpc, TS)
    wgrid = np.logspace(0, np.log10(np.pi/TS*0.999), 700)
    Lz = dfreqresp(Gpd, TS, wgrid)*dfreqresp(controller_ss, TS, wgrid)
    return float(np.max(np.abs(1.0/(1.0 + Lz))))

pi_d = SS([[1.0]], [[1.0]], [[1.0*TS]], [[1.0 + 1.0*TS/2.0]])   # PI: 1 + 1/s Tustin
worstS_new, worstS_pi = 0.0, 0.0
for K in K_SET:
    for Td in TD_SET:
        worstS_new = max(worstS_new, disc_S_peak(plant(K, Td, 300e-6, 0.8e-3), ctrl_d))
        worstS_pi = max(worstS_pi, disc_S_peak(plant(K, Td, 300e-6, 0.8e-3), pi_d))
print(f"worst-corner discrete ||S||inf: Youla-H = {worstS_new:.3f}, legacy PI = {worstS_pi:.3f}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Emit artifacts
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs(FIGDIR, exist_ok=True)

# 7a. Bode / loop-shape CSVs
with open(os.path.join(FIGDIR, "loopshapes_youla_h.csv"), "w") as f:
    f.write("w_rad_s,S_mag,T_mag,Y_mag,invWp,invWd,invWu,L_mag,L_phase_deg\n")
    Sm = np.abs(nomS.freqresp(w)); Tm = np.abs(nomT.freqresp(w))
    Ym = np.abs(nomY.freqresp(w)); Lr = nomL.freqresp(w)
    iWp = 1/np.abs(Wp.freqresp(w)); iWd = 1/np.abs(Wd.freqresp(w)); iWu = 1/np.abs(Wu.freqresp(w))
    for i in range(len(w)):
        f.write(f"{w[i]:.6e},{Sm[i]:.6e},{Tm[i]:.6e},{Ym[i]:.6e},"
                f"{iWp[i]:.6e},{iWd[i]:.6e},{iWu[i]:.6e},"
                f"{np.abs(Lr[i]):.6e},{np.degrees(np.angle(Lr[i])):.3f}\n")

with open(os.path.join(FIGDIR, "controller_bode.csv"), "w") as f:
    f.write("w_rad_s,Gc_hinf_mag,Gc_youlah_mag,Gc_reduced_mag,Gc_discrete_mag\n")
    gh = np.abs(K_H.freqresp(w)); gy = np.abs(Gc_YH_full.freqresp(w))
    gr = np.abs(Gc_red_freq(w))
    wd_ = w[w < np.pi/TS*0.999]
    gd = np.abs(dfreqresp(ctrl_d, TS, wd_))
    for i in range(len(w)):
        gdv = gd[i] if i < len(wd_) else float('nan')
        f.write(f"{w[i]:.6e},{gh[i]:.6e},{gy[i]:.6e},{gr[i]:.6e},{gdv:.6e}\n")

with open(os.path.join(FIGDIR, "timedomain_step_ramp.csv"), "w") as f:
    f.write("t_s,step_ref,step_alpha_youlah,step_alpha_pi,step_r_cmd,ramp_ref,ramp_alpha\n")
    for k in range(max(len(y_step), len(y_ramp))):
        t = k*TS
        s_ref = step_ref(t) if k < len(y_step) else float('nan')
        sy = y_step[k] if k < len(y_step) else float('nan')
        sp = y_pi[k] if k < len(y_pi) else float('nan')
        su = u_step[k] if k < len(u_step) else float('nan')
        rr = ramp_ref(t) if k < len(y_ramp) else float('nan')
        ry = y_ramp[k] if k < len(y_ramp) else float('nan')
        f.write(f"{t:.4f},{s_ref},{sy:.6f},{sp:.6f},{su:.6f},{rr:.6f},{ry:.6f}\n")

# 7b. reference vectors for the C++ unit test (error sequence -> u sequence)
rng = np.random.default_rng(20260710)
e_seq = np.concatenate([np.full(20, 0.2), np.full(20, -0.15),
                        0.1*rng.standard_normal(24)])
ref_ctrl = DiscreteController(sos, kI, TS)
u_seq = [ref_ctrl.step(float(e)) for e in e_seq]

# 7c. firmware coefficients header
def carr(v):
    return ", ".join(f"{x:.9e}f" for x in v)

with open(FW_HEADER, "w", encoding="utf-8") as f:
    f.write(f"""// share_controller_coeffs.h — GENERATED by controller_design/synthesize_controller.py
// DO NOT EDIT BY HAND. Regenerate after bench calibration (system_model.md §9).
//
// Youla-H robust power-share controller, Gc(z) = R(z) + kI*Ts/2*(z+1)/(z-1),
// discretized (Tustin) at Ts = {TS*1e3:.1f} ms from the H-inf + Youla-H design
// (gamma = {g_used:.4f}, T(0) = 1 enforced; see controller_design/controller_synthesis.md).
// R(z) realized as {len(sos)} DF2T biquad section(s); the integrator is separate so the
// firmware can apply back-calculation anti-windup (share_controller.h).
#pragma once

#define SHARE_CTRL_TS_US   {int(TS*1e6)}      // controller update period, microseconds
#define SHARE_CTRL_NSOS    {len(sos)}
static const float SHARE_CTRL_KI = {kI:.9e}f;   // integrator gain (continuous kI, Tustin in code)
// measured-share prefilter 1/(tauf*s+1), tauf = {TAUF*1e3:.1f} ms, discretized at Ts:
// alphaFilt += (1 - A)*(alphaRaw - alphaFilt), A = exp(-Ts/tauf). Part of the design
// plant (system_model.md 6d) — the loop is synthesized WITH this lag in it.
static const float SHARE_CTRL_MEAS_FILT_A = {np.exp(-TS/TAUF) if TAUF > 0 else 0.0:.9e}f;

// biquad sections: b0 b1 b2 a1 a2 (a0 = 1)
static const float SHARE_CTRL_SOS[SHARE_CTRL_NSOS][5] = {{
""")
    for b, a in sos:
        f.write(f"    {{ {carr(b)}, {a[1]:.9e}f, {a[2]:.9e}f }},\n")
    f.write("};\n")

with open(os.path.join(HERE, "reference_vectors.h"), "w", encoding="utf-8") as f:
    f.write("// GENERATED reference I/O for test_share_controller (synthesize_controller.py)\n")
    f.write("// error sequence -> expected controller output, Ts = 1 ms, r0 = 0.5\n#pragma once\n")
    f.write(f"#define SHARE_REF_N {len(e_seq)}\n")
    f.write("static const float SHARE_REF_E[SHARE_REF_N] = {\n    " +
            ",\n    ".join(f"{x:.9e}f" for x in e_seq) + "\n};\n")
    f.write("static const float SHARE_REF_U[SHARE_REF_N] = {\n    " +
            ",\n    ".join(f"{x:.9e}f" for x in u_seq) + "\n};\n")

# 7d. metrics summary for the report
with open(os.path.join(HERE, "synthesis_metrics.txt"), "w", encoding="utf-8") as f:
    f.write(f"""H-inf + Youla-H synthesis metrics (generated)
gamma_opt            = {g_opt:.4f}
gamma_used           = {g_used:.4f}
||Tzw||inf           = {tzw_norm:.4f}
controller order     = {K_H.n} (H-inf) -> {Gc_red.n} (reduced: integrator + {Gs_red.n})
T_H(0)               = {T0_H:.8f}
T_YH(0) reduced      = {T0_red:.12f}
S/T crossover        = {wc_ach:.1f} rad/s
nominal M2           = {M2_nom:.4f}
phase margin         = {pm:.1f} deg
delay margin         = {dm*1e3:.2f} ms
worst-corner M2      = {worstM2:.4f} at (K, Td, taur, tauf) = {worst_corner}
worst |z| discrete   = {worst_rad:.4f}
step 2% settle       = {t_settle*1e3:.0f} ms, overshoot = {ovs:.1f} %
ramp err (t = 6 s)   = {ramp_err_tail:.2e}
discrete worst ||S||inf: youla = {worstS_new:.3f}, legacy PI = {worstS_pi:.3f}
kI                   = {kI:.6f}
""")

print(f"\nartifacts: share_controller_coeffs.h, reference_vectors.h, "
      f"synthesis_metrics.txt, 3 CSVs")
print("\n" + ("ALL GATES PASSED" if not failures else "FAILURES: " + "; ".join(failures)))
raise SystemExit(1 if failures else 0)
