#!/usr/bin/env python3
"""Self-test for tools/benchlog_analysis/figures.py (the figure-building
layer only -- decoder coverage lives in tools/test_decode_benchlog.py, this
file does not duplicate it).

INTERPRETER: unlike test_decode_benchlog.py (stdlib-only), figures.py
imports numpy and matplotlib, which live only in the repo's dedicated venv
(see tools/benchlog_analysis/README.md "Interpreter"). This file MUST be run
with that venv's interpreter, NOT the system/stdlib python:

    .venv_benchlog/Scripts/python.exe tools/test_figures.py

Same house style as test_decode_benchlog.py: no pytest/unittest, plain
check(name, cond, detail="") / skip(name, reason) helpers with module-level
pass/fail/skip counters, and a main() that runs every test function and
prints "N/M passed" before sys.exit(0 on all-pass, 1 on any failure).

Legend labels use the Greek tau (u"τ"), which the default Windows console
codepage (cp1252) cannot always encode; stdout is reconfigured to UTF-8 below
so a FAIL detail string containing it never crashes the run with a raw
UnicodeEncodeError instead of a clean report.

Synthetic data dicts are built in memory to match exactly what
common.load_csv() returns for each format version (CSV_COLUMNS /
CSV_COLUMNS_V3 / CSV_COLUMNS_V6, plus the derived t_s key) -- see
make_v1v2_fixture / make_v3_fixture / make_v6_fixture below. The v3/v6
fixtures carry a deliberate NaN in I_fc (present in every format) and in
V_chg (v3+ only) so NaN handling (np.array_equal(..., equal_nan=True)) is
actually exercised, not just assumed. V_chg/V_rgn magnitudes are set to
match every real log on record (logs/ML0135...ML0162): V_rgn ~13.4 V (a
few-volt regen excursion above that), V_chg ~0.01 V -- the charger path has
never been energized in any logged run, so V_chg reads essentially zero.

Covers:
  (a) Registry contract -- tracking_overlay is gone (neither registered nor
      a module attribute), charge_regen_and_currents is registered between
      bus_and_share and drive_controller_conditioning, every registry entry
      is a (str, callable) pair, and names are unique.
  (b) charge_regen_and_currents builds the correct series on v3+ data: no
      twinx (exactly 2 axes -- the user has decided the top subplot keeps a
      single shared voltage axis even though V_chg reads near zero; this
      test does NOT demand a dual axis, banding, or a log scale), the top
      axes carries exactly V_rgn/V_chg with y-data equal to the input
      arrays and colours equal to a PINNED (not module-derived) expected
      hex per role -- EXPECTED_COLOR below -- which is what actually
      catches a mutation that swaps two roles' VALUES inside the COLORS
      dict, unlike comparing against figures.COLORS[role] itself (that
      comparison is circular: the builder forwards whatever the dict
      currently holds, so it can never disagree with itself even after a
      swap); the bottom axes' raw total equals I_fc + I_batt EXACTLY
      (elementwise), the filtered total equals lowpass(I_fc) +
      lowpass(I_batt) independently recomputed in the test, every line's
      colour matches its pinned role colour (raw) or _darker(pinned role
      colour) (filtered), the returned Figure is still OPEN (builders must
      never self-close), ylabels/xlabel are correct, and -- the
      anti-vacuity check for this figure -- the
      filtered-current AND filtered-total legend labels carry the
      NON-DEFAULT taus fed in via cfg (and do NOT carry the default taus'
      labels), which only passes if the builder actually reads cfg rather
      than hardcoding the default.
  (c) Version gate: charge_regen_and_currents returns None (never raises)
      on v1/v2 data, and also when only ONE of V_chg/V_rgn is present --
      both columns are required, not just "any".
  (d) Registry regression: every builder in figures.FIGURES is called on a
      v6 fixture (all builders must return a Figure, none may raise, and
      every returned Figure must still be OPEN when the builder returns) and
      on a v1/v2 fixture (the three version-gated builders --
      charge_regen_and_currents, drive_controller_conditioning,
      encoder_diagnostics -- must return None; the rest must return an OPEN
      Figure); every returned Figure is closed by the test immediately
      after the open-figure check.
  (e) End-to-end through the real driver: make_test_blg.py generates a
      synthetic v6 .BLG and a synthetic default (v1/v2) .BLG, both written
      only into a tempfile.TemporaryDirectory() (never logs/); each is run
      through ingest_log.ingest() + make_figures.make_all(), and the
      produced PNG set is checked to contain charge_regen_and_currents.png
      for the v6 log, to NOT contain it for the v1/v2 log (proving the
      graceful-skip path works through the real driver, not just at the
      builder level), and to never contain tracking_overlay.png either way.
      The process CWD's *.png listing is snapshotted before/after each
      render and asserted unchanged, catching a builder that saves a file
      itself instead of returning the Figure for make_figures.py to save.
  (f) Doc/registry consistency: tools/benchlog_analysis/README.md no longer
      mentions tracking_overlay and does mention charge_regen_and_currents.
      SKIPPED (not failed) if the README is absent.
  (g) The filtered-total legend label format
      "I_fc + I_batt (filt, tau=%s/%s)" % (_tau_label(tau_fc),
      _tau_label(tau_bt)) -- FC tau first, BT tau second, '/'-separated,
      both rendered through _tau_label -- pinned against the two worked
      examples (defaults -> "10 ms/10 ms"; I_fc_tau_s=0.0/I_batt_tau_s=1.5
      -> "0.0 ms/1.50 s") for both charge_regen_and_currents AND
      bus_and_share, which carries the identical contract.

Run: .venv_benchlog/Scripts/python.exe tools/test_figures.py
Exit code 0 on all-pass, 1 on any failure.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

# See the module docstring's note on tau -- reconfigure stdout to UTF-8
# before anything prints, so a FAIL detail string containing "τ" never
# crashes the run with UnicodeEncodeError on a cp1252 Windows console.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent   # tools/
REPO_ROOT = HERE.parent                  # repo root

# figures.py (and therefore this test) needs numpy + matplotlib from the
# dedicated venv -- see the module docstring above. Importing them here,
# before touching sys.path, means a system-python invocation fails fast
# with a plain ImportError rather than a confusing downstream error.
import numpy as np

# figures.py has a direct-script import shim keyed off __package__; the
# clean way in for a test file living in tools/ (a sibling of the
# benchlog_analysis package, not inside it) is to put tools/ on sys.path
# and import the package normally -- this makes __package__ ==
# "benchlog_analysis" for every module below, so their *own* shims take the
# `from . import common` branch rather than the direct-script branch.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from benchlog_analysis import common, figures, ingest_log, make_figures  # noqa: E402
from benchlog_analysis import make_test_blg  # noqa: E402

_passed = 0
_failed = 0
_skipped = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"PASS: {name}")
    else:
        _failed += 1
        print(f"FAIL: {name}" + (f" -- {detail}" if detail else ""))


def skip(name, reason):
    global _skipped
    _skipped += 1
    print(f"SKIP: {name} -- {reason}")


def assert_figure_open(label, fig):
    """The builder contract (figures.py's 'HOW TO ADD A FIGURE' block) says
    builders never save AND never close -- make_figures.py owns all file
    I/O. A builder that closes its own figure before returning it would
    still let most attribute access on the (stale) Figure/Axes objects
    succeed, so this must be checked explicitly rather than assumed from
    "no exception" -- plt.fignum_exists() is the actual ground truth."""
    check(f"{label}: figure is still OPEN when the builder returns "
          f"(a builder must never call plt.close() on its own figure)",
          figures.plt.fignum_exists(fig.number))


def list_pngs(dir_path):
    return {p.name for p in Path(dir_path).glob("*.png")}


# --------------------------------------------------------------------------
# Synthetic fixtures -- shaped exactly like common.load_csv()'s output for
# each format version.
# --------------------------------------------------------------------------

N = 300  # samples; 1 kHz nominal -> a 0.3 s synthetic run


def _base_channels(seed):
    """The v1/v2 (CSV_COLUMNS) channel set, plus the derived t_s key.

    Carries one deliberate NaN (I_fc[50]) so every fixture -- v1/v2 included
    -- exercises NaN handling in anything that reads I_fc.
    """
    rng = np.random.default_rng(seed)
    t_s = np.arange(N, dtype=np.float64) * 0.001

    data = {
        "t_us": t_s * 1.0e6,
        "share_sp": np.full(N, 0.5, dtype=np.float64),
        "share_act": (0.5 + 0.03 * np.sin(2 * np.pi * t_s / 0.05)
                      + rng.normal(0.0, 0.01, N)),
        "v_sp": np.linspace(0.0, 2.0, N),
        "v_act": np.linspace(0.0, 2.0, N) + rng.normal(0.0, 0.02, N),
        "I_fc": (1.0 + 0.30 * np.sin(2 * np.pi * t_s / 0.07)
                 + rng.normal(0.0, 0.02, N)),
        "I_batt": (0.8 + 0.25 * np.cos(2 * np.pi * t_s / 0.09)
                   + rng.normal(0.0, 0.02, N)),
        "gFC": np.full(N, 0.5, dtype=np.float64),
        "gBT": np.full(N, 0.5, dtype=np.float64),
        "V_bus": 16.0 + rng.normal(0.0, 0.01, N),
        "I_cmd": rng.normal(0.0, 1.0, N),
        "fault_flags": np.zeros(N, dtype=np.float64),
        "ps_phase": np.full(N, np.nan, dtype=np.float64),
        "dc_phase": np.full(N, np.nan, dtype=np.float64),
        "trap_phase": np.full(N, np.nan, dtype=np.float64),
        "flags": np.zeros(N, dtype=np.float64),
    }
    data["I_fc"][50] = np.nan
    data["t_s"] = t_s
    return data


def _v3_extra(seed, t_s):
    """v3+ node voltages, at REALISTIC magnitudes.

    Verified across every real log on record (logs/ML0135...ML0162):
    V_rgn (regen node) sits at 13.2-18.2 V (close to V_bus), and V_chg
    (charger input) sits at 0.000-0.021 V -- the charger path has never
    been energized in any logged run, so V_chg reads essentially zero. This
    is deliberately NOT the earlier V_chg~12V/V_rgn~0.5V placeholder: that
    had the two channels backwards relative to reality and made a genuine
    scale problem (V_chg's near-invisible trace on a shared linear axis)
    structurally invisible to this harness, even though the identity/NaN
    checks passed either way. The user has decided the shared single
    voltage axis in charge_regen_and_currents stays as-is (V_chg~=0 IS the
    correct finding for every run to date; a shared same-unit axis is right
    for a future run where the charger is powered) -- this fixture exists
    to make that reality visible to anyone eyeballing test output/figures,
    not to justify a dual axis in the test assertions.
    """
    rng = np.random.default_rng(seed + 1000)
    extra = {
        "V_fc": 12.5 + rng.normal(0.0, 0.01, N),
        "V_batt": 8.0 + rng.normal(0.0, 0.01, N),
        "V_chg": (0.010 + 0.004 * np.abs(np.sin(2 * np.pi * t_s / 0.11))
                  + rng.normal(0.0, 0.002, N)),
        "V_rgn": (13.4 + 1.2 * np.abs(np.sin(2 * np.pi * t_s / 0.13))
                  + rng.normal(0.0, 0.05, N)),
    }
    extra["V_chg"][70] = np.nan  # deliberate, independent NaN channel
    return extra


def _v5_extra(seed, t_s):
    rng = np.random.default_rng(seed + 2000)
    return {
        "u_unsat": 15.0 * np.sin(2 * np.pi * t_s / 0.20) + rng.normal(0.0, 0.05, N),
        "drive_x0": 3.0 * np.sin(2 * np.pi * t_s / 0.33) + rng.normal(0.0, 0.02, N),
    }


def _v6_extra(seed, t_s):
    rng = np.random.default_rng(seed + 3000)
    return {
        "encoder_pos": np.cumsum(rng.integers(-2, 3, N)).astype(np.float64),
        "enc_period_ref_us": np.full(N, 4000.0),
        "enc_multi_pitch_count": np.cumsum(
            rng.poisson(0.01, N)).astype(np.float64),
        "enc_spurious_drop_count": np.cumsum(
            rng.poisson(0.02, N)).astype(np.float64),
    }


def make_v1v2_fixture(seed=0):
    return _base_channels(seed)


def make_v3_fixture(seed=1):
    data = _base_channels(seed)
    data.update(_v3_extra(seed, data["t_s"]))
    return data


def make_v6_fixture(seed=2):
    data = _base_channels(seed)
    data.update(_v3_extra(seed, data["t_s"]))
    data.update(_v5_extra(seed, data["t_s"]))
    data.update(_v6_extra(seed, data["t_s"]))
    return data


def _default_cfg():
    return copy.deepcopy(common.DEFAULT_CONFIG)


# --------------------------------------------------------------------------
# Pinned colour expectations -- literal, NOT derived from figures.COLORS.
# --------------------------------------------------------------------------
# Comparing a rendered line's colour against figures.COLORS[role] read from
# the SAME (possibly mutated) module is circular for the exact bug class
# this guards against: a mutation that swaps two roles' VALUES inside the
# COLORS dict (e.g. COLORS["V_chg"] <-> COLORS["V_rgn"]) leaves every
# builder still forwarding "whatever COLORS[role] currently holds" -- the
# rendered line and the module's own COLORS[role] can never disagree,
# swapped or not (verified empirically: an early draft of this test
# compared against figures.COLORS[role] directly and still passed 78/78
# against a scratchpad copy with V_chg/V_rgn's values swapped). These five
# roles are therefore pinned literally instead, mirroring
# test_decode_benchlog.py's test_v1v2_regression (which spells out its
# expected CSV header literally rather than importing it from
# decode_benchlog, "so this test does not depend on the module under test
# to define its own expectation"). Sourced from figures.py's COLORS map as
# of the charge_regen_and_currents round (2026-08-17) -- update these in
# lockstep with any deliberate palette change to these roles; a legitimate
# colour redesign SHOULD make this test fail and force a conscious update,
# the same way a real CSV header change would.
EXPECTED_COLOR = {
    "I_fc": "#1baf7a",
    "I_batt": "#4a3aa7",
    "I_total": "#e87ba4",
    "V_chg": "#0f8f95",
    "V_rgn": "#7d6608",
}


# --------------------------------------------------------------------------
# (a) Registry contract
# --------------------------------------------------------------------------

def test_registry_contract():
    names = [name for name, _ in figures.FIGURES]

    check("(a) tracking_overlay is absent from figures.FIGURES",
          "tracking_overlay" not in names, names)
    check("(a) figures module has no tracking_overlay attribute at all",
          not hasattr(figures, "tracking_overlay"))
    check("(a) charge_regen_and_currents is registered",
          "charge_regen_and_currents" in names, names)

    idx_bus = names.index("bus_and_share") if "bus_and_share" in names else -1
    idx_new = (names.index("charge_regen_and_currents")
               if "charge_regen_and_currents" in names else -1)
    idx_drive = (names.index("drive_controller_conditioning")
                 if "drive_controller_conditioning" in names else -1)
    check("(a) charge_regen_and_currents sits after bus_and_share and "
          "before drive_controller_conditioning",
          idx_bus != -1 and idx_new != -1 and idx_drive != -1
          and idx_bus < idx_new < idx_drive,
          f"bus_and_share={idx_bus} charge_regen_and_currents={idx_new} "
          f"drive_controller_conditioning={idx_drive}")

    check("(a) registry names are unique",
          len(names) == len(set(names)), names)

    all_pairs_ok = all(
        isinstance(entry, tuple) and len(entry) == 2
        and isinstance(entry[0], str) and callable(entry[1])
        for entry in figures.FIGURES)
    check("(a) every registry entry is a (str, callable) 2-tuple",
          all_pairs_ok, figures.FIGURES)


# --------------------------------------------------------------------------
# (b) New figure builds and its series are correct
# --------------------------------------------------------------------------

def test_charge_regen_and_currents_series():
    data = make_v3_fixture()
    # Deliberately non-default taus, distinct from each other and from
    # common.DEFAULT_CONFIG's 0.010/0.010 -- this is the anti-vacuity
    # requirement: a builder that ignored cfg and hardcoded the default
    # would fail the "cfg tau is in the label" checks below.
    tau_fc = 0.037
    tau_bt = 0.081
    cfg = {"filters": {"I_fc_tau_s": tau_fc, "I_batt_tau_s": tau_bt,
                        "share_act_tau_s": 0.020}}

    fig = figures.charge_regen_and_currents(data, cfg)
    ok = fig is not None
    check("(b) builder returns a Figure for v3+ data", ok)
    if not ok:
        return

    assert_figure_open("(b) charge_regen_and_currents", fig)

    try:
        axes = fig.axes
        check("(b) figure has exactly 2 axes (no twinx added -- the shared "
              "single voltage axis is an intentional design decision, not "
              "a gap this test should demand a dual axis/banding/log scale "
              "for)",
              len(axes) == 2, f"got {len(axes)}")
        if len(axes) != 2:
            return
        ax0, ax1 = axes[0], axes[1]

        # --- top axes: exactly V_rgn and V_chg, raw ---
        top_lines = ax0.get_lines()
        check("(b) top axes has exactly 2 lines",
              len(top_lines) == 2, f"got {len(top_lines)}")
        top_by_label = {ln.get_label(): ln for ln in top_lines}
        vrgn_line = next((ln for lbl, ln in top_by_label.items()
                           if lbl.startswith("V_rgn")), None)
        vchg_line = next((ln for lbl, ln in top_by_label.items()
                           if lbl.startswith("V_chg")), None)
        check("(b) top axes carries a V_rgn line",
              vrgn_line is not None, list(top_by_label))
        check("(b) top axes carries a V_chg line",
              vchg_line is not None, list(top_by_label))
        if vrgn_line is not None:
            check("(b) V_rgn y-data equals the input V_rgn array exactly "
                  "(NaN-tolerant)",
                  np.array_equal(vrgn_line.get_ydata(), data["V_rgn"],
                                  equal_nan=True))
            check("(b) V_rgn line colour == the pinned V_rgn colour "
                  "(catches COLORS['V_rgn']/COLORS['V_chg'] being swapped "
                  "in the dict itself, not just a builder key mismatch)",
                  vrgn_line.get_color() == EXPECTED_COLOR["V_rgn"],
                  f"got {vrgn_line.get_color()!r}, "
                  f"expected {EXPECTED_COLOR['V_rgn']!r}")
        if vchg_line is not None:
            check("(b) V_chg y-data equals the input V_chg array exactly "
                  "(NaN-tolerant, exercises the V_chg[70]=NaN fixture)",
                  np.array_equal(vchg_line.get_ydata(), data["V_chg"],
                                  equal_nan=True))
            check("(b) V_chg line colour == the pinned V_chg colour",
                  vchg_line.get_color() == EXPECTED_COLOR["V_chg"],
                  f"got {vchg_line.get_color()!r}, "
                  f"expected {EXPECTED_COLOR['V_chg']!r}")
        # Would catch "plotted V_chg twice" / "plotted V_rgn as V_chg":
        if vrgn_line is not None and vchg_line is not None:
            check("(b) V_rgn and V_chg lines are not the same series",
                  not np.array_equal(vrgn_line.get_ydata(),
                                      vchg_line.get_ydata(), equal_nan=True))
        # Would catch COLORS['V_chg']/COLORS['V_rgn'] being swapped even if
        # the data-identity checks above still happened to pass:
        if vrgn_line is not None and vchg_line is not None:
            check("(b) V_rgn and V_chg lines do not share a colour "
                  "(catches the two roles' COLORS entries being swapped)",
                  vrgn_line.get_color() != vchg_line.get_color(),
                  f"both {vrgn_line.get_color()!r}")

        # --- bottom axes: I_fc, I_batt, total (raw + filtered) ---
        bottom_lines = ax1.get_lines()
        check("(b) bottom axes has exactly 6 lines",
              len(bottom_lines) == 6, f"got {len(bottom_lines)}")
        bottom_by_label = {ln.get_label(): ln for ln in bottom_lines}

        i_fc_meas = bottom_by_label.get("I_fc (meas)")
        i_bt_meas = bottom_by_label.get("I_batt (meas)")
        total_meas = bottom_by_label.get("I_fc + I_batt (meas)")
        check("(b) bottom axes carries the raw I_fc series",
              i_fc_meas is not None, list(bottom_by_label))
        check("(b) bottom axes carries the raw I_batt series",
              i_bt_meas is not None, list(bottom_by_label))
        check("(b) bottom axes carries the raw total series",
              total_meas is not None, list(bottom_by_label))
        if i_fc_meas is not None:
            check("(b) I_fc (meas) colour == the pinned I_fc colour",
                  i_fc_meas.get_color() == EXPECTED_COLOR["I_fc"],
                  f"got {i_fc_meas.get_color()!r}")
        if i_bt_meas is not None:
            check("(b) I_batt (meas) colour == the pinned I_batt colour",
                  i_bt_meas.get_color() == EXPECTED_COLOR["I_batt"],
                  f"got {i_bt_meas.get_color()!r}")
        if total_meas is not None:
            expected_total = data["I_fc"] + data["I_batt"]
            # The load-bearing assertion: would fail if the builder plotted
            # I_fc - I_batt, or I_fc alone, as the "total".
            check("(b) total series y-data == I_fc + I_batt EXACTLY, "
                  "elementwise",
                  np.array_equal(total_meas.get_ydata(), expected_total,
                                  equal_nan=True),
                  "total line and I_fc+I_batt differ")
            check("(b) I_fc + I_batt (meas) colour == the pinned I_total "
                  "colour",
                  total_meas.get_color() == EXPECTED_COLOR["I_total"],
                  f"got {total_meas.get_color()!r}")

        t = data["t_s"]
        i_fc_f_expected = common.lowpass(data["I_fc"], t, tau_fc)
        i_bt_f_expected = common.lowpass(data["I_batt"], t, tau_bt)
        expected_total_f = i_fc_f_expected + i_bt_f_expected

        # --- anti-vacuity: legend labels must carry the FED-IN taus ---
        label_fc = "I_fc (filt, τ=%s)" % figures._tau_label(tau_fc)
        label_bt = "I_batt (filt, τ=%s)" % figures._tau_label(tau_bt)
        label_total_filt = ("I_fc + I_batt (filt, τ=%s/%s)"
                             % (figures._tau_label(tau_fc),
                                figures._tau_label(tau_bt)))
        i_fc_filt = bottom_by_label.get(label_fc)
        i_bt_filt = bottom_by_label.get(label_bt)
        total_filt = bottom_by_label.get(label_total_filt)
        check("(b) I_fc filtered line's label carries the cfg tau",
              i_fc_filt is not None, list(bottom_by_label))
        check("(b) I_batt filtered line's label carries the cfg tau",
              i_bt_filt is not None, list(bottom_by_label))
        check("(b) bottom axes carries the filtered-total series under the "
              "BOTH-taus label format",
              total_filt is not None, list(bottom_by_label))
        if i_fc_filt is not None:
            check("(b) I_fc (filt) colour == _darker(pinned I_fc colour)",
                  i_fc_filt.get_color() == figures._darker(EXPECTED_COLOR["I_fc"]),
                  f"got {i_fc_filt.get_color()!r}")
        if i_bt_filt is not None:
            check("(b) I_batt (filt) colour == _darker(pinned I_batt colour)",
                  i_bt_filt.get_color() == figures._darker(EXPECTED_COLOR["I_batt"]),
                  f"got {i_bt_filt.get_color()!r}")
        if total_filt is not None:
            check("(b) filtered total == lowpass(I_fc, tau_fc) + "
                  "lowpass(I_batt, tau_bt), independently recomputed here",
                  np.array_equal(total_filt.get_ydata(), expected_total_f,
                                  equal_nan=True))
            check("(b) I_fc + I_batt (filt) colour == "
                  "_darker(pinned I_total colour)",
                  total_filt.get_color() == figures._darker(EXPECTED_COLOR["I_total"]),
                  f"got {total_filt.get_color()!r}")

        default_tau_fc = common.DEFAULT_CONFIG["filters"]["I_fc_tau_s"]
        default_tau_bt = common.DEFAULT_CONFIG["filters"]["I_batt_tau_s"]
        assert tau_fc != default_tau_fc and tau_bt != default_tau_bt, (
            "fixture bug: chosen taus must differ from the defaults or the "
            "checks below are vacuous")
        default_label_fc = "I_fc (filt, τ=%s)" % figures._tau_label(
            default_tau_fc)
        default_label_bt = "I_batt (filt, τ=%s)" % figures._tau_label(
            default_tau_bt)
        default_label_total = ("I_fc + I_batt (filt, τ=%s/%s)"
                                % (figures._tau_label(default_tau_fc),
                                   figures._tau_label(default_tau_bt)))
        check("(b) the DEFAULT-tau label is ABSENT for I_fc -- proves the "
              "builder reads cfg rather than hardcoding the default",
              default_label_fc not in bottom_by_label, list(bottom_by_label))
        check("(b) the DEFAULT-tau label is ABSENT for I_batt -- same check "
              "for the second channel",
              default_label_bt not in bottom_by_label, list(bottom_by_label))
        check("(b) the DEFAULT-taus label is ABSENT for the filtered total "
              "-- same anti-vacuity check for the both-taus total label",
              default_label_total not in bottom_by_label,
              list(bottom_by_label))

        # --- labels ---
        check("(b) top axes ylabel is 'Voltage [V]'",
              ax0.get_ylabel() == "Voltage [V]", ax0.get_ylabel())
        check("(b) bottom axes ylabel is 'Current [A]'",
              ax1.get_ylabel() == "Current [A]", ax1.get_ylabel())
        check("(b) bottom axes xlabel is 'Time [s]'",
              ax1.get_xlabel() == "Time [s]", ax1.get_xlabel())
    finally:
        figures.plt.close(fig)


# --------------------------------------------------------------------------
# (g) Filtered-total legend label format -- worked examples, both builders
#     that carry the "both taus in the total label" contract.
# --------------------------------------------------------------------------

def _total_filt_label(tau_fc, tau_bt):
    return ("I_fc + I_batt (filt, τ=%s/%s)"
            % (figures._tau_label(tau_fc), figures._tau_label(tau_bt)))


def test_charge_regen_total_label_worked_examples():
    data = make_v3_fixture()

    # Worked example 1: defaults -> "10 ms/10 ms".
    cfg_default = _default_cfg()
    fig = figures.charge_regen_and_currents(data, cfg_default)
    ok = fig is not None
    check("(g) charge_regen_and_currents builds on default cfg", ok)
    if ok:
        try:
            labels = {ln.get_label() for ax in fig.axes for ln in ax.get_lines()}
            expected = _total_filt_label(0.010, 0.010)
            check("(g) charge_regen_and_currents default-cfg total label "
                  "== 'I_fc + I_batt (filt, τ=10 ms/10 ms)'",
                  expected in labels, sorted(labels))
        finally:
            figures.plt.close(fig)

    # Worked example 2 (the motivating failure case): I_fc_tau_s=0.0,
    # I_batt_tau_s=1.5 -> "0.0 ms/1.50 s". Also the anti-vacuity pair: the
    # two taus are non-default AND mutually different, so "renders both"
    # cannot be confused with "renders one twice".
    cfg2 = {"filters": {"I_fc_tau_s": 0.0, "I_batt_tau_s": 1.5,
                        "share_act_tau_s": 0.020}}
    fig2 = figures.charge_regen_and_currents(data, cfg2)
    ok2 = fig2 is not None
    check("(g) charge_regen_and_currents builds on the worked-example cfg",
          ok2)
    if ok2:
        try:
            labels2 = {ln.get_label() for ax in fig2.axes
                       for ln in ax.get_lines()}
            expected2 = _total_filt_label(0.0, 1.5)
            check("(g) charge_regen_and_currents worked-example total "
                  "label == 'I_fc + I_batt (filt, τ=0.0 ms/1.50 s)'",
                  expected2 in labels2, sorted(labels2))
            check("(g) charge_regen_and_currents worked-example total "
                  "label is NOT the default-cfg label (mutually different "
                  "taus actually changed the rendering)",
                  _total_filt_label(0.010, 0.010) not in labels2)
        finally:
            figures.plt.close(fig2)


def test_bus_and_share_total_label():
    """bus_and_share now carries the identical both-taus total-label
    contract as charge_regen_and_currents; cover it separately since it is
    a different builder (with a twinx top axes, unlike charge_regen)."""
    data = make_v1v2_fixture()  # bus_and_share only needs v1/v2 columns

    cfg_default = _default_cfg()
    fig = figures.bus_and_share(data, cfg_default)
    ok = fig is not None
    check("(g) bus_and_share builds on default cfg", ok)
    if ok:
        try:
            labels = {ln.get_label() for ax in fig.axes for ln in ax.get_lines()}
            expected = _total_filt_label(0.010, 0.010)
            check("(g) bus_and_share default-cfg total label == "
                  "'I_fc + I_batt (filt, τ=10 ms/10 ms)'",
                  expected in labels, sorted(labels))
        finally:
            figures.plt.close(fig)

    # Non-default, mutually-different taus -- same anti-vacuity pairing as
    # charge_regen_and_currents's worked-example check.
    tau_fc, tau_bt = 0.045, 0.123
    cfg2 = {"filters": {"I_fc_tau_s": tau_fc, "I_batt_tau_s": tau_bt,
                        "share_act_tau_s": 0.020}}
    fig2 = figures.bus_and_share(data, cfg2)
    ok2 = fig2 is not None
    check("(g) bus_and_share builds on a non-default cfg", ok2)
    if ok2:
        try:
            labels2 = {ln.get_label() for ax in fig2.axes
                       for ln in ax.get_lines()}
            expected2 = _total_filt_label(tau_fc, tau_bt)
            check("(g) bus_and_share filtered-total label carries BOTH "
                  "non-default cfg taus",
                  expected2 in labels2, sorted(labels2))
            check("(g) bus_and_share default-taus total label is ABSENT "
                  "-- proves this builder also reads cfg for the total "
                  "label rather than hardcoding the default",
                  _total_filt_label(0.010, 0.010) not in labels2)
        finally:
            figures.plt.close(fig2)


# --------------------------------------------------------------------------
# (c) Version gate
# --------------------------------------------------------------------------

def _call_gracefully(builder, data, cfg):
    """Call builder(data, cfg); returns (result, raised_bool)."""
    try:
        return builder(data, cfg), False
    except Exception:
        return None, True


def test_version_gate():
    cfg = _default_cfg()

    v1v2 = make_v1v2_fixture()
    result, raised = _call_gracefully(figures.charge_regen_and_currents,
                                       v1v2, cfg)
    check("(c) v1/v2 data (no V_chg/V_rgn): does not raise",
          not raised)
    check("(c) v1/v2 data (no V_chg/V_rgn): returns None",
          result is None, result)
    if result is not None:
        figures.plt.close(result)

    v3 = make_v3_fixture()

    only_vrgn = dict(v3)
    del only_vrgn["V_chg"]
    result, raised = _call_gracefully(figures.charge_regen_and_currents,
                                       only_vrgn, cfg)
    check("(c) only V_chg missing: does not raise", not raised)
    check("(c) only V_chg missing: returns None (both columns required)",
          result is None, result)
    if result is not None:
        figures.plt.close(result)

    only_vchg = dict(v3)
    del only_vchg["V_rgn"]
    result, raised = _call_gracefully(figures.charge_regen_and_currents,
                                       only_vchg, cfg)
    check("(c) only V_rgn missing: does not raise", not raised)
    check("(c) only V_rgn missing: returns None (both columns required)",
          result is None, result)
    if result is not None:
        figures.plt.close(result)


# --------------------------------------------------------------------------
# (d) Registry regression -- every builder, v6 fixture and v1/v2 fixture
# --------------------------------------------------------------------------

# Builders that must return None (not a Figure) on a v1/v2-shaped dict --
# every other registered builder must return a Figure.
NONE_ON_V1V2 = {"charge_regen_and_currents", "drive_controller_conditioning",
                 "encoder_diagnostics"}


def test_registry_regression_v6():
    cfg = _default_cfg()
    data = make_v6_fixture()
    for name, builder in figures.FIGURES:
        result, raised = _call_gracefully(builder, data, cfg)
        check(f"(d) {name}: does not raise on the v6 (all-columns) fixture",
              not raised)
        if raised:
            continue
        check(f"(d) {name}: returns a Figure on the v6 fixture "
              f"(every column any builder needs is present)",
              result is not None)
        if result is not None:
            assert_figure_open(f"(d) {name} [v6]", result)
            figures.plt.close(result)


def test_registry_regression_v1v2():
    cfg = _default_cfg()
    data = make_v1v2_fixture()
    for name, builder in figures.FIGURES:
        result, raised = _call_gracefully(builder, data, cfg)
        check(f"(d) {name}: does not raise on the v1/v2 fixture "
              f"(no KeyError on absent newer-format columns)",
              not raised)
        if raised:
            continue
        if name in NONE_ON_V1V2:
            check(f"(d) {name}: returns None on v1/v2 data (version-gated)",
                  result is None)
        else:
            check(f"(d) {name}: returns a Figure on v1/v2 data "
                  f"(not version-gated)",
                  result is not None)
        if result is not None:
            assert_figure_open(f"(d) {name} [v1/v2]", result)
            figures.plt.close(result)


# --------------------------------------------------------------------------
# (e) End-to-end through the real driver
# --------------------------------------------------------------------------

def test_end_to_end_v6():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        blg_path = tmp / "TESTV6.BLG"
        blg_path.write_bytes(
            make_test_blg.build_blg(seed=0, truncate=False, v6=True))

        run_dir = ingest_log.ingest(blg_path)
        check("(e) v6 end-to-end: run directory was created inside the "
              "temp dir, not logs/",
              str(run_dir).startswith(str(tmp)), str(run_dir))

        cwd_before = list_pngs(os.getcwd())
        saved = make_figures.make_all(run_dir)
        cwd_after = list_pngs(os.getcwd())
        names = {p.name for p in saved}
        on_disk = {p.name for p in run_dir.glob("*.png")}

        check("(e) v6 end-to-end: charge_regen_and_currents.png produced",
              "charge_regen_and_currents.png" in names, names)
        check("(e) v6 end-to-end: tracking_overlay.png NOT produced",
              "tracking_overlay.png" not in names, names)
        check("(e) v6 end-to-end: returned PNG list matches what is "
              "actually on disk",
              names == on_disk, f"returned={names} on_disk={on_disk}")

        new_pngs = cwd_after - cwd_before
        check("(e) v6 end-to-end: no NEW .png appeared in the process CWD "
              "(a builder must never self-save -- make_figures.py owns all "
              "file I/O; a stray save here would land outside run_dir "
              "entirely)",
              not new_pngs, new_pngs)
        for name in new_pngs:  # best-effort cleanup if this ever fires
            try:
                (Path(os.getcwd()) / name).unlink()
            except OSError:
                pass


def test_end_to_end_v1v2():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        blg_path = tmp / "TESTV1.BLG"
        # make_test_blg's default layout (no --v3/--v4/--v5/--v6) is v1/v2.
        blg_path.write_bytes(
            make_test_blg.build_blg(seed=0, truncate=False))

        run_dir = ingest_log.ingest(blg_path)
        check("(e) v1/v2 end-to-end: run directory was created inside the "
              "temp dir, not logs/",
              str(run_dir).startswith(str(tmp)), str(run_dir))

        cwd_before = list_pngs(os.getcwd())
        saved = make_figures.make_all(run_dir)
        cwd_after = list_pngs(os.getcwd())
        names = {p.name for p in saved}

        check("(e) v1/v2 end-to-end: charge_regen_and_currents.png is "
              "ABSENT (no V_chg/V_rgn columns) -- proves the graceful-skip "
              "path through the real driver, not just the builder",
              "charge_regen_and_currents.png" not in names, names)
        check("(e) v1/v2 end-to-end: tracking_overlay.png NOT produced",
              "tracking_overlay.png" not in names, names)
        check("(e) v1/v2 end-to-end: a non-gated figure "
              "(tracking_subplots.png) is still produced",
              "tracking_subplots.png" in names, names)

        new_pngs = cwd_after - cwd_before
        check("(e) v1/v2 end-to-end: no NEW .png appeared in the process "
              "CWD",
              not new_pngs, new_pngs)
        for name in new_pngs:  # best-effort cleanup if this ever fires
            try:
                (Path(os.getcwd()) / name).unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------
# (f) Doc/registry consistency
# --------------------------------------------------------------------------

def test_readme_consistency():
    readme_path = REPO_ROOT / "tools" / "benchlog_analysis" / "README.md"
    if not readme_path.is_file():
        skip("(f) README doc consistency", f"{readme_path} not present")
        return
    text = readme_path.read_text(encoding="utf-8")
    check("(f) README no longer mentions tracking_overlay",
          "tracking_overlay" not in text)
    check("(f) README mentions charge_regen_and_currents",
          "charge_regen_and_currents" in text)


def main():
    test_registry_contract()
    test_charge_regen_and_currents_series()
    test_charge_regen_total_label_worked_examples()
    test_bus_and_share_total_label()
    test_version_gate()
    test_registry_regression_v6()
    test_registry_regression_v1v2()
    test_end_to_end_v6()
    test_end_to_end_v1v2()
    test_readme_consistency()

    total = _passed + _failed
    print(f"\n{_passed}/{total} passed" +
          (f" ({_skipped} skipped)" if _skipped else ""))
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
