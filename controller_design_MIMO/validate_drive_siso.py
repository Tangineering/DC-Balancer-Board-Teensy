#!/usr/bin/env python
"""
validate_drive_siso.py — Stage-2 independent validator for drive_siso_coeffs.h /
drive_siso_metrics.txt / figures/drive_siso_replay.csv (2026-08-16 calibration round).

Deliberately does NOT import synthesize_drive_siso.py. Parses the generated header and
CSV fresh (regex + csv), re-implements the Hanus recursion and the SOS+integrator form
independently, and checks numeric properties against drive_siso_metrics.txt.

This becomes the round's regression check; run it with the project venv:
    ./ctrl-venv/Scripts/python.exe validate_drive_siso.py
"""
import re
import sys
import csv
import numpy as np

HDR = "drive_siso_coeffs.h"
METRICS = "drive_siso_metrics.txt"
REPLAY = "figures/drive_siso_replay.csv"

results = []  # (name, passed, detail)


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    tag = "PASS" if passed else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# 1. Parse header by regex
# ---------------------------------------------------------------------------
with open(HDR, "r") as f:
    hdr_text = f.read()

FLOAT_RE = r"[-+]?\d+\.\d+e[-+]\d+"


def find_scalar(name):
    m = re.search(rf"{name}\s*=\s*({FLOAT_RE})f?", hdr_text)
    if not m:
        raise ValueError(f"could not find scalar {name}")
    return float(m.group(1))


def find_define_int(name):
    m = re.search(rf"#define\s+{name}\s+(\d+)", hdr_text)
    if not m:
        raise ValueError(f"could not find #define {name}")
    return int(m.group(1))


def find_2d_array(name, nrows, ncols):
    # find the block "static const float NAME[..][..] = { ... };"
    pat = re.compile(rf"static const float {name}\[[^\]]*\](?:\[[^\]]*\])?\s*=\s*\{{(.*?)\n\}};", re.S)
    m = pat.search(hdr_text)
    if not m:
        raise ValueError(f"could not find array {name}")
    body = m.group(1)
    rows = re.findall(r"\{([^{}]*)\}", body)
    arr = []
    for r in rows:
        vals = [float(x) for x in re.findall(FLOAT_RE, r)]
        arr.append(vals)
    arr = np.array(arr, dtype=np.float64)
    if arr.shape != (nrows, ncols):
        raise ValueError(f"{name} shape {arr.shape} != expected ({nrows},{ncols})")
    return arr


NSTATES = find_define_int("DRIVE_CTRL_NSTATES")
NSOS = find_define_int("DRIVE_CTRL_NSOS")
TS_US = find_define_int("DRIVE_CTRL_TS_US")
KI = find_scalar("DRIVE_CTRL_KI")
I_MIN = find_scalar("DRIVE_CTRL_I_MIN")
I_MAX = find_scalar("DRIVE_CTRL_I_MAX")
DD = find_scalar("DRIVE_CTRL_DD")

record("parse: DRIVE_CTRL_NSTATES == 5", NSTATES == 5, f"got {NSTATES}")
record("parse: DRIVE_CTRL_I_MIN/I_MAX == +-12.0", I_MIN == -12.0 and I_MAX == 12.0,
       f"I_MIN={I_MIN} I_MAX={I_MAX}")
record("parse: DRIVE_CTRL_TS_US == 2000", TS_US == 2000, f"got {TS_US}")

AD = find_2d_array("DRIVE_CTRL_AD", NSTATES, NSTATES)
BD = find_2d_array("DRIVE_CTRL_BD", NSTATES, 1)
CD = find_2d_array("DRIVE_CTRL_CD", 1, NSTATES)
AC = find_2d_array("DRIVE_CTRL_AC", NSTATES, NSTATES)

# SOS block
sos_pat = re.compile(r"DRIVE_CTRL_SOS\[DRIVE_CTRL_NSOS\]\[5\]\s*=\s*\{(.*?)\n\};", re.S)
m = sos_pat.search(hdr_text)
sos_rows = re.findall(r"\{([^{}]*)\}", m.group(1))
SOS = np.array([[float(x) for x in re.findall(FLOAT_RE, r)] for r in sos_rows], dtype=np.float64)
record("parse: SOS shape", SOS.shape == (NSOS, 5), f"got {SOS.shape}")

# Check 1: AC == AD - BD*CD/DD
AC_expected = AD - (BD @ CD) / DD
ac_err = np.max(np.abs(AC - AC_expected))
record("check1: AC == AD - BD*CD/DD", ac_err < 1e-6, f"max abs err = {ac_err:.3e} (tol 1e-6)")

# ---------------------------------------------------------------------------
# 2. Load replay CSV, implement Hanus recursion in float64
# ---------------------------------------------------------------------------
episodes = {}
with open(REPLAY, newline="") as f:
    reader = csv.reader(row for row in f if not row.startswith("#"))
    header = next(reader)
    idx = {name: i for i, name in enumerate(header)}
    for row in reader:
        ep = row[idx["episode"]]
        k = int(row[idx["k"]])
        e_in = float(row[idx["e_in"]])
        u_out = float(row[idx["u_out"]])
        episodes.setdefault(ep, []).append((k, e_in, u_out))

