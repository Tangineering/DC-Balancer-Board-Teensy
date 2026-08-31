#!/usr/bin/env python3
"""pytest suite for tools/hil_electrical.py — the hi-fi HIL electrical engine.

Mirrors the style of test_hil_plant_sim.py: plain pytest, stdlib only, no
network. ElectricalSim's adaptive substep budgeting depends on host timing
(time.perf_counter), so determinism tests pin `_n_sub` explicitly rather than
relying on wall-clock-driven substep counts (see the determinism-guard note
below).

Run: cd tools && python -m pytest test_hil_electrical.py -v
"""
import math
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
    # Force the motor node (the regen node IS V-MOT — 2026-08-30 topology fix)
    # just above the clamp but far below the 30.7 V power-rating crossover,
    # then run one substep directly.
    e.v[he.N_MOT] = 20.0
    e._substep(1e-5, 0, 0, 0.0, 0.0, 0.0, 0.0)
    assert e.chopper_active
    assert 0.0 < e.chopper_peak_w < he.P_CHOPPER_MAX_W
    assert not any(ev["kind"] == "chopper_over_power" for ev in e.events)


def test_chopper_over_power_event_once_per_excursion():
    e = he.ElectricalSim()
    # Start far above the rating crossover: even after one backward-Euler
    # relaxation the solved node stays > 30.7 V, so V^2/47 > 20 W.
    e.v[he.N_MOT] = 60.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    over = [ev for ev in e.events if ev["kind"] == "chopper_over_power"]
    assert len(over) == 1
    assert over[0]["p_w"] > he.P_CHOPPER_MAX_W
    assert over[0]["rating_w"] == pytest.approx(20.0)
    assert e.chopper_peak_w > he.P_CHOPPER_MAX_W
    # Still above the rating on the next substep: the once-per-excursion latch
    # must NOT emit a second event.
    e.v[he.N_MOT] = 60.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    assert sum(1 for ev in e.events if ev["kind"] == "chopper_over_power") == 1
    # Excursion ends (node back below the clamp), then a new excursion begins:
    # a second event is correct.
    e.v[he.N_MOT] = 5.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    e.v[he.N_MOT] = 60.0
    e._substep(1e-6, 0, 0, 0.0, 0.0, 0.0, 0.0)
    assert sum(1 for ev in e.events if ev["kind"] == "chopper_over_power") == 2


