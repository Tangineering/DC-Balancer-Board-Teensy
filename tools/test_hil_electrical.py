#!/usr/bin/env python3
"""pytest suite for tools/hil_electrical.py — the hi-fi HIL electrical engine.

Mirrors the style of test_hil_plant_sim.py: plain pytest, stdlib only, no
network. ElectricalSim's adaptive substep budgeting depends on host timing
(time.perf_counter), so determinism tests pin `_n_sub` explicitly rather than
relying on wall-clock-driven substep counts (see the determinism-guard note
below).

Run: cd tools && python -m pytest test_hil_electrical.py -v
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hil_electrical as he  # noqa: E402


SW_FC_BUS, SW_BT_BUS, SW_MOT_PWR = he.SW_FC_BUS, he.SW_BT_BUS, he.SW_MOT_PWR
SW_REGEN, SW_FC_CHARGE, SW_BT_SEQ = he.SW_REGEN, he.SW_FC_CHARGE, he.SW_BT_SEQ
AUX_FC_REG, AUX_BT_REG = he.AUX_FC_REG, he.AUX_BT_REG


def _actuators(sw=0, aux=0, i_motor_a=0.0, code_fc=0.5, code_bt=0.5, i_charge_a=0.0):
    return {"sw": sw, "aux": aux, "i_motor_a": i_motor_a,
            "code_fc": code_fc, "code_bt": code_bt, "i_charge_a": i_charge_a}


def _pin_and_step(e, dt, actuators, n_sub=8):
    """Step with a pinned substep count, for host-timing-independent tests."""
    e._n_sub = n_sub
    return e.step(dt, actuators)


# ─────────────────────────────────────────────────────────────────────────
# 1. ElectricalSim API contract
# ─────────────────────────────────────────────────────────────────────────

EXPECTED_RAIL_KEYS = {"V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt"}


def test_step_returns_exactly_seven_contract_keys():
    e = he.ElectricalSim(trace_config="short")
    rails = _pin_and_step(e, 1e-3, _actuators())
    assert set(rails.keys()) == EXPECTED_RAIL_KEYS


def test_achieved_substep_hz_positive_after_steps():
    e = he.ElectricalSim(trace_config="short")
    assert e.achieved_substep_hz == 0.0    # nothing stepped yet
    for _ in range(5):
        e.step(1e-3, _actuators())
    assert e.achieved_substep_hz > 0.0


def test_events_list_present_and_starts_empty():
    e = he.ElectricalSim(trace_config="short")
    assert e.events == []
    _pin_and_step(e, 1e-3, _actuators())
    assert isinstance(e.events, list)


def test_invalid_trace_config_rejected():
    with pytest.raises(ValueError):
        he.ElectricalSim(trace_config="bogus")


# ─────────────────────────────────────────────────────────────────────────
# 2. Rt1987 state machine
# ─────────────────────────────────────────────────────────────────────────

def _run_switch(css_nf, v_in=16.0, v_out_fixed=None, ticks=1200, dt=1e-4,
                 trace_l_nh=1.5, en=True):
    """Drive one Rt1987 with a v array under direct control.  If
    v_out_fixed is given, node 1 (VOUT) is pinned there every tick — useful
    for isolating the state machine from the node solver (e.g. to force a
    perpetual foldback bind by never letting VOUT rise)."""
    sw = he.Rt1987("T", 0, 1, css_nf=css_nf, c_load_f=30e-6)
    v = [v_in, 0.0 if v_out_fixed is None else v_out_fixed]
    events = []
    t = 0.0
    trace = []
    for _ in range(ticks):
        sw.update(dt, v, en, events, t, trace_l_nh)
        t += dt
        trace.append((round(t, 6), sw.state))
        if v_out_fixed is not None:
            v[1] = v_out_fixed
    return sw, events, trace


def _first_transition_time(trace, target_state):
    for t, s in trace:
        if s == target_state:
            return t
    return None


def test_en_rise_holds_td_on_for_8ms_no_conduction():
    """EN rising must hold TD_ON for RT_TD_ON_S (8 ms typ) with NO conduction
    stamped — stamp() returns early for OFF/TD_ON."""
    sw, _events, trace = _run_switch(css_nf=100.0, ticks=100, dt=1e-4)  # 10 ms
    # Still in TD_ON well before the 8 ms boundary.
    states_at_5ms = [s for t, s in trace if t <= 5e-3]
    assert all(s in ("TD_ON",) for s in states_at_5ms[1:]), states_at_5ms[:5]
    t_soft = _first_transition_time(trace, "SOFT")
    assert t_soft is not None
    assert t_soft == pytest.approx(he.RT_TD_ON_S, abs=2e-4)

    # No conduction stamped while TD_ON: G/J must be untouched.
    sw2 = he.Rt1987("T2", 0, 1, css_nf=100.0, c_load_f=30e-6)
    v = [16.0, 0.0]
    events = []
    sw2.update(1e-4, v, True, events, 0.0, 1.5)
    assert sw2.state == "TD_ON"
    G = [[0.0, 0.0], [0.0, 0.0]]
    J = [0.0, 0.0]
    sw2.stamp(G, J, v, None)   # 4th arg 'en' unused by stamp() but part of its signature
    assert G == [[0.0, 0.0], [0.0, 0.0]]
    assert J == [0.0, 0.0]


def test_soft_start_ramp_duration_scales_with_css():
    """tON = (VIN/35)*(CSS_nF/0.0023 - 100) us — a 100 nF switch (bus/mot
    switches) must ramp roughly two orders of magnitude longer than a 5.6 nF
    one (regen/charge/seq switches)."""
    t_100 = he.rt1987_t_on_s(16.0, 100.0)
    t_56 = he.rt1987_t_on_s(16.0, 5.6)
    assert t_100 > 0.0
    assert t_56 > 0.0
    ratio = t_100 / t_56
    # (100/0.0023 - 100) / (5.6/0.0023 - 100) ~= 18.6
    assert ratio == pytest.approx(18.6, rel=0.05)
    assert t_100 == pytest.approx(19.83e-3, rel=0.02)
    assert t_56 == pytest.approx(1.07e-3, rel=0.02)


def test_off_state_full_isolation_no_stamp_no_reverse_current():
    """A switch that has never been enabled stays OFF and stamps nothing —
    no body-diode/reverse path through the ideal-diode controller itself."""
    sw = he.Rt1987("T", 0, 1, css_nf=5.6, c_load_f=30e-6)
    assert sw.state == "OFF"
    G = [[0.0, 0.0], [0.0, 0.0]]
    J = [0.0, 0.0]
    sw.stamp(G, J, [16.0, 20.0], None)   # VOUT > VIN: a body-diode path would conduct
    assert G == [[0.0, 0.0], [0.0, 0.0]]
    assert J == [0.0, 0.0]


def test_off_state_persists_when_en_low():
    sw, events, trace = _run_switch(css_nf=5.6, ticks=50, en=False)
    assert sw.state == "OFF"
    assert all(s == "OFF" for _t, s in trace)


def test_reverse_comparator_blocks_when_out_exceeds_in():
    """Drive a switch to ON with a small forward differential, then reverse
    it past RT_V_REV: it must open within (about) one tick and re-arm
    WITHOUT a fresh soft-start (the TP0178/TP0201 reactive-pickup path)."""
    sw = he.Rt1987("T", 0, 1, css_nf=5.6, c_load_f=30e-6)
    v = [10.0, 9.98]
    events = []
    t = 0.0
    dt = 1e-4
    for _ in range(200):
        sw.update(dt, v, True, events, t, 1.5)
        t += dt
    assert sw.state == "ON"

    v = [10.0, 10.10]   # VOUT now exceeds VIN by more than |RT_V_REV|
    sw.update(dt, v, True, events, t, 1.5)
    assert sw.state == "OFF"
    assert sw._restart_no_ss is True
    reverse_events = [e for e in events if e["kind"] == "reverse_block"]
    assert len(reverse_events) == 1
    assert reverse_events[0]["dv"] < he.RT_V_REV

    # Forward again: re-arms straight to ON, no new TD_ON/SOFT cycle.
    v = [10.0, 9.90]
    sw.update(dt, v, True, events, t + dt, 1.5)
    assert sw.state == "ON"


def test_foldback_bind_over_250us_trips_cut_and_64ms_retry():
    """Pin VOUT at 0 forever (an infinite-inrush stimulus the node solver
    would never actually produce, but exactly what isolates the state
    machine's own SCP timer): the foldback clamp binds continuously, and
    after RT_SCP_BLANK_S (250 us) the switch must CUT and emit both a
    sw_ring and an scp_cut event, then retry after RT_SCP_RETRY_S (64 ms)."""
    sw, events, trace = _run_switch(css_nf=100.0, v_out_fixed=0.0,
                                     ticks=1200, dt=1e-4)
    cuts = [e for e in events if e["kind"] == "scp_cut"]
    rings = [e for e in events if e["kind"] == "sw_ring"]
    assert len(cuts) >= 1
    assert len(rings) >= 1
    assert cuts[0]["cut_count"] == 1
    t_first_cut = cuts[0]["t"]
    # It must have run for at least the SCP blank time before cutting (with
    # slack for the 8 ms TD_ON that precedes SOFT).
    assert t_first_cut >= he.RT_TD_ON_S + he.RT_SCP_BLANK_S - 1e-6
    if len(cuts) >= 2:
        gap = cuts[1]["t"] - cuts[0]["t"]
        # Retry gap ~= RT_SCP_RETRY_S plus a fresh TD_ON+partial-SOFT run
        # before the next cut — must be at least the bare retry timer.
        assert gap >= he.RT_SCP_RETRY_S - 1e-6


def test_foldback_limit_shape():
    """rt1987_fold_limit: high (8.5 A) at/under the knee, tapering down
    toward the low limit (2.5 A) as dV grows, and clamped at the floor."""
    assert he.rt1987_fold_limit(0.0) == he.RT_I_FOLD_HIGH
    assert he.rt1987_fold_limit(he.RT_DV_FOLD_KNEE) == he.RT_I_FOLD_HIGH
    assert he.rt1987_fold_limit(16.0) == pytest.approx(5.3, abs=0.05)
    assert he.rt1987_fold_limit(1000.0) == he.RT_I_FOLD_LOW  # clamped at the floor
    # Monotone non-increasing as dV rises past the knee.
    vals = [he.rt1987_fold_limit(dv) for dv in (5.0, 8.0, 12.0, 16.0, 30.0)]
    assert all(a >= b - 1e-9 for a, b in zip(vals, vals[1:]))


# ─────────────────────────────────────────────────────────────────────────
# 3. Bring-up / droop integration
# ─────────────────────────────────────────────────────────────────────────

def test_bringup_from_dark_reaches_regulation_neighborhood():
    """From a cold network, closing FC_BUS with FC_REG enabled must bring
    V_bus up toward the ~15.9 V no-load regulation point over a few hundred
    ms (t_D(ON) 8 ms + soft-start ~20 ms + boost tau_r settling)."""
    e = he.ElectricalSim(trace_config="short")
    sw = SW_FC_BUS
    aux = AUX_FC_REG
    rails = None
    for _ in range(300):        # 300 ms at dt=1e-3
        rails = e.step(1e-3, _actuators(sw=sw, aux=aux))
    assert rails["V_bus"] > 10.0
    assert rails["V_bus"] < 17.0


def test_droop_raising_code_fc_lowers_fc_channel_target_monotonically():
    """Share-authority sign check: for a fixed nonzero channel current,
    raising the FC droop code (g) must LOWER the FC boost's output-node
    voltage (V_out = V0 - RE_MAX*g*i), never raise it."""
    def fc_node_voltage(code_fc):
        e = he.ElectricalSim(trace_config="short")
        sw = SW_FC_BUS | SW_MOT_PWR
        aux = AUX_FC_REG
        rails = None
        for _ in range(400):
            rails = e.step(1e-3, _actuators(sw=sw, aux=aux, i_motor_a=1.0,
                                            code_fc=code_fc, code_bt=0.5))
        return e.node_voltage("OFC"), rails

    v_low, _ = fc_node_voltage(0.1)
    v_high, _ = fc_node_voltage(0.9)
    assert v_high < v_low


# ─────────────────────────────────────────────────────────────────────────
# 4. Handoff sag
# ─────────────────────────────────────────────────────────────────────────

def test_handoff_dark_standby_picks_up_reactively_after_bus_sags():
    """TP0178/TP0201-class handoff: FC alone regulates the bus (BT held
    completely dark in standby — the real hardware condition, not "both
    live"), then FC's bus switch opens and BT's closes in the SAME tick
    (the share loop commanding a hard rail flip).  BT is NOT instantly
    conducting: it must run TD_ON (8 ms) + soft-start before it regulates,
    so the bus SAGS — through the disabled boosts' body-diode passthrough
    and the bare node capacitance/bleed — before BT reactively picks it back
    up.  This is the mechanism the handoff-sag scenario (hil_plant_sim.py)
    exists to reproduce; the standby diode does not pick up proactively."""
    e = he.ElectricalSim(trace_config="short")
    rails = None
    for _ in range(500):
        rails = e.step(1e-3, _actuators(sw=SW_FC_BUS, aux=AUX_FC_REG))
    v_before = rails["V_bus"]
    assert v_before > 10.0
    assert e.switches["FC_BUS"].state == "ON"
    assert e.switches["BT_BUS"].state == "OFF"

    sw_bt = SW_BT_BUS | SW_BT_SEQ
    aux_bt = AUX_BT_REG
    v_min = v_before
    for _ in range(50):         # the handoff transient window
        rails = e.step(1e-3, _actuators(sw=sw_bt, aux=aux_bt))
        v_min = min(v_min, rails["V_bus"])
    assert v_min < v_before - 0.5, (
        f"expected a real sag below {v_before:.3f} V during the handoff gap, "
        f"min was {v_min:.3f} V")

    # Recovery: BT alone regulates it back up close to the same no-load point.
    for _ in range(600):
        rails = e.step(1e-3, _actuators(sw=sw_bt, aux=aux_bt))
    assert rails["V_bus"] > v_min + 5.0
    assert rails["V_bus"] == pytest.approx(v_before, abs=0.5)


# ─────────────────────────────────────────────────────────────────────────
# 5. Parasitic ring events
# ─────────────────────────────────────────────────────────────────────────

def test_scp_cut_ring_event_peak_above_node_voltage():
    sw, events, _trace = _run_switch(css_nf=100.0, v_out_fixed=0.0,
                                      ticks=1200, dt=1e-4)
    rings = [e for e in events if e["kind"] == "sw_ring"]
    assert rings
    for r in rings:
        assert r["peak_v"] > 0.0
        assert "over_absmax" in r
        assert r["i_cut"] > 0.0


def test_ring_peak_scales_with_trace_length_bt_vs_fc():
    """Directly exercise Rt1987._open() with the two FastHenry trace
    inductances (FC 1.538 nH vs BT 3.480 nH, 'long' config) and confirm the
    BT (longer-trace) ring estimate peaks higher for the same cut current,
    in proportion to L (V_peak = V_node + L*di/dt is linear in L)."""
    def peak_for(l_nh):
        sw = he.Rt1987("T", 0, 1, css_nf=5.6, c_load_f=30e-6)
        sw.i = 3.0  # pretend a 3 A cut current
        events = []
        sw._open(events, t_now=0.0, trace_l_nh=l_nh, v_node=15.0, reason="scp_cut")
        rings = [e for e in events if e["kind"] == "sw_ring"]
        return rings[0]["peak_v"]

    l_fc = he.TRACE_L_NH["long"]["FC"]
    l_bt = he.TRACE_L_NH["long"]["BT"]
    peak_fc = peak_for(l_fc)
    peak_bt = peak_for(l_bt)
    assert peak_bt > peak_fc
    extra_fc = peak_fc - 15.0
    extra_bt = peak_bt - 15.0
    assert extra_bt / extra_fc == pytest.approx(l_bt / l_fc, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────
# 6. Noise
# ─────────────────────────────────────────────────────────────────────────

_SAMPLE_RAILS = {"V_fc": 12.9, "V_batt": 7.86, "V_bus": 15.9,
                 "V_chg": 0.0, "V_rgn": 0.0, "I_fc": 0.5, "I_batt": 0.3}


def test_noise_default_quantize_only_is_deterministic():
    nc1 = he.NoiseConfig()
    nc2 = he.NoiseConfig()
    out1 = nc1.apply(_SAMPLE_RAILS)
    out2 = nc2.apply(_SAMPLE_RAILS)
    assert out1 == out2


def test_noise_quantization_changes_by_at_most_one_lsb():
    nc = he.NoiseConfig(quantize=True, ina_zero_offset=0.0)
    out = nc.apply(_SAMPLE_RAILS)
    lsb = {"V_fc": he.LSB_V_FC, "V_batt": he.LSB_V_BATT, "V_bus": he.LSB_V_BUS,
           "V_chg": he.LSB_V_CHG, "V_rgn": he.LSB_V_RGN,
           "I_fc": he.LSB_I, "I_batt": he.LSB_I}
    for key, step in lsb.items():
        assert abs(out[key] - _SAMPLE_RAILS[key]) <= step / 2.0 + 1e-9, key


def test_noise_no_quantize_ina_zero_offset_still_applies():
    nc = he.NoiseConfig(quantize=False, ina_zero_offset=0.02)
    out = nc.apply(_SAMPLE_RAILS)
    assert out["I_fc"] == pytest.approx(_SAMPLE_RAILS["I_fc"] + 0.02, abs=1e-9)
    assert out["V_fc"] == pytest.approx(_SAMPLE_RAILS["V_fc"], abs=1e-9)


def test_noise_never_produces_negative_rails():
    nc = he.NoiseConfig(quantize=True, sigma={"I_fc": 5.0}, seed=1)
    rails = dict(_SAMPLE_RAILS)
    rails["I_fc"] = 0.001
    for _ in range(50):
        out = nc.apply(rails)
        assert out["I_fc"] >= 0.0


def test_noise_seeded_gaussian_reproducible():
    """Two NoiseConfig instances built with the same seed must draw the same
    first sample (statistical, but with a fixed seed it is exact)."""
    nc1 = he.NoiseConfig(sigma={"V_bus": 0.05}, seed=42)
    nc2 = he.NoiseConfig(sigma={"V_bus": 0.05}, seed=42)
    out1 = nc1.apply(_SAMPLE_RAILS)
    out2 = nc2.apply(_SAMPLE_RAILS)
    assert out1 == out2


def test_noise_suggested_has_nonzero_sigmas():
    nc = he.NoiseConfig.suggested(seed=7)
    assert any(v > 0.0 for v in nc.sigma.values())
    out = nc.apply(_SAMPLE_RAILS)
    # With non-zero sigma the quantized-only path is not guaranteed equal.
    assert isinstance(out, dict)


# ─────────────────────────────────────────────────────────────────────────
# 7. Determinism guard
# ─────────────────────────────────────────────────────────────────────────

def test_pinned_substep_count_gives_reproducible_trajectory():
    """The engine's adaptive substep budgeting measures real wall-clock cost
    (time.perf_counter), so achieved_substep_hz and the resulting _n_sub can
    legitimately vary run-to-run on a loaded host — that part is NOT
    claimed to be deterministic.  But the underlying PHYSICS (backward-Euler
    node solve, switch state machines, source models) must be: with the
    substep count pinned externally before each step, two independent runs
    over the same actuator sequence must produce bit-identical rails."""
    def run():
        e = he.ElectricalSim(trace_config="short")
        sw = SW_FC_BUS
        aux = AUX_FC_REG
        out = None
        for _ in range(50):
            out = _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux), n_sub=8)
        return out

    a = run()
    b = run()
    assert a == b


def test_determinism_finding_unpinned_substep_count_is_host_timing_dependent():
    """FINDING (not a defect): without pinning `_n_sub`, the substep count
    self-adapts from a real time.perf_counter() measurement each call, so
    the exact floating-point trajectory is NOT guaranteed host-independent
    even for identical actuator sequences — only the pinned-substep path
    (tested above) is reproducible. This test documents that the API
    provides no public way to pin the substep count other than reaching
    into the private `_n_sub` attribute; there is no keyword to run a fixed
    number of substeps per step() call.  Recorded as a gap against the
    'determinism guard' floor item, not asserted as a bug."""
    e = he.ElectricalSim(trace_config="short")
    assert not hasattr(e, "n_sub"), "no public substep-count knob exists"
    assert hasattr(e, "_n_sub"), "only the private attribute can pin it (used above)"


# ─────────────────────────────────────────────────────────────────────────
# 8. H1: regen node-runaway backstop (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

def test_h1_regen_with_mot_pwr_open_node_stays_bounded():
    """A large NEGATIVE (regen) i_motor_a with MOT_PWR open must not run the
    V-MOT node away: the Norton-conductance stamp (i_motor / max(v, floor))
    keeps it self-limiting, so after many ticks the node stays within the
    V_NODE_RUNAWAY_MULT*V_ABSMAX backstop with at most the occasional
    node_runaway event, not a divergence."""
    e = he.ElectricalSim(trace_config="short")
    for _ in range(2000):
        e.step(1e-3, _actuators(sw=0, aux=0, i_motor_a=-50.0))
    assert e.node_voltage("MOT") <= he.V_NODE_RUNAWAY_MULT * he.V_ABSMAX
    assert e.node_voltage("MOT") >= 0.0
    runaways = [ev for ev in e.events if ev["kind"] == "node_runaway"]
    assert len(runaways) <= 1


def test_h1_node_runaway_backstop_fires_and_clamps_once():
    """Force an implausible prior MOT-node voltage (simulating a solver
    artefact) ahead of a large regen draw: the backstop must clamp the node
    to V_NODE_RUNAWAY_MULT*V_ABSMAX, emit exactly one node_runaway event for
    that tick, and not re-trigger every subsequent tick once the node is
    back in a sane range."""
    e = he.ElectricalSim(trace_config="short")
    e.v[he.N_MOT] = 1000.0     # implausible prior state
    e._n_sub = 1
    e.step(1e-3, _actuators(sw=0, aux=0, i_motor_a=-50.0))
    first_pass_events = [ev for ev in e.events if ev["kind"] == "node_runaway"]
    assert len(first_pass_events) == 1
    assert first_pass_events[0]["clamped_to"] == pytest.approx(he.V_NODE_RUNAWAY_MULT * he.V_ABSMAX)
    assert e.node_voltage("MOT") == pytest.approx(he.V_NODE_RUNAWAY_MULT * he.V_ABSMAX)

    for _ in range(20):
        e._n_sub = 1
        e.step(1e-3, _actuators(sw=0, aux=0, i_motor_a=-50.0))
    total_runaways = [ev for ev in e.events if ev["kind"] == "node_runaway"]
    assert len(total_runaways) == 1, "backstop must not keep re-firing once the node is bounded"


def test_h1_sw_ring_over_absmax_suppressed_when_node_already_implausible():
    """Rt1987._open()'s plausibility gate: an implausible v_node (> V_ABSMAX)
    at cut time must NOT be able to manufacture an over_absmax verdict on its
    own, even though the analytic peak estimate (v_node + L*di/dt) exceeds
    V_ABSMAX by construction whenever v_node itself already does."""
    sw = he.Rt1987("T", 0, 1, css_nf=5.6, c_load_f=30e-6)
    sw.i = 5.0
    events = []
    sw._open(events, t_now=0.0, trace_l_nh=50.0, v_node=100.0, reason="scp_cut")
    rings = [e for e in events if e["kind"] == "sw_ring"]
    assert len(rings) == 1
    assert rings[0]["peak_v"] > he.V_ABSMAX     # the raw estimate WOULD trip it
    assert rings[0]["over_absmax"] is False     # but the plausibility gate blocks it


def test_h1_sw_ring_over_absmax_true_when_node_plausible():
    """Same construction, but v_node itself is a plausible (<= V_ABSMAX)
    value at cut time: the over_absmax verdict must fire normally."""
    sw = he.Rt1987("T", 0, 1, css_nf=5.6, c_load_f=30e-6)
    sw.i = 5.0
    events = []
    sw._open(events, t_now=0.0, trace_l_nh=50.0, v_node=15.0, reason="scp_cut")
    rings = [e for e in events if e["kind"] == "sw_ring"]
    assert len(rings) == 1
    assert rings[0]["peak_v"] > he.V_ABSMAX
    assert rings[0]["over_absmax"] is True


# ─────────────────────────────────────────────────────────────────────────
# 9. H2: reverse-trip re-arm semantics (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

def _drive_to_on(sw, v, ticks=200, dt=1e-4):
    events = []
    t = 0.0
    for _ in range(ticks):
        sw.update(dt, v, True, events, t, 1.5)
        t += dt
    return events, t


def test_h2_reverse_trip_still_enabled_rearms_without_soft_start():
    """Kept-behavior control case: a reverse-blocked switch that stays
    ENABLED (EN never goes low) must re-arm straight to ON once forward
    again — no fresh TD_ON/SOFT cycle."""
    sw = he.Rt1987("T", 0, 1, css_nf=5.6, c_load_f=30e-6)
    v = [10.0, 9.98]
    events, t = _drive_to_on(sw, v)
    assert sw.state == "ON"

    v = [10.0, 10.10]   # reverse trip
    sw.update(1e-4, v, True, events, t, 1.5)
    t += 1e-4
    assert sw.state == "OFF"
    assert sw._restart_no_ss is True

    v = [10.0, 9.90]     # forward again, EN never dropped
    sw.update(1e-4, v, True, events, t, 1.5)
    assert sw.state == "ON"


def test_h2_reverse_trip_then_en_cycle_forces_td_on_then_soft():
    """H2 fix: a reverse-blocked switch that THEN sees EN go low (or VIN drop
    under UVLO) must have _restart_no_ss cleared — a fresh EN into a
    near-0-V node must run TD_ON then SOFT like a normal cold start, never
    jump straight to ON."""
    sw = he.Rt1987("T", 0, 1, css_nf=5.6, c_load_f=30e-6)
    v = [10.0, 9.98]
    events, t = _drive_to_on(sw, v)
    assert sw.state == "ON"

    v = [10.0, 10.10]   # reverse trip
    sw.update(1e-4, v, True, events, t, 1.5)
    t += 1e-4
    assert sw._restart_no_ss is True

    # EN goes low: must clear the pending no-soft-start re-arm.
    v = [10.0, 0.0]
    sw.update(1e-4, v, False, events, t, 1.5)
    t += 1e-4
    assert sw.state == "OFF"
    assert sw._restart_no_ss is False

    # Fresh EN into a ~0 V node: must go TD_ON, not straight to ON.
    sw.update(1e-4, v, True, events, t, 1.5)
    assert sw.state == "TD_ON"
    t += 1e-4
    for _ in range(70):        # well under RT_TD_ON_S (8 ms)
        sw.update(1e-4, v, True, events, t, 1.5)
        t += 1e-4
        assert sw.state == "TD_ON", "must not skip TD_ON after the EN cycle"
    for _ in range(100):        # cross the 8 ms boundary
        sw.update(1e-4, v, True, events, t, 1.5)
        t += 1e-4
        if sw.state == "SOFT":
            break
    assert sw.state == "SOFT", "must reach SOFT (soft-start), not jump to ON"


# ─────────────────────────────────────────────────────────────────────────
# 10. M1: SCP-cut retry timer reset on EN cycle (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

def test_m1_en_cycle_after_scp_cut_resets_retry_timer():
    sw, events, _trace = _run_switch(css_nf=100.0, v_out_fixed=0.0, ticks=120, dt=1e-4)
    assert sw.state == "OFF"
    assert sw.cut_count >= 1
    assert sw.t_retry > 0.0, "expected the 64 ms auto-retry timer armed after the cut"

    # EN low then high again, well before the 64 ms retry would have elapsed.
    v = [16.0, 0.0]
    sw.update(1e-4, v, False, events, 0.0120, 1.5)
    assert sw.t_retry == 0.0, "EN-cycle must reset the retry timer, not just decrement it"
    sw.update(1e-4, v, True, events, 0.0121, 1.5)
    assert sw.state == "TD_ON", "must restart the TD_ON/SOFT cycle immediately, not wait out the old retry"


# ─────────────────────────────────────────────────────────────────────────
# 11. M2: numeric_fault / neg_clamp_count (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

def test_m2_nan_actuator_sets_sticky_numeric_fault_and_restores_finite():
    """Inject NaN via a NaN actuator (i_motor_a) with MOT_PWR closed, AFTER a
    few good ticks so there is a finite previous state to restore from.
    Confirms: a numeric_fault event per corrupted node, the sticky flag set
    (and visible via summary()), and every node restored to a finite value."""
    import math
    e = he.ElectricalSim(trace_config="short")
    for _ in range(10):
        e.step(1e-3, _actuators())
    assert all(math.isfinite(x) for x in e.v)
    assert e.numeric_fault is False

    e._n_sub = 1
    e.step(1e-3, _actuators(sw=SW_MOT_PWR, i_motor_a=float("nan")))
    assert e.numeric_fault is True
    assert e.summary()["numeric_fault"] is True
    assert all(math.isfinite(x) for x in e.v), "a corrupted node must be restored, not left NaN"
    numeric_events = [ev for ev in e.events if ev["kind"] == "numeric_fault"]
    assert numeric_events

    # Sticky: a later CLEAN tick must not clear the flag.
    e.step(1e-3, _actuators())
    assert e.numeric_fault is True
    assert e.summary()["numeric_fault"] is True


def test_m2_neg_clamp_count_increments_on_negative_node_clamp():
    """A dark network (everything OFF, nothing driving any node up) decays
    toward/through 0 and gets clamped there — neg_clamp_count must count
    those clamps as a diagnostic."""
    e = he.ElectricalSim(trace_config="short")
    assert e.neg_clamp_count == 0
    e.step(1e-3, _actuators(sw=0, aux=0))
    assert e.neg_clamp_count > 0
    assert e.summary()["neg_clamp_count"] == e.neg_clamp_count


# ─────────────────────────────────────────────────────────────────────────
# 12. M5: v_bus_sense_offset rename (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

def test_m5_attribute_renamed_to_v_bus_sense_offset():
    e = he.ElectricalSim(trace_config="short")
    assert hasattr(e, "v_bus_sense_offset")
    assert e.v_bus_sense_offset == 0.0
    assert not hasattr(e, "v_bus_offset"), "the old name must not linger as a stale alias"


def test_m5_sense_offset_moves_only_v_bus_in_rails_not_the_node():
    """The offset is added ONLY in _rails()'s V_bus computation, never seen
    by the node solve, so the underlying VBUS node (and everything derived
    from it, like V_chg/V_rgn) must be untouched by it."""
    e = he.ElectricalSim(trace_config="short")
    for _ in range(50):
        e.step(1e-3, _actuators(sw=SW_FC_BUS, aux=AUX_FC_REG))
    node_before = e.node_voltage("BUS")
    rails_before = e._rails(SW_FC_BUS)

    e.v_bus_sense_offset = -5.0
    rails_after = e._rails(SW_FC_BUS)
    node_after = e.node_voltage("BUS")

    assert node_after == pytest.approx(node_before)       # node itself untouched
    assert rails_after["V_bus"] == pytest.approx(rails_before["V_bus"] - 5.0)
    assert rails_after["V_chg"] == pytest.approx(rails_before["V_chg"])
    assert rails_after["V_rgn"] == pytest.approx(rails_before["V_rgn"])


# ─────────────────────────────────────────────────────────────────────────
# 13. L3: source-model degenerate-parameter guards (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

def test_l3_fuelcellsource_zero_tau_raises_valueerror():
    with pytest.raises(ValueError):
        he.FuelCellSource(tau_s=0.0)
    with pytest.raises(ValueError):
        he.FuelCellSource(tau_s=-0.01)


def test_l3_batterysource_zero_capacity_raises_valueerror():
    with pytest.raises(ValueError):
        he.BatterySource(capacity_ah=0.0)
    with pytest.raises(ValueError):
        he.BatterySource(capacity_ah=-1.0)


# ─────────────────────────────────────────────────────────────────────────
# 14. L4: zero-elapsed-tick handling (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

def test_l4_zero_elapsed_tick_holds_last_achieved_rate(monkeypatch):
    """On a host with a coarse time.perf_counter(), a genuinely zero-elapsed
    tick must HOLD the last non-zero achieved_substep_hz rather than reset
    it to 0.0 (the old `_cost_ewma == 0.0` sentinel would have corrupted the
    EWMA on this exact condition)."""
    e = he.ElectricalSim(trace_config="short")
    e.step(1e-3, _actuators())     # establish a real, nonzero rate
    prev_rate = e.achieved_substep_hz
    assert prev_rate > 0.0
    assert e._cost_init is True

    const_time = [100.0]
    monkeypatch.setattr(he.time, "perf_counter", lambda: const_time[0])
    e.step(1e-3, _actuators())     # elapsed == 0.0 exactly
    assert e.achieved_substep_hz == prev_rate


def test_l4_cost_init_flag_starts_false_and_first_tick_sets_it():
    e = he.ElectricalSim(trace_config="short")
    assert e._cost_init is False
    e.step(1e-3, _actuators())
    assert e._cost_init is True


# ─────────────────────────────────────────────────────────────────────────────
# Regen chopper: bench-calibrated clamp + the 20 W dissipation question
# (operator calibration 2026-08-27: clamp observed at 18.1 V; the purpose of the
# chopper model is checking dissipation vs the 47 Ω resistor's 20 W rating).
# ─────────────────────────────────────────────────────────────────────────────

def test_chopper_constants_bench_calibrated():
    assert he.V_CHOPPER_TRIP == pytest.approx(18.1)
    assert he.R_CHOPPER == pytest.approx(47.0)
    assert he.P_CHOPPER_MAX_W == pytest.approx(20.0)
    # At the clamp level the steady dissipation is well under the rating —
    # the rating is only reachable past sqrt(20*47) ~= 30.66 V.
    assert (18.1 ** 2) / 47.0 == pytest.approx(6.97, abs=0.01)


def test_chopper_peak_power_tracked_no_event_below_rating():
    e = he.ElectricalSim()
    # Force the regen node just above the clamp but far below the 30.7 V
    # power-rating crossover, then run one substep directly.
    e.v[he.N_RGN] = 20.0
    e._substep(1e-5, 0, 0, 0.0, 0.0, 0.0, 0.0)
    assert e.chopper_active
    assert 0.0 < e.chopper_peak_w < he.P_CHOPPER_MAX_W
    assert not any(ev["kind"] == "chopper_over_power" for ev in e.events)


def test_chopper_over_power_event_once_per_excursion():
    e = he.ElectricalSim()
    # Start far above the rating crossover: even after one backward-Euler
    # relaxation the solved node stays > 30.7 V, so V^2/47 > 20 W.
    e.v[he.N_RGN] = 60.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    over = [ev for ev in e.events if ev["kind"] == "chopper_over_power"]
    assert len(over) == 1
    assert over[0]["p_w"] > he.P_CHOPPER_MAX_W
    assert over[0]["rating_w"] == pytest.approx(20.0)
    assert e.chopper_peak_w > he.P_CHOPPER_MAX_W
    # Still above the rating on the next substep: the once-per-excursion latch
    # must NOT emit a second event.
    e.v[he.N_RGN] = 60.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    assert sum(1 for ev in e.events if ev["kind"] == "chopper_over_power") == 1
    # Excursion ends (node back below the clamp), then a new excursion begins:
    # a second event is correct.
    e.v[he.N_RGN] = 5.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    e.v[he.N_RGN] = 60.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    assert sum(1 for ev in e.events if ev["kind"] == "chopper_over_power") == 2


def test_chopper_peak_w_in_summary():
    e = he.ElectricalSim()
    assert e.summary()["chopper_peak_w"] == 0.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