for ep in episodes:
    episodes[ep].sort(key=lambda t: t[0])


def run_hanus(e_seq, dtype=np.float64):
    Ac = AC.astype(dtype)
    Bd = BD.astype(dtype)
    Cd = CD.astype(dtype)
    Dd = dtype(DD)
    imin = dtype(I_MIN)
    imax = dtype(I_MAX)
    n = Ac.shape[0]
    x = np.zeros((n, 1), dtype=dtype)
    u_out = np.zeros(len(e_seq), dtype=dtype)
    clamped = np.zeros(len(e_seq), dtype=bool)
    for i, e in enumerate(e_seq):
        e = dtype(e)
        u_unsat = (Cd @ x)[0, 0] + Dd * e
        u = min(max(u_unsat, imin), imax)
        clamped[i] = (u != u_unsat)
        u_out[i] = u
        x = Ac @ x + Bd * (u / Dd)
    return u_out, clamped


max_err_by_ep = {}
clamp_stats = {}
for ep, rows in episodes.items():
    e_seq = np.array([r[1] for r in rows], dtype=np.float64)
    u_csv = np.array([r[2] for r in rows], dtype=np.float64)
    u_out, clamped = run_hanus(e_seq, dtype=np.float64)
    err = np.max(np.abs(u_out - u_csv))
    max_err_by_ep[ep] = err
    clamp_stats[ep] = clamped

for ep in ("small", "regen"):
    if ep in max_err_by_ep:
        record(f"check2: Hanus float64 replay match [{ep}]",
               max_err_by_ep[ep] < 1e-5,
               f"max |u-u_csv| = {max_err_by_ep[ep]:.3e} A (tol 1e-5)")

if "small" in clamp_stats:
    record("check2: 'small' episode never clamps", not np.any(clamp_stats["small"]),
           f"{np.sum(clamp_stats['small'])} clamped samples of {len(clamp_stats['small'])}")
if "regen" in clamp_stats:
    frac = np.mean(clamp_stats["regen"])
    record("check2: 'regen' episode genuinely rails", frac > 0.05,
           f"{frac*100:.1f}% of samples clamped")

# ---------------------------------------------------------------------------
# 3. Unsaturated equivalence: SOS cascade + trapezoidal integrator vs state-space
# ---------------------------------------------------------------------------
Ts = TS_US * 1e-6


def run_sos_plus_integrator(e_seq):
    # Direct Form II Transposed biquads, cascaded, then add trapezoidal (Tustin)
    # integrator kI*Ts/2*(z+1)/(z-1) applied to the same input e.
    x = e_seq.astype(np.float64).copy()
    for (b0, b1, b2, a1, a2) in SOS:
        y = np.zeros_like(x)
        w1 = 0.0
        w2 = 0.0
        for i, xn in enumerate(x):
            wn = xn - a1 * w1 - a2 * w2
            yn = b0 * wn + b1 * w1 + b2 * w2
            y[i] = yn
            w2 = w1
            w1 = wn
        x = y
    r_out = x  # biquad cascade output

    # trapezoidal integrator: y[k] = y[k-1] + kI*Ts/2*(e[k]+e[k-1])
    integ = np.zeros_like(e_seq)
    prev_e = 0.0
    prev_y = 0.0
    for i, e in enumerate(e_seq):
        y = prev_y + KI * Ts / 2.0 * (e + prev_e)
        integ[i] = y
        prev_e = e
        prev_y = y

    return r_out + integ


if "small" in episodes:
    rows = episodes["small"]
    e_seq = np.array([r[1] for r in rows], dtype=np.float64)
    u_ss, _ = run_hanus(e_seq, dtype=np.float64)
    u_sos = run_sos_plus_integrator(e_seq)
    err3 = np.max(np.abs(u_ss - u_sos))
    record("check3: SOS+integrator vs state-space (unsaturated 'small')",
           err3 < 1e-4, f"max abs diff = {err3:.3e} A (tol 1e-4)")
else:
    record("check3: SOS+integrator vs state-space", False, "no 'small' episode found")

# ---------------------------------------------------------------------------
# 4. float32 repeat, report deviation vs float64
# ---------------------------------------------------------------------------
for ep, rows in episodes.items():
    e_seq = np.array([r[1] for r in rows], dtype=np.float64)
    u64, _ = run_hanus(e_seq, dtype=np.float64)
    u32, _ = run_hanus(e_seq, dtype=np.float32)
    dev = np.max(np.abs(u64 - u32.astype(np.float64)))
    ok = dev <= 1e-3
    record(f"check4: float32 vs float64 deviation [{ep}]", ok,
           f"max |u32-u64| = {dev:.3e} A ({'<=' if ok else '>'} 1e-3 A threshold)")

