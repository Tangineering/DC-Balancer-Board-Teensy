#!/usr/bin/env python3
"""pytest suite for tools/h2_map.py -- the H-20 stack's hydrogen consumption
map (the scored estimator from 2026-09-08 onward).

INTERPRETER: the module's SCALAR path (`rate_gps`, `current_a`,
`polarization_v`, `eta_lhv`, `marginal_gps_per_w`, `fingerprint*`,
`stored_polarization_rms_v`, the module-level constants) is STDLIB ONLY
(module docstring: "numpy is imported LAZILY... so importing this module
from the plant costs nothing"), so most of this file collects and runs under
BOTH `.venv_hil` (stdlib-only) and miniforge.  Only the VECTORIZED path
(`rate_gps_array`, `current_a_array`), the FITTING helpers
(`quadratic_fit`, `efficiency_peak`, `student_form`) and the SCIPY-based
`refit_polarization()` need numpy/scipy -- those tests each
`pytest.importorskip` individually rather than gating the whole file, so the
stdlib-only anchors, shape and hook tests still run under `.venv_hil`.

Run:
    C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_h2_map.py -v
    .venv_hil/Scripts/python.exe -m pytest tools/test_h2_map.py -v

THIS IS A FLOOR, NOT A CEILING.  Coverage gaps this file does NOT close:
  * The DIGITIZED polarization points themselves (POLARIZATION_POINTS_A_V)
    are not cross-checked against the brochure PDF here -- that is a
    document-reading exercise, not a unit test.
  * `student_form()`'s `a0` is the quadratic fit's constant term, which the
    module's own docstring says trades some of the offset against curvature;
    this file checks it is "within 10% of A0" per the task brief, but does
    not independently verify that 10% is the right bound for every future
    coefficient change.
  * No test drives `h2_map.py` as `__main__` (the `if __name__ ==
    "__main__":` block at the bottom, an operator convenience printout).
  * The INVERSE TABLE's own accuracy claim ("< 3e-6 A ... on [0, I_PMAX_A]")
    is exercised only indirectly (vectorized-vs-scalar agreement, saturation
    floor); a dedicated accuracy-vs-grid-density test is not included.
"""
import math
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import h2_map  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# 1. Brochure anchors
# ═════════════════════════════════════════════════════════════════════════

def test_rate_gps_at_rated_power_matches_the_brochure_flow():
    """0.28 L/min at STP, converted to g/s -- the anchor the whole offset
    term is built from (FLOW_RATED_GPS).

    ⚠️ TOLERANCE IS 2%, NOT 0.5%, and the module's own documented residual is
    why: `rate_gps(20.28)` round-trips 20.28 W THROUGH THE FITTED
    POLARIZATION CURVE (P -> I via `current_a()`, then Faraday), and the
    curve's own module-documented fit quality is "V(2.6 A) = 7.902 V against
    the nameplate's 7.8 V (+1.3 %)" -- so `current_a(20.28)` resolves to
    2.5428 A, not the nameplate's 2.6 A, and the resulting rate undershoots
    FLOW_RATED_GPS by ~1.85%. `A0_OFFSET_GPS + K_FARADAY_GPS_PER_A *
    I_RATED_A` (checked in `test_a0_offset_equals_flow_minus_faraday_at_
    rated_current` above) is the EXACT identity FLOW_RATED_GPS is defined
    from; THIS test instead exercises the map's own P -> rate path at the
    nameplate power, which is a genuinely different (looser) claim."""
    want = 4.1944e-4
    got = h2_map.rate_gps(20.28)
    assert got == pytest.approx(want, rel=0.02)


def test_check_rated_efficiency_matches_the_brochures_printed_40_percent():
    eta = h2_map.check_rated_efficiency()
    assert eta == pytest.approx(0.40, abs=0.01)
    # And it is the STP reading specifically, per the module's own STP-vs-NTP
    # derivation (0.403 reproduces 40%, 0.432 would not).
    assert eta == pytest.approx(0.403, abs=0.005)


def test_polarization_v_at_nameplate_current_within_0p15v_of_7p8():
    v = h2_map.polarization_v(2.6)
    assert v == pytest.approx(7.8, abs=0.15)


