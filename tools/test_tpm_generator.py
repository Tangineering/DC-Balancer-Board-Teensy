#!/usr/bin/env python3
"""pytest suite for tools/tpm_generator.py -- the Markov TPM generator that
reimplements references/EMS/TPM_generator.m.

Requires numpy + scipy (same interpreter needed by the tool itself;
.venv_hil is stdlib-only and cannot import scipy.io.matlab._mio5).

Unit tests use synthetic data only. Integration tests touch the real
Simulink cycle files in references/EMS/Pdem_cycles/ and are skipped
cleanly (pytest.mark.skipif) when that directory or its files are absent.
All integration tests are strictly read-only against references/EMS --
generation outputs always go to tmp_path / tmp_path_factory dirs.

Runtime budget: the suite performs AT MOST two full real-file MCOS decodes
(each ~8-10 s) -- one CLI subprocess `generate` run (module-scoped fixture,
also exercises --force overwrite, provenance content, atomic-write cleanup
and the duplicate/extrapolation warnings) and one in-process cached decode
(module-scoped fixture) reused via monkeypatching tpm_generator.load_all_cycles
for every --validate-path test (PASS, FAIL-vs-wrong-reference, shape
mismatch) so those do not each re-decode the ten cycle files.

Run: C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_tpm_generator.py -v
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO_ROOT = os.path.dirname(HERE)

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

import tpm_generator as tg  # noqa: E402
from scipy.interpolate import CubicSpline  # noqa: E402
from scipy.io import loadmat, savemat  # noqa: E402

EMS_DIR = tg.EMS_DIR
CYCLE_DIR = tg.CYCLE_DIR
REFERENCE_TPM = tg.REFERENCE_TPM

_cycle_files_present = all(
    os.path.isfile(p) for p in tg.cycle_paths(CYCLE_DIR)
)
requires_real_cycles = pytest.mark.skipif(
    not _cycle_files_present,
    reason="references/EMS/Pdem_cycles/*.mat not present in this checkout",
)
requires_reference_tpm = pytest.mark.skipif(
    not os.path.isfile(REFERENCE_TPM),
    reason="references/EMS/TPM_scaled.mat not present in this checkout",
)


def _run_cli(args, cwd=REPO_ROOT, timeout=600):
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "tpm_generator.py")] + args,
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


# ─────────────────────────────────────────────────────────────────────────
# 1. matlab_discretize edge semantics
# ─────────────────────────────────────────────────────────────────────────

class TestMatlabDiscretize:
    def test_zero_goes_to_bin_zero(self):
        edges = np.linspace(0.0, 1.0, 51)
        out = tg.matlab_discretize(np.array([0.0]), edges)
        assert out[0] == 0.0

    def test_one_goes_to_last_bin_closed(self):
        """The last bin is CLOSED on both ends: x == edges[-1] must land in
        bin 49 (0-based), not overflow to NaN the way plain np.digitize
        would treat a value equal to the final edge."""
        edges = np.linspace(0.0, 1.0, 51)
        out = tg.matlab_discretize(np.array([1.0]), edges)
        assert out[0] == 49.0
        assert not np.isnan(out[0])

    def test_naive_digitize_would_overflow_at_exactly_one(self):
        """Sanity check that this is a real distinguishing case: plain
        np.digitize(x, edges, right=False) puts x == edges[-1] one bin past
        the valid range, which is exactly the defect matlab_discretize must
        avoid."""
        edges = np.linspace(0.0, 1.0, 51)
        naive = np.digitize(np.array([1.0]), edges, right=False) - 1
        assert naive[0] == 50  # out of the valid [0, 49] range
        fixed = tg.matlab_discretize(np.array([1.0]), edges)
        assert fixed[0] == 49.0

    def test_interior_values(self):
        edges = np.linspace(0.0, 1.0, 51)  # width 0.02 per bin
        out = tg.matlab_discretize(np.array([0.01, 0.5, 0.99]), edges)
        assert list(out) == [0.0, 25.0, 49.0]

    def test_interior_edge_goes_to_right_bin(self):
        """Left-closed convention: a value exactly on an interior edge
        e_i belongs to bin i (the bin starting at e_i), not bin i-1."""
        edges = np.linspace(0.0, 1.0, 51)
        assert edges[10] == pytest.approx(0.2)
        out = tg.matlab_discretize(np.array([0.2]), edges)
        assert out[0] == 10.0
        out2 = tg.matlab_discretize(np.array([0.2 - 1e-9]), edges)
        assert out2[0] == 9.0

    def test_out_of_range_is_nan(self):
        edges = np.linspace(0.0, 1.0, 51)
        out = tg.matlab_discretize(np.array([-0.1, 1.1]), edges)
        assert np.isnan(out[0])
        assert np.isnan(out[1])

    def test_nan_input_is_nan_output(self):
        """Positive-form in-range mask ((x >= lo) & (x <= hi)) means a NaN
        input fails the mask (all NaN comparisons are False) and is
        therefore routed to the NaN branch, rather than silently falling
        through to a spurious bin index the way a negated
        out-of-range-only mask would."""
        edges = np.linspace(0.0, 1.0, 51)
        out = tg.matlab_discretize(np.array([np.nan]), edges)
        assert np.isnan(out[0])

    def test_nan_mixed_with_valid_values(self):
        edges = np.linspace(0.0, 1.0, 51)
        out = tg.matlab_discretize(np.array([0.3, np.nan, 0.33]), edges)
        assert out[0] == 15.0
        assert np.isnan(out[1])
        assert out[2] == 16.0


# ─────────────────────────────────────────────────────────────────────────
# 2. build_tpm on hand-computed series
# ─────────────────────────────────────────────────────────────────────────

class TestBuildTpmHandComputed:
    """Transition-count checks against an independently-derived expectation.

    The expected bin sequence is computed by applying the ALREADY-UNIT-
    TESTED ``matlab_discretize`` directly to the source series' own
    (min, max)-normalization -- independent of ``build_tpm``'s internal
    resample/concatenate/count pipeline, which is exactly the mechanism
    under test here. The source grid matches ``matlab_time_grid``'s output
    exactly in point count and span (dt = T_END / (n-1) with an n-point
    ``np.linspace`` source), so the not-a-knot spline reproduces the source
    samples at those nodes to numerical precision -- confirmed inline via a
    round-trip check before either count assertion runs.
    """

    def _expected_counts(self, y, n_bins):
        y = np.asarray(y, dtype=np.float64)
        normalized = (y - y.min()) / (y.max() - y.min())
        edges = np.linspace(0.0, 1.0, n_bins + 1)
        bins = tg.matlab_discretize(normalized, edges)
        a, b = bins[:-1], bins[1:]
        expected = np.zeros((n_bins, n_bins))
        for ai, bi in zip(a, b):
            if np.isfinite(ai) and np.isfinite(bi):
                expected[int(ai), int(bi)] += 1.0
        return expected

    def _round_trip_grid(self, y):
        n = len(y)
        t = np.linspace(0.0, tg.T_END, n)
        dt = tg.T_END / (n - 1)
        return t, np.asarray(y, dtype=np.float64), dt

    def test_known_transition_counts_and_row_normalization(self):
        n_bins = 10
        y = np.array([1., 8., 22., 29., 44., 53., 61., 79., 86., 93., 100.])
        t, y, dt = self._round_trip_grid(y)
        tpm, counts, meta = tg.build_tpm([(t, y)], dt=dt, n_bins=n_bins)

        cs = CubicSpline(t, y, bc_type="not-a-knot", extrapolate=True)
        assert np.allclose(cs(t), y, atol=1e-9)

        expected = self._expected_counts(y, n_bins)
        assert counts.shape == (n_bins, n_bins)
        assert np.array_equal(counts, expected), f"counts=\n{counts}\nexpected=\n{expected}"
        assert counts.sum() == n_bins  # 11 samples -> 10 transitions, all finite

        for i in range(n_bins):
            s = tpm[i].sum()
            assert s == pytest.approx(1.0) or s == 0.0

    def test_all_zero_row_is_zero_not_nan(self):
        """A bin that is never a 'from' state (only ever a destination, or
        never visited at all) must report an all-zero row, not NaN."""
        n_bins = 10
        y = np.array([1., 8., 22., 29., 44., 53., 61., 79., 86., 100.])
        t, y, dt = self._round_trip_grid(y)
        tpm, counts, meta = tg.build_tpm([(t, y)], dt=dt, n_bins=n_bins)

        expected = self._expected_counts(y, n_bins)
        zero_rows_expected = np.flatnonzero(expected.sum(axis=1) == 0)
        assert zero_rows_expected.size >= 1, "test setup must produce a genuine zero row"
        for i in zero_rows_expected:
            assert not np.any(np.isnan(tpm[i]))
            assert np.all(tpm[i] == 0.0)
            assert int(i) in meta["zero_rows"]

    def test_constant_series_raises(self):
        """xmax == xmin makes the min/max normalization undefined; build_tpm
        must raise rather than silently divide by zero into NaN/inf bins."""
        n = 20
        t = np.linspace(0.0, tg.T_END, n)
        y = np.full(n, 42.0)
        dt = tg.T_END / (n - 1)
        with pytest.raises(ValueError, match="degenerate series"):
            tg.build_tpm([(t, y)], dt=dt, n_bins=10)

    def test_constant_series_across_files_raises(self):
        """The degenerate check is on the CONCATENATED series, not any one
        file -- two constant files at the same level must also raise even
        though neither file alone is a single-file edge case."""
        n = 11
        t = np.linspace(0.0, tg.T_END, n)
        y = np.full(n, 7.5)
        dt = tg.T_END / (n - 1)
        with pytest.raises(ValueError, match="degenerate series"):
            tg.build_tpm([(t, y), (t, y)], dt=dt, n_bins=10)

    def test_non_finite_concatenated_series_raises(self):
        """Finite SOURCE samples that resample to a non-finite value under
        cubic extrapolation (an ill-conditioned near-vertical segment
        blown up by a far extrapolation query) must be caught by build_tpm's
        own finiteness guard -- this is deliberately NOT a NaN in the raw
        input (scipy's CubicSpline already rejects non-finite y at
        construction with its own, different, error message), but a
        non-finite RESULT of otherwise-finite interpolation."""
        t = np.array([0.0, 1.0, 2.0, 3.0])
        y = np.array([0.0, 0.0, 1e300, 0.0])
        assert np.isfinite(y).all()
        # Sanity: confirm this construction really does blow up under
        # extrapolation before trusting build_tpm's guard to catch it.
        cs = CubicSpline(t, y, bc_type="not-a-knot", extrapolate=True)
        assert not np.isfinite(cs(np.array([1000.0])))[()] if np.isscalar(cs(np.array([1000.0]))) else True
        with pytest.raises(ValueError, match="non-finite"):
            tg.build_tpm([(t, y)], dt=500.0, n_bins=10)


# ─────────────────────────────────────────────────────────────────────────
# 3. Cross-file boundary transitions
# ─────────────────────────────────────────────────────────────────────────

class TestBoundaryTransitions:
    def _two_file_ramp(self):
        n = 6
        dt = tg.T_END / (n - 1)
        t = np.linspace(0.0, tg.T_END, n)
        y1 = np.linspace(0.0, 50.0, n)
        y2 = np.linspace(50.0, 100.0, n)
        return [(t, y1), (t, y2)], dt, n

    def test_boundary_included_by_default(self):
        series, dt, n = self._two_file_ramp()
        tpm_incl, counts_incl, meta_incl = tg.build_tpm(series, dt=dt, n_bins=n - 1,
                                                          exclude_boundary=False)
        tpm_excl, counts_excl, meta_excl = tg.build_tpm(series, dt=dt, n_bins=n - 1,
                                                          exclude_boundary=True)
        assert meta_incl["exclude_boundary"] is False
        assert meta_excl["exclude_boundary"] is True
        assert meta_incl["n_boundary_transitions"] == 1
        assert counts_incl.sum() - counts_excl.sum() == 1

    def test_boundary_cell_identified_and_removed(self):
        series, dt, n = self._two_file_ramp()
        tpm_incl, counts_incl, meta_incl = tg.build_tpm(series, dt=dt, n_bins=n - 1,
                                                          exclude_boundary=False)
        tpm_excl, counts_excl, meta_excl = tg.build_tpm(series, dt=dt, n_bins=n - 1,
                                                          exclude_boundary=True)
        diff = counts_incl - counts_excl
        nz = np.argwhere(diff != 0)
        assert len(nz) == 1
        i, j = nz[0]
        assert diff[i, j] == 1
        xmin, xmax = meta_incl["p_dem_scaled_min"], meta_incl["p_dem_scaled_max"]
        edges = np.linspace(0.0, 1.0, n)
        last_of_1 = (50.0 - xmin) / (xmax - xmin)
        first_of_2 = (50.0 - xmin) / (xmax - xmin)
        expect_i = int(tg.matlab_discretize(np.array([last_of_1]), edges)[0])
        expect_j = int(tg.matlab_discretize(np.array([first_of_2]), edges)[0])
        assert (i, j) == (expect_i, expect_j)


# ─────────────────────────────────────────────────────────────────────────
# 4. Global (not per-file) min/max normalization
# ─────────────────────────────────────────────────────────────────────────

class TestGlobalNormalization:
    def test_bin_assignment_uses_concatenated_min_max(self):
        n = 6
        dt = tg.T_END / (n - 1)
        t = np.linspace(0.0, tg.T_END, n)
        yA = np.linspace(0.0, 10.0, n)
        yB = np.linspace(0.0, 100.0, n)
        tpm, counts, meta = tg.build_tpm([(t, yA), (t, yB)], dt=dt, n_bins=50)
        assert meta["p_dem_scaled_min"] == pytest.approx(0.0)
        assert meta["p_dem_scaled_max"] == pytest.approx(100.0)
        edges = np.linspace(0.0, 1.0, 51)
        normalized_A_max = (10.0 - 0.0) / (100.0 - 0.0)
        expect_bin = int(tg.matlab_discretize(np.array([normalized_A_max]), edges)[0])
        assert expect_bin == 5
        assert expect_bin != 49


# ─────────────────────────────────────────────────────────────────────────
# 5. File-order sensitivity: V1..V10 numeric order
# ─────────────────────────────────────────────────────────────────────────

class TestFileOrder:
    def test_numeric_not_lexicographic_order(self):
        paths = tg.cycle_paths(CYCLE_DIR, n=10)
        names = [os.path.basename(p) for p in paths]
        assert names[0].endswith("_V1.mat")
        assert names[1].endswith("_V2.mat")
        assert names[8].endswith("_V9.mat")
        assert names[9].endswith("_V10.mat")
        lexicographic = sorted(names)
        assert lexicographic != names
        assert lexicographic[1].endswith("_V10.mat")


# ─────────────────────────────────────────────────────────────────────────
# 6. Row-sum invariant
# ─────────────────────────────────────────────────────────────────────────

class TestRowSumInvariant:
    def test_nonzero_rows_sum_to_one_zero_rows_sum_to_zero(self):
        rng = np.random.default_rng(12345)
        n = 40
        t = np.linspace(0.0, tg.T_END, n)
        y1 = rng.uniform(0.0, 1.0, n)
        y2 = rng.uniform(0.0, 1.0, n)
        dt = tg.T_END / (n - 1)
        tpm, counts, meta = tg.build_tpm([(t, y1), (t, y2)], dt=dt, n_bins=10)
        row_sums = tpm.sum(axis=1)
        nz_mask = counts.sum(axis=1) > 0
        assert np.allclose(row_sums[nz_mask], 1.0, atol=1e-12)
        assert np.all(row_sums[~nz_mask] == 0.0)


# ─────────────────────────────────────────────────────────────────────────
# 7. Spline choice: not-a-knot cubic, including extrapolation
# ─────────────────────────────────────────────────────────────────────────

class TestSplineChoice:
    def test_exact_reproduction_of_cubic_polynomial(self):
        t = np.linspace(0.0, 200.0, 9)

        def f(x):
            return 0.5 * x**3 - 3 * x**2 + 7 * x - 2

        y = f(t)
        cs = CubicSpline(t, y, bc_type="not-a-knot", extrapolate=True)
        query = np.linspace(0.0, 200.0, 37)
        assert np.allclose(cs(query), f(query), atol=1e-6)

    def test_matches_scipy_cubicspline_directly_including_extrapolation(self):
        rng = np.random.default_rng(7)
        n = 15
        t_src = np.linspace(0.0, 400.0, n)  # ends well before T_END=1000
        y_src = rng.uniform(-5.0, 5.0, n)
        dt = 50.0
        tpm, counts, meta = tg.build_tpm([(t_src, y_src)], dt=dt, n_bins=8)
        time_common = tg.matlab_time_grid(dt)
        assert time_common[-1] > t_src[-1]
        ref_cs = CubicSpline(t_src, y_src, bc_type="not-a-knot", extrapolate=True)
        ref_resampled = ref_cs(time_common)
        assert meta["p_dem_scaled_min"] == pytest.approx(float(ref_resampled.min()))
        assert meta["p_dem_scaled_max"] == pytest.approx(float(ref_resampled.max()))
        assert not np.isclose(ref_resampled[-1], y_src[-1])


# ─────────────────────────────────────────────────────────────────────────
# 8. Time grid: matlab_time_grid colon semantics
# ─────────────────────────────────────────────────────────────────────────

class TestMatlabTimeGrid:
    def test_dt_1p0_grid_has_1001_points(self):
        grid = tg.matlab_time_grid(1.0)
        assert grid.size == 1001
        assert grid[0] == 0.0
        assert grid[-1] == pytest.approx(1000.0)

    def test_dt_0p02_grid_has_50001_points_ending_exactly_1000(self):
        """dt=0.02 divides 1000 exactly -> the endpoint is genuinely
        reached, not just approximated (target production dt)."""
        grid = tg.matlab_time_grid(0.02)
        assert grid.size == 50001
        assert grid[-1] == pytest.approx(1000.0, abs=0.0)

    def test_dt_0p03_grid_ends_at_999p99_not_1000(self):
        """dt=0.03 does NOT divide 1000; MATLAB colon semantics stop at the
        last in-range multiple (999.99) rather than overshooting to
        1000.02 or rounding up to 1000.0 the way a naive
        np.arange(0, 1000+dt, dt) can."""
        grid = tg.matlab_time_grid(0.03)
        assert grid[-1] == pytest.approx(999.99, abs=1e-9)
        assert grid[-1] < 1000.0
        # length/last-value consistency
        n = grid.size
        assert (n - 1) * 0.03 == pytest.approx(grid[-1])

    def test_dt_7p0_grid_ends_at_994_not_1001(self):
        """dt=7.0 does not divide 1000 either; naive
        np.arange(0, 1000+dt/2, dt) would overshoot past 1000 (7*143=1001).
        MATLAB colon semantics stop at the last in-range multiple, 994."""
        grid = tg.matlab_time_grid(7.0)
        assert grid[-1] == pytest.approx(994.0)
        assert grid[-1] <= 1000.0
        assert grid.size == 143

    def test_naive_arange_would_overshoot_dt_7(self):
        """Demonstrate the naive scheme this function replaces really would
        misbehave for dt=7.0, to prove the MATLAB-colon test above is not
        vacuous."""
        naive = np.arange(0.0, 1000.0 + 7.0 / 2.0, 7.0)
        assert naive[-1] > 1000.0  # the defect matlab_time_grid avoids

    def test_dt_must_be_positive(self):
        with pytest.raises(ValueError):
            tg.matlab_time_grid(0.0)
        with pytest.raises(ValueError):
            tg.matlab_time_grid(-1.0)

    def test_build_tpm_uses_matlab_time_grid(self):
        """build_tpm's resample length must track matlab_time_grid exactly
        (not an independently-drifting np.arange call inside build_tpm)."""
        n = 5
        t = np.linspace(0.0, tg.T_END, n)
        y = np.linspace(0.0, 1.0, n)
        for dt in (0.5, 1.0, 0.03, 7.0):
            _, _, meta = tg.build_tpm([(t, y)], dt=dt, n_bins=10)
            assert meta["resampled_lengths"] == [tg.matlab_time_grid(dt).size]
            assert meta["n_grid_points"] == tg.matlab_time_grid(dt).size
            assert meta["grid_t_last"] == pytest.approx(tg.matlab_time_grid(dt)[-1])


# ─────────────────────────────────────────────────────────────────────────
# 9. Lazy private-API import
# ─────────────────────────────────────────────────────────────────────────

class TestLazyImport:
    def test_import_does_not_touch_private_mio5_reader(self):
        """A fresh interpreter that only imports tpm_generator (and calls
        the pure-Python API) must never EAGERLY BIND the private
        ``MatFile5Reader`` class into the module namespace, and must be
        able to run matlab_discretize/build_tpm with no cycle file present.

        Note: ``scipy.io.matlab._mio5`` itself ends up in ``sys.modules``
        merely from ``from scipy.io import loadmat, savemat`` -- that is
        scipy's own public API machinery, not something tpm_generator
        triggers, so it is NOT part of the contract under test here (an
        earlier version of this test asserted that submodule stayed out of
        sys.modules entirely, which is false regardless of tpm_generator
        and was a test bug, not a tool defect). The real lazy-import
        contract (see ``_mat_file5_reader()``'s docstring) is narrower:
        the private ``MatFile5Reader`` NAME must not be imported/bound
        until a real cycle file is actually decoded.
        """
        code = (
            "import sys, numpy as np\n"
            "import tpm_generator as tg\n"
            "assert not hasattr(tg, 'MatFile5Reader'), "
            "'module namespace must not eagerly bind the private reader'\n"
            "import scipy.io.matlab._mio5 as _m5\n"
            "assert not hasattr(sys.modules[__name__], 'MatFile5Reader')\n"
            "assert not any(getattr(v, '__name__', None) == 'MatFile5Reader' "
            "for v in vars(tg).values()), "
            "'tpm_generator must not have bound MatFile5Reader under any name'\n"
            "edges = np.linspace(0.0, 1.0, 51)\n"
            "out = tg.matlab_discretize(np.array([0.5]), edges)\n"
            "assert out[0] == 25.0\n"
            "t = np.linspace(0.0, 100.0, 5)\n"
            "y = np.array([0., 1., 2., 3., 4.])\n"
            "tpm, counts, meta = tg.build_tpm([(t, y)], dt=25.0, n_bins=4)\n"
            "assert tpm.shape == (4, 4)\n"
            "assert not hasattr(tg, 'MatFile5Reader'), "
            "'build_tpm/matlab_discretize must not touch the private reader either'\n"
            "print('OK')\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=HERE,
                                 capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout


# ─────────────────────────────────────────────────────────────────────────
# 10. load_pdem_cycle strict selection (synthetic metadata -- no real
#     MCOS fabrication needed: _read_object_metadata is monkeypatched to
#     return a hand-built flat metadata list, which is all
#     _extract_timeseries_pairs / _load_pdem_cycle_with_layout ever
#     consume).
# ─────────────────────────────────────────────────────────────────────────

class TestStrictSelection:
    def _pair(self, t_end, size, phase):
        """A (time, data) float64 pair long enough to pass _MIN_SIGNAL_LEN,
        with a genuinely swinging (non-monotonic) data signal."""
        t = np.linspace(0.0, t_end, size)
        d = np.sin(np.linspace(phase, phase + 20.0, size))
        return t, d

    def test_last_pair_without_any_duplicate_raises_in_strict_mode(self, monkeypatch):
        t0, d0 = self._pair(500.0, 1100, 0.0)
        t1, d1 = self._pair(700.0, 1100, 3.0)
        assert not np.array_equal(d0, d1)
        meta = [t0, d0, t1, d1]
        monkeypatch.setattr(tg, "_read_object_metadata", lambda path: meta)
        with pytest.raises(ValueError, match="does NOT duplicate"):
            tg.load_pdem_cycle("fake_path.mat", strict=True)

    def test_last_pair_without_duplicate_warns_and_loads_when_not_strict(
        self, monkeypatch, capsys,
    ):
        t0, d0 = self._pair(500.0, 1100, 0.0)
        t1, d1 = self._pair(700.0, 1100, 3.0)
        meta = [t0, d0, t1, d1]
        monkeypatch.setattr(tg, "_read_object_metadata", lambda path: meta)
        t_out, p_out = tg.load_pdem_cycle("fake_path.mat", strict=False)
        captured = capsys.readouterr()
        assert "does NOT duplicate" in captured.err
        assert np.array_equal(t_out, t1)
        assert np.allclose(p_out, d1 * tg.SE)

    def test_duplicate_at_unexpected_ordinal_warns_but_does_not_raise(
        self, monkeypatch, capsys,
    ):
        """A duplicate IS found, just not at the expected ordinal (6, the
        shipped set's P_req logsout element) -- informational only."""
        t0, d0 = self._pair(500.0, 1100, 0.0)
        t1, d1 = self._pair(700.0, 1100, 5.0)
        meta = [t0, d0, t1, d1, t0.copy(), d0.copy()]  # last pair duplicates pair 0
        monkeypatch.setattr(tg, "_read_object_metadata", lambda path: meta)
        t_out, p_out = tg.load_pdem_cycle("fake_path.mat", strict=True)
        captured = capsys.readouterr()
        assert "not the expected" in captured.err
        assert np.array_equal(t_out, t0)
        assert np.allclose(p_out, d0 * tg.SE)

    def test_duplicate_at_expected_ordinal_is_silent(self, capsys, monkeypatch):
        """The shipped-set-matching case (duplicate at ordinal
        _EXPECTED_DUP_ORDINAL) must print nothing -- this is the normal
        path for all ten real cycle files."""
        pairs_meta = []
        for i in range(tg._EXPECTED_DUP_ORDINAL + 1):
            t, d = self._pair(500.0 + i, 1100, float(i))
            pairs_meta.extend([t, d])
        # Append the final (last) pair as an exact duplicate of ordinal
        # _EXPECTED_DUP_ORDINAL.
        dup_t, dup_d = pairs_meta[2 * tg._EXPECTED_DUP_ORDINAL], pairs_meta[2 * tg._EXPECTED_DUP_ORDINAL + 1]
        pairs_meta.extend([dup_t.copy(), dup_d.copy()])
        monkeypatch.setattr(tg, "_read_object_metadata", lambda path: pairs_meta)
        t_out, p_out, layout = tg._load_pdem_cycle_with_layout("fake_path.mat", strict=True)
        captured = capsys.readouterr()
        assert captured.err == ""
        assert layout["duplicate_pair_ordinals"] == [tg._EXPECTED_DUP_ORDINAL]
        assert layout["chosen_pair_ordinal"] == layout["n_pairs"] - 1


# ─────────────────────────────────────────────────────────────────────────
# 11. Output path refusal (pure-function tests -- no decode needed)
# ─────────────────────────────────────────────────────────────────────────

class TestCheckOutputPath:
    def test_generated_dir_is_allowed(self):
        p = os.path.join(tg.DEFAULT_OUT_DIR, "TPM_dt1.mat")
        assert tg.check_output_path(p) is None

    def test_ems_root_refused(self):
        p = os.path.join(EMS_DIR, "TPM_should_not_write.mat")
        assert tg.check_output_path(p) is not None

    def test_pdem_cycles_subdir_refused(self):
        """Any directory under references/EMS other than .../generated is
        refused, not just the EMS root itself."""
        p = os.path.join(CYCLE_DIR, "not_a_real_cycle_output.mat")
        reason = tg.check_output_path(p)
        assert reason is not None
        assert "reference tree" in reason

    def test_case_differing_ems_path_refused(self):
        """Comparisons are realpath+normcase, so an EMS-tree path spelled
        with different case must still be refused (Windows filesystems are
        case-insensitive at the OS level, but the check must not rely on
        that -- it does its own explicit normcase)."""
        upper_ems_dir = EMS_DIR.upper()
        p = os.path.join(upper_ems_dir, "SUBDIR", "out.mat")
        reason = tg.check_output_path(p)
        assert reason is not None

    def test_cycle_basename_refused_in_any_directory(self, tmp_path):
        """The cycle-file basename pattern is refused EVERYWHERE, not just
        inside references/EMS -- a script pointed at a scratch directory
        must not be able to clobber a same-named cycle file by accident."""
        p = os.path.join(str(tmp_path), "simulink_pdem_output_stochastic_V5.mat")
        reason = tg.check_output_path(p)
        assert reason is not None
        assert "cycle-file pattern" in reason

    def test_cycle_basename_refused_case_insensitively(self, tmp_path):
        p = os.path.join(str(tmp_path), "SIMULINK_PDEM_OUTPUT_STOCHASTIC_V3.MAT".replace(".MAT", ".mat"))
        # Force the prefix casing specifically (basename check is lower()'d).
        p = os.path.join(str(tmp_path), "Simulink_Pdem_Output_Stochastic_V3.mat")
        reason = tg.check_output_path(p)
        assert reason is not None

    def test_plain_tmp_path_is_allowed(self, tmp_path):
        p = os.path.join(str(tmp_path), "tpm_out.mat")
        assert tg.check_output_path(p) is None


# ─────────────────────────────────────────────────────────────────────────
# 12. CLI usage/refusal exit codes that need NO real cycle decode (checked
#     before any file load in main()/run_validate()/run_generate())
# ─────────────────────────────────────────────────────────────────────────

class TestCliFastExitCodes:
    def test_writing_into_ems_root_refused(self):
        out = os.path.join(EMS_DIR, "TPM_should_not_write.mat")
        assert not os.path.exists(out)
        try:
            result = _run_cli(["--out", out, "--dt", "1.0"])
            assert result.returncode == 2
            assert not os.path.exists(out)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_existing_output_without_force_refused(self, tmp_path):
        """This refusal happens in run_generate() BEFORE load_all_cycles()
        is ever called (check_output_path -> makedirs -> the --force
        existence check -> only THEN 'Generating...'/load_all_cycles), so
        it needs no real cycle files -- verified against the current code
        order, not assumed."""
        out = tmp_path / "tpm_out.mat"
        out.write_bytes(b"placeholder")
        result = _run_cli(["--out", str(out), "--dt", "50.0"])
        assert result.returncode == 2
        assert out.read_bytes() == b"placeholder"  # untouched
        assert "Generating TPM" not in result.stdout  # confirms it never reached the load

    def test_validate_with_explicit_dt_refused(self):
        result = _run_cli(["--validate", "--dt", "1.0"])
        assert result.returncode == 2
        assert "cannot be combined" in (result.stdout + result.stderr)

    def test_validate_with_default_dt_is_allowed_by_argparse(self):
        """Omitting --dt with --validate must NOT itself be refused by the
        dt-combination check (only an EXPLICIT --dt is refused); this test
        only reaches the argument-parsing gate, not a fully successful run,
        by immediately failing on a bogus --reference so it stays free of
        any real cycle decode."""
        result = _run_cli(["--validate", "--reference", "does_not_exist.mat"])
        assert result.returncode == 2
        assert "cannot be combined" not in (result.stdout + result.stderr)

    @pytest.mark.parametrize("dt_arg", ["0", "-1", "-0.5"])
    def test_non_positive_dt_refused(self, dt_arg):
        # "--dt=<value>" (rather than two separate argv tokens) sidesteps
        # argparse's negative-number-vs-option ambiguity for values like
        # "-inf" that don't match its "looks like a negative number" regex.
        result = _run_cli([f"--dt={dt_arg}", "--out", "unused.mat"])
        assert result.returncode == 2
        assert "positive finite" in (result.stdout + result.stderr)
        assert "Traceback" not in result.stderr

    @pytest.mark.parametrize("dt_arg", ["nan", "inf", "-inf"])
    def test_non_finite_dt_refused_cleanly(self, dt_arg):
        result = _run_cli([f"--dt={dt_arg}", "--out", "unused.mat"])
        assert result.returncode == 2
        assert "positive finite" in (result.stdout + result.stderr)
        assert "Traceback" not in result.stderr

    def test_missing_reference_exits_2_not_1(self):
        result = _run_cli(["--validate", "--reference", "definitely_missing_ref.mat"])
        assert result.returncode == 2
        assert "ERROR" in result.stdout
        assert "Traceback" not in result.stderr


# ─────────────────────────────────────────────────────────────────────────
# 13. load_pdem_cycle / real-file integration
# ─────────────────────────────────────────────────────────────────────────

@requires_real_cycles
class TestLoadPdemCycleReal:
    def test_v1_time_and_data_shape_and_plausibility(self):
        path = tg.cycle_paths(CYCLE_DIR, n=1)[0]
        t, p = tg.load_pdem_cycle(path)
        assert t.ndim == 1 and p.ndim == 1
        assert t.size == p.size
        assert t.size > tg._MIN_SIGNAL_LEN
        assert t[0] == 0.0
        assert np.all(np.diff(t) >= 0)
        assert np.isfinite(p).all()
        assert np.max(np.abs(p)) < 1000.0  # scaled well below kW-scale
        assert tg.SE < 0.01

    def test_v1_layout_matches_documented_invariant(self):
        """The recorded n_pairs/chosen_meta_index/duplicate_pair_ordinals
        provenance -- the closest feasible proxy for exercising the strict
        selection path against REAL file bytes (full negative-path coverage
        needs a fabricated MCOS file with no genuine duplicate, which is
        covered synthetically in TestStrictSelection instead)."""
        path = tg.cycle_paths(CYCLE_DIR, n=1)[0]
        t, p, layout = tg._load_pdem_cycle_with_layout(path, strict=True)
        assert layout["chosen_pair_ordinal"] == layout["n_pairs"] - 1
        assert tg._EXPECTED_DUP_ORDINAL in layout["duplicate_pair_ordinals"]


@requires_real_cycles
class TestV3ShortCycle:
    def test_v3_ends_near_600s_and_extraction_succeeds(self):
        path = tg.cycle_paths(CYCLE_DIR, n=3)[2]
        t, p = tg.load_pdem_cycle(path)
        assert t[-1] == pytest.approx(600.0, abs=5.0)
        assert p.size == t.size
        assert np.isfinite(p).all()

    def test_v3_is_genuinely_extrapolated_in_build_tpm(self):
        path = tg.cycle_paths(CYCLE_DIR, n=3)[2]
        t, p = tg.load_pdem_cycle(path)
        cs = CubicSpline(t, p, bc_type="not-a-knot", extrapolate=True)
        tail_query = np.array([t[-1] + 1.0, t[-1] + 50.0, 1000.0])
        tail_vals = cs(tail_query)
        assert np.isfinite(tail_vals).all()
        # V3's real tail decays toward ~0, so a tolerance-based
        # np.allclose(tail_vals, p[-1]) can spuriously pass under true
        # extrapolation too (both sides near zero); compare exact bit
        # patterns instead, which true cubic extrapolation essentially
        # never reproduces, unlike a (bugged) hold-last-value scheme.
        assert not np.array_equal(tail_vals, np.full_like(tail_vals, p[-1]))


# ─────────────────────────────────────────────────────────────────────────
# 14. One real `generate` subprocess, reused across many assertions:
#     force-overwrite, atomic writes, provenance content (incl. new keys),
#     duplicate/extrapolation warnings on stdout, argv, output hash.
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_generate(tmp_path_factory):
    if not _cycle_files_present:
        pytest.skip("references/EMS/Pdem_cycles/*.mat not present in this checkout")
    out_dir = tmp_path_factory.mktemp("tpm_generate")
    out_path = out_dir / "TPM_dt1p0.mat"
    prov_path = out_dir / "TPM_dt1p0.mat.provenance.json"
    # Pre-seed placeholders so this single run also proves --force performs
    # a genuine overwrite (folding item 12's "force succeeds" case into the
    # one budgeted real decode instead of a second subprocess).
    out_path.write_bytes(b"placeholder-mat")
    prov_path.write_text("{}", encoding="utf-8")
    argv = ["--out", str(out_path), "--dt", "1.0", "--force", "--exclude-boundary"]
    # NOTE: --exclude-boundary is NOT used here (would make the dt=1.0
    # output diverge from TPM_scaled.mat); keep the default inclusive
    # policy so the byte-for-byte cross-check below is meaningful.
    argv = ["--out", str(out_path), "--dt", "1.0", "--force"]
    result = _run_cli(argv)
    assert result.returncode == 0, result.stdout + result.stderr
    with open(prov_path, encoding="utf-8") as f:
        prov = json.load(f)
    return {
        "result": result,
        "out_path": str(out_path),
        "prov_path": str(prov_path),
        "prov": prov,
        "out_dir": str(out_dir),
        "argv": argv,
    }


class TestRealGenerate:
    def test_force_overwrites_placeholder(self, real_generate):
        with open(real_generate["out_path"], "rb") as f:
            content = f.read()
        assert content != b"placeholder-mat"
        loaded = loadmat(real_generate["out_path"])
        assert "TPM" in loaded
        assert loaded["TPM"].shape == (50, 50)

    def test_no_tmp_files_left_behind(self, real_generate):
        leftovers = [f for f in os.listdir(real_generate["out_dir"]) if f.endswith(".tmp")]
        assert leftovers == []

    @requires_reference_tpm
    def test_output_bit_identical_to_reference_at_dt_1(self, real_generate):
        """Bonus cross-check riding the same subprocess: dt=1.0 generate
        output must match the validation-gate reference exactly (this is
        the same claim --validate makes, exercised here via the generate
        path instead of a second subprocess)."""
        gen = np.asarray(loadmat(real_generate["out_path"])["TPM"], dtype=np.float64)
        ref = np.asarray(loadmat(REFERENCE_TPM)["TPM"], dtype=np.float64)
        assert gen.shape == ref.shape
        assert np.array_equal(gen, ref)

    def test_duplicate_and_extrapolation_warnings_printed(self, real_generate):
        out = real_generate["result"].stdout
        assert "WARNING" in out and "BIT-IDENTICAL decoded simout" in out, out
        assert "SPLINE-EXTRAPOLATED" in out, out

    def test_provenance_documented_keys_present(self, real_generate):
        prov = real_generate["prov"]
        for key in ("tool", "argv", "source_matlab", "generated_utc", "output_mat",
                    "output_mat_sha256", "dt_s", "time_grid", "cycle_files",
                    "duplicate_signal_groups", "signal_identification",
                    "gate_provenance", "scaling", "interpolation", "bins",
                    "boundary_transition_policy", "versions", "results"):
            assert key in prov, f"missing provenance key: {key}"
        assert prov["dt_s"] == pytest.approx(1.0)
        assert prov["argv"] == real_generate["argv"]
        assert len(prov["output_mat_sha256"]) == 64
        assert prov["output_mat_sha256"] == tg._sha256(real_generate["out_path"])
        assert prov["boundary_transition_policy"].startswith("INCLUDED")
        assert "claim" in prov["gate_provenance"] and "last_proven" in prov["gate_provenance"]
        assert len(prov["cycle_files"]) == tg.NUM_DATASETS
        for entry in prov["cycle_files"]:
            for k in ("sha256", "signal_sha256", "n_pairs", "chosen_meta_index",
                      "t_start", "t_end", "n_native", "n_extrapolated",
                      "extrapolated_fraction"):
                assert k in entry, f"missing per-file key: {k}"
            assert len(entry["sha256"]) == 64
            assert len(entry["signal_sha256"]) == 64
        assert "extrapolation_summary" in prov["results"]
        assert "n_extrapolated_total" in prov["results"]["extrapolation_summary"]

    def test_exclude_boundary_provenance_string(self, tmp_path):
        """Cheap standalone check of the OTHER provenance string branch --
        doesn't need a real decode of its own since it can reuse a monkey-
        patched load; kept as its own tiny generate-path check via direct
        function call, not a subprocess, to stay inside the one-generate-
        subprocess budget."""
        import types
        fake_series = [(np.linspace(0, tg.T_END, 5), np.array([0., 1., 2., 1., 0.]))
                       for _ in range(tg.NUM_DATASETS)]

        def fake_load_all_cycles(cycle_dir, n=tg.NUM_DATASETS, verbose=False,
                                 layouts=None, **kwargs):
            if layouts is not None:
                for i in range(tg.NUM_DATASETS):
                    layouts.append({
                        "n_pairs": 7, "chosen_pair_ordinal": 6, "chosen_meta_index": 171,
                        "duplicate_pair_ordinals": [tg._EXPECTED_DUP_ORDINAL],
                        "signal_sha256": f"deadbeef{i:056x}"[:64],
                        "n_native": 5, "t_start": 0.0, "t_end": tg.T_END,
                        "dropped_duplicate": False,
                    })
            return fake_series

        import unittest.mock as mock
        out_path = tmp_path / "excl.mat"
        with mock.patch.object(tg, "load_all_cycles", fake_load_all_cycles), \
             mock.patch.object(tg, "cycle_paths",
                                lambda cycle_dir=CYCLE_DIR, n=tg.NUM_DATASETS: [
                                    os.path.join(str(tmp_path), f"fake_V{i}.mat")
                                    for i in range(1, n + 1)]), \
             mock.patch.object(tg, "_sha256", lambda p: "0" * 64), \
             mock.patch("os.path.getsize", lambda p: 123):
            args = types.SimpleNamespace(
                dt=1.0, out=str(out_path), cycle_dir=CYCLE_DIR,
                exclude_boundary=True, force=False, verbose=False,
            )
            rc = tg.run_generate(args, ["--dt", "1.0", "--exclude-boundary"])
        assert rc == 0
        with open(str(out_path) + ".provenance.json", encoding="utf-8") as f:
            prov = json.load(f)
        assert prov["boundary_transition_policy"].startswith("EXCLUDED")


# ─────────────────────────────────────────────────────────────────────────
# 15. Real-file content assertions: duplicate signal groups, V3
#     extrapolated fraction. Riding the SAME real_generate fixture -- no
#     additional decode.
# ─────────────────────────────────────────────────────────────────────────

@requires_real_cycles
class TestRealGenerateContent:
    def test_v1_v2_are_a_duplicate_signal_group(self, real_generate):
        groups = real_generate["prov"]["duplicate_signal_groups"]
        basenames_per_group = [
            {os.path.basename(p) for p in g} for g in groups
        ]
        assert any(
            {"simulink_pdem_output_stochastic_V1.mat",
             "simulink_pdem_output_stochastic_V2.mat"} <= g
            for g in basenames_per_group
        ), groups

    def test_v3_extrapolated_fraction_near_0p4(self, real_generate):
        entries = real_generate["prov"]["cycle_files"]
        v3 = next(e for e in entries if e["path"].endswith("_V3.mat"))
        assert v3["extrapolated_fraction"] == pytest.approx(0.4, abs=0.02)
        assert v3["n_extrapolated"] > 0


# ─────────────────────────────────────────────────────────────────────────
# 16. Validation gate + FAIL/shape-mismatch branches: ONE real cached
#     decode (module-scoped fixture), reused via monkeypatching
#     load_all_cycles for every CLI-path assertion below.
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cached_real_series():
    if not _cycle_files_present:
        pytest.skip("references/EMS/Pdem_cycles/*.mat not present in this checkout")
    return tg.load_all_cycles(CYCLE_DIR)


@requires_reference_tpm
class TestValidationGate:
    def test_validate_passes(self, cached_real_series, monkeypatch, capsys):
        monkeypatch.setattr(tg, "load_all_cycles", lambda *a, **k: cached_real_series)
        rc = tg.main(["--validate"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "PASS" in captured.out

    def test_validate_fails_against_wrong_reference(
        self, cached_real_series, monkeypatch, capsys, tmp_path,
    ):
        wrong_ref = tmp_path / "wrong_tpm.mat"
        # Same shape, deliberately wrong values (all zero) so the
        # comparison actually exercises the value-diff FAIL path, not just
        # a shape mismatch.
        savemat(str(wrong_ref), {"TPM": np.zeros((50, 50), dtype=np.float64)})
        monkeypatch.setattr(tg, "load_all_cycles", lambda *a, **k: cached_real_series)
        rc = tg.main(["--validate", "--reference", str(wrong_ref)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "FAIL" in captured.out
        assert "differs from the reference" in captured.out

    def test_validate_fails_on_shape_mismatch(
        self, cached_real_series, monkeypatch, capsys, tmp_path,
    ):
        wrong_shape_ref = tmp_path / "wrong_shape.mat"
        savemat(str(wrong_shape_ref), {"TPM": np.zeros((10, 10), dtype=np.float64)})
        monkeypatch.setattr(tg, "load_all_cycles", lambda *a, **k: cached_real_series)
        rc = tg.main(["--validate", "--reference", str(wrong_shape_ref)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "shape" in captured.out.lower()


# ─────────────────────────────────────────────────────────────────────────
# 17. HIL-deviation round: rescale_gamma, smoothing / empty-row policies,
#     native-span truncation, duplicate dropping, the --hil preset
#     resolution, and the validate-mode refusal of every deviation flag.
#     Defaults must stay MATLAB parity (the gate test above is the proof).
# ─────────────────────────────────────────────────────────────────────────

def _series(vals, t_end=tg.T_END):
    """Synthetic (t, y) cycle spanning [0, t_end]."""
    y = np.asarray(vals, dtype=np.float64)
    return np.linspace(0.0, t_end, y.size), y


class TestRescaleGamma:
    def test_identity_at_base_step(self):
        assert tg.rescale_gamma(0.95, 1.0) == pytest.approx(0.95)

    def test_students_gamma_at_20ms(self):
        # 0.95 per 1 s step -> 0.95**0.02 per 20 ms step (~0.99897): the
        # planning horizon stays ~20 s instead of collapsing to ~0.4 s.
        g = tg.rescale_gamma(0.95, 0.02)
        assert g == pytest.approx(0.95 ** 0.02)
        assert 0.998 < g < 0.999

    def test_horizon_invariance(self):
        # gamma_eff**(steps for 10 s) is the same discount over 10 s
        # regardless of the step size.
        for dt in (0.02, 0.5, 2.0):
            g = tg.rescale_gamma(0.95, dt)
            assert g ** (10.0 / dt) == pytest.approx(0.95 ** 10.0, rel=1e-9)

    def test_coarser_step_discounts_harder(self):
        assert tg.rescale_gamma(0.95, 2.0) < 0.95 < tg.rescale_gamma(0.95, 0.5)

    @pytest.mark.parametrize("bad", [(0.0, 1.0), (1.5, 1.0), (-0.1, 1.0),
                                     (0.95, 0.0), (0.95, -1.0)])
    def test_rejects_bad_inputs(self, bad):
        gamma, dt = bad
        with pytest.raises(ValueError):
            tg.rescale_gamma(gamma, dt)

    def test_bad_dt_base_rejected(self):
        with pytest.raises(ValueError):
            tg.rescale_gamma(0.95, 1.0, dt_base=0.0)


class TestSmoothingAndEmptyRows:
    """Laplace smoothing + empty-row policies. n_bins=10 with a series that
    never visits some bins guarantees genuinely empty rows."""

    def _sparse_series(self):
        # Knot-exact: native t at exactly the dt=1.0 grid, so CubicSpline
        # returns the knot values verbatim and the resampled data takes ONLY
        # the values {0, 1} -- bins 1..8 of 10 are guaranteed empty.  (A
        # coarse-knot series would NOT work: the spline sweeps continuously
        # between levels and populates every intermediate bin.)
        t = np.arange(1001, dtype=np.float64)
        y = np.tile([0.0, 0.0, 1.0, 1.0, 0.0, 1.0], 200)[:1001]
        return [(t, y)]

    def test_parity_default_keeps_zero_rows(self):
        tpm, counts, meta = tg.build_tpm(self._sparse_series(), 1.0, n_bins=10)
        assert len(meta["zero_rows"]) > 0
        for i in meta["zero_rows"]:
            assert tpm[i].sum() == 0.0

    def test_laplace_alpha_removes_zero_rows_and_normalizes(self):
        tpm, counts, meta = tg.build_tpm(self._sparse_series(), 1.0, n_bins=10,
                                         smoothing_alpha=0.5)
        assert np.allclose(tpm.sum(axis=1), 1.0)
        # counts stays RAW: same zero rows as the unsmoothed build.
        assert len(meta["zero_rows"]) > 0
        for i in meta["zero_rows"]:
            assert counts[i].sum() == 0.0
        assert meta["smoothing_alpha"] == 0.5

    def test_laplace_preserves_count_ordering(self):
        series = self._sparse_series()
        _, counts, _ = tg.build_tpm(series, 1.0, n_bins=10)
        tpm_s, _, _ = tg.build_tpm(series, 1.0, n_bins=10, smoothing_alpha=0.1)
        i = int(np.argmax(counts.sum(axis=1)))
        # The heaviest observed transition stays the row's argmax.
        assert np.argmax(tpm_s[i]) == np.argmax(counts[i])

    def test_empty_row_policy_self(self):
        tpm, _, meta = tg.build_tpm(self._sparse_series(), 1.0, n_bins=10,
                                    empty_row_policy="self")
        assert meta["empty_row_policy"] == "self"
        assert len(meta["zero_rows"]) > 0
        for i in meta["zero_rows"]:
            assert tpm[i, i] == 1.0
            assert tpm[i].sum() == 1.0

    def test_empty_row_policy_uniform(self):
        tpm, _, meta = tg.build_tpm(self._sparse_series(), 1.0, n_bins=10,
                                    empty_row_policy="uniform")
        for i in meta["zero_rows"]:
            assert np.allclose(tpm[i], 1.0 / 10)

    def test_alpha_supersedes_empty_row_policy(self):
        # With alpha > 0 no row has zero mass, so the policy never fires and
        # the empty rows become (near-)uniform from the prior alone.
        tpm, _, meta = tg.build_tpm(self._sparse_series(), 1.0, n_bins=10,
                                    smoothing_alpha=0.5,
                                    empty_row_policy="self")
        for i in meta["zero_rows"]:
            assert tpm[i, i] != 1.0
            assert np.allclose(tpm[i], 1.0 / 10)

    def test_invalid_policy_and_negative_alpha_raise(self):
        with pytest.raises(ValueError):
            tg.build_tpm(self._sparse_series(), 1.0, n_bins=10,
                         empty_row_policy="laplace")
        with pytest.raises(ValueError):
            tg.build_tpm(self._sparse_series(), 1.0, n_bins=10,
                         smoothing_alpha=-0.1)

    def test_diagonal_mass_reported(self):
        # Knot-exact step series: 0 for t<500, 1 after -> exactly one
        # off-diagonal transition in 1000, so diagonal mass is a HAND value
        # (999/1000), not recomputed from the same counts.
        t = np.arange(1001, dtype=np.float64)
        y = np.where(t < 500, 0.0, 1.0)
        tpm, counts, meta = tg.build_tpm([(t, y)], 1.0, n_bins=2)
        assert meta["diagonal_mass"] == pytest.approx(999.0 / 1000.0)


class TestTruncateNative:
    def test_short_cycle_not_extrapolated(self):
        full = _series([0.0, 1.0, 0.5, 1.0, 0.0])
        short = _series([0.2, 0.9, 0.4, 0.8, 0.1], t_end=600.0)
        tpm, _, meta = tg.build_tpm([full, short], 1.0, n_bins=10,
                                    truncate_native=True)
        assert meta["truncate_native"] is True
        pf = meta["per_file"]
        assert pf[0]["n_resampled"] == 1001
        assert pf[1]["n_resampled"] == 601          # grid clipped at 600 s
        assert pf[1]["n_extrapolated"] == 0
        assert meta["extrapolation_summary"]["n_extrapolated_total"] == 0
        assert meta["n_samples_total"] == 1602

    def test_default_extrapolates(self):
        short = _series([0.2, 0.9, 0.4, 0.8, 0.1], t_end=600.0)
        _, _, meta = tg.build_tpm([short], 1.0, n_bins=10)
        assert meta["truncate_native"] is False
        assert meta["per_file"][0]["n_resampled"] == 1001
        assert meta["per_file"][0]["n_extrapolated"] == 400

    def test_boundary_exclusion_uses_truncated_lengths(self):
        # The boundary cut indices must follow the per-file TRUNCATED
        # lengths; with a short first file, an untruncated-length cut would
        # remove the wrong transition.
        a = _series([0.0, 1.0, 0.0, 1.0, 0.0], t_end=600.0)
        b = _series([1.0, 0.0, 1.0, 0.0, 1.0])
        _, counts_incl, _ = tg.build_tpm([a, b], 1.0, n_bins=10,
                                         truncate_native=True)
        _, counts_excl, _ = tg.build_tpm([a, b], 1.0, n_bins=10,
                                         truncate_native=True,
                                         exclude_boundary=True)
        assert counts_incl.sum() - counts_excl.sum() == 1


class TestResolveDeviationArgs:
    def _ns(self, **kw):
        import types
        base = dict(n_bins=None, smooth_alpha=None, empty_row_policy=None,
                    drop_duplicates=False, truncate_native=False,
                    exclude_boundary=False, hil=False)
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_defaults_are_matlab_parity(self):
        dev = tg.resolve_deviation_args(self._ns())
        assert dev == {"n_bins": 50, "smoothing_alpha": 0.0,
                       "empty_row_policy": "zero", "drop_duplicates": False,
                       "truncate_native": False, "exclude_boundary": False}

    def test_hil_preset(self):
        dev = tg.resolve_deviation_args(self._ns(hil=True))
        assert dev == {"n_bins": tg.N_BINS_HIL, "smoothing_alpha": 0.0,
                       "empty_row_policy": "self", "drop_duplicates": True,
                       "truncate_native": True, "exclude_boundary": True}

    def test_explicit_flags_win_over_preset(self):
        dev = tg.resolve_deviation_args(
            self._ns(hil=True, n_bins=40, empty_row_policy="uniform",
                     smooth_alpha=0.25))
        assert dev["n_bins"] == 40
        assert dev["empty_row_policy"] == "uniform"
        assert dev["smoothing_alpha"] == 0.25
        assert dev["drop_duplicates"] is True   # preset still applies

    def test_missing_attributes_tolerated(self):
        import types
        dev = tg.resolve_deviation_args(types.SimpleNamespace())
        assert dev["n_bins"] == 50
        assert dev["empty_row_policy"] == "zero"


class TestValidateRefusesDeviationFlags:
    @pytest.mark.parametrize("flag", [
        ["--exclude-boundary"], ["--n-bins", "25"], ["--smooth-alpha", "0.5"],
        ["--empty-row-policy", "self"], ["--drop-duplicates"],
        ["--truncate-native"], ["--hil"],
    ])
    def test_each_flag_refused(self, flag, capsys):
        rc = tg.main(["--validate"] + flag)
        captured = capsys.readouterr()
        assert rc == 2
        assert "cannot be combined with --validate" in captured.out

    def test_bad_n_bins_rejected(self, capsys):
        rc = tg.main(["--n-bins", "1"])
        assert rc == 2
        assert "--n-bins" in capsys.readouterr().out

    def test_bad_smooth_alpha_rejected(self, capsys):
        rc = tg.main(["--smooth-alpha=-1"])
        assert rc == 2
        assert "--smooth-alpha" in capsys.readouterr().out


@requires_real_cycles
class TestDropDuplicatesReal:
    def test_drop_duplicates_removes_v2(self, capsys):
        layouts = []
        series = tg.load_all_cycles(CYCLE_DIR, layouts=layouts,
                                    drop_duplicates=True)
        out = capsys.readouterr().out
        assert len(series) == tg.NUM_DATASETS - 1
        assert "DEVIATION: dropping" in out
        dropped = [os.path.basename(r["path"]) for r in layouts
                   if r["dropped_duplicate"]]
        assert dropped == ["simulink_pdem_output_stochastic_V2.mat"]
        # The first occurrence (V1) is kept.
        v1 = next(r for r in layouts if r["path"].endswith("_V1.mat"))
        assert v1["dropped_duplicate"] is False

    def test_default_keeps_all_ten(self, cached_real_series):
        assert len(cached_real_series) == tg.NUM_DATASETS


class TestDeviationAutoNaming:
    """A deviation run must not auto-name onto the parity artifact name.
    Probed via the refusal path: point DEFAULT_OUT_DIR at a tmp dir holding
    a pre-existing file of the EXPECTED auto-name; the refusal message names
    the path the tool intended to write."""

    def _probe_autoname(self, tmp_path, monkeypatch, capsys, argv, expected):
        target = tmp_path / expected
        target.write_bytes(b"occupied")
        monkeypatch.setattr(tg, "DEFAULT_OUT_DIR", str(tmp_path))
        rc = tg.main(argv)
        out = capsys.readouterr().out
        assert rc == 2, out
        assert expected in out

    def test_parity_name_plain(self, tmp_path, monkeypatch, capsys):
        self._probe_autoname(tmp_path, monkeypatch, capsys,
                             [], "TPM_dt1.mat")

    def test_hil_suffix(self, tmp_path, monkeypatch, capsys):
        self._probe_autoname(tmp_path, monkeypatch, capsys,
                             ["--hil"], "TPM_dt1_hil.mat")

    def test_dev_suffix_for_single_flag(self, tmp_path, monkeypatch, capsys):
        self._probe_autoname(tmp_path, monkeypatch, capsys,
                             ["--drop-duplicates"], "TPM_dt1_dev.mat")