def test_chopper_peak_w_in_summary():
    e = he.ElectricalSim()
    assert e.summary()["chopper_peak_w"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Measured noise model (2026-08-27 bench-log corpus fit) — pin the values so a
# drive-by edit cannot silently detach them from their measurement provenance.
# ─────────────────────────────────────────────────────────────────────────────

def test_suggested_sigmas_are_the_measured_values():
    nc = he.NoiseConfig.suggested(seed=1)
    assert nc.sigma == {
        "V_fc": 0.019, "V_batt": 0.0024, "V_bus": 0.0018,
        "V_chg": 0.004, "V_rgn": 0.0040,
        "I_fc": 0.0044, "I_batt": 0.0044,
    }
    # V_chg is adopted from V_rgn (identical divider; own channel censored at 0
    # in every logged run) — the two must stay paired until a charge run is logged.
    assert nc.sigma["V_chg"] == pytest.approx(nc.sigma["V_rgn"], rel=0.01)


def test_ina_zero_offset_default_is_per_channel_asymmetric():
    nc = he.NoiseConfig(quantize=False, seed=1)
    assert nc.ina_zero_offset == {"I_fc": he.INA_ZERO_OFFSET_A, "I_batt": 0.0}
    rails = {"V_fc": 12.0, "V_batt": 8.0, "V_bus": 15.9, "V_chg": 0.0,
             "V_rgn": 0.0, "I_fc": 1.0, "I_batt": 1.0}
    out = nc.apply(rails)
    assert out["I_fc"] == pytest.approx(1.0 + he.INA_ZERO_OFFSET_A)
    assert out["I_batt"] == pytest.approx(1.0)      # BT part measured offset-free


def test_ina_zero_offset_float_back_compat_applies_to_both():
    nc = he.NoiseConfig(quantize=False, ina_zero_offset=0.05, seed=1)
    rails = {"V_fc": 12.0, "V_batt": 8.0, "V_bus": 15.9, "V_chg": 0.0,
             "V_rgn": 0.0, "I_fc": 1.0, "I_batt": 2.0}
    out = nc.apply(rails)
    assert out["I_fc"] == pytest.approx(1.05)
    assert out["I_batt"] == pytest.approx(2.05)


# ─────────────────────────────────────────────────────────────────────────────
# Physical SOFT-state operating point (2026-08-30 fix) — Rt1987._soft_operating_
# point() now returns i_phys = max(c_load*rate, (target_prev - v_out)/R) with
# target_prev evaluated at the SAME instant as v_out, instead of the old
# next-instant target whose per-substep step across the 21 mOhm pass resistance
# read as tens of amps of fictitious demand.  Most tests below are REGRESSIONS
# for that fix (each docstring says why it would have FAILED under the old
# form); three are GUARDS, not regressions — they passed under the old code too
# and pin what the fix must NOT break: the two genuine-overload/persistent-short
# tests (the old form folded MORE readily) and the _h==0 degradation test
# (arithmetically identical either way).
# ─────────────────────────────────────────────────────────────────────────────

def _settle(e, sw, aux, ticks, dt=1e-3, i_motor_a=0.0):
    # F1 (review, 2026-08-30): every step in this section pins _n_sub — the
    # adaptive budgeting floors at 1 substep on a starved host, and the physical
    # SOFT current converges only for substeps <= ~125 us (measured: peak
    # precharge I_fc reads 4.27 A at _n_sub=1 vs the converged 0.22 A at >=8).
    rails = None
    for _ in range(ticks):
        rails = _pin_and_step(e, dt, _actuators(sw=sw, aux=aux, i_motor_a=i_motor_a))
    return rails


def test_regen_reaches_on_from_regulated_bus_with_zero_scp_cuts():
    """REGEN's input node is V-MOT (topology fix, 2026-08-30 docstring at the
    switch table), so bring the bus AND MOT_PWR up first, then close REGEN.

    Under the OLD stale-target form, the 5.6 nF REGEN switch's ~1.07 ms
    soft-start ramp read a fictitious ~tens-of-amps demand for its ENTIRE
    ramp (the module docstring's "fold-active for their entire ramp" claim),
    so t_clamped ran past the 250 us SCP blanking every single time and
    REGEN could never reach ON — it would CUT instead.  This test would
    therefore have failed (reached_on=False, cut_count>0) under the old code.
    """
    e = he.ElectricalSim(trace_config="short")
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ | SW_MOT_PWR
    aux = AUX_FC_REG | AUX_BT_REG
    _settle(e, sw, aux, 500)
    assert e.switch_state("MOT_PWR") == "ON"
    v_bus_before = e.node_voltage("BUS")

    cut_before = e.switches["REGEN"].cut_count
    sw |= SW_REGEN
    reached_on = False
    rails = None
    for _ in range(20):        # ~20 ms budget; t_D(ON) 8ms + soft ~1.07ms
        rails = _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
        if e.switch_state("REGEN") == "ON":
            reached_on = True
            break
    assert reached_on, (
        f"REGEN never reached ON within 20 ms (state={e.switch_state('REGEN')}); "
        "this is exactly the old-code regression the fix addresses")
    assert e.switches["REGEN"].cut_count == cut_before, "expected zero scp_cut events"
    assert rails["V_chg"] == pytest.approx(v_bus_before, abs=0.5)


def test_fc_charge_reaches_on_from_regulated_bus_with_zero_scp_cuts():
    """FC_CHARGE's input node is V-BUS directly.  Same old-code failure mode
    as REGEN above (5.6 nF CSS, tON ~1.07 ms, fold-active the whole ramp
    under the stale-target form) — this test would have failed under the
    old code (never ON, cut_count > cut_before)."""
    e = he.ElectricalSim(trace_config="short")
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = AUX_FC_REG | AUX_BT_REG
    _settle(e, sw, aux, 500)
    v_bus_before = e.node_voltage("BUS")

    cut_before = e.switches["FC_CHARGE"].cut_count
    sw |= SW_FC_CHARGE
    reached_on = False
    rails = None
    for _ in range(20):
        rails = _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
        if e.switch_state("FC_CHARGE") == "ON":
            reached_on = True
            break
    assert reached_on, (
        f"FC_CHARGE never reached ON within 20 ms (state={e.switch_state('FC_CHARGE')})")
    assert e.switches["FC_CHARGE"].cut_count == cut_before
    assert rails["V_chg"] == pytest.approx(v_bus_before, abs=0.5)


def test_precharge_current_is_physical_not_fictitious_amps():
    """Regression pin for today's bench FAULT_OC_FC: from dark, close
    FC_BUS + BT_BUS with the boosts OFF (body-diode-only precharge of the
    boost-output nodes / V-BUS).  LIMIT_I_FC_MAX is 1.4 A in firmware; the
    physical inrush is C*dV/dt on the order of tens of mA.

    Under the OLD stale-target form, self.i (the INA253 sense point for
    FC_BUS/BT_BUS) carried the rate*h/R skew — "enough fictitious I_fc to
    latch FAULT_OC_FC ... on a production HIL boot" per the module
    docstring — so |I_fc| would have spiked well past 0.3 A (indeed past the
    1.4 A firmware limit) during precharge under the old code.
    """
    e = he.ElectricalSim(trace_config="short")
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = 0        # boosts OFF: pure body-diode precharge
    peak_i_fc = peak_i_bt = 0.0
    for _ in range(60):     # well past both switches' t_D(ON)+soft-start
        rails = _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
        peak_i_fc = max(peak_i_fc, abs(rails["I_fc"]))
        peak_i_bt = max(peak_i_bt, abs(rails["I_batt"]))
    assert peak_i_fc < 0.3, f"I_fc precharge peak {peak_i_fc:.3f} A"
    assert peak_i_bt < 0.3, f"I_batt precharge peak {peak_i_bt:.3f} A"
    assert e.switch_state("FC_BUS") == "ON"
    assert e.switch_state("BT_BUS") == "ON"
    assert e.switches["FC_BUS"].cut_count == 0
    assert e.switches["BT_BUS"].cut_count == 0


def test_full_bringup_current_ceiling_stays_under_1p2a():
    """P0 close bus switches -> P1 enable boosts -> close MOT_PWR (no aux
    load): every sampled |I_fc|/|I_batt| stays under 1.2 A across the whole
    staged bring-up.  Under the old stale-target form the SOFT-state
    current on FC_BUS/BT_BUS (100 nF, tON ~19.8 ms) would read the
    per-substep rate*h/R skew for a large fraction of that ramp, well above
    1.2 A (the module docstring cites a ~36 A example at h=50 us)."""
    e = he.ElectricalSim(trace_config="short")
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = 0
    samples = []

    for _ in range(50):        # P0: bus switches only
        samples.append(_pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux)))

    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(400):       # P1: boosts enabled
        samples.append(_pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux)))

    sw |= SW_MOT_PWR
    for _ in range(400):       # close MOT_PWR
        samples.append(_pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux)))

    worst_fc = max(abs(r["I_fc"]) for r in samples)
    worst_bt = max(abs(r["I_batt"]) for r in samples)
    assert worst_fc < 1.2, f"worst I_fc {worst_fc:.3f} A during bring-up"
    assert worst_bt < 1.2, f"worst I_batt {worst_bt:.3f} A during bring-up"