def test_polarization_v_at_zero_current_is_open_circuit_voltage_exactly():
    assert h2_map.polarization_v(0.0) == h2_map.POLARIZATION_V0_V
    assert h2_map.polarization_v(0.0) == 12.2


def test_k_faraday_matches_the_closed_form_to_1e_minus_12_relative():
    want = 13 * 2.016 / (2 * 96485.33)
    got = h2_map.K_FARADAY_GPS_PER_A
    assert got == pytest.approx(want, rel=1e-12)
    # And N_CELLS/M_H2/F are exactly the nameplate constants this closed
    # form is written against -- pin them too, so a silent constant edit
    # cannot make the two expressions agree by coincidence.
    assert h2_map.N_CELLS == 13
    assert h2_map.M_H2_G_PER_MOL == pytest.approx(2.016)
    assert h2_map.F_C_PER_MOL == pytest.approx(96485.33)


def test_a0_offset_equals_flow_minus_faraday_at_rated_current():
    want = h2_map.FLOW_RATED_GPS - h2_map.K_FARADAY_GPS_PER_A * h2_map.I_RATED_A
    assert h2_map.A0_OFFSET_GPS == pytest.approx(want, rel=1e-15)
    assert h2_map.A0_OFFSET_GPS > 0.0


# ═════════════════════════════════════════════════════════════════════════
# 2. Shape: monotone, convex, single efficiency peak, rising marginal rate
# ═════════════════════════════════════════════════════════════════════════

def test_rate_is_strictly_increasing_in_power_on_the_full_range():
    """Floor, not ceiling: a modest grid, stdlib only (no numpy needed for a
    plain Python loop)."""
    n = 200
    pts = [h2_map.P_MAX_W * k / (n - 1) for k in range(n)]
    rates = [h2_map.rate_gps(p) for p in pts]
    for k in range(1, n):
        assert rates[k] > rates[k - 1], (
            "rate_gps is not strictly increasing at P=%.4f -> %.4f "
            "(%.6e -> %.6e)" % (pts[k - 1], pts[k], rates[k - 1], rates[k]))


def test_rate_is_convex_on_the_full_range_second_differences_positive():
    """Convexity: the second finite difference of rate_gps w.r.t. P must be
    positive everywhere on the operating range (excluding the very ends,
    where a coarse difference can catch numerical noise from the table
    interpolation's own linear segments)."""
    n = 400
    h = h2_map.P_MAX_W / (n - 1)
    pts = [h2_map.P_MAX_W * k / (n - 1) for k in range(n)]
    rates = [h2_map.rate_gps(p) for p in pts]
    neg = 0
    for k in range(1, n - 1):
        d2 = rates[k + 1] - 2.0 * rates[k] + rates[k - 1]
        if d2 <= 0.0:
            neg += 1
    # Allow a small number of interior points to read as flat/negative due
    # to the piecewise-linear inverse table's own segment boundaries (the
    # module's own accuracy note: "< 3e-6 A" error, which is not exactly
    # zero) -- but convexity must hold on the overwhelming majority of the
    # grid, not merely "on average".
    assert neg <= 2, (
        "%d of %d interior points were non-convex (second difference <= 0); "
        "expected the H-20 map's convexity to hold essentially everywhere"
        % (neg, n - 2))


def test_eta_lhv_rises_then_falls_with_a_single_peak_near_14p75_w():
    numpy = pytest.importorskip("numpy")
    p_peak, eta_peak = h2_map.efficiency_peak()
    assert p_peak == pytest.approx(14.75, abs=0.5)
    assert eta_peak == pytest.approx(0.433, abs=0.01)

    # Single-peak shape: eta_lhv strictly rises up to (near) p_peak and
    # strictly falls afterward, sampled coarsely on [0, P_MAX_W] (P_MAX_W is
    # ABOVE p_peak, so the falling side is exercised too, without entering
    # the saturated region where eta_lhv over-reads by design).
    n = 60
    pts = numpy.linspace(1e-3, h2_map.P_MAX_W, n)
    etas = [h2_map.eta_lhv(float(p)) for p in pts]
    k_peak = int(numpy.argmax(etas))
    # The sampled peak's power must land near the analytic p_peak.
    assert pts[k_peak] == pytest.approx(p_peak, rel=0.15)
    # Monotone rising before the sampled peak, monotone falling after.
    rising = etas[:k_peak + 1]
    falling = etas[k_peak:]
    assert all(b >= a - 1e-9 for a, b in zip(rising, rising[1:])), \
        "eta_lhv is not monotone rising before the peak"
    assert all(b <= a + 1e-9 for a, b in zip(falling, falling[1:])), \
        "eta_lhv is not monotone falling after the peak"


