#!/usr/bin/env python3
"""pytest suite for tools/regen_power.py -- the ONE regenerative-braking chain
the offline EMS tools share (the ftp75c round, 2026-09-02).

INTERPRETER.  The module under test is stdlib-only and imports nothing from
the repository, which is the property that lets `ems_walk.py` and `mpc_ems.py`
use it without numpy.  This file is stdlib-only for the same reason and runs
under BOTH interpreters:

    .venv_hil/Scripts/python.exe    -m pytest tools/test_regen_power.py -q
    C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_regen_power.py -q

WHAT THIS FILE IS FOR.  `regen_power.py` exists because four consumers price
braking energy -- the plant, the DP generator, the offline walk and the MPC's
prediction model -- and writing the same five-line chain four times is how
`V_bus * i_chg` came to be written five times before `charger_power.py`
existed.  The tests below therefore fall into three groups:

  1. THE ERA CONVENTION.  `eta_regen is None` is the pre-regen sentinel, and
     it must mean the ABSENCE of the credit rather than the credit at zero.
     Those are the same number here and different numbers everywhere a header
     line, a fingerprint or a database key is written, so the distinction is
     pinned as behaviour and not left to a docstring.
  2. THE CHAIN'S OWN ARITHMETIC, term by term, including the two clamps (the
     VESC regen-side current clip and the Ag105's output-referred ceiling)
     that are the only places energy can go missing.
  3. THE RE-EXPORTED DEFAULTS, pinned equal to `hil_plant_sim`'s constants --
     the module's own docstring says they are re-exports "pinned equal by
     test", and this is that test.

The four-consumer EQUALITY claim (this module against the DP generator, the
MPC's scalar port and `Plant.step()`'s own chain) is NOT here: it needs numpy
and the plant, so it lives in `test_hil_plant_sim.py`'s regen section and in
`test_ems_walk.py`'s lockstep test.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import regen_power as rp                  # noqa: E402  (stdlib-safe)

# The two constants the chain is parameterised by, at their live values.  Named
# here rather than repeated inline so a reader can see what a figure below is
# made of, and pinned against `hil_plant_sim` in its own test at the bottom.
K_F = 0.7538
I_CLIP = 1.5


# ═════════════════════════════════════════════════════════════════════════════
# 1. The era convention.  `eta_regen is None` names the PRE-REGEN demand model.
# ═════════════════════════════════════════════════════════════════════════════
def test_resolve_eta_regen_reads_absent_and_explicit_none_the_same_way():
    """An ABSENT key and an explicit None are ONE statement -- the pre-regen
    era -- because a run sidecar written before the key existed and a sidecar
    that declares the sentinel describe the same run.  `charger_power`'s
    `resolve_eta_chg()` convention, verbatim."""
    assert rp.resolve_eta_regen({}) is None
    assert rp.resolve_eta_regen(None) is None
    assert rp.resolve_eta_regen({"eta_regen": None}) is None
    assert rp.resolve_eta_regen({"eta_chg": 0.88}) is None


def test_resolve_eta_regen_returns_a_declared_value_as_a_float():
    assert rp.resolve_eta_regen({"eta_regen": 0.8}) == 0.8
    assert isinstance(rp.resolve_eta_regen({"eta_regen": 1}), float)


def test_resolve_eta_regen_default_is_only_used_for_a_missing_value():
    """The `default` argument exists for a caller that deliberately wants a
    different era for an unstated key.  It must NOT override a declared one,
    or a table header would stop being the record it is supposed to be."""
    assert rp.resolve_eta_regen({}, default=0.8) == 0.8
    assert rp.resolve_eta_regen({"eta_regen": None}, default=0.8) == 0.8
    assert rp.resolve_eta_regen({"eta_regen": 0.5}, default=0.8) == 0.5


def test_check_eta_regen_passes_the_sentinel_and_the_open_unit_interval():
    assert rp.check_eta_regen(None) is None
    assert rp.check_eta_regen(0.8) == 0.8
    assert rp.check_eta_regen(1.0) == 1.0        # lossless is admissible
    assert isinstance(rp.check_eta_regen(1), float)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.0001, 2.0])
def test_check_eta_regen_refuses_a_value_outside_zero_to_one(bad):
    """ZERO IS REFUSED DELIBERATELY, and it is the interesting case: an
    efficiency of exactly 0 is arithmetically the pre-regen era but is a
    DIFFERENT declaration -- it writes an `# eta_regen: 0.0` header line, moves
    the fingerprint and keys a database record apart.  Refusing it means there
    is exactly one way to say "no credit"."""
    with pytest.raises(ValueError) as exc:
        rp.check_eta_regen(bad)
    assert "eta_regen" in str(exc.value)


def test_era_label_distinguishes_the_two_eras_in_prose():
    assert "no regen" in rp.era_label(None)
    assert "0.8" in rp.era_label(0.8)


# ═════════════════════════════════════════════════════════════════════════════
# 2. The clip.  `Plant.step()` applies the VESC's Battery Regen Max to the
#    CURRENT command; the offline models carry a FORCE and never a command.
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("i_cmd", [-12.0, -3.0, -1.5, -1.4999, -0.5, 0.0,
                                   0.5, 1.5, 12.0])
def test_clip_on_the_force_equals_the_plants_clip_on_the_command(i_cmd):
    """THE EQUIVALENCE THE MODULE CLAIMS, asserted rather than argued.

    `Plant.step()` computes `i_cmd_eff = max(i_cmd, -VESC_REGEN_I_MAX_A)` and
    then `f = K_F * i_cmd_eff`; this module computes `max(K_F*i_cmd,
    -K_F*i_clip)`.  They are the same number because `K_F > 0`, and if a future
    edit ever makes them differ the two halves of the round-trip -- braking
    force and electrical return -- stop coming from ONE number, which is the
    whole point of applying the clip before the force develops."""
    assert rp.clip_regen_force_n(K_F * i_cmd, K_F, I_CLIP) == pytest.approx(
        K_F * max(i_cmd, -I_CLIP), rel=1e-15, abs=1e-18)


@pytest.mark.parametrize("f", [0.0, 0.001, 1.13, 9.05])
def test_clip_leaves_every_motoring_force_untouched(f):
    """A `max()` against a negative bound cannot touch a positive force, and
    that is what keeps every pre-round traction figure bit-identical."""
    assert rp.clip_regen_force_n(f, K_F, I_CLIP) == f


def test_clip_is_indifferent_to_the_sign_of_the_clip_argument():
    """`abs()` inside the bound: a caller passing the clip as a negative
    current must not silently invert the bound into a floor on motoring."""
    assert rp.clip_regen_force_n(-5.0, K_F, I_CLIP) == \
        rp.clip_regen_force_n(-5.0, K_F, -I_CLIP)


def test_the_clip_bound_is_the_1_13_newton_figure_the_design_note_quotes():
    """`K_F * VESC_REGEN_I_MAX_A` = 1.1307 N -- the number the ftp75c design
    note and the `ems_regen_harvest` caption both quote as the reason the
    harvest is small."""
    assert rp.clip_regen_force_n(-100.0, K_F, I_CLIP) == pytest.approx(-1.1307,
                                                                      abs=5e-5)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Shaft power, node power and the era gate on the credit.
# ═════════════════════════════════════════════════════════════════════════════
def test_shaft_power_is_zero_whenever_the_stage_is_not_braking():
    """`max(0, -(f*v))`: a motoring stage, a standstill and a braking force
    against a standstill all return exactly zero, so a credit can never be
    earned by a sign convention."""
    assert rp.regen_shaft_power_w(2.0, 3.0, K_F, I_CLIP) == 0.0
    assert rp.regen_shaft_power_w(-2.0, 0.0, K_F, I_CLIP) == 0.0
    assert rp.regen_shaft_power_w(0.0, 3.0, K_F, I_CLIP) == 0.0


def test_shaft_power_is_the_clipped_force_times_speed():
    # -3.0 N is beyond the 1.1307 N clip, so the clip is what is billed.
    assert rp.regen_shaft_power_w(-3.0, 2.0, K_F, I_CLIP) == pytest.approx(
        K_F * I_CLIP * 2.0, rel=1e-15)
    # -0.5 N is inside it, so the force passes through.
    assert rp.regen_shaft_power_w(-0.5, 2.0, K_F, I_CLIP) == pytest.approx(
        1.0, rel=1e-15)


def test_node_power_is_exactly_zero_in_the_pre_regen_era():
    """THE ABSENCE OF THE TERM, not the term multiplied by zero -- and the
    distinction is what makes every old-era total bit-identical rather than
    merely equal to the last bit."""
    assert rp.regen_node_power_w(-3.0, 2.0, None, K_F, I_CLIP) == 0.0
    assert isinstance(rp.regen_node_power_w(-3.0, 2.0, None, K_F, I_CLIP),
                      float)


def test_node_power_applies_eta_regen_to_the_shaft_power():
    shaft = rp.regen_shaft_power_w(-3.0, 2.0, K_F, I_CLIP)
    assert rp.regen_node_power_w(-3.0, 2.0, 0.8, K_F, I_CLIP) == \
        pytest.approx(0.8 * shaft, rel=1e-15)


def test_node_power_validates_its_era_argument():
    with pytest.raises(ValueError):
        rp.regen_node_power_w(-3.0, 2.0, 0.0, K_F, I_CLIP)


# ═════════════════════════════════════════════════════════════════════════════
# 4. The Ag105's output-referred share.
# ═════════════════════════════════════════════════════════════════════════════
def test_pack_current_uses_the_1_to_1_arithmetic_when_eta_chg_is_absent():
    """`eta_chg is None` is the 1:1 CURRENT-TRANSFER era, in which the charger
    moved current rather than energy.  Written as the `eta_chg = 1.0`
    arithmetic so a pre-2026-09-01 table's credit is reproducible."""
    assert rp.regen_pack_current_a(8.0, 8.0, None, 99.0) == pytest.approx(1.0)
    assert rp.regen_pack_current_a(8.0, 8.0, 1.0, 99.0) == \
        rp.regen_pack_current_a(8.0, 8.0, None, 99.0)


