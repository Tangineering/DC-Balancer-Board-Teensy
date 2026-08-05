#!/usr/bin/env python3
"""full_model_mimo.py — full-order 2-in / 2-out TRUTH model for the MIMO study.

COPIED from controller_design/tps61288_full_model.py @ 51b8962: the parameter
block, `zcomp_ss()`, and the complete `full_plant()` state-space assembly (the
11-state small-signal TPS61288 / droop / bus / INA model documented in
controller_design/full_order_validation.md).  That model is preserved verbatim
below as `full_plant()` so its published baseline behaviour stays reproducible.

ADAPTED / EXTENDED (this file) — three changes, all documented in
mimo_system_model.md §6:

  1. `dv0` operating-point knob.  The original model is structurally matched
     (both channels share VREF and the same divider network), so its no-load
     voltage mismatch is dV0 == 0 and its d(alpha)/d(I_tot) is identically zero.
     dV0 enters the SMALL-SIGNAL model only through the operating-point current
     split: the droop conductances stay set by the commanded r0, but the actual
     split becomes alpha0 = r0 + dv0 r0(1-r0)/(k_d I_tot).  Setting I_F0/I_B0 from
     alpha0 (instead of r0) is the whole change, and it makes the DC coupling
     -dV0 r0(1-r0)/(k_d I_tot^2) emerge ENDOGENOUSLY (gate G1.3b).

  2. Second exogenous input column `dI_load` entering the v_bus node row with
     -1/Cbus, and a second output row `v_hat_bus`.  -> `full_plant_ext()`.

     DEVIATION from the plan spec: the plan also asked for an explicit
     "d(alpha_hat)/d(I_tot) sensitivity term added to the alpha_hat output row".
     That term is NOT added, because it would DOUBLE COUNT.  The full model's
     alpha_hat row, (I_B0 i_F - I_F0 i_B)/I_tot^2, is the exact linearization of
     i_F/(i_F+i_B); a load step moves v_bus, which moves both channel currents
     through their droop load lines, and the resulting d(alpha) is already the
     complete sensitivity.  Adding it again would double it.  Instead the term is
     used as a GATE (validate_mimo_model.py G1.3b): the full model's DC
     d(alpha_hat)/d(I_load) must EQUAL the design plant's analytic
     d(alpha)/d(I_tot).  That is a strictly stronger check than importing the
     number, and it is what actually validates the design plant's coupling row.

  3. A drive branch (VESC Pade(2) + current-loop lag -> k_t*eta_dt*phi/r_t ->
     1/(m_eff s + b_eff)) is SERIES-CONNECTED: its states are appended, its
     linearized bus draw dI_bus (identical linearization to plant_mimo.py) is
     wired into the dI_load column, and its speed output becomes output 2.
     -> `full_plant_mimo()`, 11 + 4 = 15 states, 2 in / 2 out.

Run `<ctrl-venv python> validate_mimo_model.py` for the gate battery.
"""

import numpy as np

from hinf_mimo import SS, tf2ss, pade2, ss_series

import plant_mimo as pm