def test_genuine_overload_still_folds_and_cuts_then_recovers_on_retry():
    """MOT_PWR closing into a large VESC cap (0.9 mF) PLUS a heavy motor
    draw is a GENUINE overload: the node cannot track the soft-start ramp,
    the demand crosses the foldback limit on physics (not discretization),
    and MOT_PWR must still SCP-cut after ~250 us of continuous fold-active
    clamping.  This is the fix's own claim (docstring: "a genuine overload
    still folds and cuts... on physics rather than on discretization") —
    a test suite that only checked the false-cut fix without this would not
    catch a fix that went too far and disabled foldback altogether."""
    e = he.ElectricalSim(trace_config="short", c_vesc_f=0.9e-3)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = AUX_FC_REG | AUX_BT_REG
    _settle(e, sw, aux, 500)

    sw |= SW_MOT_PWR
    heavy_i = 40.0     # A: enough sustained draw to hold V-MOT down and
                        # keep the ramp from tracking (a genuine overload,
                        # not a discretization artifact)
    cut_before = e.switches["MOT_PWR"].cut_count
    scp_events = []
    for _ in range(800):       # 800 ms budget to observe the first cut
        _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux, i_motor_a=heavy_i))
        scp_events = [ev for ev in e.events
                      if ev["kind"] == "scp_cut" and ev["switch"] == "MOT_PWR"]
        if scp_events:
            break
    assert scp_events, "genuine overload never tripped an SCP cut on MOT_PWR"
    assert scp_events[0]["cut_count"] == cut_before + 1

    # Release the overload and let the 64 ms auto-retry bring it up cleanly.
    reached_on = False
    for _ in range(300):       # 300 ms: several retry windows
        _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux, i_motor_a=0.0))
        if e.switch_state("MOT_PWR") == "ON":
            reached_on = True
            break
    assert reached_on, "MOT_PWR never recovered to ON after the overload was released"


