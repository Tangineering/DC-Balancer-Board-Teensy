#!/usr/bin/env python3
"""Host-native checks for asymmetry_fit.py (numpy only, no pytest required).

Run:  .venv_benchlog/Scripts/python.exe tools/benchlog_analysis/test_asymmetry_fit.py
"""
import os
import sys

import pytest

np = pytest.importorskip("numpy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asymmetry_fit as af  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


# ── Model algebra ────────────────────────────────────────────────────────────
r = np.linspace(0.2, 0.8, 25)
it = np.linspace(0.7, 2.2, 25)

# M2 with rho = 1 and A = dV0/k_d must equal M1 exactly.
for dv0 in (-0.1, 0.0, 0.05, 0.2):
    a1 = af.m1_predict(r, it, dv0)
    a2 = af.m2_predict(r, it, dv0 / af.K_DROOP, 1.0)
    check(np.allclose(a1, a2, atol=1e-12), f"M2(rho=1) != M1 at dV0={dv0}")

# dV0 = 0 must give alpha = r exactly (nominal unity static gain,
# system_model.md:189-203 fact 1).
check(np.allclose(af.m1_predict(r, it, 0.0), r, atol=1e-15), "dV0=0 must give alpha=r")

# The disturbance is maximal at r = 0.5 and scales as 1/I_tot.
d = af.m1_predict(0.5, 1.0, 0.05) - 0.5
check(abs(af.m1_predict(0.5, 2.0, 0.05) - 0.5 - d / 2.0) < 1e-15,
      "disturbance must scale as 1/I_tot")
check(all(af.m1_predict(x, 1.0, 0.05) - x <= d + 1e-15 for x in r),
      "disturbance must peak at r = 0.5")

# ── Estimator recovery on synthetic data ─────────────────────────────────────
rng = np.random.default_rng(7)
rr = rng.uniform(0.2, 0.8, 4000)
ii = rng.uniform(0.7, 2.3, 4000)
aa = af.m1_predict(rr, ii, 0.0444)
check(abs(af.fit_m1(rr, ii, aa)["dV0_V"] - 0.0444) < 1e-9, "fit_m1 must be exact, noise-free")

p2 = af.fit_m2(rr, ii, af.m2_predict(rr, ii, 0.15, 0.90))
check(abs(p2["A_V_per_ohm"] - 0.15) < 1e-4 and abs(p2["rho_sF_over_sB"] - 0.90) < 1e-4,
      f"fit_m2 must recover (A, rho); got {p2}")

# Noise on alpha must not bias M1 (mean of many draws).
ests = [af.fit_m1(rr, ii, aa + rng.normal(0, 0.02, aa.size))["dV0_V"] for _ in range(30)]
check(abs(float(np.mean(ests)) - 0.0444) < 2e-3, "fit_m1 biased under alpha noise")

# ── Mode classification (decode_benchlog.py:33-52 bit semantics) ─────────────
check(af.classify_mode(np.array([0x0D] * 8), True) == "closed", "bit2 set -> closed")
check(af.classify_mode(np.array([0x33] * 8), True) == "openloop", "bit2/3 clear -> openloop")
check(af.classify_mode(np.array([0x09] * 8), True) is None, "HOLD (bit3 only) must be rejected")
check(af.classify_mode(np.array([0x0D, 0x33]), True) is None, "mixed mode must be rejected")
check(af.classify_mode(np.array([0x00] * 8), True) is None, "droop idle must be rejected")
check(af.classify_mode(np.array([0x01] * 8), False) == "legacy", "pre-v3 flags -> legacy")

# ── Constants must track the firmware ────────────────────────────────────────
check(af.K_DROOP == 0.30 and af.RE_MAX == 2.014, "K_DROOP/RE_MAX must match .ino:2166-2167")
check(af.I_TOT_MIN >= 2 * af.SHARE_MINORITY_I_MIN_A - 1e-12,
      "I_TOT_MIN must not sit below the closed-loop entry threshold")


# ─────────────────────────────────────────────────────────────────────────────
# L2: synthetic-CSV fixtures driving extract_windows through each branch
# ─────────────────────────────────────────────────────────────────────────────
import csv as _csv          # noqa: E402
import tempfile             # noqa: E402

_HDR = ["t_us", "share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
        "gFC", "gBT", "V_bus", "I_cmd", "V_fc", "V_batt", "V_chg", "V_rgn",
        "fault_flags", "ps_phase", "dc_phase", "trap_phase", "flags"]


def _write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(_HDR)
        w.writerows(rows)


def _synth(n=1400, alpha=0.5, r=0.5, i_tot=1.5, sp=0.5, flags=0x0D,
           fault=0, ramp=0.0, noise=0.0, seed=3, r_drift=0.0):
    """One run's worth of rows at a single operating point.

    Gains are the firmware map inverted from `r`, so extract_windows' own
    r_cmd = gBT/(gFC+gBT) recovers exactly the r asked for.
    """
    rg = np.random.default_rng(seed)
    rows = []
    for k in range(n):
        rk = r + r_drift * k / max(n - 1, 1)
        gF = af.K_DROOP / (af.RE_MAX * rk)
        gB = af.K_DROOP / (af.RE_MAX * (1.0 - rk))
        it = i_tot * (1.0 + ramp * k / max(n - 1, 1)) + rg.normal(0, noise)
        rows.append([1000 * k, sp, alpha, "", "", alpha * it, (1 - alpha) * it,
                     gF, gB, 15.9, 1.0, 8.4, 8.3, 0.0, 13.3,
                     fault, "", "", 0, flags])
    return rows


def _run(rows, fw=6):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "X.csv")
    _write_csv(rows, path)
    return af.extract_windows("X", d, path, fw)


