#!/usr/bin/env python3
"""pytest suite for tools/drive_ripple.py -- the drive-ripple predictor, the
frozen fw v35 reference, the offline closed-loop simulator and the lock-in
(2026-11-04, the drive-ripple round).

Written by a test author independent of the implementer.  Tests pin what was
BUILT (see the module docstring and docs/HIL_SCENARIOS.md), not the original
spec where the two differ (zero-cutoff coast, +/-15 % tolerance, the
discriminator scored against the predicted |L|).

This file also exports `synth_ripple_csv()`, the closed-loop CSV generator the
run_hil_suite tests reuse: the REAL hil_plant_sim.Plant (simple engine) with
the drive law run as a fake board, written in the exact column subset
`run_hil_suite.scan_drive_ripple()` reads.

Run: cd tools && python3 -m pytest -q -p no:cacheprovider test_drive_ripple.py
"""
import ast
import cmath
import csv
import math
import os
import random
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import drive_ripple as dr  # noqa: E402
import hil_plant_sim as hil  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Shared helper: a closed-loop CSV of the real plant + a fake board.
# ─────────────────────────────────────────────────────────────────────────

def synth_ripple_csv(path, scenario, coeffs, t_end=None, mutate=None):
    """Run hil_plant_sim.Plant (simple engine, the scenario's own ripple hooks)
    against the drive law `coeffs` executed as the board would (2 ms gate, the
    zero-setpoint cutoff, Hanus-conditioned clamp), and write a CSV with the
    columns scan_drive_ripple() reads.  `mutate(row_dict)` may edit/skip a row
    (return None to drop it)."""
    meta = hil.SCENARIOS[scenario]
    plant = hil.Plant(drive_ripple_cfg=meta["drive_ripple"])
    prof = meta["ems_v_profile"]
    sw = hil.SW_FC_BUS | hil.SW_BT_BUS | hil.SW_MOT_PWR | hil.SW_BT_SEQ
    aux = hil.AUX_FC_REG | hil.AUX_BT_REG
    n = coeffs["NSTATES"]
    x = [0.0] * n
    held = 0.0
    cut = True
    obs = None
    dt = 1e-3
    steps = int((t_end if t_end is not None else meta["duration_s"]) / dt)
    cols = ["t", "I_fc", "I_batt", "v_actual", "state", "current",
            "fault_flags", "v_true", "fly_theta"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for k in range(steps):
            t = k * dt
            hil.apply_scenario(plant, scenario, t)
            s = plant.step(dt, obs)
            sp = (hil.piecewise(prof, t)
                  if 3.0 <= t < meta["ems_run_exit_s"] else 0.0)
            if k % 2 == 0:
                if abs(sp) < dr.V_SP_ZERO_THRESH_MPS:
                    if not cut:
                        x = [0.0] * n
                        cut = True
                    held = 0.0
                else:
                    cut = False
                    e = sp - s["v_actual"]
                    u = coeffs["DD"] * e + sum(coeffs["CD"][j] * x[j]
                                               for j in range(n))
                    uc = max(coeffs["I_MIN"], min(coeffs["I_MAX"], u))
                    x = [coeffs["BD"][i] * e + coeffs["L"][i] * (uc - u)
                         + sum(coeffs["AD"][i][j] * x[j] for j in range(n))
                         for i in range(n)]
                    held = uc
            obs = {"state": 2, "switch": sw, "aux": aux, "current": held,
                   "mdac_fc": 0x1000 | 2048, "mdac_bt": 0x1000 | 2048,
                   "fault_flags": 0, "mppt_cnt": 255, "error_code": 0}
            row = {"t": "%.6f" % t, "I_fc": "%.4f" % s["I_fc"],
                   "I_batt": "%.4f" % s["I_batt"],
                   "v_actual": "%.6f" % s["v_actual"], "state": 2,
                   "current": "%.4f" % held, "fault_flags": 0,
                   "v_true": "%.6f" % s["v_true"],
                   "fly_theta": "%.6f" % s["fly_theta"]}
            if mutate is not None:
                row = mutate(row)
                if row is None:
                    continue
            w.writerow([row[c] for c in cols])
    return path


# ─────────────────────────────────────────────────────────────────────────
# 1. The header parser
# ─────────────────────────────────────────────────────────────────────────

def test_repo_header_parses_to_a_five_state_two_ms_law():
    c = dr.repo_drive_coeffs()
    assert c["NSTATES"] == 5 and c["TS_US"] == 2000
    assert len(c["AD"]) == 5 and all(len(r) == 5 for r in c["AD"])
    assert len(c["BD"]) == len(c["CD"]) == len(c["L"]) == 5
    assert c["I_MAX"] == 12.0 and c["I_MIN"] == -12.0
    # state 0 is the integrator in this realization (the simulator relies on it)
    assert c["AD"][0][0] == 1.0 and all(v == 0.0 for v in c["AD"][0][1:])
    assert c["source"].endswith("drive_controller_coeffs.h")


def test_repo_header_values_match_the_raw_text():
    """Cross-check the parse against an independent read of the header: DD and
    the first CD entry as written in the file."""
    with open(dr.DRIVE_COEFF_HEADER) as fh:
        src = fh.read()
    c = dr.repo_drive_coeffs()
    m = re.search(r"DRIVE_CTRL_DD\s*=\s*([-0-9.eE+]+)f?", src)
    assert float(m.group(1)) == c["DD"]
    m = re.search(r"DRIVE_CTRL_KI\s*=\s*([-0-9.eE+]+)f?", src)
    assert float(m.group(1)) == c["KI"]


def _good_header(**over):
    """A minimal valid 2-state header text, with substitutions."""
    txt = {
        "ns": "#define DRIVE_CTRL_NSTATES 2",
        "ts": "#define DRIVE_CTRL_TS_US 2000",
        "ki": "static const float DRIVE_CTRL_KI = 1.5f;",
        "imin": "static const float DRIVE_CTRL_I_MIN = -12.0f;",
        "imax": "static const float DRIVE_CTRL_I_MAX = 12.0f;",
        "dd": "static const float DRIVE_CTRL_DD = 2.0f;",
        "ad": "static const float DRIVE_CTRL_AD[2][2] = {{1.0f, 0.0f}, {0.0f, 0.5f}};",
        "bd": "static const float DRIVE_CTRL_BD[2][1] = {{1.0f}, {0.25f}};",
        "cd": "static const float DRIVE_CTRL_CD[1][2] = {{3.0f, 4.0f}};",
        "l": "static const float DRIVE_CTRL_L[2][1] = {{0.1f}, {0.2f}};",
    }
    txt.update(over)
    return "\n".join(txt.values()) + "\n"


def _write(tmp_path, text, name="h.h"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_parser_accepts_a_minimal_good_header(tmp_path):
    c = dr.load_drive_coeffs(_write(tmp_path, _good_header()))
    assert c["NSTATES"] == 2 and c["DD"] == 2.0
    assert c["AD"] == ((1.0, 0.0), (0.0, 0.5))
    assert c["BD"] == (1.0, 0.25) and c["CD"] == (3.0, 4.0)
    assert c["L"] == (0.1, 0.2) and c["KI"] == 1.5 and c["I_MIN"] == -12.0


@pytest.mark.parametrize("key", ["dd", "ki", "imax", "ad", "bd", "cd", "l",
                                 "ns", "ts"])
def test_parser_raises_on_a_missing_field(tmp_path, key):
    with pytest.raises(RuntimeError):
        dr.load_drive_coeffs(_write(tmp_path, _good_header(**{key: ""})))


def test_parser_raises_on_a_short_matrix_row(tmp_path):
    bad = _good_header(ad="static const float DRIVE_CTRL_AD[2][2] = "
                          "{{1.0f, 0.0f}, {0.0f}};")
    with pytest.raises(RuntimeError, match="malformed"):
        dr.load_drive_coeffs(_write(tmp_path, bad))


def test_parser_raises_on_wrong_row_count(tmp_path):
    bad = _good_header(ad="static const float DRIVE_CTRL_AD[2][2] = "
                          "{{1.0f, 0.0f}};")
    with pytest.raises(RuntimeError, match="rows"):
        dr.load_drive_coeffs(_write(tmp_path, bad))


def test_parser_ignores_numbers_quoted_in_comments(tmp_path):
    """Comments are stripped first: a commented-out DD and a prose number must
    not be picked up, and the real value still is."""
    txt = ("// DRIVE_CTRL_DD = 99.0f;\n/* DRIVE_CTRL_KI = 77.0f; */\n"
           + _good_header())
    c = dr.load_drive_coeffs(_write(tmp_path, txt))
    assert c["DD"] == 2.0 and c["KI"] == 1.5


def test_parser_raises_on_a_commented_out_only_field(tmp_path):
    bad = _good_header(dd="// static const float DRIVE_CTRL_DD = 2.0f;")
    with pytest.raises(RuntimeError):
        dr.load_drive_coeffs(_write(tmp_path, bad))


# ─────────────────────────────────────────────────────────────────────────
# 2. The frozen fw v35 law, coeffs_equal
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("f_hz,expect", [(2.089, 85.9), (3.133, 78.7),
                                         (4.595, 74.6), (5.639, 72.8)])
def test_v35_controller_gain_at_the_rotation_frequencies(f_hz, expect):
    """|C| of the frozen fw v35 law, A per (m/s), at the four hold frequencies
    (the figures the HIL_SCENARIOS entry quotes)."""
    assert abs(dr.controller_response(dr.V35_DRIVE_COEFFS, f_hz)) == \
        pytest.approx(expect, rel=0.005)


V35_REFERENCE_SHA256 = "698d483da14e4928f8f7cfaa4068a703ecbec9b1858cdd53febb28bbcc2a4f5c"


def test_v35_frozen_table_is_bit_identical_to_the_ab4a705_header_via_git():
    """The frozen table was transcribed from `git show ab4a705:...` ("fw v35,
    flashed on the board").  Re-parse that revision with the same parser and
    demand bit equality (skipped where the commit is not reachable)."""
    import subprocess
    import tempfile
    try:
        out = subprocess.run(
            ["git", "show", "ab4a705:teensy_controller/drive_controller_coeffs.h"],
            capture_output=True, text=True, cwd=HERE, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("git unavailable")
    if out.returncode != 0 or "DRIVE_CTRL_DD" not in out.stdout:
        pytest.skip("commit ab4a705 not reachable in this checkout")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "v35.h")
        with open(p, "w") as fh:
            fh.write(out.stdout)
        ref = dr.load_drive_coeffs(p)
    for k in ("TS_US", "NSTATES", "KI", "I_MIN", "I_MAX", "DD", "AD", "BD",
              "CD", "L"):
        assert dr.V35_DRIVE_COEFFS[k] == ref[k], k


def test_v35_frozen_table_tripwire_digest():
    """A typo in any coefficient of the frozen table moves this digest (the
    |C| spot checks above are too coarse to see a 0.1 % DD slip)."""
    import hashlib
    v = dr.V35_DRIVE_COEFFS
    rep = repr([v[k] for k in ("TS_US", "NSTATES", "KI", "I_MIN", "I_MAX", "DD",
                               "AD", "BD", "CD", "L")])
    assert hashlib.sha256(rep.encode()).hexdigest() == V35_REFERENCE_SHA256


def test_coeffs_sha256_is_a_stable_fingerprint_of_the_law():
    """(fix-round helper) 64 hex chars, stable, law-sensitive, insensitive to
    the dict's provenance string."""
    v35 = dr.V35_DRIVE_COEFFS
    h = dr.coeffs_sha256(v35)
    assert re.fullmatch(r"[0-9a-f]{64}", h)
    assert dr.coeffs_sha256(dict(v35, source="elsewhere")) == h
    assert dr.coeffs_sha256(dr.repo_drive_coeffs()) != h
    assert dr.coeffs_sha256(dict(v35, DD=v35["DD"] + 1e-9)) != h
    assert dr.coeffs_sha256(dict(v35, I_MAX=11.0)) != h


def test_bus_signature_algebra_and_hypothesis_contrast():
    """(fix-round helper) dI_bus = k (v0 di + I0 dv_true); dv_true = v_inj under
    the force hypothesis and -L v_inj under the artefact one."""
    i_ph, v_ph = 0.6 * cmath.exp(1j * 2.5), 0.02 * cmath.exp(1j * 0.3)
    loop = 0.46 * cmath.exp(-1j * 2.0)
    out = dr.bus_ripple_signatures(i_ph, v_ph, i0=4.0, v0=1.0, k_bus=0.1,
                                   loop_l=loop)
    assert out["force"] == pytest.approx(0.1 * (1.0 * i_ph + 4.0 * v_ph))
    assert out["meas"] == pytest.approx(0.1 * (1.0 * i_ph - 4.0 * loop * v_ph))
    # no DC current -> the hypotheses are indistinguishable
    z = dr.bus_ripple_signatures(i_ph, v_ph, 0.0, 1.0, 0.1, loop)
    assert z["meas"] == pytest.approx(z["force"])


def test_repo_law_is_the_lower_gain_law():
    """fw v37 re-synthesised at a lower crossover: |C| at every hold frequency
    is under half of v35's."""
    r = dr.repo_drive_coeffs()
    for f in (2.089, 3.133, 4.595, 5.639):
        assert abs(dr.controller_response(r, f)) < \
            0.5 * abs(dr.controller_response(dr.V35_DRIVE_COEFFS, f))


def test_coeffs_equal_reflexive_and_distinguishes_the_two_laws():
    v35 = dr.V35_DRIVE_COEFFS
    assert dr.coeffs_equal(v35, v35)
    assert dr.coeffs_equal(dr.repo_drive_coeffs(), dr.repo_drive_coeffs())
    assert not dr.coeffs_equal(dr.repo_drive_coeffs(), v35)


def test_coeffs_equal_sees_every_law_term_but_not_the_gains_it_ignores():
    v35 = dr.V35_DRIVE_COEFFS

    def clone(**over):
        c = dict(v35)
        c.update(over)
        return c
    assert not dr.coeffs_equal(v35, clone(DD=v35["DD"] + 1e-9))
    assert not dr.coeffs_equal(v35, clone(TS_US=1000))
    bd = list(v35["BD"]); bd[2] += 1e-9
    assert not dr.coeffs_equal(v35, clone(BD=tuple(bd)))
    cd = list(v35["CD"]); cd[4] += 1e-9
    assert not dr.coeffs_equal(v35, clone(CD=tuple(cd)))
    ad = [list(r) for r in v35["AD"]]; ad[3][2] += 1e-9
    assert not dr.coeffs_equal(v35, clone(AD=tuple(map(tuple, ad))))
    # KI / L / the rails are not part of the LINEAR law as defined.
    assert dr.coeffs_equal(v35, clone(KI=0.0))
    assert dr.coeffs_equal(v35, clone(I_MAX=1.0))


# ─────────────────────────────────────────────────────────────────────────
# 3. Geometry, plant params, predictor properties
# ─────────────────────────────────────────────────────────────────────────

def test_f_rot_is_2_089_hz_per_mps_and_sign_blind():
    assert dr.f_rot_hz(1.0) == pytest.approx(2.0886, abs=1e-3)
    assert dr.f_rot_hz(-2.0) == pytest.approx(2 * dr.f_rot_hz(1.0))
    assert dr.f_rot_hz(0.0) == 0.0
    assert dr.FLYWHEEL_RADIUS_M == 0.0762


def test_plant_params_come_from_the_plants_own_constants():
    p = dr.hil_plant_params()
    assert p == {"m_eff": hil.M_EFF, "b_lin": hil.B_EFF, "k_f": hil.K_F}
    # a compensated road load has a speed-proportional slope instead
    q = dr.hil_plant_params(hil.DRAG_MODE_SCALED_AIR, 2.0)
    assert q["b_lin"] == pytest.approx(2.0 * hil.drag_k_air(hil.DRAG_MODE_SCALED_AIR)
                                       * 2.0)
    assert q["b_lin"] != hil.B_EFF


def test_predict_hold_measurement_hook_identities():
    """meas: i = |C S| A (up to the latency's modulus-1 factor), and the
    true/injected ratio is exactly |L|."""
    c = dr.repo_drive_coeffs()
    p = dr.hil_plant_params()
    for v in (1.0, 1.5, 2.2, 2.7):
        pr = dr.predict_hold(c, v, p, a_meas=0.02)
        assert pr["true_over_inj"] == pytest.approx(pr["abs_L"], rel=1e-9)
        assert pr["i_amp"] == pytest.approx(pr["abs_CS"] * 0.02, rel=1e-9)
        assert pr["f_hz"] == pytest.approx(dr.f_rot_hz(v))


def test_predict_hold_force_hook_true_equals_injected():
    c = dr.repo_drive_coeffs()
    p = dr.hil_plant_params()
    for v in (1.0, 2.7):
        pr = dr.predict_hold(c, v, p, f_rip=1.0)
        assert pr["true_over_inj"] == pytest.approx(1.0, abs=1e-12)
        assert pr["v_inj_amp"] == pytest.approx(pr["v_true_amp"], rel=1e-12)
        assert pr["i_amp"] == pytest.approx(pr["abs_T"] * 1.0 / p["k_f"],
                                            rel=1e-9)


def test_predict_hold_is_linear_in_amplitude_and_zero_without_a_hook():
    c = dr.repo_drive_coeffs()
    p = dr.hil_plant_params()
    a = dr.predict_hold(c, 1.5, p, a_meas=0.01)["i_amp"]
    b = dr.predict_hold(c, 1.5, p, a_meas=0.04)["i_amp"]
    assert b == pytest.approx(4 * a, rel=1e-12)
    z = dr.predict_hold(c, 1.5, p)
    assert z["i_amp"] == 0.0 and z["i_phase_vs_vinj_deg"] is None \
        and z["true_over_inj"] is None


def test_predict_hold_band_brackets_the_nominal_and_basis_is_small():
    p = dr.hil_plant_params()
    for c in (dr.repo_drive_coeffs(), dr.V35_DRIVE_COEFFS):
        for v in (1.0, 2.7):
            nom = dr.predict_hold(c, v, p, a_meas=0.02)["i_amp"]
            lo, hi = dr.predict_hold_band(c, v, p, a_meas=0.02)
            assert lo <= nom * (1 + 1e-12) and hi >= nom * (1 - 1e-12)
    basis = dr.drive_ripple_tolerance_basis(
        [dr.repo_drive_coeffs(), dr.V35_DRIVE_COEFFS], [1.0, 1.5, 2.2, 2.7],
        p, a_meas=0.02)
    # the delay-uncertainty term must fit well inside the scored tolerance
    assert 0.0 < basis < dr.PREDICTION_TOL_FRAC / 2


def test_prediction_tolerance_is_15_percent():
    assert dr.PREDICTION_TOL_FRAC == 0.15


def test_nominal_pipeline_delay_lies_inside_its_band():
    lo, hi = dr.HIL_LOOP_DELAY_BAND_S
    assert 0.0 <= lo <= dr.HIL_LOOP_DELAY_S <= hi < 10e-3


def test_equivalent_delay_of_the_simulator_pipeline_is_linear_in_ticks():
    """Whatever the fold-in constant, each extra integer tick of pipeline adds
    exactly one tick of equivalent delay, and the unit pipeline's equivalent
    delay stays inside the scored latency band."""
    base = dr.sim_equivalent_delay_s(1, 1)
    assert dr.sim_equivalent_delay_s(2, 1) - base == pytest.approx(1e-3)
    assert dr.sim_equivalent_delay_s(1, 2) - base == pytest.approx(1e-3)
    assert dr.sim_equivalent_delay_s(1, 1, dt=2e-3) - \
        dr.sim_equivalent_delay_s(0, 0, dt=2e-3) == pytest.approx(
            2 * (base - dr.sim_equivalent_delay_s(0, 0)))
    lo, hi = dr.HIL_LOOP_DELAY_BAND_S
    assert lo <= base <= hi + 1e-3


def test_controller_response_dc_gain_has_the_integrator_pole():
    """C(z) has an integrator (AD[0][0] == 1): |C| rises without bound toward
    DC on both laws."""
    for c in (dr.repo_drive_coeffs(), dr.V35_DRIVE_COEFFS):
        assert abs(dr.controller_response(c, 0.01)) > \
            5 * abs(dr.controller_response(c, 1.0))


# ─────────────────────────────────────────────────────────────────────────
# 4. Predictor vs the tick-exact simulator
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("law", ["repo", "v35"])
@pytest.mark.parametrize("hook", ["meas", "force"])
@pytest.mark.parametrize("v", [1.0, 2.7])
def test_predictor_matches_the_closed_loop_simulator(
        law, hook, v):
    c = dr.repo_drive_coeffs() if law == "repo" else dr.V35_DRIVE_COEFFS
    p = dr.hil_plant_params()
    kw = {"a_meas": 0.02} if hook == "meas" else {"f_rip": 1.0}
    s = dr.simulate_hold(c, v, duration_s=10.0, plant=p, **kw)
    i0 = next(i for i, t in enumerate(s["t"]) if t >= 4.0)
    li = dr.lockin(s["t"][i0:], s["current"][i0:], s["theta"][i0:])
    pr = dr.predict_hold(c, v, p, delay_s=dr.sim_equivalent_delay_s(), **kw)
    # The spec asked for 2 %; the fixed predictor agrees to ~0.02 %, and 0.2 %
    # is tight enough to see a 1 ms (half-ZOH) mis-fold (0.4-1.9 % here).
    assert li["amp"] == pytest.approx(pr["i_amp"], rel=0.002)
    # and the discriminator quantity
    lt = dr.lockin(s["t"][i0:], s["v_true"][i0:], s["theta"][i0:])
    lj = dr.lockin(s["t"][i0:], s["v_inj"][i0:], s["theta"][i0:])
    assert lt["amp"] / lj["amp"] == pytest.approx(pr["true_over_inj"], rel=0.002)


def test_simulate_hold_without_hooks_has_no_ripple_line():
    c = dr.repo_drive_coeffs()
    s = dr.simulate_hold(c, 1.5, duration_s=8.0)
    i0 = next(i for i, t in enumerate(s["t"]) if t >= 3.0)
    li = dr.lockin(s["t"][i0:], s["current"][i0:], s["theta"][i0:])
    assert li["amp"] < 1e-3


def test_simulate_hold_zero_cutoff_commands_zero_amps():
    """Below V_SP_ZERO_THRESH the controller is held reset and 0 A commanded
    (motorControl()); the body coasts down."""
    c = dr.repo_drive_coeffs()
    s = dr.simulate_hold(c, lambda t: 1.0 if t < 1.0 else 0.0, duration_s=3.0)
    late = [i for t, i in zip(s["t"], s["current"]) if t > 1.1]
    assert all(i == 0.0 for i in late)
    assert s["v_true"][-1] < s["v_true"][int(1.0 / 1e-3)]


def test_simulate_hold_theta_wraps_and_rate_is_v_over_r():
    c = dr.repo_drive_coeffs()
    s = dr.simulate_hold(c, 1.0, duration_s=2.0)
    assert all(0.0 <= th < 2 * math.pi for th in s["theta"])
    un = dr.unwrap(s["theta"])
    rate = (un[-1] - un[0]) / (s["t"][-1] - s["t"][0])
    assert rate == pytest.approx(1.0 / dr.FLYWHEEL_RADIUS_M, rel=0.02)


# ─────────────────────────────────────────────────────────────────────────
# 5. Lock-in
# ─────────────────────────────────────────────────────────────────────────

def _synthetic(amp, phase_deg, dc, slope, f_hz, dur, dt=1e-3, harmonic=1,
               noise=0.0, seed=1):
    rng = random.Random(seed)
    t = [k * dt for k in range(int(dur / dt))]
    th = [(2 * math.pi * f_hz * tt) % (2 * math.pi) for tt in t]
    ph = math.radians(phase_deg)
    x = [dc + slope * tt + amp * math.sin(harmonic * (2 * math.pi * f_hz * tt) + ph)
         + (rng.gauss(0, noise) if noise else 0.0) for tt in t]
    return t, x, th


@pytest.mark.parametrize("dur,f", [(6.0, 2.089), (6.37, 3.133), (6.011, 5.639),
                                   (7.77, 4.595)])
def test_lockin_recovers_amplitude_and_phase_with_dc_and_trend(dur, f):
    t, x, th = _synthetic(0.62, 37.0, dc=4.2, slope=0.05, f_hz=f, dur=dur)
    li = dr.lockin(t, x, th)
    assert li["amp"] == pytest.approx(0.62, rel=1e-6)
    assert li["phase_deg"] == pytest.approx(37.0, abs=1e-4)
    assert li["mean"] == pytest.approx(4.2 + 0.05 * (t[li["n"] - 1] / 2), rel=1e-3)
    assert li["revs"] >= 11.99 and abs(li["revs"] - round(li["revs"])) < 0.01


def test_lockin_phase_quadrants():
    for ph in (-170.0, -90.0, 0.0, 90.0, 170.0):
        t, x, th = _synthetic(1.0, ph, 0.0, 0.0, 3.0, 5.0)
        assert dr.lockin(t, x, th)["phase_deg"] == pytest.approx(ph, abs=1e-4)


def test_lockin_second_harmonic_and_rejection_of_other_harmonics():
    t, x, th = _synthetic(0.3, 20.0, 1.0, 0.0, 3.0, 5.0, harmonic=2)
    assert dr.lockin(t, x, th, harmonic=2)["amp"] == pytest.approx(0.3, rel=1e-6)
    assert dr.lockin(t, x, th, harmonic=1)["amp"] < 2e-3


def test_lockin_survives_nonuniform_angle_rate():
    """Force variant: the angle is not uniform in time (the speed itself
    ripples).  Build x as a pure function of the angle."""
    dt = 1e-3
    t, th, ang = [], [], 0.0
    x = []
    for k in range(8000):
        tt = k * dt
        w = 20.0 * (1.0 + 0.1 * math.sin(ang))
        ang += w * dt
        t.append(tt)
        th.append(ang % (2 * math.pi))
        x.append(3.0 + 0.5 * math.sin(ang + 0.7))
    li = dr.lockin(t, x, th)
    assert li["amp"] == pytest.approx(0.5, rel=2e-3)
    assert li["phase_deg"] == pytest.approx(math.degrees(0.7), abs=0.3)


def test_lockin_returns_none_under_one_revolution_or_too_few_samples():
    t, x, th = _synthetic(1.0, 0.0, 0.0, 0.0, 2.0, 0.45)       # 0.9 rev
    assert dr.lockin(t, x, th) is None
    assert dr.lockin([], [], []) is None
    t, x, th = _synthetic(1.0, 0.0, 0.0, 0.0, 2.0, 0.6, dt=0.1)  # < 8 samples
    assert dr.lockin(t, x, th) is None


def test_lockin_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        dr.lockin([0.0, 1.0], [0.0], [0.0, 1.0])


def test_lockin_noise_leaves_the_estimate_close():
    t, x, th = _synthetic(0.5, 10.0, 3.0, 0.0, 3.0, 6.0, noise=0.05)
    assert dr.lockin(t, x, th)["amp"] == pytest.approx(0.5, abs=0.01)


def test_unwrap_integer_rev_span_and_phase_diff():
    th = [0.0, 3.0, 6.0, 0.5, 3.5, 6.2, 0.9]       # wraps twice
    un = dr.unwrap(th)
    assert un == sorted(un) and un[-1] > 2 * math.pi * 1
    assert dr.integer_rev_span([]) == (0, 0)
    assert dr.integer_rev_span([0.0, 1.0, 2.0]) == (0, 0)
    i0, i1 = dr.integer_rev_span([0.0, 3.0, 6.0, 6.5, 7.0, 9.0, 12.0, 13.0])
    assert (i0, i1) == (0, 7)           # last index with theta <= 4 pi
    assert dr.phase_diff_deg(10.0, 350.0) == pytest.approx(20.0)
    assert dr.phase_diff_deg(350.0, 10.0) == pytest.approx(-20.0)
    assert dr.phase_diff_deg(180.0, 0.0) == pytest.approx(180.0)
    assert dr.phase_diff_deg(-180.0, 0.0) == pytest.approx(180.0)


# ─────────────────────────────────────────────────────────────────────────
# 6. Step metrics
# ─────────────────────────────────────────────────────────────────────────

def _step_profile(tau, n=6000, dt=1e-3, v_target=2.0, t_step=1.0, over=0.0):
    t = [k * dt for k in range(n)]
    v = [0.0 if tt < t_step else
         v_target * (1.0 - math.exp(-(tt - t_step) / tau)
                     + over * math.sin(2 * math.pi * (tt - t_step)) *
                     math.exp(-(tt - t_step) / tau))
         for tt in t]
    return t, v


def test_step_metrics_settle_time_of_a_first_order_response():
    t, v = _step_profile(0.5)
    cur = [3.0] * len(t)
    m = dr.step_metrics(t, v, cur, 1.0, 2.0, 12.0)
    # 2 % band of a first-order lag: tau * ln(50) = 1.956 s
    assert m["settle_2pct_s"] == pytest.approx(0.5 * math.log(50.0), abs=0.01)
    assert m["overshoot_pct"] == 0.0
    assert m["peak_current_a"] == 3.0
    assert m["rail_s"] == 0.0


def test_step_metrics_reports_never_settled_as_none():
    t, v = _step_profile(5.0, n=4000)          # ends inside the band, far off
    m = dr.step_metrics(t, v, [1.0] * len(t), 1.0, 2.0, 12.0)
    assert m["settle_2pct_s"] is None


def test_step_metrics_overshoot_and_rail_time():
    t, v = _step_profile(0.3)
    v = [(2.1 if 4.0 <= tt < 4.1 else vv) for tt, vv in zip(t, v)]
    cur = [12.0 if 1.0 <= tt < 1.4 else 2.0 for tt in t]
    m = dr.step_metrics(t, v, cur, 1.0, 2.0, 12.0)
    assert m["overshoot_pct"] == pytest.approx(5.0, abs=0.2)
    assert m["rail_s"] == pytest.approx(0.4, abs=0.003)
    assert m["peak_current_a"] == 12.0
    # a negative rail excursion counts too (|current| vs the rail)
    cur2 = [-12.0 if 1.0 <= tt < 1.1 else 0.0 for tt in t]
    assert dr.step_metrics(t, v, cur2, 1.0, 2.0, 12.0)["rail_s"] == \
        pytest.approx(0.1, abs=0.003)


def test_step_metrics_respects_t_end_and_empty_window():
    t, v = _step_profile(0.5)
    assert dr.step_metrics(t, v, [0.0] * len(t), 99.0, 2.0, 12.0) is None
    m = dr.step_metrics(t, v, [0.0] * len(t), 1.0, 2.0, 12.0, t_end=1.3)
    assert m["settle_2pct_s"] is None       # window ends while still rising


def test_step_metrics_instant_settle_is_zero():
    t = [k * 1e-3 for k in range(2000)]
    v = [0.0 if tt < 0.5 else 2.0 for tt in t]
    m = dr.step_metrics(t, v, [1.0] * len(t), 0.5, 2.0, 12.0)
    assert m["settle_2pct_s"] == 0.0 or m["settle_2pct_s"] == pytest.approx(0.0, abs=2e-3)


# ─────────────────────────────────────────────────────────────────────────
# 7. Module hygiene (constants_hash safety, stdlib only)
# ─────────────────────────────────────────────────────────────────────────

def test_drive_ripple_imports_nothing_outside_the_stdlib():
    with open(os.path.join(HERE, "drive_ripple.py")) as fh:
        tree = ast.parse(fh.read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    # hil_plant_sim is imported lazily (inside functions) only
    stdlib = set(getattr(sys, "stdlib_module_names", ())) or \
        {"cmath", "math", "os", "re", "hashlib"}
    assert mods - {"hil_plant_sim"} <= stdlib, mods - stdlib - {"hil_plant_sim"}
    assert not (mods & {"numpy", "scipy"})


def test_hil_plant_sim_imports_drive_ripple_as_a_module_not_by_name():
    """A from-import would re-export UPPERCASE numerics into hil_plant_sim and
    move every run's constants_hash."""
    assert hil.drive_ripple is dr
    for name in ("FLYWHEEL_RADIUS_M", "HIL_LOOP_DELAY_S",
                 "HIL_LOOP_DELAY_BAND_S", "PREDICTION_TOL_FRAC",
                 "V_SP_ZERO_THRESH_MPS", "DRIVE_COEFF_HEADER"):
        assert not hasattr(hil, name), name
    with open(os.path.join(HERE, "hil_plant_sim.py")) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "drive_ripple"


# ─────────────────────────────────────────────────────────────────────────
# 8. The generator itself is a faithful fake board (guards the suite tests)
# ─────────────────────────────────────────────────────────────────────────

def test_synth_generator_tracks_the_setpoint_and_carries_the_ripple(tmp_path):
    p = synth_ripple_csv(str(tmp_path / "m.csv"), "drive-ripple-meas",
                         dr.repo_drive_coeffs(), t_end=16.0)
    rows = list(csv.DictReader(open(p)))
    assert len(rows) == 16000
    r15 = next(r for r in rows if float(r["t"]) >= 14.9)
    assert float(r15["v_true"]) == pytest.approx(1.0, abs=0.02)
    # the injected speed differs from the true one only by the hook
    dv = [float(r["v_actual"]) - float(r["v_true"]) for r in rows
          if 9.0 <= float(r["t"]) <= 15.0]
    assert max(dv) == pytest.approx(0.02, abs=2e-4)
    assert min(dv) == pytest.approx(-0.02, abs=2e-4)
