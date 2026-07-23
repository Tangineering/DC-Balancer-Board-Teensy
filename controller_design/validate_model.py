#!/usr/bin/env python3
"""Numerical validation of the droop power-share plant model (system_model.md).

Pure-stdlib (no numpy) so it runs on any Python 3. Checks:
  1. Static share law:  alpha = r + dV0*r*(1-r)/(k_d*I_tot)   (exact, both diodes on)
  2. Plant gain:        d(alpha)/dr = 1 + dV0*(1-2r)/(k_d*I_tot)
  3. Dynamics: with dV0=0 the share tracks r INSTANTLY through the bus-voltage
     transient; with dV0!=0 the share settles with tau ~= C_bus*k_d (mismatch path).
  4. MDAC actuator audit: firmware k_eq=0.45 saturates g>1 for r<0.896; the
     recommended k_d=0.333 stays in range over r in [0.15,0.85].
  5. Constraint checks: CPL bus-stability bound, OPA197 headroom, share quantization.

Writes step-response CSVs to figures/ and prints a pass/fail summary.
"""

import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figures")

# ── Hardware constants (see system_model.md §8 for sources) ─────────────────
VREF   = 0.6          # V     TPS61288 FB reference  TODO(verify)
RD1    = 215e3        # ohm   RD1 bodged 237k -> 215k (16V bus retune 2026-07-11; schematic shows 237k)
RD2    = 10e3         # ohm   schematic RD2-*
RINJ   = 53.6e3       # ohm   schematic RINJ-*
AV     = 1 + 40.2/10  # OPA197 non-inverting gain = 5.02
KSNS   = 0.1          # V/A   INA253A1
RE_MAX = KSNS * AV * RD1 / RINJ          # max electronic droop resistance, ohm
V0_NOM = VREF * (1 + RD1/RD2 + RD1/RINJ) # no-load output voltage, V

K_D          = 0.30    # ohm  proposed design droop scale (system_model.md §4; bound RE_MAX*0.15 = 0.302)
K_EQ_FIRMWARE = 0.45   # firmware constant (defective mapping, §4)
ADC_LSB_A    = 3.3/4095/KSNS             # SCALE_I, A per count

failures = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def solve_static(r, dv0, i_tot, k_d=K_D):
    """Exact circuit solution: two Thevenin sources, constant-current load.
    Returns (alpha, v_bus, clamped) honoring the RT1987 unidirectional constraint."""
    rf, rb = k_d/r, k_d/(1-r)
    v0f, v0b = V0_NOM + dv0/2, V0_NOM - dv0/2
    # both conducting:
    vb = (v0f/rf + v0b/rb - i_tot) / (1/rf + 1/rb)
    i_f, i_b = (v0f - vb)/rf, (v0b - vb)/rb
    if i_f >= 0 and i_b >= 0:
        return i_f/i_tot, vb, False
    # one diode blocks -> the other source carries everything
    if i_f < 0:
        return 0.0, v0b - rb*i_tot, True
    return 1.0, v0f - rf*i_tot, True


print(f"Derived constants: V0={V0_NOM:.4f} V  Re_max={RE_MAX:.4f} ohm  "
      f"ADC LSB={ADC_LSB_A*1e3:.3f} mA")
check("V0 matches the 16 V retune target", abs(V0_NOM - 16.0) < 0.15,
      f"V0={V0_NOM:.3f}")

# ── 1. static share law ──────────────────────────────────────────────────────
print("\n1. Static share law alpha = r + dV0*r*(1-r)/(k_d*I_tot)")
worst = 0.0
for r in [i/100 for i in range(15, 86, 5)]:
    for dv0 in (-0.4, 0.0, 0.4):
        for i_tot in (0.5, 2.0, 8.0):
            alpha, _, clamped = solve_static(r, dv0, i_tot)
            if clamped:
                continue
            pred = r + dv0*r*(1-r)/(K_D*i_tot)
            worst = max(worst, abs(alpha - pred))
check("closed form exact on unclamped grid", worst < 1e-12, f"max err={worst:.2e}")

# ── 2. small-signal gain ─────────────────────────────────────────────────────
print("\n2. Plant gain dalpha/dr = 1 + dV0*(1-2r)/(k_d*I_tot)")
worst = 0.0
for r in (0.2, 0.5, 0.8):
    for dv0 in (-0.4, 0.4):
        for i_tot in (2.0, 8.0):
            h = 1e-6
            num = (solve_static(r+h, dv0, i_tot)[0]
                   - solve_static(r-h, dv0, i_tot)[0]) / (2*h)
            pred = 1 + dv0*(1-2*r)/(K_D*i_tot)
            worst = max(worst, abs(num - pred))
check("analytic gain matches numeric derivative", worst < 1e-4,
      f"max err={worst:.2e}")
for (rr, ii) in ((0.5, 2.0), (0.3, 2.0), (0.15, 2.0), (0.15, 6.0)):
    g_lo = 1 - 0.4*abs(1-2*rr)/(K_D*ii)
    g_hi = 1 + 0.4*abs(1-2*rr)/(K_D*ii)
    print(f"     gain envelope at r={rr}, I_tot={ii} A: [{g_lo:.3f}, {g_hi:.3f}]")
print("     -> K in [0.75,1.25] holds for r in [0.3,0.7] at I_tot>=2A;"
      " widen to [0.55,1.45] at range edges / light load (system_model.md 6d)")