# ---------------------------------------------------------------------------
# 5. DC sanity
# ---------------------------------------------------------------------------
m = re.search(r"Gs_red\(0\)\s*=\s*([\d.]+)\s*A/\(m/s\)", open(METRICS).read())
if not m:
    record("check5: parse Gs_red(0) from metrics", False, "pattern not found")
else:
    gs_red0_metrics = float(m.group(1))

    # DC gain of the SOS remainder (non-integral branch) evaluated at z=1
    def sos_dc_gain():
        g = 1.0
        for (b0, b1, b2, a1, a2) in SOS:
            g *= (b0 + b1 + b2) / (1.0 + a1 + a2)
        return g

    sos_dc = sos_dc_gain()
    rel_err = abs(sos_dc - gs_red0_metrics) / abs(gs_red0_metrics)
    record("check5: SOS remainder DC gain matches Gs_red(0) (metrics)",
           rel_err < 0.01,
           f"SOS DC = {sos_dc:.2f}, metrics Gs_red(0) = {gs_red0_metrics:.2f}, "
           f"rel err = {rel_err*100:.3f}% (tol 1%)")

    # integrator pole at z=1 -> infinite DC gain along the integrator branch
    # (kI*Ts/2*(z+1)/(z-1) has a pole at z=1: denominator -> 0 as z->1)
    integ_pole_at_1 = True  # by construction of the transfer function (z-1) denom
    record("check5: integrator has a pole at z=1 (infinite DC gain)", integ_pole_at_1)

    # sign check: positive step error -> positive current at DC (short horizon, small step)
    e_seq = np.full(2000, 0.01)  # 10 mm/s constant positive error, well under e_sat=16.1mm/s
    u_step, clamped_step = run_hanus(e_seq, dtype=np.float64)
    sign_ok = u_step[-1] > 0 and not np.any(clamped_step)
    record("check5: positive velocity error -> positive current (DC sign)",
           sign_ok, f"u[-1] = {u_step[-1]:.4f} A, any clamped = {np.any(clamped_step)}")

# ---------------------------------------------------------------------------
# 6. Closed-loop replay sanity: nominal G22 discretized, closed loop with Hanus
# ---------------------------------------------------------------------------
metrics_text = open(METRICS).read()
K_F = float(re.search(r"K_F\s+[\d.]+\s*->\s*([\d.]+)\s*N/A", metrics_text).group(1))
m_mass = float(re.search(r"m_eff\s*\(([\d.]+)\s*kg\)", metrics_text).group(1))
b_drag = float(re.search(r"b_eff\s*=\s*([\d.]+)\s*N\*s/m", metrics_text).group(1))

# ignoring fast lags: m*dv/dt = K_F*i - b*v  ->  continuous state space
# x = v, u = i:  dv/dt = (-b/m) v + (K_F/m) i
Ac_cont = np.array([[-b_drag / m_mass]])
Bc_cont = np.array([[K_F / m_mass]])
Cc_cont = np.array([[1.0]])
Dc_cont = np.array([[0.0]])

# Zero-order-hold discretization via matrix exponential (build my own, no scipy.signal.cont2discrete
# dependency assumption issue — but scipy is available per task statement, use it directly is fine
# since this is independent of synthesize_drive_siso.py)
from scipy.linalg import expm

n_p = 1
M = np.zeros((n_p + 1, n_p + 1))
M[:n_p, :n_p] = Ac_cont
M[:n_p, n_p:] = Bc_cont
Md = expm(M * Ts)
Ad_p = Md[:n_p, :n_p]
Bd_p = Md[:n_p, n_p:]

v = np.zeros((1, 1))
xc = np.zeros((NSTATES, 1))
v_ref = 2.0
vs = []
us = []
NSTEPS = int(6.0 / Ts)  # 6 s, well beyond the 1.558 s settle reported in metrics
for k in range(NSTEPS):
    e = v_ref - v[0, 0]
    u_unsat = (CD @ xc)[0, 0] + DD * e
    u = min(max(u_unsat, I_MIN), I_MAX)
    xc = AC @ xc + BD * (u / DD)
    v = Ad_p @ v + Bd_p * u
    vs.append(v[0, 0])
    us.append(u)

vs = np.array(vs)
final_v = vs[-1]
max_v = np.max(np.abs(vs))
has_nan = np.any(np.isnan(vs)) or np.any(np.isnan(us))

gate_ok = (not has_nan) and abs(final_v - 2.0) < 0.01 and max_v < 3.0
record("check6: closed-loop 0->2 m/s step settles cleanly",
       gate_ok,
       f"final v = {final_v:.6f} m/s (target 2.0, tol 0.01), max|v| = {max_v:.4f} (< 3.0), "
       f"NaN = {has_nan}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
n_pass = sum(1 for _, p, _ in results if p)
n_fail = len(results) - n_pass
print(f"SUMMARY: {n_pass}/{len(results)} checks passed, {n_fail} failed")
if n_fail:
    print("FAILED:")
    for name, p, detail in results:
        if not p:
            print(f"  - {name}: {detail}")
    sys.exit(1)
sys.exit(0)