# Happy path: a clean closed-loop point is accepted, and the recovered
# r_cmd/alpha/I_tot round-trip the values that generated it.
w, rej = _run(_synth(alpha=0.55, r=0.50, i_tot=1.5, sp=0.55))
check(len(w) >= 2, "clean synthetic run must yield windows; got %d %s" % (len(w), rej))
check(abs(w[0]["r_cmd"] - 0.50) < 1e-9, "r_cmd round-trip")
check(abs(w[0]["alpha"] - 0.55) < 1e-9, "alpha round-trip")
check(abs(w[0]["I_tot"] - 1.5) < 1e-9, "I_tot round-trip")
check(w[0]["mode"] == "closed", "bit2 fixture must label closed")

# Each rejection branch fires, and rejects every window when it does.
BRANCHES = [
    ("fault_flag_set", dict(fault=1)),
    ("i_tot_below_0.60A", dict(i_tot=0.4)),
    ("channel_dark", dict(alpha=0.98, sp=0.98)),
    ("r_cmd_nonstationary", dict(r_drift=0.10)),
    ("i_tot_noisy", dict(i_tot=3.0, noise=0.45)),
    ("i_tot_ramping", dict(ramp=0.8)),
    ("setpoint_out_of_band(cut)", dict(sp=0.05)),
    ("closed_loop_not_converged", dict(alpha=0.62, sp=0.50, i_tot=2.0)),
]
for _name, _kw in BRANCHES:
    _base = dict(alpha=0.5, r=0.5, i_tot=1.5, sp=0.5)
    _base.update(_kw)
    _w, _rej = _run(_synth(**_base))
    check(_name in _rej, "branch %r did not fire; got %s" % (_name, _rej))
    check(len(_w) == 0, "branch %r must reject every window" % _name)

# Droop-idle (bit0 clear) and HOLD (bit3 only) both land in the mode branch.
for _fl in (0x00, 0x09):
    _w, _rej = _run(_synth(flags=_fl))
    check("mode_mixed_or_droop_idle" in _rej and not _w,
          "flags %#04x must be rejected as a mode branch" % _fl)

