#!/usr/bin/env python3
"""pytest suite for tools/mpc_ems.py - the governor-aware MPC energy manager.

INTERPRETER.  The module under test is stdlib-only on its decision path, so the
bulk of this file runs under `.venv_hil`:

    .venv_hil/Scripts/python.exe -m pytest tools/test_mpc_ems.py -q

The equality checks against the numpy originals (gen_dp_ems_table's demand,
mask and pack steps) and against scipy's MAT reader are guarded with
`pytest.importorskip`, so they SKIP under `.venv_hil` and RUN under miniforge:

    C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_mpc_ems.py -q

⚠️ A SKIP IS NOT A PASS.  The numpy-guarded tests are the ONLY thing standing
between the scalar ports here and the numpy originals they were transcribed
from, which is the drift this repository has already recorded twice.  A change
to either side must be validated under miniforge, not under `.venv_hil` alone.

⚠️ THREE TESTS ARE WALL-CLOCK-BUDGET TESTS (2026-09-03 fix round, L5).  The
MPC's search width is bounded by a solve BUDGET IN MILLISECONDS, so a host that
is running something else explores fewer candidates and can commit a different
plan.  These three exercise that path and are the file's only known flakes
under concurrent load; each passes in isolation, and a failure is a scheduling
observation until it is reproduced ALONE:

    test_transition_roll_slices_and_completes
    test_the_search_width_reads_no_clock
    test_the_committed_plan_is_insensitive_to_the_projection

    <interpreter> -m pytest tools/test_mpc_ems.py -q -k "<name>"

They are NOT marked skip or xfail: each asserts a real invariant and must fail
loudly when the invariant breaks.  Do not widen their tolerances to absorb host
load -- rerun them alone instead.
"""
import math
import os
import json
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import charger_power as chg              # noqa: E402
import governor_model as gm              # noqa: E402
import hil_plant_sim as sim              # noqa: E402
import mpc_ems as M                      # noqa: E402

REPO = os.path.dirname(HERE)
TPM_PATH = os.path.join(REPO, "references", "EMS", "generated",
                        "TPM_dt1_hil.mat")
SCEN = "ems-soc-band"


def _meta():
    return sim.SCENARIOS[SCEN]


def _bound(**kw):
    s = M.MpcStrategy("mpc-det", **kw)
    s.bind_scenario(SCEN, _meta())
    return s


# ═════════════════════════════════════════════════════════════════════════════
# 1. The pinned literals.  These are the numbers the adjudication rules on, and
#    every one of them is RECOMPUTED from the code's own constants here rather
#    than transcribed, so a constant that moves fails the test instead of
#    silently repricing the controller.
# ═════════════════════════════════════════════════════════════════════════════
def test_proxy_and_over_read_literals():
    assert M.PROXY_GPS_PER_W == pytest.approx(2.0833333333333333e-05, rel=1e-15)
    assert M.PROXY_OVER_READ == pytest.approx(1.1811885267006539, rel=1e-12)
    # Both candidates independently measured 1.181.
    assert M.PROXY_OVER_READ == pytest.approx(1.181, abs=5e-4)


def test_terminal_price_modes():
    # metric = proxy_over_read / lambda, i.e. 1.181 x 2.439 (adjudication 2.4).
    assert M.terminal_price("metric") == pytest.approx(2.8809476, rel=1e-6)
    assert M.terminal_price("metric") == pytest.approx(
        M.PROXY_OVER_READ * (1.0 / 0.41), rel=1e-15)
    assert M.terminal_price("sdp-shadow") == pytest.approx(4.793012, rel=1e-6)
    assert M.terminal_price(3.0) == 3.0
    assert M.terminal_price("2.5") == 2.5
    with pytest.raises(ValueError):
        M.terminal_price("nonsense")
    with pytest.raises(ValueError):
        M.terminal_price(-1.0)


def test_lever_arithmetic():
    """Section 2.5 of both candidates, recomputed."""
    assert M.LEVER_SHARE_SOC_PER_G == pytest.approx(0.4504504505, rel=1e-9)
    assert M.LEVER_CHG_OLD_SOC_PER_G == pytest.approx(0.2089864159, rel=1e-9)
    assert M.LEVER_CHG_ETA_SOC_PER_G == pytest.approx(0.3963963964, rel=1e-9)
    assert M.SDP_V3_ADMISSION_SOC_PER_G == pytest.approx(0.3068192060, rel=1e-9)
    # THE CONSEQUENCE, asserted rather than left in prose: the eta-era charge
    # lever EXCEEDS sdp_policy_v3's admission threshold, so charging is admitted
    # at v3's own alpha in this era.
    assert M.LEVER_CHG_ETA_SOC_PER_G > M.SDP_V3_ADMISSION_SOC_PER_G


def test_oc_margins():
    assert M.I_FC_MAX_A == pytest.approx(1.19, rel=1e-12)
    assert M.I_BT_MAX_A == pytest.approx(2.55, rel=1e-12)


def test_governor_thresholds_come_from_the_firmware_model():
    assert M.GOV_ENTRY_A == pytest.approx(0.60)
    assert M.GOV_RELEASE_A == pytest.approx(0.55)
    assert M.GOV_MIN_LOAD_A == pytest.approx(0.075)
    # Property A's own arithmetic: the load filter keeps 5.3e-23 of its state
    # across a 1 s stage, which is what makes the precompute control-independent.
    alpha = gm.GOV_CONST["SHARE_GOV_FILT_ALPHA"]
    assert (1.0 - alpha) ** 1000 < 1e-20


def test_huber_shape():
    rho = 2.0
    d = M.TERMINAL_DELTA_SOC
    assert M.huber(0.0, rho) == 0.0
    # Continuous and C1 at the knee.
    assert M.huber(d, rho) == pytest.approx(rho * d / 2.0)
    assert M.huber(d * (1 + 1e-9), rho) == pytest.approx(M.huber(d, rho),
                                                         rel=1e-6)
    # Linear far out, with slope rho.
    assert (M.huber(0.02, rho) - M.huber(0.01, rho)) == pytest.approx(
        rho * 0.01, rel=1e-12)
    # Symmetric.
    assert M.huber(-0.004, rho) == M.huber(0.004, rho)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Scalar ports versus the numpy originals (miniforge only).
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def gen():
    pytest.importorskip("numpy")
    import gen_dp_ems_table as _gen
    return _gen


@pytest.mark.parametrize("eta_chg", [None, chg.ETA_CHG_DEFAULT])
def test_pack_steps_match_numpy_originals(gen, eta_chg):
    """Both charger eras, to 1e-12 relative."""
    cap_as = M.BATT_CAPACITY_AH * 3600.0
    for soc in (0.05, 0.12, 0.15, 0.30, 0.55, 0.60, 0.65, 0.70, 0.95):
        assert M.pack_ocv(soc) == pytest.approx(float(gen.pack_ocv(soc)),
                                                rel=1e-12)
        assert M.pack_rs(soc) == pytest.approx(float(gen.pack_rs(soc)),
                                               rel=1e-12)
        assert M.pack_charge_voltage(soc, 0.8) == pytest.approx(
            float(gen.pack_charge_voltage(soc, 0.8)), rel=1e-12)
        for p_dem in (2.0, 8.5, 13.7, 22.9):
            assert M.pack_current_from_bus_power(p_dem, soc) == pytest.approx(
                float(gen.pack_current_from_bus_power(p_dem, soc)), rel=1e-12)
            for share in (0.15, 0.5, 0.85):
                a = M._dp_step_discharge(soc, share, p_dem, 15.9, 0.1, cap_as)
                b = gen.step_discharge(soc, share, p_dem, 15.9, 0.1, cap_as)
                for x, y in zip(a, b):
                    assert x == pytest.approx(float(y), rel=1e-12, abs=1e-18)
            a = M._dp_step_charge(soc, p_dem, 15.9, 0.8, 0.1, cap_as, eta_chg)
            b = gen.step_charge(soc, p_dem, 15.9, 0.8, 0.1, cap_as, eta_chg)
            for x, y in zip(a, b):
                assert x == pytest.approx(float(y), rel=1e-12, abs=1e-18)


def test_the_drain_scenario_name_is_a_real_tuple():
    """L1 (2026-09-03). The name reads as a tuple, so it must BE one. It was a
    custom object implementing only `__contains__`/`__iter__`/`__len__`/
    `__eq__`, and every other tuple operation raised: indexing, `hash()`,
    `json.dumps()`, and `== None` (which raised instead of returning False, so
    an ordinary None-guard blew up). PEP 562 defers the simulator import
    exactly as far and returns the genuine article."""
    d = M.SOC_BAND_DRAIN_SCENARIOS
    assert type(d) is tuple
    assert d[0] and isinstance(d[0], str)          # indexable
    assert hash(d) == hash(tuple(d))               # hashable
    assert json.loads(json.dumps(d)) == list(d)    # JSON-serialisable
    assert (d == None) is False                    # noqa: E711 - the point
    assert d != ()
    assert "ems-soc-band" in d and len(d) == len(set(d))
    # ...and the deferral it exists for: a bad name still raises AttributeError
    with pytest.raises(AttributeError):
        M.NO_SUCH_MODULE_ATTRIBUTE


def test_drain_and_demand_match_numpy_originals(gen):
    """The whole preview chain, on the registered EMS scenarios."""
    import numpy as np
    # The scalar port's whitelist must agree with the generator's, or the two
    # models see different loads for the same scenario (the B2 defect).
    assert set(M.SOC_BAND_DRAIN_SCENARIOS) == set(gen.SOC_BAND_DRAIN_SCENARIOS)
    for scen in ("ems-soc-band", "ems-sdp", "ems-dp-replay"):
        meta = sim.SCENARIOS[scen]
        dt = M.PREVIEW_DT_S
        n = int(round(float(meta["duration_s"]) / dt)) + 1
        times = [k * dt for k in range(n)]
        got = M.build_demand(scen, meta, times, dt)
        want = gen.build_demand(scen, meta, np.array(times), dt)
        for gi, wi in zip(got, want):
            assert np.allclose(np.array(gi, dtype=float),
                               np.asarray(wi, dtype=float),
                               rtol=1e-12, atol=1e-15)
        # L11: the EXPLICIT-PRELOAD arm as well as the registry arm.  The
        # `aux_preload_a` override is the path a caller uses to model a
        # scenario at a preload other than its declared one, and it has its own
        # ramp arithmetic - which nothing exercised until this round.
        for preload in (None, 0.0, 0.45, 0.65):
            for t in (0.0, 3.0, 11.5, 40.0, 57.9):
                assert M.scenario_drain_a(scen, t, preload) == pytest.approx(
                    float(gen.scenario_drain_a(scen, t, preload)), rel=1e-12)
        # The mask, both eras.
        chg_a = sim.dp_chg_ceiling_a(meta)
        run_exit = float(sim.SOC_BAND_RUN_EXIT_S
                         if meta.get("ems_run_exit_s") is None
                         else meta["ems_run_exit_s"])
        # SEVEN elements since the 2026-09-02 regen round.
        _, _, p_dem, v_bus, _, cruise, i_regen = got
        # Pre-regen era on every one of these rig-drag scenarios: the credit
        # is the ABSENCE of the term, so the column is exactly zero.
        assert not any(i_regen)
        for eta in (None, chg.ETA_CHG_DEFAULT):
            vref = None if eta is None else M.pack_charge_voltage(0.7, chg_a)
            mine = M.charge_mask(times, p_dem, v_bus, cruise, chg_a, run_exit,
                                 eta, vref)
            theirs = gen.charge_mask(np.array(times), np.array(p_dem),
                                     np.array(v_bus), np.array(cruise),
                                     chg_a, run_exit, eta, vref)
            assert list(map(bool, mine)) == list(map(bool, theirs))


def test_mat_reader_matches_scipy(gen):
    """The stdlib MAT-file reader against scipy's, element for element."""
    loadmat = pytest.importorskip("scipy.io").loadmat
    import numpy as np
    mine = M.load_tpm(TPM_PATH)
    ref = loadmat(TPM_PATH)
    key = [k for k in ref if not k.startswith("__")]
    assert len(key) == 1
    theirs = np.asarray(ref[key[0]], dtype=float)
    assert np.allclose(np.array(mine), theirs, rtol=0.0, atol=0.0)


# ═════════════════════════════════════════════════════════════════════════════
# 3. The MAT reader's own properties (stdlib).
# ═════════════════════════════════════════════════════════════════════════════
def test_tpm_shape_and_stochasticity():
    tpm = M.load_tpm(TPM_PATH)
    assert len(tpm) == 25 and all(len(r) == 25 for r in tpm)
    for r in tpm:
        assert sum(r) == pytest.approx(1.0, abs=1e-12)
    nnz = sum(1 for r in tpm for x in r if x)
    assert nnz == 211                       # sidecar `results.nnz`
    # The sidecar's `diagonal_mass` is the OCCUPANCY-WEIGHTED self-transition
    # mass, not the unweighted mean of the diagonal - the two differ by 3x here,
    # and quoting the wrong one is how a near-persistence claim gets overstated.
    import json
    side = json.load(open(TPM_PATH + ".provenance.json", encoding="utf-8"))
    occ = side["results"]["row_occupancy"]
    tot = float(sum(occ))
    weighted = sum(occ[i] * tpm[i][i] for i in range(25)) / tot
    assert weighted == pytest.approx(side["results"]["diagonal_mass"], rel=1e-6)
    assert weighted == pytest.approx(0.762, abs=5e-3)


def test_mat_reader_refuses_a_non_mat_file(tmp_path):
    p = tmp_path / "not.mat"
    p.write_bytes(b"x" * 200)
    with pytest.raises(ValueError):
        M.load_mat_doubles(str(p))


# ═════════════════════════════════════════════════════════════════════════════
# 4. Property A: the precompute's mode classification versus a full roll.
# ═════════════════════════════════════════════════════════════════════════════
def _synthetic_preview(profile_a, n_stages=20, dt=M.PREVIEW_DT_S):
    """A preview whose source total follows `profile_a(t)`."""
    n_sub = int(round(M.DECISION_DT_S / dt))
    n = n_stages * n_sub
    times = [k * dt for k in range(n)]
    i_tot = [max(1e-3, profile_a(t)) for t in times]
    v_bus = [15.95 - 0.074 * i for i in i_tot]
    p_dem = [v_bus[k] * i_tot[k] for k in range(n)]
    return M.Preview(times=times, p_dem=p_dem, v_bus=v_bus, i_total=i_tot,
                     cruise=[True] * n, chg_ok=[False] * n, dt=dt)


def _roll_modes(prev, share, n_stages):
    """A full 1 kHz GovernorModel roll; returns the per-stage dominant mode."""
    g = gm.GovernorModel(dt_s=M.GOV_TICK_S, seed_r=0.5)
    n_sub = int(round(M.DECISION_DT_S / prev.dt))
    ticks_per_sub = int(round(prev.dt / M.GOV_TICK_S))
    out = []
    delivered = 0.5
    t = 0.0
    for j in range(n_stages):
        counts = {}
        for s in range(n_sub):
            k = j * n_sub + s
            i_tot = prev.i_total[k]
            for _ in range(ticks_per_sub):
                i_fc = delivered * i_tot
                o = g.step(share, i_fc, i_tot - i_fc, True, True, t)
                delivered = g.delivered_share(o.r_applied, i_tot, True, True)
                counts[o.mode] = counts.get(o.mode, 0) + 1
                t += M.GOV_TICK_S
        out.append(max(counts.items(), key=lambda kv: kv[1])[0])
    return out


def test_precompute_mode_classification_matches_a_full_roll():
    """The mode class is a function of the preview alone (Property A)."""
    import random
    rng = random.Random(20260901)
    matched = total = 0
    for trial in range(6):
        lo = rng.uniform(0.20, 0.50)
        hi = rng.uniform(0.80, 1.60)
        period = rng.uniform(6.0, 16.0)
        prof = (lambda t, lo=lo, hi=hi, p=period:
                lo + (hi - lo) * 0.5 * (1.0 + math.sin(2 * math.pi * t / p)))
        prev = _synthetic_preview(prof)
        for share in (0.25, 0.50, 0.75):
            pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_OPEN)
            rolled = _roll_modes(prev, share, 20)
            for j in range(20):
                # The precompute's dominant sub-sample class.
                counts = {}
                for m in pre.mode[j]:
                    counts[m] = counts.get(m, 0) + 1
                mine = max(counts.items(), key=lambda kv: kv[1])[0]
                theirs = rolled[j]
                closed_t = theirs == gm.MODE_CLOSED
                closed_m = mine == M.STAGE_CLOSED
                total += 1
                matched += int(closed_t == closed_m)
    # Opus measured 240/240 on its own synthetic set; the acceptance here is a
    # band, because a stage that straddles the hysteresis is genuinely
    # ambiguous and pinning 100 % would be pinning the random seed.
    assert matched / total >= 0.95, "mode classification %d/%d" % (matched, total)


# ═════════════════════════════════════════════════════════════════════════════
# 5. Property B: the closed-stage surrogate band (Gate 1).
# ═════════════════════════════════════════════════════════════════════════════
def test_closed_stage_surrogate_band():
    """Mean absolute delivered-share error on CLOSED stages, versus a roll.

    Acceptance 5e-3 (candidate_opus section 2.3 / section 5.1, PROVISIONAL until
    a walk measures it; the closed-stage measurement there was mean 8.2e-4)."""
    import random
    rng = random.Random(4242)
    errs = []
    for trial in range(5):
        base = rng.uniform(0.9, 1.5)
        amp = rng.uniform(0.05, 0.30)
        prof = (lambda t, b=base, a=amp: b + a * math.sin(2 * math.pi * t / 9.0))
        prev = _synthetic_preview(prof)
        pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
        for share in (0.25, 0.4167, 0.5, 0.5833, 0.75):
            g = gm.GovernorModel(dt_s=M.GOV_TICK_S, seed_r=0.5)
            g.state.closed_loop_mode = True
            g.state.closed_loop_run = True
            g.state.filt_total = prev.i_total[0]
            n_sub = int(round(M.DECISION_DT_S / prev.dt))
            ticks_per_sub = int(round(prev.dt / M.GOV_TICK_S))
            delivered = 0.5
            t = 0.0
            for j in range(20):
                acc = 0.0
                nn = 0
                closed = True
                for s in range(n_sub):
                    k = j * n_sub + s
                    i_tot = prev.i_total[k]
                    closed = closed and pre.mode[j][s] == M.STAGE_CLOSED
                    for _ in range(ticks_per_sub):
                        i_fc = delivered * i_tot
                        o = g.step(share, i_fc, i_tot - i_fc, True, True, t)
                        delivered = g.delivered_share(o.r_applied, i_tot,
                                                      True, True)
                        acc += delivered
                        nn += 1
                        t += M.GOV_TICK_S
                if not closed or j == 0:
                    continue          # only closed stages, and not the seed one
                rolled = acc / nn
                sur = 0.0
                for s in range(n_sub):
                    lo = pre.lo[j][s]
                    sur += min(max(share, lo), 1.0 - lo)
                sur /= n_sub
                errs.append(abs(sur - rolled))
    assert errs, "no closed stages were scored - the fixture is vacuous"
    mean = sum(errs) / len(errs)
    assert mean <= 5e-3, "closed-stage surrogate mean error %.6f" % mean