# ─────────────────────────────────────────────────────────────────────────────
# Parameters — COPIED from controller_design/tps61288_full_model.py @ 51b8962
# (sources: TPS61288 DS §7.5/§9.2.2.5; schematic sheets 1-2 + bodges;
#  controller_design/system_model.md §8)
# ─────────────────────────────────────────────────────────────────────────────
VREF   = 0.6            # V     TPS61288 FB reference (DS §7.5, verified)
GEA    = 180e-6         # S     EA transconductance (DS §7.5)
KCOMP  = 13.5           # A/V   power-stage transconductance (DS §7.5)
L      = 2.2e-6         # H
RC     = 61.2e3         # ohm   compensator (both channels post RC-BT bodge)
CC     = 2e-9           # F
CPP    = 27e-12         # F     COMP pin Cp
RD1    = 215e3          # ohm   FB top (RD1 bodge, 16 V retune; schematic shows 237k)
RD2    = 10e3           # ohm
RINJ   = 53.6e3         # ohm
AV     = 1 + 40.2/10    # OPA197 gain 5.02
KSNS   = 0.1            # V/A   INA253A1
RSH    = 2e-3           # ohm   INA253 internal shunt
W_INA  = 2*np.pi*350e3  # rad/s INA253 bandwidth
RE_MAX = KSNS*AV*RD1/RINJ                 # 2.014 ohm
K_D    = 0.30           # ohm   firmware K_DROOP
VBUS0  = VREF*(1 + RD1/RD2 + RD1/RINJ)    # 15.907 V no-load setpoint
TS     = 1e-3           # s     share-loop period
TD     = 1e-3           # s     ZOH + latch delay (same as simplified nominal)

# FB node superposition gains (op-amp output = low-impedance source)
_P  = RD2*RINJ/(RD2 + RINJ)
H1  = _P/(RD1 + _P)                       # v_bus-side divider
H2  = H1*RD1/RINJ                         # injection gain (h2/h1 = RD1/RINJ exactly)


# COPIED from controller_design/tps61288_full_model.py @ 51b8962, unmodified.
def zcomp_ss(REA):
    """Exact compensation impedance Z_comp(s), strictly proper (2 states, D=0)."""
    num = [RC*CC, 1.0]
    den = [RC*CC*CPP, CPP + CC + RC*CC/REA, 1.0/REA]
    return tf2ss(num, den)


