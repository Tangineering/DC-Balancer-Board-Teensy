"""Anti-windup figure on the paper's alternate ("example") plant Gp = 1/(s+1).

The paper gives the weights only graphically (Figures/H-TSY-2nd.png); the first-order
weights below are read off that plot (1/Wd: +20 dB -> -34 dB crossing 1 rad/s;
1/Wp: +20 dB/dec through 1 rad/s; 1/Wu: +20 dB, rolling off past ~100 rad/s) and the
H-inf synthesis is the repo's own hinfsyn_mixed (controller_design/hinf_synthesis.py),
so gamma and T_H(0) here will differ slightly from the MATLAB values in the paper.
Wp is realised strictly proper (hf = 0) because the mixed-sensitivity augmentation
needs D11 = 0; the plot's 1/Wp only reaches ~0 dB at high frequency anyway.
"""
import sys, os
import numpy as np, scipy.signal as sg, scipy.linalg as la
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "controller_design"))
from hinf_synthesis import (SS, tf2ss, makeweight, strictly_proper_lf_weight, ss_series,
                            ss_scale, AugPlant, hinfsyn_mixed, split_integrator)

Ts = 1e-3
Gp = tf2ss([1.0], [1.0, 1.0])                        # paper eq. Gp_simple
Wp = strictly_proper_lf_weight(1e4, 1.0)             # on S
Wd = makeweight(0.1, 1.0, 50.0)                      # on T
Wu = makeweight(0.1, 100.0, 30.0)                    # on Y
K_H, g_used, g_opt, tzw = hinfsyn_mixed(AugPlant(Gp, Wp, Wu, Wd))
print(f"gamma_opt = {g_opt:.4f}")

def loop_tfs(Gc, G):
    L = ss_series(Gc, G)
    S = SS(L.A - L.B @ L.C, L.B, -L.C, [[1.0]])
    T = SS(L.A - L.B @ L.C, L.B,  L.C, [[0.0]])
    return S, T, ss_series(S, Gc)
S_H, T_H, Y_H = loop_tfs(K_H, Gp)
T0 = T_H.dcgain(); print(f"T_H(0) = {T0:.7f}  (deficiency {1-T0:.2e})")
Y_YH = ss_scale(Y_H, 1.0/T0)
A_gc = np.block([[Y_YH.A, Y_YH.B @ Gp.C], [Gp.B @ Y_YH.C, Gp.A]])
GcYH = SS(A_gc, np.vstack([Y_YH.B, np.zeros((Gp.n, 1))]),
          np.hstack([Y_YH.C, np.zeros((1, Gp.n))]), [[0.0]])
kI, R = split_integrator(GcYH, tol=1e-4)
print(f"kI = {kI:.4f}   R(0) = {R.dcgain():.4f}   K_H order {K_H.n}, R order {R.n}")

def tustin(s): d = sg.cont2discrete((s.A, s.B, s.C, s.D), Ts, method='bilinear'); return [np.atleast_2d(m) for m in d[:4]]
def zoh(s):    d = sg.cont2discrete((s.A, s.B, s.C, s.D), Ts, method='zoh');      return [np.atleast_2d(m) for m in d[:4]]
Pd, Hd, Rd = zoh(Gp), tustin(K_H), tustin(R)

Ai,Bi,Ci,Di = np.array([[1.0]]), np.array([[kI*Ts]]), np.array([[1.0]]), np.array([[kI*Ts/2]])
Ar,Br,Cr,Dr = Rd
Ad = la.block_diag(Ai,Ar); Bd = np.vstack([Bi,Br]); Cd = np.hstack([Ci,Cr]); Dd = Di+Dr
n = Ad.shape[0]
ev_self = la.eigvals(Ad - (Bd/Dd)@Cd); print("eig(A - L_self C):", np.round(ev_self, 5))
poles = np.array([0.5 if abs(p+1) < 1e-3 else p for p in ev_self])
L = sg.place_poles(Ad.T, Cd.T, poles).gain_matrix.T
print("eig(A - L C):", np.round(la.eigvals(Ad - L@Cd), 5))

