"""Third anti-windup option, intended to REPLACE the paper's example plant section.

Plant Gp = 1/(s+1) (paper eq. Gp_simple), first-order relaxed weights, but the loop
crossover is placed BELOW the plant pole (0.3 rad/s): the controller is then close to a
PI, the stable remainder R(s) of the split G_CYH = kI/s + R(s) carries little
low-frequency gain, and back-calculation on the integrator alone de-winds the
controller. gamma < 1 and T_H(0) != 1, so the section's original point (Youla-H still
matters when the optimization is easy) is preserved. Synthesis is the repo's
hinfsyn_mixed (controller_design/hinf_synthesis.py); Wp is strictly proper (hf = 0).
Outputs: YH-TSY-3rd (loop shapes vs 1/W) and YH-AW-3rd (saturated response).
"""
import sys, os
import numpy as np, scipy.signal as sg, scipy.linalg as la
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "controller_design"))
from hinf_synthesis import (SS, tf2ss, makeweight, strictly_proper_lf_weight, ss_series,
                            ss_scale, AugPlant, hinfsyn_mixed, split_integrator, hinf_norm)

Ts = 1e-3; WC = 0.3
Gp = tf2ss([1.0], [1.0, 1.0])
Wp = strictly_proper_lf_weight(1e3, WC)      # on S
Wd = makeweight(0.1, WC, 20.0)               # on T
Wu = makeweight(0.1, 100.0*WC, 30.0)         # on Y
K_H, g_used, g_opt, tzw = hinfsyn_mixed(AugPlant(Gp, Wp, Wu, Wd))
def loop_tfs(Gc, G):
    L = ss_series(Gc, G)
    S = SS(L.A - L.B @ L.C, L.B, -L.C, [[1.0]]); T = SS(L.A - L.B @ L.C, L.B, L.C, [[0.0]])
    return S, T, ss_series(S, Gc)
S_H, T_H, Y_H = loop_tfs(K_H, Gp); T0 = T_H.dcgain()
print(f"gamma_opt = {g_opt:.4f}   T_H(0) = {T0:.7f} (deficiency {1-T0:.2e})   M2_H = {1/hinf_norm(S_H):.4f}")
Y_YH = ss_scale(Y_H, 1.0/T0)
A_gc = np.block([[Y_YH.A, Y_YH.B @ Gp.C], [Gp.B @ Y_YH.C, Gp.A]])
GcYH = SS(A_gc, np.vstack([Y_YH.B, np.zeros((Gp.n,1))]), np.hstack([Y_YH.C, np.zeros((1,Gp.n))]), [[0.0]])
S_YH, T_YH, Y_YH2 = loop_tfs(GcYH, Gp)
print(f"T_YH(0) = {T_YH.dcgain():.7f}   M2_YH = {1/hinf_norm(S_YH):.4f}")
kI, R = split_integrator(GcYH, tol=1e-4)
print(f"kI = {kI:.4f}   R(0) = {R.dcgain():.4f}   remainder poles (cont.): {np.round(np.sort(la.eigvals(R.A).real)[::-1][:4],3)}")

# ---- loop-shape figure (replacement for H-TSY-2nd) ----
w = np.logspace(-2, 3, 500); dB = lambda g: 20*np.log10(np.abs(g))
plt.rcParams.update({'font.size':10,'font.family':'serif','axes.linewidth':0.6,'mathtext.fontset':'cm'})
fig,ax = plt.subplots(figsize=(7.0,4.6))
ax.plot(w, dB(T_YH.freqresp(w)), 'k-', lw=1.1, label='$T$')
ax.plot(w, dB(S_YH.freqresp(w)), 'k--', lw=1.0, label='$S$')
ax.plot(w, dB(Y_YH2.freqresp(w)), 'k:', lw=1.1, label='$Y$')
ax.plot(w, -dB(Wd.freqresp(w)), c='0.55', ls='-', lw=0.8, label='$1/W_d$')
ax.plot(w, -dB(Wp.freqresp(w)), c='0.55', ls='--', lw=0.8, label='$1/W_p$')
ax.plot(w, -dB(Wu.freqresp(w)), c='0.55', ls=':', lw=0.9, label='$1/W_u$')
ax.set_xscale('log'); ax.set_ylim(-60,25); ax.set_xlabel('frequency [rad/s]'); ax.set_ylabel('magnitude [dB]')
ax.grid(alpha=0.25,lw=0.4,which='both'); ax.legend(frameon=False,fontsize=9,ncol=6,loc='upper center',bbox_to_anchor=(0.5,-0.14)); fig.subplots_adjust(bottom=0.22)
fig.savefig(os.path.join(HERE,'figures','YH-TSY-3rd.png'),dpi=400,bbox_inches='tight'); fig.savefig(os.path.join(HERE,'figures','YH-TSY-3rd.pdf'),bbox_inches='tight')