def test_persistent_hard_short_never_reaches_on():
    """A held-down node (huge sustained load, never released) must stay in
    the cut/retry cycle indefinitely — never ON.  Companion to the recovery
    half above: confirms the fix did not turn foldback into a one-shot
    formality that always eventually lets a short through."""
    e = he.ElectricalSim(trace_config="short", c_vesc_f=0.9e-3)
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = AUX_FC_REG | AUX_BT_REG
    _settle(e, sw, aux, 500)

    sw |= SW_MOT_PWR
    heavy_i = 1000.0   # A: a persistent hard short, never released
    for _ in range(2000):      # 2 s: several retry cycles
        _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux, i_motor_a=heavy_i))
    assert e.switch_state("MOT_PWR") != "ON"
    assert e.switches["MOT_PWR"].cut_count >= 2, "expected multiple retry cycles"


def test_soft_start_current_is_physical_and_bounded_below_1a():
    """During a healthy 100 nF SOFT ramp (FC_BUS charging C_VBUS from
    dark), self.i (the INA253 sense point, read via rails["I_fc"]) must
    stay physically small — bounded above by 1 A and below a loose
    multiple of the analytic ramp-displacement estimate c_load*rate — and
    NEVER the old amps-scale discretization artifact.

    Under the OLD stale-target form this is precisely the case the module
    docstring quantifies: "rate*h/R at 15 kV/s and h = 50 us is ~36 A,
    against a true C*rate of ~0.5 A" — i.e. the old code would have failed
    the `< 1.0` assertion below by roughly two orders of magnitude.
    """
    e = he.ElectricalSim(trace_config="short")
    sw = SW_FC_BUS
    aux = AUX_FC_REG
    max_i = 0.0
    v_in_at_soft = None
    for _ in range(60):        # covers t_D(ON) 8ms + soft-start ~19.8ms
        rails = _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
        if e.switch_state("FC_BUS") == "SOFT":
            if v_in_at_soft is None:
                v_in_at_soft = e.node_voltage("OFC")   # FC_BUS's n_in
            max_i = max(max_i, abs(rails["I_fc"]))
    assert v_in_at_soft is not None, "never observed SOFT — widen the window"
    assert max_i < 1.0, f"I_fc peaked at {max_i:.3f} A during SOFT — artifact-scale"
    assert max_i > 1e-4, "I_fc stayed exactly zero during SOFT — data path dead?"

    # Loose physical cross-check against the analytic ramp-displacement
    # estimate c_load*rate (deliberately loose: v_in itself drifts across
    # the sampled window as the boost regulates up, so this is order-of-
    # magnitude, not exact).
    # (v_in itself keeps rising across the sampled window as FC_BUS's own
    # input node charges, so the single-instant estimate below under-states
    # the true rate later in the ramp; the multiplier is widened accordingly
    # and is still an order-of-magnitude check, not a tight one.)
    t_on = he.rt1987_t_on_s(max(v_in_at_soft, 1.0), 100.0)
    rate_estimate = v_in_at_soft / t_on
    i_track_estimate = he.C_VBUS * rate_estimate
    assert i_track_estimate * 0.05 <= max_i <= i_track_estimate * 15.0, (
        f"max_i={max_i:.4f} A vs c_load*rate estimate={i_track_estimate:.4f} A")


