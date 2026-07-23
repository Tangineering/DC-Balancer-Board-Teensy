#!/usr/bin/env python3
"""tps61288_full_model.py — full-order small-signal model of the droop share plant.

Empirical validation companion to the simplified design plant (system_model.md §6d/§6e
and full_order_validation.md). Builds the COMPLETE small-signal LTI model of the
r -> alpha share plant with the full TPS61288 dynamics per datasheet §9.2.2.5:

  * per-channel gm error amplifier with the exact compensation impedance
    Z_comp = R_EA || (R_C + 1/sC_C) || 1/sC_P   (not the factored pole approximation)
  * per-channel power stage as a Norton equivalent — controlled current source
    i_N = K_COMP (1-D)(1 - s/w_RHPZ) v_comp with shunt R_int = Vbus0/I_i0 — which
    reduces EXACTLY to DS Eq. 7 under a single resistive load (gate-checked below);
    this equivalence is what licenses paralleling two converters on one bus
  * three-resistor FB node with droop injection (h1 = bus divider, h2 = op-amp
    injection; h2/h1 = R_D1/R_inj recovers the static droop law)
  * bilinear droop linearization: v_op = Av*Ksns*(g0*H_INA(s)*i + I0*g_hat),
    g_hat from the firmware mapping g = K_DROOP/(RE_MAX*r)
  * INA253 sense pole (350 kHz), per-channel output caps, 2 mOhm INA shunts,
    shared bus capacitance, CC load
  * the same digital layer as the simplified model: Pade(2) delay + ZOH at Ts=1ms

Then validates, all gate-checked:
  A. Norton -> DS Eq. 7 reduction (exact)
  B. DC gain d(alpha)/dr = 1 emerges from the full linearization
  C. per-channel voltage-loop crossovers match the §6e datasheet arithmetic
  D. nominal Bode deviation vs the simplified plant, in the design band
  E. envelope: every operating-grid point is covered by the simplified corner family
  F. discrete closed loop with the SHIPPED controller (parsed from
     share_controller_coeffs.h): stability across the grid, worst ||S||inf,
     step/ramp overlay vs the simplified plant

Emits figures/fullorder_*.csv + fullorder_metrics.txt.
Run:  <ctrl-venv python> tps61288_full_model.py
"""

import os
import re
import numpy as np
from numpy.linalg import eigvals, solve

from hinf_synthesis import (SS, tf2ss, pade2, ss_series, ss_parallel,
                            c2d_zoh, dfreqresp)

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figures")
FW_HEADER = os.path.join(HERE, "..", "teensy_controller", "share_controller_coeffs.h")

failures = []


