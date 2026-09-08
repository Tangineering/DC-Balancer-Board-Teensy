#!/usr/bin/env python3
"""
test_encoder_edge_script.py - edge-list invariants for tools/encoder_edge_script.py.

Run:  .venv_hil/Scripts/python.exe -m pytest tools/test_encoder_edge_script.py

Stdlib + pytest only.  What is asserted here is what the harness relies on:
monotone t_us, exact quarter-pitch lag on the nominal wheel, per-channel level
alternation, the geometry assertion actually failing on a divergence, and every
defect naming each altered edge in the manifest.
"""

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import encoder_edge_script as ees  # noqa: E402


# ---------------------------------------------------------------------------
# Geometry / constants
# ---------------------------------------------------------------------------

def test_geometry_matches_the_ino():
    geom = ees.assert_geometry_against_ino()
    assert geom["ENCODER_SLOTS_PER_REV"] == 90.0
    assert abs(geom["FLYWHEEL_RADIUS_M"] - 0.0762) < 1e-9
    # 2*pi*0.0762/90 = 5.3198 mm, the fw v18 figure quoted in the .ino changelog.
    assert abs(geom["ENC_SLOT_PITCH_M"] - 5.3198e-3) < 1e-7


def test_geometry_assertion_fires_on_a_divergence(tmp_path):
    fake = tmp_path / "fake.ino"
    fake.write_text("#define ENCODER_SLOTS_PER_REV 120.0f\n"
                    "#define FLYWHEEL_RADIUS_M    0.0762f\n", encoding="ascii")
    with pytest.raises(AssertionError):
        ees.assert_geometry_against_ino(str(fake))


def test_geometry_assertion_fires_on_a_missing_define(tmp_path):
    fake = tmp_path / "fake.ino"
    fake.write_text("// nothing here\n", encoding="ascii")
    with pytest.raises(AssertionError):
        ees.assert_geometry_against_ino(str(fake))


def test_mechanical_constants_are_imported_not_retyped():
    import hil_plant_sim as hps
    assert ees.M_EFF is hps.M_EFF
    assert ees.K_F is hps.K_F
    assert ees.F_COULOMB is hps.F_COULOMB
    assert ees.B_EFF is hps.B_EFF


# ---------------------------------------------------------------------------
# Mechanical law
# ---------------------------------------------------------------------------

def test_below_breakaway_the_wheel_does_not_move():
    # K_F * i = 0.7538 * 2.0 = 1.508 N < F_COULOMB 2.00 N
    vs, xs = ees.integrate_trajectory([2.0] * 500)
    assert abs(xs[-1]) < 1e-9
    assert abs(vs[-1]) < 1e-9


def test_terminal_velocity_matches_the_force_balance():
    i = 5.0
    vs, _ = ees.integrate_trajectory([i] * 60000)
    v_expect = (ees.K_F * i - ees.F_COULOMB) / ees.B_EFF
    assert abs(vs[-1] - v_expect) < 1e-3


def test_coast_decays_toward_zero():
    stream = [5.0] * 3000 + [0.0] * 6000
    vs, _ = ees.integrate_trajectory(stream)
    assert vs[3000] > 1.0
    assert vs[-1] < vs[3000]
    assert vs[-1] >= 0.0


# ---------------------------------------------------------------------------
# Nominal wheel
# ---------------------------------------------------------------------------

def _nominal(duration=4.0, cruise_i=5.0, **kw):
    return ees.build(profile="cruise", duration_s=duration, cruise_i=cruise_i, **kw)


def test_edges_are_time_sorted():
    events, _ = _nominal()
    ts = [e["t_us"] for e in events]
    assert ts == sorted(ts)


def test_each_channel_alternates_levels():
    events, _ = _nominal()
    for ch in ("A", "B"):
        levels = [e["level"] for e in events if e["channel"] == ch]
        assert len(levels) > 20
        for a, b in zip(levels, levels[1:]):
            assert a != b, "channel %s emitted two identical levels in a row" % ch


def test_both_channels_produce_the_same_edge_count_within_one():
    events, _ = _nominal()
    na = sum(1 for e in events if e["channel"] == "A")
    nb = sum(1 for e in events if e["channel"] == "B")
    assert abs(na - nb) <= 1