def test_stamp_without_prior_update_h_zero_degrades_safely():
    """_h defaults to 0.0 until update() first runs.  A stamp() called on a
    fresh switch (never update()'d, _h still 0.0) must not raise, and the
    degradation must be toward SAFE — not toward the retired stale-target
    artifact.

    With _h == 0.0, t_prev = max(0, t_state - 0) == t_state, so
    frac_prev == frac and target_prev == target: the lag term collapses to
    (target - v_out)/R evaluated at ONE instant, exactly what the fix
    intends (same-instant target vs v_out), never the old rate*h/R skew
    (which required a genuine h > 0 gap between the two evaluations to
    exist at all). This documents the code's own degradation path rather
    than asserting a value the source does not commit to.
    """
    sw = he.Rt1987("T", 0, 1, css_nf=100.0, c_load_f=35e-6)
    assert sw._h == 0.0                    # never update()'d
    sw.state = "SOFT"
    sw.t_state = 5e-3
    sw.v_ss_start = 0.0
    v = [15.0, 3.0]
    G = [[0.0, 0.0], [0.0, 0.0]]
    J = [0.0, 0.0]
    sw.stamp(G, J, v, None)                # must not raise

    t_on = he.rt1987_t_on_s(15.0, 100.0)
    frac = min(1.0, sw.t_state / t_on)
    frac_prev = min(1.0, max(0.0, sw.t_state - sw._h) / t_on)
    assert frac_prev == frac               # same-instant degradation, confirmed

    assert math.isfinite(G[1][1]) and math.isfinite(J[1])
    assert G[1][1] > 0.0                   # a finite, sane conductance was stamped


# ─────────────────────────────────────────────────────────────────────────────
# SOFT-start pre-charged-node fix (2026-08-30c) — Rt1987._soft_operating_point()
# now derives tON from a PER-EPISODE VIN HIGH WATER MARK (self._ss_v_in_max)
# rather than the instantaneous v_in, but ONLY when the episode starts on a
# pre-charged node (v_ss_start > RT_SS_PRECHARGED_V). A cold start (v_ss_start
# ~ 0) keeps the original instantaneous-VIN expression bit-for-bit. See the
# module docstring at _soft_operating_point() for the full derivation and the
# two REJECTED fixes (skipping the stamp above target; latching tON at SOFT
# entry) — both are documented there as guard comments, not tested here.
# ─────────────────────────────────────────────────────────────────────────────

def test_soft_start_precharged_node_warm_regression_bounded():
    """THE WARM REGRESSION THIS ROUND WAS FOR. fw v23's between-run warm
    reset can close MOT_PWR onto V-MOT bled to ~4.4 V while the bus is live
    at ~15.6-15.8 V — a soft-start entry on a PRE-CHARGED node. Under the
    retired instantaneous-VIN tON, a sagging v_in shrank tON and grew the
    ramp rate (positive feedback): the module docstring measures the
    reported current at ~6.8x the physical displacement current standalone,
    enough to latch a spurious OC_FC 3 ms after Idle.

    Reproduced end to end through the real ElectricalSim/Rt1987 solve (not
    a hand-derived formula): bring the bus up normally (FC_BUS+BT_BUS+boosts,
    the default c_vesc_f -> MOT_PWR's c_load = C_MOT_LOCAL 470 uF +
    C_VESC_DEFAULT 500 uF = 970 uF, matching the item's c_load=970 uF), force
    V-MOT down to the bled 4.4 V figure, close MOT_PWR, and pin the substep
    count per the file's _pin_and_step convention. The physical bound is
    re-derived from the SAME public rt1987_t_on_s() helper the implementation
    uses (not a hand-copied constant), against the switch's own recorded
    v_ss_start/_ss_v_in_max, so it tracks the real episode rather than an
    assumed one."""
    e = he.ElectricalSim(trace_config="short")   # default c_vesc_f
    assert he.C_MOT_LOCAL + he.C_VESC_DEFAULT == pytest.approx(970e-6)

    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(500):
        _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
    v_bus = e.node_voltage("BUS")
    assert v_bus == pytest.approx(15.6, abs=0.3), (
        f"sanity: bus should be near its ~15.6 V nominal, got {v_bus:.3f} V")

    e.v[he.N_MOT] = 4.4    # simulate the bled V-MOT node (isolated OFF switch
                            # stamps nothing, so this holds until MOT_PWR closes)

    sw |= SW_MOT_PWR
    mot = e.switches["MOT_PWR"]
    peak_i = 0.0
    reached_soft = False
    for _ in range(30):    # t_D(ON) 8ms + several ms into the ramp
        _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
        if mot.state == "SOFT":
            reached_soft = True
            peak_i = max(peak_i, abs(mot.i))
    assert reached_soft, "MOT_PWR never reached SOFT within the window"
    assert mot.v_ss_start == pytest.approx(4.4, abs=0.5), (
        "sanity: v_ss_start should have captured the bled node")
    assert mot.v_ss_start > he.RT_SS_PRECHARGED_V, (
        "sanity: this must actually exercise the pre-charged path")

    t_on = he.rt1987_t_on_s(max(mot._ss_v_in_max, 1.0), mot.css_nf)
    rate = (max(0.0, mot._ss_v_in_max - mot.v_ss_start) / t_on) if t_on > 0 else 0.0
    i_track_bound = mot.c_load * rate    # i_load == 0 here (no i_motor_a driven)
    assert peak_i <= 1.2 * i_track_bound + 1e-6, (
        f"reported current {peak_i:.4f} A exceeds 1.2x the physical "
        f"displacement estimate {i_track_bound:.4f} A -- the positive-"
        f"feedback regression this fix closes")

    # MED-2 TIGHTENED (2026-08-30 short follow-up round): the counter used to
    # increment on EVERY call to _soft_operating_point() -- it is called TWICE
    # per substep (stamp() for the network contribution, update() for the
    # sense current) -- so it read ~2x high, AND it counted the SOFT-entry
    # tick itself, where v_out == target trivially (frac == 0, target ==
    # v_ss_start == v_out at the instant SOFT is entered) -- a definitional
    # artefact, not a genuine "node above its own ramp" event. `count=True` is
    # now passed ONLY from stamp() (the one call per substep per switch), and
    # is additionally gated on `self.t_state > 0.0` to skip that entry tick.
    # A cold/warm SOFT entry with no genuine runaway now records EXACTLY 0,
    # not merely "at most 1" -- this was previously a loose bound because the
    # old counter could not distinguish the boundary artefact from a real
    # excursion; now it can, so the bound is exact.
    assert mot._ss_above_target_max_v == pytest.approx(0.0, abs=1e-9)
    assert mot._ss_above_target_substeps == 0