def gate(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


# ─────────────────────────────────────────────────────────────────────────────
# Parameters (sources: TPS61288 DS §7.5/§9.2.2.5; schematic sheets 1-2 + bodges;
# system_model.md §8)
# ─────────────────────────────────────────────────────────────────────────────
VREF   = 0.6          # V     TPS61288 FB reference (DS §7.5, verified)
GEA    = 180e-6       # S     EA transconductance (DS §7.5)
KCOMP  = 13.5         # A/V   power-stage transconductance (DS §7.5)
L      = 2.2e-6       # H
RC     = 61.2e3       # ohm   compensator (both channels post RC-BT bodge)
CC     = 2e-9         # F
CPP    = 27e-12       # F     COMP pin Cp
RD1    = 215e3        # ohm   FB top (RD1 bodge, 16V retune; schematic shows 237k)
RD2    = 10e3         # ohm
RINJ   = 53.6e3       # ohm
AV     = 1 + 40.2/10  # OPA197 gain 5.02
KSNS   = 0.1          # V/A   INA253A1
RSH    = 2e-3         # ohm   INA253 internal shunt
W_INA  = 2*np.pi*350e3  # rad/s INA253 bandwidth
RE_MAX = KSNS*AV*RD1/RINJ            # 2.014 ohm
K_D    = 0.30         # ohm   firmware K_DROOP
VBUS0  = VREF*(1 + RD1/RD2 + RD1/RINJ)   # 15.907 V no-load setpoint
TS     = 1e-3         # s     share-loop period
TD     = 1e-3         # s     ZOH + latch delay (same as simplified nominal)

# FB node superposition gains (op-amp output = low-impedance source)
_P  = RD2*RINJ/(RD2 + RINJ)
H1  = _P/(RD1 + _P)                        # v_bus-side divider
H2  = H1*RD1/RINJ                          # injection gain (h2/h1 = RD1/RINJ exactly)

# simplified-model constants for comparison
TAUR_NOM  = 100e-6
TAUR_SET  = (20e-6, 100e-6, 300e-6)
TD_SET    = (0.5e-3, 1e-3, 2e-3)


def zcomp_ss(REA):
    """Exact compensation impedance Z_comp(s), strictly proper (2 states, D=0)."""
    num = [RC*CC, 1.0]
    den = [RC*CC*CPP, CPP + CC + RC*CC/REA, 1.0/REA]
    return tf2ss(num, den)


# ─────────────────────────────────────────────────────────────────────────────
# Full-order plant assembly:  r_hat -> alpha_hat
# states: [x_zcF(2), x_zcB(2), v_oF, v_oB, v_bus, x_inaF, x_inaB, x_pade(2)]
# ─────────────────────────────────────────────────────────────────────────────
def full_plant(VinF=9.0, VinB=8.0, Itot=2.0, r0=0.5,
               Co=30e-6, Cbus=30e-6, REA=10e6, Td=TD, with_pade=True):
    IF0, IB0 = r0*Itot, (1-r0)*Itot
    ch = []
    for Vin, I0 in ((VinF, IF0), (VinB, IB0)):
        oneD  = Vin/VBUS0                        # (1-D)
        Rint  = VBUS0/I0                         # operating-point load line
        wrhpz = Rint*oneD**2/L                   # DS Eq. 10 (rad/s)
        g0    = None                             # set below per channel
        ch.append(dict(oneD=oneD, Rint=Rint, wrhpz=wrhpz, I0=I0))
    ch[0]['g0'] = K_D/(RE_MAX*r0)
    ch[1]['g0'] = K_D/(RE_MAX*(1-r0))
    ch[0]['dg'] = -K_D/(RE_MAX*r0**2)            # d g_F / d r
    ch[1]['dg'] = +K_D/(RE_MAX*(1-r0)**2)        # d g_B / d r

    zc = zcomp_ss(REA)                           # shared realization (same RC/CC/CP)
    Azc, Bzc, Czc = zc.A, zc.B.flatten(), GEA*zc.C.flatten()
    nz = 2

    pd = pade2(Td) if with_pade else tf2ss([1.0], [1.0])
    npd = pd.n

    n = 2*nz + 3 + 2 + npd
    A = np.zeros((n, n)); B = np.zeros((n, 1))
    iZ = [slice(0, nz), slice(nz, 2*nz)]         # compensator states per channel
    iV = [2*nz, 2*nz+1]                          # v_oF, v_oB
    iB_ = 2*nz + 2                               # v_bus
    iI = [2*nz+3, 2*nz+4]                        # INA states per channel
    iP = slice(2*nz+5, 2*nz+5+npd)

    # Pade: r_d = Cpd x_pd + Dpd r
    if npd:
        A[iP, iP] = pd.A
        B[iP.start:iP.stop, 0] = pd.B.flatten()
    Cpd = pd.C.flatten() if npd else np.zeros(0)
    Dpd = pd.D[0, 0]

    for k in (0, 1):
        c = ch[k]
        Kc = KCOMP*c['oneD']
        # channel current i_k = (v_ok - v_bus)/RSH  (row over states)
        row_i = np.zeros(n); row_i[iV[k]] = 1.0/RSH; row_i[iB_] = -1.0/RSH

        # v_op_k = AV*g0*x_ina + AV*KSNS*I0*g_hat ; g_hat = dg*(Cpd x_pd + Dpd r)
        row_vop = np.zeros(n); row_vop[iI[k]] = AV*c['g0']
        if npd:
            row_vop[iP] += AV*KSNS*c['I0']*c['dg']*Cpd
        vop_D = AV*KSNS*c['I0']*c['dg']*Dpd      # feedthrough from r

        # u_k = -(h1 v_ok + h2 v_op_k)
        row_u = np.zeros(n); row_u[iV[k]] = -H1
        row_u += -H2*row_vop
        u_D = -H2*vop_D

        # compensator states: x_zc' = Azc x_zc + Bzc u_k
        A[iZ[k], iZ[k]] = Azc
        A[iZ[k], :] += np.outer(Bzc, row_u)
        B[iZ[k], 0] += Bzc*u_D

        # Norton current i_N = Kc [Czc x_zc - (1/wr) Czc(Azc x_zc + Bzc u)]
        row_iN = np.zeros(n)
        row_iN[iZ[k]] = Kc*(Czc - (Czc @ Azc)/c['wrhpz'])
        cb = float(Czc @ Bzc)
        row_iN += -Kc*cb/c['wrhpz']*row_u
        iN_D = -Kc*cb/c['wrhpz']*u_D

        # node: Co v_ok' = i_N - v_ok/Rint - i_k
        A[iV[k], :] += (row_iN - row_i)/Co
        A[iV[k], iV[k]] += -1.0/(c['Rint']*Co)
        B[iV[k], 0] += iN_D/Co

        # bus: Cbus v_bus' += i_k
        A[iB_, :] += row_i/Cbus

        # INA: x_ina' = W_INA (KSNS i_k - x_ina)
        A[iI[k], :] += W_INA*KSNS*row_i
        A[iI[k], iI[k]] += -W_INA

    # output: alpha_hat = (IB0 iF - IF0 iB)/Itot^2
    rF = np.zeros(n); rF[iV[0]] = 1.0/RSH; rF[iB_] = -1.0/RSH
    rB = np.zeros(n); rB[iV[1]] = 1.0/RSH; rB[iB_] = -1.0/RSH
    C = ((ch[1]['I0']*rF - ch[0]['I0']*rB)/Itot**2).reshape(1, n)
    return SS(A, B, C, [[0.0]])


def simplified_plant(K=1.0, Td=TD, taur=TAUR_NOM):
    """Design plant WITHOUT tau_f (tau_f is the digital Hf, common to both models)."""
    from hinf_synthesis import ss_scale
    return ss_scale(ss_series(pade2(Td), tf2ss([1.0], [taur, 1.0])), K)


# ─────────────────────────────────────────────────────────────────────────────
# Gate A — Norton model reduces exactly to DS Eq. 7 under a resistive load
# ─────────────────────────────────────────────────────────────────────────────
print("A. Norton equivalent vs datasheet Eq. 7 (single channel, resistive load)")
Vin, Ro, Co_, ESR = 9.0, 8.0, 66e-6, 2e-3
oneD = Vin/VBUS0
wr = Ro*oneD**2/L
w = np.logspace(1, 6, 200)
s = 1j*w
# Norton: v_o = i_N * (Rint || Ro || (ESR + 1/sCo)), Rint = Ro
Zc = ESR + 1.0/(s*Co_)
Ypar = 1.0/Ro + 1.0/Ro + 1.0/Zc
G_norton = KCOMP*oneD*(1 - s/wr) / Ypar
# DS Eq. 7 with fP = 2/(2pi Ro Co), fESRZ = 1/(2pi ESR Co)
G_eq7 = KCOMP*(Ro*oneD/2)*(1 + s*ESR*Co_)*(1 - s/wr)/(1 + s*Ro*Co_/2)
# exact algebra: (Ro/2)(1+sESRCo)/(1+s(Ro/2+ESR)Co) vs DS's (Ro/2)(1+sESRCo)/(1+sRoCo/2)
# -> identical when ESR << Ro/2; compare with the exact parallel first (must be machine-exact)
G_exact = KCOMP*oneD*(1 - s/wr)*(Ro/2)*(1 + s*ESR*Co_)/(1 + s*(Ro/2 + ESR)*Co_)
err_exact = np.max(np.abs(G_norton - G_exact)/np.abs(G_exact))
err_ds = np.max(np.abs(G_norton - G_eq7)/np.abs(G_eq7))
gate("Norton == exact parallel-impedance algebra", err_exact < 1e-12,
     f"max rel err {err_exact:.2e}")
gate("Norton == DS Eq. 7 (ESR-in-pole difference only)", err_ds < 2*ESR/(Ro/2),
     f"max rel err {err_ds:.2e} vs ESR/(Ro/2) = {ESR/(Ro/2):.2e}")

# ─────────────────────────────────────────────────────────────────────────────
# Gate B — DC gain of the full linearization
# ─────────────────────────────────────────────────────────────────────────────
print("\nB. DC gain d(alpha)/dr from the full model")
Pn = full_plant()             # nominal: VinF 9, VinB 8, Itot 2, r0 0.5, REA 10M
dc = Pn.dcgain()
gate("d(alpha)/dr(0) = 1 (within finite-EA-gain tolerance)", abs(dc - 1) < 1e-2,
     f"dc = {dc:.6f}")
gate("full plant is open-loop stable", Pn.is_stable(),
     f"max Re(p) = {np.max(eigvals(Pn.A).real):.3e}, order {Pn.n}")

# ─────────────────────────────────────────────────────────────────────────────
# Gate C — per-channel voltage-loop crossovers vs §6e datasheet arithmetic
# (single channel + resistive load + droop loop OPEN: T = GEA Zc Kc Zload h1)
# ─────────────────────────────────────────────────────────────────────────────
print("\nC. Voltage-loop crossovers vs system_model.md §6e predictions")
wgrid = np.logspace(2, 6.5, 4000)
for name, Vin_, Co__ in (("FC Vin=9  Co=30u", 9.0, 30e-6), ("FC Vin=9  Co=66u", 9.0, 66e-6),
                         ("BT Vin=7.4 Co=30u", 7.4, 30e-6), ("BT Vin=8.4 Co=66u", 8.4, 66e-6)):
    oneD_ = Vin_/VBUS0
    Ro_ = VBUS0/1.0                              # 1 A channel op point
    wr_ = Ro_*oneD_**2/L
    zc_ = zcomp_ss(10e6)
    Zc_resp = GEA*zc_.freqresp(wgrid)
    sg = 1j*wgrid
    Zload = (Ro_/2)/(1 + sg*(Ro_/2)*Co__)
    Tv = Zc_resp*KCOMP*oneD_*(1 - sg/wr_)*Zload*H1
    idx = np.argmin(np.abs(np.abs(Tv) - 1.0))
    fc_meas = wgrid[idx]/(2*np.pi)
    fc_pred = RC*oneD_*VREF*GEA*KCOMP/(2*np.pi*VBUS0*Co__)
    print(f"     {name}: crossover {fc_meas/1e3:6.2f} kHz  (§6e formula {fc_pred/1e3:6.2f} kHz)")
    gate(f"crossover within 40% of §6e formula ({name})",
         0.6 < fc_meas/fc_pred < 1.4, f"ratio {fc_meas/fc_pred:.2f}")

# ─────────────────────────────────────────────────────────────────────────────
# Gate D — nominal Bode comparison, full vs simplified, design band
# ─────────────────────────────────────────────────────────────────────────────
print("\nD. Nominal Bode comparison (design band <= 1100 rad/s)")
wband = np.logspace(-1, np.log10(1100.0), 120)
wfull = np.logspace(-1, 5, 400)
Gf_n = Pn.freqresp(wband)
Gs_n = simplified_plant().freqresp(wband)
dev_nom = np.max(np.abs(Gf_n - Gs_n)/np.abs(Gs_n))
gate("in-band deviation, full vs simplified nominal < 15%", dev_nom < 0.15,
     f"max dev = {100*dev_nom:.2f}%")

# corner family (K=1; gain uncertainty is the separately-validated STATIC mismatch axis)
corners = [simplified_plant(1.0, td, tr) for td in TD_SET for tr in TAUR_SET]
corner_band = [c.freqresp(wband) for c in corners]

# ─────────────────────────────────────────────────────────────────────────────
# Gate E — envelope study over the operating grid
# ─────────────────────────────────────────────────────────────────────────────
print("\nE. Envelope: full-model family vs simplified corner family")
grid = [(vf, vb, it, r0, co, cb, rea)
        for vf in (9.0, 12.0) for vb in (7.4, 8.4)
        for it in (1.0, 2.0, 4.0) for r0 in (0.3, 0.5, 0.7)
        for co in (30e-6, 66e-6) for cb in (30e-6, 500e-6)
        for rea in (1e6, 10e6, 100e6)]
worst_env, worst_pt, dev_list = 0.0, None, []
full_mag_band = []
for pt in grid:
    P = full_plant(*pt)
    G = P.freqresp(wband)
    full_mag_band.append(np.abs(G))
    best = min(np.max(np.abs(G - Gc_)/np.abs(Gc_)) for Gc_ in corner_band)
    dev_list.append(best)
    if best > worst_env:
        worst_env, worst_pt = best, pt
gate("every grid point within 15% of some simplified corner (in band)",
     worst_env < 0.15,
     f"worst best-corner dev = {100*worst_env:.2f}% at "
     f"(VinF,VinB,Itot,r0,Co,Cbus,REA) = {worst_pt}")
print(f"     median best-corner deviation: {100*np.median(dev_list):.2f}%; "
      f"{len(grid)} grid points")

# ─────────────────────────────────────────────────────────────────────────────
# Gate F — discrete closed loop with the SHIPPED controller
# ─────────────────────────────────────────────────────────────────────────────
print("\nF. Discrete closed loop with the shipped controller (parsed from firmware)")
txt = open(FW_HEADER, encoding="utf-8").read()
Ts_fw = float(re.search(r"SHARE_CTRL_TS_US\s+(\d+)", txt).group(1))*1e-6
kI_fw = float(re.search(r"SHARE_CTRL_KI\s*=\s*([^f;\s]+)f", txt).group(1))
Afilt = float(re.search(r"SHARE_CTRL_MEAS_FILT_A\s*=\s*([^f;\s]+)f", txt).group(1))
sos = []
for row in re.findall(r"\{\s*([^{}]*?)\s*\}", txt):
    v = [float(x) for x in row.replace("f", "").split(",")]
    if len(v) == 5:
        sos.append(v)
assert sos, "failed to parse SOS rows"
print(f"     parsed: Ts={Ts_fw} s, kI={kI_fw:.4f}, filtA={Afilt:.6f}, {len(sos)} SOS")

Rz = tf2ss([1.0], [1.0])
for b0, b1, b2, a1, a2 in sos:
    Rz = ss_series(Rz, tf2ss([b0, b1, b2], [1.0, a1, a2]))
Iz = SS([[1.0]], [[1.0]], [[kI_fw*Ts_fw]], [[kI_fw*Ts_fw/2.0]])
Gc_d = ss_parallel(Iz, Rz)
Hf_d = SS([[Afilt]], [[1.0-Afilt]], [[Afilt]], [[1.0-Afilt]])


def discrete_cl(Pd):
    """Closed loop: e = ref - Hf(alpha), r = Gc e, alpha = Pd r. Returns (Acl, Bcl, Ccl)
    with output alpha. Pd must have D=0."""
    Ap, Bp, Cp = Pd.A, Pd.B, Pd.C
    Ac, Bc, Cc, Dc = Gc_d.A, Gc_d.B, Gc_d.C, Gc_d.D[0, 0]
    Af, Bf, Cf, Df = Hf_d.A, Hf_d.B, Hf_d.C, Hf_d.D[0, 0]
    npp, nc, nf = Pd.n, Gc_d.n, Hf_d.n
    # e = ref - Cf xf - Df Cp xp ;  r = Cc xc + Dc e
    A = np.zeros((npp+nc+nf, npp+nc+nf))
    Bref = np.zeros((npp+nc+nf, 1))
    A[:npp, :npp] = Ap + Bp @ (-Dc*Df*Cp)
    A[:npp, npp:npp+nc] = Bp @ Cc
    A[:npp, npp+nc:] = Bp @ (-Dc*Cf)
    Bref[:npp] = Bp*Dc
    A[npp:npp+nc, :npp] = Bc @ (-Df*Cp)
    A[npp:npp+nc, npp:npp+nc] = Ac
    A[npp:npp+nc, npp+nc:] = Bc @ (-Cf)
    Bref[npp:npp+nc] = Bc
    A[npp+nc:, :npp] = Bf @ Cp
    A[npp+nc:, npp+nc:] = Af
    C = np.zeros((1, npp+nc+nf)); C[0, :npp] = Cp
    return A, Bref, C


def disc_S_peak(Pd):
    wg = np.logspace(0, np.log10(np.pi/Ts_fw*0.999), 500)
    Lz = dfreqresp(Pd, Ts_fw, wg)*dfreqresp(Gc_d, Ts_fw, wg)*dfreqresp(Hf_d, Ts_fw, wg)
    return float(np.max(np.abs(1.0/(1.0 + Lz))))


def step_response(Pd, nsteps=400, amp=0.2):
    Acl, Bcl, Ccl = discrete_cl(Pd)
    x = np.zeros((Acl.shape[0], 1)); out = []
    for _ in range(nsteps):
        out.append((Ccl @ x).item())
        x = Acl @ x + Bcl*amp
    return 0.5 + np.array(out)


# nominal comparison
Pd_full = c2d_zoh(Pn, Ts_fw)
Pd_simp = c2d_zoh(simplified_plant(), Ts_fw)
y_full = step_response(Pd_full)
y_simp = step_response(Pd_simp)
t = np.arange(len(y_full))*Ts_fw
dev_step = np.max(np.abs(y_full - y_simp))
gate("nominal step: full vs simplified overlay within 0.02 share", dev_step < 0.02,
     f"max |diff| = {dev_step:.4f}")
sett = np.where(np.abs(y_full - 0.7) > 0.02*0.2)[0]
t_settle = (sett[-1]+1)*Ts_fw if len(sett) else 0.0
print(f"     full-model 2% settle = {t_settle*1e3:.0f} ms "
      f"(simplified prediction was 22 ms)")

# ramp overlay
def ramp_response(Pd, nsteps=4000, rate=0.05):
    Acl, Bcl, Ccl = discrete_cl(Pd)
    x = np.zeros((Acl.shape[0], 1)); out = []
    for k in range(nsteps):
        out.append((Ccl @ x).item())
        ref = min(0.3, rate*k*Ts_fw)
        x = Acl @ x + Bcl*ref
    return 0.5 + np.array(out)

yr_full = ramp_response(Pd_full)
ramp_err = abs(yr_full[3000] - (0.5 + min(0.3, 0.05*3000*Ts_fw)))
gate("ramp: full-model tracking error -> 0 (T(0)=1 preserved)", ramp_err < 1e-3,
     f"err @ t=3 s = {ramp_err:.2e}")

# grid sweep: stability + worst sensitivity peak
worstS, worstS_pt, nUnstable = 0.0, None, 0
for pt in grid:
    Pd = c2d_zoh(full_plant(*pt), Ts_fw)
    Acl, _, _ = discrete_cl(Pd)
    radius = np.max(np.abs(eigvals(Acl)))
    if radius >= 1.0:
        nUnstable += 1
        continue
    pk = disc_S_peak(Pd)
    if pk > worstS:
        worstS, worstS_pt = pk, pt
gate("discrete CL stable on ALL grid points with the shipped controller",
     nUnstable == 0, f"{len(grid)-nUnstable}/{len(grid)} stable")
gate("worst ||S||inf over the grid comparable to the simplified result (< 2.2)",
     worstS < 2.2, f"worst = {worstS:.3f} at {worstS_pt} "
     f"(simplified 60-corner worst was 1.867)")

# ─────────────────────────────────────────────────────────────────────────────
# Artifacts
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs(FIGDIR, exist_ok=True)
Gf_wide = Pn.freqresp(wfull)
Gs_wide = simplified_plant().freqresp(wfull)
corner_wide = [c.freqresp(wfull) for c in corners]
with open(os.path.join(FIGDIR, "fullorder_bode_overlay.csv"), "w", encoding="utf-8") as f:
    f.write("w_rad_s,full_mag,full_phase_deg,simp_mag,simp_phase_deg,corner_mag_min,corner_mag_max\n")
    cm = np.array([np.abs(g) for g in corner_wide])
    for i in range(len(wfull)):
        f.write(f"{wfull[i]:.6e},{np.abs(Gf_wide[i]):.6e},{np.degrees(np.angle(Gf_wide[i])):.3f},"
                f"{np.abs(Gs_wide[i]):.6e},{np.degrees(np.angle(Gs_wide[i])):.3f},"
                f"{cm[:, i].min():.6e},{cm[:, i].max():.6e}\n")

with open(os.path.join(FIGDIR, "fullorder_envelope.csv"), "w", encoding="utf-8") as f:
    f.write("w_rad_s,full_mag_min,full_mag_max,corner_mag_min,corner_mag_max,simp_nom_mag\n")
    fm = np.array(full_mag_band)
    cmb = np.array([np.abs(g) for g in corner_band])
    for i in range(len(wband)):
        f.write(f"{wband[i]:.6e},{fm[:, i].min():.6e},{fm[:, i].max():.6e},"
                f"{cmb[:, i].min():.6e},{cmb[:, i].max():.6e},{np.abs(Gs_n[i]):.6e}\n")

with open(os.path.join(FIGDIR, "fullorder_step_overlay.csv"), "w", encoding="utf-8") as f:
    f.write("t_s,alpha_full,alpha_simplified\n")
    for i in range(len(t)):
        f.write(f"{t[i]:.4f},{y_full[i]:.6f},{y_simp[i]:.6f}\n")

with open(os.path.join(HERE, "fullorder_metrics.txt"), "w", encoding="utf-8") as f:
    f.write(f"""Full-order TPS61288 model validation metrics (generated)
full-plant order (nominal)      = {Pn.n} states
DC gain d(alpha)/dr             = {dc:.6f}
nominal in-band deviation       = {100*dev_nom:.2f} %  (band <= 1100 rad/s)
worst best-corner deviation     = {100*worst_env:.2f} % at {worst_pt}
median best-corner deviation    = {100*np.median(dev_list):.2f} %  ({len(grid)} grid points)
discrete CL stable              = {len(grid)-nUnstable}/{len(grid)}
worst discrete ||S||inf         = {worstS:.3f} at {worstS_pt}  (simplified: 1.867)
nominal step overlay max |diff| = {dev_step:.4f} share
full-model 2% settle            = {t_settle*1e3:.0f} ms  (simplified: 22 ms)
ramp err @ 3 s                  = {ramp_err:.2e}
""")

print(f"\nartifacts: 3 CSVs + fullorder_metrics.txt")
print("\n" + ("ALL GATES PASSED" if not failures else "FAILURES: " + "; ".join(failures)))
raise SystemExit(1 if failures else 0)