def test_marginal_gps_per_w_increases_with_operating_power():
    m3 = h2_map.marginal_gps_per_w(3.0)
    m10 = h2_map.marginal_gps_per_w(10.0)
    m20 = h2_map.marginal_gps_per_w(20.0)
    assert 0.0 < m3 < m10 < m20


# ═════════════════════════════════════════════════════════════════════════
# 3. Saturation
# ═════════════════════════════════════════════════════════════════════════

def test_rate_above_p_max_floors_at_the_p_max_value():
    assert h2_map.rate_gps(25.0) == h2_map.rate_gps(h2_map.P_MAX_W)
    assert h2_map.rate_gps(1e6) == h2_map.rate_gps(h2_map.P_MAX_W)


def test_is_saturated_reports_above_and_below_p_max_correctly():
    assert h2_map.is_saturated(25.0) is True
    assert h2_map.is_saturated(20.0) is False
    assert h2_map.is_saturated(h2_map.P_MAX_W) is False   # AT P_MAX, not above
    assert h2_map.is_saturated(h2_map.P_MAX_W + 1e-9) is True


# ═════════════════════════════════════════════════════════════════════════
# 4. Hooks: stack_on and SHUTDOWN_ENABLED
# ═════════════════════════════════════════════════════════════════════════

def test_stack_off_bills_zero_regardless_of_power():
    assert h2_map.rate_gps(5.0, stack_on=False) == 0.0
    assert h2_map.rate_gps(0.0, stack_on=False) == 0.0
    assert h2_map.rate_gps(h2_map.P_MAX_W, stack_on=False) == 0.0


def test_default_shutdown_policy_bills_the_offset_at_zero_power():
    """SHUTDOWN_ENABLED defaults False -- an idling-but-on stack still burns
    the purge/blower offset."""
    assert h2_map.SHUTDOWN_ENABLED is False
    assert h2_map.rate_gps(0.0) == pytest.approx(h2_map.A0_OFFSET_GPS, rel=1e-15)


def test_shutdown_enabled_override_zeros_the_offset_at_zero_power_only():
    assert h2_map.rate_gps(0.0, shutdown_enabled=True) == 0.0
    # The instant power goes positive, even by an infinitesimal amount, the
    # offset (and a hair of Faraday) is billed again.
    assert h2_map.rate_gps(1e-9, shutdown_enabled=True) > h2_map.A0_OFFSET_GPS \
        or h2_map.rate_gps(1e-9, shutdown_enabled=True) == pytest.approx(
            h2_map.A0_OFFSET_GPS, rel=1e-9)
    assert h2_map.rate_gps(1e-9, shutdown_enabled=True) > 0.0


def test_negative_power_behaves_as_zero():
    assert h2_map.rate_gps(-5.0) == pytest.approx(h2_map.A0_OFFSET_GPS, rel=1e-15)
    assert h2_map.rate_gps(-5.0) == h2_map.rate_gps(0.0)
    assert h2_map.current_a(-5.0) == 0.0
    assert h2_map.polarization_v(-1.0) == h2_map.polarization_v(0.0)


# ═════════════════════════════════════════════════════════════════════════
# 5. Vectorized == scalar
# ═════════════════════════════════════════════════════════════════════════

def test_rate_gps_array_matches_scalar_elementwise():
    np = pytest.importorskip("numpy")
    pts = [0.0, 1e-9, 0.5, 3.0, 10.0, 20.28, h2_map.P_MAX_W, 25.0, 1e6, -5.0]
    arr = np.array(pts, dtype=float)
    got = h2_map.rate_gps_array(arr)
    want = np.array([h2_map.rate_gps(p) for p in pts])
    np.testing.assert_allclose(got, want, rtol=1e-12, atol=0.0)