# ---- saturated response ----
def tustin(s): d = sg.cont2discrete((s.A,s.B,s.C,s.D),Ts,method='bilinear'); return [np.atleast_2d(m) for m in d[:4]]
def zoh(s):    d = sg.cont2discrete((s.A,s.B,s.C,s.D),Ts,method='zoh');      return [np.atleast_2d(m) for m in d[:4]]
Pd, Hd, (Ar,Br,Cr,Dr) = zoh(Gp), tustin(K_H), tustin(R)
Ad = la.block_diag([[1.0]],Ar); Bd = np.vstack([[kI*Ts],Br]); Cd = np.hstack([[[1.0]],Cr]); Dd = kI*Ts/2 + Dr
n = Ad.shape[0]
ev = la.eigvals(Ad - (Bd/Dd)@Cd); L = sg.place_poles(Ad.T, Cd.T, np.array([0.5 if abs(p+1)<1e-3 else p for p in ev])).gain_matrix.T

U_MAX = 1.5; T_HI = 3.5
def ref(tt): return 3.0 if 1.0 <= tt < T_HI else 1.0 if tt >= T_HI else 0.0
N = int(20/Ts)
def sim(mode):
    Ap,Bp,Cp,Dp = Pd; xp = np.zeros((Ap.shape[0],1)); y = 0.0; Y = np.zeros(N); U = np.zeros(N)
    xc = np.zeros((Hd[0].shape[0],1)) if mode=='H' else np.zeros((n,1))
    for k in range(N):
        e = ref(k*Ts) - y
        if mode == 'H':
            ul = float((Hd[2]@xc + Hd[3]*e).item()); u = float(np.clip(ul,-U_MAX,U_MAX)); xc = Hd[0]@xc + Hd[1]*e
        else:
            ul = float((Cd@xc + Dd*e).item()); u = float(np.clip(ul,-U_MAX,U_MAX)); xn = Ad@xc + Bd*e
            if mode == 'AWI': xn[0,0] += (u - ul)
            elif mode == 'AWH': xn += L*(u - ul)
            xc = xn
        xp = Ap@xp + Bp*u; y = float((Cp@xp + Dp*u).item()); Y[k]=y; U[k]=u
    return Y,U
t = np.arange(N)*Ts; modes = ['H','YH','AWI','AWH']; res = {m: sim(m) for m in modes}
for m,(Y,U) in res.items():
    seg = t >= T_HI; err = Y[seg]-1.0; idx = np.where(np.abs(err) > 0.02)[0]
    print(f"{m}: rail dwell {np.sum(np.abs(U)>=U_MAX-1e-12)*Ts:.2f} s, after step-down: peak {Y[seg].max():.3f}, "
          f"min {Y[seg].min():.3f}, 2% settle {t[seg][idx[-1]]-T_HI if len(idx) else 0:.2f} s, final err {err[-1]:+.1e}")

fig,ax = plt.subplots(2,1,figsize=(7.0,5.2),sharex=True,gridspec_kw={'hspace':0.10,'height_ratios':[1.5,1]})
st = {'H':dict(c='0.6',ls='--',lw=1.0,label=r'$H_\infty$, clamp only'),
      'YH':dict(c='k',ls=':',lw=1.1,label='Youla-H, clamp only'),
      'AWI':dict(c='k',ls='-',lw=1.2,label='Youla-H, integrator back-calc.')}
ax[0].plot(t,[ref(x) for x in t],c='0.8',lw=0.8)
for m in ['H','YH','AWI']: ax[0].plot(t,res[m][0],**st[m]); ax[1].plot(t,res[m][1],**st[m])
ax[0].set_ylabel('$y$'); ax[1].set_ylabel('$u$'); ax[1].set_xlabel('time [s]')
ax[1].axhline(U_MAX,c='0.8',lw=0.6); ax[1].set_ylim(-0.4,1.8)
h,l=ax[0].get_legend_handles_labels(); fig.legend(h,l,frameon=False,fontsize=9,loc='lower center',ncol=2,bbox_to_anchor=(0.5,0.0)); fig.subplots_adjust(bottom=0.20); ax[0].set_xlim(0,20)
for a in ax: a.grid(alpha=0.25,lw=0.4)
fig.savefig(os.path.join(HERE,'figures','YH-AW-3rd.png'),dpi=400,bbox_inches='tight'); fig.savefig(os.path.join(HERE,'figures','YH-AW-3rd.pdf'),bbox_inches='tight')
print("saved YH-TSY-3rd, YH-AW-3rd")