def test_soft_start_cold_start_bringup_peaks_preserved():
    """Cold-start preservation: the 2026-08-30c fix's cold-start path (a
    fresh episode entering SOFT with v_ss_start ~ 0, i.e. NOT
    > RT_SS_PRECHARGED_V) is documented to keep the original
    instantaneous-VIN expression bit-for-bit — this pins the staged-
    bring-up-like cold episode's two peak currents as a REGRESSION
    CONTRACT: they are triple-corroborated on hardware and must not move
    now that the pre-charged branch exists alongside the cold one.

      P0 (FC_BUS+BT_BUS body-diode precharge, boosts OFF): peak I_fc ~0.222 A
      Full staged bring-up (P0 -> P1 boosts enabled -> MOT_PWR closes, no aux
      load): peak I_fc/I_batt ~0.474 A

    (Same scenario shape as test_precharge_current_is_physical_not_fictitious_
    amps / test_full_bringup_current_ceiling_stays_under_1p2a, which only
    assert loose upper bounds; this pins the actual converged values.)"""
    e = he.ElectricalSim(trace_config="short")
    sw = SW_FC_BUS | SW_BT_BUS | SW_BT_SEQ
    aux = 0
    p0_peak_fc = 0.0
    for _ in range(50):        # P0: bus switches only, boosts off
        rails = _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
        p0_peak_fc = max(p0_peak_fc, abs(rails["I_fc"]))
    assert p0_peak_fc == pytest.approx(0.2224, abs=2e-3)

    aux = AUX_FC_REG | AUX_BT_REG
    for _ in range(400):       # P1: boosts enabled
        _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))

    sw |= SW_MOT_PWR
    full_peak_fc = full_peak_bt = 0.0
    for _ in range(400):       # close MOT_PWR
        rails = _pin_and_step(e, 1e-3, _actuators(sw=sw, aux=aux))
        full_peak_fc = max(full_peak_fc, abs(rails["I_fc"]))
        full_peak_bt = max(full_peak_bt, abs(rails["I_batt"]))
    assert full_peak_fc == pytest.approx(0.4739, abs=2e-3)
    assert full_peak_bt == pytest.approx(0.4739, abs=2e-3)

    # Cold-start invariant this fix must not disturb: v_ss_start stays ~0 at
    # every SOFT entry in this scenario (nothing here is pre-charged), so the
    # per-episode high-water-mark branch never engages.
    for name in ("FC_BUS", "BT_BUS", "MOT_PWR"):
        assert e.switches[name].v_ss_start <= he.RT_SS_PRECHARGED_V, (
            f"{name}: this scenario is supposed to be all-cold-start "
            f"(v_ss_start={e.switches[name].v_ss_start:.3f} V)")
    # Re-verification (short follow-up round, item 4): the min(target, v_in)
    # cap that used to bound the ramp target was REMOVED this round (TRCB in
    # SOFT is its replacement, see below) -- confirm the cold-start pins
    # above and the warm-regression bound in
    # test_soft_start_precharged_node_warm_regression_bounded are unaffected
    # by that removal. Both are re-asserted verbatim in this file (not
    # merely re-run): neither test references the cap, both still pass, and
    # both were re-verified against the actual post-removal simulator output
    # rather than trusted from before the round.