def test_nominal_lag_is_exactly_a_quarter_pitch():
    """B rising follows A rising by 0.25 pitch of travel, at every slot."""
    events, _ = _nominal()
    a_rises = [e for e in events if e["channel"] == "A" and e["level"] == 1]
    b_rises = [e for e in events if e["channel"] == "B" and e["level"] == 1]
    # u is the crossing position in pitches: A at integers, B at integers + 0.25.
    for e in a_rises:
        assert abs(e["u"] - round(e["u"])) < 1e-9
    for e in b_rises:
        assert abs((e["u"] % 1.0) - 0.25) < 1e-9
    # Pair by position: every A rise at u = n has a B rise at u = n + 0.25 that
    # follows it in time.  (The run starts at u = 0 with A already high, so the
    # first emitted B rise at u = 0.25 has no A partner in the list.)
    b_by_u = {round(e["u"], 9): e for e in b_rises}
    paired = 0
    for a in a_rises:
        b = b_by_u.get(round(a["u"] + 0.25, 9))
        if b is None:
            continue
        paired += 1
        assert b["t_us"] >= a["t_us"]
    assert paired >= len(a_rises) - 1


def test_duty_is_fifty_percent_on_both_channels():
    """A falling edge sits half a pitch after its rising edge, by construction."""
    events, _ = _nominal()
    for ch in ("A", "B"):
        chan = [e for e in events if e["channel"] == ch]
        for r, f in zip(chan, chan[1:]):
            if r["level"] == 1 and f["level"] == 0:
                assert abs((f["u"] - r["u"]) - 0.5) < 1e-9


def test_a_leads_b_forward():
    """Forward travel puts every B rise a quarter pitch AFTER the A rise of its
    own slot, i.e. A leads B - the mount convention doEncoderB() documents."""
    events, _ = _nominal()
    a_rises = {round(e["u"], 9): e for e in events if e["channel"] == "A" and e["level"] == 1}
    b_rises = [e for e in events if e["channel"] == "B" and e["level"] == 1]
    checked = 0
    for b in b_rises:
        a = a_rises.get(round(b["u"] - 0.25, 9))
        if a is None:
            continue
        checked += 1
        assert a["t_us"] <= b["t_us"]
    assert checked >= len(b_rises) - 1


def test_slot_index_increases_monotonically_forward():
    events, _ = _nominal()
    slots = [e["slot"] for e in events]
    assert slots == sorted(slots)
    assert slots[-1] > 30


def test_edge_count_matches_the_distance_travelled():
    events, manifest = _nominal()
    slots = manifest["trajectory"]["slots_travelled"]
    # 2 edges per channel per pitch = 4 total.
    assert abs(len(events) - 4.0 * slots) <= 4


# ---------------------------------------------------------------------------
# Defects
# ---------------------------------------------------------------------------

def test_phase_offset_moves_only_channel_b():
    base, _ = _nominal()
    off, _ = _nominal(phase_offset_deg=30.0)
    a_base = [(e["t_us"], e["level"]) for e in base if e["channel"] == "A"]
    a_off = [(e["t_us"], e["level"]) for e in off if e["channel"] == "A"]
    assert a_base == a_off
    b_rises = [e for e in off if e["channel"] == "B" and e["level"] == 1]
    for e in b_rises:
        assert abs((e["u"] % 1.0) - (30.0 / 360.0)) < 1e-9


def test_phase_offset_beyond_180_reverses_the_apparent_lead():
    """At 270 deg B leads A: the decode direction is the thing that flips."""
    off, _ = _nominal(phase_offset_deg=270.0)
    b_rises = [e for e in off if e["channel"] == "B" and e["level"] == 1]
    for e in b_rises:
        assert abs((e["u"] % 1.0) - 0.75) < 1e-9


def test_missing_slot_removes_both_channels_and_is_manifested():
    events, manifest = _nominal(missing_slot=20, missing_run=1)
    assert all(e["slot"] != 20 for e in events)
    removed = manifest["altered_edges"]
    assert len(removed) == 4  # 2 edges x 2 channels
    assert {r["channel"] for r in removed} == {"A", "B"}
    assert all(r["action"] == "removed" and r["slot"] == 20 for r in removed)
    assert manifest["defects"]["missing_slots"] == {"k": 20, "n": 1}


def test_missing_run_removes_n_slots():
    events, manifest = _nominal(missing_slot=20, missing_run=4)
    assert all(not (20 <= e["slot"] < 24) for e in events)
    assert len(manifest["altered_edges"]) == 16


