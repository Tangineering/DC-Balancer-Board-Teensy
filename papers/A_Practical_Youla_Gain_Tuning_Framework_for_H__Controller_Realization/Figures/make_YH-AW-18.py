import numpy as np, scipy.signal as sg, scipy.linalg as la
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

Ts = 1e-3
# Plant (paper eq. Gp_numerical)
Gp = sg.ZerosPolesGain([], [-4.32e-5], 22.624)
# Controllers from paper eqs. Gch / Gcyh (ZPK)
zs = np.concatenate([[-8.225, -4.316e-5], np.roots([1, 5.045e4, 1.273e9])])
p_H  = np.concatenate([[-1.926e4], np.roots([1, 0.2141, 0.02291]), np.roots([1, 747.5, 2.795e5])])
p_YH = np.concatenate([[0.0, -1.926e4, -0.2113], np.roots([1, 747.5, 2.795e5])])
GcH  = sg.ZerosPolesGain(zs, p_H, 4.5781).to_ss()
GcYH = sg.ZerosPolesGain(zs, p_YH, 4.5787).to_ss()

def split_integrator(ss, tol=1e-6):
    """Gc = kI/s + R(s): ordered real Schur, then Sylvester block-diagonalisation."""
    A,B,C,D = ss.A, ss.B, ss.C, ss.D
    T,Z,sdim = la.schur(A, output='real', sort=lambda x,y: np.hypot(x,y) < tol)
    assert sdim == 1
    l0, A22, M = T[0,0], T[1:,1:], T[0:1,1:]
    S = la.solve_sylvester(np.array([[l0]]), -A22, -M)
    n = A.shape[0]; W = np.eye(n); W[0:1,1:] = S; Wi = np.eye(n); Wi[0:1,1:] = -S
    Ab, Bt, Ct = Wi@T@W, Wi@Z.T@B, C@Z@W
    kI = float(Ct[0,0]*Bt[0,0])
    return kI, sg.StateSpace(Ab[1:,1:], Bt[1:], Ct[:,1:], D)

kI, R = split_integrator(GcYH)
print("kI =", kI, " R(0) =", float((R.C@la.solve(-R.A, R.B)+R.D).squeeze()))

def tustin(ss):
    d = sg.cont2discrete((ss.A, ss.B, ss.C, ss.D), Ts, method='bilinear'); return [np.atleast_2d(m) for m in d[:4]]
def zoh(ss):
    d = sg.cont2discrete((ss.A, ss.B, ss.C, ss.D), Ts, method='zoh'); return [np.atleast_2d(m) for m in d[:4]]

Pd = zoh(Gp.to_ss())
Hd, YHd, Rd = tustin(GcH), tustin(GcYH), tustin(R)


U_MAX = 0.10      # N*m, illustrative actuator limit (see note in section text)
r_step = 5.0      # m/s
N = int(12/Ts)

# Discrete split realization: x = [x_I ; x_R],  u = x_I + C_R x_R + (kI Ts/2 + D_R) e
Ai,Bi,Ci,Di = np.array([[1.0]]), np.array([[kI*Ts]]), np.array([[1.0]]), np.array([[kI*Ts/2]])
Ar,Br,Cr,Dr = Rd
Ad = la.block_diag(Ai,Ar); Bd = np.vstack([Bi,Br]); Cd = np.hstack([Ci,Cr]); Dd = Di+Dr
n = Ad.shape[0]
# Hanus self-conditioned gain and its saturated-mode spectrum
L_self = Bd/Dd
ev_self = la.eigvals(Ad - L_self@Cd)
print("eig(A - L_self C):", np.round(ev_self,6))
# pole-placed L: keep the spectrum, move any eigenvalue at z=-1 to +0.5 (fw v18 recipe)
poles = ev_self.copy()
poles = np.array([0.5 if abs(p+1)<1e-3 else p for p in poles])
pp = sg.place_poles(Ad.T, Cd.T, poles)
L = pp.gain_matrix.T
print("eig(A - L C):", np.round(la.eigvals(Ad-L@Cd),6))

