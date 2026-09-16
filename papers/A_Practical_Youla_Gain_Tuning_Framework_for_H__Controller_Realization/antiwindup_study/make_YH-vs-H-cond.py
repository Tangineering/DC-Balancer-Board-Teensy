"""H-inf vs Youla-H on the drivetrain plant, BOTH with full-state (Hanus) conditioning.
Question: does Youla-H retain a benefit once the discretized controller needs full-state
conditioning anyway?  Same plant/controllers as make_YH-AW-18.py (paper eqs. Gp_numerical,
Gch, Gcyh), Tustin at 1 ms, conditioning gain L pole-placed from the self-conditioned
spectrum with the structural z = -1 eigenvalue moved to +0.5.
"""
import os, numpy as np, scipy.signal as sg, scipy.linalg as la
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.abspath(__file__)); Ts = 1e-3
Gp = sg.ZerosPolesGain([], [-4.32e-5], 22.624).to_ss()
zs = np.concatenate([[-8.225, -4.316e-5], np.roots([1, 5.045e4, 1.273e9])])
p_H  = np.concatenate([[-1.926e4], np.roots([1, 0.2141, 0.02291]), np.roots([1, 747.5, 2.795e5])])
p_YH = np.concatenate([[0.0, -1.926e4, -0.2113], np.roots([1, 747.5, 2.795e5])])
GcH  = sg.ZerosPolesGain(zs, p_H, 4.5781).to_ss()
GcYH = sg.ZerosPolesGain(zs, p_YH, 4.5787).to_ss()
def split_integrator(ss, tol=1e-6):
    A,B,C,D = ss.A, ss.B, ss.C, ss.D
    T,Z,sdim = la.schur(A, output='real', sort=lambda x,y: np.hypot(x,y) < tol); assert sdim == 1
    l0, A22, M = T[0,0], T[1:,1:], T[0:1,1:]
    S = la.solve_sylvester(np.array([[l0]]), -A22, -M)
    n = A.shape[0]; W = np.eye(n); W[0:1,1:] = S; Wi = np.eye(n); Wi[0:1,1:] = -S
    Ab, Bt, Ct = Wi@T@W, Wi@Z.T@B, C@Z@W
    return float(Ct[0,0]*Bt[0,0]), sg.StateSpace(Ab[1:,1:], Bt[1:], Ct[:,1:], D)
def tustin(s): d = sg.cont2discrete((s.A,s.B,s.C,s.D),Ts,method='bilinear'); return [np.atleast_2d(m) for m in d[:4]]
def zoh(s):    d = sg.cont2discrete((s.A,s.B,s.C,s.D),Ts,method='zoh');      return [np.atleast_2d(m) for m in d[:4]]
Pd = zoh(Gp)
# H-inf: plain Tustin state-space.  Youla-H: exact integrator (trapezoid) + Tustin remainder.
Hd = tustin(GcH)
kI, R = split_integrator(GcYH); Ar,Br,Cr,Dr = tustin(R)
YHd = [la.block_diag([[1.0]],Ar), np.vstack([[kI*Ts],Br]), np.hstack([[[1.0]],Cr]), kI*Ts/2 + Dr]
def cond_gain(Ad,Bd,Cd,Dd):
    ev = la.eigvals(Ad - (Bd/Dd)@Cd)
    L = sg.place_poles(Ad.T, Cd.T, np.array([0.5 if abs(p+1)<1e-3 else p for p in ev])).gain_matrix.T
    return L, ev, la.eigvals(Ad - L@Cd)
ctrl = {}
for name, M in [('H', Hd), ('YH', YHd)]:
    L, ev0, ev1 = cond_gain(*M); ctrl[name] = (M, L)
    print(f"{name}: self-cond eig {np.round(np.sort_complex(ev0),5)}\n     placed eig    {np.round(np.sort_complex(ev1),5)}")

U_MAX = 0.10
def sim(name, ref, N, cond=True):
    (Ad,Bd,Cd,Dd), L = ctrl[name]; Ap,Bp,Cp,Dp = Pd
    xc = np.zeros((Ad.shape[0],1)); xp = np.zeros((Ap.shape[0],1)); y = 0.0
    Y = np.zeros(N); U = np.zeros(N)
    for k in range(N):
        e = ref(k*Ts) - y
        ul = float((Cd@xc + Dd*e).item()); u = float(np.clip(ul,-U_MAX,U_MAX))
        xc = Ad@xc + Bd*e + (L*(u-ul) if cond else 0.0)
        xp = Ap@xp + Bp*u; y = float((Cp@xp + Dp*u).item()); Y[k]=y; U[k]=u
    return Y,U