# A pre-v3 CSV (no V_fc) is labelled legacy, not rejected.
_rows = _synth(alpha=0.55, sp=0.55, flags=0x01)
_d = tempfile.mkdtemp()
_p = os.path.join(_d, "L.csv")
with open(_p, "w", newline="") as _f:
    _wcsv = _csv.writer(_f)
    _keep = [i for i, c in enumerate(_HDR)
             if c not in ("V_fc", "V_batt", "V_chg", "V_rgn")]
    _wcsv.writerow([_HDR[i] for i in _keep])
    _wcsv.writerows([[row[i] for i in _keep] for row in _rows])
_wl, _ = af.extract_windows("L", _d, _p, None)
check(_wl and _wl[0]["mode"] == "legacy", "pre-v3 CSV must label legacy")

# The governor clip is APPLIED, not rejected: at 0.8 A the floor is
# 0.30/0.8 = 0.375, so sp 0.20 is delivered as 0.375.
_wg, _ = _run(_synth(alpha=0.375, r=0.30, i_tot=0.8, sp=0.20))
check(_wg and abs(_wg[0]["share_sp"] - 0.375) < 1e-9,
      "the GOVERNED setpoint must be recorded, not the raw one")

# ── per_channel_droop: the fixed series term must come off (H2) ──────────────
R_TRUE, V0_TRUE, G = 0.12, 15.9, 0.25
_fake = [dict(log="A", gFC=G, gBT=G, I_fc=x, I_batt=x, V_bus=V0_TRUE - R_TRUE * x)
         for x in np.linspace(0.4, 0.8, 6)]
_pcd = af.per_channel_droop(_fake)
check(len(_pcd) == 2, "per_channel_droop must fit both channels")
for _rec in _pcd:
    check(abs(_rec["R_meas_ohm"] - R_TRUE) < 1e-9, "R_meas must recover the slope")
    check(abs(_rec["V0_V"] - V0_TRUE) < 1e-9, "V0 must recover the intercept")
    _exp = (R_TRUE - af.DROOP_FIXED_SERIES_OHM) / (af.RE_MAX * G)
    check(abs(_rec["s_scale"] - _exp) < 1e-12, "s_scale must subtract the series term")
    check(_rec["s_scale"] < _rec["s_scale_uncorrected"],
          "the corrected scale must be the smaller of the two")
check(af.DROOP_FIXED_SERIES_OHM == 0.033, "series term must match hil_electrical.py:203")

# Pooling two runs with different V0 must not fake droop: grouping is per-run.
_mixed = _fake + [dict(log="B", gFC=G, gBT=G, I_fc=x, I_batt=x,
                       V_bus=16.4 - R_TRUE * x) for x in np.linspace(0.4, 0.8, 6)]
for _rec in af.per_channel_droop(_mixed):
    check(abs(_rec["R_meas_ohm"] - R_TRUE) < 1e-9,
          "per-run grouping must not absorb a between-run V0 step")

# ── bootstrap / median CI helpers ────────────────────────────────────────────
_ci = af.bootstrap(af.fit_m1, rr, ii, aa)
check(_ci["dV0_V"][0] <= 0.0444 <= _ci["dV0_V"][1], "bootstrap CI must bracket the truth")
check(_ci["dV0_V"][0] < _ci["dV0_V"][1], "bootstrap CI must be ordered")
check(af.median_ci([1.0]) is None, "median_ci must refuse a degenerate sample")
_lo, _hi = af.median_ratio_ci([2.0] * 9, [1.0] * 9)
check(abs(_lo - 2.0) < 1e-9 and abs(_hi - 2.0) < 1e-9,
      "median_ratio_ci on constant samples must collapse to the exact ratio")
check(af.median_ratio_ci([1.0], [1.0]) is None, "median_ratio_ci needs >= 2 points")