U_MAX = 1.5                       # actuator limit; u_ss = r on this unity-DC-gain plant
T_HI = 3.5
def ref(tt): return 3.0 if 1.0 <= tt < T_HI else 1.0 if tt >= T_HI else 0.0
N = int(16/Ts)

def sim(mode):
    Ap,Bp,Cp,Dp = Pd; xp = np.zeros((Ap.shape[0],1)); y = 0.0
    Y = np.zeros(N); U = np.zeros(N)
    if mode == 'H': Ac,Bc,Cc,Dc = Hd; xc = np.zeros((Ac.shape[0],1))
    else: xc = np.zeros((n,1))
    for k in range(N):
        e = ref(k*Ts) - y
        if mode == 'H':
            ul = float((Cc@xc + Dc*e).item()); u = float(np.clip(ul,-U_MAX,U_MAX)); xc = Ac@xc + Bc*e
        else:
            ul = float((Cd@xc + Dd*e).item()); u = float(np.clip(ul,-U_MAX,U_MAX))
            xn = Ad@xc + Bd*e
            if mode == 'AWI': xn[0,0] += (u - ul)
            elif mode == 'AWH': xn += L*(u - ul)
            xc = xn
        xp = Ap@xp + Bp*u; y = float((Cp@xp + Dp*u).item()); Y[k]=y; U[k]=u
    return Y,U

t = np.arange(N)*Ts; modes = ['H','YH','AWI','AWH']; res = {m: sim(m) for m in modes}
for m,(Y,U) in res.items():
    seg = t >= T_HI; err = Y[seg]-1.0
    idx = np.where(np.abs(err) > 0.02)[0]
    print(f"{m}: rail dwell {np.sum(np.abs(U)>=U_MAX-1e-12)*Ts:.2f} s, "
          f"after step-down: peak {Y[seg].max():.3f}, min {Y[seg].min():.3f}, "
          f"2% settle {t[seg][idx[-1]]-T_HI if len(idx) else 0:.2f} s, final err {err[-1]:+.1e}")

plt.rcParams.update({'font.size':8,'font.family':'serif','axes.linewidth':0.6,'mathtext.fontset':'cm'})
fig,ax = plt.subplots(2,1,figsize=(3.45,2.9),sharex=True,gridspec_kw={'hspace':0.10,'height_ratios':[1.5,1]})
st = {'H':dict(c='b',ls='--',lw=1.2,label=r'$H_\infty$, clamp only'),
      'YH':dict(c='k',ls=':',lw=1.6,label='Youla-H, clamp only'),
      'AWI':dict(c='k',ls='-.',lw=1.2,label='Youla-H, integrator back-calc.'),
      'AWH':dict(c='k',ls='-',lw=1.2,label='Youla-H, full-state conditioning')}
ax[0].plot(t,[ref(x) for x in t],c='0.8',lw=0.8)
for m in modes: ax[0].plot(t,res[m][0],**st[m]); ax[1].plot(t,res[m][1],**st[m])
ax[0].set_ylabel('$y$'); ax[1].set_ylabel('$u$'); ax[1].set_xlabel('time [s]')
ax[1].axhline(U_MAX,c='0.8',lw=0.6); ax[1].set_ylim(-0.4,1.8)
h,l=ax[0].get_legend_handles_labels(); fig.legend(h,l,frameon=False,fontsize=7,loc='lower center',ncol=2,bbox_to_anchor=(0.5,-0.01)); fig.subplots_adjust(bottom=0.30); ax[0].set_xlim(0,16)
for a in ax: a.grid(alpha=0.25,lw=0.4)
out = os.path.join(HERE,'figures','python','YH-AW-2nd')
fig.savefig(out+'.png',dpi=300,bbox_inches='tight'); fig.savefig(out+'.pdf',bbox_inches='tight'); print("saved", out)