def test_rate_gps_array_stack_on_and_shutdown_hooks_match_scalar():
    np = pytest.importorskip("numpy")
    pts = np.array([0.0, 1.0, 10.0])
    got_off = h2_map.rate_gps_array(pts, stack_on=False)
    np.testing.assert_array_equal(got_off, np.zeros(3))

    got_sd = h2_map.rate_gps_array(pts, shutdown_enabled=True)
    want_sd = np.array([h2_map.rate_gps(float(p), shutdown_enabled=True)
                        for p in pts])
    np.testing.assert_allclose(got_sd, want_sd, rtol=1e-12)

    # Per-element stack_on array (a stage-wise mirror), not just a scalar.
    on_mask = np.array([True, False, True])
    got_mixed = h2_map.rate_gps_array(pts, stack_on=on_mask)
    assert got_mixed[1] == 0.0
    assert got_mixed[0] == pytest.approx(h2_map.rate_gps(0.0), rel=1e-12)
    assert got_mixed[2] == pytest.approx(h2_map.rate_gps(10.0), rel=1e-12)


def test_current_a_array_matches_scalar_elementwise():
    np = pytest.importorskip("numpy")
    pts = [0.0, 1.0, 5.0, 15.0, h2_map.P_MAX_W, 25.0, -3.0]
    arr = np.array(pts, dtype=float)
    got = h2_map.current_a_array(arr)
    want = np.array([h2_map.current_a(p) for p in pts])
    np.testing.assert_allclose(got, want, rtol=1e-9, atol=1e-9)


# ═════════════════════════════════════════════════════════════════════════
# 6. quadratic_fit() and student_form()
# ═════════════════════════════════════════════════════════════════════════

def test_quadratic_fit_constant_term_within_10_percent_of_a0():
    pytest.importorskip("numpy")
    a0, _a1, _a2, max_rel_err = h2_map.quadratic_fit()
    assert a0 == pytest.approx(h2_map.A0_OFFSET_GPS, rel=0.10)
    assert max_rel_err < 0.08


def test_quadratic_fit_reproduces_the_map_within_its_own_stated_error():
    """The fitted quadratic must actually track rate_gps() on the grid within
    max_rel_err, not merely report a small number and diverge -- checked
    directly at a handful of points across [0, QUADRATIC_FIT_P_HI_W]."""
    np = pytest.importorskip("numpy")
    a0, a1, a2, max_rel_err = h2_map.quadratic_fit()
    for p in (0.0, 1.0, 5.0, 10.0, 15.0, h2_map.QUADRATIC_FIT_P_HI_W):
        fit = a0 + a1 * p + a2 * p * p
        real = h2_map.rate_gps(p)
        rel = abs(fit - real) / max(real, 1e-12)
        assert rel <= max_rel_err + 1e-9, (
            "P=%.2f: quadratic fit relative error %.4f exceeds the "
            "reported max_rel_err %.4f" % (p, rel, max_rel_err))


def test_student_form_keys_and_ranges():
    pytest.importorskip("numpy")
    d = h2_map.student_form()
    assert set(d.keys()) == {"a0", "p_peak", "eta_peak"}
    assert d["a0"] == pytest.approx(h2_map.A0_OFFSET_GPS, rel=0.10)
    assert d["p_peak"] == pytest.approx(14.75, abs=0.5)
    assert d["eta_peak"] == pytest.approx(0.433, abs=0.01)
    # p_peak/eta_peak come from efficiency_peak() verbatim, not the
    # parabola's own vertex (module docstring) -- cross-check directly.
    p_peak, eta_peak = h2_map.efficiency_peak()
    assert d["p_peak"] == p_peak
    assert d["eta_peak"] == eta_peak


# ═════════════════════════════════════════════════════════════════════════
# 7. fingerprint() / fingerprint_str()
# ═════════════════════════════════════════════════════════════════════════

def test_fingerprint_is_deterministic():
    a = h2_map.fingerprint()
    b = h2_map.fingerprint()
    assert a == b
    assert h2_map.fingerprint_str() == h2_map.fingerprint_str()


def test_fingerprint_contains_the_map_id():
    fp = h2_map.fingerprint()
    assert fp["map_id"] == "h20-brochure-v1"
    assert fp["map_id"] == h2_map.MAP_ID
    assert "h20-brochure-v1" in h2_map.fingerprint_str()


def test_fingerprint_includes_the_shutdown_flag():
    fp = h2_map.fingerprint()
    assert "shutdown_enabled" in fp
    assert fp["shutdown_enabled"] is False
    assert isinstance(fp["shutdown_enabled"], bool)