# ─────────────────────────────────────────────────────────────────────────────
# SOFT-start review-fix round (2026-08-30, short follow-up): TRCB now runs in
# SOFT (not just ON), TD_ON->SOFT gains an admission gate on the reverse
# differential, and the min(target, v_in) cap tried in the prior round was
# REMOVED (its own defect: sank the servo conductance out of n_out with
# J[n_in] == 0 -- "charge annihilated", measured -94 A / -345 A). See
# Rt1987._soft_operating_point()'s and update()'s docstrings for the full
# derivation; these tests are unit-level (bare Rt1987, no network solve) for
# full control over v_in/v_out, matching the file's existing
# test_stamp_without_prior_update_h_zero_degrades_safely pattern.
# ─────────────────────────────────────────────────────────────────────────────

def test_trcb_fires_in_soft_on_reverse_differential():
    """TRCB is no longer an ON-only feature (DS 17.6: the fast reverse
    comparator trips within t_FRC whenever VIN-VOUT falls below V_FRC, with
    no restriction to post-soft-start). Mid-ramp (t_state > 0, well short of
    tON), a reverse differential (v_in - v_out < RT_V_REV) must: open the
    switch (state -> OFF), latch _restart_no_ss (the reactive standby-diode
    re-arm-without-soft-start path), zero self.i, and record a reverse_block
    event tagged during == 'soft_start'.

    v_in/v_out are both kept comfortably above RT_UVLO_V (3.175 V) so the
    unpowered path is not what is being exercised here -- this is
    specifically the SOFT-state TRCB branch, not a UVLO open."""
    sw = he.Rt1987("T", 0, 1, css_nf=100.0, c_load_f=35e-6)
    sw.state = "SOFT"
    sw.v_ss_start = 0.0
    sw._ss_v_in_max = 5.0
    sw.t_state = 5e-3                  # mid-ramp, not the entry tick
    v = [5.0, 6.0]                     # dv = -1.0, well past RT_V_REV (-0.050)
    assert v[0] > he.RT_UVLO_V and v[1] > he.RT_UVLO_V, "sanity: not a UVLO case"
    assert (v[0] - v[1]) < he.RT_V_REV

    # CRITICALLY: the stamp for THIS substep -- the one in which the reverse
    # differential is discovered -- must not imply a wild sink. This is
    # exactly the defect class the removed target-cap produced: J[n_in] is
    # the explicit current withdrawn from the input node, and it must stay
    # bounded (floored at 0, ceilinged by the foldback limit) regardless of
    # how far the ramp target has drifted from v_out.
    G = [[0.0, 0.0], [0.0, 0.0]]
    J = [0.0, 0.0]
    sw.stamp(G, J, v, True)
    assert math.isfinite(J[0]) and math.isfinite(J[1])
    assert -he.RT_I_FOLD_HIGH - 1e-6 <= J[0] <= 0.0, (
        f"J[n_in]={J[0]:.3f} A implies an out-of-band explicit current draw "
        f"-- the old -94 A/-345 A sink defect class")

    events = []
    sw.update(1e-3, v, True, events, t_now=0.1234, trace_l_nh=1.5)

    assert sw.state == "OFF"
    assert sw._restart_no_ss is True
    assert sw.i == 0.0

    reverse = [e for e in events if e["kind"] == "reverse_block"]
    assert len(reverse) == 1
    assert reverse[0]["switch"] == "T"
    assert reverse[0]["during"] == "soft_start"
    assert reverse[0]["dv"] == pytest.approx(v[0] - v[1])
    assert reverse[0]["dv"] < he.RT_V_REV