def test_pack_current_is_energy_conserving_in_the_eta_chg_era():
    assert rp.regen_pack_current_a(10.0, 8.0, 0.88, 99.0) == pytest.approx(
        0.88 * 10.0 / 8.0, rel=1e-15)


def test_pack_current_is_capped_at_the_ag105_ceiling():
    """The ceiling is the SAME scenario key that bounds the FC-path charge
    current, so a regen stage cannot bank more than the charger can deliver."""
    assert rp.regen_pack_current_a(1000.0, 8.0, 0.88, 0.8) == 0.8


def test_pack_current_refuses_to_divide_by_a_non_positive_pack_voltage():
    assert rp.regen_pack_current_a(10.0, 0.0, 0.88, 99.0) == 0.0
    assert rp.regen_pack_current_a(10.0, -1.0, 0.88, 99.0) == 0.0


# ═════════════════════════════════════════════════════════════════════════════
# 5. The whole chain -- what the DP, the walk and the MPC actually call.
# ═════════════════════════════════════════════════════════════════════════════
def _chain(force_n, v_mps, eta_regen=0.8, eta_chg=0.88, v_pack=7.9,
           i_max=0.8):
    return rp.regen_pack_current_from_force_a(
        force_n, v_mps, eta_regen=eta_regen, eta_chg=eta_chg,
        v_pack_v=v_pack, k_f=K_F, i_clip_a=I_CLIP, i_max_a=i_max)