def test_fingerprint_changes_when_a_polarization_coefficient_moves(monkeypatch):
    fp_before = h2_map.fingerprint()
    before = h2_map.fingerprint_str()
    monkeypatch.setattr(h2_map, "POLARIZATION_R_OHM",
                        h2_map.POLARIZATION_R_OHM + 0.01)
    fp_after = h2_map.fingerprint()
    after = h2_map.fingerprint_str()
    assert before != after
    # The dict form disagrees on exactly the perturbed field and nothing
    # else (`monkeypatch` restores the module attribute on teardown, so no
    # cleanup is needed here).
    assert fp_after["r_ohm"] != fp_before["r_ohm"]
    diff_keys = {k for k in fp_before if fp_before[k] != fp_after[k]}
    assert diff_keys == {"r_ohm"}


def test_fingerprint_changes_when_shutdown_enabled_flips(monkeypatch):
    before = h2_map.fingerprint_str()
    monkeypatch.setattr(h2_map, "SHUTDOWN_ENABLED", True)
    after = h2_map.fingerprint_str()
    assert before != after
    assert h2_map.fingerprint()["shutdown_enabled"] is True


def test_fingerprint_str_is_a_single_short_stable_string():
    s = h2_map.fingerprint_str()
    assert isinstance(s, str)
    assert "\n" not in s
    # Fixed field order (module docstring): map_id first, shutdown flag last.
    assert s.startswith(h2_map.MAP_ID)
    parts = s.split("|")
    # 10 fields (2026-09-08, review item A8): map_id, v0, b, i0, r, i_pmax,
    # _INV_TABLE_N (7th), k_faraday, a0_offset, shutdown_enabled. The inverse
    # table's grid size joined the fingerprint because it is not physics --
    # it is the grid I(P) is interpolated on -- and raising it moves every
    # returned rate by ~4e-10 g/s, so a DP table is the optimum of the map
    # that was EVALUATED, not merely intended.
    assert len(parts) == 10
    assert parts[6] == str(h2_map._INV_TABLE_N) == "2049"
    assert parts[-1] in ("True", "False")


# ═════════════════════════════════════════════════════════════════════════
# 8. refit_polarization() -- FUNCTIONAL agreement only
# ═════════════════════════════════════════════════════════════════════════

