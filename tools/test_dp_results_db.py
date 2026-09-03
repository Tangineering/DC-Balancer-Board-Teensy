#!/usr/bin/env python3
"""pytest suite for tools/dp_results_db.py -- the reusable store of solved
delta-SoC-matched DP hydrogen baselines.

INTERPRETER: storage/lookup/keying are STDLIB-ONLY by design (module
docstring), so this file must run under BOTH the repo's `.venv_hil`
(stdlib-only) and miniforge. The few tests that actually SOLVE (they import
gen_dp_ems_table, which needs numpy) are individually gated with
`pytest.importorskip("numpy")` INSIDE the test function, not at module scope
-- the rest of the file must still collect and pass under `.venv_hil`.

Every storage test passes an explicit `db_dir=tmp_path/...` -- the module's
default DP_DB_DIR (tools/dp_db/) is never touched by this suite.

Run:
    C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_dp_results_db.py -v
    .venv_hil/Scripts/python.exe -m pytest tools/test_dp_results_db.py -v
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dp_results_db as db  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Fixture helpers -- synthetic key-field dicts and minimal records, so these
# tests never need a real DP solve.
# ─────────────────────────────────────────────────────────────────────────

def _fields(**over):
    """A complete key-field dict, built BY HAND (not through problem_fields())
    so these tests stay stdlib-only: problem_fields() calls model_fields(),
    which imports gen_dp_ems_table.py, which imports numpy at module scope --
    fine for the numpy-gated solve tests below, but fatal for the pure
    storage/keying tests that must also pass under `.venv_hil`. The ten
    model-derived values below are representative constants (not re-derived
    live), which is fine here: these tests exercise the KEYING/STORAGE
    mechanism, not whether the numbers match the live model."""
    base = dict(
        scenario="ems-soc-band", profile_fingerprint="fp-aaaa",
        soc0=0.7, capacity_ah=5.0, charger_accounting="physical",
        stage_dt=0.1, n_share=41, soc_step=5e-6, chg_a=0.8,
        lambda_dev=0.0, aux_preload_a=None,
        # eta_chg (2026-09-01): an OPTIONAL key field. None is the 1:1
        # current-transfer charger era, which is what every record in the
        # shipped store was solved against, and it is OMITTED from the
        # canonical form so those records keep their pre-change keys.
        eta_chg=None,
        # loss_map (2026-09-02): the second OPTIONAL key field, on
        # identical terms. None is the loss-map-free demand model, which
        # is what every record in the shipped store was solved against,
        # and it is OMITTED from the canonical form so those records keep
        # their pre-change keys. It is carried as the CANONICAL STRING
        # (hil_plant_sim.loss_map_canonical), never as a dict.
        loss_map=None,
        # drag / eta_regen (2026-09-02, the ftp75c round): the third and
        # fourth OPTIONAL key fields, on identical terms again. None names
        # the MEASURED RIG ROAD LOAD and the PRE-REGEN demand model
        # respectively -- what every record in the shipped store was solved
        # against -- and both are OMITTED from the canonical form, so those
        # records keep their pre-change keys. `drag` is carried as its MODE
        # STRING, never as a k_air value.
        drag=None, eta_regen=None,
        gfc_dc_gain=1.7637602179836514e-05, eta_boost=0.85,
        limit_i_fc_max_a=1.4, charge_share_value=0.75, share_span=0.25,
        cruise_slope_max=0.05, cruise_min_mps=0.5, run_entry_s=3.0,
        run_exit_s=58.0, target_soc=0.698,
    )
    base.update(over)
    target = base.pop("target_soc")
    base["target_soc_q"] = db.quantize_target(target)
    # aux_preload_a: mirror problem_fields()'s ACTUAL (not docstring) mapping
    # -- None -> 0.0 -- so these hand-built fields agree with what a real
    # caller through problem_fields() would produce (pinned separately below).
    aux = base.pop("aux_preload_a")
    base["aux_preload_a"] = 0.0 if aux is None else float(aux)
    # eta_chg is NOT floated by the loop below: None is a meaningful value
    # (the era), not a missing number.
    eta = base.pop("eta_chg")
    base["eta_chg"] = None if eta is None else float(eta)
    # loss_map is not floated either, and for the same reason: None is
    # the era and a present value is a string.
    lm = base.pop("loss_map")
    base["loss_map"] = None if lm is None else str(lm)
    # drag and eta_regen are not floated either: `drag` is a mode string and
    # None is its era, and `eta_regen` is None-or-float where None is its era.
    dg = base.pop("drag")
    base["drag"] = None if dg is None else str(dg)
    er = base.pop("eta_regen")
    base["eta_regen"] = None if er is None else float(er)
    for name in ("soc0", "capacity_ah", "stage_dt", "n_share", "soc_step",
                "chg_a", "lambda_dev", "gfc_dc_gain", "eta_boost",
                "limit_i_fc_max_a", "charge_share_value", "share_span",
                "cruise_slope_max", "cruise_min_mps", "run_entry_s",
                "run_exit_s"):
        base[name] = float(base[name])
    assert set(base) == set(db.KEY_FIELDS), \
        "KEY_FIELDS changed -- update this test fixture in lockstep: %s" % (
            set(db.KEY_FIELDS) ^ set(base))
    return base


def _record(fields, target_soc=None, h2_g=0.0117564033, converged=True,
            residual_soc=1.5e-6):
    ts = fields["target_soc_q"] if target_soc is None else target_soc
    return {
        "format_version": 1,
        "key": db.make_key(fields),
        "non_target_hash": db.non_target_hash(fields),
        "key_fields": dict(fields),
        "created_utc": "2026-09-01T00:00:00Z",
        "target_soc": float(ts),
        "match_tol": 2.0e-6,
        "residual_soc": residual_soc,
        "converged": bool(converged),
        "lambda_term": 2.475,
        "n_solves": 12,
        "j0": 0.0117564033,
        "h2_g": h2_g,
        "h2_plant_g": h2_g,
        "soc_final": float(ts),
        "delta_soc": float(ts) - fields["soc0"],
        "wall_s": 1.5,
        "traj_stride": 1,
        "share": [0.5, 0.5],
        "charge": [0.0, 0.0],
        "provenance": {"gen_dp_ems_table_sha256": "deadbeef",
                       "hil_plant_sim_constants_hash": None},
    }


# ─────────────────────────────────────────────────────────────────────────
# item 7: keying primitives
# ─────────────────────────────────────────────────────────────────────────

def test_quantize_target_rounds_to_the_grid():
    q = db.DP_DB_TARGET_QUANTUM
    assert db.quantize_target(0.700000) == pytest.approx(0.70000)
    assert db.quantize_target(0.700003) == pytest.approx(round(0.700003 / q) * q)


def test_quantize_target_boundary_at_half_a_quantum_rounds_half_to_even():
    """A value exactly N+0.5 quanta from zero exercises Python's round()
    banker's rounding (round-half-to-even) -- pinned explicitly since a
    caller relying on round-half-away-from-zero would silently disagree."""
    q = db.DP_DB_TARGET_QUANTUM
    half = 0.5 * q
    assert db.quantize_target(half) == pytest.approx(0.0, abs=1e-15)   # 0.5 -> 0 (even)
    assert db.quantize_target(3 * half) == pytest.approx(2 * q)         # 1.5 -> 2 (even)
    assert db.quantize_target(5 * half) == pytest.approx(2 * q)         # 2.5 -> 2 (even)


def test_make_key_stable_regardless_of_field_insertion_order():
    fields = _fields()
    reordered = dict(reversed(list(fields.items())))
    assert db.make_key(fields) == db.make_key(reordered)


def test_make_key_stable_across_int_vs_float_representation():
    """A numeric field passed as an int (n_share=41) and the SAME value
    passed as a float (41.0) must key identically -- _canonical() runs every
    non-string, non-None value through repr(float(val))."""
    a = _fields(n_share=41)
    b = _fields(n_share=41.0)
    assert db.make_key(a) == db.make_key(b)


def test_make_key_changes_when_any_key_field_changes():
    a = _fields()
    for field, new_val in (("soc0", 0.71), ("capacity_ah", 4.9),
                           ("charger_accounting", "simple"),
                           ("scenario", "ems-dp-replay"),
                           ("profile_fingerprint", "fp-bbbb")):
        b = _fields(**{field: new_val})
        assert db.make_key(a) != db.make_key(b), field


def test_non_target_hash_invariant_across_targets_but_key_differs():
    """(item 7) Two field sets differing ONLY in target_soc must share a
    non_target_hash (so lookup() can find them as candidates) while their
    make_key()s -- which DO fold in the target -- differ."""
    a = _fields(target_soc=0.698)
    b = _fields(target_soc=0.703)
    assert db.non_target_hash(a) == db.non_target_hash(b)
    assert db.make_key(a) != db.make_key(b)


def test_non_target_hash_changes_when_a_non_target_field_changes():
    a = _fields(target_soc=0.698)
    b = _fields(target_soc=0.698, soc0=0.71)
    assert db.non_target_hash(a) != db.non_target_hash(b)


def test_aux_preload_override_moves_both_hash_and_key():
    """(item 5, dp_results_db half) An aux_preload_a override is a KEY
    field -- it must move both non_target_hash and make_key relative to the
    None (registry) path."""
    a = _fields(target_soc=0.698, aux_preload_a=None)
    b = _fields(target_soc=0.698, aux_preload_a=0.85)
    assert db.non_target_hash(a) != db.non_target_hash(b)
    assert db.make_key(a) != db.make_key(b)


def test_problem_fields_none_aux_preload_resolves_to_the_live_registry_value(
        monkeypatch):
    """RECONCILED (fix-round-2, MED-4): problem_fields() no longer collapses
    an omitted aux_preload_a to 0.0 -- None now means "whatever the scenario
    declares", resolved HERE against the live sim.SCENARIOS registry.

    AMENDED by the implementer (2026-09-01, stimulus-era item): this test was
    written against `ems-ftp75-5050` when FTP75_PRELOAD_A was 0.65 A. The
    parallel scenario-meta round then set that constant to 0.0, which erased
    the very distinction the test asserts (None and an explicit 0.0 collide
    again, correctly, because the scenario now DECLARES zero) and failed it.
    The declared preload is another round's number, so the test no longer
    depends on it: a non-zero preload is monkeypatched into the registry and
    the RESOLUTION MECHANISM is what is pinned. The contrast case below still
    covers a scenario that declares nothing."""
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    scen = dict(sim.SCENARIOS["ems-ftp75-5050"], aux_preload_a=0.65)
    monkeypatch.setitem(sim.SCENARIOS, "ems-ftp75-5050", scen)
    common = dict(profile_fingerprint="fp-aaaa", soc0=0.7, capacity_ah=5.0,
                 charger_accounting="physical", stage_dt=0.1, n_share=41,
                 soc_step=5e-6, chg_a=0.8, lambda_dev=0.0, run_exit_s=58.0,
                 target_soc=0.698)
    none_fields = db.problem_fields("ems-ftp75-5050", aux_preload_a=None,
                                    **common)
    zero_fields = db.problem_fields("ems-ftp75-5050", aux_preload_a=0.0,
                                    **common)
    assert none_fields["aux_preload_a"] == pytest.approx(0.65)
    assert zero_fields["aux_preload_a"] == 0.0
    # None vs an explicit 0.0 now produce DIFFERENT keys (they used to
    # collide before the fix).
    assert db.make_key(none_fields) != db.make_key(zero_fields)
    assert db.non_target_hash(none_fields) != db.non_target_hash(zero_fields)


def test_problem_fields_none_aux_preload_still_collides_with_zero_when_scenario_declares_none():
    """The OTHER half, kept for contrast: a scenario that declares no
    aux_preload_a at all (ems-soc-band) still resolves None to 0.0, so None
    and an explicit 0.0 key IDENTICALLY there -- this is not a bug, it is the
    "whatever the scenario declares" rule applied to a scenario that declares
    nothing."""
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    assert "aux_preload_a" not in sim.SCENARIOS["ems-soc-band"]
    common = dict(profile_fingerprint="fp-aaaa", soc0=0.7, capacity_ah=5.0,
                 charger_accounting="physical", stage_dt=0.1, n_share=41,
                 soc_step=5e-6, chg_a=0.8, lambda_dev=0.0, run_exit_s=58.0,
                 target_soc=0.698)
    none_fields = db.problem_fields("ems-soc-band", aux_preload_a=None,
                                    **common)
    zero_fields = db.problem_fields("ems-soc-band", aux_preload_a=0.0,
                                    **common)
    assert none_fields["aux_preload_a"] == 0.0
    assert zero_fields["aux_preload_a"] == 0.0
    assert db.make_key(none_fields) == db.make_key(zero_fields)


# ─────────────────────────────────────────────────────────────────────────
# item 8: lookup()
# ─────────────────────────────────────────────────────────────────────────

def test_lookup_exact_hit(tmp_path):
    db_dir = str(tmp_path / "db")
    fields = _fields(target_soc=0.698)
    rec = _record(fields)
    db.store(rec, db_dir=db_dir)
    got = db.lookup(fields, db_dir=db_dir)
    assert got is not None
    assert got["key"] == rec["key"]


def test_lookup_returns_nearest_within_tolerance_among_three_candidates(tmp_path):
    db_dir = str(tmp_path / "db")
    # Three stored solves at 0.690 / 0.700 / 0.710, all sharing every
    # non-target field. A caller wanting 0.6985 should get the 0.700 record.
    for t in (0.690, 0.700, 0.710):
        f = _fields(target_soc=t)
        db.store(_record(f, target_soc=t), db_dir=db_dir)
    want = _fields(target_soc=0.6985)
    got = db.lookup(want, tol_soc=0.01, db_dir=db_dir)
    assert got is not None
    assert got["target_soc"] == pytest.approx(0.700)


def test_lookup_refuses_beyond_tolerance(tmp_path):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.5)
    db.store(_record(f, target_soc=0.5), db_dir=db_dir)
    want = _fields(target_soc=0.9)
    assert db.lookup(want, tol_soc=db.DP_DB_LOOKUP_TOL, db_dir=db_dir) is None


def test_lookup_misses_when_a_non_target_field_differs(tmp_path):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698, scenario="ems-soc-band")
    db.store(_record(f, target_soc=0.698), db_dir=db_dir)
    want = _fields(target_soc=0.698, scenario="ems-dp-replay")
    assert db.lookup(want, db_dir=db_dir) is None


def test_lookup_tolerance_argument_overrides_the_default(tmp_path):
    """A caller-supplied tol_soc wider than the module default must find a
    record the default would have refused, and a caller-supplied tol_soc
    narrower than the default must refuse one the default would have
    accepted."""
    db_dir = str(tmp_path / "db")
    gap = db.DP_DB_LOOKUP_TOL * 3.0
    stored = _fields(target_soc=0.700)
    db.store(_record(stored, target_soc=0.700), db_dir=db_dir)
    want = _fields(target_soc=0.700 + gap)

    # Default tolerance refuses (gap is 3x the default).
    assert db.lookup(want, db_dir=db_dir) is None
    # An explicit wider tolerance accepts the same pair.
    got = db.lookup(want, tol_soc=gap * 2.0, db_dir=db_dir)
    assert got is not None
    # An explicit narrower-than-default tolerance also refuses.
    assert db.lookup(want, tol_soc=db.DP_DB_LOOKUP_TOL / 10.0,
                     db_dir=db_dir) is None


def test_dp_db_lookup_tol_and_target_quantum_are_1e_5():
    """The implementer's concurrent tolerance-tightening change
    (DP_DB_LOOKUP_TOL / DP_DB_TARGET_QUANTUM: 5e-4 -> 1e-5) -- read the live
    constants rather than hard-coding the old value anywhere above."""
    assert db.DP_DB_LOOKUP_TOL == pytest.approx(1.0e-5)
    assert db.DP_DB_TARGET_QUANTUM == pytest.approx(1.0e-5)


def test_dp_db_target_quantum_le_lookup_tol_import_assert_holds():
    """(fix-round-2 item 2) The module-level assert
    `DP_DB_TARGET_QUANTUM <= DP_DB_LOOKUP_TOL` must hold on THIS checkout --
    it already ran once at import time (or this test file would never have
    collected), but re-check it explicitly so a future edit that weakens one
    constant without the other is caught by this suite too, not only by an
    import-time crash a caller might not see."""
    assert db.DP_DB_TARGET_QUANTUM <= db.DP_DB_LOOKUP_TOL


def test_lookup_raw_vs_raw_target_comparison_not_quantized(tmp_path):
    """(fix-round-2 item 2) lookup()'s tolerance test compares the caller's
    RAW target against the stored RECORD's raw target_soc -- not the
    quantized target_soc_q. A stored target 1.4e-5 away from the caller's
    raw want must MISS at tol_soc=1e-5 even though both values round onto
    the SAME quantized grid point (quantum 1e-5), because a quantized-grid
    coincidence is not the same claim as "within tolerance of what was
    actually asked for"."""
    db_dir = str(tmp_path / "db")
    stored_target = 0.700000
    f = _fields(target_soc=stored_target)
    db.store(_record(f, target_soc=stored_target), db_dir=db_dir)

    want_target = stored_target + 1.4e-5
    want = _fields(target_soc=want_target)
    # The RAW gap (1.4e-5) exceeds tol_soc=1e-5, so lookup() must miss: the
    # exact-key path also misses (different target_soc_q), and the tolerance
    # scan must not let quantization narrow the gap.
    assert want["target_soc_q"] != f["target_soc_q"]
    got = db.lookup(want, tol_soc=1.0e-5, db_dir=db_dir)
    assert got is None
    # Sanity: a raw gap actually within tolerance DOES hit.
    want_close = _fields(target_soc=stored_target + 0.5e-5)
    got_close = db.lookup(want_close, tol_soc=1.0e-5, db_dir=db_dir)
    assert got_close is not None


