#!/usr/bin/env python3
"""validate_mimo_model.py — Phase-1 gate battery for the MIMO plant models.

Gates (plan §8, phase table row 1):
  G1.0  copied full-order model is bit-identical to the published baseline
  G1.1  design_plant G11 block == the shipped SISO design plant (1e-9 rel)
  G1.2  G22 DC gain == K_enc*k_t*eta_dt*phi/(r_t*b_eff)
  G1.3  G12 DC coupling == finite-difference of the static alpha(r, I_tot) map
  G1.3b full-order truth model reproduces the SAME DC coupling endogenously
  G1.4  G21 of the FULL model ~ 0 in-band (verifies the design plant's G21 = 0)
  G1.5  design plant vs full truth model: in-band per-channel deviation < 15%
  G1.6  all 5760 Tier-1 corners well-posed and open-loop stable
  RGA   RGA(0) = I exactly (structural); coupling quantified by other metrics

Exits non-zero on any failure.
Run:  ctrl-venv/Scripts/python.exe validate_mimo_model.py
"""

import os
import sys
import time

import numpy as np

from hinf_mimo import rga, sv
import plant_mimo as pm
import full_model_mimo as fm

HERE = os.path.dirname(os.path.abspath(__file__))
np.set_printoptions(precision=6, suppress=False, linewidth=120)

failures = []
results = []