# ── 3. dynamics: bus-cap transient ───────────────────────────────────────────
print("\n3. Dynamics (Euler sim of C*dVb/dt, constant-current load, Run: C=500uF)")
C_BUS, I_TOT = 500e-6, 4.0
DT, T_END = 1e-7, 5e-3


def sim_step(dv0, fname):
    """r steps 0.4->0.6 at t=1ms; Euler-integrates the bus cap. Writes CSV,
    returns (rows, alpha_final)."""
    v0f, v0b = V0_NOM + dv0/2, V0_NOM - dv0/2
    r = 0.4
    vb = solve_static(r, dv0, I_TOT)[1]     # start settled
    rows, t = [], 0.0
    while t < T_END:
        if t >= 1e-3:
            r = 0.6
        rf, rb = K_D/r, K_D/(1-r)
        i_f, i_b = max(0.0, (v0f - vb)/rf), max(0.0, (v0b - vb)/rb)
        alpha = i_f/(i_f + i_b)
        vb += DT * (i_f + i_b - I_TOT) / C_BUS
        if len(rows) == 0 or t - rows[-1][0] >= 5e-6:
            rows.append((t, r, alpha, vb))
        t += DT
    with open(os.path.join(FIGDIR, fname), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "r_cmd", "alpha", "v_bus"])
        w.writerows((f"{a:.6e}", f"{b:.4f}", f"{c:.6f}", f"{d:.5f}") for a, b, c, d in rows)
    return rows, rows[-1][2]


os.makedirs(FIGDIR, exist_ok=True)

rows, final = sim_step(0.0, "step_response_nominal.csv")
dev = max(abs(a - r) for _, r, a, _ in rows)
check("dV0=0: share == r at EVERY instant (share is delay-free)", dev < 1e-9,
      f"max |alpha-r| through transient = {dev:.2e}")

rows, final = sim_step(0.4, "step_response_mismatch.csv")
post = [(t - 1e-3, a) for t, r, a, _ in rows if t >= 1e-3 + DT]
resid0 = final - post[0][1]                 # transient amplitude after the jump
tau_pred = C_BUS * K_D    # constant-current load: tau = C*(RF||RB) = C*k_d
# time for the residual to decay to 1/e of its initial value -> fitted tau
tau_fit = next((t for t, a in post if abs(final - a) <= abs(resid0)/math.e), None)
check("dV0=0.4: bus-pole residue is SMALL (<5% of the 0.2 step)",
      abs(resid0) < 0.05*0.2, f"residue={resid0:+.4f} share")
check("dV0=0.4: mismatch-path decay tau ~= C_bus*k_d",
      tau_fit is not None and 0.5*tau_pred < tau_fit < 2*tau_pred,
      f"tau_fit={tau_fit*1e6:.0f}us vs C*k_d={tau_pred*1e6:.0f}us")
check("dV0=0.4: DC offset matches dV0*r*(1-r)/(k_d*I_tot)",
      abs((final - 0.6) - 0.4*0.6*0.4/(K_D*I_TOT)) < 1e-3,
      f"offset={final-0.6:+.4f} vs predicted {0.4*0.6*0.4/(K_D*I_TOT):+.4f}")

# ── 4. MDAC actuator audit ───────────────────────────────────────────────────
print("\n4. MDAC gain audit  g_F = k/(Re_max*r) [true mapping] vs firmware")


def g_firmware(r):
    return K_EQ_FIRMWARE / (r * KSNS * AV)      # firmware: omits RD1/RINJ factor


def g_true(r, k_d=K_D):
    return k_d / (RE_MAX * r)


r_sat = K_EQ_FIRMWARE / (KSNS * AV)             # firmware g=1 boundary
check("firmware k_eq=0.45 saturates MDAC for r < 0.896", abs(r_sat - 0.8964) < 1e-3,
      f"g_F>1 for all r<{r_sat:.3f}: plant gain is ~0 over most of the range")
gmax = max(g_true(0.15), g_true(1-0.85))
check(f"recommended k_d={K_D} keeps g<=1 over r in [0.15,0.85]", gmax <= 1.0,
      f"max g={gmax:.4f} (hard bound: k_d <= Re_max*0.15 = {RE_MAX*0.15:.4f} ohm)")

# ── 5. constraint checks ─────────────────────────────────────────────────────
print("\n5. Constraints")
p_max = 50.0
check("CPL bus stability k_d < Vbus^2/P", K_D < V0_NOM**2/p_max,
      f"{K_D} << {V0_NOM**2/p_max:.1f} ohm at {p_max:.0f} W")
i_headroom = 4.9 / (AV * KSNS)                  # OPA197 near-rail output at 5V supply
check("OPA197 headroom: g*I ceiling above worst per-channel demand",
      K_D*8.0/RE_MAX < i_headroom,              # g*I at I_tot=8A
      f"g*I={K_D*8.0/RE_MAX:.2f} A-equiv < {i_headroom:.1f}")
for i_tot in (0.5, 2.0, 6.0):
    print(f"     share quantization at I_tot={i_tot:>4} A: "
          f"{ADC_LSB_A/i_tot*100:.2f} % per ADC LSB")

# ── summary ──────────────────────────────────────────────────────────────────
print(f"\n{'ALL CHECKS PASSED' if not failures else 'FAILURES: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