# ── item 2 (fix-round-2): lookup() strict / provenance-drift ───────────────

def _record_with_provenance(fields, target_soc, chash):
    rec = _record(fields, target_soc=target_soc)
    rec["provenance"] = {"gen_dp_ems_table_sha256": "deadbeef",
                         "hil_plant_sim_constants_hash": chash}
    return rec


def test_lookup_strict_false_returns_drifted_record_flagged(tmp_path,
                                                             monkeypatch):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    db.store(_record_with_provenance(f, 0.698, "stored-hash-old"), db_dir=db_dir)
    monkeypatch.setattr(db, "live_constants_hash", lambda: "live-hash-new")

    got = db.lookup(f, strict=False, db_dir=db_dir)
    assert got is not None
    assert got["provenance_drift"] is True


def test_lookup_strict_false_undrifted_record_flagged_false(tmp_path,
                                                             monkeypatch):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    db.store(_record_with_provenance(f, 0.698, "same-hash"), db_dir=db_dir)
    monkeypatch.setattr(db, "live_constants_hash", lambda: "same-hash")

    got = db.lookup(f, strict=False, db_dir=db_dir)
    assert got is not None
    assert got["provenance_drift"] is False


def test_lookup_strict_true_skips_the_exact_drifted_hit_and_finds_nothing_else(
        tmp_path, monkeypatch):
    """An exact-key hit that is drifted must be REFUSED under strict=True,
    and with no other candidate in range, lookup() returns None (not the
    drifted record, and not a crash)."""
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    db.store(_record_with_provenance(f, 0.698, "stored-hash-old"), db_dir=db_dir)
    monkeypatch.setattr(db, "live_constants_hash", lambda: "live-hash-new")

    assert db.lookup(f, strict=True, db_dir=db_dir) is None
    # The lenient call on the SAME store still succeeds.
    assert db.lookup(f, strict=False, db_dir=db_dir) is not None