# ── M3 sense-offset equivalence (M5: the INJECTED defaults) ──────────────────
_dF, _dB = 0.020, 0.0
_equiv = af.K_DROOP * (_dF - 0.5 * (_dF + _dB)) / 0.25
check(abs(_equiv - 0.0120) < 1e-9, "M3 equivalent must be +0.0120 V")
check(abs(af.K_DROOP * (0.0199 - 0.5 * (0.0199 + 0.0002)) / 0.25 - _equiv) > 1e-5,
      "the fitted-median and injected-default equivalents must be distinguishable")


def _req(i_t, dv0=0.0444):
    lo_, hi_ = 0.05, 0.95
    for _ in range(200):
        mid = 0.5 * (lo_ + hi_)
        if af.m1_predict(mid, i_t, dv0) < 0.5:
            lo_ = mid
        else:
            hi_ = mid
    return 0.5 * (lo_ + hi_)


for _i in (0.5, 1.0, 2.0):
    _rq = _req(_i)
    check(abs(af.m1_predict(_rq, _i, 0.0444) - 0.5) < 1e-9,
          "bisection must invert M1 at %.1f A" % _i)
    check(_rq < 0.5, "a positive dV0 must require r_cmd BELOW 0.50")
check(_req(0.5) < _req(1.0) < _req(2.0) < 0.5,
      "the required r_cmd must rise toward 0.50 as load rises")

# ── single-source fitting ────────────────────────────────────────────────────
_SS = [dict(log="S", channel="FC", I=x, V_bus=15.95 - 0.15 * x, g_cmd=0.32)
       for x in np.linspace(0.4, 1.4, 8)]
_sf = af.fit_single_source(_SS)
check(len(_sf) == 1 and abs(_sf[0]["K_ohm"] - 0.15) < 1e-9,
      "fit_single_source must recover the slope")
check(abs(_sf[0]["s_scale"] - (0.15 - 0.033) / (af.RE_MAX * 0.32)) < 1e-12,
      "single-source s_scale must subtract the series term too")
_short = [dict(log="S", channel="FC", I=x, V_bus=15.95 - 0.15 * x, g_cmd=0.32)
          for x in np.linspace(0.40, 0.50, 8)]
check(af.fit_single_source(_short) == [], "a sub-span single-source group must be refused")

# ── reconcile_ratios: the pooled-anchor identity is stationary at equality ───
_eq = [dict(log="A", channel=c, K_ohm=0.15, s_scale=0.19, g_cmd=0.30)
       for c in ("FC", "BT")]
_rec = af.reconcile_ratios(_eq)
check(abs(_rec["pred_ratio_pooled_single"] - 2.0) < 1e-12,
      "matched channels must give the structural pooled ratio 2.000")
check(abs(_rec["shared_mismatch_effect_frac"]) < 1e-12,
      "matched channels must show zero mismatch effect")
_un = [dict(log="A", channel="FC", K_ohm=0.15, s_scale=0.18, g_cmd=0.30),
       dict(log="A", channel="BT", K_ohm=0.14, s_scale=0.20, g_cmd=0.30)]
_rec2 = af.reconcile_ratios(_un)
check(abs(_rec2["shared_mismatch_effect_frac"]) < 0.01,
      "a ~10 % channel mismatch must move the SHARED value well under 1 % -- "
      "the parallel combination is second-order in the mismatch")
check(_rec2["pred_ratio_pooled_single"] > 2.0,
      "the pooled ratio must exceed 2.000 for unequal channels")
check(af.reconcile_ratios([]) == {}, "reconcile_ratios must tolerate no fits")

# L2: the entry-threshold check must not pass on equality alone.
check(af.I_TOT_MIN >= 2 * af.SHARE_MINORITY_I_MIN_A,
      "I_TOT_MIN must not sit below the closed-loop entry threshold")
check(af.SS_LIVE_MIN_A >= af.SHARE_MINORITY_I_MIN_A,
      "a single-source window must clear the minority conduction floor")

if FAILS:
    print("FAIL")
    for m in FAILS:
        print("  -", m)
    sys.exit(1)
print("asymmetry_fit: extended checks pass")