def sim(mode):
    Ap,Bp,Cp,Dp = Pd
    xp = np.zeros((Ap.shape[0],1)); y = 0.0
    Y = np.zeros(N); U = np.zeros(N); UU = np.zeros(N)
    if mode == 'H':
        Ac,Bc,Cc,Dc = Hd; xc = np.zeros((Ac.shape[0],1))
    else:
        xc = np.zeros((n,1))
    for k in range(N):
        r = r_step if k*Ts >= 0.5 else 0.0
        e = r - y
        if mode == 'H':
            u_lin = float((Cc@xc + Dc*e).item()); u = float(np.clip(u_lin,-U_MAX,U_MAX))
            xc = Ac@xc + Bc*e
        else:
            u_lin = float((Cd@xc + Dd*e).item()); u = float(np.clip(u_lin,-U_MAX,U_MAX))
            xn = Ad@xc + Bd*e
            if mode == 'AWI':                     # back-calculation, integrator state only
                xn[0,0] += (u - u_lin)
            elif mode == 'AWH':                   # general Hanus conditioning, all states
                xn += L*(u - u_lin)
            xc = xn
        xp = Ap@xp + Bp*u; y = float((Cp@xp + Dp*u).item())
        Y[k]=y; U[k]=u; UU[k]=u_lin
    return Y,U,UU

t = np.arange(N)*Ts
modes = ['H','YH','AWI','AWH']
res = {m: sim(m) for m in modes}
for m,(Y,U,UU) in res.items():
    sat = np.sum(np.abs(U)>=U_MAX-1e-12)*Ts
    idx = np.where(np.abs(Y-r_step)>0.02*r_step)[0]
    print(f"{m}: sat dwell {sat:.2f} s, peak y {Y.max():.3f} (overshoot {100*(Y.max()/r_step-1):.1f}%), "
          f"settle(2%) {t[idx[-1]] if len(idx) else 0:.2f} s, max|u_unsat| {np.abs(UU).max():.2f}")

plt.rcParams.update({'font.size':8,'font.family':'serif','axes.linewidth':0.6,'mathtext.fontset':'cm'})
fig,ax = plt.subplots(2,1,figsize=(3.45,2.6),sharex=True,gridspec_kw={'hspace':0.10,'height_ratios':[1.5,1]})
st = {'H':dict(c='0.6',ls='--',lw=1.0,label=r'$H_\infty$, clamp only'),
      'YH':dict(c='k',ls=':',lw=1.1,label='Youla-H, clamp only'),
      'AWI':dict(c='k',ls='-.',lw=1.0,label='Youla-H, integrator back-calc.'),
      'AWH':dict(c='k',ls='-',lw=1.2,label='Youla-H, full-state conditioning')}
ax[0].plot(t,np.where(t>=0.5,r_step,0.0),c='0.8',lw=0.8)
for m in modes:
    ax[0].plot(t,res[m][0],**st[m]); ax[1].plot(t,res[m][1],**st[m])
ax[0].set_ylabel('$v$ [m/s]'); ax[1].set_ylabel('$T_e$ [N$\\cdot$m]'); ax[1].set_xlabel('time [s]')
ax[1].axhline(U_MAX,c='0.8',lw=0.6); ax[1].axhline(-U_MAX,c='0.8',lw=0.6)
ax[0].legend(frameon=False,fontsize=6,loc='upper left'); ax[0].set_xlim(0,12)
for a in ax: a.grid(alpha=0.25,lw=0.4)
out='/home/user/DC-Balancer-Board-Teensy/papers/A_Practical_Youla_Gain_Tuning_Framework_for_H__Controller_Realization/Figures/YH-AW-18'
fig.savefig(out+'.png',dpi=300,bbox_inches='tight'); fig.savefig(out+'.pdf',bbox_inches='tight')
print("saved", out)