def test_the_chain_composes_its_four_stages_in_order():
    """Recomputed stage by stage rather than transcribed, so a constant that
    moves fails the test instead of silently repricing the credit."""
    f, v = -0.9, 2.5
    want = min(0.88 * (0.8 * (0.9 * 2.5)) / 7.9, 0.8)
    assert _chain(f, v) == pytest.approx(want, rel=1e-15)


def test_the_chain_is_zero_in_the_pre_regen_era_at_every_operating_point():
    for f, v in ((-3.0, 3.0), (-0.5, 1.0), (-0.05, 0.1)):
        assert _chain(f, v, eta_regen=None) == 0.0


def test_the_chain_is_zero_on_a_stage_that_is_not_braking():
    assert _chain(+2.0, 3.0) == 0.0
    assert _chain(-2.0, 0.0) == 0.0


def test_the_chain_saturates_at_the_ceiling_and_never_above_it():
    """THE TWO CLAMPS BIND IN A FIXED ORDER, and which one binds is worth
    recording: the VESC clip is FIRST and, on this rig, is the only one that
    ever binds.  At the compressed cycle's 3.0 m/s peak an unbounded braking
    force still returns only 1.1307 N * 3.0 * 0.8 * 0.88 / 7.9 = 0.302 A, well
    under the 0.8 A `chg_i_ceiling_a` the scenarios declare -- so the Ag105
    ceiling is structurally slack on every registered stimulus and the harvest
    figures are a VESC-clip result, not a charger result.  The ceiling is
    exercised here by setting it below that, which is the only way to reach
    it."""
    peak = _chain(-50.0, 3.0, i_max=99.0)
    assert peak == pytest.approx(0.3023, abs=5e-4)
    assert _chain(-50.0, 3.0, i_max=0.8) == pytest.approx(peak)   # slack
    assert _chain(-50.0, 3.0, i_max=0.1) == 0.1                   # binds