def test_refit_polarization_functional_agreement_not_coefficient_equality():
    """Per the module's own docstring: the (b, i0) valley is flat, so a
    refit does NOT reproduce the stored coefficients -- what must hold is
    that the two curves agree numerically over the operating range, and
    that the stored coefficients' own RMS against the digitized points is
    small."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    fit = h2_map.refit_polarization()
    assert set(fit.keys()) >= {"v0_v", "b_v", "i0_a", "r_ohm", "rms_v", "cost"}

    i_grid = np.linspace(0.0, h2_map.I_PMAX_A, 200)
    v_stored = np.array([h2_map.polarization_v(float(i)) for i in i_grid])
    v_refit = (fit["v0_v"] - fit["b_v"] * np.log1p(i_grid / fit["i0_a"])
              - fit["r_ohm"] * i_grid)
    max_dev = float(np.max(np.abs(v_stored - v_refit)))
    assert max_dev < 0.2, (
        "stored vs refit polarization curves diverge by %.4f V, expected "
        "< 0.2 V (functional agreement, not coefficient equality)" % max_dev)

    assert h2_map.stored_polarization_rms_v() < 0.3


def test_stored_polarization_rms_v_is_stdlib_only_and_matches_the_banner():
    """No numpy/scipy import needed for this one -- it is the STDLIB
    comparison partner the docstring names."""
    rms = h2_map.stored_polarization_rms_v()
    assert rms == pytest.approx(0.2676, abs=0.01)


# ═════════════════════════════════════════════════════════════════════════
# 9. Stdlib-only import path
# ═════════════════════════════════════════════════════════════════════════

def test_h2_map_imports_without_numpy_under_the_stdlib_interpreter():
    """`python -c "import h2_map"` must succeed and must NOT pull numpy into
    sys.modules -- the module docstring's RUNTIME CONTRACT ("numpy is
    imported LAZILY... so importing this module from the plant costs
    nothing"), verified in a FRESH subprocess so an already-imported numpy
    from this test session cannot hide a regression."""
    venv_python = os.path.join(
        os.path.dirname(HERE), ".venv_hil", "Scripts", "python.exe")
    if not os.path.isfile(venv_python):
        pytest.skip(".venv_hil interpreter not present in this checkout")
    code = ("import sys; sys.path.insert(0, %r); import h2_map; "
           "print('numpy' in sys.modules)" % HERE)
    out = subprocess.run([venv_python, "-c", code],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False", (
        "h2_map import pulled numpy into sys.modules under the stdlib "
        "interpreter: stdout=%r stderr=%r" % (out.stdout, out.stderr))


# ═════════════════════════════════════════════════════════════════════════
# 10. The NaN contract (2026-09-08 fix round): NaN RAISES ValueError on
#     every scalar/array entry point; +/-inf does NOT raise (it clamps).
#     `_finite()`'s own docstring is the rationale: this module integrates
#     its own output, so a silently-propagated NaN poisons a whole run's
#     h2_cum_g, a whole DP stage column, or a whole SDP sweep.
# ═════════════════════════════════════════════════════════════════════════

NAN = float("nan")


def test_rate_gps_raises_on_nan_even_with_stack_off():
    """`rate_gps(nan, stack_on=False)` must still raise: `_finite()` runs
    BEFORE the `stack_on` check (h2_map.py's own docstring says so), so the
    refusal does not depend on an unrelated flag."""
    with pytest.raises(ValueError):
        h2_map.rate_gps(NAN)
    with pytest.raises(ValueError):
        h2_map.rate_gps(NAN, stack_on=False)


def test_rate_gps_does_not_raise_on_infinity_it_clamps():
    """+inf clamps to the P_MAX_W/I_PMAX_A floor; -inf clamps to zero power
    -- both are the physically right answers at the two ends of the curve
    (`_finite()`'s docstring), so neither raises."""
    hi = h2_map.rate_gps(float("inf"))
    lo = h2_map.rate_gps(float("-inf"))
    assert hi == pytest.approx(h2_map.rate_gps(h2_map.P_MAX_W))
    assert lo == pytest.approx(h2_map.rate_gps(0.0))
    assert h2_map.is_saturated(float("inf")) is True
    assert h2_map.is_saturated(float("-inf")) is False
    assert h2_map.current_a(float("inf")) == pytest.approx(h2_map.I_PMAX_A)
    assert h2_map.current_a(float("-inf")) == pytest.approx(0.0)


def test_current_a_raises_on_nan():
    with pytest.raises(ValueError):
        h2_map.current_a(NAN)


def test_is_saturated_raises_on_nan():
    """A saturation predicate that answered False for a NaN would let a
    poisoned sample past the one check that exists to catch an
    out-of-range one (is_saturated()'s own docstring)."""
    with pytest.raises(ValueError):
        h2_map.is_saturated(NAN)


def test_eta_lhv_raises_on_nan():
    with pytest.raises(ValueError):
        h2_map.eta_lhv(NAN)


def test_marginal_gps_per_w_raises_on_nan():
    with pytest.raises(ValueError):
        h2_map.marginal_gps_per_w(NAN)
    # The step `dp_w` is also passed through `_finite()`.
    with pytest.raises(ValueError):
        h2_map.marginal_gps_per_w(3.0, dp_w=NAN)


def test_rate_gps_array_raises_on_nan():
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError):
        h2_map.rate_gps_array(np.array([1.0, NAN, 3.0]))
    # Same "raises even with the stack off" contract as the scalar path.
    with pytest.raises(ValueError):
        h2_map.rate_gps_array(np.array([NAN]), stack_on=False)


def test_current_a_array_raises_on_nan():
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError):
        h2_map.current_a_array(np.array([1.0, NAN]))


def test_rate_gps_array_does_not_raise_on_infinity_it_clamps():
    """The array path's contract mirrors the scalar path's exactly."""
    np = pytest.importorskip("numpy")
    out = h2_map.rate_gps_array(np.array([float("inf"), float("-inf")]))
    assert out[0] == pytest.approx(h2_map.rate_gps(h2_map.P_MAX_W))
    assert out[1] == pytest.approx(h2_map.rate_gps(0.0))