# ─────────────────────────────────────────────────────────────────────────────
# full_plant_ext — COPIED assembly + EXTENSIONS (1) and (2) above.
# states: [x_zcF(2), x_zcB(2), v_oF, v_oB, v_bus, x_inaF, x_inaB, x_pade(2)]
# inputs: [r_hat, dI_load]        outputs: [alpha_hat, v_hat_bus]
# ─────────────────────────────────────────────────────────────────────────────
def full_plant_ext(VinF=9.0, VinB=8.0, Itot=2.0, r0=0.5,
                   Co=30e-6, Cbus=30e-6, REA=10e6, Td=TD, with_pade=True,
                   dv0=0.0):
    # EXTENSION (1): operating-point split reflects the source mismatch dv0.
    # The droop CONDUCTANCES stay set by the commanded r0 (below); only the
    # realized current split moves.  alpha0 is the exact static share law from
    # controller_design/validate_model.py check 1.
    alpha0 = r0 + dv0*r0*(1.0 - r0)/(K_D*Itot)
    if not (1e-6 < alpha0 < 1.0 - 1e-6):
        raise ValueError(f"dv0={dv0} clamps the share at OP (alpha0={alpha0:.4f}); "
                         "the RT1987 blocks one source -- outside the linear model")
    IF0, IB0 = alpha0*Itot, (1.0 - alpha0)*Itot

    ch = []
    for Vin, I0 in ((VinF, IF0), (VinB, IB0)):
        oneD  = Vin/VBUS0                    # (1-D)
        Rint  = VBUS0/I0                     # operating-point load line
        wrhpz = Rint*oneD**2/L               # DS Eq. 10 (rad/s)
        ch.append(dict(oneD=oneD, Rint=Rint, wrhpz=wrhpz, I0=I0))
    ch[0]['g0'] = K_D/(RE_MAX*r0)
    ch[1]['g0'] = K_D/(RE_MAX*(1 - r0))
    ch[0]['dg'] = -K_D/(RE_MAX*r0**2)        # d g_F / d r
    ch[1]['dg'] = +K_D/(RE_MAX*(1 - r0)**2)  # d g_B / d r

    zc = zcomp_ss(REA)                       # shared realization (same RC/CC/CP)
    Azc, Bzc, Czc = zc.A, zc.B.flatten(), GEA*zc.C.flatten()
    nz = 2

    pd = pade2(Td) if with_pade else tf2ss([1.0], [1.0])
    npd = pd.n

    n = 2*nz + 3 + 2 + npd
    A = np.zeros((n, n)); B = np.zeros((n, 2))      # EXTENSION (2): 2 input columns
    iZ = [slice(0, nz), slice(nz, 2*nz)]
    iV = [2*nz, 2*nz+1]                      # v_oF, v_oB
    iB_ = 2*nz + 2                           # v_bus
    iI = [2*nz+3, 2*nz+4]                    # INA states per channel
    iP = slice(2*nz+5, 2*nz+5+npd)

    if npd:
        A[iP, iP] = pd.A
        B[iP.start:iP.stop, 0] = pd.B.flatten()
    Cpd = pd.C.flatten() if npd else np.zeros(0)
    Dpd = pd.D[0, 0]

    for k in (0, 1):
        c = ch[k]
        Kc = KCOMP*c['oneD']
        row_i = np.zeros(n); row_i[iV[k]] = 1.0/RSH; row_i[iB_] = -1.0/RSH

        row_vop = np.zeros(n); row_vop[iI[k]] = AV*c['g0']
        if npd:
            row_vop[iP] += AV*KSNS*c['I0']*c['dg']*Cpd
        vop_D = AV*KSNS*c['I0']*c['dg']*Dpd

        row_u = np.zeros(n); row_u[iV[k]] = -H1
        row_u += -H2*row_vop
        u_D = -H2*vop_D

        A[iZ[k], iZ[k]] = Azc
        A[iZ[k], :] += np.outer(Bzc, row_u)
        B[iZ[k], 0] += Bzc*u_D

        row_iN = np.zeros(n)
        row_iN[iZ[k]] = Kc*(Czc - (Czc @ Azc)/c['wrhpz'])
        cb = float(Czc @ Bzc)
        row_iN += -Kc*cb/c['wrhpz']*row_u
        iN_D = -Kc*cb/c['wrhpz']*u_D

        A[iV[k], :] += (row_iN - row_i)/Co
        A[iV[k], iV[k]] += -1.0/(c['Rint']*Co)
        B[iV[k], 0] += iN_D/Co

        A[iB_, :] += row_i/Cbus

        A[iI[k], :] += W_INA*KSNS*row_i
        A[iI[k], iI[k]] += -W_INA

    # EXTENSION (2): exogenous load current leaves the bus node.
    B[iB_, 1] = -1.0/Cbus

    # outputs: alpha_hat = (IB0 iF - IF0 iB)/Itot^2 ;  v_hat_bus
    rF = np.zeros(n); rF[iV[0]] = 1.0/RSH; rF[iB_] = -1.0/RSH
    rB = np.zeros(n); rB[iV[1]] = 1.0/RSH; rB[iB_] = -1.0/RSH
    C = np.zeros((2, n))
    C[0, :] = (ch[1]['I0']*rF - ch[0]['I0']*rB)/Itot**2
    C[1, iB_] = 1.0
    return SS(A, B, C, np.zeros((2, 2)))


def full_plant(VinF=9.0, VinB=8.0, Itot=2.0, r0=0.5,
               Co=30e-6, Cbus=30e-6, REA=10e6, Td=TD, with_pade=True):
    """The ORIGINAL 1-in/1-out r_hat -> alpha_hat model, bit-for-bit.

    COPIED behaviour from controller_design/tps61288_full_model.py @ 51b8962:
    with dv0 = 0 the extended assembly is identical to the original, so this is
    the original model (verified by gate G1.0 in validate_mimo_model.py).
    """
    P = full_plant_ext(VinF, VinB, Itot, r0, Co, Cbus, REA, Td, with_pade, dv0=0.0)
    return SS(P.A, P.B[:, :1], P.C[:1, :], [[0.0]])