def gate(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    results.append((name, bool(cond), detail))
    if not cond:
        failures.append(name)


# ─────────────────────────────────────────────────────────────────────────────
# G1.0 — the copied full-order model still equals the published baseline
# ─────────────────────────────────────────────────────────────────────────────
print("G1.0  copied full-order model vs controller_design/tps61288_full_model.py")
_CD = os.path.abspath(os.path.join(HERE, "..", "controller_design"))
baseline_ok, baseline_detail = None, ""
#
# HARD CONSTRAINT: this sub-project must not write anything outside
# controller_design_MIMO/.  The baseline module runs its own gate battery at
# import time AND emits CSVs / fullorder_metrics.txt into controller_design/, and
# importing it normally would also drop a __pycache__ .pyc there.  So instead we
# read its SOURCE, truncate it just before its first gate section, and exec that
# prefix in a throwaway namespace: model definitions only, zero side effects.
#
try:
    _src = open(os.path.join(_CD, "tps61288_full_model.py"), encoding="utf-8").read()
    _cut = _src.index("# Gate A")
    _cut = _src.rindex("# " + "─"*77, 0, _cut)        # start of that banner block
    _ns = {"__name__": "_baseline_full_defs_only", "__file__": os.path.join(_CD, "x.py")}
    _old_path, _old_bc = list(sys.path), sys.dont_write_bytecode
    sys.dont_write_bytecode = True                          # no .pyc anywhere
    sys.path.insert(0, _CD)                                 # for `import hinf_synthesis`
    try:
        exec(compile(_src[:_cut], "<baseline:tps61288_full_model.py>", "exec"), _ns)
    finally:
        sys.path[:] = _old_path
        sys.dont_write_bytecode = _old_bc
    wgrid = np.logspace(-1, 5, 200)
    err = 0.0
    for pt in [(9.0, 8.0, 2.0, 0.5, 30e-6, 30e-6, 10e6),
               (12.0, 7.4, 4.0, 0.3, 66e-6, 500e-6, 1e6)]:
        a = _ns["full_plant"](*pt).freqresp(wgrid)
        b = fm.full_plant(*pt).freqresp(wgrid)
        err = max(err, float(np.max(np.abs(a - b)/np.abs(a))))
    baseline_ok = err < 1e-12
    baseline_detail = f"max rel err {err:.2e}, definitions-only exec (no side effects)"
except Exception as exc:                                   # pragma: no cover
    baseline_ok, baseline_detail = False, f"baseline load failed: {exc!r}"
gate("copied full_plant() reproduces the baseline model exactly",
     baseline_ok, baseline_detail)

op = pm.nominal_op()
p = pm.nominal_params()
G = pm.design_plant(op, p)
print(f"\nnominal design plant: {G.n} states, {G.ny}x{G.nu}, "
      f"K = {pm.share_gain_K(op, p):.6f}, b_eff = {pm.b_eff(op, p):.5f} N*s/m")

# ─────────────────────────────────────────────────────────────────────────────
# G1.1 — G11 == the shipped SISO design plant
# ─────────────────────────────────────────────────────────────────────────────
print("\nG1.1  G11 block == shipped SISO design plant")
from hinf_mimo import tf2ss, pade2, ss_series, ss_scale


def siso_share_plant(K, Td, taur, tauf):
    """COPIED from controller_design/synthesize_controller.py:60-65 @ 51b8962."""
    g = pade2(Td)
    g = ss_series(g, tf2ss([1.0], [taur, 1.0]))
    if tauf > 0:
        g = ss_series(g, tf2ss([1.0], [tauf, 1.0]))
    return ss_scale(g, K)


w = np.logspace(-2, 5, 600)
worst_g11 = 0.0
for o in pm.op_grid():
    for sc in ({}, dict(dV0=-0.4), dict(dV0=0.4), dict(dV0=0.0, tauf=0.0),
               dict(Td=2e-3, taur=20e-6)):
        Gc, oc, pc = pm.corner_plant(o, sc, {})
        K = pm.share_gain_K(oc, pc)
        ref = siso_share_plant(K, pc['Td'], pc['taur'], pc['tauf']).freqresp(w)
        got = Gc.freqresp_matrix(w)[:, 0, 0]
        worst_g11 = max(worst_g11, float(np.max(np.abs(got - ref)/np.abs(ref))))
gate("G11 identical to the SISO plant at the OP-evaluated K (all OPs x 5 corners)",
     worst_g11 < 1e-9, f"max rel err {worst_g11:.3e}")

# K-envelope study.  controller_design/validate_model.py @ 51b8962 states the
# shipped claim precisely: "K in [0.75,1.25] holds for r in [0.3,0.7] at
# I_tot>=2A; widen to [0.55,1.45] at range edges / light load".  Gate exactly
# that claim; REPORT (do not gate) the excursions outside its stated domain.
K_core, K_all, K_infeas = [], [], 0
for o in pm.op_grid():
    for dv in (-0.4, 0.0, 0.4):
        oc = dict(o, dV0=dv)
        if not pm.op_feasible(oc, p):
            K_infeas += 1
            continue
        K = pm.share_gain_K(oc, p)
        K_all.append((K, oc['I_tot0'], oc['r0'], dv))
        if oc['I_tot0'] >= 2.0 and 0.3 <= oc['r0'] <= 0.7:
            K_core.append(K)
print(f"     feasible (OP, dV0) pairs: {len(K_all)}/30 "
      f"({K_infeas} clamped -- see op_feasible())")
print(f"     K envelope, shipped domain (I_tot >= 2 A, r in [0.3,0.7]): "
      f"[{min(K_core):.3f}, {max(K_core):.3f}]")
lo, hi = min(K_all), max(K_all)
print(f"     K envelope, FULL feasible OP set: [{lo[0]:.3f} @ "
      f"(I={lo[1]}, r={lo[2]}, dV0={lo[3]:+}), {hi[0]:.3f} @ "
      f"(I={hi[1]}, r={hi[2]}, dV0={hi[3]:+})]")
gate("K envelope covered by the shipped [0.55, 1.45] set ON ITS STATED DOMAIN "
     "(I_tot >= 2 A, r in [0.3, 0.7])",
     min(K_core) >= 0.55 - 1e-9 and max(K_core) <= 1.45 + 1e-9,
     f"[{min(K_core):.3f}, {max(K_core):.3f}]")
print("     FINDING: outside that domain the OP-implied K leaves [0.55, 1.45] --")
print("     the FC-charge-cruise OP (2 A, r0 = 0.85) gives K in [0.533, 1.467],")
print("     and the light-load 0.5 A OPs reach K = 2.07.  The shipped SISO")
print("     controller was never gated at those points; they are stability-only")
print("     corners here (mimo_system_model.md §7.3).")

# ─────────────────────────────────────────────────────────────────────────────
# G1.2 — G22 DC gain vs hand formula
# ─────────────────────────────────────────────────────────────────────────────
print("\nG1.2  G22 DC gain vs K_enc*k_t*eta_dt*phi/(r_t*b_eff)")
worst_g22 = 0.0
for o in pm.op_grid():
    for dc in pm.drive_corners():
        Gc, oc, pc = pm.corner_plant(o, {}, dc)
        hand = (pc['K_enc']*pc['K_v']*pc['k_t']*pc['eta_dt']*pc['phi']
                / (pc['r_t']*pm.b_eff(oc, pc)))
        got = Gc.dcgain_matrix()[1, 1]
        worst_g22 = max(worst_g22, abs(got - hand)/abs(hand))
gate("G22(0) == hand formula over all OPs x 24 drive corners",
     worst_g22 < 1e-10, f"max rel err {worst_g22:.3e}")
print(f"     nominal G22(0) = {G.dcgain_matrix()[1,1]:.4f} (m/s)/A, "
      f"drive pole = {-pm.b_eff(op,p)/p['m_eff']:.4f} rad/s")

# ─────────────────────────────────────────────────────────────────────────────
# G1.3 — G12 DC coupling vs finite-difference of the static share map
# ─────────────────────────────────────────────────────────────────────────────
print("\nG1.3  G12 DC coupling vs finite-difference of alpha(r, I_tot)")


def alpha_static(r, I_tot, dV0, k_d):
    """COPIED from controller_design/validate_model.py @ 51b8962 (check 1 closed form)."""
    return r + dV0*r*(1.0 - r)/(k_d*I_tot)


worst_c = 0.0
for o in pm.op_grid():
    for sc in pm.share_corners()[::3]:
        for dc in pm.drive_corners()[::5]:
            Gc, oc, pc = pm.corner_plant(o, sc, dc)
            if not pm.op_feasible(oc, pc):
                continue
            # G12(0) = (d alpha / d I_tot) * (d I_bus / d i_cmd)|_DC.  Divide the
            # measured DC coupling by the (independently-known) DC bus-draw gain
            # and compare the remainder against the finite difference.
            A_i, A_w, _, _ = pm.bus_current_gains(oc, pc)
            dv_dim = pm.force_per_amp(pc)/pm.b_eff(oc, pc)       # (m/s) per A of i_m
            dIbus_dc = A_i + A_w*pc['phi']/pc['r_t']*dv_dim
            got = Gc.dcgain_matrix()[0, 1]/dIbus_dc
            h = oc['I_tot0']*1e-6
            fd = (alpha_static(oc['r0'], oc['I_tot0'] + h, oc['dV0'], pc['k_d'])
                  - alpha_static(oc['r0'], oc['I_tot0'] - h, oc['dV0'], pc['k_d']))/(2*h)
            scale = max(abs(fd), 1e-3)
            worst_c = max(worst_c, abs(got - fd)/scale)
gate("G12(0)/(dI_bus/di_cmd) == d(alpha)/d(I_tot) finite difference",
     worst_c < 1e-6, f"max rel err {worst_c:.3e}")
print(f"     nominal d(alpha)/d(I_tot) = {pm.dalpha_dItot(op, p):.6e} share/A; "
      f"G12(0) = {G.dcgain_matrix()[0,1]:.6e} share/A_cmd")

# ─────────────────────────────────────────────────────────────────────────────
# G1.3b — the full-order truth model reproduces the coupling ENDOGENOUSLY
# ─────────────────────────────────────────────────────────────────────────────
print("\nG1.3b full-order model's DC d(alpha_hat)/d(I_load) vs the analytic formula")
# The truth model's DC coupling splits into two parts:
#   (a) an ODD-in-dV0 part -- the source-mismatch coupling the design plant
#       models, which must equal -dV0 r0(1-r0)/(k_d I_tot^2); and
#   (b) an EVEN (dV0-independent) offset that survives at dV0 = 0.  That offset
#       is NOT a modelling error: the two channels are not structurally
#       identical in the truth model (VinF = 9 V vs VinB = 8 V give different
#       (1-D), K_COMP*(1-D) and w_RHPZ) and the error amplifiers have finite DC
#       gain (REA = 10 M), so a load step splits very slightly unevenly even
#       with matched references.  Gate (a) relatively and (b) absolutely.
worst_odd, worst_odd_pt = 0.0, None
worst_even, worst_even_pt = 0.0, None
for I_tot in (0.5, 2.0, 5.0):
    for r0 in (0.3, 0.5, 0.7):
        for cbus in (30e-6, 500e-6):
            o0 = dict(pm.nominal_op(), I_tot0=I_tot, r0=r0, dV0=0.0)
            even = fm.full_plant_ext(Itot=I_tot, r0=r0, Cbus=cbus,
                                     dv0=0.0).dcgain_matrix()[0, 1]
            if abs(even) > worst_even:
                worst_even, worst_even_pt = abs(even), (I_tot, r0, cbus)
            for dv0 in (0.2, 0.4):
                op_p, op_m = dict(o0, dV0=+dv0), dict(o0, dV0=-dv0)
                if not (pm.op_feasible(op_p, p) and pm.op_feasible(op_m, p)):
                    continue
                gp = fm.full_plant_ext(Itot=I_tot, r0=r0, Cbus=cbus,
                                       dv0=+dv0).dcgain_matrix()[0, 1]
                gm = fm.full_plant_ext(Itot=I_tot, r0=r0, Cbus=cbus,
                                       dv0=-dv0).dcgain_matrix()[0, 1]
                got_odd = 0.5*(gp - gm)
                ana_odd = pm.dalpha_dItot(op_p, p)     # analytic value is odd in dV0
                err = abs(got_odd - ana_odd)/abs(ana_odd)
                if err > worst_odd:
                    worst_odd, worst_odd_pt = err, (I_tot, r0, dv0, cbus)
gate("truth model reproduces -dV0 r0(1-r0)/(k_d I_tot^2) endogenously "
     "(odd-in-dV0 part, <1.5%)",
     worst_odd < 0.015, f"max rel err {100*worst_odd:.3f}% at "
                        f"(I_tot,r0,dV0,Cbus)={worst_odd_pt}")
gate("residual dV0-independent coupling offset negligible (<3e-3 share/A)",
     worst_even < 3e-3, f"max |offset| = {worst_even:.2e} share/A at "
                        f"(I_tot,r0,Cbus)={worst_even_pt}")

# ─────────────────────────────────────────────────────────────────────────────
# G1.4 — G21 of the FULL model, in band
# ─────────────────────────────────────────────────────────────────────────────
print("\nG1.4  G21 (dr -> dv) of the full truth model, in band (w <= 100 rad/s)")
wb = np.logspace(-2, np.log10(100.0), 200)
worst_21 = 0.0
De, Du = pm.scaling_matrices()
for o in pm.op_grid()[:9]:
    for dv0 in (-0.4, 0.0, 0.4):
        oc = dict(o, dV0=dv0)
        if not pm.op_feasible(oc, p):
            continue                                   # clamped OP, outside linear model
        Pf = fm.full_plant_mimo(oc, p)
        R = Pf.freqresp_matrix(wb)
        # scaled comparison: both entries in the same physical normalization
        num = np.max(np.abs(R[:, 1, 0])*Du[0, 0]/De[1, 1])
        den = np.max(np.abs(R[:, 1, 1])*Du[1, 1]/De[1, 1])
        worst_21 = max(worst_21, num/den)
gate("scaled ||G21||/||G22|| < 1% in band (full truth model)", worst_21 < 0.01,
     f"max ratio = {worst_21:.3e}")
print("     NOTE: this ratio is EXACTLY zero, and structurally so -- see")
print("     mimo_system_model.md §4.3.  The VESC runs a current loop, so at a")
print("     fixed i_cmd the delivered motor torque is independent of v_bus until")
print("     the duty rail is hit; dr moves v_bus by <= k_d*I_tot ~ 0.6 V about a")
print("     15.9 V bus, nowhere near that rail.  The gate therefore CONFIRMS the")
print("     modelling assumption rather than measuring a small residual.")
# quantify the physical residual that G21=0 discards: the bus excursion caused by dr
Pf3 = fm.full_plant_mimo(op, p, with_bus_output=True)
Rb = Pf3.freqresp_matrix(np.array([1e-3]))
print(f"     informational: |dv_bus/dr|(DC) = {abs(Rb[0,2,0]):.4f} V per unit r "
      f"({100*abs(Rb[0,2,0])*0.35/fm.VBUS0:.3f}% of bus over the +-0.35 r span)")

# ─────────────────────────────────────────────────────────────────────────────
# G1.5 — design plant vs full truth model, in-band envelope
# (methodology mirrors controller_design/full_order_validation.md §2: compare
#  magnitude/phase over the design band, report the max relative deviation)
# ─────────────────────────────────────────────────────────────────────────────
print("\nG1.5  design plant vs full truth model, per channel, w <= 200 rad/s")
wband = np.logspace(-2, np.log10(200.0), 200)
p_nof = dict(p, tauf=0.0)          # tau_f is the DIGITAL filter, absent from both
Gd = pm.design_plant(op, p_nof)
Pf = fm.full_plant_mimo(op, p_nof)
Rd = Gd.freqresp_matrix(wband)
Rf = Pf.freqresp_matrix(wband)
chan_dev = {}
for (i, j, nm) in ((0, 0, "G11 share"), (0, 1, "G12 coupling"), (1, 1, "G22 drive")):
    d = np.max(np.abs(Rf[:, i, j] - Rd[:, i, j])/np.abs(Rd[:, i, j]))
    chan_dev[nm] = float(d)
    print(f"     {nm:15s} max in-band deviation = {100*d:6.3f} %")
gate("nominal per-channel deviation < 15%", max(chan_dev.values()) < 0.15,
     ", ".join(f"{k}={100*v:.2f}%" for k, v in chan_dev.items()))

# envelope over the operating grid (report, gate at 15%)
worst_env, worst_env_pt, worst_env_ch = 0.0, None, None
for o in pm.op_grid():
    for dv0 in (-0.4, 0.0, 0.4):
        for cbus in (30e-6, 500e-6):
            oc = dict(o, dV0=dv0)
            if not pm.op_feasible(oc, p_nof):
                continue
            Pfe = fm.full_plant_mimo(oc, p_nof, Cbus=cbus)
            Gde = pm.design_plant(oc, p_nof)
            Rfe = Pfe.freqresp_matrix(wband)
            Rde = Gde.freqresp_matrix(wband)
            for (i, j, nm) in ((0, 0, "G11"), (0, 1, "G12"), (1, 1, "G22")):
                den = np.abs(Rde[:, i, j])
                if np.max(den) < 1e-14:
                    continue
                d = float(np.max(np.abs(Rfe[:, i, j] - Rde[:, i, j])/np.maximum(den, 1e-14)))
                if d > worst_env:
                    worst_env, worst_env_pt, worst_env_ch = d, (oc['I_tot0'], oc['r0'], dv0, cbus), nm
gate("envelope over OP grid x dV0 x Cbus < 15%", worst_env < 0.15,
     f"worst {100*worst_env:.2f}% on {worst_env_ch} at "
     f"(I_tot,r0,dV0,Cbus)={worst_env_pt}")

# ─────────────────────────────────────────────────────────────────────────────
# G1.6 — Tier-1 corner sweep
# ─────────────────────────────────────────────────────────────────────────────
print("\nG1.6  Tier-1 corner sweep (10 OPs x 24 share x 24 drive = 5760)")
t0 = time.time()
n_corner, n_bad, n_skip, worst_re, worst_re_pt = 0, 0, 0, -np.inf, None
for o, sc, dc, feas in pm.tier1_corners():
    if not feas:
        n_skip += 1
        continue
    Gc, oc, pc = pm.corner_plant(o, sc, dc)
    ev = Gc.poles()
    mx = float(np.max(ev.real)) if ev.size else -np.inf
    n_corner += 1
    if mx > worst_re:
        worst_re, worst_re_pt = mx, (oc['I_tot0'], oc['r0'], oc['dV0'], pc['tauf'],
                                     pc['pole_factor'])
    if not np.all(np.isfinite(Gc.A)) or mx >= 1e-6:
        n_bad += 1
dt = time.time() - t0
gate("all Tier-1 corners well-posed and open-loop stable (Re(p) < 1e-6)",
     n_bad == 0 and n_corner + n_skip == 5760,
     f"{n_corner - n_bad}/{n_corner} feasible OK ({n_skip} clamped, skipped), "
     f"worst Re(p) = {worst_re:.4e} at "
     f"(I_tot,r0,dV0,tauf,pole_f)={worst_re_pt}")
print(f"     runtime {dt:.1f} s ({1e3*dt/max(n_corner,1):.2f} ms/corner); "
      f"{n_skip} of 5760 skipped as clamped operating points")

# ─────────────────────────────────────────────────────────────────────────────
# RGA / coupling quantification
# ─────────────────────────────────────────────────────────────────────────────
print("\nRGA  relative gain array and coupling metrics")
worst_rga_zero, worst_rga_dv = 0.0, 0.0
worst_dv_pt = None
for o in pm.op_grid():
    for dv0 in (-0.4, 0.0, 0.4):
        if not pm.op_feasible(dict(o, dV0=dv0), p):
            continue
        Gc = pm.design_plant(dict(o, dV0=dv0), p)
        R = rga(Gc.dcgain_matrix())
        dep = float(np.max(np.abs(R - np.eye(2))))
        if dv0 == 0.0:
            worst_rga_zero = max(worst_rga_zero, dep)
        elif dep > worst_rga_dv:
            worst_rga_dv, worst_dv_pt = dep, (o['I_tot0'], o['r0'], dv0)
gate("RGA(0) = I exactly at dV0 = 0 corners", worst_rga_zero < 1e-12,
     f"max |RGA - I| = {worst_rga_zero:.2e}")
print(f"     max |RGA(0) - I| over dV0 = +-0.4 corners: {worst_rga_dv:.2e} "
      f"at {worst_dv_pt}")
print("     -> RGA is IDENTICALLY I for every corner: the design plant is")
print("        upper-triangular, and RGA(T) = I for ANY triangular T regardless")
print("        of the off-diagonal magnitude.  RGA is therefore BLIND to this")
print("        coupling and must not be used as the coupling metric here")
print("        (mimo_system_model.md §5).  The informative metrics are:")

wc = np.logspace(-2, 3, 200)
rows = []
for o in pm.op_grid():
    for dv0 in (-0.4, 0.4):
        if not pm.op_feasible(dict(o, dV0=dv0), p):
            continue
        Gs = pm.scaled_plant(op=dict(o, dV0=dv0), params=p)
        R = Gs.freqresp_matrix(wc)
        ratio = float(np.max(np.abs(R[:, 0, 1])/np.maximum(np.abs(R[:, 0, 0]), 1e-14)))
        s = sv(Gs, wc)
        cond = float(np.max(s[:, 0]/np.maximum(s[:, -1], 1e-300)))
        rows.append((o['I_tot0'], o['r0'], dv0, ratio, cond))
rows.sort(key=lambda t: -t[3])
print("        I_tot  r0    dV0    max|Gs12|/|Gs11|   max cond(Gs)")
for r_ in rows[:5]:
    print(f"        {r_[0]:5.1f} {r_[1]:5.2f} {r_[2]:+5.1f}   {r_[3]:16.4f}   {r_[4]:12.3e}")
print(f"        ... {len(rows)} (OP, dV0) pairs; worst scaled coupling ratio "
      f"{rows[0][3]:.4f}")

# ─────────────────────────────────────────────────────────────────────────────
# summary
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*78)
print(f"{'GATE':<62}{'RESULT'}")
print("-"*78)
for name, ok, _ in results:
    print(f"{name[:60]:<62}{'PASS' if ok else 'FAIL'}")
print("="*78)
print("ALL GATES PASSED" if not failures else "FAILURES: " + "; ".join(failures))
sys.exit(1 if failures else 0)