def test_the_chain_is_monotone_in_speed_below_the_ceiling():
    """A physical sanity gate: harder braking at higher speed returns more, up
    to the ceiling.  A sign error anywhere in the chain breaks monotonicity
    before it breaks any single pinned value."""
    vals = [_chain(-0.6, v, i_max=99.0) for v in (0.5, 1.0, 1.5, 2.0, 3.0)]
    assert all(b > a for a, b in zip(vals, vals[1:]))


# ═════════════════════════════════════════════════════════════════════════════
# 6. The re-exported defaults, pinned to their source of truth.
# ═════════════════════════════════════════════════════════════════════════════
def test_the_defaults_are_pinned_to_hil_plant_sims_constants():
    """`ETA_REGEN` and `VESC_REGEN_I_MAX_A` live in `hil_plant_sim.py` with
    their `TODO(verify)` provenance; the values here are re-exports for
    stdlib-only callers that cannot import it.  The module docstring says they
    are "pinned equal by test" -- this is that test.  It imports the plant
    module, so it is the ONE test in this file that is not stdlib-pure."""
    sim = pytest.importorskip("hil_plant_sim")
    assert rp.ETA_REGEN_DEFAULT == sim.ETA_REGEN == 0.80
    assert rp.VESC_REGEN_I_MAX_A_DEFAULT == sim.VESC_REGEN_I_MAX_A == 1.5
    # And the two literals this file parameterises its chain with.
    assert K_F == sim.K_F
    assert I_CLIP == sim.VESC_REGEN_I_MAX_A


def test_the_module_imports_nothing_from_the_repository():
    """The stdlib-only property is STRUCTURAL, not incidental: `ems_walk.py`
    and `mpc_ems.py` import this module on interpreters that have no numpy and
    must not acquire the plant module transitively."""
    src = open(os.path.join(HERE, "regen_power.py"), encoding="utf-8").read()
    for forbidden in ("import numpy", "import hil_plant_sim",
                      "import charger_power", "import gen_dp_ems_table"):
        assert forbidden not in src, forbidden


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