def test_lookup_strict_true_falls_through_a_drifted_nearer_candidate_to_an_undrifted_farther_one(
        tmp_path, monkeypatch):
    """The load-bearing case: the NEAREST stored target is drifted and the
    exact-key path misses (different target_soc_q, so it goes through the
    tolerance scan). strict=True must skip the nearer drifted candidate and
    return the next-nearest UNDRIFTED one instead of simply giving up."""
    db_dir = str(tmp_path / "db")
    near = _fields(target_soc=0.6981)     # closer to `want` below
    far = _fields(target_soc=0.6970)      # farther, but still in tolerance
    db.store(_record_with_provenance(near, 0.6981, "stored-hash-old"),
            db_dir=db_dir)
    db.store(_record_with_provenance(far, 0.6970, "same-hash"), db_dir=db_dir)
    monkeypatch.setattr(db, "live_constants_hash", lambda: "same-hash")

    want = _fields(target_soc=0.6980)
    tol = abs(0.6980 - 0.6970) + 1e-6     # wide enough to admit both

    got_lenient = db.lookup(want, tol_soc=tol, strict=False, db_dir=db_dir)
    assert got_lenient is not None
    assert got_lenient["target_soc"] == pytest.approx(0.6981)   # nearest wins

    got_strict = db.lookup(want, tol_soc=tol, strict=True, db_dir=db_dir)
    assert got_strict is not None
    assert got_strict["target_soc"] == pytest.approx(0.6970)    # fell through
    assert got_strict["provenance_drift"] is False


def test_store_never_persists_the_provenance_drift_annotation(tmp_path,
                                                               monkeypatch):
    """provenance_drift is a lookup-time annotation; store() must strip it so
    a record round-tripped through lookup()+store() never picks it up as a
    stored field."""
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    db.store(_record_with_provenance(f, 0.698, "same-hash"), db_dir=db_dir)
    monkeypatch.setattr(db, "live_constants_hash", lambda: "same-hash")
    got = db.lookup(f, db_dir=db_dir)
    assert "provenance_drift" in got

    db.store(got, db_dir=db_dir)      # round-trip: write the looked-up dict back
    on_disk = db.get(got["key"], db_dir=db_dir)
    assert "provenance_drift" not in on_disk


# ─────────────────────────────────────────────────────────────────────────
# item 9: store() atomicity and index rebuilds
# ─────────────────────────────────────────────────────────────────────────

def test_store_writes_via_temp_file_and_replace_leaving_no_tmp_behind(tmp_path):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    rec = _record(f)
    path = db.store(rec, db_dir=db_dir)
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp")


def test_a_failing_write_leaves_no_partial_final_file(tmp_path, monkeypatch):
    """A crash mid-write (json.dump raising) must never leave a truncated
    file at the FINAL path -- os.replace() only runs after the temp file is
    fully written and closed, so the final path is either the previous
    version or absent, never a half-written one."""
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    rec = _record(f)
    final_path = os.path.join(db_dir, "solves", "%s.json" % rec["key"])

    calls = {"n": 0}

    def _boom(*a, **kw):
        calls["n"] += 1
        raise OSError("simulated disk-full mid-write")

    monkeypatch.setattr(db.json, "dump", _boom)
    with pytest.raises(OSError):
        db.store(rec, db_dir=db_dir)
    assert calls["n"] == 1
    assert not os.path.exists(final_path)


def test_write_json_atomic_cleans_up_the_tmp_file_on_a_failing_dump(
        tmp_path, monkeypatch):
    """(fix-round-2 item 2) RECONCILED: _write_json_atomic() now wraps the
    open()+json.dump() block in try/except BaseException, removes the temp
    file, and re-raises -- so a failing write leaves BOTH no partial final
    file AND no orphaned .tmp file behind, and the caller still sees the
    original exception (not swallowed)."""
    db_dir = str(tmp_path / "db")
    solves_dir = os.path.join(db_dir, "solves")
    target = os.path.join(solves_dir, "probe.json")

    def _boom(*a, **kw):
        raise OSError("simulated disk-full mid-write")

    monkeypatch.setattr(db.json, "dump", _boom)
    with pytest.raises(OSError, match="simulated disk-full"):
        db._write_json_atomic(target, {"a": 1})

    assert not os.path.exists(target)
    # No stray temp file of ANY name pattern was left in the directory.
    assert os.path.isdir(solves_dir)
    leftovers = [n for n in os.listdir(solves_dir) if ".tmp" in n]
    assert leftovers == [], leftovers


def test_write_json_atomic_uses_unique_temp_names_across_writers(tmp_path,
                                                                  monkeypatch):
    """(fix-round-2 item 2) Two writers targeting the SAME final path must
    not share one "<path>.tmp" name -- the tmp name folds in os.getpid() and
    a fresh uuid4 hex per call, so two overlapping writes cannot replace one
    another's half-written file. Verified by capturing the tmp path
    os.replace() actually receives across two separate calls."""
    db_dir = str(tmp_path / "db")
    target = os.path.join(db_dir, "solves", "probe.json")

    seen_tmp_names = []
    real_replace = db.os.replace

    def _spy_replace(src, dst):
        seen_tmp_names.append(src)
        return real_replace(src, dst)

    monkeypatch.setattr(db.os, "replace", _spy_replace)
    db._write_json_atomic(target, {"a": 1})
    db._write_json_atomic(target, {"a": 2})

    assert len(seen_tmp_names) == 2
    assert seen_tmp_names[0] != seen_tmp_names[1]
    for name in seen_tmp_names:
        assert name.startswith(target + ".")
        assert name.endswith(".tmp")
        # "<path>.<pid>.<uuid8>.tmp" -- the pid segment is this process's.
        assert (".%d." % os.getpid()) in name[len(target):]