def test_missing_slot_doubles_the_a_rising_period():
    base, _ = _nominal()
    gone, _ = _nominal(missing_slot=30, missing_run=1)

    def a_rises(evs):
        return [e for e in evs if e["channel"] == "A" and e["level"] == 1]

    # The base stream's A rise at slot 30 and the period it opens.
    b_list = a_rises(base)
    i = next(j for j, e in enumerate(b_list) if e["slot"] == 30)
    t_29 = b_list[i - 1]["t_us"]
    t_30 = b_list[i]["t_us"]
    t_31 = b_list[i + 1]["t_us"]
    nominal_29 = t_30 - t_29
    # With slot 30 deleted, the interval from the slot-29 rise runs to slot 31.
    g_list = a_rises(gone)
    j = next(k for k, e in enumerate(g_list) if e["slot"] == 29)
    gap = g_list[j + 1]["t_us"] - g_list[j]["t_us"]
    assert g_list[j + 1]["slot"] == 31
    assert abs(gap - (t_31 - t_29)) <= 2
    # Two pitches of travel; at a constant speed that is 2x the neighbour period.
    assert 1.7 < gap / nominal_29 < 2.3


def test_bounce_inserts_a_fall_rise_pair_and_names_them():
    events, manifest = _nominal(bounce_slot=25, bounce_spacing_us=300)
    ins = [a for a in manifest["altered_edges"] if a["action"] == "inserted"]
    assert len(ins) == 2
    assert [i["level"] for i in ins] == [0, 1]
    assert all(i["channel"] == "A" and i["slot"] == 25 for i in ins)
    assert ins[1]["t_us"] - ins[0]["t_us"] == 300


def test_bounce_leaves_the_channel_a_level_sequence_valid():
    events, _ = _nominal(bounce_slot=25, bounce_spacing_us=300)
    levels = [e["level"] for e in events if e["channel"] == "A"]
    for a, b in zip(levels, levels[1:]):
        assert a != b


def test_bounce_at_an_absent_slot_raises():
    with pytest.raises(ValueError):
        _nominal(bounce_slot=100000)


def test_jitter_is_seeded_and_reproducible():
    e1, m1 = _nominal(jitter_us=40.0, jitter_seed=7)
    e2, m2 = _nominal(jitter_us=40.0, jitter_seed=7)
    e3, _ = _nominal(jitter_us=40.0, jitter_seed=8)
    assert [e["t_us"] for e in e1] == [e["t_us"] for e in e2]
    assert [e["t_us"] for e in e1] != [e["t_us"] for e in e3]
    assert m1["jitter_seed"] == 7
    assert m2["defects"]["edge_jitter_us"]["amp_us"] == 40.0


def test_jitter_is_bounded_and_zero_mean_ish():
    _, m = _nominal(jitter_us=40.0, jitter_seed=3)
    deltas = [a["delta_us"] for a in m["altered_edges"] if a["action"] == "shifted"]
    assert len(deltas) > 100
    assert max(abs(d) for d in deltas) <= 41
    assert abs(sum(deltas) / len(deltas)) < 6.0


def test_jitter_keeps_the_list_sorted_and_channels_alternating():
    events, _ = _nominal(jitter_us=40.0, jitter_seed=5)
    ts = [e["t_us"] for e in events]
    assert ts == sorted(ts)
    for ch in ("A", "B"):
        levels = [e["level"] for e in events if e["channel"] == ch]
        for a, b in zip(levels, levels[1:]):
            assert a != b


def test_dropout_window_empties_its_span():
    events, manifest = _nominal(dropout_start_us=1_000_000, dropout_end_us=1_500_000)
    assert not any(1_000_000 <= e["t_us"] < 1_500_000 for e in events)
    assert len(manifest["altered_edges"]) > 0
    assert all(a["action"] == "removed" for a in manifest["altered_edges"])
    assert manifest["defects"]["dropout_window"]["end_us"] == 1_500_000


def test_defects_compose():
    events, manifest = _nominal(missing_slot=20, missing_run=2,
                                bounce_slot=40, bounce_spacing_us=250,
                                jitter_us=10.0, jitter_seed=2)
    d = manifest["defects"]
    assert set(d) == {"missing_slots", "bounce_slots", "edge_jitter_us"}
    assert manifest["edge_counts"]["altered"] > 0


# ---------------------------------------------------------------------------
# Manifest / emission
# ---------------------------------------------------------------------------

