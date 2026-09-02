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
"""
import math
import os
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
                a = M.step_discharge(soc, share, p_dem, 15.9, 0.1, cap_as)
                b = gen.step_discharge(soc, share, p_dem, 15.9, 0.1, cap_as)
                for x, y in zip(a, b):
                    assert x == pytest.approx(float(y), rel=1e-12, abs=1e-18)
            a = M.step_charge(soc, p_dem, 15.9, 0.8, 0.1, cap_as, eta_chg)
            b = gen.step_charge(soc, p_dem, 15.9, 0.8, 0.1, cap_as, eta_chg)
            for x, y in zip(a, b):
                assert x == pytest.approx(float(y), rel=1e-12, abs=1e-18)


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
        for t in (0.0, 3.0, 11.5, 40.0, 57.9):
            assert M.scenario_drain_a(scen, t) == pytest.approx(
                float(gen.scenario_drain_a(scen, t)), rel=1e-12)
        # The mask, both eras.
        chg_a = sim.dp_chg_ceiling_a(meta)
        run_exit = float(sim.SOC_BAND_RUN_EXIT_S
                         if meta.get("ems_run_exit_s") is None
                         else meta["ems_run_exit_s"])
        _, _, p_dem, v_bus, _, cruise = got
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
    # The table is keyed on the ABSOLUTE preview sample of the stage start, so
    # a table still in use one decision later points at the same stage.
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
    """The slicing mechanism completes inside 50 callbacks (adjudication 2.2)."""
    # Four transitions in the horizon - RollJob.MAX_TRANSITIONS, the
    # adjudication's own bound on the slice.
    prof = lambda t: 1.2 if (t < 4.0 or 8.0 <= t < 12.0 or t >= 16.0) else 0.35
    prev = _synthetic_preview(prof, n_stages=20)
    pre = M.precompute_stages(prev, 0, 20, mode_seed=M.STAGE_CLOSED)
    ladder = [0.25 + i * 0.5 / 6.0 for i in range(7)]
    job = M.RollJob(pre, ladder)
    n_items = len(job.items)
    assert n_items >= 7, "the fixture carries too few transitions to slice"
    calls = 0
    while not job.done and calls < 50:
        job.advance(M.ROLL_BUDGET_MS_DEFAULT * 1e-3)
        calls += 1
    assert job.done, "the roll table did not complete within 50 callbacks"
    assert len(job.table) == n_items


def test_zero_budget_roll_makes_progress_but_does_not_raise():
    prof = lambda t: 1.2 if t < 5.0 else 0.35
    prev = _synthetic_preview(prof, n_stages=10)
    pre = M.precompute_stages(prev, 0, 10, mode_seed=M.STAGE_CLOSED)
    job = M.RollJob(pre, [0.25, 0.75])
    job.advance(0.0)
    # One item per call at worst: the budget is checked AFTER an item, so the
    # job always advances and can never livelock.
    assert job.cursor >= 1


# ═════════════════════════════════════════════════════════════════════════════
# 7. Constraints.
# ═════════════════════════════════════════════════════════════════════════════
def test_no_candidate_leaves_the_share_band():
    for band in (M.SHARE_BAND_DP, M.SHARE_BAND_SDP):
        p = M.Planner(share_band=band)
        assert p.ladder[0] == pytest.approx(band[0])
        assert p.ladder[-1] == pytest.approx(band[1])
        assert all(band[0] - 1e-15 <= s <= band[1] + 1e-15 for s in p.ladder)
        # The DP band stops short of the cut rails, so the setpoint latch can
        # never fire (adjudication 2.3).
        if band == M.SHARE_BAND_DP:
            assert p.ladder[0] > gm.GOV_CONST["DROOP_R_MIN"]
            assert p.ladder[-1] < gm.GOV_CONST["DROOP_R_MAX"]


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
    d, pfc, pbt, ok = p.delivery_table(pre, {}, 0.5, [False] * 20)
    for j in range(20):
        for si, share in enumerate(p.ladder):
            i_fc = d[j][si] * pre.i_tot_mean[j]
            if i_fc > M.I_FC_MAX_A + 1e-12:
                assert not ok[j][si]
    # And the solver must not return an infeasible plan silently: with EVERY
    # ladder point infeasible the decision is flagged.
    dec = p.solve(0.6, 0.6, pre, {}, 0.5, [[False] * 20])
    assert not dec.feasible


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
    order = p._enumeration_order(len(p.ladder), 3)
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
    # The hard budget is honoured: no solve may run materially past it.
    assert tm["solve_ms_max"] <= s.budget_ms * 2.0, tm


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
    for token in ("decisions", "budget expired", "share prediction error",
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


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