# Scenario A: saturating 5 m/s step
NA = int(12/Ts); tA = np.arange(NA)*Ts; refA = lambda tt: 5.0 if tt>=0.5 else 0.0
# Scenario B: unsaturated slow ramp 0 -> 5 m/s over 200 s  (T(0) bias)
NB = int(200/Ts); tB = np.arange(NB)*Ts; refB = lambda tt: 0.025*tt
# Scenario C: saturating ramp 0 -> 5 m/s over 1.5 s then hold  (accel 3.33 > 2.26 m/s^2 limit)
NC = int(12/Ts); tC = np.arange(NC)*Ts; refC = lambda tt: min(5.0, 5.0*max(tt-0.5,0)/1.5)
res = {}
for name in ['H','YH']:
    YA,UA = sim(name, refA, NA); YB,UB = sim(name, refB, NB); YC,UC = sim(name, refC, NC)
    rA = np.array([refA(x) for x in tA]); rB = refB(tB); rC = np.array([refC(x) for x in tC])
    iA = np.where(np.abs(YA-5)>0.1)[0]; iC = np.where(np.abs(YC-5)>0.1)[0]
    print(f"\n{name} (conditioned):")
    print(f"  A step : rail {np.sum(np.abs(UA)>=U_MAX-1e-12)*Ts:.2f} s, overshoot {100*(YA.max()/5-1):+.2f} %, "
          f"2% settle {tA[iA[-1]]-0.5:.2f} s, y(12 s) err {YA[-1]-5:+.2e}")
    print(f"  B ramp : tracking error at 50/100/200 s = {YB[int(50/Ts)]-rB[int(50/Ts)]:+.4f} / "
          f"{YB[int(100/Ts)]-rB[int(100/Ts)]:+.4f} / {YB[-1]-rB[-1]:+.4f} m/s, max|u| {np.abs(UB).max():.3f}")
    print(f"  C sat ramp: rail {np.sum(np.abs(UC)>=U_MAX-1e-12)*Ts:.2f} s, overshoot {100*(YC.max()/5-1):+.2f} %, "
          f"2% settle {tC[iC[-1]]-0.5:.2f} s")
    res[name] = (YA,UA,YB,UB,YC,UC,rB)
# unconditioned reference: bias of H-inf on ramp B without saturation is the same (never clamps)

plt.rcParams.update({'font.size':10,'font.family':'serif','axes.linewidth':0.6,'mathtext.fontset':'cm'})
fig,ax = plt.subplots(1,2,figsize=(7.0,3.6),gridspec_kw={'wspace':0.45})
st = {'H':dict(c='b',ls='--',lw=1.6,label=r'$H_\infty$, conditioned'),
      'YH':dict(c='k',ls='-',lw=1.6,label='Youla-H, conditioned')}
for name in ['H','YH']:
    YA,UA,YB,UB,YC,UC,rB = res[name]
    ax[0].plot(tA, YA, **st[name]); ax[1].plot(tB, YB-rB, **st[name])
ax[0].plot(tA, [refA(x) for x in tA], c='0.8', lw=0.8, zorder=0)
ax[0].set_xlabel('time [s]'); ax[0].set_ylabel('$v$ [m/s]'); ax[0].set_title('saturating step', fontsize=8)
ax[1].set_xlabel('time [s]'); ax[1].set_ylabel('$v - v_{ref}$ [m/s]'); ax[1].set_title('slow ramp, no saturation', fontsize=8)
h,l=ax[1].get_legend_handles_labels(); fig.legend(h,l,frameon=False,fontsize=9,loc='lower center',ncol=2,bbox_to_anchor=(0.5,0.0)); fig.subplots_adjust(bottom=0.28)
for a in ax: a.grid(alpha=0.25, lw=0.4)
fig.savefig(os.path.join(HERE,'figures','python','YH-vs-H-cond-18.png'),dpi=400,bbox_inches='tight'); fig.savefig(os.path.join(HERE,'figures','python','YH-vs-H-cond-18.pdf'),bbox_inches='tight')
print("saved YH-vs-H-cond-18")