def test_manifest_is_json_serialisable_and_records_provenance():
    _, manifest = _nominal(missing_slot=15)
    text = json.dumps(manifest)
    assert "hil_plant_sim.py" in text
    assert manifest["mechanical_constants"]["M_EFF"] == ees.M_EFF
    assert manifest["geometry"]["ENCODER_SLOTS_PER_REV"] == 90.0


def test_cli_writes_both_files(tmp_path):
    stem = str(tmp_path / "run")
    rc = ees.main(["--profile", "cruise", "--duration", "2.0", "--cruise-i", "5.0",
                   "--missing-slots", "10", "--out", stem])
    assert rc == 0
    assert os.path.isfile(stem + "_edges.csv")
    assert os.path.isfile(stem + "_manifest.json")
    with open(stem + "_edges.csv", encoding="ascii") as fh:
        head = fh.readline().strip()
    assert head == "t_us,channel,level,slot"
    with open(stem + "_manifest.json", encoding="ascii") as fh:
        m = json.load(fh)
    assert m["defects"]["missing_slots"]["k"] == 10


def test_channel_level_law():
    assert ees.channel_level(0.0, 0.0) == 1
    assert ees.channel_level(0.49, 0.0) == 1
    assert ees.channel_level(0.51, 0.0) == 0
    assert ees.channel_level(0.25, 0.25) == 1
    assert ees.channel_level(0.24, 0.25) == 0


def test_slot_pitch_constant():
    assert abs(ees.SLOT_PITCH_M - (2 * math.pi * 0.0762 / 90.0)) < 1e-15


# ---------------------------------------------------------------------------
# The mechanical law is the PLANT'S, not a re-derivation (fix round F2)
# ---------------------------------------------------------------------------
# `step_velocity()` is a port of the `k_air == 0.0` (rig-profile) branch of
# `hil_plant_sim.Plant.step`.  An earlier version was a re-derivation and diverged
# in three places: it used `abs(v) > V_STICTION` for the moving branch, it decayed
# a sub-stiction velocity viscously instead of zeroing it, and it inhibited the
# friction zero-crossing whenever `abs(f_drive) <= F_COULOMB` rather than only at
# `f_drive == 0.0` exactly.  The last of those changes the trajectory of every
# stiction crossing under a small non-zero drive, which is exactly the coast-down
# and reversal regime the encoder harness sweeps.  These tests step BOTH laws from
# identical states and demand identical trajectories.

import hil_plant_sim as hps  # noqa: E402  (path set at the top of this file)

# The breakaway current: the drive at which K_F*i exactly equals F_COULOMB.
F_BREAKAWAY_A = ees.F_COULOMB / ees.K_F


def _plant_reference_trajectory(v0, i_stream, dt=ees.DT_S):
    """Drive hil_plant_sim.Plant's own step() and return the velocity after each tick."""
    p = hps.Plant()
    p.v = v0
    out = []
    for i_cmd in i_stream:
        # The mechanical branch is gated on `mot_live and bus_up`; hold the bus above
        # the 5 V gate every tick so the force term is never suppressed by the
        # ELECTRICAL model (which this port does not reproduce and does not need to).
        p.v_bus = 16.0
        obs = {"switch": hps.SW_FC_BUS | hps.SW_BT_BUS | hps.SW_MOT_PWR,
               "aux": hps.AUX_FC_REG | hps.AUX_BT_REG,
               "current": i_cmd, "mdac_fc": 2048, "mdac_bt": 2048}
        p.step(dt, obs)
        out.append(p.v)
    return out


def _port_trajectory(v0, i_stream, dt=ees.DT_S):
    v = v0
    out = []
    for i_cmd in i_stream:
        v = ees.step_velocity(v, i_cmd, dt)
        out.append(v)
    return out