def test_trcb_in_soft_does_not_fire_on_a_forward_differential():
    """Converse/guard: a healthy forward differential mid-ramp must NOT trip
    TRCB -- confirms the new branch is gated correctly, not just always-open.

    v_out is chosen close to the analytic ramp target at this t_state (both
    computed the same way _soft_operating_point() does, via the public
    rt1987_t_on_s() helper) so the SCP foldback path is not what stops this
    test from staying in SOFT -- i.e. this isolates the TRCB gate alone,
    not an incidental fold trip from an artificially large tracking gap."""
    sw = he.Rt1987("T", 0, 1, css_nf=100.0, c_load_f=35e-6)
    sw.state = "SOFT"
    sw.v_ss_start = 0.0
    sw._ss_v_in_max = 15.0
    sw.t_state = 5e-3
    t_on = he.rt1987_t_on_s(15.0, 100.0)
    target = 15.0 * min(1.0, sw.t_state / t_on)
    v = [15.0, target]     # v_out tracking the ramp closely -- healthy, forward
    assert (v[0] - v[1]) > he.RT_V_REV
    events = []
    sw.update(1e-3, v, True, events, t_now=0.0, trace_l_nh=1.5)
    assert sw.state == "SOFT"
    assert not [e for e in events if e["kind"] == "reverse_block"]
    assert sw._restart_no_ss is False


def test_td_on_holds_past_rt_td_on_s_when_reverse_differential_present():
    """TD_ON -> SOFT admission gate (DS 17.4 condition 1): t_D(ON) elapsing
    is necessary but NOT sufficient. With VIN - VOUT held at -0.5 V (well
    past RT_V_REV), the switch must HOLD in TD_ON even after t_state runs
    well past RT_TD_ON_S (8 ms) -- pinning that it holds, not a specific
    duration, since the real part 'continuously monitors' rather than
    admitting on a timer alone."""
    sw = he.Rt1987("T", 0, 1, css_nf=100.0, c_load_f=35e-6)
    sw.state = "TD_ON"
    sw.t_state = 0.0
    v_reverse = [5.0, 5.5]      # dv = -0.5 V, inadmissible
    dt = 1e-3
    for _ in range(20):         # 20 ms, well past RT_TD_ON_S (8 ms)
        sw.update(dt, v_reverse, True, [], t_now=0.0, trace_l_nh=1.5)
    assert sw.t_state > he.RT_TD_ON_S
    assert sw.state == "TD_ON", (
        "must HOLD in TD_ON while VIN-VOUT < RT_V_REV, even long past RT_TD_ON_S")

    # Differential clears -> admitted into SOFT on the very next tick, no
    # further wait once RT_TD_ON_S has already elapsed.
    v_clear = [5.5, 5.0]        # dv = +0.5 V, admissible
    sw.update(dt, v_clear, True, [], t_now=0.0, trace_l_nh=1.5)
    assert sw.state == "SOFT"
    assert sw.v_ss_start == pytest.approx(5.0)      # v_out at the instant of entry
    assert sw._ss_v_in_max == pytest.approx(5.5)    # v_in at the instant of entry


def test_td_on_enters_soft_immediately_when_differential_already_admissible():
    """Guard/converse: the ordinary case -- the differential is admissible
    from the start, so SOFT is entered exactly at t_state == RT_TD_ON_S, not
    delayed."""
    sw = he.Rt1987("T", 0, 1, css_nf=100.0, c_load_f=35e-6)
    sw.state = "TD_ON"
    sw.t_state = 0.0
    v = [15.0, 0.5]      # dv = +14.5, admissible throughout
    dt = 1e-3
    for _ in range(7):   # 7 ms < RT_TD_ON_S (8 ms) -- must still be waiting
        sw.update(dt, v, True, [], t_now=0.0, trace_l_nh=1.5)
    assert sw.state == "TD_ON"
    sw.update(dt, v, True, [], t_now=0.0, trace_l_nh=1.5)   # 8th ms
    assert sw.state == "SOFT"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