def test_a_failing_write_leaves_the_previous_version_intact_on_a_second_store(
        tmp_path, monkeypatch):
    """The stronger, load-bearing half of item 9: overwriting an EXISTING
    record whose write then fails must leave the OLD record readable at the
    final path -- os.replace() is what makes this atomic, and this is the
    scenario that actually matters operationally (a corrupt store is worse
    than a stale one)."""
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    rec_v1 = _record(f, h2_g=0.0111)
    db.store(rec_v1, db_dir=db_dir)
    final_path = os.path.join(db_dir, "solves", "%s.json" % rec_v1["key"])

    rec_v2 = _record(f, h2_g=0.0222)
    assert rec_v2["key"] == rec_v1["key"]      # same fields -> same path

    def _boom(*a, **kw):
        raise OSError("simulated disk-full mid-write")

    monkeypatch.setattr(db.json, "dump", _boom)
    with pytest.raises(OSError):
        db.store(rec_v2, db_dir=db_dir)

    with open(final_path, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk["h2_g"] == pytest.approx(0.0111)


def test_rebuild_index_after_deleting_one_solve_file(tmp_path):
    db_dir = str(tmp_path / "db")
    recs = []
    for t in (0.690, 0.700):
        f = _fields(target_soc=t)
        rec = _record(f, target_soc=t)
        db.store(rec, db_dir=db_dir)
        recs.append(rec)
    assert len(db.load_index(db_dir).get("records", [])) == 2

    victim = os.path.join(db_dir, "solves", "%s.json" % recs[0]["key"])
    os.remove(victim)
    index = db.rebuild_index(db_dir)
    assert len(index["records"]) == 1
    assert index["records"][0]["key"] == recs[1]["key"]


def test_corrupt_index_json_self_heals_on_load(tmp_path):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    rec = _record(f)
    db.store(rec, db_dir=db_dir)

    index_path = os.path.join(db_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write("{not valid json::")

    index = db.load_index(db_dir)
    assert len(index.get("records", [])) == 1
    assert index["records"][0]["key"] == rec["key"]
    # The corrupt file must actually have been rewritten (self-healed), not
    # merely tolerated in memory.
    with open(index_path, encoding="utf-8") as fh:
        json.load(fh)          # raises if still corrupt


def test_index_missing_entirely_self_heals_on_load(tmp_path):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.5)
    rec = _record(f, target_soc=0.5)
    db.store(rec, db_dir=db_dir)
    os.remove(os.path.join(db_dir, "index.json"))
    index = db.load_index(db_dir)
    assert len(index["records"]) == 1


# ─────────────────────────────────────────────────────────────────────────
# item 10: solve_and_store() fingerprint refusal (numpy path, monkeypatched
# to avoid a real solve)
# ─────────────────────────────────────────────────────────────────────────

def test_solve_and_store_refuses_on_profile_fingerprint_mismatch(tmp_path,
                                                                  monkeypatch):
    np = pytest.importorskip("numpy")            # noqa: F841
    import gen_dp_ems_table as gen
    import hil_plant_sim as sim

    fake_scenario = "test-fingerprint-mismatch-scenario"
    monkeypatch.setitem(sim.SCENARIOS, fake_scenario, {"duration_s": 10.0})

    class _FakeProblem:
        fingerprint = "this-does-not-match-the-key"

    def _fake_prepare_problem(*a, **kw):
        return _FakeProblem()

    def _must_not_be_called(*a, **kw):
        raise AssertionError("solve_matched must not run when the "
                             "fingerprint check refuses first")

    monkeypatch.setattr(gen, "prepare_problem", _fake_prepare_problem)
    monkeypatch.setattr(gen, "solve_matched", _must_not_be_called)

    fields = _fields(scenario=fake_scenario,
                     profile_fingerprint="the-key-expects-this",
                     target_soc=0.698)
    db_dir = str(tmp_path / "db")
    with pytest.raises(ValueError, match="fingerprint drift"):
        db.solve_and_store(fields, 0.698, db_dir=db_dir, log=None)
    # And nothing was stored.
    assert not os.path.isdir(os.path.join(db_dir, "solves")) or \
        not os.listdir(os.path.join(db_dir, "solves"))


# ─────────────────────────────────────────────────────────────────────────
# item 11: _parse_span, prefill --dry-run, prefill skip-if-cached
# ─────────────────────────────────────────────────────────────────────────

def test_parse_span_evenly_spaced_inclusive_of_both_ends():
    vals = db._parse_span("0.0:1.0:5")
    assert vals == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])


def test_parse_span_single_point_returns_the_start():
    assert db._parse_span("0.3:0.9:1") == pytest.approx([0.3])


def test_parse_span_negative_start_form():
    vals = db._parse_span("-0.0030:-0.0010:3")
    assert vals == pytest.approx([-0.0030, -0.0020, -0.0010])


@pytest.mark.parametrize("text", [
    "0.0:1.0",              # only 2 parts
    "0.0:1.0:2:3",          # 4 parts
    "not-a-number:1.0:3",   # unparseable float
])
def test_parse_span_rejects_malformed_forms(text):
    with pytest.raises(ValueError):
        db._parse_span(text)


def test_parse_span_rejects_n_less_than_one():
    with pytest.raises(ValueError, match="N must be >= 1"):
        db._parse_span("0.0:1.0:0")