# Each case is (name, v0, i_cmd stream).  The plant clips the REGEN side of the
# command at VESC_REGEN_I_MAX_A = 1.5 A before it becomes force, so every braking
# current below is inside that clip and the two laws see the same f_drive.
_STICTION_CASES = [
    # A coast with NO drive at all: the `f_drive == 0.0` zero-crossing inhibit is
    # the only thing that stops friction dragging the body backwards.
    ("coast to rest", 0.30, [0.0] * 600),
    # THE CASE THAT SEPARATED THE OLD PORTS: braking through zero under a small but
    # NON-zero drive.  |f_drive| = 0.7538*1.0 = 0.754 N <= F_COULOMB = 2.0 N, so the
    # re-derivation's inhibit fired and pinned the body at zero; the plant does not.
    ("brake through zero, sub-Coulomb drive", 0.30, [-1.0] * 800),
    # The drive exactly AT the breakaway force, on the drive side (the plant clips the
    # regen side at VESC_REGEN_I_MAX_A = 1.5 A, and F_BREAKAWAY_A is 2.65 A, so this
    # current is only representable on the drive side).  `abs(f_drive) <= F_COULOMB`
    # is TRUE at exactly the breakaway, so the deadband holds and nothing moves.
    ("hold at exactly the breakaway force", 0.0, [F_BREAKAWAY_A] * 200),
    # Launch from rest through the deadband, then brake back through it.
    ("launch and brake back", 0.0, [4.0] * 400 + [-1.2] * 900),
    # Start INSIDE the stiction band under a sub-breakaway drive: the plant zeroes
    # the velocity outright, the re-derivation decayed it viscously.
    ("held inside the deadband", 0.015, [1.0] * 50 + [0.0] * 50),
    # Negative-going mirror of the coast.
    ("reverse coast to rest", -0.30, [0.0] * 600),
]


@pytest.mark.parametrize("name,v0,stream", _STICTION_CASES,
                         ids=[c[0] for c in _STICTION_CASES])
def test_step_velocity_matches_plant_reference(name, v0, stream):
    ref = _plant_reference_trajectory(v0, stream)
    got = _port_trajectory(v0, stream)
    assert len(ref) == len(got)
    for k, (a, b) in enumerate(zip(ref, got)):
        assert a == b, ("%s: tick %d diverges: plant %.17g vs port %.17g"
                        % (name, k, a, b))


def test_the_stiction_cases_actually_reach_rest():
    """A guard on the guard: if no case reached zero, the equivalence test above
    would pass on a law that never exercises the deadband branch at all."""
    reached = 0
    for _name, v0, stream in _STICTION_CASES:
        traj = [v0] + _port_trajectory(v0, stream)
        if any(v == 0.0 for v in traj[1:]):
            reached += 1
    assert reached == len(_STICTION_CASES)


def test_the_deadband_zeroes_the_velocity_it_does_not_decay_it():
    """The reachable half of the re-derivation's divergence.  Inside V_STICTION with a
    sub-breakaway drive the plant sets `f_net = 0` AND `v = 0` in ONE step; the
    re-derivation set `f_net = -B_EFF*v` and let the velocity decay over many ticks,
    which under the encoder geometry is the difference between a wheel that stops and
    one that keeps emitting edges."""
    v0 = 0.015                       # inside V_STICTION = 0.02
    assert abs(ees.K_F * 1.0) <= ees.F_COULOMB
    assert ees.step_velocity(v0, 1.0) == 0.0
    assert ees.step_velocity(v0, 0.0) == 0.0
    assert ees.step_velocity(-v0, 0.0) == 0.0
    # Above the breakaway the deadband releases and the body accelerates.
    assert ees.step_velocity(v0, 4.0) > v0


def test_the_crossing_inhibit_is_gated_on_exactly_zero_drive():
    """The other half: the inhibit lives in the MOVING branch and tests `f_drive == 0.0`
    exactly, not `abs(f_drive) <= F_COULOMB`.  At these constants the deadband catches a
    decelerating body before the moving branch can step it through zero, so the two
    forms are behaviourally equivalent on the reachable set - but the port must still
    carry the plant's form, because a future F_COULOMB or dt change makes them differ.
    Asserted structurally: a coast from rest-adjacent speed never reverses, and the
    inhibit never fires when the drive is non-zero (the body is stopped by the
    DEADBAND, i.e. from inside V_STICTION, never from a moving-branch crossing)."""
    traj = [0.30] + _port_trajectory(0.30, [0.0] * 800)
    assert all(v >= 0.0 for v in traj), \
        "with f_drive == 0 exactly, friction alone must never reverse the body"
    # Under a sub-Coulomb braking drive the body still never reverses, but the tick that
    # zeroes it must be one that ENTERED the deadband, not a moving-branch crossing.
    prev = 0.30
    stopped_from = None
    for v in _port_trajectory(0.30, [-1.0] * 800):
        if v == 0.0 and prev != 0.0:
            stopped_from = prev
            break
        prev = v
    assert stopped_from is not None
    assert abs(stopped_from) < ees.V_STICTION, \
        "the body must come to rest via the deadband, not a moving-branch crossing"