def simplified_plant(K=1.0, Td=TD, taur=1e-4):
    """Design plant WITHOUT tau_f (tau_f is the digital Hf, common to both models).
    COPIED from controller_design/tps61288_full_model.py @ 51b8962."""
    from hinf_mimo import ss_scale
    return ss_scale(ss_series(pade2(Td), tf2ss([1.0], [taur, 1.0])), K)


# ─────────────────────────────────────────────────────────────────────────────
# EXTENSION (3): graft the drive branch -> 2-in / 2-out truth model
# ─────────────────────────────────────────────────────────────────────────────
def full_plant_mimo(op=None, params=None, VinF=9.0, VinB=8.0,
                    Co=30e-6, Cbus=30e-6, REA=10e6, with_bus_output=False):
    """15-state 2x2 truth model.  u = [dr; di_cmd], y = [dalpha_hat; dv]
    (or [dalpha_hat; dv; dv_bus] when with_bus_output=True).

    The OP's I_tot0 / r0 / dV0 set the boost-side operating point; the drive
    branch and its bus-current linearization use exactly the same expressions as
    plant_mimo.py (imported, not re-derived) so the two models cannot drift.

    NOTE: the truth model carries NO tau_f measurement prefilter -- tau_f is a
    digital filter in firmware, common to both models (same convention as
    controller_design/full_order_validation.md).  Compare against
    design_plant(..., tauf=0).
    """
    op = dict(pm.nominal_op() if op is None else op)
    p = dict(pm.nominal_params() if params is None else params)

    base = full_plant_ext(VinF, VinB, op['I_tot0'], op['r0'],
                          Co, Cbus, REA, Td=p['Td'], dv0=op['dV0'])
    nb = base.n

    Dv = pm.vesc_current_path(p)             # 3 states: di_cmd -> di_m
    Mm = pm.vehicle_mech(op, p)              # 1 state:  force -> dv_phys
    nd, nm = Dv.n, Mm.n
    n = nb + nd + nm
    iB = slice(0, nb)
    iD = slice(nb, nb + nd)
    iM = slice(nb + nd, nb + nd + nm)

    KF = pm.force_per_amp(p)
    A_i, A_w, _, _ = pm.bus_current_gains(op, p)
    Aw_v = A_w*p['phi']/p['r_t']

    A = np.zeros((n, n)); B = np.zeros((n, 2))
    A[iB, iB] = base.A
    B[iB, 0:1] = base.B[:, 0:1]              # dr

    A[iD, iD] = Dv.A
    B[iD, 1:2] = Dv.B                        # di_cmd
    row_im = np.zeros(n); row_im[iD] = Dv.C[0]

    A[iM, iM] = Mm.A
    A[iM, :] += Mm.B @ (KF*row_im.reshape(1, n))
    row_v = np.zeros(n); row_v[iM] = Mm.C[0]

    # drive bus draw -> the dI_load column of the base model
    row_Ibus = A_i*row_im + Aw_v*row_v
    A[iB, :] += base.B[:, 1:2] @ row_Ibus.reshape(1, n)

    ny = 3 if with_bus_output else 2
    C = np.zeros((ny, n))
    C[0, iB] = base.C[0, :]                                  # alpha_hat
    C[1, :] = p['K_enc']*p['K_v']*row_v                      # measured speed
    if with_bus_output:
        C[2, iB] = base.C[1, :]                              # v_hat_bus
    return SS(A, B, C, np.zeros((ny, 2)))


if __name__ == "__main__":
    P = full_plant_mimo()
    print(f"full 2x2 truth model: {P.n} states, {P.ny}x{P.nu}")
    print("DC gain:\n", P.dcgain_matrix())
    print("design plant DC:\n", pm.design_plant(pm.nominal_op(),
                                                dict(pm.nominal_params(), tauf=0.0)).dcgain_matrix())
    print(f"stable: {P.is_stable()}   max Re(p) = {np.max(P.poles().real):.3e}")