def test_prefill_dry_run_writes_nothing(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    db_dir = str(tmp_path / "db")
    rc = db.main(["--db-dir", db_dir, "prefill",
                 "--scenario", "ems-soc-band", "--soc0", "0.7",
                 "--dsoc-span=-0.0010:-0.0010:1",
                 "--stage-dt", "1.0", "--soc-step", "5e-5", "--n-share", "5",
                 "--dry-run"])
    assert rc == 0
    solves_dir = os.path.join(db_dir, "solves")
    assert not os.path.isdir(solves_dir) or not os.listdir(solves_dir)


def test_prefill_skips_a_target_already_cached(tmp_path, monkeypatch, capsys):
    pytest.importorskip("numpy")
    import gen_dp_ems_table as gen
    import hil_plant_sim as sim

    db_dir = str(tmp_path / "db")
    meta = sim.SCENARIOS["ems-soc-band"]
    run_exit = float(sim.SOC_BAND_RUN_EXIT_S)
    target = 0.7 - 0.0010
    fields = db.problem_fields(
        "ems-soc-band",
        profile_fingerprint=sim.dp_profile_fingerprint("ems-soc-band", meta),
        soc0=0.7, capacity_ah=5.0, charger_accounting="physical",
        stage_dt=1.0, n_share=5, soc_step=5e-5,
        chg_a=sim.dp_chg_ceiling_a(meta), lambda_dev=gen.DP_LAMBDA_DEV_G_PER_SOC_S,
        aux_preload_a=meta.get("aux_preload_a"), run_exit_s=run_exit,
        target_soc=target)
    db.store(_record(fields, target_soc=target), db_dir=db_dir)

    def _must_not_be_called(*a, **kw):
        raise AssertionError("prefill must not solve a cached target")

    monkeypatch.setattr(gen, "solve_matched", _must_not_be_called)

    rc = db.main(["--db-dir", db_dir, "prefill",
                 "--scenario", "ems-soc-band", "--soc0", "0.7",
                 "--dsoc-span=-0.0010:-0.0010:1",
                 "--stage-dt", "1.0", "--soc-step", "5e-5", "--n-share", "5",
                 "--tol", str(db.DP_DB_LOOKUP_TOL)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cached" in out
    assert "1 solved, 0 already cached" not in out  # sanity: not the inverse
    assert "0 solved, 1 already cached" in out


# ─────────────────────────────────────────────────────────────────────────
# fix-round-2 item 2: rekey_store() / `rekey` subcommand
# ─────────────────────────────────────────────────────────────────────────

def _stale_record(target_soc, coarse_q):
    """A record whose key_fields carry a `target_soc_q` computed under a
    COARSER quantum than the live DP_DB_TARGET_QUANTUM -- simulating a record
    written before a quantum tightening, without touching the module
    constant itself."""
    fields = _fields(target_soc=target_soc)          # live (correct) fields
    stale_fields = dict(fields)
    stale_fields["target_soc_q"] = coarse_q
    old_key = db.make_key(stale_fields)
    rec = _record(stale_fields, target_soc=target_soc)
    rec["key"] = old_key
    rec["key_fields"] = {k: stale_fields[k] for k in db.KEY_FIELDS}
    return rec, old_key, fields


def test_rekey_store_refiles_a_coarser_quantum_record_without_resolving(
        tmp_path, monkeypatch):
    db_dir = str(tmp_path / "db")
    target = 0.6981234
    # A quantum of 1e-4 (coarser than the live 1e-5) quantizes this target to
    # 0.6981, distinct from the live quantize_target() value.
    coarse_q = round(round(target / 1e-4) * 1e-4, 12)
    assert coarse_q != db.quantize_target(target)
    rec, old_key, live_fields = _stale_record(target, coarse_q)
    db.store(rec, db_dir=db_dir)
    assert db.get(old_key, db_dir=db_dir) is not None

    def _must_not_solve(*a, **kw):
        raise AssertionError("rekey must never re-solve")
    # rekey_store() is stdlib-only and imports nothing solve-related, but
    # patch gen.solve_matched anyway as a belt-and-braces guard in case a
    # future edit adds one.
    import sys as _sys
    if "gen_dp_ems_table" in _sys.modules:
        monkeypatch.setattr(_sys.modules["gen_dp_ems_table"], "solve_matched",
                           _must_not_solve, raising=False)

    moved = db.rekey_store(db_dir)
    assert len(moved) == 1
    old, new = moved[0]
    assert old == old_key
    new_key_expected = db.make_key(live_fields)
    assert new == new_key_expected

    # The old file is GONE, the new key is reachable, and the index agrees.
    assert db.get(old_key, db_dir=db_dir) is None
    new_rec = db.get(new, db_dir=db_dir)
    assert new_rec is not None
    assert new_rec["target_soc"] == pytest.approx(target)
    index_keys = {e.get("key") for e in db.load_index(db_dir)["records"]}
    assert new in index_keys
    assert old_key not in index_keys
    # And it is genuinely reachable through lookup() at the live key.
    assert db.lookup(live_fields, db_dir=db_dir)["key"] == new


def test_rekey_store_dry_run_reports_without_moving_anything(tmp_path):
    db_dir = str(tmp_path / "db")
    target = 0.6981234
    coarse_q = round(round(target / 1e-4) * 1e-4, 12)
    rec, old_key, _live_fields = _stale_record(target, coarse_q)
    db.store(rec, db_dir=db_dir)

    moved = db.rekey_store(db_dir, dry_run=True)
    assert len(moved) == 1
    # The old file is UNTOUCHED and no new file was created.
    assert db.get(old_key, db_dir=db_dir) is not None
    solves_dir = os.path.join(db_dir, "solves")
    assert len(os.listdir(solves_dir)) == 1


def test_rekey_store_leaves_an_already_current_record_alone(tmp_path):
    db_dir = str(tmp_path / "db")
    f = _fields(target_soc=0.698)
    rec = _record(f, target_soc=0.698)
    db.store(rec, db_dir=db_dir)
    moved = db.rekey_store(db_dir)
    assert moved == []
    assert db.get(rec["key"], db_dir=db_dir) is not None


def test_rekey_cli_subcommand_dry_run_then_real(tmp_path, capsys):
    db_dir = str(tmp_path / "db")
    target = 0.6981234
    coarse_q = round(round(target / 1e-4) * 1e-4, 12)
    rec, old_key, _live_fields = _stale_record(target, coarse_q)
    db.store(rec, db_dir=db_dir)

    rc = db.main(["--db-dir", db_dir, "rekey", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WOULD REKEY" in out
    assert "1 record(s) would be re-keyed" in out
    assert db.get(old_key, db_dir=db_dir) is not None    # dry-run: untouched

    rc = db.main(["--db-dir", db_dir, "rekey"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "rekeyed" in out
    assert "1 record(s) re-keyed" in out
    assert db.get(old_key, db_dir=db_dir) is None         # now actually moved


# ─────────────────────────────────────────────────────────────────────────
# fix-round-2 item 2: prefill --key-fields (JSON literal and @file forms)
# ─────────────────────────────────────────────────────────────────────────

def test_load_key_fields_json_literal_round_trips():
    import json as _json
    payload = {name: 1.0 for name in db.KEY_FIELDS}
    payload["scenario"] = "ems-soc-band"
    payload["profile_fingerprint"] = "fp"
    payload["charger_accounting"] = "physical"
    payload["target_soc"] = 0.7
    loaded = db.load_key_fields(_json.dumps(payload))
    assert loaded["scenario"] == "ems-soc-band"
    assert db.make_key(loaded) == db.make_key(payload)


def test_load_key_fields_at_file_form_round_trips(tmp_path):
    import json as _json
    payload = {name: 1.0 for name in db.KEY_FIELDS}
    payload["scenario"] = "ems-soc-band"
    payload["profile_fingerprint"] = "fp"
    payload["charger_accounting"] = "physical"
    payload["target_soc"] = 0.7
    p = tmp_path / "key_fields.json"
    p.write_text(_json.dumps(payload), encoding="utf-8")
    loaded = db.load_key_fields("@%s" % p)
    assert db.make_key(loaded) == db.make_key(payload)


def test_load_key_fields_rejects_missing_fields():
    import json as _json
    incomplete = {"scenario": "ems-soc-band"}
    with pytest.raises(ValueError, match="missing"):
        db.load_key_fields(_json.dumps(incomplete))


def test_load_key_fields_rejects_a_non_object_json():
    import json as _json
    with pytest.raises(ValueError, match="JSON object"):
        db.load_key_fields(_json.dumps([1, 2, 3]))


def test_prefill_key_fields_reproduces_the_same_key_and_reports_cached(
        tmp_path, capsys):
    """The exact-reproduction path: pre-store a record at the key
    problem_fields() produces for a hand-built dict, feed that SAME dict back
    through --key-fields (both the JSON-literal and @file forms), and prefill
    must recognise it as already cached -- i.e. it computed the identical
    key -- without ever needing to solve."""
    pytest.importorskip("numpy")
    import json as _json
    db_dir = str(tmp_path / "db")
    fields = db.problem_fields(
        "ems-soc-band",
        profile_fingerprint="fp-key-fields-roundtrip",
        soc0=0.7, capacity_ah=5.0, charger_accounting="physical",
        stage_dt=1.0, n_share=5, soc_step=5e-5, chg_a=0.8, lambda_dev=0.0,
        aux_preload_a=0.0, run_exit_s=58.0, target_soc=0.699)
    db.store(_record(fields, target_soc=fields["target_soc"]), db_dir=db_dir)

    rc = db.main(["--db-dir", db_dir, "prefill",
                 "--key-fields", _json.dumps(fields)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "already cached" in out

    kf_path = tmp_path / "key_fields.json"
    kf_path.write_text(_json.dumps(fields), encoding="utf-8")
    rc = db.main(["--db-dir", db_dir, "prefill",
                 "--key-fields", "@%s" % kf_path])
    assert rc == 0
    out = capsys.readouterr().out
    assert "already cached" in out


def test_prefill_key_fields_dry_run_would_solve_and_writes_nothing(tmp_path,
                                                                    capsys):
    pytest.importorskip("numpy")
    import json as _json
    db_dir = str(tmp_path / "db")
    fields = db.problem_fields(
        "ems-soc-band",
        profile_fingerprint="fp-key-fields-dry-run",
        soc0=0.7, capacity_ah=5.0, charger_accounting="physical",
        stage_dt=1.0, n_share=5, soc_step=5e-5, chg_a=0.8, lambda_dev=0.0,
        aux_preload_a=0.0, run_exit_s=58.0, target_soc=0.699)
    rc = db.main(["--db-dir", db_dir, "prefill",
                 "--key-fields", _json.dumps(fields), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WOULD SOLVE" in out
    solves_dir = os.path.join(db_dir, "solves")
    assert not os.path.isdir(solves_dir) or not os.listdir(solves_dir)


# ─────────────────────────────────────────────────────────────────────────
# fix-round-2 item 2: prefill --aux-preload / --chg-a / --run-exit reach the
# key (via a spy on the module-level problem_fields())
# ─────────────────────────────────────────────────────────────────────────

def test_prefill_flags_aux_preload_chg_a_run_exit_reach_the_key(
        tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    db_dir = str(tmp_path / "db")
    real_problem_fields = db.problem_fields
    calls = []

    def _spy(*a, **kw):
        calls.append(kw)
        return real_problem_fields(*a, **kw)

    monkeypatch.setattr(db, "problem_fields", _spy)
    rc = db.main(["--db-dir", db_dir, "prefill",
                 "--scenario", "ems-soc-band", "--soc0", "0.7",
                 "--dsoc-span=-0.0010:-0.0010:1",
                 "--stage-dt", "1.0", "--soc-step", "5e-5", "--n-share", "5",
                 "--aux-preload", "0.42", "--chg-a", "0.99",
                 "--run-exit", "50.0", "--dry-run"])
    assert rc == 0
    assert len(calls) == 1
    kw = calls[0]
    assert kw["aux_preload_a"] == pytest.approx(0.42)
    assert kw["chg_a"] == pytest.approx(0.99)
    assert kw["run_exit_s"] == pytest.approx(50.0)


def test_prefill_flags_default_to_scenario_values_when_omitted(tmp_path,
                                                                monkeypatch):
    """The other half: omitting the three flags must fall back to the
    scenario's OWN chg ceiling / run-exit / declared preload, not to a bare
    0.0 / None that would silently change the problem being solved."""
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    import gen_dp_ems_table as gen
    db_dir = str(tmp_path / "db")
    real_problem_fields = db.problem_fields
    calls = []

    def _spy(*a, **kw):
        calls.append(kw)
        return real_problem_fields(*a, **kw)

    monkeypatch.setattr(db, "problem_fields", _spy)
    meta = sim.SCENARIOS["ems-soc-band"]
    rc = db.main(["--db-dir", db_dir, "prefill",
                 "--scenario", "ems-soc-band", "--soc0", "0.7",
                 "--dsoc-span=-0.0010:-0.0010:1",
                 "--stage-dt", "1.0", "--soc-step", "5e-5", "--n-share", "5",
                 "--dry-run"])
    assert rc == 0
    kw = calls[0]
    assert kw["chg_a"] == pytest.approx(sim.dp_chg_ceiling_a(meta))
    assert kw["run_exit_s"] == pytest.approx(float(sim.SOC_BAND_RUN_EXIT_S))
    assert kw["aux_preload_a"] == meta.get("aux_preload_a")


# ==========================================================================
# ADDED BY THE STAGE-1 IMPLEMENTER (2026-09-01), NOT THE TEST-WRITER.
# The test-writer stage had closed when the stimulus-era generalization
# (MED follow-up) landed; the coordinator authorized a minimal extension for
# that item only. Everything below covers era_overrides / fingerprint
# reconstruction and nothing else.
# ==========================================================================


def _era_fields(**over):
    """Key fields for ems-soc-band with an era_overrides object."""
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    base = dict(profile_fingerprint="fp", soc0=0.7, capacity_ah=5.0,
                charger_accounting="physical", stage_dt=0.1, n_share=41,
                soc_step=5e-6, chg_a=0.8, lambda_dev=0.0, aux_preload_a=0.0,
                run_exit_s=58.0, target_soc=0.698)
    base.update(over)
    return db.problem_fields("ems-soc-band", **base)


def test_apply_era_overrides_sets_replaces_and_deletes():
    meta = {"a": 1.0, "b": 2.0}
    out = db.apply_era_overrides(meta, {"a": 9.0, "b": None, "c": 3.0})
    assert out == {"a": 9.0, "c": 3.0}
    assert meta == {"a": 1.0, "b": 2.0}          # input untouched
    assert db.apply_era_overrides(meta, None) == meta
    assert db.apply_era_overrides(None, {}) == {}


def test_fingerprint_parts_reproduces_dp_profile_fingerprint():
    """The diff helper must hash to the same digest as the real function --
    otherwise a mismatch message would name the wrong key."""
    import hil_plant_sim as sim
    for name in ("ems-soc-band", "ems-dp-replay"):
        meta = sim.SCENARIOS[name]
        parts = db.fingerprint_parts(name, meta)
        assert db.fingerprint_from_parts(parts) == \
            sim.dp_profile_fingerprint(name, meta)


def test_fingerprint_diff_names_only_the_changed_keys():
    import hil_plant_sim as sim
    meta = sim.SCENARIOS["ems-soc-band"]
    other = db.apply_era_overrides(meta, {"chg_i_ceiling_a": 0.123})
    assert sorted(db.fingerprint_diff("ems-soc-band", meta, other)) == \
        ["chg_i_ceiling_a"]
    assert db.fingerprint_diff("ems-soc-band", meta, dict(meta)) == {}


def test_fingerprint_diff_raises_when_reconstruction_goes_stale(monkeypatch):
    monkeypatch.setattr(db, "fingerprint_from_parts",
                        lambda parts: "not-the-real-digest")
    import hil_plant_sim as sim
    with pytest.raises(RuntimeError):
        db.fingerprint_diff("ems-soc-band", sim.SCENARIOS["ems-soc-band"],
                            sim.SCENARIOS["ems-soc-band"])


def test_problem_fields_carries_era_overrides_without_keying_on_them():
    """era_overrides is a payload, not a key field: the fingerprint it
    produced is already in the key, so keying on it too would split one
    problem across two records."""
    a = _era_fields(era_overrides={"chg_i_ceiling_a": 2.5})
    b = _era_fields(era_overrides=None)
    assert a["era_overrides"] == {"chg_i_ceiling_a": 2.5}
    assert b["era_overrides"] == {}
    assert "era_overrides" not in db.KEY_FIELDS
    assert db.make_key(a) == db.make_key(b)


def test_load_key_fields_accepts_and_validates_era_overrides(tmp_path):
    fields = _era_fields(era_overrides={"chg_i_ceiling_a": 2.5})
    path = tmp_path / "kf.json"
    path.write_text(json.dumps(fields), encoding="utf-8")
    assert db.load_key_fields("@%s" % path)["era_overrides"] == \
        {"chg_i_ceiling_a": 2.5}
    bad = dict(fields, era_overrides=[1, 2])
    with pytest.raises(ValueError, match="era_overrides"):
        db.load_key_fields(json.dumps(bad))
    # An object predating the field is still accepted.
    old = {k: v for k, v in fields.items() if k != "era_overrides"}
    assert "era_overrides" not in db.load_key_fields(json.dumps(old))


def test_solve_and_store_rebuilds_the_run_era_meta(tmp_path, monkeypatch):
    """The reported production failure: a scenario-meta change after the run
    moved the fingerprint, and a preload-only reconstruction could not put it
    back. With era_overrides the solve reaches the recorded fingerprint."""
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    import gen_dp_ems_table as gen

    name = "ems-soc-band"
    run_era = dict(sim.SCENARIOS[name])
    run_era_fp = sim.dp_profile_fingerprint(name, run_era)

    # The parallel round's change, simulated.
    monkeypatch.setitem(sim.SCENARIOS, name,
                        dict(run_era, chg_i_ceiling_a=0.123))
    assert sim.dp_profile_fingerprint(name, sim.SCENARIOS[name]) != run_era_fp

    monkeypatch.setattr(gen, "solve_matched", lambda p, **kw: gen.MatchedSolve(
        1.0, 1.0, 0.698, -0.002, 0.0, True, 1.0, 1, 0.0, [0.5], [0.0],
        [0.7, 0.698], 0.0))

    fields = _era_fields(
        profile_fingerprint=run_era_fp,
        chg_a=sim.dp_chg_ceiling_a(run_era),
        era_overrides={"chg_i_ceiling_a": run_era.get("chg_i_ceiling_a")})
    rec = db.solve_and_store(fields, 0.698, db_dir=str(tmp_path), log=None)
    assert rec["h2_g"] == pytest.approx(1.0)
    assert rec["key_fields"]["profile_fingerprint"] == run_era_fp

    # Stripping them reproduces the failure, and the message names the keys.
    with pytest.raises(ValueError) as exc:
        db.solve_and_store(dict(fields, era_overrides={}), 0.698,
                           db_dir=str(tmp_path), log=None)
    msg = str(exc.value)
    assert "profile fingerprint drift" in msg
    assert "chg_i_ceiling_a" in msg
    assert "NOT overridable" in msg          # the constants are separated out


# ==========================================================================
# 2026-09-01 charger-efficiency round (WP-1B1): `eta_chg` as an OPTIONAL key
# field.  The store holds only old-era records, and they must stay reachable.
# ==========================================================================

def test_eta_chg_is_a_key_field_and_none_omits_it_from_the_canonical_form():
    assert "eta_chg" in db.KEY_FIELDS
    assert "eta_chg" in db.OPTIONAL_KEY_FIELDS
    old = _fields()
    assert old["eta_chg"] is None
    # A dict that predates the field keys IDENTICALLY to one that carries None,
    # which is what keeps every archived record reachable.
    legacy = {k: v for k, v in old.items() if k != "eta_chg"}
    assert db.make_key(legacy) == db.make_key(old)
    assert db.non_target_hash(legacy) == db.non_target_hash(old)


def test_a_new_era_record_keys_differently_from_an_old_era_one():
    old = _fields()
    new = _fields(eta_chg=0.88)
    assert db.make_key(new) != db.make_key(old)
    assert db.non_target_hash(new) != db.non_target_hash(old)


def test_old_era_lookup_still_finds_a_stored_old_era_record(tmp_path):
    fields = _fields()
    db.store(_record(fields), db_dir=str(tmp_path))
    # Looked up BOTH ways: with the field present as None, and with a
    # pre-change field dict that does not carry it at all.
    assert db.lookup(fields, db_dir=str(tmp_path)) is not None
    legacy = {k: v for k, v in fields.items() if k != "eta_chg"}
    assert db.lookup(legacy, db_dir=str(tmp_path)) is not None
    # A new-era lookup MISSES it, which is the point of keying the era.
    assert db.lookup(_fields(eta_chg=0.88), db_dir=str(tmp_path)) is None


def test_committed_store_records_key_unchanged_under_the_new_field():
    """Every record actually in tools/dp_db/ must still hash to its own key."""
    recs = list(db.iter_records())
    if not recs:
        pytest.skip("empty store in this checkout")
    for rec in recs:
        f = dict(rec["key_fields"])
        f["target_soc"] = rec["target_soc"]
        assert db.make_key(f) == rec["key"], rec["key"]


def test_load_key_fields_accepts_an_object_without_the_optional_field(tmp_path):
    obj = {k: v for k, v in _fields().items() if k != "eta_chg"}
    p = tmp_path / "k.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    got = db.load_key_fields("@" + str(p))
    assert "eta_chg" not in got
    assert db.make_key(got) == db.make_key(_fields())


def test_era_overrides_accept_eta_chg():
    """`eta_chg` joined DP_FINGERPRINT_META_KEYS, so an archived run's era is
    reconstructable through the same override mechanism as its preload."""
    sim = pytest.importorskip("hil_plant_sim")
    if "eta_chg" not in getattr(sim, "DP_FINGERPRINT_META_KEYS", ()):
        pytest.skip("this checkout's hil_plant_sim does not carry eta_chg in "
                    "DP_FINGERPRINT_META_KEYS yet (parallel work package)")
    meta = dict(sim.SCENARIOS["ems-soc-band"])
    a = db.apply_era_overrides(meta, {"eta_chg": None})
    b = db.apply_era_overrides(meta, {"eta_chg": 0.5})
    assert "eta_chg" not in a           # None DELETES, per apply_era_overrides
    assert b["eta_chg"] == 0.5
    # The DELETED key is NOT the old era here: hil_plant_sim.dp_eta_chg()
    # resolves an absent key to the module's own ETA_CHG, so `a` fingerprints
    # as the LIVE efficiency.  0.5 is used as the contrasting value precisely
    # because it is not that default - overriding with the default would move
    # nothing and the test would pass vacuously.
    assert sim.dp_profile_fingerprint("ems-soc-band", a) != \
        sim.dp_profile_fingerprint("ems-soc-band", b)
    assert sim.dp_profile_fingerprint("ems-soc-band", a) == \
        sim.dp_profile_fingerprint(
            "ems-soc-band", dict(meta, eta_chg=sim.dp_eta_chg({})))


def test_fields_from_problem_carries_the_problems_era():
    pytest.importorskip("numpy")
    import gen_dp_ems_table as gen
    import hil_plant_sim as sim
    meta = sim.SCENARIOS["ems-soc-band"]
    kw = dict(soc0=0.7, capacity_ah=5.0, stage_dt=1.0, n_share=5,
              soc_step=5e-5, run_exit=float(sim.SOC_BAND_RUN_EXIT_S),
              charger_accounting="physical")
    p_old = gen.prepare_problem("ems-soc-band", meta, **kw)
    p_new = gen.prepare_problem("ems-soc-band", meta, eta_chg=0.88, **kw)
    assert db.fields_from_problem(p_old, 0.698)["eta_chg"] is None
    assert db.fields_from_problem(p_new, 0.698)["eta_chg"] == 0.88


# ==========================================================================
# 2026-09-02 review: H2 (the duplicated --eta-chg registrations) and M4
# (the two era flags, and the era reaching the FINGERPRINT).
# ==========================================================================

def test_every_subcommand_parses_h2_the_duplicate_registrations_are_gone():
    """H2: `--eta-chg` / `--eta-chg-none` were registered ten times on the
    prefill parser, which raises argparse.ArgumentError at parser BUILD time -
    i.e. every subcommand of this tool, including `list`, died before doing
    anything. A parse of each subcommand is the regression."""
    with pytest.raises(SystemExit) as exc:
        db.main(["list", "--help"])
    assert exc.value.code == 0
    for cmd in ("show", "rebuild-index", "rekey", "prefill"):
        with pytest.raises(SystemExit) as exc:
            db.main([cmd, "--help"])
        assert exc.value.code == 0


def test_prefill_refuses_both_era_flags_together(tmp_path, capsys):
    """M4(a): `--eta-chg-none` wins silently inside problem_fields(), so a
    caller passing both would get an OLD-era solve while believing they asked
    for the eta era. It must be a refusal, not a precedence rule."""
    rc = db.main(["--db-dir", str(tmp_path / "db"), "prefill",
                  "--scenario", "ems-soc-band", "--soc0", "0.7",
                  "--dsoc-span=-0.0010:-0.0010:1",
                  "--eta-chg", "0.88", "--eta-chg-none", "--dry-run"])
    assert rc == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_prefill_era_reaches_the_profile_fingerprint(tmp_path, monkeypatch):
    """M4(b): keying an explicit era while fingerprinting the LIVE scenario
    meta produced a record no post-eta run could ever hit - a post-eta run's
    sidecar carries `eta_chg`, so it fingerprints differently. The eta-era
    prefill must therefore fingerprint over the era-resolved meta, and the
    old-era one must be unchanged (the term is omitted when it resolves to
    None)."""
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    calls = []
    real = db.problem_fields

    def _spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(db, "problem_fields", _spy)
    base = ["--db-dir", str(tmp_path / "db"), "prefill",
            "--scenario", "ems-soc-band", "--soc0", "0.7",
            "--dsoc-span=-0.0010:-0.0010:1",
            "--stage-dt", "1.0", "--soc-step", "5e-5", "--n-share", "5",
            "--dry-run"]
    assert db.main(base) == 0
    assert db.main(base + ["--eta-chg", "0.88"]) == 0
    meta = sim.SCENARIOS["ems-soc-band"]
    old_fp = calls[0]["profile_fingerprint"]
    new_fp = calls[1]["profile_fingerprint"]
    assert old_fp == sim.dp_profile_fingerprint("ems-soc-band", meta)
    assert new_fp == sim.dp_profile_fingerprint(
        "ems-soc-band", dict(meta, eta_chg=0.88))
    assert new_fp != old_fp
    # L8 (review 2026-09-02): the era must reach the KEY FIELDS too, not only
    # the fingerprint — a record fingerprinted for the eta era but keyed at the
    # old one is unreachable from the era it was solved for.
    assert calls[0]["eta_chg"] is None
    assert calls[1]["eta_chg"] == 0.88


def test_prefill_eta_chg_none_fingerprints_exactly_as_the_bare_default(
        tmp_path, monkeypatch):
    """The explicit old-era flag must key and fingerprint identically to the
    bare default - the old era IS the absence of the term."""
    pytest.importorskip("numpy")
    calls = []
    real = db.problem_fields

    def _spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(db, "problem_fields", _spy)
    base = ["--db-dir", str(tmp_path / "db"), "prefill",
            "--scenario", "ems-soc-band", "--soc0", "0.7",
            "--dsoc-span=-0.0010:-0.0010:1",
            "--stage-dt", "1.0", "--soc-step", "5e-5", "--n-share", "5",
            "--dry-run"]
    assert db.main(base) == 0
    assert db.main(base + ["--eta-chg-none"]) == 0
    assert calls[0]["profile_fingerprint"] == calls[1]["profile_fingerprint"]
    assert calls[0]["eta_chg"] is None and calls[1]["eta_chg"] is None


# ==========================================================================
# `prefill --scenario ... --eta-chg X` (campaign 20260902_011926, item 6)
#
# _cmd_prefill() resolves the era INTO the meta it fingerprints, but
# solve_and_store() then re-fingerprinted the LIVE meta (which declares no
# `eta_chg`), so every such solve died on "profile fingerprint drift" before it
# started -- the exact-reproduction `--key-fields` path was the only one that
# worked, because a run's key_fields carry era_overrides.
# ==========================================================================

def test_solve_and_store_resolves_the_charger_era_into_the_fingerprint(
        tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    import gen_dp_ems_table as gen

    name = "ems-soc-band"
    live = dict(sim.SCENARIOS[name])
    # What `prefill --scenario ... --eta-chg 0.88` computes: the live meta with
    # the era resolved in.
    era_fp = sim.dp_profile_fingerprint(name, dict(live, eta_chg=0.88))
    assert era_fp != sim.dp_profile_fingerprint(name, live)

    monkeypatch.setattr(gen, "solve_matched", lambda p, **kw: gen.MatchedSolve(
        1.0, 1.0, 0.698, -0.002, 0.0, True, 1.0, 1, 0.0, [0.5], [0.0],
        [0.7, 0.698], 0.0))

    # NOTE: no era_overrides — this is the `--scenario` path, not `--key-fields`.
    fields = _era_fields(profile_fingerprint=era_fp, eta_chg=0.88)
    assert not fields.get("era_overrides")
    rec = db.solve_and_store(fields, 0.698, db_dir=str(tmp_path), log=None)
    assert rec["key_fields"]["profile_fingerprint"] == era_fp
    assert rec["key_fields"]["eta_chg"] == 0.88


def test_explicit_era_overrides_still_win_over_the_eta_field(
        tmp_path, monkeypatch):
    """`era_overrides` is the caller's explicit channel and must not be
    second-guessed: a key that names an era there decides it."""
    pytest.importorskip("numpy")
    import hil_plant_sim as sim
    import gen_dp_ems_table as gen

    name = "ems-soc-band"
    live = dict(sim.SCENARIOS[name])
    fp = sim.dp_profile_fingerprint(name, dict(live, eta_chg=0.5))
    monkeypatch.setattr(gen, "solve_matched", lambda p, **kw: gen.MatchedSolve(
        1.0, 1.0, 0.698, -0.002, 0.0, True, 1.0, 1, 0.0, [0.5], [0.0],
        [0.7, 0.698], 0.0))
    fields = _era_fields(profile_fingerprint=fp, eta_chg=0.88,
                         era_overrides={"eta_chg": 0.5})
    rec = db.solve_and_store(fields, 0.698, db_dir=str(tmp_path), log=None)
    assert rec["key_fields"]["profile_fingerprint"] == fp


# ═════════════════════════════════════════════════════════════════════════
# `loss_map` AS AN OPTIONAL KEY FIELD (2026-09-02, the DP-bound round)
# ═════════════════════════════════════════════════════════════════════════
_LM_TEXT = ("v0_eff=15.871722,r_fix=0.017986,k_g=1.95079,g_par=0.148922,"
            "g_node_bus=3.3333333333333335e-05,"
            "g_node_other=1.6666666666666667e-05,rt_v_fwd=0.035,rt_r_on=0.021")


def test_loss_map_is_a_key_field_and_an_optional_one():
    assert "loss_map" in db.KEY_FIELDS
    assert "loss_map" in db.OPTIONAL_KEY_FIELDS


def test_an_absent_loss_map_keys_exactly_as_the_pre_round_code_did():
    """THE OMISSION ARGUMENT, executable.  An ABSENT map names the demand
    model every record in the shipped store was solved against, so its
    canonical form must be byte-identical to the pre-2026-09-02 one and all
    30 stored records must stay reachable."""
    f_absent = _fields()
    del f_absent["loss_map"]
    f_none = _fields(loss_map=None)
    assert db._canonical(f_absent) == db._canonical(f_none)
    assert "loss_map" not in db._canonical(f_absent)
    assert db.make_key(f_absent) == db.make_key(f_none)


def test_the_two_demand_eras_key_apart():
    """A baseline solved on a different demand model is not a baseline for
    this one, which is the whole reason the key carries the map."""
    old = db.make_key(_fields(loss_map=None))
    new = db.make_key(_fields(loss_map=_LM_TEXT))
    assert old != new
    # ... and a map with a DIFFERENT coefficient keys apart again, so a
    # re-probe cannot silently reuse the previous fit's records.
    other = db.make_key(_fields(loss_map=_LM_TEXT.replace("15.871722",
                                                          "15.9")))
    assert other not in (old, new)


def test_the_loss_map_is_carried_as_a_string_not_a_dict():
    """`_canonical` renders a str verbatim and everything else through
    `repr(float(...))`, so a dict would raise.  The key field is therefore the
    CANONICAL STRING, and this test pins that contract."""
    text = db._canonical(_fields(loss_map=_LM_TEXT))
    assert '"loss_map":"%s"' % _LM_TEXT in text
    bad = _fields()
    bad["loss_map"] = {"v0_eff": 15.871722}      # a dict, bypassing _fields()
    with pytest.raises((TypeError, ValueError)):
        db._canonical(bad)


def test_the_non_target_hash_also_omits_an_absent_map():
    f_absent = _fields()
    del f_absent["loss_map"]
    assert db.non_target_hash(f_absent) == \
        db.non_target_hash(_fields(loss_map=None))
    assert db.non_target_hash(f_absent) != \
        db.non_target_hash(_fields(loss_map=_LM_TEXT))


def test_apply_era_overrides_carries_a_map_and_deletes_it_on_none():
    lm = {"v0_eff": 15.871722}
    meta = db.apply_era_overrides({"duration_s": 61.0}, {"loss_map": lm})
    assert meta["loss_map"] == lm
    assert db.apply_era_overrides(meta, {"loss_map": None}) == \
        {"duration_s": 61.0}


def test_every_stored_record_is_still_reachable_by_its_own_key():
    """THE REGRESSION THE OMISSION EXISTS FOR.  Adding a key field must not
    orphan a single archived solve."""
    import glob
    root = os.path.join(HERE, "dp_db")
    if not os.path.isdir(root):
        pytest.skip("dp_db store not present in this checkout")
    seen = 0
    for path in glob.glob(os.path.join(root, "**", "*.json"), recursive=True):
        if os.path.basename(path) == "index.json":
            continue
        rec = json.load(open(path, encoding="utf-8"))
        kf = rec.get("key_fields")
        if not kf:
            continue
        seen += 1
        assert db.make_key(kf) == rec["key"], path
    assert seen >= 16, "expected the archived solves to be present"


def test_solve_and_store_recovers_the_map_from_a_stored_records_own_fields():
    """`store()` persists only KEY_FIELDS, so a record read back off disk
    carries the CANONICAL STRING and not the dict the caller built.  A prefill
    fed those bytes must still reconstruct the same problem, or the store's
    own records become unusable as prefill inputs one era after they were
    written."""
    import glob
    sim = pytest.importorskip("hil_plant_sim")
    root = os.path.join(HERE, "dp_db")
    if not os.path.isdir(root):
        pytest.skip("dp_db store not present in this checkout")
    seen = 0
    for path in glob.glob(os.path.join(root, "**", "*.json"), recursive=True):
        if os.path.basename(path) == "index.json":
            continue
        kf = json.load(open(path, encoding="utf-8")).get("key_fields") or {}
        assert "loss_map_dict" not in kf, path      # never persisted
        text = kf.get("loss_map")
        if text is None:
            continue
        seen += 1
        # The string parses back to a VALID map, and to the one this checkout
        # ships (every loss-map record in the store was solved against it).
        assert sim.loss_map_from_canonical(text) == sim.plant_loss_map(), path
    assert seen >= 1, ("no loss-map-era record in the store; the seven "
                       "loss-map-era EMS prefills are part of this round")


# ─────────────────────────────────────────────────────────────────────────────
# THE ROAD-LOAD AND REGEN ERAS AS KEY FIELDS (2026-09-02, the ftp75c round)
#
# `drag` and `eta_regen` joined KEY_FIELDS on exactly the terms `eta_chg` and
# `loss_map` did, and the reachability argument is the same one: an ABSENT
# `drag` names the MEASURED RIG ROAD LOAD and an ABSENT `eta_regen` the
# PRE-REGEN demand model, which is what every record in the shipped store was
# solved against.  Both are OMITTED from the canonical form, so those records
# keep their pre-change keys.
# ─────────────────────────────────────────────────────────────────────────────

def test_drag_and_eta_regen_are_optional_key_fields():
    assert "drag" in db.KEY_FIELDS and "eta_regen" in db.KEY_FIELDS
    assert {"drag", "eta_regen"} <= set(db.OPTIONAL_KEY_FIELDS)


def test_an_absent_drag_keys_exactly_as_the_pre_round_code_did():
    """THE OMISSION ARGUMENT, executable, for the third optional field."""
    f_absent = _fields()
    del f_absent["drag"]
    f_none = _fields(drag=None)
    f_rig = _fields(drag="rig")
    assert db._canonical(f_absent) == db._canonical(f_none)
    assert "drag" not in db._canonical(f_absent)
    assert db.make_key(f_absent) == db.make_key(f_none)
    # ⚠️ "rig" is NOT the same canonical statement as an omission at THIS
    # layer: `_canonical` records what it is given, and it is
    # `problem_fields()` that normalises the mode through `plant_drag_mode()`
    # BEFORE the record is built (asserted separately below). Pinning the
    # normalisation at its real site is the point -- a reader must not think
    # the store itself understands the sentinel.
    assert db.make_key(f_rig) != db.make_key(f_absent)


def test_an_absent_eta_regen_keys_exactly_as_the_pre_round_code_did():
    f_absent = _fields()
    del f_absent["eta_regen"]
    f_none = _fields(eta_regen=None)
    assert db._canonical(f_absent) == db._canonical(f_none)
    assert "eta_regen" not in db._canonical(f_absent)
    assert db.make_key(f_absent) == db.make_key(f_none)


def test_the_two_road_load_eras_key_apart():
    old = db.make_key(_fields(drag=None))
    new = db.make_key(_fields(drag="scaled-air"))
    other = db.make_key(_fields(drag="scaled-air-matched"))
    assert len({old, new, other}) == 3
    # ... and the regen era keys apart on its own axis, because the two are
    # INDEPENDENT: a rig-drag run in the regen era is legitimate and simply
    # earns zero credit.
    assert db.make_key(_fields(eta_regen=0.8)) != \
        db.make_key(_fields(eta_regen=None))
    assert db.make_key(_fields(drag="scaled-air", eta_regen=0.8)) != new


def test_the_drag_field_is_carried_as_a_mode_string_not_a_k_air_value():
    """`_canonical` renders a str verbatim and everything else through
    `repr(float(...))`, so the field must be the MODE STRING -- a k_air float
    would key two modes apart correctly today and silently re-key every record
    the moment `Cd * A_f` is corrected."""
    text = db._canonical(_fields(drag="scaled-air"))
    assert '"drag":"scaled-air"' in text
    assert "0.0598" not in text


def test_problem_fields_normalises_the_rig_sentinel_to_an_omission():
    """The normalisation lives in `problem_fields()`, through
    `plant_drag_mode()`, so a caller that passes "rig" and a caller that passes
    nothing produce the SAME record -- which is what keeps a pre-round record
    reachable from a post-round lookup."""
    pytest.importorskip("numpy")     # problem_fields() -> model_fields() -> gen
    import inspect
    sig = inspect.signature(db.problem_fields).parameters
    assert sig["drag"].default is None
    assert sig["eta_regen"].default is None
    common = dict(profile_fingerprint="fp-aaaa", soc0=0.7, capacity_ah=5.0,
                  charger_accounting="physical", stage_dt=0.1, n_share=41,
                  soc_step=5e-6, chg_a=0.8, lambda_dev=0.0,
                  aux_preload_a=None, run_exit_s=58.0, target_soc=0.698)
    a = db.problem_fields("ems-soc-band", **common)
    b = db.problem_fields("ems-soc-band", drag="rig", **common)
    c = db.problem_fields("ems-soc-band", drag="scaled-air", **common)
    assert a["drag"] is None and b["drag"] is None
    assert db.make_key(a) == db.make_key(b)
    assert c["drag"] == "scaled-air"
    assert db.make_key(c) != db.make_key(a)
    # `eta_regen` passes through as a float-or-None, no normalisation needed:
    # it has no non-None spelling of its own sentinel.
    d = db.problem_fields("ems-soc-band", eta_regen=0.8, **common)
    assert d["eta_regen"] == 0.8
    assert db.problem_fields("ems-soc-band", eta_regen=None,
                             **common)["eta_regen"] is None


def test_the_non_target_hash_also_omits_both_absent_era_fields():
    """The non-target hash is what a nearest-target lookup matches on, so an
    omission that held for the key but not for it would make every stored
    record unreachable by proximity."""
    f_absent = _fields()
    del f_absent["drag"]
    del f_absent["eta_regen"]
    f_none = _fields(drag=None, eta_regen=None)
    assert db.non_target_hash(f_absent) == db.non_target_hash(f_none)
    assert db.non_target_hash(_fields(drag="scaled-air")) != \
        db.non_target_hash(f_none)


def test_every_stored_record_is_still_reachable_after_the_two_keys_landed():
    """THE REACHABILITY CLAIM AT THE STORE, not at the field dict: a record
    written before either key existed must still be found by a lookup made
    today.  The fingerprint move that orphaned all 16 records once already is
    the failure this guards."""
    f_old = _fields()
    del f_old["drag"]
    del f_old["eta_regen"]
    key_old = db.make_key(f_old)
    f_now = _fields()                 # today's caller: both at their sentinels
    assert db.make_key(f_now) == key_old
    assert db.non_target_hash(f_now) == db.non_target_hash(f_old)