# ═════════════════════════════════════════════════════════════════════════════
# 6. The transition rolls.
# ═════════════════════════════════════════════════════════════════════════════
def test_transition_roll_reproduces_a_full_roll():
    """RollJob's r_hold equals a hand-written full roll of the same stage."""
    prof = lambda t: 1.2 if t < 5.0 else 0.35      # a downward 0.55 A crossing
    prev = _synthetic_preview(prof, n_stages=10)
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    assert any(pre.transition), "the fixture carries no mode transition"
    job = M.RollJob(pre, [0.25, 0.5, 0.75])
    job.run_all()
    assert job.table, "the roll produced no entries"
    # The table is keyed on the ABSOLUTE stage index on the DECISION grid, so
    # a table still in use one decision later points at the same stage even
    # though the decisions do not land on the preview grid (they fire at 1.02 s,
    # so the preview index advances by 9, 10 or 11 samples).
    assert set(job.table) == {(pre.stage_key[j], si) for j, si in job.items}
    for j, si in job.items:
        r = job.table[(pre.stage_key[j], si)]
        assert 0.0 <= r <= 1.0
        # Recompute the same roll independently.
        share = job.ladder[si]
        lo0 = pre.lo[j][0]
        seed = min(max(share, lo0), 1.0 - lo0)
        g = gm.GovernorModel(dt_s=M.GOV_TICK_S, seed_r=seed)
        g.state.filt_total = pre.i_tot[j][0]
        if pre.mode[j][0] == M.STAGE_CLOSED:
            g.state.closed_loop_mode = True
        # `closed_loop_run` is STICKY: a closed-loop run sets it and only a
        # setpoint change clears it, and this roll holds the command. Seeding it
        # from the stage's opening mode alone predicts a feedforward slew the
        # firmware does not perform.
        if pre.run_entry[j] or pre.mode[j][0] == M.STAGE_CLOSED:
            g.state.closed_loop_run = True
            g.state.acted_sp = share
        n_sub = len(pre.i_tot[j])
        ticks = int(round(M.DECISION_DT_S / M.GOV_TICK_S))
        per = max(1, ticks // n_sub)
        delivered = seed
        for tk in range(ticks):
            i_tot = pre.i_tot[j][min(n_sub - 1, tk // per)]
            i_fc = delivered * i_tot
            o = g.step(share, i_fc, i_tot - i_fc, True, True, tk * M.GOV_TICK_S)
            delivered = g.delivered_share(o.r_applied, i_tot, True, True)
        assert r == pytest.approx(g.state.r_prev, rel=0.0, abs=0.0)


def test_transition_roll_slices_and_completes():
    """The slicing mechanism completes inside 50 callbacks (adjudication 2.2).

    WALL-CLOCK-BUDGET TEST -- run it alone before believing a failure (see the
    module docstring; the other two are `test_the_search_width_reads_no_clock`
    and `test_the_committed_plan_is_insensitive_to_the_projection`)."""
    # Four transitions in the horizon - RollJob.MAX_TRANSITIONS, the
    # adjudication's own bound on the slice.
    prof = lambda t: 1.2 if (t < 4.0 or 8.0 <= t < 12.0 or t >= 16.0) else 0.35
    prev = _synthetic_preview(prof, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    ladder = [0.25 + i * 0.5 / 6.0 for i in range(7)]
    job = M.RollJob(pre, ladder)
    n_items = len(job.items)
    assert n_items >= 7, "the fixture carries too few transitions to slice"
    # THE BOUND IS THE JOB'S OWN WORK, not a transcribed callback count.  The
    # adjudication's "inside 50 callbacks" was measured on one interpreter and
    # this fixture needs 36 of them under CPython 3.14 and 56 under 3.13, so a
    # literal 50 fails a correct scheduler on the slower one.  What the slicing
    # must guarantee is that the work is spread at the budget and nothing is
    # lost to the slicing, and that is what is asserted: the call count is the
    # measured work divided by the budget, plus a call of slack.
    twin = M.RollJob(pre, ladder)
    t0 = time.perf_counter()
    twin.run_all()
    work_ms = (time.perf_counter() - t0) * 1e3
    calls = 0
    while not job.done and calls < 500:
        job.advance(M.ROLL_BUDGET_MS_DEFAULT * 1e-3)
        calls += 1
    assert job.done, "the roll table did not complete"
    assert len(job.table) == n_items
    assert job.table == twin.table, "slicing changed the table"
    allowed = math.ceil(work_ms / M.ROLL_BUDGET_MS_DEFAULT) + 2
    assert calls <= max(allowed, 4), (calls, allowed, work_ms)
    # And it does complete inside a bounded number of 50 Hz callbacks on an
    # interpreter that meets the design's measured per-roll cost.
    #
    # ⚠️ THE BOUND WAS RAISED 60 -> 75 IN THE fw v26 TOOLS ROUND AND IS NOW 70
    # (re-derived 2026-09-02, after the L6 constant hoist). It is a WALL-CLOCK
    # assertion on a shared machine, so the number is only worth what its
    # measurement is, and both are recorded here.
    #
    # WHAT THE ROUND ORIGINALLY MEASURED. Adding the fw v26 current-ceiling
    # clamp to `GovernorModel.step()` cost about 7 % per tick, which pushed a
    # fixture already at ~54 callbacks past the 60 bound and made it FLAKY: it
    # passed alone and failed inside a full-suite run. The bound went to 75.
    #
    # WHAT THE HOIST RECOVERED. `ceiling_bounded_share()` and the clamp's inert
    # early-out now read module-level constants instead of `GOV_CONST` dict
    # entries, and the inert condition is inlined at both `step()` call sites.
    # RE-MEASURED over 50 000 governor ticks, best of seven: 0.2312 s with the
    # clamp live against 0.2323 s with the ceilings pinned out of reach -- a
    # DELTA OF -0.5 %, i.e. inside this machine's noise. The clamp no longer
    # costs a measurable amount per tick.
    #
    # WHY NOT BACK TO 60. The fixture itself measures 58.2 to 58.9 callbacks
    # (116.4 to 117.7 ms at the 2.0 ms budget, best of seven, idle machine), so
    # 60 leaves 1.9 % of margin and would be flaky again for reasons that have
    # nothing to do with fw v26. 70 clears the measurement by 19 % and still
    # fails on any regression above that. What this must NOT become is a number
    # quietly raised each time the model grows; the next move needs its own
    # measurement recorded here, as both of these are.
    assert work_ms / M.ROLL_BUDGET_MS_DEFAULT < 70.0, work_ms


def test_zero_budget_roll_makes_progress_but_does_not_raise():
    prof = lambda t: 1.2 if t < 5.0 else 0.35
    prev = _synthetic_preview(prof, n_stages=10)
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    job = M.RollJob(pre, [0.25, 0.75])
    job.advance(0.0)
    # ONE CHUNK per call at worst (M1): the budget is checked after a chunk of
    # RollJob.TICK_CHUNK governor ticks, so the job always advances and can
    # never livelock - but it no longer completes a whole 1000-tick item under a
    # zero budget, which is the point of the chunking.
    assert job.chunks == 1
    assert job.cursor == 0 and job._cur is not None
    assert job._cur["tk"] == M.RollJob.TICK_CHUNK
    # And it still finishes: repeated zero-budget calls complete the table.
    guard = 0
    while not job.done and guard < 100000:
        job.advance(0.0)
        guard += 1
    assert job.done and len(job.table) == len(job.items)


# ═════════════════════════════════════════════════════════════════════════════
# 7. Constraints.
# ═════════════════════════════════════════════════════════════════════════════
def test_no_candidate_leaves_the_share_band():
    for band in (M.SHARE_BAND_DP, M.SHARE_BAND_SDP):
        p = M.Planner(share_band=band)
        assert p.ladder[0] == pytest.approx(band[0])
        assert p.ladder[-1] == pytest.approx(band[1])
        assert all(band[0] - 1e-15 <= s <= band[1] + 1e-15 for s in p.ladder)
        # ⚠️ THE BAND IS THE CUT BAND NOW (2026-09-02).  This used to assert
        # that the DP band stopped SHORT of the rails, so the setpoint latch
        # could never fire.  The standing operator rule gives every EMS
        # strategy the full [0.15, 0.85] range, so the ladder ends ON the
        # rails -- and that is safe for the reason the widening rests on:
        # updateShareSetpointCutoff() compares STRICTLY, so the rails are IN
        # band, and the firmware carries SHARE_CUTOFF_HYST beyond them on top.
        # What must still hold is that no candidate goes OUTSIDE.
        assert p.ladder[0] >= gm.GOV_CONST["DROOP_R_MIN"]
        assert p.ladder[-1] <= gm.GOV_CONST["DROOP_R_MAX"]
        # ... and the ladder edges are the rails EXACTLY, so the emitted
        # setpoint is the same float the firmware compares.
        assert p.ladder[0] == gm.GOV_CONST["DROOP_R_MIN"]
        assert p.ladder[-1] == gm.GOV_CONST["DROOP_R_MAX"]


def test_commanded_share_stays_in_band_over_a_run():
    s = _bound()
    prev = s.preview
    soc = 0.70
    t = 0.0
    while t < 61.0:
        k = prev.index(t)
        out = s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
                    "I_fc": 0.5 * prev.i_total[k],
                    "I_batt": 0.5 * prev.i_total[k],
                    "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
        assert M.SHARE_BAND_DP[0] - 1e-12 <= out["power_share_setpoint"] \
            <= M.SHARE_BAND_DP[1] + 1e-12
        soc -= 1e-5
        t += 0.02


def test_overcurrent_infeasibility_is_enforced():
    """A stage whose FC current would exceed 1.19 A is refused, not clipped."""
    prof = lambda t: 6.0                      # 6 A source total everywhere
    prev = _synthetic_preview(prof, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    p = M.Planner()
    d, pfc, pbt, ok, viol = p.delivery_table(pre, {}, 0.5, [False] * 20)
    for j in range(20):
        for si, share in enumerate(p.ladder):
            i_fc = d[j][si] * pre.i_tot_mean[j]
            if i_fc > M.I_FC_MAX_A + 1e-12:
                assert not ok[j][si]
    # And the solver must not return an infeasible plan silently: with EVERY
    # ladder point infeasible the decision is flagged.
    dec = p.solve(0.6, 0.6, pre, {}, 0.5, [[False] * 20])
    assert not dec.feasible
    # L5: the fallback is the LEAST-VIOLATING ladder point, not the bottom rail.
    worst = [max(viol[j][si] for j in range(20)) for si in range(len(p.ladder))]
    assert dec.share == pytest.approx(
        p.ladder[min(range(len(p.ladder)), key=lambda i: (worst[i], i))])
    assert dec.worst_violation_a == pytest.approx(min(worst))


def test_charge_is_never_commanded_outside_the_mask():
    s = _bound()
    prev = s.preview
    soc = 0.70
    t = 0.0
    while t < 61.0:
        k = prev.index(t)
        out = s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
                    "I_fc": 0.5 * prev.i_total[k],
                    "I_batt": 0.5 * prev.i_total[k],
                    "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
        if out["charge_goal"] > 0.0:
            # A latch may hold the intent past a mask edge for the dwell, which
            # is the SDP's own semantics; the OPENING must be admitted.
            assert s.latch.hold_until is not None
        soc -= 2e-5
        t += 0.02


def test_a_regen_window_does_not_arm_the_fc_dwell():
    """THE REGEN GUARD ON THE 8 s FC DWELL (M2, 2026-09-02).

    `SdpStrategy.decide()` and `SocBandStrategy.__call__()` both refuse to arm
    the minimum-dwell latch on a tick the regen manager has claimed, and the MPC
    did not.  The dwell is a HOST construct governing the FC-PATH windows;
    inside a regen window the firmware's `regenActive` branch owns the charger
    and the FC path is SHUT, so arming there records a window that never existed
    and pins the intent high for 8 s after the braking ends.

    ⚠️ THE CHARGE DECISION IS FORCED, and deliberately.  On every registered
    stimulus this controller declines to charge on its own economics, so a
    black-box drive never reaches the `goal > 0.0` branch the guard lives on and
    would assert nothing.  Forcing the planner's decision is the only way to
    exercise it; everything downstream of `solve()` -- the latch, the guard, the
    emitted goal -- is the shipped code.  The two runs differ ONLY in
    `regen_commanded`."""
    def _run(regen_commanded):
        s = _bound()
        real = s.planner.solve

        def _always_charge(*a, **k):
            dec = real(*a, **k)
            dec.charge = True
            return dec

        s.planner.solve = _always_charge
        prev = s.preview
        k0 = prev.index(20.0)
        fb = {"t": 20.0, "soc": 0.66, "V_bus": prev.v_bus[k0],
              "I_fc": 0.5 * prev.i_total[k0],
              "I_batt": 0.5 * prev.i_total[k0],
              "v_profile": sim.piecewise(_meta()["ems_v_profile"], 20.0),
              "regen_commanded": regen_commanded}
        out = s(20.0, fb)
        return out["charge_goal"], s.latch.hold_until

    # The forcing works and the branch is reached: without the flag the leg
    # emits the intent AND arms the dwell.  That is what makes the assertion
    # below a statement about the guard rather than about a dead branch.
    goal_off, hold_off = _run(False)
    assert goal_off > 0.0
    assert hold_off is not None

    # With the tick claimed by the manager, the intent still goes out -- the
    # firmware's regen branch is what consumes it -- but NO FC dwell is armed.
    goal_on, hold_on = _run(True)
    assert goal_on > 0.0
    assert hold_on is None


def test_planner_refuses_a_band_that_does_not_span_the_blocks():
    with pytest.raises(ValueError):
        M.Planner(horizon=20, blocks=(2, 6, 8))
    with pytest.raises(ValueError):
        M.Planner(share_levels=1)


def test_convex_h2_map_is_refused_unless_supplied():
    with pytest.raises(ValueError):
        M.Planner(h2_map="convex")
    p = M.Planner(h2_map="convex",
                  h2_convex={"a0": 1.0e-5, "p_peak": 40.0, "eta_peak": 0.5})
    # a0 at zero power, and monotone upward.
    assert p.h2_rate_gps(0.0) == 0.0
    assert p.h2_rate_gps(20.0) > p.h2_rate_gps(10.0) > 0.0


# ═════════════════════════════════════════════════════════════════════════════
# 8. The dwell latch versus SdpStrategy's own.
# ═════════════════════════════════════════════════════════════════════════════
def _script_both(events, arm_at=0.0, v_ref=1.5):
    """Drive the MPC latch and SdpStrategy's through one scripted sequence."""
    mine = M.ChargeLatch()
    mine.arm(arm_at, v_ref)
    theirs = sim.SdpStrategy("sdp-v3", sim.SDP_POLICY_FILE_V3)
    theirs.chg_hold_until = arm_at + sim.SDP_CHG_MIN_DWELL_S
    theirs.chg_hold_v_ref = v_ref
    out = []
    for t, fb in events:
        out.append((mine.status(t, fb), theirs.charge_hold_status(t, fb)))
    return out


def test_dwell_latch_matches_sdp_semantics():
    v = {"v_profile": 1.5}
    # active -> active -> expired
    for a, b in _script_both([(1.0, v), (5.0, v), (8.5, v), (9.0, v)]):
        assert a == b
    # fault drop, tested BEFORE expiry
    faulted = {"v_profile": 1.5, "fault_flags": sim.SDP_CHG_ABORT_FAULT_MASK}
    for a, b in _script_both([(2.0, v), (8.5, faulted), (9.0, v)]):
        assert a == b
    # cruise exit
    off = {"v_profile": 1.5 + 2 * sim.SDP_CHG_CRUISE_DELTA_MPS}
    for a, b in _script_both([(2.0, v), (3.0, off), (4.0, v)]):
        assert a == b
    # no latch at all
    assert M.ChargeLatch().status(1.0, v) is None


def test_dwell_latch_counters():
    lat = M.ChargeLatch()
    lat.arm(0.0, 1.5)
    assert lat.holds == 1
    assert lat.stages_remaining(0.0) == int(sim.SDP_CHG_MIN_DWELL_S)
    assert lat.stages_remaining(7.5) == 1
    assert lat.status(9.0, {"v_profile": 1.5}) == "expired"
    assert lat.drops == 0                # an expiry is not a drop
    lat.arm(10.0, 1.5)
    lat.status(11.0, {"v_profile": 5.0})
    assert lat.drops == 1


# ═════════════════════════════════════════════════════════════════════════════
# 9. Warm start and the anytime path.
# ═════════════════════════════════════════════════════════════════════════════
def test_warm_start_orders_the_incumbent_first():
    p = M.Planner()
    p.incumbent = (0, 6, 3)
    order = p._enumeration_order(range(len(p.ladder)), 3)
    assert order[0] == (0, 6, 3)
    # And outward in ladder distance from it.
    d = [sum(abs(c[i] - p.incumbent[i]) for i in range(3)) for c in order]
    assert d == sorted(d)


def test_zero_budget_returns_a_feasible_incumbent_and_does_not_raise():
    prev = _synthetic_preview(lambda t: 1.2, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    p = M.Planner(budget_ms=0.0)
    dec = p.solve(0.6, 0.6, pre, {}, 0.5, [[False] * 20])
    assert dec.budget_hit
    assert dec.candidates >= 1
    assert M.SHARE_BAND_DP[0] <= dec.share <= M.SHARE_BAND_DP[1]
    assert math.isfinite(dec.cost)


def test_ties_resolve_to_the_smaller_share_and_no_charge():
    """SDP D8, asserted on a degenerate problem where every share ties."""
    prev = _synthetic_preview(lambda t: 1.2, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    # A zero terminal price and a zero-cost hydrogen map make every candidate
    # cost exactly 0, so only the tie rule can decide.
    p = M.Planner(terminal_mode=0.0)
    p.h2_rate_gps = lambda w: 0.0
    dec = p.solve(0.6, 0.6, pre, {}, 0.5, [[False] * 20, [True] * 20])
    # Every candidate costs exactly 0, so only the tie rule can decide, and it
    # must decide against charging: the no-charge option is enumerated first and
    # a STRICT improvement is required to displace it.
    assert dec.cost == 0.0
    assert dec.charge is False
    assert dec.plan_charge == [False] * 20


def test_higher_terminal_price_never_lowers_the_first_move_share():
    """Monotonicity: pricing SoC higher cannot make the plan discharge harder."""
    prev = _synthetic_preview(lambda t: 1.2, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    last = -1.0
    for rho in (0.0, 1.0, 2.881, 4.793, 20.0):
        p = M.Planner(terminal_mode=rho, budget_ms=1e6)
        dec = p.solve(0.60, 0.60, pre, {}, 0.5, [[False] * 20])
        assert dec.share >= last - 1e-12
        last = dec.share


# ═════════════════════════════════════════════════════════════════════════════
# 10. The strategy surface.
# ═════════════════════════════════════════════════════════════════════════════
def test_strategy_surface_matches_sdp_strategy():
    s = M.MpcStrategy("mpc-det")
    for attr in ("bind_scenario", "reset", "__call__", "summary_line"):
        assert callable(getattr(s, attr))
    assert hasattr(s, "provenance")
    assert s.summary_line() is None          # never ran


def test_call_without_bind_refuses():
    s = M.MpcStrategy("mpc-det")
    with pytest.raises(RuntimeError):
        s(3.0, {"t": 3.0, "soc": 0.7})


def test_command_keys_and_run_window():
    s = _bound()
    out = s(1.0, {"t": 1.0, "soc": 0.7, "V_bus": 15.9, "I_fc": 0.3,
                  "I_batt": 0.3, "v_profile": 0.0})
    assert set(out) == {"mode_cmd", "power_share_setpoint", "v_setpoint",
                        "charge_goal"}
    assert out["mode_cmd"] == sim.MODE_SAFE     # before EMS_RUN_ENTRY_S
    assert out["charge_goal"] == 0.0
    out = s(10.0, {"t": 10.0, "soc": 0.7, "V_bus": 15.9, "I_fc": 0.6,
                   "I_batt": 0.6, "v_profile": 1.5})
    assert out["mode_cmd"] == sim.MODE_HYBRID


def test_missing_soc_degrades_to_the_nominal_split():
    s = _bound()
    out = s(10.0, {"t": 10.0, "V_bus": 15.9, "I_fc": 0.6, "I_batt": 0.6,
                   "v_profile": 1.5})
    assert out["power_share_setpoint"] == pytest.approx(
        sim.SOC_BAND_SHARE_NOMINAL)
    assert out["charge_goal"] == 0.0


def test_rewind_resets_the_run_state():
    s = _bound()
    s(10.0, {"t": 10.0, "soc": 0.7, "V_bus": 15.9, "I_fc": 0.6, "I_batt": 0.6,
             "v_profile": 1.5})
    assert s.decisions >= 1
    ref_before = s.soc_ref
    s(1.0, {"t": 1.0, "soc": 0.8, "V_bus": 15.9, "I_fc": 0.3, "I_batt": 0.3,
            "v_profile": 0.0})
    # A rewind is a NEW run: the decision counter restarts and the captured
    # state-of-charge reference is re-taken from the new run's first sample, so
    # a second run in one process cannot inherit the first run's reference.
    assert s.decisions == 1
    assert s.soc_ref == pytest.approx(0.8)
    assert s.soc_ref != ref_before


def test_provenance_block():
    s = _bound()
    p = s.provenance
    for k in ("variant", "horizon_n", "decision_dt_s", "block_lengths",
              "share_levels", "terminal", "terminal_price_mode", "h2_model",
              "eta_fc_proxy", "eta_chg", "budget_ms", "soc_ref_offset",
              "governor_commit", "preview_source", "ladder", "share_band"):
        assert k in p, k
    assert p["preview_source"] == "scenario_profile"
    assert p["terminal"]["shape"] == "huber"
    assert p["terminal"]["delta_soc"] == pytest.approx(0.0015)
    assert p["eta_chg"] == pytest.approx(chg.ETA_CHG_DEFAULT)


def test_sto_provenance_and_forecast():
    s = M.MpcStrategy("mpc-sto", variant="sto", tpm_path=TPM_PATH)
    s.bind_scenario(SCEN, _meta())
    assert s.provenance["preview_source"] == "tpm"
    assert s.provenance["tpm_n_bins"] == 25
    assert s.provenance["oc_quantile"] == pytest.approx(0.90)
    means, quants = s._tpm_forecast(10)
    assert len(means) == s.horizon and len(quants) == s.horizon
    lo, hi = s.tpm_map_w
    assert all(lo <= m <= hi for m in means)
    # The quantile bound is never below the mean's bin centre by construction of
    # a 90 % upper quantile on a non-negative axis - the point of tightening it.
    assert quants[0] >= 0.0
    # Near-persistence: the 0.762 diagonal makes a one-step forecast sit close
    # to the current bin's own centre.  Asserted so a matrix swap that broke it
    # would be visible (candidate_opus section 4.3).
    centre = lo + (hi - lo) * 10.5 / 25.0
    assert abs(means[0] - centre) < 0.20 * (hi - lo)


def test_bin_clamp_counters():
    s = M.MpcStrategy("mpc-sto", variant="sto", tpm_path=TPM_PATH)
    s.bind_scenario(SCEN, _meta())
    s._bin_of(-5.0)
    s._bin_of(1e6)
    assert s.clamped_bin_low == 1 and s.clamped_bin_high == 1


def test_shadow_governor_corrects_from_mdac_when_supplied():
    sh = M.ShadowGovernor()
    code_fc = gm._mdac_code(0.30)
    code_bt = gm._mdac_code(0.70)
    sh.observe({"mdac_fc": code_fc, "mdac_bt": code_bt})
    assert sh.mdac_corrections == 1
    assert sh.r == pytest.approx(gm.r_from_codes(code_fc, code_bt))
    # And from the measured split when the words are absent.
    sh.observe({"I_fc": 0.9, "I_batt": 0.3})
    assert sh.current_corrections == 1
    assert sh.r == pytest.approx(0.75, rel=1e-9)
    # Below the closed-loop entry the split does not identify the ratio, so the
    # model keeps its own state.
    before = sh.r
    sh.observe({"I_fc": 0.1, "I_batt": 0.1})
    assert sh.r == before


def test_shadow_governor_ticks_at_1khz():
    sh = M.ShadowGovernor()
    fb = {"I_fc": 0.6, "I_batt": 0.6}
    sh.tick_to(1.00, 0.5, fb)
    sh.tick_to(1.02, 0.5, fb)
    assert sh.ticks == 20                # 20 ms at 1 kHz


# ═════════════════════════════════════════════════════════════════════════════
# 11. Timing.
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("variant", ["det", "sto"])
def test_decision_timing_over_a_61s_loop(variant):
    """Median decision < 20 ms and maximum < 50 ms (adjudication 2.2).

    Wall-clock on the host running the suite.  The bands are generous against
    the measured figures precisely so a loaded CI host does not fail a correct
    controller; a REGRESSION of an order of magnitude still fails."""
    kw = {"tpm_path": TPM_PATH} if variant == "sto" else {}
    s = M.MpcStrategy("mpc-" + variant, variant=variant, **kw)
    s.bind_scenario(SCEN, _meta())
    prev = s.preview
    soc = 0.70
    t = 0.0
    while t < 61.0:
        k = prev.index(t)
        s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
              "I_fc": 0.5 * prev.i_total[k], "I_batt": 0.5 * prev.i_total[k],
              "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
        soc -= 1e-5
        t += 0.02
    tm = s.timing()
    assert tm["decisions"] >= 55
    assert tm["solve_ms_median"] < 20.0, tm
    assert tm["solve_ms_max"] < 50.0, tm
    # The hard budget is honoured: no solve may run materially past it.  The
    # multiple is 3 rather than 2 because on a loaded host the check that ENDS a
    # solve can be preceded by a delivery-table build, and a 2x band flakes
    # without a defect to show for it (L12).
    # The budget is per-decision since 2026-09-02, so the bound is the LARGEST
    # budget any decision was given, not a constant of the configuration.
    assert tm["solve_ms_max"] <= tm["budget_ms_max"] * 3.0, tm


def test_timing_reports_the_candidate_maximum():
    """Campaign C item 1: enumeration GROWTH is what the cap and the budget are
    spent on, and last/fewest could not show it. `candidates_max` is reported
    beside them, in timing() (hence in the sidecar's config.mpc) and in the
    summary line."""
    s = _bound()
    assert s.timing()["candidates_max"] is None       # before any decision
    prev = s.preview
    soc, t = 0.70, 0.0
    while t < 20.0:
        k = prev.index(t)
        s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
              "I_fc": 0.5 * prev.i_total[k], "I_batt": 0.5 * prev.i_total[k],
              "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
        soc -= 1e-5
        t += 0.02
    tm = s.timing()
    assert tm["candidates_max"] is not None
    assert tm["candidates_max"] >= tm["candidates_last"]
    assert tm["candidates_max"] >= tm["candidates_min"]
    assert "most %d" % tm["candidates_max"] in s.summary_line()


def test_summary_line_reports_the_diagnostics():
    s = _bound()
    prev = s.preview
    soc, t = 0.70, 0.0
    while t < 20.0:
        k = prev.index(t)
        s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
              "I_fc": 0.5 * prev.i_total[k], "I_batt": 0.5 * prev.i_total[k],
              "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
        soc -= 1e-5
        t += 0.02
    line = s.summary_line()
    assert line and line.startswith("[hil] mpc-det:")
    for token in ("decisions", "expired on", "ladder", "points min/median/max", "share prediction error",
                  "shadow governor", "terminal price", "PREVIEW, NOT CAUSAL"):
        assert token in line
    assert s.share_pred is not None


def test_share_pred_err_is_measured():
    s = _bound()
    prev = s.preview
    soc, t = 0.70, 0.0
    while t < 30.0:
        k = prev.index(t)
        s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
              "I_fc": 0.6 * prev.i_total[k], "I_batt": 0.4 * prev.i_total[k],
              "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
        soc -= 1e-5
        t += 0.02
    assert s.share_pred_err is not None
    assert 0.0 <= s.share_pred_err <= 1.0
    assert s.share_pred_err_max >= s.share_pred_err - 1e-12


# ═════════════════════════════════════════════════════════════════════════════
# 13. The review round of 2026-09-02.  Every test below is a CONSUMPTION test:
#     it asserts that a term is actually read on the decision path, not merely
#     that it exists.  The five mutations the reviewer found surviving the
#     original suite (drop the minority clip, drop the charger's bus power from
#     the charge stage cost, flip the charge state-of-charge sign, never consult
#     r_hold, zero the terminal cost) are each covered here.
# ═════════════════════════════════════════════════════════════════════════════
class _Args:
    """The subset of `main()`'s argparse namespace the binder hook passes."""

    def __init__(self, capacity_ah=None):
        self.capacity_ah = capacity_ah


def test_bind_scenario_signature_matches_the_hook_contract():
    """H3: `main()` calls the binder BY NAME with its trailing arguments.

    ⚠️ FIVE, not two, since the 2026-09-02 ftp75c round: `droop_mode` and
    `asymmetry_mode` joined the contract in the earlier fix round so the
    demand-model era could be resolved from the RUN rather than taken blind
    from the scenario key (fix M1), and `drag_mode` joined for the same reason
    again -- `--drag` OVERRIDES a scenario's own `drag` key, so a binder handed
    only the meta would resolve the wrong road-load era. Every implementation
    must accept all five or a campaign dies at bind time with a TypeError.

    ALL FOUR BINDERS are compared, not just the SDP one: the DP and soc-band
    binders take the same trailing arguments from the same call site, and the
    soc-band binder is the newest of them (its per-scenario charge thresholds
    arrive through this hook).
    """
    import inspect
    want = ["self", "scenario", "meta", "electrical_mode",
            "args", "droop_mode", "asymmetry_mode", "drag_mode"]
    for cls in (M.MpcStrategy, sim.SdpStrategy, sim.DpReplayStrategy,
                sim.SocBandStrategy):
        assert list(inspect.signature(cls.bind_scenario).parameters) == want,             cls.__name__
    # And the call `main()` actually makes must not raise.
    s = M.MpcStrategy("mpc-det")
    s.bind_scenario(SCEN, _meta(), electrical_mode="hifi", args=_Args(),
                    droop_mode="design", asymmetry_mode="measured",
                    drag_mode=None)
    assert s.electrical_mode == "hifi"


def test_bind_scenario_takes_the_run_capacity_and_the_scenario_offset():
    """H3: the pack the run integrates, and the scenario's SoC-axis placement."""
    s = M.MpcStrategy("mpc-det")
    s.bind_scenario(SCEN, _meta(), args=_Args(capacity_ah=2.5))
    assert s.cap_as == pytest.approx(2.5 * 3600.0)
    assert s.planner.cap_as == pytest.approx(2.5 * 3600.0)
    assert s.provenance["capacity_ah"] == pytest.approx(2.5)
    # A run without the flag gets the module default, unchanged.
    d = M.MpcStrategy("mpc-det")
    d.bind_scenario(SCEN, _meta(), args=_Args())
    assert d.planner.cap_as == pytest.approx(M.BATT_CAPACITY_AH * 3600.0)
    # The scenario's own placement on the SoC axis, read AFTER reset().
    meta = dict(_meta())
    meta["mpc_soc_ref_offset"] = 0.013
    o = M.MpcStrategy("mpc-det")
    o.bind_scenario(SCEN, meta)
    assert o.soc_ref_offset == pytest.approx(0.013)
    o(0.0, {"t": 0.0, "soc": 0.70, "V_bus": 15.9, "I_fc": 0.3, "I_batt": 0.3})
    assert o.soc_ref == pytest.approx(0.70 - 0.013)


def test_the_roll_slice_runs_at_50_hz_not_at_1_hz():
    """H1: `advance()` belongs to __call__, so the table completes in a second."""
    s = _bound()
    prev = s.preview
    soc, t = 0.70, 0.0
    slices = {"n": 0}
    orig = M.RollJob.advance

    def counted(self, budget_s):
        slices["n"] += 1
        return orig(self, budget_s)

    M.RollJob.advance = counted
    try:
        while t < 20.0:
            k = prev.index(t)
            s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
                  "I_fc": 0.5 * prev.i_total[k],
                  "I_batt": 0.5 * prev.i_total[k],
                  "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
            soc -= 1e-5
            t += 0.02
    finally:
        M.RollJob.advance = orig
    # Many slices per decision, not one - the defect was exactly one.
    assert slices["n"] > 5 * s.decisions, (slices["n"], s.decisions)
    assert s.r_hold, "the roll table never completed"


def test_an_empty_roll_job_does_not_wipe_the_standing_table():
    """H2: publication is a MERGE, and a job with no items is a no-op."""
    s = _bound()
    s.r_hold = {(3, 0): 0.4242}

    class _Empty:
        table = {}
        handoff = {}
        stage_key = [3, 4, 5]
        dropped_transitions = 0

    s._publish_roll(_Empty())
    assert s.r_hold == {(3, 0): 0.4242}
    assert s.rolls_empty == 1
    assert s.rolls_published == 0

    class _Job:
        table = {(5, 1): 0.31}
        handoff = {(5, 1): False}
        stage_key = [3, 4, 5]
        dropped_transitions = 2

    s.r_hold[(1, 0)] = 0.9        # a stage that has receded past the horizon
    s._publish_roll(_Job())
    assert (5, 1) in s.r_hold and s.r_hold[(5, 1)] == pytest.approx(0.31)
    assert (3, 0) in s.r_hold, "a key still inside the horizon was dropped"
    assert (1, 0) not in s.r_hold, "a receded key was kept"
    assert s.rolls_published == 1
    assert s.roll_dropped_transitions == 2


def test_r_hold_is_consumed_by_the_delivery_table():
    """H4 mutation 4: an entry in r_hold must change the open-stage carry."""
    prof = lambda t: 1.2 if t < 3.0 else 0.35      # closed, then open
    prev = _synthetic_preview(prof, n_stages=10)
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    p = M.Planner()
    j_open = next(j for j in range(10)
                  if all(m == M.STAGE_OPEN for m in pre.mode[j]))
    base = p.delivery_table(pre, {}, 0.5, [False] * 10)[0]
    # Force the carried ratio at the stage BEFORE the open one.
    key = (pre.stage_key[j_open - 1], 0)
    forced = p.delivery_table(pre, {key: 0.11}, 0.5, [False] * 10)[0]
    assert forced[j_open][0] == pytest.approx(0.11)
    assert forced[j_open][0] != pytest.approx(base[j_open][0])


def test_delivery_table_applies_the_minority_clip():
    """H4 mutation 1: at I_tot 0.7 A the 0.30 A minority floor binds."""
    prof = lambda t: 0.7
    prev = _synthetic_preview(prof, n_stages=4)
    pre = M.precompute_stages(prev, 0, 4, mode_seed=M.STAGE_CLOSED)
    p = M.Planner()
    d = p.delivery_table(pre, {}, 0.5, [False] * 4)[0]
    lo = M.GOV_MINORITY_A / 0.7
    assert lo == pytest.approx(0.42857142857142855)
    # The bottom ladder point 0.15 is BELOW the floor and must come back
    # clipped.  (0.25 before the 2026-09-02 band widening; the clip binds
    # HARDER now, which is the point of asserting it here.)
    assert p.ladder[0] == pytest.approx(0.15)
    assert d[0][0] == pytest.approx(lo)
    # The top point 0.85 is above 1 - lo and must come back clipped too.
    assert d[0][-1] == pytest.approx(1.0 - lo)
    # And the middle point, which the clip does not bind on, is untouched.
    # Index 4 is the centre of a NINE-point ladder (0.15 + 4*0.0875 = 0.50).
    assert p.ladder[4] == pytest.approx(0.5)
    assert d[0][4] == pytest.approx(0.5)


def test_charge_stage_cost_carries_the_charger_bus_power():
    """H4 mutations 2 and 3: the charger's draw and the SoC sign."""
    prof = lambda t: 0.5
    prev = _synthetic_preview(prof, n_stages=8)
    prev.chg_ok = [True] * len(prev.times)
    pre = M.precompute_stages(prev, 0, 8, mode_seed=M.STAGE_CLOSED)
    p = M.Planner(horizon=8, blocks=(2, 2, 4), terminal_mode=0.0, chg_a=0.8)
    tabs = p.delivery_table(pre, {}, 0.5, [True] * 8, soc_hint=0.6)
    cost, soc_n, _ = p._rollout(0.60, 0.60, pre, tabs, [True] * 8, (0, 0, 0),
                                float("inf"))
    # THE SIGN: eight charge stages RAISE the state of charge by chg_a*dt/cap.
    assert soc_n == pytest.approx(0.60 + 8 * 0.8 * 1.0 / p.cap_as, rel=0, abs=1e-15)
    # TERM FOR TERM: the stage cost is the demand PLUS the charger's bus power.
    sim_mod = M._load_sim()
    want = 0.0
    soc = 0.60
    for j in range(8):
        p_fc = (pre.p_dem_mean[j] + chg.charger_bus_power_w(
            0.8, pre.v_bus_mean[j], M.pack_charge_voltage(soc, 0.8),
            p.eta_chg))
        want += p.h2_rate_gps(p_fc / sim_mod.ETA_BOOST) * 1.0
        soc += 0.8 * 1.0 / p.cap_as
    assert cost == pytest.approx(want, rel=1e-12)
    # STRICTLY HIGHER than the same rollout with the charger's draw removed:
    # dropping the term is not a rounding-level mutation.
    bare = sum(p.h2_rate_gps(pre.p_dem_mean[j] / sim_mod.ETA_BOOST) * 1.0
               for j in range(8))
    assert cost > bare * (1.0 + 1e-6)


@pytest.mark.parametrize("eta", [None, 0.70, chg.ETA_CHG_DEFAULT])
def test_charge_stage_cost_tracks_the_charger_era(eta):
    """H4 mutation 2, second arm: the charge cost moves with the charger model.

    The eta era bills the charger at the PACK voltage divided by eta, the old
    era at the BUS voltage on a 1:1 current transfer, so the eta era is the
    CHEAPER of the two at this rig's voltages (7.4 V / 0.88 against 15.95 V) -
    which is the arithmetic behind the charge lever crossing sdp_policy_v3's
    admission threshold.  Inside the eta era a WORSE charger costs more."""
    # 0.2 A of source total: the 1:1 era draws the full 0.8 A charge current at
    # the bus, and 0.2 + 0.8 = 1.0 A must stay inside the 1.19 A margin or the
    # reference arm is refused as infeasible rather than priced.
    prof = lambda t: 0.2
    prev = _synthetic_preview(prof, n_stages=8)
    pre = M.precompute_stages(prev, 0, 8, mode_seed=M.STAGE_CLOSED)
    p = M.Planner(horizon=8, blocks=(2, 2, 4), terminal_mode=0.0, chg_a=0.8,
                  eta_chg=eta)
    tabs = p.delivery_table(pre, {}, 0.5, [True] * 8, soc_hint=0.6)
    cost, _, _ = p._rollout(0.60, 0.60, pre, tabs, [True] * 8, (0, 0, 0),
                            float("inf"))
    ref = M.Planner(horizon=8, blocks=(2, 2, 4), terminal_mode=0.0, chg_a=0.8,
                    eta_chg=None)
    ref_tabs = ref.delivery_table(pre, {}, 0.5, [True] * 8, soc_hint=0.6)
    ref_cost, _, _ = ref._rollout(0.60, 0.60, pre, ref_tabs, [True] * 8,
                                  (0, 0, 0), float("inf"))
    if eta is None:
        assert cost == pytest.approx(ref_cost, rel=1e-15)
    else:
        # Cheaper than the 1:1 current-transfer era ...
        assert cost < ref_cost
    if eta == 0.70:
        # ... and dearer than the same era with a better charger.
        better = M.Planner(horizon=8, blocks=(2, 2, 4), terminal_mode=0.0,
                           chg_a=0.8, eta_chg=chg.ETA_CHG_DEFAULT)
        b_tabs = better.delivery_table(pre, {}, 0.5, [True] * 8, soc_hint=0.6)
        b_cost, _, _ = better._rollout(0.60, 0.60, pre, b_tabs, [True] * 8,
                                       (0, 0, 0), float("inf"))
        assert cost > b_cost


def test_the_terminal_price_moves_the_first_move():
    """H4 mutation 5: a zeroed terminal cost is not a silent no-op.

    ⚠️ AN EXPLICIT, LARGE BUDGET IS REQUIRED (2026-09-02, the band widening).
    This test asserts a property of the OPTIMUM -- that a dearer terminal state
    of charge never asks less of the fuel cell -- and the search is ANYTIME, so
    at the default budget it returns a truncated incumbent instead.  At nine
    ladder points the enumeration is 729 candidates for a single charge option
    against 343 before, and the default budget explored only 433-540 of them:
    the sequence came back [0.15, 0.5, 0.675, 0.5, 0.5], non-monotone purely
    because the later solves saw fewer candidates.  With the budget lifted it
    is [0.15, 0.15, 0.85, 0.85, 0.85], which is monotone AND spans the full
    band -- a stronger reading of the same property than the old ladder could
    express.  Nothing about the controller changed; a test of the optimum must
    not be a test of the wall clock."""
    shares = []
    for rho in (0.0, 1.0, M.RHO_METRIC_G_PER_SOC, M.RHO_SDP_SHADOW_G_PER_SOC,
                20.0):
        s = M.MpcStrategy("mpc-det", terminal_price_mode=rho,
                          budget_ms=1.0e5)
        s.bind_scenario(SCEN, _meta())
        pre = M.precompute_stages(s.preview, s.preview.index(20.0),
                                  M.HORIZON_N, mode_seed=M.STAGE_CLOSED)
        dec = s.planner.solve(0.58, 0.60, pre, {}, 0.5, [[False] * M.HORIZON_N])
        shares.append(dec.share)
    assert len(set(shares)) >= 2, shares
    # A dearer terminal state of charge never asks LESS of the fuel cell.
    assert all(b >= a - 1e-12 for a, b in zip(shares, shares[1:])), shares
    assert shares[0] == pytest.approx(M.SHARE_BAND_DP[0])


def test_chunked_rolls_reproduce_the_unsliced_roll_exactly():
    """M1: the chunking is a scheduling change, not a numerical one."""
    prof = lambda t: 1.2 if (t < 4.0 or t >= 8.0) else 0.35
    prev = _synthetic_preview(prof, n_stages=12)
    pre = M.precompute_stages(prev, 0, 12, mode_seed=M.STAGE_CLOSED)
    ladder = [0.25, 0.5, 0.75]
    whole = M.RollJob(pre, ladder)
    whole.run_all()
    sliced = M.RollJob(pre, ladder)
    while not sliced.done:
        sliced.advance(0.0)          # one chunk per call
    assert sliced.table == whole.table
    assert sliced.chunks > len(sliced.items), "the job was not actually chunked"


def test_the_roll_slice_overshoot_is_one_chunk_not_one_item():
    """M1: the measured bound the callback arithmetic rests on."""
    prof = lambda t: 1.2 if int(t) % 2 == 0 else 0.35
    prev = _synthetic_preview(prof, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    job = M.RollJob(pre, [0.25 + i * 0.5 / 6.0 for i in range(7)])
    assert job.dropped_transitions >= 0
    worst = 0.0
    while not job.done:
        t0 = time.perf_counter()
        job.advance(M.ROLL_BUDGET_MS_DEFAULT * 1e-3)
        worst = max(worst, (time.perf_counter() - t0) * 1e3)
    # One whole item is ~2.7 ms; a chunk is ~0.3 ms.  The band is generous
    # against a loaded host but still fails a return to per-item granularity.
    assert worst < M.ROLL_BUDGET_MS_DEFAULT + 2.0, worst


def test_the_stochastic_variant_subtracts_its_own_charger_draw():
    """M2: the campaign-000816 self-load subtraction, as SdpStrategy does it."""
    s = M.MpcStrategy("mpc-sto", variant="sto", tpm_path=TPM_PATH)
    s.bind_scenario(SCEN, _meta())
    seen = []
    orig = M.MpcStrategy._bin_of
    M.MpcStrategy._bin_of = lambda self, p: (seen.append(p) or orig(self, p))
    try:
        fb = {"t": 5.0, "soc": 0.70, "V_bus": 16.0, "I_fc": 0.8,
              "I_batt": 0.4, "I_charge": 0.5, "v_profile": 1.5}
        s.latch.arm(5.0, 1.5)              # a hold is in force
        s.decide(5.0, fb)
    finally:
        M.MpcStrategy._bin_of = orig
    # 16.0*(0.8+0.4) = 19.2 W of demand, less 16.0*0.5 = 8.0 W of charger.
    assert seen and seen[-1] == pytest.approx(11.2)
    # With no hold in force the charger term is NOT subtracted.
    s.latch.reset()
    seen.clear()
    M.MpcStrategy._bin_of = lambda self, p: (seen.append(p) or orig(self, p))
    try:
        s.decide(6.0, {"t": 6.0, "soc": 0.70, "V_bus": 16.0, "I_fc": 0.8,
                       "I_batt": 0.4, "I_charge": 0.5, "v_profile": 1.5})
    finally:
        M.MpcStrategy._bin_of = orig
    assert seen and seen[-1] == pytest.approx(19.2)


def test_the_demand_map_is_read_from_the_sdp_artifact():
    """M3: the map and the bin edges come from the file, not from a constant."""
    import json
    s = M.MpcStrategy("mpc-sto", variant="sto", tpm_path=TPM_PATH)
    s.bind_scenario(SCEN, _meta())
    path = os.path.join(HERE, "sdp_policies", M.SDP_POLICY_FOR_DEMAND_MAP)
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert s.tpm_map_w == (doc["normalization"]["p_dem_min_w"],
                           doc["normalization"]["p_dem_max_w"])
    assert s.tpm_edges == [float(e) for e in doc["demand_bins"]["edges"]]
    assert len(s.tpm_edges) - 1 == len(s.tpm)
    assert s.provenance["demand_map_source"] == \
        doc["normalization"]["demand_map_source"]
    # The constant is the ASSERTION, not the source.
    assert s.tpm_map_w == M.DEMAND_MAP_W_EXPECTED
    # And the bin a measured power lands in is the bin the SDP would use.
    assert s._bin_of(23.5) == 23


def test_the_demand_map_actually_flows_from_the_file(tmp_path, monkeypatch):
    """M3, second arm: the shipped artifact's map EQUALS the old hard-coded
    one, so an equality test alone cannot tell a reader from a constant.  This
    arm points the loader at a DIFFERENT artifact and requires the difference to
    reach the strategy - through the refusal on the map, and through the edges
    on a file whose partition is not uniform."""
    import json
    src = os.path.join(HERE, "sdp_policies", M.SDP_POLICY_FOR_DEMAND_MAP)
    with open(src, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    def _write(name, doc_):
        d = tmp_path / "sdp_policies"
        d.mkdir(exist_ok=True)
        (d / name).write_text(json.dumps(doc_), encoding="utf-8")
        monkeypatch.setattr(M, "_TOOLS", str(tmp_path))
        monkeypatch.setattr(M, "SDP_POLICY_FOR_DEMAND_MAP", name)

    moved = json.loads(json.dumps(doc))
    moved["normalization"]["p_dem_max_w"] = 30.0
    _write("moved.json", moved)
    with pytest.raises(ValueError, match="demand map"):
        M.MpcStrategy("mpc-sto", variant="sto",
                      tpm_path=TPM_PATH).bind_scenario(SCEN, _meta())

    # A non-uniform partition on the SAME map: the edges must be the file's.
    skewed = json.loads(json.dumps(doc))
    n = len(skewed["demand_bins"]["edges"]) - 1
    skewed["demand_bins"]["edges"] = [(i / n) ** 2 for i in range(n + 1)]
    _write("skewed.json", skewed)
    s2 = M.MpcStrategy("mpc-sto", variant="sto", tpm_path=TPM_PATH)
    s2.bind_scenario(SCEN, _meta())
    assert s2.tpm_edges == [(i / n) ** 2 for i in range(n + 1)]
    assert s2.tpm_edges != [i / n for i in range(n + 1)]
    # A skewed partition puts the same power in a different bin, which is the
    # whole point: the classification is the artifact's, not this module's.
    assert s2._bin_of(23.5) != 23


def test_the_modal_bin_of_this_stimulus_has_no_self_transition():
    """M4: the 0.762 diagonal mass is occupancy-weighted, not this bin's."""
    s = M.MpcStrategy("mpc-sto", variant="sto", tpm_path=TPM_PATH)
    s.bind_scenario(SCEN, _meta())
    census = {}
    for p in s.preview.p_dem:
        b = s._bin_of(p)
        census[b] = census.get(b, 0) + 1
    modal = max(census.items(), key=lambda kv: kv[1])
    assert modal[0] == 23 and modal[1] == 250 and len(s.preview.p_dem) == 611
    # EXACTLY zero, not merely small: the matrix says this bin never repeats.
    assert s.tpm[23][23] == 0.0
    assert math.fsum(s.tpm[23]) == pytest.approx(1.0, abs=1e-9)
    # One step from the modal bin the conditional mean falls off its centre by
    # 2 W, so `mpc-sto` systematically UNDER-predicts this stimulus's cruise.
    lo, hi = s.tpm_map_w
    centre = lo + (hi - lo) * (23 + 0.5) / len(s.tpm)
    assert centre == pytest.approx(23.5)
    assert s._tpm_forecast(23)[0][0] == pytest.approx(21.5)
    assert s._tpm_forecast(23)[0][0] < centre


def test_a_charge_window_edge_is_a_transition_stage():
    """M5: the charge pair of the four transition classes (adjudication 2.1)."""
    prof = lambda t: 1.2                       # no GOVERNOR transition at all
    prev = _synthetic_preview(prof, n_stages=10)
    flat = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    assert not any(flat.transition), "the fixture must isolate the charge edge"
    n_sub = int(round(M.DECISION_DT_S / prev.dt))
    prev.chg_ok = [(4 * n_sub <= k < 7 * n_sub) for k in range(len(prev.times))]
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED,
                              chg_seed=False)
    assert pre.transition[4], "the window OPENING is not a transition"
    assert pre.transition[7], "the window CLOSING is not a transition"
    assert sum(1 for x in pre.transition if x) == 2
    # And the OPTION's own boundary is one too, even where the mask is flat.
    job = M.RollJob(flat, [0.25, 0.75],
                    charge_stage=lambda j: 2 <= j < 5)
    assert 2 in job.transition_stages and 5 in job.transition_stages


def test_the_deterministic_candidate_cap_is_reproducible():
    """M6: a wall clock makes the trajectory host-dependent; the cap does not."""
    prof = lambda t: 1.2
    prev = _synthetic_preview(prof, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    shares = []
    for _ in range(3):
        p = M.Planner(max_candidates=40, budget_ms=1e6)
        dec = p.solve(0.60, 0.60, pre, {}, 0.5, [[False] * 20])
        shares.append((dec.share, dec.candidates, dec.cap_hit, dec.budget_hit))
    assert len(set(shares)) == 1, shares
    assert shares[0][1] == 40 and shares[0][2] and not shares[0][3]
    # Uncapped, the same search runs the whole ladder cube.
    full = M.Planner(budget_ms=1e6)
    dec = full.solve(0.60, 0.60, pre, {}, 0.5, [[False] * 20])
    assert dec.candidates == M.SHARE_LEVELS ** len(M.MOVE_BLOCKS)
    assert not dec.cap_hit
    # A cap EQUAL to the enumeration size cuts nothing and must not flag: the
    # campaign legs set exactly this value (MPC_CAMPAIGN_MAX_CANDIDATES) so a
    # run is reproducible without reading as "capped" on every decision.
    exact = M.Planner(max_candidates=M.SHARE_LEVELS ** len(M.MOVE_BLOCKS),
                      budget_ms=1e6)
    dec = exact.solve(0.60, 0.60, pre, {}, 0.5, [[False] * 20])
    assert dec.candidates == M.SHARE_LEVELS ** len(M.MOVE_BLOCKS)
    assert not dec.cap_hit
    with pytest.raises(ValueError):
        M.Planner(max_candidates=0)


def test_load_tpm_refuses_a_matrix_that_is_not_row_stochastic(tmp_path,
                                                              monkeypatch):
    """M7: the two checks sdp_ems_solver.load_tpm() makes."""
    good = M.load_tpm(TPM_PATH)
    calls = {"n": 0}

    def fake(path, name="TPM"):
        calls["n"] += 1
        return {"TPM": (2, 2, [0.5, 0.5, 0.5, 0.5])}

    monkeypatch.setattr(M, "load_mat_doubles", fake)
    assert M.load_tpm("x") == [[0.5, 0.5], [0.5, 0.5]]
    monkeypatch.setattr(M, "load_mat_doubles",
                        lambda p, name="TPM": {"TPM": (2, 2, [0.5, 0.5, 0.4,
                                                              0.5])})
    with pytest.raises(ValueError, match="not 1"):
        M.load_tpm("x")
    monkeypatch.setattr(M, "load_mat_doubles",
                        # COLUMN-MAJOR: row 0 is [1.5, -0.5], which sums to
                        # 1 and would pass the row-sum check alone.
                        lambda p, name="TPM": {"TPM": (2, 2, [1.5, 0.5, -0.5,
                                                              0.5])})
    with pytest.raises(ValueError, match="negative"):
        M.load_tpm("x")
    assert len(good) == 25


def test_share_prediction_error_is_a_stage_quantity():
    """L1: accumulated over the stage, scored once per decision."""
    s = _bound()
    prev = s.preview
    soc, t = 0.70, 0.0
    scored = []
    while t < 20.0:
        k = prev.index(t)
        before = s.share_pred_err_n
        s(t, {"t": t, "soc": soc, "V_bus": prev.v_bus[k],
              "I_fc": 0.6 * prev.i_total[k], "I_batt": 0.4 * prev.i_total[k],
              "v_profile": sim.piecewise(_meta()["ems_v_profile"], t)})
        if s.share_pred_err_n > before:
            scored.append(t)
        soc -= 1e-5
        t += 0.02
    # One score per decision, not one per callback.
    assert s.share_pred_err_n == len(scored)
    assert s.share_pred_err_n <= s.decisions
    assert s.share_pred_err_n >= s.decisions - 2
    tm = s.timing()
    assert tm["share_pred_err_mean"] is not None
    assert tm["share_pred_err_mean"] <= tm["share_pred_err_max"] + 1e-12
    # The accumulator is emptied at each score, so a stage's samples cannot
    # leak into the next stage's mean.
    assert s._stage_share_n <= int(round(M.DECISION_DT_S / 0.02)) + 1


def test_stages_past_the_preview_end_are_counted():
    """L6: the horizon runs off the end of the run, and says so."""
    prof = lambda t: 1.2
    prev = _synthetic_preview(prof, n_stages=5)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    n_sub = int(round(M.DECISION_DT_S / prev.dt))
    assert pre.beyond_preview == 15 * n_sub
    # The clamped sample is the last one, i.e. the run's standstill load.
    assert pre.i_tot[19][-1] == pytest.approx(prev.i_total[-1])
    inside = M.precompute_stages(prev, 0, 5, mode_seed=M.STAGE_CLOSED)
    assert inside.beyond_preview == 0



# ═════════════════════════════════════════════════════════════════════════════
# 14. The open-loop FEEDFORWARD stage model (2026-09-02).
#
#     The firmware's open-loop branch HOLDS only while a closed-loop run stands
#     and the setpoint has not moved; otherwise it slews the applied ratio
#     toward the setpoint and WRITES the MDACs.  Every test below scores the
#     model against a full 1 kHz `GovernorModel` roll of the same stage, which
#     is the only reference this repository accepts for a delivery claim.
# ═════════════════════════════════════════════════════════════════════════════
def _open_preview(i_tot_a, n_stages=6):
    """A preview whose source total sits in the OPEN-loop regime throughout."""
    return _synthetic_preview(lambda t: i_tot_a, n_stages=n_stages)


def _roll_open_stage(prev, pre, stage, share, r0, acted, run, i_tot_a,
                     dark=False):
    """Stage-mean delivered share from a full 1 kHz roll of one OPEN stage.

    The governor is seeded with the same three firmware variables the stage
    model is seeded with - the applied ratio, `share_actedSp` and
    `shareClosedLoopRun` - so the comparison isolates the stage model."""
    g = gm.GovernorModel(dt_s=M.GOV_TICK_S, seed_r=r0)
    st = g.state
    st.r_prev = r0
    st.acted_sp = acted
    st.closed_loop_run = run
    st.closed_loop_mode = False
    st.filt_total = i_tot_a
    # The conduction-aware slew mode is seeded EXPLICITLY rather than left to
    # warm up: its filters start at zero, so an unseeded roll spends its first
    # ticks on the handoff ceiling for a reason that has nothing to do with the
    # stage under test.
    st.dark_fc = st.dark_bt = bool(dark)
    st.handoff_i_fc_filt = 0.5 * i_tot_a
    st.handoff_i_bt_filt = 0.5 * i_tot_a
    st.handoff_prev_ratio = r0
    n_sub = len(pre.i_tot[stage])
    ticks_per_sub = int(round(M.DECISION_DT_S / n_sub / M.GOV_TICK_S))
    delivered = r0
    acc = 0.0
    nn = 0
    t = 0.0
    for sub in range(n_sub):
        i_tot = pre.i_tot[stage][sub]
        for _ in range(ticks_per_sub):
            i_fc = delivered * i_tot
            o = g.step(share, i_fc, i_tot - i_fc, True, True, t)
            delivered = g.delivered_share(o.r_applied, i_tot, True, True)
            acc += delivered
            nn += 1
            t += M.GOV_TICK_S
    return acc / nn, g.state.r_prev


def test_open_feedforward_stage_matches_a_full_roll():
    """A CHANGED setpoint on an open stage slews; the model must follow it."""
    i_tot = 0.40                       # below the 0.55 A release, above 0.075
    prev = _open_preview(i_tot)
    pre = M.precompute_stages(prev, 0, 6, mode_seed=M.STAGE_OPEN)
    assert all(m == M.STAGE_OPEN for m in pre.mode[0]), "fixture is not open"
    p = M.Planner()
    si = 0                             # ladder point 0.25
    s = p.ladder[si]
    r0, acted = 0.50, 0.70             # the acted setpoint differs from s
    tab = p.delivery_table(pre, {}, r0, [False] * 6, sp_acted=acted,
                           run_seed=True)[0]
    rolled, _ = _roll_open_stage(prev, pre, 0, s, r0, acted, True, i_tot)
    # EXACT, not approximate: on the full ceiling the ramp is the arithmetic
    # series `ramp_mean()` sums, so the model and the roll agree to the last bit.
    assert tab[0][si] == pytest.approx(rolled, abs=1e-12), (
        "feedforward stage mean %.6f against a full roll's %.6f"
        % (tab[0][si], rolled))
    # ...and it must be materially different from the HOLD the old model made.
    hold = p.delivery_table(pre, {}, r0, [False] * 6)[0]
    assert hold[0][si] == pytest.approx(r0)
    assert abs(hold[0][si] - rolled) > 0.10


def test_open_hold_stage_matches_a_full_roll():
    """An UNCHANGED setpoint on an open stage holds; nothing is written."""
    i_tot = 0.40
    prev = _open_preview(i_tot)
    pre = M.precompute_stages(prev, 0, 6, mode_seed=M.STAGE_OPEN)
    p = M.Planner()
    si = 0
    s = p.ladder[si]
    r0 = 0.50
    tab = p.delivery_table(pre, {}, r0, [False] * 6, sp_acted=s,
                           run_seed=True)[0]
    rolled, r_end = _roll_open_stage(prev, pre, 0, s, r0, s, True, i_tot)
    assert rolled == pytest.approx(r0, abs=1e-12), "the roll did not HOLD"
    assert r_end == pytest.approx(r0, abs=1e-12)
    assert tab[0][si] == pytest.approx(rolled, abs=1e-12)


def test_a_cleared_run_flag_slews_even_on_an_unchanged_setpoint():
    """`shareClosedLoopRun` false is the OTHER way into the feedforward branch."""
    i_tot = 0.40
    prev = _open_preview(i_tot)
    pre = M.precompute_stages(prev, 0, 6, mode_seed=M.STAGE_OPEN)
    p = M.Planner()
    si = 0
    s = p.ladder[si]
    r0 = 0.50
    tab = p.delivery_table(pre, {}, r0, [False] * 6, sp_acted=s,
                           run_seed=False)[0]
    rolled, _ = _roll_open_stage(prev, pre, 0, s, r0, s, False, i_tot)
    assert tab[0][si] == pytest.approx(rolled, abs=1e-12)
    assert abs(tab[0][si] - r0) > 0.10, "the model held where the firmware slews"


def test_the_handoff_ceiling_slows_the_modelled_ramp():
    """A roll that ended DARK selects the 0.002/tick ceiling for that stage."""
    i_tot = 0.20                       # both channels under SHARE_HANDOFF_MIN_A
    prev = _open_preview(i_tot)
    pre = M.precompute_stages(prev, 0, 6, mode_seed=M.STAGE_OPEN)
    p = M.Planner()
    si = 0
    s = p.ladder[si]
    r0, acted = 0.75, 0.75
    key = (pre.stage_key[0], si)
    slow = p.delivery_table(pre, {}, r0, [False] * 6, sp_acted=acted,
                            run_seed=False, handoff={key: True})[0]
    fast = p.delivery_table(pre, {}, r0, [False] * 6, sp_acted=acted,
                            run_seed=False)[0]
    rolled, _ = _roll_open_stage(prev, pre, 0, s, r0, acted, False, i_tot,
                                 dark=True)
    # The handoff ceiling is ten times slower, so the stage mean sits HIGHER:
    # the ramp spends longer near its 0.75 start.
    assert slow[0][si] > fast[0][si] + 1e-3
    # Not exact: the dwell allowance is spent on MOVING ticks and the release
    # to the full ceiling therefore lands one tick apart from the model's.
    assert slow[0][si] == pytest.approx(rolled, abs=5e-4), (
        "handoff stage mean %.6f against a full roll's %.6f"
        % (slow[0][si], rolled))
    assert abs(fast[0][si] - rolled) > abs(slow[0][si] - rolled)


def test_ramp_mean_equals_a_tick_loop():
    """The closed form is the arithmetic series a per-tick loop would sum."""
    import random
    rng = random.Random(20260902)
    for _ in range(200):
        r0 = rng.uniform(0.0, 1.0)
        tgt = rng.uniform(M.DROOP_R_MIN, M.DROOP_R_MAX)
        n = rng.choice((1, 7, 100, 250))
        dwell = rng.choice((0, 5, 175))
        slow = rng.choice((None, M.SLEW_HANDOFF_PER_TICK))
        mean, end, dw = M.ramp_mean(r0, tgt, n, step_slow=slow,
                                    dwell_left=dwell)
        # The reference: one tick at a time, exactly as the firmware writes.
        r = r0
        acc = 0.0
        left = dwell
        for _k in range(n):
            step = (M.SLEW_HANDOFF_PER_TICK
                    if (slow is not None and left > 0)
                    else M.SLEW_FULL_PER_TICK)
            nxt = min(max(tgt, r - step), r + step)
            if slow is not None and left > 0 and abs(nxt - r) > 1e-15:
                left -= 1
            r = nxt
            acc += r
        assert mean == pytest.approx(acc / n, abs=1e-12)
        assert end == pytest.approx(r, abs=1e-12)
        assert dw == left


def test_the_feedforward_branch_is_inert_without_the_seeds():
    """BYTE IDENTITY: no seeds, or a seed pair that HOLDS, is the old table."""
    prof = lambda t: 1.2 if t < 3.0 else 0.35
    prev = _synthetic_preview(prof, n_stages=10)
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    p = M.Planner()
    base = p.delivery_table(pre, {}, 0.5, [False] * 10)
    for si in range(len(p.ladder)):
        # A seed pair naming THIS ladder point holds on every open sub-sample,
        # so the column it builds must be bit-identical to the hold-only one.
        held = p.delivery_table(pre, {}, 0.5, [False] * 10,
                                sp_acted=p.ladder[si], run_seed=True)
        for tab_new, tab_old in zip(held, base):
            assert tab_new[0][si] == tab_old[0][si]
            for j in range(10):
                assert tab_new[j][si] == tab_old[j][si]
    none_seeded = p.delivery_table(pre, {}, 0.5, [False] * 10, sp_acted=None,
                                   run_seed=True)
    assert none_seeded[0] == base[0]
    assert p.delivery_table(pre, {}, 0.5, [False] * 10, sp_acted=0.4,
                            run_seed=None)[0] == base[0]


def test_the_asymmetry_map_is_inert_at_dv0_zero():
    """dv0 = 0 degenerates the droop map to the identity, bit-for-bit."""
    prof = lambda t: 1.2 if t < 3.0 else 0.35
    prev = _synthetic_preview(prof, n_stages=10)
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    a = M.Planner(dv0_v=0.0).delivery_table(pre, {}, 0.5, [False] * 10,
                                            sp_acted=0.4, run_seed=True)
    b = M.Planner().delivery_table(pre, {}, 0.5, [False] * 10,
                                   sp_acted=0.4, run_seed=True)
    assert a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
    c = M.Planner(dv0_v=0.030223).delivery_table(pre, {}, 0.5, [False] * 10,
                                                 sp_acted=0.4, run_seed=True)
    assert c[0] != a[0], "a non-zero dv0 left the delivered share unchanged"


def test_the_strategy_seeds_the_branch_from_the_shadow_governor():
    """The two seeds reaching `solve()` are the shadow governor's own state."""
    seen = {}
    s = _bound()
    orig = s.planner.solve

    def spy(*a, **kw):
        seen.update(kw)
        return orig(*a, **kw)

    s.planner.solve = spy
    s.shadow.model.state.acted_sp = 0.3125
    s.shadow.model.state.closed_loop_run = True
    s.decide(20.0, {"soc": 0.7, "I_fc": 0.3, "I_batt": 0.3, "V_bus": 15.9,
                    "v_profile": 1.5})
    assert seen["sp_acted"] == pytest.approx(0.3125)
    assert seen["run_seed"] is True
    assert seen["handoff"] is s.r_handoff


def test_the_roll_carry_is_skipped_on_a_feedforward_stage():
    """r_hold is a HELD-command result and must not overwrite a modelled slew."""
    i_tot = 0.40
    prev = _open_preview(i_tot)
    pre = M.precompute_stages(prev, 0, 6, mode_seed=M.STAGE_OPEN)
    p = M.Planner()
    si = 0
    key = (pre.stage_key[0], si)
    # HOLD: the roll's carry is consumed, exactly as before.
    held = p.delivery_table(pre, {key: 0.11}, 0.5, [False] * 6,
                            sp_acted=p.ladder[si], run_seed=True)[0]
    assert held[1][si] == pytest.approx(0.11)
    # FEEDFORWARD: the modelled ramp is the carry, and 0.11 is ignored.
    ff = p.delivery_table(pre, {key: 0.11}, 0.5, [False] * 6,
                          sp_acted=0.70, run_seed=True)[0]
    assert ff[1][si] != pytest.approx(0.11)
    assert ff[1][si] == pytest.approx(p.ladder[si], abs=1e-9)


def test_the_roll_job_publishes_a_handoff_flag():
    """The roll records the conduction-handoff state it ended in."""
    prof = lambda t: 1.2 if t < 5.0 else 0.35
    prev = _synthetic_preview(prof, n_stages=10)
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    job = M.RollJob(pre, [0.25, 0.5, 0.75])
    job.run_all()
    assert set(job.handoff) == set(job.table)
    assert all(isinstance(v, bool) for v in job.handoff.values())


def test_disabling_the_feedforward_branch_raises_the_prediction_error():
    """MUTATION: the branch is what carries the Gate-1 improvement.

    The fixture is a 61 s closed loop over the `ems-soc-band` preview, driven the
    way the walk drives it, and the scored quantity is the strategy's own
    `share_pred_err` - the Gate-1 metric, not a new one."""
    def _run(disable):
        s = _bound()
        if disable:
            orig = M.Planner.delivery_table

            def patched(self, pre, r_hold, r_seed, charge_stages,
                        i_tot_oc=None, soc_hint=0.6, sp_acted=None,
                        run_seed=None, handoff=None, active=None,
                        pre_ss=None):
                # `pre_ss` (2026-09-03) is FORWARDED rather than dropped: this
                # mutation disables the FEEDFORWARD seeds only, and a patch
                # that also dropped the single-source demand would measure two
                # mutations at once.
                return orig(self, pre, r_hold, r_seed, charge_stages, i_tot_oc,
                            soc_hint, None, None, None, active, pre_ss)
            s.planner.delivery_table = patched.__get__(s.planner, M.Planner)
        g = gm.GovernorModel(dt_s=M.GOV_TICK_S,
                             seed_r=sim.SOC_BAND_SHARE_NOMINAL)
        prev = s.preview
        delivered = sim.SOC_BAND_SHARE_NOMINAL
        t = 0.0
        n_sub = int(round(0.02 / M.GOV_TICK_S))
        while t < 61.0:
            k = prev.index(t)
            i_tot = prev.i_total[k]
            i_fc = delivered * i_tot
            out = s(t, {"soc": 0.7, "I_fc": i_fc, "I_batt": i_tot - i_fc,
                        "V_bus": prev.v_bus[k], "I_charge": 0.0,
                        "v_profile": 1.5})
            share = float(out["power_share_setpoint"])
            for i in range(n_sub):
                i_fc = delivered * i_tot
                o = g.step(share, i_fc, i_tot - i_fc, True, True,
                           t + i * M.GOV_TICK_S)
                delivered = g.delivered_share(o.r_applied, i_tot, True, True)
            t += 0.02
        return s.timing()["share_pred_err_mean"], s.share_pred_err_max

    on_mean, on_max = _run(False)
    off_mean, off_max = _run(True)
    assert on_mean is not None and off_mean is not None
    assert on_mean < 5e-3, "the shipped model missed the Gate 1 band"
    assert off_mean > 5e-3, "the mutation did not raise the error"
    assert off_mean > 5.0 * on_mean
    assert off_max > on_max



# ═════════════════════════════════════════════════════════════════════════════
# 15. The adaptive solve budget and the transition-aware ladder coarsening
#     (2026-09-02).
# ═════════════════════════════════════════════════════════════════════════════
def test_derive_budget_ms_is_the_callback_bound():
    """The derivation is the banner's arithmetic, term for term."""
    b = M.derive_budget_ms(roll_slice_ms=2.0, surface_ms=0.2, rollout_ms=0.01,
                           command_period_ms=20.0, margin_ms=2.0,
                           floor_ms=0.0, ceiling_ms=1e6)
    assert b == pytest.approx(20.0 - 2.0 - 2.0 - 0.2 - 0.01)
    # Every term SPENDS budget: raising any of the four lowers the result.
    for kw in ({"roll_slice_ms": 3.0}, {"surface_ms": 1.2},
               {"rollout_ms": 1.01}, {"margin_ms": 3.0}):
        base = {"roll_slice_ms": 2.0, "surface_ms": 0.2, "rollout_ms": 0.01,
                "margin_ms": 2.0, "floor_ms": 0.0, "ceiling_ms": 1e6}
        base.update(kw)
        assert M.derive_budget_ms(**base) < b - 0.9


def test_derive_budget_ms_clamps_and_falls_back_to_the_nominals():
    """A pathological measurement can neither starve nor monopolise the search."""
    assert M.derive_budget_ms(roll_slice_ms=100.0) == M.BUDGET_MS_FLOOR
    assert M.derive_budget_ms(roll_slice_ms=0.0, surface_ms=0.0,
                              rollout_ms=0.0) == M.BUDGET_MS_CEILING
    # With nothing measured the nominal terms of the banner are used.
    assert M.derive_budget_ms() == pytest.approx(
        min(M.BUDGET_MS_CEILING,
            M.COMMAND_PERIOD_MS - M.BUDGET_MARGIN_MS
            - (M.ROLL_BUDGET_MS_DEFAULT + M.ROLL_CHUNK_OVERSHOOT_MS)
            - M.SURFACE_MS_NOMINAL - M.ROLLOUT_MS_NOMINAL))


def test_an_explicit_budget_takes_precedence_over_the_derivation():
    """The `mpc_budget_ms` scenario key must still work, and must win."""
    fixed = M.MpcStrategy("mpc-det", budget_ms=7.5)
    assert fixed.budget_ms_fixed is True
    assert fixed.adaptive_budget is False
    adaptive = M.MpcStrategy("mpc-det")
    assert adaptive.budget_ms is None and adaptive.adaptive_budget is True
    # ...and the scenario key reaches the constructor through the same name.
    kw = sim.mpc_configure_kwargs(
        type("A", (), {"mpc_max_candidates": None})(), {"mpc_budget_ms": 15.0})
    assert kw["budget_ms"] == pytest.approx(15.0)

    s = _bound(budget_ms=7.5)
    prev = s.preview
    t = 0.0
    while t < 4.0:
        k = prev.index(t)
        s(t, {"soc": 0.7, "V_bus": prev.v_bus[k], "I_fc": 0.5 * prev.i_total[k],
              "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
        t += 0.02
    assert set(s.budget_ms_all) == {7.5}, "the fixed budget was not honoured"


def test_the_adaptive_budget_is_reported_per_decision():
    s = _bound()
    prev = s.preview
    t = 0.0
    while t < 6.0:
        k = prev.index(t)
        s(t, {"soc": 0.7, "V_bus": prev.v_bus[k], "I_fc": 0.5 * prev.i_total[k],
              "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
        t += 0.02
    tm = s.timing()
    assert tm["budget_adaptive"] is True
    assert tm["decisions"] == len(s.budget_ms_all)
    assert M.BUDGET_MS_FLOOR <= tm["budget_ms_min"] <= tm["budget_ms_median"]
    assert tm["budget_ms_median"] <= tm["budget_ms_max"] <= M.BUDGET_MS_CEILING
    assert tm["ladder_points_min"] >= 3
    assert tm["ladder_points_max"] <= len(s.planner.ladder)
    assert "budget" in s.summary_line() and "ladder" in s.summary_line()


def test_coarsen_ladder_is_pure_and_deterministic():
    """Same arguments, same answer - and no wall clock is read."""
    args = dict(n_levels=7, n_blocks=3, n_options=3, incumbent=(3, 3, 3),
                budget_ms=10.0, n_transitions=0, candidate_cost_ms=0.0162)
    first = M.coarsen_ladder(**args)
    for _ in range(20):
        assert M.coarsen_ladder(**args) == first
    assert first == tuple(sorted(set(first))), "the result is not sorted"


def test_coarsen_ladder_fits_the_full_enumeration_in_the_budget():
    """M1: the REALISED set is what must fit, and it is asserted exactly.

    The earlier form of this test budgeted the rule's nominal size and allowed
    the realised set to overrun it by 2.2x, which is how a nominal four came to
    be admitted on an allowance sized for 64 candidates and then walk 125."""
    for budget in (4.0, 7.5, 10.0, 15.0):
        for n_opt in (1, 2, 3):
            for inc in (None, (4, 4, 4), (0, 6, 3)):
                act = M.coarsen_ladder(7, 3, n_opt, incumbent=inc,
                                       budget_ms=budget,
                                       candidate_cost_ms=0.0162)
                allow = M.LADDER_ENUM_SAFETY * budget / 0.0162
                smallest = M.coarse_ladder_set(7, min(M.LADDER_SIZES), inc)
                if n_opt * len(smallest) ** 3 > allow:
                    # Nothing fits; the floor set is returned and the budget
                    # expiry is what reports it.
                    assert act == smallest
                    continue
                assert n_opt * len(act) ** 3 <= allow, (budget, n_opt, inc, act)


def test_every_ladder_size_is_reachable_and_distinct():
    """M1: no dead entry.  A size whose realised set duplicates a larger one's
    can never be selected, because selection walks the sizes descending and
    stops at the first realised set that fits."""
    seen = {}
    for k in M.LADDER_SIZES:
        got = M.coarse_ladder_set(7, k)
        assert got not in seen.values(), (
            "size %r realises the same set as size %r" % (k, seen))
        seen[k] = got
    # ...and the one that WAS dead is gone: a nominal four realises the
    # five-point set, because the centre is always unioned in.
    assert 4 not in M.LADDER_SIZES
    assert M.coarse_ladder_set(7, 4) == M.coarse_ladder_set(7, 5)


def test_a_transition_heavy_horizon_coarsens_sooner():
    """The transition count halves the allowance, by the roll cap's definition."""
    quiet = M.coarsen_ladder(7, 3, 3, budget_ms=15.0, n_transitions=0,
                             candidate_cost_ms=0.0097)
    heavy = M.coarsen_ladder(7, 3, 3, budget_ms=15.0,
                             n_transitions=M.RollJob.MAX_TRANSITIONS,
                             candidate_cost_ms=0.0097)
    assert len(quiet) == 7, "the quiet horizon should not coarsen here"
    assert len(heavy) < 7, "the transition-heavy horizon did not coarsen"


def test_the_coarse_ladder_keeps_the_rails_the_centre_and_the_incumbent():
    """THE INCUMBENT-RETENTION INVARIANT: the shifted incumbent stays a candidate."""
    n = 7
    for inc in (None, (0, 0, 0), (6, 6, 6), (1, 5, 2), (3, 4, 1)):
        act = M.coarsen_ladder(n, 3, 3, incumbent=inc, budget_ms=6.0,
                               candidate_cost_ms=0.0162)
        assert 0 in act and n - 1 in act, "a rail was dropped"
        assert (n - 1) // 2 in act, "the centre was dropped"
        for v in (inc or ()):
            assert v in act, "an incumbent block value was dropped"


def test_the_enumeration_walks_only_the_active_set_and_starts_at_the_incumbent():
    p = M.Planner()
    p.incumbent = (0, 6, 3)
    active = M.coarsen_ladder(7, 3, 3, incumbent=p.incumbent, budget_ms=5.0,
                              candidate_cost_ms=0.0162)
    order = p._enumeration_order(active, 3)
    assert order[0] == (0, 6, 3), "the warm start is not the incumbent"
    assert len(order) == len(active) ** 3
    for cand in order:
        assert all(c in active for c in cand)


def test_a_coarsened_solve_returns_a_candidate_from_the_active_set():
    prev = _synthetic_preview(lambda t: 1.2, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    p = M.Planner()
    active = (0, 3, 6)
    dec = p.solve(0.7, 0.7, pre, {}, 0.5, [[False] * 20], active=active)
    assert dec.ladder_points == 3
    assert dec.share in [p.ladder[i] for i in active]
    assert dec.candidates <= 27


def test_the_coarsening_does_not_move_the_walk_totals():
    """MEASURED: on the registered stimulus the coarser search commits the same
    plan, so the coarsening buys wall clock and an uncut search, not a
    different trajectory.  A change here is a finding, not a failure."""
    # `ems_walk` reaches gen_dp_ems_table, which needs numpy, so this one runs
    # under miniforge and SKIPS under `.venv_hil` like the other walk-backed
    # checks in this file.
    pytest.importorskip("numpy")
    ems_walk = pytest.importorskip("ems_walk")
    out = {}
    for label, kw in (("full", {"coarsen_ladder_enabled": False,
                                "budget_ms": 1e5}),
                      ("coarse", {"budget_ms": 15.0,
                                  "candidate_cost_ms": 0.0162})):
        r = ems_walk.walk("mpc-det", SCEN, soc0=0.7, governor=True,
                          strategy_kwargs=dict(kw))
        out[label] = (round(r.h2_g, 9), round(r.delta_soc, 9))
    assert out["full"] == out["coarse"], out


def test_a_frozen_sub_sample_holds_whatever_the_setpoint_did():
    """The minimum-load gate returns BEFORE the loop-mode decision (.ino:10099).

    A sub-sample under `SHARE_I_TOT_MIN_A` writes nothing, so a changed setpoint
    must NOT be modelled as a feedforward slew there."""
    i_tot = 0.5 * gm.GOV_CONST["SHARE_I_TOT_MIN_A"]      # 0.0375 A, frozen
    prev = _open_preview(i_tot)
    pre = M.precompute_stages(prev, 0, 6, mode_seed=M.STAGE_OPEN)
    assert all(m == M.STAGE_FROZEN for m in pre.mode[0]), "fixture is not frozen"
    p = M.Planner()
    si, r0 = 0, 0.50
    tab = p.delivery_table(pre, {}, r0, [False] * 6, sp_acted=0.70,
                           run_seed=True)[0]
    assert tab[0][si] == pytest.approx(r0), (
        "a frozen stage slewed: modelled %.6f against the standing %.4f"
        % (tab[0][si], r0))
    # ...and a full roll agrees: the governor writes nothing at this load.
    g = gm.GovernorModel(dt_s=M.GOV_TICK_S, seed_r=r0)
    g.state.acted_sp = 0.70
    g.state.closed_loop_run = True
    for k in range(1000):
        g.step(p.ladder[si], r0 * i_tot, (1.0 - r0) * i_tot, True, True,
               k * M.GOV_TICK_S)
    assert g.state.r_prev == pytest.approx(r0)
    assert g.state.mode_counts[gm.MODE_FROZEN] == 1000



# ═════════════════════════════════════════════════════════════════════════════
# 16. The fix round of 2026-09-02: the search width is wall-clock-free.
# ═════════════════════════════════════════════════════════════════════════════
def test_index_five_is_reachable_from_a_coarsened_decision():
    """H1: a share the coarse rule skips must not be structurally unreachable.

    The evenly-spaced coarse rule cannot produce every index, so some appear in
    NO coarse set.  The incumbent's NEIGHBOURS are unioned in so any index is
    one coarsened decision from an adjacent one.

    ⚠️ RE-DERIVED FOR THE NINE-POINT LADDER (2026-09-02).  The fixture used to
    name index 5 of a SEVEN-point ladder over [0.25, 0.75], which was 0.6667,
    the share `mpc-det` commanded through cruise.  The ladder is now nine
    points over [0.15, 0.85], so the skipped indices and their shares both
    move; the PROPERTY under test is unchanged and the indices are recomputed
    from the rule rather than retyped."""
    p = M.Planner()
    assert len(p.ladder) == 9
    bare = M.coarse_ladder_set(9, 5)
    skipped = [i for i in range(9) if i not in bare]
    assert skipped, "the fixture no longer bites"
    for i in skipped:
        for inc in ((max(0, i - 1),) * 3, (min(8, i + 1),) * 3,
                    (max(0, i - 1), min(8, i + 1), max(0, i - 1))):
            act = M.coarsen_ladder(9, 3, 3, incumbent=inc, budget_ms=10.0)
            assert i in act,                 "index %d unreachable from incumbent %r: %r" % (i, inc, act)
    for inc in ((0, 0, 0), (2, 2, 2)):
        act = M.coarsen_ladder(9, 3, 3, incumbent=inc, budget_ms=10.0)
        assert 1 in act, "0.3333 unreachable from incumbent %r: %r" % (inc, act)


def test_the_coarse_set_only_ever_grows_with_the_unions():
    """Every union ADDS points; none may remove one."""
    for k in M.LADDER_SIZES:
        base = set(M.coarse_ladder_set(7, k))
        for inc in (None, (0,), (3,), (5, 5, 5), (0, 3, 6)):
            got = set(M.coarse_ladder_set(7, k, inc))
            assert base <= got
            assert got <= set(range(7))
        assert {0, 6, 3} <= base, "a rail or the centre was dropped"


def test_the_search_width_reads_no_clock():
    """H1: `coarsen_ladder()` is a pure function and `decide()` feeds it the
    NOMINAL constant, never the measured per-candidate cost.

    The measurement is captured and asserted to be reported, not consumed: a
    strategy whose measured cost is driven far above the nominal must still
    produce the same active set.

    WALL-CLOCK-BUDGET TEST -- run it alone before believing a failure (see the
    module docstring; the other two are
    `test_transition_roll_slices_and_completes` and
    `test_the_committed_plan_is_insensitive_to_the_projection`)."""
    seen = []
    s = _bound(budget_ms=15.0)
    orig = s.planner.solve

    def spy(*a, **kw):
        seen.append(kw.get("active"))
        return orig(*a, **kw)

    s.planner.solve = spy
    prev = s.preview
    t = 0.0
    while t < 8.0:
        k = prev.index(t)
        # Poison the measured cost between callbacks.  It must not move the
        # active set, because nothing on that path reads it.
        s._rollout_ms = 10.0
        s(t, {"soc": 0.7, "V_bus": prev.v_bus[k], "I_fc": 0.5 * prev.i_total[k],
              "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
        t += 0.02
    poisoned = list(seen)

    seen2 = []
    s2 = _bound(budget_ms=15.0)
    orig2 = s2.planner.solve

    def spy2(*a, **kw):
        seen2.append(kw.get("active"))
        return orig2(*a, **kw)

    s2.planner.solve = spy2
    t = 0.0
    while t < 8.0:
        k = prev.index(t)
        s2(t, {"soc": 0.7, "V_bus": prev.v_bus[k],
               "I_fc": 0.5 * prev.i_total[k],
               "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
        t += 0.02
    assert poisoned == seen2, "the measured per-candidate cost moved the search"
    tm = s.timing()
    assert tm["candidate_cost_ms_nominal"] == pytest.approx(
        M.CANDIDATE_COST_MS_NOMINAL)
    assert tm["candidate_cost_ms_seen"] > 0.0
    assert isinstance(tm["candidate_cost_over_nominal"], bool)


def test_a_slow_host_is_reported_not_absorbed():
    """H1: `candidate_cost_over_nominal` is the visible signal of a host the
    projection did not size for."""
    s = _bound(budget_ms=15.0)
    prev = s.preview
    t = 0.0
    while t < 4.0:
        k = prev.index(t)
        s(t, {"soc": 0.7, "V_bus": prev.v_bus[k], "I_fc": 0.5 * prev.i_total[k],
              "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
        t += 0.02
    s.candidate_cost_ms_seen = M.CANDIDATE_COST_MS_NOMINAL * 3.0
    assert s.timing()["candidate_cost_over_nominal"] is True
    s.candidate_cost_ms_seen = M.CANDIDATE_COST_MS_NOMINAL * 0.5
    assert s.timing()["candidate_cost_over_nominal"] is False


def test_the_census_and_trajectory_are_wall_clock_free():
    """H1, end to end: a fixed budget makes the whole search width a function of
    the configuration, so the census and the committed plan are pinned.

    Both runs are driven by the same deterministic loop; nothing here reads the
    clock except the budget, which is fixed."""
    def _run():
        s = _bound(budget_ms=15.0)
        prev = s.preview
        shares = []
        t = 0.0
        while t < 61.0:
            k = prev.index(t)
            out = s(t, {"soc": 0.7 - 1e-5 * (t / 0.02),
                        "V_bus": prev.v_bus[k],
                        "I_fc": 0.5 * prev.i_total[k],
                        "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
            shares.append(round(float(out["power_share_setpoint"]), 12))
            t += 0.02
        return tuple(s.ladder_points_all), tuple(shares)

    a = _run()
    b = _run()
    assert a[0] == b[0], "the ladder census moved between two identical runs"
    assert a[1] == b[1], "the commanded share sequence moved"


def test_derive_budget_raw_ms_is_unclamped_and_the_floor_is_counted():
    """M2: the floor is a DEVIATION from the callback bound, and it says so."""
    raw = M.derive_budget_raw_ms(roll_slice_ms=18.0, surface_ms=0.2,
                                 rollout_ms=0.01)
    assert raw < 0.0, raw
    assert M.derive_budget_ms(roll_slice_ms=18.0, surface_ms=0.2,
                              rollout_ms=0.01) == M.BUDGET_MS_FLOOR
    # ...and the clamped function is exactly the raw one clamped.
    for roll in (0.0, 1.0, 2.3, 12.0, 18.0):
        assert M.derive_budget_ms(roll_slice_ms=roll) == pytest.approx(
            min(M.BUDGET_MS_CEILING,
                max(M.BUDGET_MS_FLOOR, M.derive_budget_raw_ms(roll_slice_ms=roll))))

    # `__call__()` overwrites the measured slice on every callback, so the
    # starved callback is produced at the derivation itself: a bound that comes
    # back negative must be COUNTED, not silently floored.
    s = _bound()
    prev = s.preview
    real = M.derive_budget_raw_ms
    M.derive_budget_raw_ms = lambda *a, **kw: -2.2
    try:
        t = 0.0
        while t < 4.0:
            k = prev.index(t)
            s(t, {"soc": 0.7, "V_bus": prev.v_bus[k],
                  "I_fc": 0.5 * prev.i_total[k],
                  "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
            t += 0.02
    finally:
        M.derive_budget_raw_ms = real
    tm = s.timing()
    assert tm["decisions"] > 0
    assert tm["budget_floor_binding"] == tm["decisions"]
    assert tm["budget_ms_max"] == pytest.approx(M.BUDGET_MS_FLOOR)

    clean = _bound()
    prev = clean.preview
    t = 0.0
    while t < 4.0:
        k = prev.index(t)
        clean(t, {"soc": 0.7, "V_bus": prev.v_bus[k],
                  "I_fc": 0.5 * prev.i_total[k],
                  "I_batt": 0.5 * prev.i_total[k], "v_profile": 1.5})
        t += 0.02
    assert clean.timing()["budget_floor_binding"] == 0


def test_the_committed_plan_is_insensitive_to_the_projection():
    """H1, the defect measured directly: sweep the per-candidate projection and
    watch the committed hydrogen.

    Before the fix this sweep contained an 8.29 % cliff at 0.03717 ms, because a
    coarsened decision could not reach ladder index 5 and the cruise share moved
    from 0.6667 to 0.75.  With the incumbent's neighbours unioned in, a 5x sweep
    of the projection moves the total by well under a per cent and the cruise
    share does not move at all.  A regression here is the return of the cliff.

    WALL-CLOCK-BUDGET TEST -- run it alone before believing a failure (see the
    module docstring; the other two are
    `test_transition_roll_slices_and_completes` and
    `test_the_search_width_reads_no_clock`).  Observed 2026-09-03: the cruise
    count read 260 under concurrent load against 270 alone, because the loaded
    host coarsened one more decision inside the same millisecond budget.  That
    is the budget acting as designed, not the cliff returning."""
    pytest.importorskip("numpy")
    ems_walk = pytest.importorskip("ems_walk")
    out = []
    # L2 (2026-09-03): the SHIPPED projection is in the sample. The sweep
    # bracketed `CANDIDATE_COST_MS_NOMINAL` = 0.0392 (the value shipped at the time; now 0.0360, read live from the module) without containing it, so
    # the one value the planner actually runs at was the only one never
    # measured here.
    for cost in (0.0097, 0.0300, M.CANDIDATE_COST_MS_NOMINAL, 0.0500):
        r = ems_walk.walk("mpc-det", SCEN, soc0=0.7, governor=True,
                          strategy_kwargs={"budget_ms": 15.0,
                                           "candidate_cost_ms": cost})
        # 0.675 is ladder index 6 of the NINE-point ladder
        # (0.15 + 6*0.0875); it was 0.6667 = index 5 of seven over
        # [0.25, 0.75] before the 2026-09-02 band widening.  The PROPERTY is
        # unchanged: the cruise command must not move with the projection.
        cruise = sum(1 for x in r.share_cmd if abs(x - 0.675) < 1e-9)
        out.append((cost, r.h2_g, cruise))
    base = out[0][1]
    for cost, h2, cruise in out:
        assert abs(h2 - base) / base <= 5e-3, (
            "projection %.4f moved the committed hydrogen by %.3f %%"
            % (cost, 100.0 * (h2 - base) / base))
        assert cruise == out[0][2], (
            "projection %.4f moved the cruise-share command count %d -> %d"
            % (cost, out[0][2], cruise))
    assert out[0][2] > 100, "the fixture no longer commands the cruise share"


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ═════════════════════════════════════════════════════════════════════════
# THE STATIC-LOSS MAP IN THE PLANNER'S DEMAND PORT (2026-09-02)
# ═════════════════════════════════════════════════════════════════════════
def test_mpc_build_demand_defaults_to_the_loss_map_free_era():
    import inspect
    assert inspect.signature(M.build_demand).parameters["loss_map"].default \
        is None


def test_mpc_build_demand_reproduces_the_generators_map_solve():
    """The scalar port must reproduce the numpy original in the loss-map era
    too, or the planner predicts on a demand the bound was not solved for."""
    gen = pytest.importorskip("gen_dp_ems_table")
    np = pytest.importorskip("numpy")
    meta = sim.SCENARIOS[SCEN]
    dt = 0.5
    n = int(round(float(meta["duration_s"]) / dt))
    times = [k * dt for k in range(n + 1)]
    lm = sim.plant_loss_map()
    g_out = gen.build_demand(SCEN, meta, np.asarray(times), dt, loss_map=lm)
    m_out = M.build_demand(SCEN, meta, times, dt, loss_map=lm)
    for k in range(n + 1):
        assert float(g_out[2][k]) == pytest.approx(float(m_out[2][k]),
                                                   rel=1e-12, abs=1e-15)
        assert float(g_out[3][k]) == pytest.approx(float(m_out[3][k]),
                                                   rel=1e-12, abs=1e-15)


def test_mpc_strategy_carries_the_map_into_its_preview_and_its_provenance():
    s = M.MpcStrategy(name="mpc-det", variant="det",
                      loss_map=sim.plant_loss_map())
    assert s.loss_map == sim.plant_loss_map()
    s.bind_scenario(SCEN, sim.SCENARIOS[SCEN])
    base = M.MpcStrategy(name="mpc-det", variant="det")
    base.bind_scenario(SCEN, sim.SCENARIOS[SCEN])
    assert base.loss_map is None
    mean_map = sum(s.preview.v_bus) / len(s.preview.v_bus)
    mean_old = sum(base.preview.v_bus) / len(base.preview.v_bus)
    assert mean_map < mean_old
    # The map is recorded in the strategy's provenance block, so a sidecar
    # names the demand era the planner actually predicted on.
    assert s.provenance["loss_map"] == sim.plant_loss_map()
    assert base.provenance["loss_map"] is None


def test_a_scenario_may_bind_the_demand_era(monkeypatch):
    """`mpc_loss_map` binds the era the way `mpc_soc_ref_offset` binds the
    reference, and an ABSENT key must leave an ad-hoc run's constructor value
    alone."""
    lm = sim.plant_loss_map()
    meta = dict(sim.SCENARIOS[SCEN])
    meta["mpc_loss_map"] = lm
    s = M.MpcStrategy(name="mpc-det", variant="det")
    s.bind_scenario(SCEN, meta)
    assert s.loss_map == lm
    s2 = M.MpcStrategy(name="mpc-det", variant="det", loss_map=lm)
    s2.bind_scenario(SCEN, sim.SCENARIOS[SCEN])
    assert s2.loss_map == lm


# ═════════════════════════════════════════════════════════════════════════
# THE BRAKING CREDIT IN THE PLANNER'S PREDICTION MODEL (2026-09-02, ftp75c)
#
# The planner's model and the bound it is scored against must carry the SAME
# credit, or the MPC systematically under-values coasting relative to a DP that
# priced it.  The demand-port equality itself is asserted in
# `test_ems_walk.py`'s lockstep test (both eras, random preview grids); what is
# covered here is the MPC-side plumbing: the preview column, the stage
# precompute, the rollout integrator, and the provenance the sidecar records.
# ═════════════════════════════════════════════════════════════════════════
_FTP75C = "ems-ftp75c-mpc"


def test_mpc_build_demand_defaults_to_the_pre_regen_era():
    import inspect
    sig = inspect.signature(M.build_demand).parameters
    assert sig["drag_mode"].default is None
    assert sig["eta_regen"].default is None
    assert sig["v_pack_ref"].default is None
    assert sig["regen_i_max_a"].default is None


def test_mpc_build_demand_returns_the_seventh_element_and_zeroes_it_old_era():
    meta = _meta()
    dt = M.PREVIEW_DT_S
    n = int(round(float(meta["duration_s"]) / dt)) + 1
    times = [k * dt for k in range(n)]
    out = M.build_demand(SCEN, meta, times, dt)
    assert len(out) == 7
    assert not any(out[6])
    assert len(out[6]) == n


def test_mpc_build_demand_refuses_the_new_era_without_its_two_references():
    """Same refusal as the numpy original's, for the same reason: the credit's
    last stage is the Ag105's output-referred cap and the reference pack
    voltage must be a SCALAR, or the stage tables stop being a lookup."""
    meta = sim.SCENARIOS[_FTP75C]
    times = [0.5 * k for k in range(11)]
    with pytest.raises(ValueError, match="v_pack_ref"):
        M.build_demand(_FTP75C, meta, times, 0.5,
                       drag_mode=sim.DRAG_MODE_SCALED_AIR, eta_regen=0.8)


def test_bind_scenario_resolves_the_drag_profile_and_the_regen_era():
    """`--drag` OVERRIDES a scenario's own key, so the binder must resolve off
    the RUN configuration when `main()` supplies one and off the scenario key
    otherwise -- a walk and a live run then predict on the same plant.
    `eta_regen` FOLLOWS the drag profile, on the generator's rule."""
    s = M.MpcStrategy("mpc-sto")
    s.bind_scenario(_FTP75C, sim.SCENARIOS[_FTP75C])
    assert s.drag_mode == sim.DRAG_MODE_SCALED_AIR
    assert s.eta_regen == pytest.approx(float(sim.ETA_REGEN))
    # A rig-drag override of the same scenario drops the credit with it.
    s2 = M.MpcStrategy("mpc-sto")
    s2.bind_scenario(_FTP75C, sim.SCENARIOS[_FTP75C],
                     drag_mode=sim.DRAG_MODE_RIG)
    assert s2.drag_mode == sim.DRAG_MODE_RIG
    assert s2.eta_regen is None
    # And a scenario that declares nothing stays in the pre-round configuration.
    s3 = _bound()
    assert s3.drag_mode == sim.DRAG_MODE_RIG
    assert s3.eta_regen is None


def test_the_preview_carries_a_non_empty_credit_column_on_a_compensated_leg():
    s = M.MpcStrategy("mpc-sto")
    s.bind_scenario(_FTP75C, sim.SCENARIOS[_FTP75C])
    assert len(s.preview.i_regen) == len(s.preview.times)
    assert max(s.preview.i_regen) > 0.0
    # EXCLUSIVITY holds on the preview's own two masks, which is what the
    # planner enumerates over.
    for k, ok in enumerate(s.preview.chg_ok):
        assert not (ok and s.preview.i_regen[k] > 0.0), k
    # ... and a pre-regen preview's column is all zeros rather than absent, so
    # every consumer indexes it the same way.
    base = _bound()
    assert len(base.preview.i_regen) == len(base.preview.times)
    assert not any(base.preview.i_regen)


def test_the_stage_precompute_averages_the_credit_over_its_substeps():
    """`StagePrecompute.i_regen_mean` is a per-stage MEAN, not a sample: the
    decision grid is coarser than the preview grid, and a braking window that
    covers part of a stage must be credited for that part."""
    s = M.MpcStrategy("mpc-sto")
    s.bind_scenario(_FTP75C, sim.SCENARIOS[_FTP75C])
    prev = s.preview
    # A decision stage covering the middle of the first commanded window.
    k0 = prev.index(sim.FTP75C_REGEN_WINDOWS[0][0])
    pre = M.precompute_stages(prev, k0, s.planner.horizon, s.planner.dt_dec,
                              mode_seed=M.STAGE_OPEN, chg_seed=None) \
        if hasattr(M, "precompute_stages") else None
    if pre is None:                      # helper is private in this build
        pytest.skip("precompute_stages is not exposed under this name")
    n_sub = int(round(s.planner.dt_dec / prev.dt))
    assert len(pre.i_regen_mean) == s.planner.horizon
    for j, mean in enumerate(pre.i_regen_mean):
        want = sum(prev.i_regen[min(len(prev.i_regen) - 1, k0 + j * n_sub + t)]
                   for t in range(n_sub)) / n_sub
        assert mean == pytest.approx(want, rel=1e-12, abs=1e-18)
    assert max(pre.i_regen_mean) > 0.0


def test_the_credit_is_share_independent_in_the_rollout():
    """Its share-independence is what keeps it OUT of the candidate comparison
    entirely -- every candidate gains the same SoC on a braking stage -- so the
    search cannot "choose" to regenerate.  Asserted structurally on the
    rollout's own source: the credit enters BOTH transitions and is read from
    the stage, never from the control index."""
    src = open(os.path.join(HERE, "mpc_ems.py"), encoding="utf-8").read()
    i = src.index("def _rollout")
    body = src[i:i + 8000]
    assert "pre.i_regen_mean[stage]" in body
    assert "soc = soc + (self.chg_a + reg) * self.dt_dec / self.cap_as" in body
    assert "soc = soc + (reg - i_pack) * self.dt_dec / self.cap_as" in body


def test_the_provenance_records_both_new_era_keys():
    """`config.mpc` is the sidecar's only record of what the planner PREDICTED
    ON, and `eta_regen` in particular is invisible to the fingerprint -- no
    live scenario declares one."""
    s = M.MpcStrategy("mpc-sto")
    prov = s.bind_scenario(_FTP75C, sim.SCENARIOS[_FTP75C])
    assert prov["drag"] == sim.DRAG_MODE_SCALED_AIR
    assert prov["eta_regen"] == pytest.approx(float(sim.ETA_REGEN))
    base = M.MpcStrategy("mpc-det")
    prov2 = base.bind_scenario(SCEN, _meta())
    assert prov2["drag"] == sim.DRAG_MODE_RIG
    assert prov2["eta_regen"] is None


def test_the_single_source_bus_law_is_the_two_source_law_scaled():
    """THE MEASURED SINGLE-SOURCE TOPOLOGY (2026-09-02, the MPC 0/1 round).

    The fitted bus law is TWO-SOURCE: its `g_par` is the parallel droop code
    `g_fc*g_bt/(g_fc+g_bt)`, which does not exist with one channel off the bus.
    Probing the hi-fi engine at three droop codes showed the single-source
    slope is the two-source slope times a constant, stable to 0.03 % over a
    factor-of-two code range, with its own no-load intercept.

    ⚠️ THE TWO RATIOS ARE NOT BOTH 2.000, and that is the asymmetry rather
    than noise: under `--asymmetry measured` the channels differ, and using a
    nominal 2.0 for both would misprice the BT-only arm by 2.9 %."""
    lm = sim.plant_loss_map()
    v0_b, k_b = sim.single_source_bus_law(lm, "both")
    v0_f, k_f = sim.single_source_bus_law(lm, "fc")
    v0_t, k_t = sim.single_source_bus_law(lm, "bt")
    # "both" is the map's own law, untouched -- so a caller that never plans a
    # single-source stage is bit-identical to one predating the function.
    assert v0_b == lm["v0_eff"]
    assert k_b == pytest.approx(lm["r_fix"] + lm["k_g"] * lm["g_par"])
    # The measured ratios and intercepts.
    assert k_f / k_b == pytest.approx(1.9453, rel=1e-9)
    assert k_t / k_b == pytest.approx(2.0579, rel=1e-9)
    assert v0_f == pytest.approx(15.87821)
    assert v0_t == pytest.approx(15.86468)
    # Single-source droops HARDER than two-source, which is the whole point.
    assert k_f > k_b and k_t > k_b
    with pytest.raises(ValueError):
        sim.single_source_bus_law(lm, "neither")


def test_the_demand_port_selects_the_single_source_bus_law():
    """`source_mode` reaches the DEMAND, not just the constants.

    Asserted through the bus voltage, because that is the quantity the law
    sets and the one a mis-selected law would silently over-state: on the 61 s
    cycle's peak the two-source law reads ~15.42 V and the single-source laws
    ~14.99 V (FC) and ~14.92 V (BT).  A `source_mode` that did not reach
    `build_demand()` would leave all three identical."""
    meta = _meta()
    lm = sim.plant_loss_map()
    dt = 1.0
    times = [k * dt for k in range(int(float(meta["duration_s"]) / dt) + 1)]
    out = {}
    for mode in ("both", "fc", "bt"):
        o = M.build_demand(SCEN, meta, times, dt, loss_map=lm,
                           source_mode=mode)
        out[mode] = min(o[3])
    assert out["both"] > out["fc"] > out["bt"]
    assert out["both"] - out["fc"] == pytest.approx(0.428, abs=0.02)
    # DEFAULT IS "both", so every pre-round caller is unchanged.
    o = M.build_demand(SCEN, meta, times, dt, loss_map=lm)
    assert min(o[3]) == out["both"]


# ═════════════════════════════════════════════════════════════════════════════
# THE SINGLE-SOURCE (0/1) CANDIDATES (2026-09-03, the operator ruling)
#
# The ruling names the MECHANISM, not just the feature: "let's do the
# rollout-time test".  So the first tests below are about the ROLL - that the
# firmware's 0.5 A share-cut load guard is evaluated on the PATH, that a doomed
# channel over the guard is refused and one under it is accepted, and that the
# state guards suppress the candidate outright.  The rest pin the enumeration's
# shape, the byte-identity of a feature-off run, and the census.
# ═════════════════════════════════════════════════════════════════════════════
def _ss_bound(**kw):
    """A single-source-armed strategy on the `ems-soc-band` stimulus."""
    kw.setdefault("loss_map", sim.plant_loss_map())
    kw.setdefault("single_source", True)
    return _bound(**kw)


def test_single_source_needs_a_loss_map_and_says_so():
    """REFUSED, not degraded.  The measured single-source bus law is a SCALING
    of the loss map and has no loss-map-free form, so binding without one would
    silently bill a latched stage on the two-source law - which under-states the
    bus sag by ~0.45 V at the 61 s cycle's peak."""
    s = M.MpcStrategy("mpc-det", single_source=True)
    with pytest.raises(ValueError) as exc:
        s.bind_scenario(SCEN, _meta())
    assert "loss" in str(exc.value).lower()


def test_the_ladder_grows_by_exactly_two_columns_and_the_band_does_not():
    """The two columns are APPENDED, so every in-band index keeps its meaning -
    which is what lets the roll table, the coarsening and every pre-round caller
    go on using the indices they used."""
    off = _bound(loss_map=sim.plant_loss_map())
    on = _ss_bound()
    assert off.planner.ladder == on.planner.ladder[:off.planner.n_band]
    assert on.planner.n_band == off.planner.n_band == off.share_levels
    assert len(on.planner.ladder) == on.planner.n_band + 2
    assert on.planner.ladder[on.planner.ss_index[M.SS_MODE_BT]] == 0.0
    assert on.planner.ladder[on.planner.ss_index[M.SS_MODE_FC]] == 1.0
    assert off.planner.ss_index == {}


def _admit_fixture(strategy, i_fc_a, i_bt_a):
    """Seed the shadow governor so the FC channel carries exactly ``i_fc_a``.

    The load guard reads the DELIVERED split at the instant of the cut, so the
    fixture sets the applied ratio and pins the preview totals to make that
    split the number the test names."""
    tot = i_fc_a + i_bt_a
    st = strategy.shadow.model.state
    st.sw_fc = st.sw_bt = True
    st.sw_init = True
    st.r_prev = i_fc_a / tot
    st.closed_loop_mode = True
    st.closed_loop_run = True
    st.filt_total = tot
    prev = strategy.preview
    pre = M.precompute_stages(prev, 0, strategy.horizon)
    pre_ss = {m: M.precompute_stages(strategy.preview_ss[m], 0,
                                     strategy.horizon)
              for m in strategy.preview_ss}
    for j in range(pre.n):
        for s_i in range(len(pre.i_tot[j])):
            pre.i_tot[j][s_i] = tot
        pre.i_tot_mean[j] = tot
        for m in pre_ss:
            for s_i in range(len(pre_ss[m].i_tot[j])):
                pre_ss[m].i_tot[j][s_i] = tot
            pre_ss[m].i_tot_mean[j] = tot
    return pre, pre_ss


def test_the_load_guard_delays_a_cut_of_a_channel_carrying_0_6_a():
    """THE RULING'S OWN TEST, and its answer is NOT the one a static rule gives.

    `updateShareSetpointCutoff()` cuts the doomed channel only while
    `abs(i) <= SHARE_CUT_MAX_HANDOFF_A` 0.5 A, and that current is a property of
    the PATH.  The only thing that differs between this test and its twin is the
    doomed channel's current, 0.6 A against 0.4 A, across the firmware's own
    0.5 A guard.

    ⚠️ WHAT THE ROLL FINDS, and what a table test could not: at 0.6 A the guard
    refuses the FIRST tick and the firmware's own DEFERRAL then clips the
    closed-loop reference back into [DROOP_R_MIN, DROOP_R_MAX], which walks the
    fuel-cell current DOWN until the guard admits.  The cut therefore happens -
    17 ticks later.  A conservative table test (resolution 1 of the design
    record) would have refused this candidate outright; the rollout-time test
    says it is feasible and says what it costs."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.6, 0.4)
    ok, reason, ticks, _ms = s._ss_admissible(M.SS_MODE_BT, 0.0, pre, pre_ss)
    assert ok is True and reason is None
    assert ticks > 1                     # the first tick WAS refused
    assert ticks <= 40                   # and the deferral cleared it promptly


def test_the_load_guard_accepts_a_cut_of_a_channel_carrying_0_4_a():
    """The twin.  Under the guard the cut fires on the FIRST tick, which is what
    makes the pair a discrimination rather than two spellings of the same
    verdict."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.4, 0.6)
    ok, reason, ticks, _ms = s._ss_admissible(M.SS_MODE_BT, 0.0, pre, pre_ss)
    assert ok is True
    assert reason is None
    assert ticks == 1


def test_a_cut_that_cannot_engage_inside_the_window_is_refused_on_load(
        monkeypatch):
    """The REFUSAL path, reached by shortening the admission window.

    ⚠️ A FINDING, recorded rather than papered over: inside the OVERCURRENT-
    admissible region the load guard can never refuse a single-source cut
    PERMANENTLY.  The deferral's band clip floors the doomed channel at
    `DROOP_R_MIN * I_tot`, which exceeds the 0.5 A guard only above 3.33 A of
    total - and both survivor bounds (1.19 A fuel cell, 2.55 A battery) refuse
    the candidate long before that.  So `SS_REFUSE_CUT_LOAD` is a DEFENSIVE
    path, and the honest way to exercise it is to shorten the window until the
    17-tick cut of the test above no longer fits."""
    monkeypatch.setattr(M, "SS_ADMIT_MAX_TICKS", 5)
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.6, 0.4)
    ok, reason, ticks, _ms = s._ss_admissible(M.SS_MODE_BT, 0.0, pre, pre_ss)
    assert ok is False
    assert reason == M.SS_REFUSE_CUT_LOAD
    assert ticks == 5


def test_the_admissibility_roll_does_not_disturb_the_committed_shadow():
    """It runs on a COPY.  A test that only checked the verdict would pass on an
    implementation that latched the real shadow governor while asking."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.4, 0.6)
    keys = ("sp_cut_fc", "sp_cut_bt", "sw_fc", "sw_bt", "r_prev", "ticks")
    before = tuple(getattr(s.shadow.model.state, k) for k in keys)
    s._ss_admissible(M.SS_MODE_BT, 0.0, pre, pre_ss)
    after = tuple(getattr(s.shadow.model.state, k) for k in keys)
    assert before == after


def test_a_single_source_candidate_over_the_survivors_limit_is_refused():
    """CONDITION 1: the survivor carries `i_total`, not a share of it.  FC-only
    is bounded at 0.85 x LIMIT_I_FC_MAX = 1.19 A, so a 1.5 A total refuses it
    while BT-only (2.55 A) is still admissible at the same load."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.4, 1.1)          # 1.5 A total
    ok, reason, _t, _m = s._ss_admissible(M.SS_MODE_FC, 0.0, pre, pre_ss)
    assert ok is False and reason == M.SS_REFUSE_OC
    ok2, reason2, _t2, _m2 = s._ss_admissible(M.SS_MODE_BT, 0.0, pre, pre_ss)
    assert ok2 is True and reason2 is None


def test_the_restore_stage_is_judged_against_the_survivors_own_bound():
    """CONDITION 2.  The RELEASE arm of `updateShareSetpointCutoff()` carries no
    load guard - only the charged-bus condition - so there is nothing
    path-dependent to roll there.  What CAN still bite is the survivor carrying
    the whole load through the restored channel's 30 ms blanking, and that is
    what this condition checks: block 0 under the bound, the first restore stage
    over it."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.4, 0.4)          # 0.8 A: FC-only is fine
    n0 = s.planner.blocks[0]
    for s_i in range(len(pre_ss[M.SS_MODE_FC].i_tot[n0])):
        pre_ss[M.SS_MODE_FC].i_tot[n0][s_i] = 2.0      # over 1.19 A
    ok, reason, _t, _m = s._ss_admissible(M.SS_MODE_FC, 0.0, pre, pre_ss)
    assert ok is False and reason == M.SS_REFUSE_RESTORE


@pytest.mark.parametrize("fb_extra,charge,expect", [
    ({"regen_commanded": True}, False, M.SS_REFUSE_REGEN),
    ({}, True, M.SS_REFUSE_CHARGE),
])
def test_the_state_guards_suppress_the_candidate_outright(fb_extra, charge,
                                                          expect):
    """The regen and FC-charge guards, each counted TWICE (both modes refused)
    and each named in the census.  A regen window and a charge window are both
    topologies somebody else already owns."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.4, 0.6)
    opts = [[False] * pre.n]
    if charge:
        opts.append([True] + [False] * (pre.n - 1))
    fb = dict({"soc": 0.7}, **fb_extra)
    assert s._ss_state_guards_pass(fb, opts) is False
    assert s.ss_refusals.get(expect) == 2


def test_a_standing_latch_and_a_deferred_cut_both_suppress_the_candidate():
    """The other two state guards.  A deferred cut means the load guard is
    ALREADY refusing a handoff the firmware wants, so commanding a second one is
    the leak the fw v6 deferral exists to prevent; a standing latch means the
    decision has already been made."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.4, 0.6)
    opts = [[False] * pre.n]
    s.shadow.model.state.deferred_fc = True
    assert s._ss_state_guards_pass({"soc": 0.7}, opts) is False
    assert s.ss_refusals.get(M.SS_REFUSE_DEFERRED) == 2
    s.shadow.model.state.deferred_fc = False
    s.shadow.model.state.sp_cut_bt = True
    assert s._ss_state_guards_pass({"soc": 0.7}, opts) is False
    assert s.ss_refusals.get(M.SS_REFUSE_LATCHED) == 2
    # ... and with the state clear the cheap guards pass and the ROLL decides.
    s.shadow.model.state.sp_cut_bt = False
    assert s._ss_state_guards_pass({"soc": 0.7}, opts) is True
    assert s._ss_modes(0.0, pre, pre_ss) == (M.SS_MODE_BT, M.SS_MODE_FC)


def test_the_single_source_columns_are_offered_at_block_zero_only():
    """THE SCOPING DEVIATION, pinned.  The rollout-time test is a fact about the
    CURRENT governor state, so a single-source value is admissible for the
    committed block and for nothing else; blocks 1 and 2 walk the in-band
    ladder.  Checked on the enumeration itself rather than on a comment."""
    s = _ss_bound()
    p = s.planner
    band = tuple(range(p.n_band))
    ss = tuple(p.ss_index[m] for m in (M.SS_MODE_BT, M.SS_MODE_FC))
    order = p._enumeration_order(band, len(p.blocks), cols0=band + ss)
    assert len(order) == (p.n_band + 2) * p.n_band * p.n_band
    assert any(c[0] in ss for c in order)
    assert not any(c[1] in ss or c[2] in ss for c in order)


def test_the_delivery_table_refuses_a_single_source_column_without_its_demand():
    """A LOUD refusal, not a fallback to the two-source arrays.  Substituting
    them is exactly the mis-billing the `pre_ss` argument exists to prevent."""
    s = _ss_bound()
    pre, _pre_ss = _admit_fixture(s, 0.4, 0.6)
    with pytest.raises(ValueError) as exc:
        s.planner.delivery_table(pre, {}, 0.5, [False] * pre.n,
                                 active=(0, s.planner.ss_index[M.SS_MODE_BT]))
    assert "single-source" in str(exc.value)


def test_a_single_source_column_delivers_a_rail_and_bills_the_single_law():
    """The column's three defining properties in one place: the delivered share
    is EXACTLY a rail (the latch freezes the whole share loop, so neither the
    minority clip nor the fw v26 ceiling can move it), the power is billed on
    the SINGLE-SOURCE demand, and a charge stage is infeasible."""
    s = _ss_bound()
    pre, pre_ss = _admit_fixture(s, 0.4, 0.6)
    si_bt = s.planner.ss_index[M.SS_MODE_BT]
    si_fc = s.planner.ss_index[M.SS_MODE_FC]
    d, pfc, pbt, _ok, _v = s.planner.delivery_table(
        pre, {}, 0.5, [False] * pre.n, active=(0, si_bt, si_fc),
        pre_ss=pre_ss)
    assert d[0][si_bt] == 0.0 and d[0][si_fc] == 1.0
    assert pfc[0][si_bt] == 0.0
    assert pbt[0][si_fc] == 0.0
    assert pfc[0][si_fc] == pytest.approx(pre_ss[M.SS_MODE_FC].p_dem_mean[0])
    assert pbt[0][si_bt] == pytest.approx(pre_ss[M.SS_MODE_BT].p_dem_mean[0])
    _d2, _f2, _b2, ok2, _v2 = s.planner.delivery_table(
        pre, {}, 0.5, [True] + [False] * (pre.n - 1), active=(0, si_bt),
        pre_ss=pre_ss)
    assert ok2[0][si_bt] is False


def test_the_shadow_governor_lets_the_latch_own_the_switches_only_at_0_or_1():
    """The switch-ownership predicate, and its INERTNESS in band.  Asserting the
    switches HIGH every tick while a latch stands would trip the S1 self-heal
    and erase the latch; doing it for an IN-BAND command would change every
    pre-2026-09-03 run."""
    s = _ss_bound()
    fb = {"I_fc": 0.4, "I_batt": 0.4}
    s.shadow.last_t = 0.0
    s.shadow.model.state.sw_init = True
    s.shadow.model.state.sw_fc = True
    s.shadow.model.state.sw_bt = True
    s.shadow.tick_to(0.05, 0.0, fb)                  # single-source command
    assert s.shadow.sp_cut == "fc"                   # the FC is off the bus
    s.shadow.tick_to(0.10, 0.0, fb)
    assert s.shadow.sp_cut == "fc"                   # and it SURVIVES
    s2 = _ss_bound()
    s2.shadow.last_t = 0.0
    s2.shadow.model.state.sw_init = True
    s2.shadow.model.state.sw_fc = True
    s2.shadow.model.state.sw_bt = True
    s2.shadow.tick_to(0.05, 0.5, fb)
    assert s2.shadow.sp_cut is None
    assert s2.shadow.model.state.sw_fc and s2.shadow.model.state.sw_bt


def _drive_61s(**kw):
    """Command sequence over the whole 61 s stimulus, as a list of floats."""
    s = _bound(loss_map=sim.plant_loss_map(), budget_ms=1e5,
               roll_budget_ms=1e5, **kw)
    prev = s.preview
    out = []
    t = 0.0
    while t < 61.0:
        k = prev.index(t)
        i_tot = prev.i_total[k]
        r = s(t, {"soc": 0.7, "I_fc": 0.5 * i_tot, "I_batt": 0.5 * i_tot,
                  "V_bus": prev.v_bus[k], "I_charge": 0.0, "v_profile": 1.5})
        out.append(r["power_share_setpoint"])
        t += 0.02
    return out


def test_the_feature_off_plan_is_byte_identical():
    """THE INERTNESS GATE.  A strategy with the feature off must produce the
    SAME command sequence it produced before the round, so every Gate-1/Gate-2
    record and every campaign anchor stays comparable."""
    assert _drive_61s() == _drive_61s(single_source=False)


def test_the_armed_strategy_is_a_different_controller():
    """The mutation the test above cannot see: a feature that never ran would
    satisfy the equality and prove nothing."""
    assert _drive_61s(single_source=True) != _drive_61s()


def test_the_stochastic_forecast_reaches_the_single_source_demand_too():
    """One decision must not sit on TWO demand forecasts.

    `mpc-sto` replaces the previewed demand with the TPM's conditional mean by
    scaling `pre` in place.  If that scale did not also reach the single-source
    precomputes, the survivor's overcurrent condition would be judged on the
    DETERMINISTIC preview while the two-source table was judged on the forecast
    — a silent inconsistency inside one decision.  Asserted by driving a `sto`
    strategy and comparing the single-source stage means against the two-source
    ones through the FIXED bus-law ratio, which is the only thing that may
    differ between them."""
    if not os.path.exists(TPM_PATH):
        pytest.skip("the demand TPM is not present in this checkout")
    s = M.MpcStrategy("mpc-sto", variant="sto", loss_map=sim.plant_loss_map(),
                      single_source=True, budget_ms=1e5, roll_budget_ms=1e5)
    s.bind_scenario(SCEN, _meta())
    seen = {}

    orig = M.MpcStrategy._ss_modes

    def spy(self, t, pre, pre_ss, i_tot_oc=None):
        seen.setdefault("pre", pre)
        seen.setdefault("pre_ss", pre_ss)
        # `i_tot_oc` (2026-09-03, review LOW-2): the quantile tightening now
        # reaches the admissibility test too, so the spy has to carry it or the
        # sto arm is judged on a demand the shipped code does not use.
        seen.setdefault("i_tot_oc", i_tot_oc)
        return orig(self, t, pre, pre_ss, i_tot_oc=i_tot_oc)

    s._ss_modes = spy.__get__(s, M.MpcStrategy)
    prev = s.preview
    t = 0.0
    while t < 30.0 and "pre" not in seen:
        k = prev.index(t)
        i_tot = prev.i_total[k]
        s(t, {"soc": 0.7, "I_fc": 0.5 * i_tot, "I_batt": 0.5 * i_tot,
              "V_bus": prev.v_bus[k], "I_charge": 0.0, "v_profile": 1.5})
        t += 0.02
    assert "pre" in seen, "no decision reached the single-source path"
    pre, pre_ss = seen["pre"], seen["pre_ss"]
    # The two-source and single-source previews differ ONLY in the bus law, so
    # the ratio of their stage-mean BUS POWERS is fixed by the profile and does
    # NOT move with the forecast. Comparing it against the same ratio taken
    # from the UNSCALED previews is what detects a scale applied to one arm and
    # not the other.
    base = {m: M.precompute_stages(s.preview_ss[m], 0, s.horizon)
            for m in s.preview_ss}
    base2 = M.precompute_stages(s.preview, 0, s.horizon)
    moved = False
    for j in range(pre.n):
        if abs(pre.p_dem_mean[j] - base2.p_dem_mean[j]) > 1e-12:
            moved = True
        for m in pre_ss:
            got = pre_ss[m].p_dem_mean[j] / pre.p_dem_mean[j]
            want = base[m].p_dem_mean[j] / base2.p_dem_mean[j]
            assert got == pytest.approx(want, rel=1e-9), (m, j)
    assert moved, "the forecast never moved the demand - the test proved nothing"
    # ...and the OVERCURRENT arm of the same decision got the quantile, not the
    # mean - the two arms of one decision on one forecast (review LOW-2).
    assert seen["i_tot_oc"] is not None


def test_the_census_counts_offers_admissions_and_commitments():
    """The reporting surface a campaign reads.  The summary fragment is ASCII
    (the cp1252 console rule) and is EMPTY when the feature is off."""
    off = _bound(loss_map=sim.plant_loss_map())
    assert off._ss_summary_fragment(off.timing()) == ""
    s = _bound(loss_map=sim.plant_loss_map(), single_source=True,
               budget_ms=1e5, roll_budget_ms=1e5)
    prev = s.preview
    t = 0.0
    while t < 61.0:
        k = prev.index(t)
        i_tot = prev.i_total[k]
        s(t, {"soc": 0.7, "I_fc": 0.5 * i_tot, "I_batt": 0.5 * i_tot,
              "V_bus": prev.v_bus[k], "I_charge": 0.0, "v_profile": 1.5})
        t += 0.02
    tm = s.timing()
    assert tm["single_source"] is True
    assert tm["ss_offered"] > 0
    # Every offer is accounted for: admitted, or refused with a named reason.
    assert tm["ss_offered"] == tm["ss_admissible"] + sum(
        tm["ss_refusals"].values())
    frag = s._ss_summary_fragment(tm)
    assert "single-source 0/1 candidates ARMED" in frag
    frag.encode("cp1252")               # the console rule, asserted
    assert s.provenance["single_source"] is True
    assert s.provenance["single_source_cut_guard_a"] == \
        gm.GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]


# =============================================================================
# 20. The 2026-09-03 review fix round.  One discriminating test per finding;
#     each names the finding it pins so a future edit that reverts the fix
#     fails with the reason attached.
# =============================================================================
def test_the_incumbent_seed_snaps_by_share_not_by_index():
    """MED-1.  The single-source columns are APPENDED, so index distance is not
    share distance for them.  Before the fix, an incumbent at the BT-only column
    (index `n_band`, share 0.0) snapped to index `n_band - 1` - share 0.85, the
    OPPOSITE rail - and a budget expiry committed that as the warm start."""
    pl = M.Planner(horizon=20, blocks=(2, 6, 12), share_levels=9,
                   single_source=True)
    n = pl.n_band
    assert pl.ladder[pl.ss_index[M.SS_MODE_BT]] == 0.0
    assert pl.ladder[pl.ss_index[M.SS_MODE_FC]] == 1.0
    cols = tuple(range(n))              # the in-band ladder, no ss columns
    # BT-only incumbent (share 0.0) -> the LOW rail, 0.15.
    pl.incumbent = (pl.ss_index[M.SS_MODE_BT],) * 3
    seed = pl._enumeration_order(cols, 3)[0]
    assert pl.ladder[seed[0]] == pytest.approx(0.15)
    assert seed[0] == 0
    # FC-only incumbent (share 1.0) -> the HIGH rail, 0.85.
    pl._order_cache.clear()
    pl.incumbent = (pl.ss_index[M.SS_MODE_FC],) * 3
    seed = pl._enumeration_order(cols, 3)[0]
    assert pl.ladder[seed[0]] == pytest.approx(0.85)
    assert seed[0] == n - 1
    # The pre-round behaviour is untouched: an in-band incumbent inside the
    # active set still snaps to ITSELF, on both metrics.
    for x in range(n):
        pl._order_cache.clear()
        pl.incumbent = (x,) * 3
        assert pl._enumeration_order(cols, 3)[0][0] == x


def test_the_seed_snap_is_index_distance_for_an_out_of_range_incumbent():
    """The fallback arm of `_snap_seed()`: an incumbent index the ladder no
    longer has (a caller whose ladder shrank between decisions) has no share to
    compare, so index distance is the only metric left."""
    pl = M.Planner(horizon=20, blocks=(2, 6, 12), share_levels=9)
    assert pl._snap_seed(99, tuple(range(pl.n_band))) == pl.n_band - 1
    assert pl._snap_seed(-4, tuple(range(pl.n_band))) == 0


# The command sequence a feature-OFF strategy produces over the whole 61 s
# stimulus, as a sha256 over the little-endian float64 encoding of all 3050
# values.  COMPUTED FROM d941170's `mpc_ems.py` - the commit before the
# single-source round - and re-checked against this worktree, so it pins the
# inertness claim against the module as it was, not against itself (MED-4).
_FEATURE_OFF_SEQ_SHA256 = (
    "412c282009c3c84eb4fca1d55bee61cc072465e3461e6f27524ed402b8f7202d")
_FEATURE_OFF_SEQ_LEN = 3050


def _seq_sha256(seq):
    import hashlib
    import struct
    return hashlib.sha256(
        b"".join(struct.pack("<d", float(v)) for v in seq)).hexdigest()


def test_the_feature_off_plan_matches_the_pre_round_fixture():
    """MED-4.  `test_the_feature_off_plan_is_byte_identical()` compares the new
    module WITH ITSELF, so a regression that moved both sides would satisfy it.
    This one compares against a sequence taken from the pre-round commit."""
    seq = _drive_61s()
    assert len(seq) == _FEATURE_OFF_SEQ_LEN
    assert _seq_sha256(seq) == _FEATURE_OFF_SEQ_SHA256


def test_the_regen_guard_reads_the_observed_switch_bit():
    """MED-3.  `regen_commanded` is a HOST key written by a scenario's
    `RegenManager`; `ems-mpc-single` has none, so before the fix the guard was
    inert on the one leg that ships the feature.  The observed `switch` word
    carries `SW_REGEN` whoever opened the path."""
    s = _bound(loss_map=sim.plant_loss_map(), single_source=True,
               budget_ms=1e5, roll_budget_ms=1e5)
    opts = [[False] * s.horizon]
    # NO host key, REGEN observed open -> refused, and counted as a regen
    # refusal rather than as something else.
    assert s._ss_state_guards_pass({"switch": M.SW_REGEN_BIT}, opts) is False
    assert s.ss_refusals.get(M.SS_REFUSE_REGEN) == 2
    # Another switch bit is NOT the regen bit.
    s.reset()
    assert s._ss_state_guards_pass({"switch": sim.SW_MOT_PWR}, opts) is True
    assert M.SS_REFUSE_REGEN not in s.ss_refusals
    # A missing `switch` (no observation frame yet) degrades to the host key.
    s.reset()
    assert s._ss_state_guards_pass({}, opts) is True


def test_the_regen_switch_mask_is_the_simulators_own():
    """The mask is restated in `mpc_ems` to keep the runtime path stdlib-only,
    so it needs a test that the two cannot drift."""
    assert M.SW_REGEN_BIT == sim.SW_REGEN


def _const_pre(n, i_tot, nsub=10):
    """A stage precompute of CONSTANT current - enough for `_ss_admissible()`,
    which reads only `n`, `i_tot` and `i_tot_mean`."""
    class _P:
        pass
    p = _P()
    p.n = n
    p.i_tot = [[i_tot] * nsub for _ in range(n)]
    p.i_tot_mean = [i_tot] * n
    p.p_dem = [[0.0] * nsub for _ in range(n)]
    p.p_dem_mean = [0.0] * n
    return p


def test_the_quantile_tightening_reaches_the_admissibility_test():
    """LOW-2.  `mpc-sto` judges the single-source COLUMN on the 90 % quantile
    (`delivery_table`'s `oc_scale`) and, before the fix, judged the same
    candidate's ADMISSIBILITY on the unscaled conditional mean - so a candidate
    the table would mark infeasible could still be admitted."""
    s = _bound(loss_map=sim.plant_loss_map(), single_source=True,
               budget_ms=1e5, roll_budget_ms=1e5)
    # FC-only survives; its bound is 1.19 A. 1.00 A of mean demand is inside it.
    i_mean = 1.00
    pre = _const_pre(s.horizon, i_mean)
    pre_ss = {m: _const_pre(s.horizon, i_mean) for m in
              (M.SS_MODE_BT, M.SS_MODE_FC)}
    assert i_mean < M.SS_LIMIT_A[M.SS_MODE_FC]
    _ok, reason_plain, _t, _ms = s._ss_admissible(
        M.SS_MODE_FC, 0.0, pre, pre_ss)
    assert reason_plain != M.SS_REFUSE_OC
    # The same candidate with a quantile 1.5x the mean is over the bound.
    oc = [i_mean * 1.5] * s.horizon
    ok, reason, _t2, _ms2 = s._ss_admissible(M.SS_MODE_FC, 0.0, pre, pre_ss,
                                             i_tot_oc=oc)
    assert ok is False and reason == M.SS_REFUSE_OC
    assert i_mean * 1.5 > M.SS_LIMIT_A[M.SS_MODE_FC]


# LOW-1: what the admission roll actually costs, on a GRID.
# Measured 2026-09-03 through the shipped `_ss_admissible()` path, at the
# measured plant dv0 0.013522 V, over I_tot in [0.60, 2.55] A (0.05 A steps) x
# r0 in {0.15, 0.30, 0.50, 0.70, 0.85} x both modes.  The two figures below are
# the whole point of the window's size and are pinned so a governor change that
# lengthens the handoff fails here rather than silently in a campaign.
_SS_GRID_MAX_TICKS = 118          # at I_tot 0.75 A, r0 0.85, BT-only
_SS_GRID_TIMEOUTS = 2             # both at I_tot 0.60 A, at the two rails
_SS_GRID_DV0_V = 0.013522


def _ss_grid(factory):
    """(max engage ticks, [(i_tot, r0, mode) that timed out on the load guard])."""
    worst, timeouts = 0, []
    i_tot = 0.60
    while i_tot <= 2.5501:
        for r0 in (0.15, 0.30, 0.50, 0.70, 0.85):
            for mode in (M.SS_MODE_BT, M.SS_MODE_FC):
                s = factory()
                st = s.shadow.model.state
                st.sw_init = True
                st.sw_fc = True
                st.sw_bt = True
                st.r_prev = r0
                s.shadow.last_t = 0.0
                pre = _const_pre(s.horizon, i_tot)
                pre_ss = {m: _const_pre(s.horizon, i_tot)
                          for m in (M.SS_MODE_BT, M.SS_MODE_FC)}
                ok, reason, ticks, _ms = s._ss_admissible(mode, 0.0, pre,
                                                          pre_ss)
                if ok:
                    worst = max(worst, ticks)
                elif reason == M.SS_REFUSE_CUT_LOAD:
                    timeouts.append((round(i_tot, 3), r0, mode))
        i_tot += 0.05
    return worst, timeouts


def test_the_admission_roll_grid_maximum_and_its_margin():
    """LOW-1.  The design record's deferral table was four hand-picked points
    with a 34-tick maximum; the grid's maximum is 118 ticks, so the 200-tick
    window's margin is 1.69x, NOT the "six blanking windows" the constant's
    comment claimed.  118 ms of a 1 s stage is 11.8 % of a stage the plan
    modelled single-source and ran two-source, and the roll carries NO plant
    current lag, so 118 is a LOWER bound on what the board would take."""
    worst, timeouts = _ss_grid(
        lambda: _bound(loss_map=sim.plant_loss_map(), single_source=True,
                       budget_ms=1e5, roll_budget_ms=1e5,
                       dv0_v=_SS_GRID_DV0_V))
    assert worst == _SS_GRID_MAX_TICKS
    assert worst < M.SS_ADMIT_MAX_TICKS
    # ...and the load-guard refusal is REACHABLE, not merely defensive: at
    # I_tot 0.60 A from either rail the doomed channel parks at 0.5157 A, just
    # over the 0.5 A guard, the reference never moves, and the roll expires.
    assert len(timeouts) == _SS_GRID_TIMEOUTS
    assert all(t[0] == 0.60 for t in timeouts), timeouts


def test_the_census_reports_the_columns_the_search_walked():
    """LOW-3.  `Decision.ss_offered` was written and never read; it is now the
    census's `ss_searched`, which says an ADMITTED mode reached the planner.
    Since the share-step guard the two may legitimately differ when the guard
    removes an admitted `SS_MODE_FC` column (`share_step_refusals` > 0); on
    this stimulus the guard never fires, so equality still holds and this
    test asserts it together with that precondition. It
    actually reached the planner's block-0 column set."""
    s = _bound(loss_map=sim.plant_loss_map(), single_source=True,
               budget_ms=1e5, roll_budget_ms=1e5)
    prev = s.preview
    t = 0.0
    while t < 61.0:
        k = prev.index(t)
        i_tot = prev.i_total[k]
        s(t, {"soc": 0.7, "I_fc": 0.5 * i_tot, "I_batt": 0.5 * i_tot,
              "V_bus": prev.v_bus[k], "I_charge": 0.0, "v_profile": 1.5})
        t += 0.02
    tm = s.timing()
    assert tm.get("share_step_guard_decisions", 0) == 0
    assert tm["ss_searched"] == tm["ss_admissible"] > 0
    # OFF: the key is present and zero, so a sidecar never has to guess.
    off = _bound(loss_map=sim.plant_loss_map())
    assert off.timing()["ss_searched"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 21. The split law reaches every model this module builds (2026-09-03 fix
#     round, M1).  `dv0_v` had wiring tests; its two siblings had none, so a
#     revert of the plumbing would have been caught nowhere in this file.
# ═════════════════════════════════════════════════════════════════════════════
_PLANT_RHO = 0.9434                # hil_electrical.ASYM_DROOP_SCALE_FC
_PLANT_R_SERIES = 0.033            # hil_electrical.DROOP_FIXED_SERIES_OHM


def test_the_planner_keeps_a_map_with_the_asymmetry_off():
    """N2, ON THE PLANNER'S OWN SHORTCUT. The `_map is None` test used to key on
    `dv0_v == 0.0` alone. With the series floor in the law that predicate stops
    meaning "the map is the identity": an `--asymmetry off` run carries
    dV0 = 0.0 and rho = 1.0 but STILL realizes 0.033 ohm, and a planner that
    dropped its map there would predict alpha = r on a plant that delivers
    up to 0.0096 of share away from it.

    REVERT GUARD: with the shortcut keyed on `dv0_v` alone the FIRST assertion
    of this test fails, because that is exactly the configuration the old key
    called trivial."""
    p = M.Planner(dv0_v=0.0, r_series_ohm=_PLANT_R_SERIES)
    assert p._map is not None
    assert p._map.r_series_ohm == _PLANT_R_SERIES
    assert p._map.droop_scale_fc == 1.0
    # rho alone is enough on its own, for the same reason.
    assert M.Planner(dv0_v=0.0, droop_scale_fc=_PLANT_RHO)._map is not None
    # ...and all three trivial is the only configuration that drops the map,
    # which is what keeps every pre-2026-09-03 caller bit-identical.
    assert M.Planner()._map is None
    assert M.Planner(dv0_v=0.0, droop_scale_fc=1.0, r_series_ohm=0.0)._map \
        is None


def test_the_strategy_hands_the_split_law_to_every_model_it_builds():
    """M1: the three parameters are one law, so a model built by this strategy
    that carries only `dv0_v` predicts a plant the run does not drive. The
    shadow governor, its rollout copy and the planner are asserted TOGETHER
    because each is a separate construction site."""
    s = M.MpcStrategy("mpc-det", dv0_v=sim.ASYM_DV0_V,
                      droop_scale_fc=_PLANT_RHO,
                      r_series_ohm=_PLANT_R_SERIES)
    for name, g in (("shadow", s.shadow.model),
                    ("shadow copy", s._ss_shadow_copy())):
        assert g.dv0_v == sim.ASYM_DV0_V, name
        assert g.droop_scale_fc == _PLANT_RHO, name
        assert g.r_series_ohm == _PLANT_R_SERIES, name
        assert not g.map_is_identity(), name
    # The planner is built by bind_scenario(), which is where the run's own
    # kwargs become a search.
    s.bind_scenario(SCEN, _meta())
    assert s.planner.droop_scale_fc == _PLANT_RHO
    assert s.planner.r_series_ohm == _PLANT_R_SERIES
    assert s.planner._map is not None
    assert s.planner._map.r_series_ohm == _PLANT_R_SERIES
    # ...and the provenance records all three, so a trace planned on the
    # corrected law can be told from one planned on the law it replaced.
    prov = s._provenance()
    assert prov["dv0_v"] == sim.ASYM_DV0_V
    assert prov["droop_scale_fc"] == _PLANT_RHO
    assert prov["r_series_ohm"] == _PLANT_R_SERIES


def test_the_roll_job_hands_the_split_law_to_the_governor_it_builds():
    """M1: `RollJob._roll_begin()` builds its own `GovernorModel` per ladder
    point, so it is a construction site of its own and a dropped parameter
    there would silently make the transition rolls the only part of the plan
    computed on the wrong law."""
    prof = lambda t: 1.2 if (t < 4.0 or t >= 8.0) else 0.35
    prev = _synthetic_preview(prof, n_stages=12)
    pre = M.precompute_stages(prev, 0, 12, mode_seed=M.STAGE_CLOSED)
    ladder = [0.25 + i * 0.5 / 6.0 for i in range(7)]
    job = M.RollJob(pre, ladder, dv0_v=sim.ASYM_DV0_V,
                    droop_scale_fc=_PLANT_RHO,
                    r_series_ohm=_PLANT_R_SERIES)
    assert job.droop_scale_fc == _PLANT_RHO
    assert job.r_series_ohm == _PLANT_R_SERIES
    seen = []
    orig = M.gov_mod.GovernorModel

    def spy(*a, **kw):
        seen.append(kw)
        return orig(*a, **kw)

    M.gov_mod.GovernorModel = spy
    try:
        job.run_all()
    finally:
        M.gov_mod.GovernorModel = orig
    assert seen, "the roll built no governor"
    for kw in seen:
        assert kw["dv0_v"] == sim.ASYM_DV0_V
        assert kw["droop_scale_fc"] == _PLANT_RHO
        assert kw["r_series_ohm"] == _PLANT_R_SERIES


def test_the_probe_and_this_module_agree_on_the_split_constants():
    """The literals above are this file's copy of the plant's constants; pinned
    here so a fit that moves in `hil_electrical` fails by name rather than
    quietly re-planning against a plant nobody runs."""
    assert _PLANT_RHO == pytest.approx(
        sim.ASYM_DROOP_SCALE_FC / sim.ASYM_DROOP_SCALE_BT, abs=1e-12)
    assert _PLANT_R_SERIES == pytest.approx(sim.DROOP_FIXED_SERIES_OHM,
                                            abs=1e-12)


# ═════════════════════════════════════════════════════════════════════════════
# THE SHARE-STEP GUARD (2026-09-03, the operator ruling)
#
# The rule: no strategy may command an upward share step in the same decision
# as an upward demand step, wherever the resulting two-source total exceeds
# 1.65 A.  See `mpc_ems.SHARE_STEP_GUARD_I_TOT_A` for both derivations of the
# constant and `docs/fw26_current_ceiling_governor.md` section 8.6 for the
# hazard it names.
# ═════════════════════════════════════════════════════════════════════════════
def test_the_share_step_guard_constant_covers_both_derivations():
    """The shipped constant is the 1.65 A DESIGN figure, and it must sit at or
    above BOTH necessary conditions: the pre-2026-09-03 split law's
    LIMIT_I_FC_MAX / DROOP_R_MAX = 1.6471 A, and the corrected law's 1.645 A.
    A constant below either would engage later than the hazard requires."""
    import governor_model as gm
    old_law = M.LIMIT_I_FC_MAX_A / gm.GOV_CONST["DROOP_R_MAX"]
    assert old_law == pytest.approx(1.6471, abs=5e-4)
    assert M.SHARE_STEP_GUARD_I_TOT_A >= old_law
    # The corrected law's figure, from
    # docs/modeling/governor_split_law_20260903.md.
    assert M.SHARE_STEP_GUARD_I_TOT_A >= 1.645
    # ...and it is not so far above either that it stops being the design
    # constant the two records name.
    assert M.SHARE_STEP_GUARD_I_TOT_A == 1.65


def test_the_guard_stage_test_fires_on_a_rising_crossing_only():
    """THE THREE CASES THE RULE DISTINGUISHES, on a synthetic stage.

    `share_step_guard_stage()` is the whole "when" half of the rule, so it is
    tested as a pure function.  Rising ACROSS the guard fires; the same level
    reached while FALLING does not; and neither does a level below the guard,
    however fast it is rising."""
    g = M.SHARE_STEP_GUARD_I_TOT_A
    # (a) RISING across the guard at stage 0, measured against the total the
    #     previous decision carried.  Fires.
    pre = _const_pre(4, g + 0.35)
    assert M.Planner.share_step_guard_stage(pre, 1.20, 2) == 0
    # (b) THE SAME TOTAL, FALLING.  The level half is satisfied and the rising
    #     half is not, so the rule does not apply: a share step onto a demand
    #     that is coming DOWN cannot outrun the load filter upward.
    assert M.Planner.share_step_guard_stage(pre, g + 0.80, 2) is None
    # (c) BELOW the guard, rising hard.  The droop band itself bounds the
    #     fuel-cell demand there, which is what the necessary condition says.
    lo = _const_pre(4, 1.40)
    assert M.Planner.share_step_guard_stage(lo, 0.20, 2) is None
    # (d) THE FIRST DECISION OF A RUN has no carried total, so nothing stepped
    #     and stage 0 is not rising.
    assert M.Planner.share_step_guard_stage(pre, None, 2) is None
    # (e) The window is BLOCK 0 only: a crossing at stage 2 is outside a
    #     two-stage block-0 and is not this decision's to refuse.
    ramp = _const_pre(4, 0.0)
    ramp.i_tot_mean = [1.00, 1.20, g + 0.30, g + 0.30]
    assert M.Planner.share_step_guard_stage(ramp, 0.90, 2) is None
    assert M.Planner.share_step_guard_stage(ramp, 0.90, 4) == 2


def _pre_for_solve(s, t=10.0):
    """A real stage precompute off a bound strategy, for `solve()`."""
    k0 = s.preview.index(t)
    return M.precompute_stages(s.preview, k0, s.horizon)


def test_the_guard_refuses_upward_columns_at_block_zero_only():
    """The "what" half: with the guard armed at a committed share of 0.15, the
    committed block-0 command may not exceed it, while the LATER blocks - which
    are a receding-horizon tail and are never issued as planned - keep the whole
    ladder."""
    s = _bound(loss_map=sim.plant_loss_map(), budget_ms=1e5, roll_budget_ms=1e5)
    pre = _pre_for_solve(s)
    opts = [[False] * s.horizon]
    free = s.planner.solve(0.7, 0.7, pre, {}, 0.5, opts)
    assert free.share_step_guarded is False and free.share_step_refused == 0
    s.planner.incumbent = None
    guarded = s.planner.solve(0.7, 0.7, pre, {}, 0.5, opts,
                              share_step_guard_r=0.15)
    assert guarded.share_step_guarded is True
    assert guarded.share_step_refused == s.planner.n_band - 1
    assert guarded.share <= 0.15 + 1e-9
    # The tail is untouched: some later stage still carries a value above the
    # guarded rail, so the guard did not collapse the whole plan.
    assert max(guarded.plan_share) > 0.15
    # A DOWNWARD step is always admissible: guarding at the TOP rail refuses
    # nothing, because no column is above it.
    s.planner.incumbent = None
    down = s.planner.solve(0.7, 0.7, pre, {}, 0.5, opts,
                           share_step_guard_r=max(s.planner.ladder))
    assert down.share_step_refused == 0
    assert down.share == pytest.approx(free.share)


def test_the_guard_never_empties_the_block_zero_column_set():
    """A guard reference BELOW every rung must still leave one command, and it
    must be the LOWEST one - refusing the whole block would make the decision
    infeasible and hand the fallback a command nobody chose."""
    s = _bound(loss_map=sim.plant_loss_map(), budget_ms=1e5, roll_budget_ms=1e5)
    pre = _pre_for_solve(s)
    dec = s.planner.solve(0.7, 0.7, pre, {}, 0.5, [[False] * s.horizon],
                          share_step_guard_r=-1.0)
    assert dec.share == pytest.approx(min(s.planner.ladder[:s.planner.n_band]))
    assert dec.share_step_refused == s.planner.n_band - 1
    assert dec.feasible


def test_the_guard_catches_the_fc_single_source_column_too():
    """`SS_MODE_FC` commands share 1.0, the largest upward step available, so it
    must be inside the guard.  `SS_MODE_BT` commands 0.0 and is always
    downward, so it must survive."""
    pl = M.Planner(horizon=20, blocks=(2, 6, 12), share_levels=9,
                   single_source=True)
    assert pl.ladder[pl.ss_index[M.SS_MODE_FC]] == 1.0
    assert pl.ladder[pl.ss_index[M.SS_MODE_BT]] == 0.0
    # Judged by the same comparison every rung is judged by.
    r_ref = 0.50
    assert pl.ladder[pl.ss_index[M.SS_MODE_FC]] > r_ref
    assert pl.ladder[pl.ss_index[M.SS_MODE_BT]] <= r_ref


def test_the_guard_is_inert_on_the_registered_61_s_stimulus():
    """THE INERTNESS GATE for this round.  The largest two-source total any
    registered EMS stimulus commands is `ems-mpc`'s 1.4714 A, 10.7 % under the
    guard, so the rule must fire on ZERO decisions and refuse ZERO columns -
    which is what keeps every campaign anchor comparable.

    `test_the_feature_off_plan_matches_the_pre_round_fixture()` above is the
    other half: it pins the same stimulus's command stream, byte for byte,
    against the pre-round commit."""
    s = _bound(loss_map=sim.plant_loss_map(), budget_ms=1e5,
               roll_budget_ms=1e5)
    prev = s.preview
    t = 0.0
    i_tot_max = 0.0
    while t < 61.0:
        k = prev.index(t)
        i_tot = prev.i_total[k]
        i_tot_max = max(i_tot_max, i_tot)
        s(t, {"soc": 0.7, "I_fc": 0.5 * i_tot, "I_batt": 0.5 * i_tot,
              "V_bus": prev.v_bus[k], "I_charge": 0.0, "v_profile": 1.5})
        t += 0.02
    tm = s.timing()
    assert tm["share_step_guard_decisions"] == 0
    assert tm["share_step_refusals"] == {}
    assert i_tot_max < M.SHARE_STEP_GUARD_I_TOT_A
    assert i_tot_max == pytest.approx(1.4714, abs=5e-4)


def test_the_guard_is_not_dead_code_on_a_stimulus_that_reaches_it():
    """The mutation the inertness gate cannot see.  Lowering the constant onto
    the 61 s stimulus's own totals must make the rule FIRE and must be counted
    in both censuses."""
    s = _bound(loss_map=sim.plant_loss_map(), budget_ms=1e5,
               roll_budget_ms=1e5)
    old = M.SHARE_STEP_GUARD_I_TOT_A
    M.SHARE_STEP_GUARD_I_TOT_A = 0.50
    try:
        prev = s.preview
        t = 0.0
        while t < 20.0:
            k = prev.index(t)
            i_tot = prev.i_total[k]
            s(t, {"soc": 0.7, "I_fc": 0.5 * i_tot, "I_batt": 0.5 * i_tot,
                  "V_bus": prev.v_bus[k], "I_charge": 0.0, "v_profile": 1.5})
            t += 0.02
        tm = s.timing()
    finally:
        M.SHARE_STEP_GUARD_I_TOT_A = old
    assert tm["share_step_guard_decisions"] > 0
    assert tm["share_step_refusals"].get(M.SHARE_STEP_REFUSE_UPWARD, 0) > 0
    # The census keys are the guard's own vocabulary, not a free-form string.
    assert set(tm["share_step_refusals"]) == {M.SHARE_STEP_REFUSE_UPWARD}


def test_the_guard_census_reaches_the_sidecar_blocks():
    """OBSERVABILITY.  The constant belongs in `config.mpc` (which era a run
    planned under) and the counts in `timing()`, which `finalize_meta()`
    refreshes AFTER the run - the `regen_early_releases` lesson."""
    s = _bound(loss_map=sim.plant_loss_map(), budget_ms=1e5, roll_budget_ms=1e5)
    prov = s._provenance()
    assert prov["share_step_guard_i_tot_a"] == M.SHARE_STEP_GUARD_I_TOT_A
    # Present on the EMPTY timing block too, so a run that ended before its
    # first decision still reports the field rather than omitting it.
    empty = s.timing()
    for k in ("share_step_guard_i_tot_a", "share_step_guard_decisions",
              "share_step_refusals"):
        assert k in empty
    assert empty["decisions"] == 0
    src = open(M.__file__, encoding="utf-8").read()
    # ... and the constant is named ONCE, in its own definition.
    assert src.count("SHARE_STEP_GUARD_I_TOT_A = ") == 1
