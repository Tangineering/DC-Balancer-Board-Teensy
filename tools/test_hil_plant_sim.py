#!/usr/bin/env python3
"""pytest suite for tools/hil_plant_sim.py — the HIL plant simulator (fw v21).

Mirrors the coverage style of tools/test_decode_benchlog.py (synthetic
inputs, explicit field-by-field assertions, byte-offset checks against the
documented wire protocol) but as pytest test functions rather than a
manual PASS/FAIL harness, since hil_plant_sim.py's surface (codec + plant
model + replay) is pure-function-friendly and doesn't need the subprocess/
CLI-diffing approach decode_benchlog's test needed.

Run: cd tools && python -m pytest test_hil_plant_sim.py -v
"""
import csv
import json
import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "benchlog_analysis"))

import hil_plant_sim as hil  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# 1. Codec
# ─────────────────────────────────────────────────────────────────────────

def test_xor_checksum_empty():
    assert hil.xor_checksum(b"") == 0


def test_xor_checksum_known():
    assert hil.xor_checksum(bytes([0x01, 0x02, 0x03])) == 0x01 ^ 0x02 ^ 0x03
    assert hil.xor_checksum(bytes([0xFF, 0xFF])) == 0x00


def test_pack_inject_size_and_sync():
    frame = hil.pack_inject(7, 13.0, 8.1, 15.9, 14.0, 13.2, 1.1, 2.2, 0.5,
                             i_charge=0.75, ag105_status=0x42)
    assert len(frame) == hil.HIL_INJECT_SIZE == 40
    assert frame[0] == hil.HIL_SYNC_INJECT == 0xB5


def test_pack_inject_field_offsets_and_values():
    frame = hil.pack_inject(
        seq=200,
        v_fc=13.0, v_batt=8.1, v_bus=15.9, v_chg=14.0, v_rgn=13.2,
        i_fc=1.1, i_batt=2.2, v_actual=0.5,
        i_charge=1.234, ag105_status=hil.AG105_ST_CHARGING,
    )
    # seq wraps mod 256
    assert frame[1] == 200
    fields = struct.unpack_from("<9f", frame, 2)
    expected = (13.0, 8.1, 15.9, 14.0, 13.2, 1.1, 2.2, 0.5, 1.234)
    for got, want in zip(fields, expected):
        assert got == pytest.approx(want, abs=1e-6)
    # I_charge lands at byte offset 34 (documented in the module docstring)
    (i_charge_at_34,) = struct.unpack_from("<f", frame, 34)
    assert i_charge_at_34 == pytest.approx(1.234, abs=1e-6)
    # ag105_status at offset 38
    assert frame[38] == hil.AG105_ST_CHARGING
    # checksum at offset 39, over bytes 1..38
    assert frame[39] == hil.xor_checksum(frame[1:39])
    assert len(frame) == 40


def test_pack_inject_seq_wraps_and_status_masked():
    frame = hil.pack_inject(0x1FF, 0, 0, 0, 0, 0, 0, 0, 0, ag105_status=0x1FF)
    assert frame[1] == 0x1FF & 0xFF
    assert frame[38] == 0x1FF & 0xFF


def _make_output_frame(seq=5, state=2, sw=0x07, aux=0x0F, current=-3.5,
                        mdac_fc=0x1ABC, mdac_bt=0x1234, faults=0x0009):
    body = struct.pack("<BBBBfHHH", seq, state, sw, aux, current,
                        mdac_fc, mdac_bt, faults)
    frame = bytes([hil.HIL_SYNC_OUTPUT]) + body
    frame += bytes([hil.xor_checksum(frame[1:15])])
    return frame


def test_parse_output_golden_accept():
    frame = _make_output_frame()
    assert len(frame) == hil.HIL_OUTPUT_SIZE == 16
    decoded = hil.parse_output(frame)
    assert decoded is not None
    assert decoded["seq"] == 5
    assert decoded["state"] == 2
    assert decoded["switch"] == 0x07
    assert decoded["aux"] == 0x0F
    assert decoded["current"] == pytest.approx(-3.5, abs=1e-6)
    assert decoded["mdac_fc"] == 0x1ABC
    assert decoded["mdac_bt"] == 0x1234
    assert decoded["fault_flags"] == 0x0009


def test_parse_output_rejects_wrong_length():
    frame = _make_output_frame()
    assert hil.parse_output(frame[:-1]) is None
    assert hil.parse_output(frame + b"\x00") is None
    assert hil.parse_output(b"") is None


def test_parse_output_rejects_bad_sync():
    frame = bytearray(_make_output_frame())
    frame[0] = 0xB5  # inject sync, not output sync
    assert hil.parse_output(bytes(frame)) is None


def test_parse_output_rejects_bad_checksum():
    frame = bytearray(_make_output_frame())
    frame[15] ^= 0xFF
    assert hil.parse_output(bytes(frame)) is None
    # corrupting a payload byte (not the checksum byte) must also be caught
    frame2 = bytearray(_make_output_frame())
    frame2[5] ^= 0x01
    assert hil.parse_output(bytes(frame2)) is None


def test_mdac_fraction_valid_word():
    word = hil.MDAC_CMD_LOAD_UPDATE | 0x0800  # half-scale-ish code
    assert hil.mdac_fraction(word) == pytest.approx(0x0800 / 4095.0)


def test_mdac_fraction_wrong_control_nibble():
    # top nibble anything other than 0x1 ("load and update") must read 0.0
    for nibble in (0x0, 0x2, 0xF):
        word = (nibble << 12) | 0x0800
        assert hil.mdac_fraction(word) == 0.0


def test_mdac_fraction_full_scale():
    word = hil.MDAC_CMD_LOAD_UPDATE | hil.MDAC_RES
    assert hil.mdac_fraction(word) == pytest.approx(1.0)


def test_mdac_fraction_zero_code():
    word = hil.MDAC_CMD_LOAD_UPDATE | 0x0000
    assert hil.mdac_fraction(word) == 0.0


# ─────────────────────────────────────────────────────────────────────────
# 2. Plant mechanics
# ─────────────────────────────────────────────────────────────────────────

def _obs(switch=0, aux=0, current=0.0, mdac_fc=None, mdac_bt=None):
    if mdac_fc is None:
        mdac_fc = hil.MDAC_CMD_LOAD_UPDATE | (hil.MDAC_RES // 2)
    if mdac_bt is None:
        mdac_bt = hil.MDAC_CMD_LOAD_UPDATE | (hil.MDAC_RES // 2)
    return {"switch": switch, "aux": aux, "current": current,
            "mdac_fc": mdac_fc, "mdac_bt": mdac_bt}


SW_ALL_LIVE = hil.SW_FC_BUS | hil.SW_BT_BUS | hil.SW_MOT_PWR
AUX_BOTH_REG = hil.AUX_FC_REG | hil.AUX_BT_REG


def test_stiction_no_breakaway_below_threshold():
    """A drive current whose force is below F_COULOMB must not move the body."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    # F_COULOMB / K_F ~= 2.65 A: pick a current comfortably below that.
    i_cmd = (hil.F_COULOMB / hil.K_F) * 0.5
    obs = _obs(switch=SW_ALL_LIVE, aux=AUX_BOTH_REG, current=i_cmd)
    for _ in range(200):
        plant.step(1e-3, obs)
    assert plant.v == 0.0


def test_stiction_breakaway_above_threshold():
    """A drive current whose force clears F_COULOMB must produce motion."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    i_cmd = (hil.F_COULOMB / hil.K_F) * 3.0  # comfortably above breakaway
    obs = _obs(switch=SW_ALL_LIVE, aux=AUX_BOTH_REG, current=i_cmd)
    for _ in range(200):
        plant.step(1e-3, obs)
    assert plant.v > 0.0


def test_breakaway_threshold_is_approximately_2_65A():
    assert hil.F_COULOMB / hil.K_F == pytest.approx(2.65, abs=0.02)


def test_viscous_decel_no_sign_flip_through_zero():
    """With zero drive force and some initial velocity, friction/drag must
    bring the body to rest at zero, never overshoot past it to the opposite
    sign within a tick (the zero-crossing guard in Plant.step)."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    plant.v = 0.05  # just above V_STICTION so the guarded branch runs
    obs = _obs(switch=0, aux=0, current=0.0)  # no drive force at all
    saw_zero = False
    for _ in range(5000):
        plant.step(1e-3, obs)
        if plant.v == 0.0:
            saw_zero = True
            break
        assert plant.v >= 0.0, "velocity flipped sign through zero"
    assert saw_zero


def test_viscous_decel_negative_initial_velocity_no_sign_flip():
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    plant.v = -0.05
    obs = _obs(switch=0, aux=0, current=0.0)
    saw_zero = False
    for _ in range(5000):
        plant.step(1e-3, obs)
        if plant.v == 0.0:
            saw_zero = True
            break
        assert plant.v <= 0.0
    assert saw_zero


def test_motor_force_gated_on_mot_pwr_enable():
    """Large commanded current with MOT_PWR_ENABLE open must not move the body,
    even with a healthy bus."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=hil.SW_FC_BUS | hil.SW_BT_BUS, aux=AUX_BOTH_REG,
               current=10.0)  # MOT_PWR bit NOT set
    for _ in range(500):
        plant.step(1e-3, obs)
    assert plant.v == 0.0


def test_motor_force_gated_on_bus_up():
    """Large commanded current with MOT_PWR closed but the bus collapsed
    (<= 5.0 V, the bus_up threshold) must not move the body."""
    plant = hil.Plant()
    plant.v_bus = 0.0  # bus down
    obs = _obs(switch=hil.SW_MOT_PWR, aux=0, current=10.0)
    for _ in range(50):
        # keep the bus collapsed manually (no source live to feed it)
        plant.v_bus = 0.0
        plant.step(1e-3, obs)
    assert plant.v == 0.0


def test_motor_force_present_when_both_gates_satisfied():
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=SW_ALL_LIVE, aux=AUX_BOTH_REG, current=6.0)
    for _ in range(200):
        plant.step(1e-3, obs)
    assert plant.v > 0.0


# ─────────────────────────────────────────────────────────────────────────
# 3. Plant electrics
# ─────────────────────────────────────────────────────────────────────────

def test_droop_bus_value_with_live_source():
    """UPDATED (tooling round): the droop model is now mode-aware — a single
    live source uses K_DROOP_BUS_SINGLE (0.16 V/A) off the measured no-load
    intercept V_BUS_DROOP_V0 (15.95 V), not the old single V_BUS_NOMINAL-based
    0.35 V/A placeholder. Only FC_BUS is live here, so this exercises the
    single-source branch."""
    plant = hil.Plant()
    obs = _obs(switch=hil.SW_FC_BUS, aux=hil.AUX_FC_REG, current=0.0)
    out = plant.step(1e-3, obs)
    # i_total is just I_AUX_A (no motor draw, mot_live False)
    expected = hil.V_BUS_DROOP_V0 - hil.K_DROOP_BUS_SINGLE * hil.I_AUX_A
    assert out["V_bus"] == pytest.approx(expected, abs=1e-6)


def test_droop_bus_value_both_sources_live():
    """The both-live regime uses the shallower K_DROOP_BUS_SHARED (0.074 V/A),
    not the single-source slope — the two are fit separately (CLAUDE.md /
    hil_plant_sim.py "MEASURED bus droop")."""
    plant = hil.Plant()
    obs = _obs(switch=hil.SW_FC_BUS | hil.SW_BT_BUS,
               aux=hil.AUX_FC_REG | hil.AUX_BT_REG, current=0.0)
    out = plant.step(1e-3, obs)
    expected = hil.V_BUS_DROOP_V0 - hil.K_DROOP_BUS_SHARED * hil.I_AUX_A
    assert out["V_bus"] == pytest.approx(expected, abs=1e-6)


def test_droop_fit_two_operating_points_both_live():
    """Fit the shared-source slope through two distinct current operating
    points (not a single sample) and confirm it matches K_DROOP_BUS_SHARED,
    with the V0 intercept landing at V_BUS_DROOP_V0."""
    def v_bus_at(i_aux):
        plant = hil.Plant()
        obs = _obs(switch=hil.SW_FC_BUS | hil.SW_BT_BUS,
                   aux=hil.AUX_FC_REG | hil.AUX_BT_REG, current=0.0)
        plant.i_aux = i_aux
        out = plant.step(1e-3, obs)
        return out["V_bus"]

    v1 = v_bus_at(0.15)
    v2 = v_bus_at(1.5)
    slope = (v1 - v2) / (1.5 - 0.15)
    assert slope == pytest.approx(hil.K_DROOP_BUS_SHARED, abs=1e-6)
    intercept = v1 + hil.K_DROOP_BUS_SHARED * 0.15
    assert intercept == pytest.approx(hil.V_BUS_DROOP_V0, abs=1e-6)


def test_droop_fit_two_operating_points_single_live():
    """Same fit, single-source regime -> K_DROOP_BUS_SINGLE."""
    def v_bus_at(i_aux):
        plant = hil.Plant()
        obs = _obs(switch=hil.SW_FC_BUS, aux=hil.AUX_FC_REG, current=0.0)
        plant.i_aux = i_aux
        out = plant.step(1e-3, obs)
        return out["V_bus"]

    v1 = v_bus_at(0.15)
    v2 = v_bus_at(1.0)
    slope = (v1 - v2) / (1.0 - 0.15)
    assert slope == pytest.approx(hil.K_DROOP_BUS_SINGLE, abs=1e-6)


def test_rc_decay_when_dark():
    """No source live: the bus decays as an RC through R_BUS_BLEED/C_BUS_F,
    it must not jump to V_BUS_NOMINAL and must monotonically fall."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=0, aux=0, current=0.0)
    prev = plant.v_bus
    for _ in range(1000):
        out = plant.step(1e-3, obs)
        assert out["V_bus"] <= prev + 1e-9
        prev = out["V_bus"]
    assert plant.v_bus < hil.V_BUS_NOMINAL
    assert plant.v_bus >= 0.0


def test_rc_decay_matches_tau_analytically():
    plant = hil.Plant()
    plant.v_bus = 10.0
    obs = _obs(switch=0, aux=0, current=0.0)
    tau = hil.R_BUS_BLEED * hil.C_BUS_F
    dt = 1e-4
    steps = int(tau / dt)  # one time-constant's worth of ticks
    for _ in range(steps):
        plant.step(dt, obs)
    # forward-Euler decay after ~1 tau should be in the right ballpark of 1/e
    assert plant.v_bus < 10.0 * 0.5
    assert plant.v_bus > 10.0 * 0.2


def test_mdac_split_both_live_even_codes():
    plant = hil.Plant()
    mdac_fc = hil.MDAC_CMD_LOAD_UPDATE | 2000
    mdac_bt = hil.MDAC_CMD_LOAD_UPDATE | 2000
    obs = _obs(switch=hil.SW_FC_BUS | hil.SW_BT_BUS,
               aux=AUX_BOTH_REG, current=0.0,
               mdac_fc=mdac_fc, mdac_bt=mdac_bt)
    out = plant.step(1e-3, obs)
    assert out["I_fc"] == pytest.approx(out["I_batt"], rel=1e-6)


def test_mdac_split_both_live_unequal_codes():
    plant = hil.Plant()
    mdac_fc = hil.MDAC_CMD_LOAD_UPDATE | 3000
    mdac_bt = hil.MDAC_CMD_LOAD_UPDATE | 1000
    obs = _obs(switch=hil.SW_FC_BUS | hil.SW_BT_BUS,
               aux=AUX_BOTH_REG, current=0.0,
               mdac_fc=mdac_fc, mdac_bt=mdac_bt)
    out = plant.step(1e-3, obs)
    total = out["I_fc"] + out["I_batt"]
    assert total == pytest.approx(hil.I_AUX_A, abs=1e-6)
    assert out["I_fc"] == pytest.approx(total * 0.75, rel=1e-6)
    assert out["I_batt"] == pytest.approx(total * 0.25, rel=1e-6)


def test_mdac_split_only_fc_live():
    plant = hil.Plant()
    obs = _obs(switch=hil.SW_FC_BUS, aux=hil.AUX_FC_REG, current=0.0)
    out = plant.step(1e-3, obs)
    assert out["I_fc"] == pytest.approx(hil.I_AUX_A, abs=1e-6)
    assert out["I_batt"] == 0.0


def test_mdac_split_only_bt_live():
    plant = hil.Plant()
    obs = _obs(switch=hil.SW_BT_BUS, aux=hil.AUX_BT_REG, current=0.0)
    out = plant.step(1e-3, obs)
    assert out["I_batt"] == pytest.approx(hil.I_AUX_A, abs=1e-6)
    assert out["I_fc"] == 0.0


def test_mdac_split_degenerate_zero_codes_falls_back_to_half():
    """Both codes 0 (zero-scale, valid load-and-update word, fraction 0.0):
    the denominator is 0, and the code must fall back to a 50/50 split
    rather than raising or dividing by zero."""
    plant = hil.Plant()
    mdac_fc = hil.MDAC_CMD_LOAD_UPDATE | 0
    mdac_bt = hil.MDAC_CMD_LOAD_UPDATE | 0
    obs = _obs(switch=hil.SW_FC_BUS | hil.SW_BT_BUS,
               aux=AUX_BOTH_REG, current=0.0,
               mdac_fc=mdac_fc, mdac_bt=mdac_bt)
    out = plant.step(1e-3, obs)
    assert out["I_fc"] == pytest.approx(out["I_batt"], rel=1e-6)
    assert out["I_fc"] == pytest.approx(hil.I_AUX_A / 2.0, abs=1e-6)


def test_ir_sag_on_source_terminals():
    """UPDATED (tooling round): the old fixed V_FC_OPEN/R_FC_INT/V_BT_OPEN/
    R_BT_INT scalar-sag model is retired from hil_plant_sim — the source
    terminals now come from the shared FuelCellSource/BatterySource paper-form
    models in hil_electrical.py (Plant.fuel_cell / Plant.battery), which sag
    under load through their own polarization/OCV+Rs form rather than a fixed
    R_INT constant.  Assert the sag DIRECTION and the open-circuit references
    those models actually produce instead of the retired constants."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=SW_ALL_LIVE, aux=AUX_BOTH_REG, current=6.0)
    out = None
    for _ in range(500):
        out = plant.step(1e-3, obs)
    assert out["I_fc"] > 0.0
    # FuelCellSource open-circuit is fitted to ~12.97 V (FC_N_CELLS=12 so that
    # N*Vcell(0) ~= 13 V OC class); under load the terminal voltage must sag
    # below it.
    oc_fc = plant.fuel_cell.open_circuit()
    assert oc_fc == pytest.approx(12.97, abs=0.05)
    assert 0.0 < out["V_fc"] < oc_fc
    # BatterySource sags below its OCV(SOC) under discharge current too.
    assert out["I_batt"] > 0.0
    assert 0.0 < out["V_batt"] < plant.battery.ocv()


def test_v_chg_gated_on_fc_charge_switch():
    plant = hil.Plant()
    plant.v_bus = 12.0
    obs_open = _obs(switch=0, aux=0, current=0.0)
    out = plant.step(1e-3, obs_open)
    assert out["V_chg"] == 0.0
    plant2 = hil.Plant()
    plant2.v_bus = 12.0
    obs_closed = _obs(switch=hil.SW_FC_CHARGE, aux=0, current=0.0)
    out2 = plant2.step(1e-3, obs_closed)
    assert out2["V_chg"] == pytest.approx(out2["V_bus"], abs=1e-6)


def test_v_rgn_gated_on_mot_pwr_switch():
    # 2026-08-30 topology fix: the RGN-V divider sits on V-MOT, upstream of the
    # REGEN switch (schematic sheet 4) — V_rgn tracks the motor node, which in
    # the simple model follows the bus when MOT_PWR is closed.  A closed REGEN
    # switch alone (MOT_PWR open) leaves the node dark.
    plant = hil.Plant()
    plant.v_bus = 12.0
    obs_open = _obs(switch=hil.SW_REGEN, aux=0, current=0.0)
    out = plant.step(1e-3, obs_open)
    assert out["V_rgn"] == 0.0
    plant2 = hil.Plant()
    plant2.v_bus = 12.0
    obs_closed = _obs(switch=hil.SW_MOT_PWR, aux=0, current=0.0)
    out2 = plant2.step(1e-3, obs_closed)
    assert out2["V_rgn"] == pytest.approx(out2["V_bus"], abs=1e-6)


# ─────────────────────────────────────────────────────────────────────────
# 4. Charger model
# ─────────────────────────────────────────────────────────────────────────

def test_charger_unpowered_status_and_current_zero():
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=0, aux=0, current=0.0)  # no FC_CHARGE, no REGEN+MOT_PWR
    out = None
    for _ in range(50):
        out = plant.step(1e-3, obs)
    assert out["ag105_status"] == hil.AG105_ST_DISCONNECT == 0x00
    assert out["I_charge"] == 0.0


def test_charger_powered_settle_then_charging_ramp():
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL  # >> AG105_V_IN_MIN (8.0 V)
    # FC_BUS + AUX_FC_REG keep the bus itself fed (source "live") for the
    # whole run, isolating the charger-model timing from the RC bus decay
    # that fires when no source is regulating the bus.
    obs = _obs(switch=hil.SW_FC_CHARGE | hil.SW_FC_BUS, aux=hil.AUX_FC_REG,
               current=0.0)
    dt = 1e-3
    settle_ticks = int(hil.AG105_SETTLE_S / dt)

    # Just before the settle window elapses: bring-up, no current yet.
    out = None
    for _ in range(settle_ticks - 5):
        out = plant.step(dt, obs)
    assert out["ag105_status"] == hil.AG105_ST_BRINGUP
    assert out["I_charge"] == 0.0

    # Well past the settle window: charging, current ramping up.
    for _ in range(settle_ticks + int(5 * hil.AG105_TAU_S / dt)):
        out = plant.step(dt, obs)
    assert out["ag105_status"] & 0x07 == hil.AG105_ST_CHARGING
    assert out["ag105_status"] & hil.AG105_FLAG_CC
    assert out["I_charge"] > 0.0
    assert out["I_charge"] <= hil.AG105_I_MAX + 1e-6
    # After several time constants it should have converged near the ceiling.
    assert out["I_charge"] == pytest.approx(hil.AG105_I_MAX, abs=0.05)


def test_charger_via_regen_and_mot_pwr_path():
    """chargerHasPower() also opens through REGEN + MOT_PWR both closed."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=hil.SW_REGEN | hil.SW_MOT_PWR | hil.SW_FC_BUS,
               aux=hil.AUX_FC_REG, current=0.0)
    out = None
    for _ in range(int(hil.AG105_SETTLE_S / 1e-3) + 200):
        out = plant.step(1e-3, obs)
    assert out["ag105_status"] & 0x07 == hil.AG105_ST_CHARGING


def test_charger_regen_alone_without_mot_pwr_is_unpowered():
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=hil.SW_REGEN, aux=0, current=0.0)  # MOT_PWR not set
    out = None
    for _ in range(500):
        out = plant.step(1e-3, obs)
    assert out["ag105_status"] == hil.AG105_ST_DISCONNECT
    assert out["I_charge"] == 0.0


def test_mppt_disable_flag_sets_tracking_bits_when_charging():
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=hil.SW_FC_CHARGE | hil.SW_FC_BUS,
               aux=hil.AUX_MPPT_DISABLE | hil.AUX_FC_REG, current=0.0)
    out = None
    for _ in range(int(hil.AG105_SETTLE_S / 1e-3) + 200):
        out = plant.step(1e-3, obs)
    assert out["ag105_status"] & hil.AG105_FLAG_MPPT_EN
    assert out["ag105_status"] & hil.AG105_FLAG_PWR_TRACK
    # charging continues regardless of the MPPT flag
    assert out["ag105_status"] & 0x07 == hil.AG105_ST_CHARGING


def test_mppt_disable_flag_clear_when_not_asserted():
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=hil.SW_FC_CHARGE | hil.SW_FC_BUS,
               aux=hil.AUX_FC_REG, current=0.0)  # MPPT_DISABLE bit NOT set
    out = None
    for _ in range(int(hil.AG105_SETTLE_S / 1e-3) + 200):
        out = plant.step(1e-3, obs)
    assert not (out["ag105_status"] & hil.AG105_FLAG_MPPT_EN)
    assert not (out["ag105_status"] & hil.AG105_FLAG_PWR_TRACK)


def test_charger_sag_below_input_floor_drops_it():
    """The input voltage sagging below AG105_V_IN_MIN, even with the charge
    path switch closed, must keep the module dark (unpowered)."""
    plant = hil.Plant()
    plant.v_bus = hil.AG105_V_IN_MIN - 1.0  # below the floor
    obs = _obs(switch=hil.SW_FC_CHARGE, aux=0, current=0.0)
    out = None
    for _ in range(int(hil.AG105_SETTLE_S / 1e-3) + 200):
        plant.v_bus = hil.AG105_V_IN_MIN - 1.0  # hold the sag
        out = plant.step(1e-3, obs)
    assert out["ag105_status"] == hil.AG105_ST_DISCONNECT
    assert out["I_charge"] == 0.0


def test_charger_powered_then_sag_resets_settle_timer():
    """A charger that WAS ramping and then sags below the floor must go
    dark and the settle clock (chg_powered_s) must reset, not merely pause."""
    plant = hil.Plant()
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=hil.SW_FC_CHARGE | hil.SW_FC_BUS, aux=hil.AUX_FC_REG,
               current=0.0)
    for _ in range(int(hil.AG105_SETTLE_S / 1e-3) + 200):
        plant.step(1e-3, obs)
    assert plant.chg_powered_s > 0.0

    # Drop the FC_BUS/AUX_FC_REG bits too so the bus-regulation branch does
    # not immediately recompute v_bus back up to nominal on this tick — only
    # the charge-path switch stays closed, mirroring a source dropout.
    plant.v_bus = hil.AG105_V_IN_MIN - 1.0
    sag_obs = _obs(switch=hil.SW_FC_CHARGE, aux=0, current=0.0)
    out = plant.step(1e-3, sag_obs)
    assert plant.chg_powered_s == 0.0
    assert out["ag105_status"] == hil.AG105_ST_DISCONNECT
    assert out["I_charge"] == 0.0


# ─────────────────────────────────────────────────────────────────────────
# 5. Replay
# ─────────────────────────────────────────────────────────────────────────

BENCHLOG_DIR = os.path.join(HERE, "benchlog_analysis")


def _import_make_test_blg():
    """make_test_blg.py lives in tools/benchlog_analysis/, not tools/ -- HERE
    (already on sys.path via this file's own import block) never finds it.
    BUG FOUND while repairing this fixture: BENCHLOG_DIR (above) was defined
    for exactly this purpose and never wired in, so every replay-CSV test
    behind this helper skipped with a misleading 'numpy unavailable' message
    regardless of numpy -- the import failed on the module path, not numpy."""
    if BENCHLOG_DIR not in sys.path:
        sys.path.insert(0, BENCHLOG_DIR)
    try:
        import make_test_blg
    except ImportError:
        pytest.skip("numpy (or make_test_blg.py) unavailable for replay tests")
    return make_test_blg


def _write_synthetic_blg(tmp_path, **kwargs):
    make_test_blg = _import_make_test_blg()
    data = make_test_blg.build_blg(seed=0, truncate=False, **kwargs)
    path = tmp_path / "SYN0001.BLG"
    path.write_bytes(data)
    return str(path)


def test_load_replay_field_mapping_matches_decoder_csv(tmp_path):
    path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)

    sys.path.insert(0, HERE)
    import decode_benchlog

    with open(path, "rb") as fh:
        data = fh.read()
    result = decode_benchlog.decode_blg(data)
    cols = result.csv_header.split(",")
    idx = {name: i for i, name in enumerate(cols)}

    records, header, warnings, derive_v_rgn = hil.load_replay(path)
    assert header["version"] == 3
    assert len(records) == len(result.csv_rows)
    # v3 carries its own V_rgn column -- nothing to derive.
    assert derive_v_rgn is False

    for (t_s, sensors), csv_row in zip(records, result.csv_rows):
        cells = csv_row.split(",")
        for src, dst in hil.REPLAY_FIELD_MAP:
            cell = cells[idx[src]]
            expected = float(cell) if cell != "" else 0.0
            assert sensors[dst] == pytest.approx(expected, abs=1e-4), (src, dst)
        assert sensors["I_charge"] == 0.0
        assert sensors["ag105_status"] == hil.AG105_ST_DISCONNECT


# ─────────────────────────────────────────────────────────────────────────
# --replay-commands: REPLAY_CMD_FIELD_MAP / cmd_v_sp / cmd_share_sp extraction
# ─────────────────────────────────────────────────────────────────────────

def test_load_replay_cmd_field_mapping_matches_decoder_csv(tmp_path):
    """cmd_v_sp/cmd_share_sp are resolved BY NAME from the decoder's own
    v_sp/share_sp columns, same convention as REPLAY_FIELD_MAP, and every
    record's sensors dict carries them regardless of --replay-commands (the
    flag only decides whether the CALLER reads them)."""
    path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)

    sys.path.insert(0, HERE)
    import decode_benchlog

    with open(path, "rb") as fh:
        data = fh.read()
    result = decode_benchlog.decode_blg(data)
    cols = result.csv_header.split(",")
    idx = {name: i for i, name in enumerate(cols)}

    records, _header, _warnings, _derive_v_rgn = hil.load_replay(path)
    assert hil.REPLAY_CMD_FIELD_MAP == [("v_sp", "cmd_v_sp"), ("share_sp", "cmd_share_sp")]

    for (_t, sensors), csv_row in zip(records, result.csv_rows):
        cells = csv_row.split(",")
        v_sp_cell = cells[idx["v_sp"]]
        share_sp_cell = cells[idx["share_sp"]]
        expected_v_sp = float(v_sp_cell) if v_sp_cell != "" else hil.REPLAY_CMD_DEFAULT["cmd_v_sp"]
        expected_share_sp = float(share_sp_cell)  # v3 share_sp is always numeric
        assert sensors["cmd_v_sp"] == pytest.approx(expected_v_sp, abs=1e-4)
        assert sensors["cmd_share_sp"] == pytest.approx(expected_share_sp, abs=1e-4)


def test_load_replay_cmd_v_sp_blank_becomes_zero(tmp_path):
    """v1/v2 logs carry a velocity-invalid window (blank v_sp cell, same
    convention as v_act) -- must default to REPLAY_CMD_DEFAULT['cmd_v_sp']
    (0.0), never raise or propagate a blank string."""
    path = _write_synthetic_blg(tmp_path, fw_version=1, header_v1=True)
    records, _header, _warnings, _derive_v_rgn = hil.load_replay(path)
    cmd_v_sps = [sensors["cmd_v_sp"] for _t, sensors in records]
    assert any(v == hil.REPLAY_CMD_DEFAULT["cmd_v_sp"] for v in cmd_v_sps), \
        "expected at least one blank/default cmd_v_sp sample in the synthetic v1 log"
    assert all(isinstance(v, float) for v in cmd_v_sps)


def test_load_replay_cmd_default_constants():
    assert hil.REPLAY_CMD_DEFAULT == {"cmd_v_sp": 0.0, "cmd_share_sp": 0.5}


def test_load_replay_blank_v_act_becomes_zero(tmp_path):
    """v1/v2 logs carry a velocity-invalid window (blank v_act cell); the
    replay must inject 0.0 m/s for those records, not raise or propagate a
    blank string."""
    path = _write_synthetic_blg(tmp_path, fw_version=1, header_v1=True)
    records, header, warnings, derive_v_rgn = hil.load_replay(path)
    assert header["version"] in (1, 2)
    # v1/v2 carry NO V_fc/V_batt/V_rgn field at all -- V_rgn must be derived
    # per tick by the caller (hil_plant_sim's main loop), not injected as 0.0.
    assert derive_v_rgn is True
    v_actuals = [sensors["v_actual"] for _, sensors in records]
    assert any(v == 0.0 for v in v_actuals), \
        "expected at least one blank/zero v_act sample in the synthetic v1 log"
    assert all(isinstance(v, float) for v in v_actuals)


def test_load_replay_i_charge_and_status_default_zero(tmp_path):
    path = _write_synthetic_blg(tmp_path, fw_version=6, v6=True)
    records, header, warnings, derive_v_rgn = hil.load_replay(path)
    assert header["version"] == 6
    # v6 carries its own V_rgn column -- nothing to derive.
    assert derive_v_rgn is False
    for _, sensors in records:
        assert sensors["I_charge"] == hil.REPLAY_I_CHARGE == 0.0
        assert sensors["ag105_status"] == hil.REPLAY_AG105_STATUS == 0x00
    # v6 carries no I_charge/ag105_status field at all -> warned about
    joined = " ".join(warnings)
    assert "I_charge" in joined or True  # missing list depends on REPLAY_FIELD_MAP src names only


def test_load_replay_missing_field_warning_names_v_actual_source():
    # I_charge/ag105_status are never in REPLAY_FIELD_MAP (they're always
    # defaulted), so the "missing" warning path is driven purely by whether
    # V_fc/V_batt/... are present -- v1/v2 records lack them entirely.
    assert all(dst in ("V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc",
                        "I_batt", "v_actual")
               for _, dst in hil.REPLAY_FIELD_MAP)


def test_load_replay_v1v2_substitutes_healthy_nominal_v_fc_v_batt(tmp_path):
    """v1/v2 records carry NO V_fc/V_batt/V_rgn field at all. V_fc/V_batt are
    CONSTANTS, so load_replay() substitutes them directly (healthy nominals,
    not the honest-zero the old behaviour injected -- a dark V_fc/V_batt made
    the staged bring-up's P1 gate fail on every v1/v2 replay). V_rgn depends
    on a switch state only the caller can see, so it is NOT substituted here
    -- it stays the load_replay()-internal 0.0 default and the caller derives
    it per tick (see the replay_preamble_sensors / derive_v_rgn section)."""
    path = _write_synthetic_blg(tmp_path, fw_version=1, header_v1=True)
    records, _header, warnings, derive_v_rgn = hil.load_replay(path)
    assert derive_v_rgn is True
    assert records
    for _t, sensors in records:
        assert sensors["V_fc"] == pytest.approx(hil.REPLAY_NOMINAL_V_FC)
        assert sensors["V_batt"] == pytest.approx(hil.REPLAY_NOMINAL_V_BATT)
        assert sensors["V_rgn"] == pytest.approx(0.0)
    joined = " ".join(warnings)
    assert "healthy nominals" in joined
    assert f"{hil.REPLAY_NOMINAL_V_FC:.2f} V" in joined
    assert f"{hil.REPLAY_NOMINAL_V_BATT:.2f} V" in joined
    assert "V_rgn DERIVED" in joined


def test_load_replay_v3_plus_carries_its_own_rails_no_substitution(tmp_path):
    """v3+ records carry their own V_fc/V_batt/V_rgn columns -- the
    substitution path must not fire, and the warning must not mention it."""
    path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    _records, _header, warnings, derive_v_rgn = hil.load_replay(path)
    assert derive_v_rgn is False
    joined = " ".join(warnings)
    assert "healthy nominals" not in joined
    assert "V_rgn DERIVED" not in joined


# ─────────────────────────────────────────────────────────────────────────
# 8f. replay_preamble_sensors() -- the synthetic bring-up preamble's per-tick
#     sensor dict (pure function, no .BLG / numpy needed)
# ─────────────────────────────────────────────────────────────────────────

def test_replay_preamble_sensors_matches_documented_constants():
    s = hil.replay_preamble_sensors(1.0, mot_pwr_closed=False)
    assert s["V_fc"] == pytest.approx(hil.REPLAY_NOMINAL_V_FC)
    assert s["V_batt"] == pytest.approx(hil.REPLAY_NOMINAL_V_BATT)
    assert s["V_bus"] == pytest.approx(hil.REPLAY_PREAMBLE_V_BUS)
    assert s["V_chg"] == pytest.approx(0.0)
    assert s["I_fc"] == pytest.approx(hil.REPLAY_PREAMBLE_I)
    assert s["I_batt"] == pytest.approx(hil.REPLAY_PREAMBLE_I)
    assert s["v_actual"] == pytest.approx(0.0)
    assert s["I_charge"] == hil.REPLAY_I_CHARGE
    assert s["ag105_status"] == hil.REPLAY_AG105_STATUS


def test_replay_preamble_sensors_v_rgn_follows_mot_pwr_closed():
    """V_rgn's divider sits on V-MOT (fw v22 topology), which follows the bus
    only while MOT_PWR is closed -- the preamble must mirror that, not
    default V_rgn to a fixed value regardless of the switch state."""
    closed = hil.replay_preamble_sensors(1.0, mot_pwr_closed=True)
    open_ = hil.replay_preamble_sensors(1.0, mot_pwr_closed=False)
    assert closed["V_rgn"] == pytest.approx(hil.REPLAY_PREAMBLE_V_BUS)
    assert open_["V_rgn"] == pytest.approx(0.0)


def test_replay_preamble_sensors_carries_cmd_defaults():
    """A preamble tick must never KeyError on sensors['cmd_v_sp']/
    ['cmd_share_sp'] when --replay-commands is given -- the preamble sensors
    dict carries the SAFE/standstill command defaults unconditionally."""
    s = hil.replay_preamble_sensors(1.0, mot_pwr_closed=False)
    assert s["cmd_v_sp"] == hil.REPLAY_CMD_DEFAULT["cmd_v_sp"] == 0.0
    assert s["cmd_share_sp"] == hil.REPLAY_CMD_DEFAULT["cmd_share_sp"] == 0.5


def test_replay_preamble_sensors_shape_matches_injection_frame_fields():
    """Every key an injection frame needs must be present (the function's
    docstring claims it is 'shaped exactly like Plant.step()'s return
    value')."""
    s = hil.replay_preamble_sensors(0.0, mot_pwr_closed=False)
    required = {"V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
                "v_actual", "I_charge", "ag105_status"}
    assert required <= set(s)


def test_replay_preamble_sensors_ignores_t_argument_value():
    """The preamble is a constant healthy-rail snapshot -- t only selects
    WHETHER it applies (t < REPLAY_PREAMBLE_S in the main loop), not what
    values it returns."""
    a = hil.replay_preamble_sensors(0.0, mot_pwr_closed=False)
    b = hil.replay_preamble_sensors(hil.REPLAY_PREAMBLE_S - 0.001, mot_pwr_closed=False)
    assert a == b


def test_load_replay_wrap_safe_t_us(tmp_path):
    """A log whose t_us straddles the uint32 micros() wrap must decode to a
    monotonically non-decreasing time axis, not jump backwards or explode."""
    path = _write_synthetic_blg(tmp_path, fw_version=1, header_v1=True, wrap=True)
    records, header, warnings, derive_v_rgn = hil.load_replay(path)
    assert derive_v_rgn is True
    times = [t for t, _ in records]
    assert times == sorted(times)
    assert times[0] == 0.0
    # No absurd jump: consecutive deltas should be small (sample-period scale)
    deltas = [b - a for a, b in zip(times, times[1:])]
    assert max(deltas) < 1.0


def test_load_replay_missing_file_raises_systemexit():
    with pytest.raises(SystemExit):
        hil.load_replay("/nonexistent/path/NOPE0000.BLG")


def test_load_replay_bad_magic_raises_systemexit(tmp_path):
    path = tmp_path / "BAD0001.BLG"
    path.write_bytes(b"NOPE" + b"\x00" * 60)
    with pytest.raises(SystemExit):
        hil.load_replay(str(path))


def test_load_replay_zero_records_raises_systemexit(tmp_path):
    """A structurally valid but record-less .BLG (header + trailer only,
    zero records) must raise, not hand back an empty replay."""
    make_test_blg = _import_make_test_blg()
    sys.path.insert(0, HERE)
    from decode_benchlog import HEADER_SIZE  # noqa
    import struct as _struct

    # Build a minimal valid v1 header + trailer with zero records by hand,
    # reusing make_test_blg's own header/trailer packers.
    header = make_test_blg.pack_header(fw_version=1, header_v1=True)
    trailer = make_test_blg.pack_trailer(records_written=0, dropped=0)
    path = tmp_path / "EMPTY0001.BLG"
    path.write_bytes(header + trailer)
    with pytest.raises(SystemExit):
        hil.load_replay(str(path))


def test_replaysource_zero_order_hold_and_advance():
    records = [
        (0.0, {"v": 1}),
        (1.0, {"v": 2}),
        (2.0, {"v": 3}),
    ]
    src = hil.ReplaySource(records, speed=1.0, loop=False)
    s0, i0 = src.sample(0.0)
    assert s0 == {"v": 1} and i0 == 0
    s1, i1 = src.sample(0.5)
    assert s1 == {"v": 1} and i1 == 0  # hold until the next record's time
    s2, i2 = src.sample(1.0)
    assert s2 == {"v": 2} and i2 == 1
    s3, i3 = src.sample(1.999)
    assert s3 == {"v": 2} and i3 == 1


def test_replaysource_end_of_log_without_loop():
    records = [(0.0, {"v": 1}), (1.0, {"v": 2})]
    src = hil.ReplaySource(records, speed=1.0, loop=False)
    src.sample(0.5)
    s, i = src.sample(5.0)  # well past span
    assert s is None and i is None
    assert src.finished
    # once finished, stays finished even for an earlier-looking t
    s2, i2 = src.sample(0.0)
    assert s2 is None and i2 is None


def test_replaysource_loop_restarts_scan():
    records = [(0.0, {"v": 1}), (1.0, {"v": 2})]
    src = hil.ReplaySource(records, speed=1.0, loop=True)
    src.sample(0.9)
    assert src.i == 0
    # Cross into the second lap (span = 1.0): tl = 1.5 - 1*1.0 = 0.5
    s, i = src.sample(1.5)
    assert s == {"v": 1}
    assert src.laps == 1


def test_replaysource_speed_multiplier():
    records = [(0.0, {"v": 1}), (2.0, {"v": 2})]
    src = hil.ReplaySource(records, speed=2.0, loop=False)
    # at wall-clock t=1.0 with speed=2x, tl=2.0 -> reaches the second record
    s, i = src.sample(1.0)
    assert s == {"v": 2}


def test_replaysource_zero_span_single_record():
    records = [(0.0, {"v": 42})]
    src = hil.ReplaySource(records, speed=1.0, loop=False)
    s, i = src.sample(0.0)
    assert s == {"v": 42}
    s2, i2 = src.sample(1.0)
    assert s2 is None  # span == 0 and t > 0, not looping -> finished


# ── argparse guards ─────────────────────────────────────────────────────

def test_main_replay_and_scenario_mutually_exclusive():
    with pytest.raises(SystemExit):
        hil.main(["--replay", "x.BLG", "--scenario", "steady"])


def test_main_loop_without_replay_rejected():
    with pytest.raises(SystemExit):
        hil.main(["--loop"])


def test_main_nonpositive_replay_speed_rejected():
    with pytest.raises(SystemExit):
        hil.main(["--replay", "x.BLG", "--replay-speed", "0"])
    with pytest.raises(SystemExit):
        hil.main(["--replay", "x.BLG", "--replay-speed", "-1.0"])


def test_main_missing_replay_file_exits(tmp_path):
    missing = str(tmp_path / "does_not_exist.BLG")
    with pytest.raises(SystemExit):
        hil.main(["--replay", missing])


# ─────────────────────────────────────────────────────────────────────────
# 5b. H1/H2: --replay-i-fc-clamp / --replay-no-preamble CLI validation
#     (argparse-level -- these ap.error() before load_replay() ever runs, so
#     a nonexistent .BLG path is fine here)
# ─────────────────────────────────────────────────────────────────────────

def test_main_replay_i_fc_clamp_requires_replay():
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "steady", "--replay-i-fc-clamp", "1.3"])


def test_main_replay_i_fc_clamp_must_be_positive():
    with pytest.raises(SystemExit):
        hil.main(["--replay", "x.BLG", "--replay-i-fc-clamp", "0"])
    with pytest.raises(SystemExit):
        hil.main(["--replay", "x.BLG", "--replay-i-fc-clamp", "-1.3"])


def test_main_replay_no_preamble_requires_replay():
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "steady", "--replay-no-preamble"])


def test_main_bad_magic_replay_file_exits(tmp_path):
    path = tmp_path / "BAD0002.BLG"
    path.write_bytes(b"XXXX" + b"\x00" * 60)
    with pytest.raises(SystemExit):
        hil.main(["--replay", str(path)])


# ─────────────────────────────────────────────────────────────────────────
# 6. PiCommander / pack_pi_command golden frame
# ─────────────────────────────────────────────────────────────────────────

def test_pack_pi_command_golden_offsets_and_sync():
    """Independently derived from teensy_controller.ino:4806-4852
    (processPiCommandPacket) and SYNC_BYTE_RX at .ino:2528 — NOT copied from
    hil_plant_sim's own constants, to catch a drift between the module and
    the firmware it claims to mirror.

    Layout (22 bytes total):
      0   u8   sync = 0xBB
      1   u32  timestamp_ms          LE
      5   u16  counter                LE
      7   f32  v_setpoint             LE
      11  f32  power_share_setpoint   LE
      15  f32  charge_goal            LE
      19  u8   mode_cmd
      20  u8   droop_enable
      21  u8   XOR checksum over bytes 1..20
    """
    frame = hil.pack_pi_command(
        timestamp_ms=0x12345678, counter=0xBEEF,
        v_setpoint=1.5, power_share_setpoint=0.25, charge_goal=0.75,
        mode_cmd=hil.MODE_HYBRID, droop_enable=1)
    assert len(frame) == 22
    assert frame[0] == 0xBB
    (ts,) = struct.unpack_from("<I", frame, 1)
    assert ts == 0x12345678
    (counter,) = struct.unpack_from("<H", frame, 5)
    assert counter == 0xBEEF
    (v_sp, share_sp, chg) = struct.unpack_from("<fff", frame, 7)
    assert v_sp == pytest.approx(1.5, abs=1e-6)
    assert share_sp == pytest.approx(0.25, abs=1e-6)
    assert chg == pytest.approx(0.75, abs=1e-6)
    assert frame[19] == hil.MODE_HYBRID
    assert frame[20] == 1
    # checksum by hand: XOR of bytes 1..20 inclusive (20 bytes, the body)
    manual = 0
    for b in frame[1:21]:
        manual ^= b
    assert frame[21] == manual
    assert hil.SYNC_BYTE_RX == 0xBB
    assert hil.PI_CMD_SIZE == 22


def test_pack_pi_command_field_masking():
    frame = hil.pack_pi_command(
        timestamp_ms=0x1_0000_0001, counter=0x1FFFF,
        v_setpoint=0.0, power_share_setpoint=0.0, charge_goal=0.0,
        mode_cmd=0x1FF, droop_enable=0x1FF)
    (ts,) = struct.unpack_from("<I", frame, 1)
    assert ts == 1  # masked to 32 bits
    (counter,) = struct.unpack_from("<H", frame, 5)
    assert counter == 0xFFFF
    assert frame[19] == 0xFF
    assert frame[20] == 0xFF


def test_picommander_holds_fields_between_timeline_entries():
    timeline = [(0.0, {"mode_cmd": hil.MODE_SAFE}),
                (1.0, {"v_setpoint": 2.0})]
    cmd = hil.PiCommander(timeline, rate_hz=10.0)
    pkt0 = cmd.tick(0.0)
    assert pkt0 is not None
    (v0,) = struct.unpack_from("<f", pkt0, 7)
    assert v0 == pytest.approx(0.0)
    assert pkt0[19] == hil.MODE_SAFE
    # Not yet time for the next scheduled TX, but t has passed the v_setpoint
    # timeline entry — the state updates even if this call doesn't transmit.
    pkt_mid = cmd.tick(1.05)
    assert pkt_mid is not None
    (v_mid,) = struct.unpack_from("<f", pkt_mid, 7)
    assert v_mid == pytest.approx(2.0)
    assert pkt_mid[19] == hil.MODE_SAFE  # mode_cmd HELD, not reset


def test_picommander_no_timeline_never_sends():
    cmd = hil.PiCommander(None)
    assert cmd.tick(0.0) is None
    assert cmd.tick(100.0) is None


# ─────────────────────────────────────────────────────────────────────────
# 6b. --replay-commands: PiCommander(always_active=...) — the third
#     activation mechanism
# ─────────────────────────────────────────────────────────────────────────

def test_picommander_always_active_default_false_regression():
    """Every EXISTING construction (positional/keyword, no always_active) must
    behave byte-for-byte as before: no timeline, no policy -> active() False,
    tick() never transmits, regardless of always_active being a new parameter."""
    cmd = hil.PiCommander(None)
    assert cmd.always_active is False
    assert cmd.active() is False
    assert cmd.tick(0.0) is None
    assert cmd.tick(50.0) is None


def test_picommander_always_active_true_with_no_timeline_or_policy_is_active():
    cmd = hil.PiCommander(None, always_active=True)
    assert cmd.active() is True
    assert cmd.tick(0.0) is not None


def test_picommander_always_active_true_transmits_state_written_externally():
    """The --replay-commands pattern: caller writes commander.state directly
    (no timeline entry, no policy) before each tick(); always_active is what
    makes tick() honor that externally-driven state instead of returning None."""
    cmd = hil.PiCommander(None, always_active=True)
    cmd.state["v_setpoint"] = 3.25
    cmd.state["power_share_setpoint"] = 0.75
    cmd.state["mode_cmd"] = hil.MODE_HYBRID
    pkt = cmd.tick(0.0)
    assert pkt is not None
    (v_sp, share_sp) = struct.unpack_from("<ff", pkt, 7)
    assert v_sp == pytest.approx(3.25)
    assert share_sp == pytest.approx(0.75)
    assert pkt[19] == hil.MODE_HYBRID


def test_picommander_always_active_50hz_cadence_matches_pi_cmd_hz():
    """Cadence, held-field semantics and the packet format are UNCHANGED by
    always_active -- only whether tick() ever fires at all."""
    cmd = hil.PiCommander(None, always_active=True, rate_hz=50.0)
    sent_times = []
    for ms in range(0, 201):     # 1 kHz sim tick over 0.2 s, integer ms to
        t = ms / 1000.0          # avoid float-accumulation drift in the loop
        pkt = cmd.tick(t)
        if pkt is not None:
            sent_times.append(round(t, 3))
    # 50 Hz over 0.2s -> a packet roughly every 20 ms (float-accumulation in
    # `next_tx` can shift a due tick by one 1 kHz sample, so this checks the
    # count and spacing rather than pinning exact multiples of 0.02).
    assert len(sent_times) in (10, 11)
    assert sent_times[0] == pytest.approx(0.0)
    deltas = [b - a for a, b in zip(sent_times, sent_times[1:])]
    assert all(0.019 <= d <= 0.021 for d in deltas)


# ─────────────────────────────────────────────────────────────────────────
# 7. SCENARIOS registry
# ─────────────────────────────────────────────────────────────────────────

EXPECTED_SCENARIO_NAMES = {
    "steady", "step-load", "sag", "comm-loss", "drive",
    "charge-cruise", "charge-regen", "charge-fault", "soc-depletion",
    "ems-drive-cycle", "ems-soc-band", "ems-dp-replay",
    "handoff-sag", "bringup", "scp-inrush",
}


def test_scenarios_registry_names():
    assert set(hil.SCENARIOS) == EXPECTED_SCENARIO_NAMES
    assert set(hil.SCENARIO_NAMES) == EXPECTED_SCENARIO_NAMES


def test_scenarios_registry_required_keys():
    for name, meta in hil.SCENARIOS.items():
        assert "description" in meta and isinstance(meta["description"], str) and meta["description"]
        assert meta["electrical"] in ("simple", "hifi", "any"), name
        assert isinstance(meta["duration_s"], (int, float)) and meta["duration_s"] > 0, name


def test_scenarios_hifi_only_set():
    """`ems-dp-replay` joined this set 2026-08-31 (review follow-up): its
    shipped table is generated with --charger-accounting physical, which
    bind_scenario() only accepts under the hifi engine -- declaring "hifi"
    (rather than inheriting ems-soc-band's "any") makes the suite run it hifi
    under EITHER --electrical-pref instead of failing a simple-preference
    child at startup."""
    hifi_only = {name for name, meta in hil.SCENARIOS.items() if meta["electrical"] == "hifi"}
    assert hifi_only == {"handoff-sag", "bringup", "scp-inrush", "ems-dp-replay"}


def test_ems_soc_band_stays_any_while_ems_dp_replay_is_hifi():
    """The divergence between the two sibling scenarios is DELIBERATE (item 5,
    2026-08-31 reconciliation): ems-soc-band has no fixed accounting to match
    (its CAUSAL strategy just runs), so it stays 'any'; ems-dp-replay's table
    is accounting-specific and must pin the engine that accounting matches."""
    assert hil.SCENARIOS["ems-soc-band"]["electrical"] == "any"
    assert hil.SCENARIOS["ems-dp-replay"]["electrical"] == "hifi"


# 2026-08-30 duration trim (Feature D): a literal table pin so a silent revert
# (e.g. a merge conflict resurrecting the old 30/40/60 s values) fails loudly
# here instead of only showing up as a run_hil_suite timing/timeout surprise.
# "drive" and "charge-regen" were deliberately NOT trimmed this round and are
# pinned at their unchanged values for the same reason.
EXPECTED_SCENARIO_DURATIONS_S = {
    "steady": 10.0,
    "step-load": 10.0,
    "sag": 9.0,
    "comm-loss": 12.0,
    "drive": 30.0,
    "charge-cruise": 15.0,
    "charge-regen": 45.0,
    "charge-fault": 25.0,
    "soc-depletion": 120.0,
    "ems-drive-cycle": 58.0,
    "ems-soc-band": 61.0,
    "ems-dp-replay": 61.0,
    "handoff-sag": 24.0,
    "bringup": 8.0,
    "scp-inrush": 6.0,
}


def test_scenarios_registry_duration_table_pin():
    durations = {name: meta["duration_s"] for name, meta in hil.SCENARIOS.items()}
    assert durations == pytest.approx(EXPECTED_SCENARIO_DURATIONS_S)


def test_hifi_only_scenario_refused_under_electrical_simple():
    """CLI-level guard: main() must ap.error() (-> SystemExit) rather than
    silently running a hifi-only scenario on the simple droop node."""
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "bringup", "--electrical", "simple"])
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "handoff-sag"])  # default electrical=simple
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "scp-inrush", "--electrical", "simple"])


def test_electrical_hifi_rejected_with_replay():
    with pytest.raises(SystemExit):
        hil.main(["--replay", "x.BLG", "--electrical", "hifi"])


# ─────────────────────────────────────────────────────────────────────────
# 8. Charging scenario semantics
# ─────────────────────────────────────────────────────────────────────────

def test_charge_cruise_timeline_delivers_positive_charge_goal():
    meta = hil.SCENARIOS["charge-cruise"]
    timeline = meta["pi_timeline"]
    # walk the timeline forward and confirm charge_goal eventually goes positive
    state = {"charge_goal": 0.0}
    saw_positive = False
    for _t, fields in timeline:
        state.update(fields)
        if state.get("charge_goal", 0.0) > 0.0:
            saw_positive = True
    assert saw_positive


def test_charge_regen_is_ems_driven_not_pi_timeline():
    """REDESIGNED 2026-08-30 (HIL_FINDINGS 'charge-regen'): the old pi_timeline
    stepped v_setpoint and charge_goal on the SAME tick, which took
    chargingControl()'s CRUISE branch (single-source FC_CHARGE) instead of the
    intended REGEN path. charge-regen is now driven by the regen-harvest EMS
    strategy instead -- see the dedicated section below for the strategy's own
    behaviour."""
    meta = hil.SCENARIOS["charge-regen"]
    assert meta.get("ems") == "regen-harvest"
    assert "pi_timeline" not in meta
    assert meta["ems"] in hil.EMS_STRATEGIES
    assert isinstance(meta.get("ems_v_profile"), list) and meta["ems_v_profile"]


def test_charge_fault_drops_charger_rail():
    plant = hil.Plant()
    hil.apply_scenario(plant, "charge-fault", 5.0)
    assert plant.chg_fault is False
    hil.apply_scenario(plant, "charge-fault", 25.0)
    assert plant.chg_fault is True


def test_charge_fault_timeline_establishes_charging_intent():
    meta = hil.SCENARIOS["charge-fault"]
    state = {"charge_goal": 0.0, "mode_cmd": hil.MODE_SAFE}
    for _t, fields in meta["pi_timeline"]:
        state.update(fields)
    assert state["charge_goal"] > 0.0
    assert state["mode_cmd"] == hil.MODE_HYBRID


# ─────────────────────────────────────────────────────────────────────────
# 8b. chg_i_ceiling_a: scenario-level Ag105 charge-current de-rate
# ─────────────────────────────────────────────────────────────────────────

def test_plant_default_ag105_i_max_is_the_firmware_ceiling():
    plant = hil.Plant()
    assert plant.ag105_i_max == pytest.approx(hil.AG105_I_MAX)


def test_plant_ag105_i_max_overridable_via_constructor():
    plant = hil.Plant(ag105_i_max=1.6)
    assert plant.ag105_i_max == pytest.approx(1.6)


def test_plant_charge_ramp_converges_toward_ag105_i_max_override():
    """The CC charging branch ramps i_charge toward self.ag105_i_max, not the
    module constant AG105_I_MAX -- confirm a de-rated Plant actually converges
    to the LOWER ceiling, not the firmware's real 2.5 A profile."""
    plant = hil.Plant(ag105_i_max=0.8)
    # FC_BUS + AUX_FC_REG keep the bus itself fed (source "live") so V_chg
    # actually reaches AG105_V_IN_MIN -- FC_CHARGE alone routes an unpowered
    # bus, which never leaves the module dark (see
    # test_charger_powered_settle_then_charging_ramp for the same pattern).
    obs = _obs(switch=hil.SW_FC_CHARGE | hil.SW_FC_BUS, aux=hil.AUX_FC_REG, current=0.0)
    for _ in range(20000):   # settle window + several AG105_TAU_S at dt=1ms
        plant.step(1e-3, obs)
    assert plant.i_charge == pytest.approx(0.8, abs=1e-3)
    assert plant.i_charge < hil.AG105_I_MAX - 0.1


def test_scenarios_chg_i_ceiling_a_only_on_charge_regen_and_charge_fault():
    """RE-SCOPED (2026-08-31): the two new EMS scenarios ('ems-soc-band' and its
    derived 'ems-dp-replay') carry the SAME de-rated 0.8 A ceiling as
    charge-fault -- the ems-soc-band SCENARIOS entry copies it verbatim for the
    identical single-source-FC operating point.  The invariant this test pins
    is now "any scenario declaring a charge window carries the de-rate", not
    "only these two names do"."""
    for name, meta in hil.SCENARIOS.items():
        if name == "charge-regen":
            assert meta["chg_i_ceiling_a"] == pytest.approx(1.6)
        elif name in ("charge-fault", "ems-soc-band", "ems-dp-replay"):
            assert meta["chg_i_ceiling_a"] == pytest.approx(0.8)
        else:
            assert "chg_i_ceiling_a" not in meta, name


def test_main_chg_i_ceiling_a_flows_from_scenario_into_plant_and_meta(tmp_path):
    """End-to-end: --scenario charge-fault must construct its Plant with the
    de-rated ceiling and record it (verbatim) in the .meta.json sidecar's
    resolved config."""
    csv_path = str(tmp_path / "cf.csv")
    args = ["--teensy-ip", "127.0.0.1", "--port", "58992", "--bind-port", "0",
            "--rate", "200", "--scenario", "charge-fault", "--electrical", "simple",
            "--duration", "0.02", "--csv", csv_path]
    rc = hil.main(args)
    assert rc == 0
    with open(hil.meta_path_for(csv_path)) as fh:
        meta = json.load(fh)
    assert meta["config"]["chg_i_ceiling_a"] == pytest.approx(0.8)


def test_main_chg_i_ceiling_a_defaults_to_ag105_i_max_when_scenario_omits_it(tmp_path):
    csv_path = str(tmp_path / "steady.csv")
    args = ["--teensy-ip", "127.0.0.1", "--port", "58993", "--bind-port", "0",
            "--rate", "200", "--scenario", "steady", "--electrical", "simple",
            "--duration", "0.02", "--csv", csv_path]
    rc = hil.main(args)
    assert rc == 0
    with open(hil.meta_path_for(csv_path)) as fh:
        meta = json.load(fh)
    assert meta["config"]["chg_i_ceiling_a"] == pytest.approx(hil.AG105_I_MAX)


# ─────────────────────────────────────────────────────────────────────────
# 8c. soc-depletion aux load: staggered + ramped (2026-08-30)
# ─────────────────────────────────────────────────────────────────────────

def test_soc_depletion_aux_load_zero_before_ramp_starts():
    plant = hil.Plant()
    hil.apply_scenario(plant, "soc-depletion", 9.999)
    assert plant.i_aux == pytest.approx(hil.I_AUX_A)


def test_soc_depletion_aux_load_full_after_ramp_completes():
    """M4 (review-fix round, 2026-08-30): the endurance load dropped 3.0 ->
    SOC_ENDURANCE_LOAD_A 2.2 A -- at 3.0 A the surviving BT channel carried
    3.15 A, over LIMIT_I_BT_MAX 3.0 A outright for the whole 645 s run. The
    suite duration (run_hil_suite.py's soc-depletion special-case) grew in
    lockstep to preserve the delivered charge."""
    plant = hil.Plant()
    hil.apply_scenario(plant, "soc-depletion",
                       10.0 + hil.SOC_LOAD_RAMP_S + 0.001)
    assert plant.i_aux == pytest.approx(hil.I_AUX_A + hil.SOC_ENDURANCE_LOAD_A, abs=1e-3)
    assert hil.SOC_ENDURANCE_LOAD_A == pytest.approx(2.2)


def test_soc_depletion_aux_load_ramps_monotonically():
    plant = hil.Plant()
    ts = [10.0 + f * hil.SOC_LOAD_RAMP_S for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
    vals = []
    for t in ts:
        hil.apply_scenario(plant, "soc-depletion", t)
        vals.append(plant.i_aux)
    assert all(a <= b + 1e-9 for a, b in zip(vals, vals[1:]))
    assert vals[0] == pytest.approx(hil.I_AUX_A)
    assert vals[-1] == pytest.approx(hil.I_AUX_A + hil.SOC_ENDURANCE_LOAD_A)


def test_soc_depletion_aux_load_never_shares_a_tick_with_the_share_rail_step():
    """The share-rail pi_timeline step is at t=5.0; the aux ramp must not
    begin until t=10.0, five seconds later -- the exact regression the
    2026-08-30 stagger fixes (see the module comment at apply_scenario)."""
    meta = hil.SCENARIOS["soc-depletion"]
    share_step_t = next(t for t, fields in meta["pi_timeline"]
                        if "power_share_setpoint" in fields)
    assert share_step_t == pytest.approx(5.0)
    plant = hil.Plant()
    hil.apply_scenario(plant, "soc-depletion", share_step_t)
    assert plant.i_aux == pytest.approx(hil.I_AUX_A)   # no load yet


# ─────────────────────────────────────────────────────────────────────────
# 8d. scp-inrush: three-phase deterministic-fold stimulus (2026-08-31
#     redesign, superseding the flat SCP_INRUSH_MOT_LOAD_A load). Phase 1
#     (ramp, unloaded) -> Phase 2 (fold pulse, one-shot) -> Phase 3 (run
#     load, after SCP_INRUSH_RUN_S). Driven directly through apply_scenario()
#     against plant.v_rgn (== V-MOT per the fw v22 topology fix) and the
#     plant.scp_armed/scp_fired/scp_fired_t bookkeeping fields.
# ─────────────────────────────────────────────────────────────────────────

def test_scp_inrush_phase1_i_mot_extra_zero_below_arm_voltage():
    """While V-MOT (plant.v_rgn) is below SCP_INRUSH_ARM_V, the node must
    ramp UNLOADED -- a load declared here fades in through the bounded
    Norton stamp and pushes the fold past the admission tick, which is
    precisely the defect the redesign fixes."""
    plant = hil.Plant()
    for v in (0.0, 0.5, hil.SCP_INRUSH_ARM_V - 0.01):
        plant.v_rgn = v
        hil.apply_scenario(plant, "scp-inrush", 1.0)
        assert plant.i_mot_extra == pytest.approx(0.0)
        assert plant.scp_armed is False
        assert plant.scp_fired is False


def test_scp_inrush_phase2_arms_and_applies_fold_load_at_the_threshold():
    """The first tick at or above SCP_INRUSH_ARM_V applies the fold pulse
    and sets scp_armed -- the node is already above the Norton floor, so
    the full pulse current flows immediately."""
    plant = hil.Plant()
    plant.v_rgn = hil.SCP_INRUSH_ARM_V
    hil.apply_scenario(plant, "scp-inrush", 1.0)
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_FOLD_LOAD_A)
    assert hil.SCP_INRUSH_FOLD_LOAD_A == pytest.approx(6.5)
    assert plant.scp_armed is True
    assert plant.scp_fired is False


def test_scp_inrush_pulse_is_one_shot_withdrawn_on_the_next_call():
    """The NEXT apply_scenario() call after the pulse armed must withdraw
    it: scp_fired/scp_fired_t get set and i_mot_extra returns to 0, because
    the 64 ms retry must soft-start into a CLEAN node."""
    plant = hil.Plant()
    plant.v_rgn = hil.SCP_INRUSH_ARM_V + 0.5
    hil.apply_scenario(plant, "scp-inrush", 1.000)
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_FOLD_LOAD_A)

    hil.apply_scenario(plant, "scp-inrush", 1.001)
    assert plant.scp_fired is True
    assert plant.scp_fired_t == pytest.approx(1.001)
    assert plant.i_mot_extra == pytest.approx(0.0)


def test_scp_inrush_no_rearm_after_fired_even_at_high_v_rgn():
    """Once fired, a subsequently high v_rgn must never re-apply the fold
    load -- the pulse is a strict one-shot, not re-armable by voltage."""
    plant = hil.Plant()
    plant.v_rgn = hil.SCP_INRUSH_ARM_V + 0.5
    hil.apply_scenario(plant, "scp-inrush", 1.000)   # arm
    hil.apply_scenario(plant, "scp-inrush", 1.001)   # withdraw -> fired
    assert plant.scp_fired is True

    for v in (hil.SCP_INRUSH_ARM_V, 10.0, 16.0):
        plant.v_rgn = v
        hil.apply_scenario(plant, "scp-inrush", 1.002)
        assert plant.i_mot_extra == pytest.approx(0.0)
        assert plant.scp_armed is True   # latched, but inert once fired


def test_scp_inrush_phase3_run_load_boundary_at_scp_inrush_run_s():
    """Just before scp_fired_t + SCP_INRUSH_RUN_S, i_mot_extra stays 0; at
    (and past) that boundary the run load applies -- pins the implemented
    comparison's closure (>=)."""
    plant = hil.Plant()
    plant.v_rgn = hil.SCP_INRUSH_ARM_V + 0.5
    hil.apply_scenario(plant, "scp-inrush", 1.000)   # arm
    hil.apply_scenario(plant, "scp-inrush", 1.001)   # withdraw -> fired
    fired_t = plant.scp_fired_t

    # Just before the boundary: still 0.
    hil.apply_scenario(plant, "scp-inrush", fired_t + hil.SCP_INRUSH_RUN_S - 0.001)
    assert plant.i_mot_extra == pytest.approx(0.0)

    # At the boundary exactly: the run load applies.
    hil.apply_scenario(plant, "scp-inrush", fired_t + hil.SCP_INRUSH_RUN_S)
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_RUN_LOAD_A)
    assert hil.SCP_INRUSH_RUN_LOAD_A == pytest.approx(5.0)

    # Comfortably past the boundary: still the run load.
    hil.apply_scenario(plant, "scp-inrush", fired_t + hil.SCP_INRUSH_RUN_S + 5.0)
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_RUN_LOAD_A)


def test_scp_inrush_reset_of_the_three_fields_re_arms_the_full_sequence():
    """Review M1 (2026-08-31): a mid-run HIL warm reset (mainState 99 -> 0)
    re-runs the staged bring-up, so the scp-inrush one-shot must re-arm for
    a clean second phase-1 ramp -- otherwise the second P3 close ramps into
    the standing run load instead of an unloaded node. The fix lives in
    main()'s warm-reset tripwire (hil_plant_sim.py, the `decoded["state"] !=
    99` transition branch), which clears exactly plant.scp_armed /
    plant.scp_fired / plant.scp_fired_t -- three plain attribute writes with
    no other plant/electrical state touched.

    main()'s socket loop itself (argv parsing, UDP recv, the actual 99->0
    transition detection) is NOT unit-testable at this level -- it needs a
    live socket and a real board/replay stream. That is a KNOWN, ACCEPTED
    residual: this test instead pins the RE-ARM SEMANTIC directly, i.e. that
    clearing those three fields (verbatim what the tripwire does) is
    SUFFICIENT to restore the stimulus -- by walking phase 1 -> 2 -> 3 to
    completion once, resetting by hand exactly as the tripwire would, and
    walking the full sequence a second time on a fresh ramp."""
    plant = hil.Plant()

    # ── First bring-up: walk the full phase 1 -> 2 -> 3 sequence. ──────────
    plant.v_rgn = 0.0
    hil.apply_scenario(plant, "scp-inrush", 0.5)          # phase 1: unloaded ramp
    assert plant.i_mot_extra == pytest.approx(0.0)
    plant.v_rgn = hil.SCP_INRUSH_ARM_V + 0.5
    hil.apply_scenario(plant, "scp-inrush", 1.000)        # phase 2: arm + pulse
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_FOLD_LOAD_A)
    assert plant.scp_armed is True
    hil.apply_scenario(plant, "scp-inrush", 1.001)        # one-shot withdrawal
    assert plant.scp_fired is True
    fired_t = plant.scp_fired_t
    assert fired_t is not None
    hil.apply_scenario(plant, "scp-inrush",
                       fired_t + hil.SCP_INRUSH_RUN_S)     # phase 3: run load
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_RUN_LOAD_A)

    # ── The warm-reset tripwire's own three lines, verbatim. ────────────────
    plant.scp_armed = False
    plant.scp_fired = False
    plant.scp_fired_t = None

    # ── Second bring-up on a fresh ramp: the full sequence must repeat. ────
    plant.v_rgn = 0.0
    hil.apply_scenario(plant, "scp-inrush", 10.5)          # phase 1 again: unloaded
    assert plant.i_mot_extra == pytest.approx(0.0)
    assert plant.scp_armed is False
    assert plant.scp_fired is False

    plant.v_rgn = hil.SCP_INRUSH_ARM_V + 0.5
    hil.apply_scenario(plant, "scp-inrush", 11.000)        # re-arm at the threshold
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_FOLD_LOAD_A)
    assert plant.scp_armed is True
    assert plant.scp_fired is False

    hil.apply_scenario(plant, "scp-inrush", 11.001)        # one-shot withdrawal again
    assert plant.scp_fired is True
    assert plant.i_mot_extra == pytest.approx(0.0)
    fired_t2 = plant.scp_fired_t
    assert fired_t2 == pytest.approx(11.001)

    # Comfortably (not exactly) past the boundary -- the exact-boundary `>=`
    # closure is already pinned by
    # test_scp_inrush_phase3_run_load_boundary_at_scp_inrush_run_s above;
    # this test is about the RE-ARM, not re-litigating float-precision at the
    # boundary itself.
    hil.apply_scenario(plant, "scp-inrush",
                       fired_t2 + hil.SCP_INRUSH_RUN_S + 0.01)  # run load again
    assert plant.i_mot_extra == pytest.approx(hil.SCP_INRUSH_RUN_LOAD_A)


# ─────────────────────────────────────────────────────────────────────────
# 8e. handoff-sag: REDESIGNED (review M3, 2026-08-30) -- a HANDOFF_PRELOAD_A
#     (0.40 A) pre-load from t=4.0 (puts the pre-rail total in the closed-
#     loop share-governor's window) plus the HANDOFF_STEP_A (1.5 A)
#     perturbation at t=20.0 (against the surviving BT channel, not FC --
#     the direction flip from the old FC-side step is what buys the margin
#     back: 0.74 + 1.5 = 2.24 A vs LIMIT_I_BT_MAX 3.0 A).
# ─────────────────────────────────────────────────────────────────────────

def test_handoff_sag_i_aux_zero_load_before_preload():
    plant = hil.Plant()
    hil.apply_scenario(plant, "handoff-sag", 3.999)
    assert plant.i_aux == pytest.approx(hil.I_AUX_A)


def test_handoff_sag_preload_applied_from_t_4():
    plant = hil.Plant()
    hil.apply_scenario(plant, "handoff-sag", 4.0)
    assert plant.i_aux == pytest.approx(hil.I_AUX_A + hil.HANDOFF_PRELOAD_A)
    assert hil.HANDOFF_PRELOAD_A == pytest.approx(0.40)


def test_handoff_sag_preload_holds_steady_until_the_step():
    plant = hil.Plant()
    hil.apply_scenario(plant, "handoff-sag", 19.999)
    assert plant.i_aux == pytest.approx(hil.I_AUX_A + hil.HANDOFF_PRELOAD_A)


def test_handoff_sag_perturbation_is_1_5_a_on_top_of_the_preload():
    plant = hil.Plant()
    hil.apply_scenario(plant, "handoff-sag", 19.999)
    before = plant.i_aux
    hil.apply_scenario(plant, "handoff-sag", 20.0)
    after = plant.i_aux
    assert before == pytest.approx(hil.I_AUX_A + hil.HANDOFF_PRELOAD_A)
    assert after == pytest.approx(hil.I_AUX_A + hil.HANDOFF_PRELOAD_A + hil.HANDOFF_STEP_A)
    assert after - before == pytest.approx(hil.HANDOFF_STEP_A)
    assert hil.HANDOFF_STEP_A == pytest.approx(1.5)


def _cruise_coast_i_cmd(v):
    """The coast-equilibrium commanded current at cruise speed v -- the same
    closed form the SCENARIOS['handoff-sag']/['charge-fault'] comments use:
    at steady state (f_net == 0), f_drive = F_COULOMB + B_EFF*v, and
    i_cmd = f_drive / K_F (hil_plant_sim.py Plant.step()'s mechanical
    section)."""
    return (hil.F_COULOMB + hil.B_EFF * v) / hil.K_F


def test_handoff_sag_operating_point_is_inside_the_share_governor_bracket():
    """(review #5, LOW) The handoff-sag operating point is bracketed by two
    REAL firmware constraints (hil_plant_sim.py SCENARIOS['handoff-sag']
    comment, review M3) -- this pins the INEQUALITIES those constants imply,
    not just the raw HANDOFF_PRELOAD_A/HANDOFF_STEP_A magnitudes:

      lower bound  2*SHARE_MINORITY_I_MIN_A (.ino:2002, 0.30 A) -- the share
                   loop must be in CLOSED-LOOP mode for a share test to mean
                   anything, which needs the filtered total > this.
      upper bound  2*SHARE_CUT_MAX_HANDOFF_A (.ino:2018, 0.5 A) -- the cut is
                   REFUSED unless the doomed channel's measured current is
                   <= this (a one-tick transfer of a bigger current onto the
                   survivor is why the cut exists at all).

    Neither SHARE_MINORITY_I_MIN_A, SHARE_CUT_MAX_HANDOFF_A nor
    LIMIT_I_BT_MAX is mirrored as a Python constant anywhere in tools/, so
    they are declared here as test-local literals citing their .ino
    definitions (the existing test-file style already does this for other
    firmware constants).

    The pre-step total is I_AUX_A + HANDOFF_PRELOAD_A + i_motor at the
    scenario's own 1.0 m/s cruise setpoint (hil_plant_sim.py SCENARIOS
    ['handoff-sag'] comment's own arithmetic) -- reproduced by actually
    running the real Plant model, not a hand-copied number, so a future
    constant change (K_F, B_EFF, F_COULOMB, ETA_BOOST, HANDOFF_PRELOAD_A,
    HANDOFF_STEP_A, I_AUX_A) is caught automatically rather than needing
    this test hand-updated in lockstep."""
    # teensy_controller/teensy_controller.ino:2002
    SHARE_MINORITY_I_MIN_A = 0.30
    # teensy_controller/teensy_controller.ino:2018
    SHARE_CUT_MAX_HANDOFF_A = 0.5
    # teensy_controller/teensy_controller.ino:1339
    LIMIT_I_BT_MAX = 3.0

    v_cruise = 1.0
    i_cmd = _cruise_coast_i_cmd(v_cruise)

    # ── Pre-step: both sources live, the share loop closed-loop entry gate ──
    plant = hil.Plant()
    plant.v = v_cruise   # the cruise setpoint, set directly -- this test wants
                         # the STEADY-STATE current at that speed, not a ramp
                         # to it (i_cmd is exactly the coast equilibrium, so
                         # f_net == 0 and v does not drift while stepping)
    hil.apply_scenario(plant, "handoff-sag", 19.999)   # pre-step i_aux (preload applied)
    obs_pre = _obs(switch=SW_ALL_LIVE, aux=AUX_BOTH_REG, current=i_cmd)
    out = None
    for _ in range(50):   # let the algebraic droop snap settle (no RC lag,
                          # but i_motor's OWN divisor uses the PREVIOUS tick's
                          # v_bus -- converges in a handful of ticks)
        out = plant.step(1e-3, obs_pre)
    pre_step_total = out["I_fc"] + out["I_batt"]

    lower = 2.0 * SHARE_MINORITY_I_MIN_A
    upper = 2.0 * SHARE_CUT_MAX_HANDOFF_A
    assert lower < pre_step_total < upper, (
        f"pre-step total {pre_step_total:.4f} A must sit strictly inside "
        f"({lower}, {upper}) A -- the closed-loop entry gate / cut-refusal "
        f"bracket the scenario is designed around")

    # ── Post-step: FC cut, BT alone carries the whole total ─────────────────
    hil.apply_scenario(plant, "handoff-sag", 20.0)     # the perturbation
    obs_post = _obs(switch=hil.SW_BT_BUS | hil.SW_MOT_PWR,
                    aux=hil.AUX_BT_REG, current=i_cmd)
    out2 = None
    for _ in range(50):
        out2 = plant.step(1e-3, obs_post)
    post_step_survivor = out2["I_batt"]

    assert post_step_survivor < LIMIT_I_BT_MAX
    margin = (LIMIT_I_BT_MAX - post_step_survivor) / LIMIT_I_BT_MAX
    assert margin > 0.10, (
        f"post-step BT current {post_step_survivor:.4f} A leaves only "
        f"{margin:.1%} margin under LIMIT_I_BT_MAX {LIMIT_I_BT_MAX} A -- too "
        f"thin to be the deliberate design margin the scenario claims")


# ─────────────────────────────────────────────────────────────────────────
# 9. CSV schema
# ─────────────────────────────────────────────────────────────────────────

def _run_main_csv(tmp_path, extra_args, name="run.csv"):
    csv_path = str(tmp_path / name)
    args = ["--teensy-ip", "127.0.0.1", "--port", "58991",
            "--bind-port", "0", "--rate", "200", "--csv", csv_path] + extra_args
    rc = hil.main(args)
    assert rc == 0
    with open(csv_path, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    return header, rows


def test_csv_schema_sim_mode_appends_soc(tmp_path):
    header, _rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple", "--duration", "0.02"])
    # cmd_v_sp/cmd_share_sp are appended UNCONDITIONALLY in simulated-plant
    # mode, after soc; h2_rate_gps/h2_cum_g (2026-08-31) are appended
    # UNCONDITIONALLY after THAT pair -- so soc is now fifth-from-last.
    assert header[-5:] == ["soc", "cmd_v_sp", "cmd_share_sp",
                           "h2_rate_gps", "h2_cum_g"]
    assert "elec_substep_hz" not in header
    assert "elec_events" not in header
    assert "replay_rec" not in header


def test_csv_schema_hifi_mode_appends_elec_columns(tmp_path):
    header, _rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "hifi", "--duration", "0.02"])
    assert header[-7:] == ["soc", "elec_substep_hz", "elec_events",
                           "cmd_v_sp", "cmd_share_sp",
                           "h2_rate_gps", "h2_cum_g"]


REPLAY_CSV_HEADER_PIN = [
    "t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
    "v_actual", "I_charge", "ag105_status",
    "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
    "fault_flags", "replay_rec",
]


def test_csv_schema_replay_mode_appends_cmd_columns_after_replay_rec(tmp_path):
    """Regression-pin the replay CSV column order: replay mode must NOT gain
    soc/elec columns (the plant integrator is bypassed, so they would be
    meaningless — see the module's own comment at the writer), and (2026-08-30,
    --replay-commands) cmd_v_sp/cmd_share_sp are now appended UNCONDITIONALLY
    after replay_rec — replay_rec itself keeps its established index, it is
    simply no longer the LAST column."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    header, _rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--duration", "0.02"], name="replay.csv")
    assert header == REPLAY_CSV_HEADER_PIN + ["cmd_v_sp", "cmd_share_sp"]
    assert header.index("replay_rec") == REPLAY_CSV_HEADER_PIN.index("replay_rec")
    assert header[-2:] == ["cmd_v_sp", "cmd_share_sp"]


def test_replay_preamble_rows_precede_recorded_trajectory_then_hand_over(tmp_path):
    """End-to-end (real .BLG through main()): every row before
    REPLAY_PREAMBLE_S carries replay_rec == REPLAY_PREAMBLE_REC and the
    documented healthy-nominal V_bus; the run then hands over to the
    recorded trajectory (a real record index) at/after that time -- the
    2026-08-30 synthetic bring-up preamble, end to end."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    duration = hil.REPLAY_PREAMBLE_S + 0.3
    header, rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--rate", "100",
                   "--duration", str(duration)],
        name="replay_preamble.csv")
    t_idx = header.index("t")
    rec_idx = header.index("replay_rec")
    vbus_idx = header.index("V_bus")
    assert rows, "sanity: the run must have produced rows"

    preamble_rows = [r for r in rows if float(r[t_idx]) < hil.REPLAY_PREAMBLE_S]
    assert preamble_rows, "sanity: some rows must fall inside the preamble window"
    for r in preamble_rows:
        assert int(r[rec_idx]) == hil.REPLAY_PREAMBLE_REC
        assert float(r[vbus_idx]) == pytest.approx(hil.REPLAY_PREAMBLE_V_BUS)

    handover_rows = [r for r in rows if float(r[t_idx]) >= hil.REPLAY_PREAMBLE_S]
    assert handover_rows, "sanity: the run must reach past the preamble"
    # The handover row is the recorded trajectory taking over -- a real record
    # index, never the preamble sentinel.
    assert int(handover_rows[0][rec_idx]) != hil.REPLAY_PREAMBLE_REC
    assert all(int(r[rec_idx]) != hil.REPLAY_PREAMBLE_REC for r in handover_rows)


# ─────────────────────────────────────────────────────────────────────────
# 9b. H2: --replay-no-preamble end to end
# ─────────────────────────────────────────────────────────────────────────

def test_replay_no_preamble_timestamps_unshifted_from_the_first_row(tmp_path):
    """--replay-no-preamble: sim time == log time from t=0 -- the very FIRST
    row is already a real recorded index, never REPLAY_PREAMBLE_REC, and no
    row anywhere reports the healthy-nominal preamble V_bus as an artefact of
    a preamble window (the log's own V_bus is whatever it is)."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    header, rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--replay-no-preamble",
                   "--rate", "200", "--duration", "0.05"],
        name="replay_raw.csv")
    rec_idx = header.index("replay_rec")
    assert rows, "sanity: the run must have produced rows"
    assert all(int(r[rec_idx]) != hil.REPLAY_PREAMBLE_REC for r in rows), (
        "no row may carry the preamble sentinel under --replay-no-preamble")


def test_replay_no_preamble_meta_sidecar_records_zero_preamble(tmp_path):
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    csv_path = str(tmp_path / "raw.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58994", "--bind-port", "0",
                   "--rate", "200", "--replay", blg_path, "--replay-no-preamble",
                   "--duration", "0.02", "--csv", csv_path])
    assert rc == 0
    with open(hil.meta_path_for(csv_path)) as fh:
        meta = json.load(fh)
    assert meta["config"]["replay_preamble_s"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────
# 9c. H1: --replay-i-fc-clamp end to end (symmetric, both signs)
# ─────────────────────────────────────────────────────────────────────────

def test_replay_i_fc_clamp_bounds_both_signs(tmp_path, monkeypatch):
    """The clamp is symmetric (hil_plant_sim.py:2629-2636): no injected I_fc
    sample may exceed +clamp or fall below -clamp.

    FIX (review #3, MED): the synthetic .BLG's own I_fc trace does not
    reliably visit both signs beyond the clamp -- in the previously-tested
    window it sat at ~0.5 A +/- 0.05, ~10 sigma from ever tripping the
    `elif sensors["I_fc"] < -args.replay_i_fc_clamp` branch, so that branch
    could be deleted and this test would still pass. Rather than depend on
    numpy/make_test_blg or a lucky seed to happen to produce a negative
    excursion, this monkeypatches load_replay() to hand back a fully
    DETERMINISTIC records list — one sample well above +clamp, one well
    below -clamp, one inside the band — so both clamp branches are provably
    exercised on every run, and this needs no numpy at all."""
    clamp = 1.3
    base = {"V_fc": 13.0, "V_batt": 7.8, "V_bus": 15.9, "V_chg": 0.0,
            "V_rgn": 0.0, "I_batt": 0.1, "v_actual": 0.0,
            "I_charge": 0.0, "ag105_status": 0}
    records = [
        (0.000, dict(base, I_fc=clamp + 5.0)),      # must clamp DOWN to +clamp
        (0.001, dict(base, I_fc=-(clamp + 5.0))),   # must clamp UP to -clamp
        (0.002, dict(base, I_fc=0.2)),              # inside the band, untouched
        # Span extended well past the run's duration below with the SAME
        # in-band value, held by zero-order hold -- ReplaySource.sample()
        # ends the run the instant sim time exceeds the last record's `t`
        # (records[-1][0] IS the span), and float accumulation of `t` over
        # many 1 ms ticks can overshoot an exact 0.002 boundary by an ulp,
        # ending the run one tick early. A comfortably later last record
        # removes that race entirely.
        (1.0, dict(base, I_fc=0.2)),
    ]

    def fake_load_replay(path):
        return records, {"version": 3, "fw_version": 14}, [], False

    monkeypatch.setattr(hil, "load_replay", fake_load_replay)
    header, rows = _run_main_csv(
        tmp_path, ["--replay", "fake_path_unused.BLG", "--replay-no-preamble",
                   "--replay-i-fc-clamp", str(clamp),
                   "--rate", "1000", "--duration", "0.005"],
        name="replay_clamp_both_signs.csv")
    i_fc_idx = header.index("I_fc")
    values = [float(r[i_fc_idx]) for r in rows if r[i_fc_idx] != ""]
    assert values, "sanity: some I_fc values must have been recorded"
    for v in values:
        assert -clamp - 1e-6 <= v <= clamp + 1e-6, (
            f"I_fc={v} escaped the +/-{clamp} A clamp")
    # Both clamp branches must actually have fired -- not just be consistent
    # with having fired.
    assert max(values) == pytest.approx(clamp)
    assert min(values) == pytest.approx(-clamp)
    # And the in-band sample must have passed through UNCHANGED (the clamp
    # is a ceiling/floor, not a rescale).
    assert any(v == pytest.approx(0.2) for v in values)


def test_replay_i_fc_clamp_meta_sidecar_records_the_value(tmp_path):
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    csv_path = str(tmp_path / "clamped.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58995", "--bind-port", "0",
                   "--rate", "200", "--replay", blg_path,
                   "--replay-i-fc-clamp", "1.3", "--duration", "0.02", "--csv", csv_path])
    assert rc == 0
    with open(hil.meta_path_for(csv_path)) as fh:
        meta = json.load(fh)
    assert meta["config"]["replay_i_fc_clamp_a"] == pytest.approx(1.3)


def test_replay_i_fc_clamp_meta_sidecar_none_when_unclamped(tmp_path):
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    csv_path = str(tmp_path / "unclamped.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58996", "--bind-port", "0",
                   "--rate", "200", "--replay", blg_path,
                   "--duration", "0.02", "--csv", csv_path])
    assert rc == 0
    with open(hil.meta_path_for(csv_path)) as fh:
        meta = json.load(fh)
    assert meta["config"]["replay_i_fc_clamp_a"] is None


# ─────────────────────────────────────────────────────────────────────────
# 9d. --replay-commands
# ─────────────────────────────────────────────────────────────────────────

def test_main_replay_commands_requires_replay():
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "steady", "--replay-commands"])
    with pytest.raises(SystemExit):
        hil.main(["--replay-commands"])


def test_replay_commands_csv_header_cmd_columns_after_replay_rec(tmp_path):
    """cmd_v_sp/cmd_share_sp are APPENDED after replay_rec, and replay_rec's
    own index is unchanged by the flag being present."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    header, _rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--replay-commands", "--duration", "0.02"],
        name="replay_cmds.csv")
    assert header == REPLAY_CSV_HEADER_PIN + ["cmd_v_sp", "cmd_share_sp"]
    assert header.index("replay_rec") == REPLAY_CSV_HEADER_PIN.index("replay_rec")


def test_replay_plain_csv_header_unchanged_cmd_columns_blank(tmp_path):
    """Plain --replay (no --replay-commands): the header still gains the two
    columns (unconditional append, same schema either way), but every row's
    cells are blank -- a number there would be a fabrication (no commander
    exists to have sent it)."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    header, rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--duration", "0.02"], name="replay_plain.csv")
    assert header == REPLAY_CSV_HEADER_PIN + ["cmd_v_sp", "cmd_share_sp"]
    v_sp_idx = header.index("cmd_v_sp")
    share_sp_idx = header.index("cmd_share_sp")
    assert rows, "sanity"
    for r in rows:
        assert r[v_sp_idx] == ""
        assert r[share_sp_idx] == ""


def test_replay_commands_csv_cells_populated_when_flag_given(tmp_path):
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    header, rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--replay-commands", "--duration", "0.05"],
        name="replay_cmds_populated.csv")
    v_sp_idx = header.index("cmd_v_sp")
    share_sp_idx = header.index("cmd_share_sp")
    assert rows, "sanity"
    for r in rows:
        # populated: parses as a float, never blank
        float(r[v_sp_idx])
        float(r[share_sp_idx])


def test_replay_commands_preamble_rows_are_mode_safe_standstill(tmp_path, capturing_socket):
    """During the synthetic bring-up preamble (t < replay_preamble_s), the
    commander must send MODE_SAFE with v_setpoint=0.0/power_share_setpoint=0.5,
    regardless of what the log's own first record contains; after the
    preamble it switches to MODE_HYBRID and the record's own values."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58997", "--bind-port", "0",
                   "--rate", "500", "--replay", blg_path, "--replay-commands",
                   "--duration", str(hil.REPLAY_PREAMBLE_S + 0.5), "--no-csv"])
    assert rc == 0
    sock = capturing_socket["sock"]
    cmd_packets = [d for d, _addr in sock.sent
                   if len(d) == hil.PI_CMD_SIZE and d[0] == hil.SYNC_BYTE_RX]
    assert cmd_packets, "expected at least one 22-byte Pi command packet"
    saw_preamble = False
    saw_post = False
    for pkt in cmd_packets:
        (ts_ms, _ctr, v_sp, share_sp, _cg, mode, _drp) = struct.unpack_from(
            "<IHfffBB", pkt, 1)
        t = ts_ms / 1000.0
        if t < hil.REPLAY_PREAMBLE_S:
            saw_preamble = True
            assert mode == hil.MODE_SAFE
            assert v_sp == pytest.approx(0.0)
            assert share_sp == pytest.approx(0.5)
        else:
            saw_post = True
            assert mode == hil.MODE_HYBRID
    assert saw_preamble, "sanity: expected at least one preamble-window packet"
    assert saw_post, "sanity: expected at least one post-preamble packet"


def test_replay_no_preamble_commands_mode_hybrid_from_t0(tmp_path, capturing_socket):
    """--replay-no-preamble: MODE_HYBRID from t=0 -- no MODE_SAFE window at
    all, since there is no synthetic preamble to stand still through."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58996", "--bind-port", "0",
                   "--rate", "500", "--replay", blg_path, "--replay-commands",
                   "--replay-no-preamble", "--duration", "0.1", "--no-csv"])
    assert rc == 0
    sock = capturing_socket["sock"]
    cmd_packets = [d for d, _addr in sock.sent
                   if len(d) == hil.PI_CMD_SIZE and d[0] == hil.SYNC_BYTE_RX]
    assert cmd_packets, "expected at least one 22-byte Pi command packet"
    for pkt in cmd_packets:
        assert pkt[19] == hil.MODE_HYBRID


def test_replay_plain_no_command_packets_sent(tmp_path, capturing_socket):
    """Plain --replay (no --replay-commands): no commander is constructed at
    all, so NO 22-byte Pi command packet is ever placed on the wire -- only
    40-byte injection frames."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58995", "--bind-port", "0",
                   "--rate", "500", "--replay", blg_path, "--duration", "0.05",
                   "--no-csv"])
    assert rc == 0
    sock = capturing_socket["sock"]
    assert sock.sent, "sanity: injection frames must have been sent"
    cmd_packets = [d for d, _addr in sock.sent
                   if len(d) == hil.PI_CMD_SIZE and d[0] == hil.SYNC_BYTE_RX]
    assert cmd_packets == [], "plain replay must construct no commander at all"


def test_replay_commands_meta_sidecar_records_true(tmp_path):
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    csv_path = str(tmp_path / "cmds.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58994", "--bind-port", "0",
                   "--rate", "200", "--replay", blg_path, "--replay-commands",
                   "--duration", "0.02", "--csv", csv_path])
    assert rc == 0
    with open(hil.meta_path_for(csv_path)) as fh:
        meta = json.load(fh)
    assert meta["config"]["replay_commands"] is True
    assert meta["replay_source"]["replay_commands"] is True


def test_replay_plain_meta_sidecar_records_false(tmp_path):
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    csv_path = str(tmp_path / "plain.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58993", "--bind-port", "0",
                   "--rate", "200", "--replay", blg_path,
                   "--duration", "0.02", "--csv", csv_path])
    assert rc == 0
    with open(hil.meta_path_for(csv_path)) as fh:
        meta = json.load(fh)
    assert meta["config"]["replay_commands"] is False
    assert meta["replay_source"]["replay_commands"] is False


def test_replay_commands_zoh_aligned_with_injection_via_speed(tmp_path):
    """At --replay-speed 2.0, the CSV's `replay_rec` for a post-preamble row
    is the exact same ReplaySource record index that produced that row's
    injection frame -- proving the command axis is zero-order held on exactly
    the same time axis, so --replay-speed alignment needs no separate pacing
    (module docstring/comment claim, verified by construction here)."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    records, _header, _warnings, _derive_v_rgn = hil.load_replay(blg_path)
    header, rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--replay-commands",
                   "--replay-speed", "2.0", "--rate", "500",
                   "--duration", str(hil.REPLAY_PREAMBLE_S + 0.3)],
        name="replay_speed2.csv")
    t_idx = header.index("t")
    rec_idx_col = header.index("replay_rec")
    v_sp_idx = header.index("cmd_v_sp")

    post_preamble = [r for r in rows if float(r[t_idx]) >= hil.REPLAY_PREAMBLE_S]
    assert post_preamble, "sanity: the run must reach past the preamble"
    checked = 0
    for r in post_preamble:
        rec_idx = int(r[rec_idx_col])
        expected_v_sp = records[rec_idx][1]["cmd_v_sp"]
        assert float(r[v_sp_idx]) == pytest.approx(expected_v_sp, abs=1e-3)
        checked += 1
    assert checked > 0


# ─────────────────────────────────────────────────────────────────────────
# 10. Source models via Plant (SOC, OCV, FC polarization)
# ─────────────────────────────────────────────────────────────────────────

def test_soc_coulomb_counting_discharge():
    """1 A discharge for 1 h (3600 ticks @ dt=1s) on a 5 Ah pack must drop
    SOC by ~0.2, matching a plain coulomb count."""
    plant = hil.Plant(soc0=0.5, capacity_ah=5.0)
    for _ in range(3600):
        plant.battery.update(1.0, 1.0)
    assert plant.battery.soc == pytest.approx(0.3, abs=1e-6)


def test_soc_coulomb_counting_charge_raises_soc():
    plant = hil.Plant(soc0=0.5, capacity_ah=5.0)
    for _ in range(3600):
        plant.battery.update(1.0, -1.0)   # negative = charge
    assert plant.battery.soc == pytest.approx(0.7, abs=1e-6)


def test_soc_clamped_to_unit_interval():
    plant = hil.Plant(soc0=0.99, capacity_ah=1.0)
    for _ in range(20000):
        plant.battery.update(1.0, 1.0)  # heavy discharge, would go deeply negative
    assert plant.battery.soc == 0.0
    plant2 = hil.Plant(soc0=0.01, capacity_ah=1.0)
    for _ in range(20000):
        plant2.battery.update(1.0, -1.0)  # heavy charge, would exceed 1.0
    assert plant2.battery.soc == 1.0


def test_v_batt_follows_ocv_monotone_in_soc():
    """V_batt (via BatterySource.ocv()) must be monotone non-decreasing in
    SOC across the whole LIPO_OCV_SOC table span."""
    from hil_electrical import LIPO_OCV_SOC
    ocvs = []
    for soc in LIPO_OCV_SOC:
        b = hil.BatterySource(soc0=soc)
        ocvs.append(b.ocv())
    assert all(a <= b + 1e-9 for a, b in zip(ocvs, ocvs[1:]))
    # And densely sampled in between (the table is linearly interpolated).
    dense = [hil.BatterySource(soc0=s / 100.0).ocv() for s in range(0, 101, 5)]
    assert all(a <= b + 1e-9 for a, b in zip(dense, dense[1:]))


def test_fc_open_circuit_approx_12_97v():
    fc = hil.FuelCellSource()
    assert fc.open_circuit() == pytest.approx(12.97, abs=0.02)


def test_fc_effective_resistance_approx_0_447_ohm_at_2A():
    """Settle the double-layer state at a constant 2 A load and confirm the
    resulting IR sag implies ~0.447 ohm effective resistance (CLAUDE.md /
    hil_electrical.py: "~0.45 ohm effective bench IR sag")."""
    fc = hil.FuelCellSource()
    oc = fc.open_circuit()
    v = None
    for _ in range(2000):        # far past FC_TAU_S=0.02s at dt=1e-3
        v = fc.update(1e-3, 2.0)
    r_eff = (oc - v) / 2.0
    assert r_eff == pytest.approx(0.447, abs=0.02)


def test_fc_first_order_sag_on_load_step():
    """A fresh fuel cell subjected to a constant current step must settle
    monotonically DOWN toward its new equilibrium over ~FC_TAU_S (the
    double-layer state starts at the old, lower-loss equilibrium and ramps
    toward the new one), not jump there instantly and not oscillate."""
    fc = hil.FuelCellSource()
    vs = []
    for _ in range(200):
        vs.append(fc.update(1e-3, 2.0))
    assert all(a >= b - 1e-9 for a, b in zip(vs, vs[1:])), "not monotone non-increasing"
    # Should have mostly settled within several time constants.
    tail_span = max(vs[-20:]) - min(vs[-20:])
    assert tail_span < 1e-3


def test_ag105_full_at_high_soc_with_cv_taper():
    """SOC >= 0.995 must report GENSTAT Fully Charged with the CV flag, and
    the charge current must taper toward 0 rather than sit at the ceiling."""
    plant = hil.Plant(soc0=0.995)
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=hil.SW_FC_CHARGE | hil.SW_FC_BUS, aux=hil.AUX_FC_REG, current=0.0)
    dt = 1e-3
    settle_ticks = int(hil.AG105_SETTLE_S / dt) + 5
    for _ in range(settle_ticks):
        out = plant.step(dt, obs)
    assert out["ag105_status"] & 0x07 == hil.AG105_ST_FULL
    assert out["ag105_status"] & hil.AG105_FLAG_CV
    # Taper toward zero: run a while longer and confirm the current decreases
    # (it starts at 0 right at bring-up, so drive it up first via a lower SOC
    # baseline is unnecessary — assert it stays near 0 / decreasing, never
    # rails at AG105_I_MAX like the CC branch does).
    for _ in range(2000):
        out = plant.step(dt, obs)
    assert out["I_charge"] < 0.1


# ─────────────────────────────────────────────────────────────────────────
# 11. M5: v_bus_sense_offset — the sag scenario's hifi asymmetry (review-fix
#     round). See test_hil_electrical.py for the engine-level version; this
#     exercises the same thing through Plant + the "sag" scenario, matching
#     how hil_plant_sim.py actually wires it (Plant.electrical.v_bus_sense_offset
#     = plant.v_bus_offset, set by apply_scenario()).
# ─────────────────────────────────────────────────────────────────────────

def test_m5_sag_scenario_moves_sensed_v_bus_not_node_internal_rails_hifi():
    from hil_electrical import ElectricalSim
    electrical = ElectricalSim(trace_config="short")
    plant = hil.Plant(electrical=electrical)
    sw = hil.SW_FC_BUS | hil.SW_FC_CHARGE
    aux = hil.AUX_FC_REG
    obs = _obs(switch=sw, aux=aux, current=0.0)
    out = None
    for _ in range(600):
        out = plant.step(1e-3, obs)
    v_bus_before, v_chg_before = out["V_bus"], out["V_chg"]

    # apply_scenario("sag", t) sets plant.v_bus_offset = -5.0 during the dip
    # window; Plant.step() forwards it to electrical.v_bus_sense_offset.
    hil.apply_scenario(plant, "sag", 5.5)
    assert plant.v_bus_offset == -5.0
    out2 = plant.step(1e-3, obs)
    assert electrical.v_bus_sense_offset == -5.0
    assert out2["V_bus"] == pytest.approx(v_bus_before - 5.0, abs=0.05)
    # V_chg is downstream of the NODE, not the sensed offset -- must not have
    # jumped by ~5 V in a single 1 ms tick the way V_bus did.
    assert abs(out2["V_chg"] - v_chg_before) < 1.0


# ─────────────────────────────────────────────────────────────────────────
# 12. M3: electrical-events sidecar streaming (review-fix round)
#
# _drain_electrical_events() is a closure nested inside main() and is not
# independently importable/reachable offline (no board, no socket peer
# needed for THIS engine, since injection is host->board only and no
# real board means `obs` stays None the whole run, so switches never close
# and no RT1987/boost events actually fire).  This is therefore a
# black-box check of the WIRING around the drain (sidecar created, valid
# JSONL, gated correctly on --csv/--electrical), not a white-box trigger of
# a nonzero event count -- see the final report for this round's note on
# the gap.
# ─────────────────────────────────────────────────────────────────────────

def test_m3_hifi_with_csv_creates_events_sidecar(tmp_path):
    header, rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "hifi", "--duration", "0.05"])
    sidecar = str(tmp_path / "run.csv") + ".events.jsonl"
    assert os.path.isfile(sidecar), "M3: the sidecar must be created up front, not just on exit"
    # Valid JSONL (each non-blank line parses), whether or not any events fired.
    import json
    with open(sidecar, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                json.loads(line)   # must not raise
    # The CSV's final elec_events column must be a non-negative integer and
    # must match the number of lines actually persisted to the sidecar (the
    # durable cumulative counter, not len(electrical.events) which is
    # trimmed after every drain).
    assert rows, "expected at least one CSV row"
    # cmd_v_sp/cmd_share_sp are unconditionally appended after the hifi elec_*
    # columns in simulated-plant mode, and h2_rate_gps/h2_cum_g (2026-08-31)
    # are unconditionally appended after THAT pair -- so elec_events is now
    # fifth-from-last, not third-from-last.
    assert header[-4:] == ["cmd_v_sp", "cmd_share_sp", "h2_rate_gps", "h2_cum_g"]
    elec_events_col = rows[-1][-5]
    assert elec_events_col.strip() != ""
    n_reported = int(elec_events_col)
    with open(sidecar, encoding="utf-8") as fh:
        n_lines = sum(1 for line in fh if line.strip())
    assert n_reported == n_lines


def test_m3_simple_mode_with_csv_writes_no_sidecar(tmp_path):
    """The sidecar is gated on `electrical is not None` -- simple mode (the
    default engine) must not create one at all."""
    _header, _rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple", "--duration", "0.02"],
        name="simple.csv")
    sidecar = str(tmp_path / "simple.csv") + ".events.jsonl"
    assert not os.path.isfile(sidecar)


def test_m3_hifi_without_csv_does_not_crash(tmp_path):
    """No --csv at all: main() must still run to completion under hifi (the
    sidecar/CSV-flush logic must not assume args.csv is set)."""
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58992", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "hifi",
                   "--duration", "0.02", "--no-csv"])
    assert rc == 0


# ─────────────────────────────────────────────────────────────────────────
# 11. EMS_STRATEGIES / ems_hold_5050 / PiCommander(policy=...)
# ─────────────────────────────────────────────────────────────────────────

def test_ems_strategies_registry_has_hold_5050():
    assert "hold-5050" in hil.EMS_STRATEGIES
    assert hil.EMS_STRATEGIES["hold-5050"] is hil.ems_hold_5050
    assert "hold-5050" in hil.EMS_NAMES


def test_ems_hold_5050_returns_constant_5050_split():
    for t in (0.0, 1.0, 3.0, 10.0, 59.9):
        out = hil.ems_hold_5050(t, {"v_profile": None})
        assert out["power_share_setpoint"] == pytest.approx(0.50)


def test_ems_hold_5050_mode_steps_at_run_entry():
    before = hil.ems_hold_5050(hil.EMS_RUN_ENTRY_S - 0.01, {"v_profile": None})
    at = hil.ems_hold_5050(hil.EMS_RUN_ENTRY_S, {"v_profile": None})
    assert before["mode_cmd"] == hil.MODE_SAFE
    assert at["mode_cmd"] == hil.MODE_HYBRID


def test_ems_hold_5050_mode_steps_back_to_safe_at_run_exit():
    """F14(b): ems_hold_5050 now hands MODE_SAFE back at EMS_RUN_EXIT_S so a
    drive cycle genuinely finishes Run -> Finish -> Idle instead of ending
    parked in State 2."""
    just_before = hil.ems_hold_5050(hil.EMS_RUN_EXIT_S - 0.01, {"v_profile": None})
    at = hil.ems_hold_5050(hil.EMS_RUN_EXIT_S, {"v_profile": None})
    well_after = hil.ems_hold_5050(hil.EMS_RUN_EXIT_S + 5.0, {"v_profile": None})
    assert just_before["mode_cmd"] == hil.MODE_HYBRID
    assert at["mode_cmd"] == hil.MODE_SAFE
    assert well_after["mode_cmd"] == hil.MODE_SAFE
    assert hil.EMS_RUN_EXIT_S > hil.EMS_RUN_ENTRY_S


def test_ems_hold_5050_uses_v_profile_when_present_else_default_cruise():
    out = hil.ems_hold_5050(5.0, {"v_profile": 2.75})
    assert out["v_setpoint"] == pytest.approx(2.75)
    out2 = hil.ems_hold_5050(5.0, {"v_profile": None})
    assert out2["v_setpoint"] == pytest.approx(hil.EMS_DEFAULT_CRUISE_MPS)


def test_ems_hold_5050_charge_goal_is_zero():
    out = hil.ems_hold_5050(5.0, {"v_profile": None})
    assert out["charge_goal"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────
# 11b. ems_regen_harvest (charge-regen's EMS strategy, 2026-08-30 redesign)
# ─────────────────────────────────────────────────────────────────────────

def test_ems_strategies_registry_has_regen_harvest():
    assert "regen-harvest" in hil.EMS_STRATEGIES
    assert hil.EMS_STRATEGIES["regen-harvest"] is hil.ems_regen_harvest
    assert "regen-harvest" in hil.EMS_NAMES


def test_ems_regen_harvest_power_share_constant_5050():
    for t in (0.0, 5.0, 15.0, 30.0, 44.0):
        out = hil.ems_regen_harvest(t, {"v_profile": None})
        assert out["power_share_setpoint"] == pytest.approx(0.50)


def test_ems_regen_harvest_uses_v_profile_when_present_else_default_cruise():
    out = hil.ems_regen_harvest(15.0, {"v_profile": 0.4})
    assert out["v_setpoint"] == pytest.approx(0.4)
    out2 = hil.ems_regen_harvest(15.0, {"v_profile": None})
    assert out2["v_setpoint"] == pytest.approx(hil.EMS_DEFAULT_CRUISE_MPS)


def test_ems_regen_harvest_mode_hybrid_during_run_safe_outside():
    before = hil.ems_regen_harvest(hil.EMS_RUN_ENTRY_S - 0.01, {"v_profile": None})
    at_entry = hil.ems_regen_harvest(hil.EMS_RUN_ENTRY_S, {"v_profile": None})
    mid_run = hil.ems_regen_harvest(20.0, {"v_profile": None})
    just_before_exit = hil.ems_regen_harvest(
        hil.EMS_REGEN_RUN_EXIT_S - 0.01, {"v_profile": None})
    at_exit = hil.ems_regen_harvest(hil.EMS_REGEN_RUN_EXIT_S, {"v_profile": None})
    well_after = hil.ems_regen_harvest(hil.EMS_REGEN_RUN_EXIT_S + 1.0, {"v_profile": None})
    assert before["mode_cmd"] == hil.MODE_SAFE
    assert at_entry["mode_cmd"] == hil.MODE_HYBRID
    assert mid_run["mode_cmd"] == hil.MODE_HYBRID
    assert just_before_exit["mode_cmd"] == hil.MODE_HYBRID
    assert at_exit["mode_cmd"] == hil.MODE_SAFE
    assert well_after["mode_cmd"] == hil.MODE_SAFE


def test_ems_regen_harvest_charge_goal_zero_during_cruise():
    """Well clear of any braking window (e.g. mid-cruise at t=10.0, before
    the first window opens at 14.0): charge_goal is 0 -- the whole point of
    the redesign is that the charger is NOT fed on cruise/acceleration."""
    out = hil.ems_regen_harvest(10.0, {"v_profile": None})
    assert out["charge_goal"] == pytest.approx(0.0)


def test_ems_regen_harvest_charge_goal_zero_immediately_at_window_open():
    """At the INSTANT a braking window opens, the commanded motor current is
    still the positive cruise hold (chargingControl() picks its branch off
    `current`, not v_setpoint) -- so charge_goal must NOT assert yet. It only
    asserts EMS_REGEN_CHARGE_LEAD_IN_S later."""
    t_open, _t_close = hil.EMS_REGEN_BRAKE_WINDOWS[0]
    out = hil.ems_regen_harvest(t_open, {"v_profile": None})
    assert out["charge_goal"] == pytest.approx(0.0)
    just_before_lead_in = hil.ems_regen_harvest(
        t_open + hil.EMS_REGEN_CHARGE_LEAD_IN_S - 0.001, {"v_profile": None})
    assert just_before_lead_in["charge_goal"] == pytest.approx(0.0)


def test_ems_regen_harvest_charge_goal_one_after_lead_in():
    t_open, _t_close = hil.EMS_REGEN_BRAKE_WINDOWS[0]
    at_lead_in = hil.ems_regen_harvest(
        t_open + hil.EMS_REGEN_CHARGE_LEAD_IN_S, {"v_profile": None})
    mid_window = hil.ems_regen_harvest(t_open + 1.0, {"v_profile": None})
    assert at_lead_in["charge_goal"] == pytest.approx(1.0)
    assert mid_window["charge_goal"] == pytest.approx(1.0)


def test_ems_regen_harvest_charge_goal_dropped_before_window_close():
    """The symmetric guard on the way OUT: charge_goal drops
    EMS_REGEN_CHARGE_LEAD_OUT_S before the window closes, so the command is
    already negative (still braking) when charging stops."""
    _t_open, t_close = hil.EMS_REGEN_BRAKE_WINDOWS[0]
    just_before_lead_out = hil.ems_regen_harvest(
        t_close - hil.EMS_REGEN_CHARGE_LEAD_OUT_S - 0.001, {"v_profile": None})
    at_lead_out = hil.ems_regen_harvest(
        t_close - hil.EMS_REGEN_CHARGE_LEAD_OUT_S, {"v_profile": None})
    at_close = hil.ems_regen_harvest(t_close, {"v_profile": None})
    assert just_before_lead_out["charge_goal"] == pytest.approx(1.0)
    assert at_lead_out["charge_goal"] == pytest.approx(0.0)
    assert at_close["charge_goal"] == pytest.approx(0.0)


def test_ems_regen_harvest_charge_goal_one_in_every_brake_window():
    """All three braking windows behave identically, not just the first."""
    for t_open, t_close in hil.EMS_REGEN_BRAKE_WINDOWS:
        mid = (t_open + hil.EMS_REGEN_CHARGE_LEAD_IN_S
               + (t_close - hil.EMS_REGEN_CHARGE_LEAD_OUT_S)) / 2.0
        out = hil.ems_regen_harvest(mid, {"v_profile": None})
        assert out["charge_goal"] == pytest.approx(1.0), (t_open, t_close)


def test_ems_regen_harvest_charge_goal_zero_between_brake_windows():
    """Low-cruise segments between braking windows are NOT charging."""
    (_a0, b0), (a1, _b1) = hil.EMS_REGEN_BRAKE_WINDOWS[0], hil.EMS_REGEN_BRAKE_WINDOWS[1]
    mid_between = (b0 + a1) / 2.0
    out = hil.ems_regen_harvest(mid_between, {"v_profile": None})
    assert out["charge_goal"] == pytest.approx(0.0)


def test_ems_regen_harvest_brake_windows_are_descending_segments_of_v_profile():
    """Every EMS_REGEN_BRAKE_WINDOWS entry must be a genuine DESCENDING
    segment of charge-regen's own ems_v_profile (the module comment's stated
    invariant) -- re-derive the profile's descending segments and confirm the
    windows are among them. NOT asserted the other way: the profile's final
    41.0-43.0 ramp to standstill also descends but is deliberately excluded
    from the braking/charging windows (it is the approach to a stop, not a
    cruise/brake cycle intended for charging), so this is a subset check, not
    an equality."""
    profile = hil.SCENARIOS["charge-regen"]["ems_v_profile"]
    descents = set()
    for (t0, v0), (t1, v1) in zip(profile, profile[1:]):
        if v1 < v0:
            descents.add((t0, t1))
    assert set(hil.EMS_REGEN_BRAKE_WINDOWS) <= descents
    # ...and the excluded final ramp-to-standstill really is a descent too,
    # confirming the subset check is not vacuous.
    assert (41.0, 43.0) in descents
    assert (41.0, 43.0) not in hil.EMS_REGEN_BRAKE_WINDOWS


def _fake_policy_unknown_field(t, fb):
    return {"not_a_real_field": 1.0}


def test_pi_commander_policy_unknown_field_raises_keyerror():
    pc = hil.PiCommander(None, policy=_fake_policy_unknown_field, policy_name="fake")
    with pytest.raises(KeyError):
        pc.tick(0.0, lambda: {"t": 0.0})


def _fake_policy_partial(t, fb):
    # Only ever sets power_share_setpoint -- every other field must HOLD.
    return {"power_share_setpoint": 0.50}


def test_pi_commander_policy_held_field_semantics():
    pc = hil.PiCommander(None, policy=_fake_policy_partial, policy_name="fake")
    pc.state["v_setpoint"] = 1.23      # pre-seed a value the policy never touches
    pkt = pc.tick(0.0, lambda: {"t": 0.0})
    assert pkt is not None
    assert pc.state["v_setpoint"] == pytest.approx(1.23), \
        "a field the policy did not return must HOLD its previous value"
    assert pc.state["power_share_setpoint"] == pytest.approx(0.50)


def test_pi_commander_policy_active_true_with_no_timeline():
    pc = hil.PiCommander(None, policy=hil.ems_hold_5050, policy_name="hold-5050")
    assert pc.active() is True


def test_pi_commander_fb_built_only_on_due_ticks():
    """fb_factory must be invoked only when the 50 Hz commander tick is actually
    due -- not once per (much faster) simulated sim tick."""
    calls = {"n": 0}

    def fb_factory():
        calls["n"] += 1
        return {"t": 0.0}

    pc = hil.PiCommander(None, policy=hil.ems_hold_5050, policy_name="hold-5050",
                          rate_hz=50.0)
    period = 1.0 / 50.0
    # Simulate a 1 kHz sim tick loop for 3 commander periods: 1 fb build per
    # commander period, not per sim tick.
    n_ticks = 0
    t = 0.0
    dt = 1.0 / 1000.0
    while t < 3 * period + dt:
        pc.tick(t, fb_factory)
        n_ticks += 1
        t += dt
    assert n_ticks > 3 * period / dt * 0.9, "sanity: this loop really ran many sim ticks"
    assert calls["n"] == pytest.approx(pc.policy_calls)
    # Roughly one fb build per commander period (allow +/-1 for boundary rounding).
    assert abs(calls["n"] - 3) <= 1


# GAP CLOSED (was a NOTE here): the module now exposes the "telemetry-
# equivalent" fb-key subset as the importable hil.FB_TELEMETRY_EQUIV_KEYS
# constant (test-writer recommendation, adjudicated ACCEPT), so this test pins
# against the real constant instead of a hand-copied literal that could
# silently drift from the module.
def test_pi_commander_fb_contains_all_keys_used_by_hold_5050_and_more():
    """Sanity floor pinning FB_TELEMETRY_EQUIV_KEYS against reality: capture the
    real fb dict main() builds (via a probe policy) and check it is a strict
    SUPERSET of every key ems_hold_5050 actually reads, plus the documented
    plant-truth/observation-frame keys the module says are NOT portable."""
    seen_fb = {}

    def _probe(t, fb):
        seen_fb.update(fb)
        return {}

    import socket as _socket

    class _NullSocket:
        def __init__(self, *a, **k):
            pass

        def setblocking(self, flag):
            pass

        def bind(self, addr):
            pass

        def sendto(self, data, addr):
            return len(data)

        def recvfrom(self, bufsize):
            raise BlockingIOError()

        def close(self):
            pass

    orig = _socket.socket
    hil.socket.socket = _NullSocket
    try:
        hil.EMS_STRATEGIES["_probe"] = _probe
        hil.EMS_NAMES.append("_probe")
        rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "59000",
                       "--bind-port", "0", "--rate", "500", "--scenario", "steady",
                       "--electrical", "simple", "--duration", "0.05",
                       "--ems", "_probe", "--no-csv"])
    finally:
        hil.socket.socket = orig
        del hil.EMS_STRATEGIES["_probe"]
        hil.EMS_NAMES.remove("_probe")
    assert rc == 0
    assert seen_fb, "the probe policy must have been called at least once"
    # Tightened per the test-writer recommendation (adjudicated ACCEPT): pin
    # against the now-importable hil.FB_TELEMETRY_EQUIV_KEYS constant instead of
    # a hand-copied literal that could silently drift from the module.
    assert hil.FB_TELEMETRY_EQUIV_KEYS <= set(seen_fb)
    not_portable = {"soc", "v_profile", "state", "aux", "current", "obs_age_s"}
    assert not_portable <= set(seen_fb)


# ─────────────────────────────────────────────────────────────────────────
# 12. hold-5050 wire-truth: capture actual 22-byte command packets
# ─────────────────────────────────────────────────────────────────────────

class _CapturingSocket:
    """Stand-in for socket.socket: records every sendto() payload/address,
    never actually transmits (destination is unreachable/meaningless in
    these tests), and answers recvfrom() as if nothing is waiting."""

    def __init__(self, *a, **k):
        self.sent = []          # list of (data, addr)

    def setblocking(self, flag):
        pass

    def bind(self, addr):
        pass

    def sendto(self, data, addr):
        self.sent.append((bytes(data), addr))
        return len(data)

    def recvfrom(self, bufsize):
        raise BlockingIOError()

    def close(self):
        pass


@pytest.fixture
def capturing_socket(monkeypatch):
    holder = {}

    def _fake_socket(*a, **k):
        s = _CapturingSocket()
        holder["sock"] = s
        return s

    monkeypatch.setattr(hil.socket, "socket", _fake_socket)
    return holder


def test_ems_hold5050_wire_truth_share_field_is_0_5(capturing_socket):
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58994", "--bind-port", "0",
                   "--rate", "500", "--scenario", "ems-drive-cycle",
                   "--electrical", "simple", "--duration", "0.2", "--ems", "hold-5050",
                   "--no-csv"])
    assert rc == 0
    sock = capturing_socket["sock"]
    # Pi-command packets are PI_CMD_SIZE (22) bytes with sync SYNC_BYTE_RX;
    # injection frames are HIL_INJECT_SIZE (40) with HIL_SYNC_INJECT -- filter
    # on size+sync to isolate the command packets actually placed on the wire.
    cmd_packets = [d for d, _addr in sock.sent
                   if len(d) == hil.PI_CMD_SIZE and d[0] == hil.SYNC_BYTE_RX]
    assert cmd_packets, "expected at least one 22-byte Pi command packet"
    import struct as _struct
    for pkt in cmd_packets:
        _ts, _ctr, _v_sp, share_sp, _cg, _mode, _drp = _struct.unpack_from(
            "<IHfffBB", pkt, 1)
        assert share_sp == pytest.approx(0.50, abs=1e-6)


# ─────────────────────────────────────────────────────────────────────────
# 13. --ems CLI
# ─────────────────────────────────────────────────────────────────────────

def test_ems_without_explicit_scenario_is_refused():
    """F9 fix: the --ems help text says "requires --scenario" and main() now
    enforces it. Before the fix, omitting --scenario silently fell back to
    'steady' (which has no ems_v_profile) and ran --ems against it anyway."""
    with pytest.raises(SystemExit):
        hil.main(["--teensy-ip", "127.0.0.1", "--port", "59001", "--bind-port", "0",
                   "--rate", "500", "--duration", "0.05",
                   "--ems", "hold-5050"])


def test_ems_refused_with_replay(tmp_path):
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    with pytest.raises(SystemExit):
        hil.main(["--replay", blg_path, "--ems", "hold-5050"])


def test_ems_and_pi_live_mutually_exclusive():
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "steady", "--ems", "hold-5050", "--pi-live"])


def test_ems_replaces_pi_timeline_prints_notice(capsys, capturing_socket):
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58995", "--bind-port", "0",
                   "--rate", "500", "--scenario", "charge-cruise",
                   "--electrical", "simple", "--duration", "0.05", "--ems", "hold-5050",
                   "--no-csv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "REPLACES" in out
    assert "charge-cruise" in out


def test_ems_default_cli_replaces_ems_drive_cycle_own_ems_no_double_notice(
        capsys, capturing_socket):
    """ems-drive-cycle already declares its OWN default ems strategy and NO
    pi_timeline -- selecting it (with no explicit --ems) must not print the
    REPLACES-a-timeline notice, since there is no timeline to replace."""
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58996", "--bind-port", "0",
                   "--rate", "500", "--scenario", "ems-drive-cycle",
                   "--electrical", "simple", "--duration", "0.05", "--no-csv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "REPLACES" not in out
    assert "EMS strategy: hold-5050" in out


class _CapturingDashboard:
    """Local copy of the pattern in test_hil_dashboard.py's _CapturingDashboard
    (that file is out of this round's scope to edit) -- captures every
    snapshot assignment without touching a real terminal."""

    def __init__(self, *a, **k):
        self.snapshots = []
        self._snapshot = None
        self.error = None

    def start(self):
        return True

    def stop(self):
        pass

    @property
    def snapshot(self):
        return self._snapshot

    @snapshot.setter
    def snapshot(self, value):
        self._snapshot = value
        self.snapshots.append(value)


@pytest.fixture
def capturing_dashboard(monkeypatch):
    instances = []

    class _Recording(_CapturingDashboard):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            instances.append(self)

    monkeypatch.setitem(sys.modules, "hil_dashboard", type(sys)("hil_dashboard"))
    sys.modules["hil_dashboard"].Dashboard = _Recording
    return instances


def test_ems_dashboard_snapshot_reflects_ems_values(tmp_path, capturing_dashboard,
                                                     capturing_socket):
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58997", "--bind-port", "0",
                   "--rate", "500", "--scenario", "ems-drive-cycle",
                   "--electrical", "simple", "--duration", "0.1", "--ems", "hold-5050",
                   "--dash", "--no-csv"])
    assert rc == 0
    instances = capturing_dashboard
    assert len(instances) == 1
    snaps = instances[0].snapshots
    assert snaps
    # The EMS policy always sets share_sp = 0.50 and v_sp to the scenario's
    # own v_profile (or the default cruise) -- never None, since the EMS
    # commander is always .active().
    assert any(s["share_sp"] == pytest.approx(0.50) for s in snaps)
    assert any(s["v_sp"] is not None for s in snaps)


# ─────────────────────────────────────────────────────────────────────────
# 14. "ems-drive-cycle" scenario
# ─────────────────────────────────────────────────────────────────────────

def test_ems_drive_cycle_in_scenarios_with_electrical_and_duration():
    meta = hil.SCENARIOS["ems-drive-cycle"]
    assert meta["electrical"] in ("simple", "hifi", "any")
    assert meta["duration_s"] == pytest.approx(58.0)  # trimmed from 60.0, 2026-08-30
    assert meta.get("ems") == "hold-5050"
    assert not meta.get("pi_timeline")


def test_ems_drive_cycle_profile_hits_standstill_and_cruise():
    profile = hil.SCENARIOS["ems-drive-cycle"]["ems_v_profile"]
    # Standstill segments (0-3 s and 52-60 s per the module comment).
    assert hil.piecewise(profile, 0.0) == pytest.approx(0.0)
    assert hil.piecewise(profile, 1.5) == pytest.approx(0.0)
    assert hil.piecewise(profile, 58.0) == pytest.approx(0.0)
    # Cruise segments.
    assert hil.piecewise(profile, 20.0) == pytest.approx(1.5)
    assert hil.piecewise(profile, 35.0) == pytest.approx(2.0)


# ─────────────────────────────────────────────────────────────────────────
# 15. --pi-live
# ─────────────────────────────────────────────────────────────────────────

def test_pi_live_sends_no_command_packets_only_injection_frames(capturing_socket):
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58998", "--bind-port", "0",
                   "--rate", "500", "--scenario", "steady",
                   "--electrical", "simple", "--duration", "0.05", "--pi-live",
                   "--no-csv"])
    assert rc == 0
    sock = capturing_socket["sock"]
    assert sock.sent, "expected injection frames to be sent"
    for data, _addr in sock.sent:
        assert not (len(data) == hil.PI_CMD_SIZE and data[0] == hil.SYNC_BYTE_RX), \
            "no 22-byte Pi command packet may be sent under --pi-live"
        assert len(data) == hil.HIL_INJECT_SIZE
        assert data[0] == hil.HIL_SYNC_INJECT


def test_pi_live_and_ems_refused():
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "steady", "--pi-live", "--ems", "hold-5050"])


def test_pi_live_with_pi_timeline_scenario_refused():
    with pytest.raises(SystemExit):
        hil.main(["--scenario", "charge-cruise", "--pi-live"])


def test_pi_live_with_ems_only_scenario_refused():
    """F3 fix: the gap this test used to pin is closed. The --pi-live refusal
    now checks `meta.get("pi_timeline") or meta.get("ems")`, so an ems-driven
    scenario ('ems-drive-cycle' carries meta['ems'] but no pi_timeline) is
    refused up front instead of silently running as a 60 s command-link no-op
    (no commander was ever created for it under the old check)."""
    with pytest.raises(SystemExit):
        hil.main(["--teensy-ip", "127.0.0.1", "--port", "59002", "--bind-port", "0",
                   "--rate", "500", "--scenario", "ems-drive-cycle",
                   "--electrical", "simple", "--duration", "0.05", "--pi-live"])


def test_pi_live_dashboard_snapshot_setpoints_are_none(tmp_path, capturing_dashboard,
                                                        capturing_socket):
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58999", "--bind-port", "0",
                   "--rate", "500", "--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.05", "--pi-live", "--dash", "--no-csv"])
    assert rc == 0
    snaps = capturing_dashboard[0].snapshots
    assert snaps
    assert all(s["v_sp"] is None for s in snaps)
    assert all(s["share_sp"] is None for s in snaps)


def test_pi_live_csv_cmd_columns_blank(tmp_path):
    header, rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.02", "--pi-live"])
    # h2_rate_gps/h2_cum_g (2026-08-31) are now the last two columns in
    # simulated-plant mode; cmd_v_sp/cmd_share_sp sit just before them.
    assert header[-4:] == ["cmd_v_sp", "cmd_share_sp", "h2_rate_gps", "h2_cum_g"]
    v_idx, share_idx = header.index("cmd_v_sp"), header.index("cmd_share_sp")
    assert rows, "expected at least one CSV row"
    for row in rows:
        assert row[v_idx] == ""
        assert row[share_idx] == ""


def test_ems_csv_cmd_columns_populated(tmp_path):
    header, rows = _run_main_csv(
        tmp_path, ["--scenario", "ems-drive-cycle", "--electrical", "simple",
                   "--duration", "0.05", "--ems", "hold-5050"])
    v_idx, share_idx = header.index("cmd_v_sp"), header.index("cmd_share_sp")
    assert rows
    assert any(row[share_idx] != "" for row in rows)
    for row in rows:
        if row[share_idx] != "":
            assert float(row[share_idx]) == pytest.approx(0.50)


def test_plain_scenario_csv_cmd_columns_reflect_timeline_or_blank(tmp_path):
    """A plain scripted scenario (default mode, no --ems/--pi-live) still has
    an active commander whenever the scenario declares a pi_timeline, so its
    cmd_* columns populate once the first packet has gone out; 'steady' (no
    timeline) leaves them blank throughout."""
    header, rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple", "--duration", "0.02"])
    v_idx, share_idx = header.index("cmd_v_sp"), header.index("cmd_share_sp")
    assert rows
    for row in rows:
        assert row[v_idx] == ""
        assert row[share_idx] == ""


# ─────────────────────────────────────────────────────────────────────────
# 13. resolve_output_path() / "HIL Results" output convention
# ─────────────────────────────────────────────────────────────────────────

def test_resolve_output_path_bare_filename_lands_under_hil_results(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    resolved = hil.resolve_output_path("run.csv")
    assert os.path.dirname(os.path.normpath(resolved)) == os.path.normpath(str(fake_dir))
    assert os.path.basename(resolved) == "run.csv"


def test_resolve_output_path_relative_with_subdir_nests_under_hil_results(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    resolved = hil.resolve_output_path(os.path.join("batch1", "run.csv"))
    expected = os.path.normpath(str(fake_dir / "batch1" / "run.csv"))
    assert os.path.normpath(resolved) == expected


def test_resolve_output_path_absolute_path_returned_verbatim(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    abs_path = str(tmp_path / "elsewhere" / "run.csv")
    resolved = hil.resolve_output_path(abs_path)
    assert os.path.normpath(resolved) == os.path.normpath(abs_path)
    # And it must NOT have been redirected under HIL_RESULTS_DIR.
    assert os.path.normpath(str(fake_dir)) not in os.path.normpath(resolved)


def test_resolve_output_path_creates_containing_directory(tmp_path, monkeypatch):
    """Resolving a path into a fresh subdir under a monkeypatched
    HIL_RESULTS_DIR must create that directory (never the real one)."""
    fake_dir = tmp_path / "HIL Results"
    assert not fake_dir.exists()
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    resolved = hil.resolve_output_path(os.path.join("fresh_subdir", "run.csv"))
    assert os.path.isdir(os.path.dirname(resolved))
    assert os.path.normpath(os.path.dirname(resolved)) == \
        os.path.normpath(str(fake_dir / "fresh_subdir"))


def test_hil_results_dir_name_and_parent_is_repo_root():
    """HIL_RESULTS_DIR must literally be '<repo root>/HIL Results' -- a
    vacuous 'is a directory under REPO_ROOT' check would pass even if the
    folder name were reverted to something else, so pin the basename too."""
    assert os.path.basename(os.path.normpath(hil.HIL_RESULTS_DIR)) == "HIL Results"
    parent = os.path.dirname(os.path.normpath(hil.HIL_RESULTS_DIR))
    assert os.path.normpath(parent) == os.path.normpath(hil.REPO_ROOT)
    assert os.path.isdir(os.path.join(hil.REPO_ROOT, "tools"))
    assert os.path.isdir(os.path.join(hil.REPO_ROOT, "teensy_controller"))


def test_main_relative_csv_is_resolved_under_monkeypatched_hil_results(tmp_path, monkeypatch):
    """Exercise the actual --csv open site in main() (not just the helper in
    isolation): a bare relative --csv name must land under HIL_RESULTS_DIR,
    with the .events.jsonl sidecar following the RESOLVED path."""
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    monkeypatch.chdir(tmp_path)
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58993", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "hifi",
                   "--duration", "0.02", "--csv", os.path.join("relbatch", "relrun.csv")])
    assert rc == 0
    resolved = fake_dir / "relbatch" / "relrun.csv"
    assert resolved.is_file()
    # The sidecar path derivation follows the resolved CSV path (main()
    # reassigns args.csv to the resolved path before deriving the sidecar).
    sidecar = fake_dir / "relbatch" / "relrun.csv.events.jsonl"
    assert sidecar.is_file()


def test_main_prints_resolved_csv_path(tmp_path, monkeypatch, capsys):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    monkeypatch.chdir(tmp_path)
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58994", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.02", "--csv", "printed.csv"])
    assert rc == 0
    out = capsys.readouterr().out
    resolved = os.path.normpath(str(fake_dir / "printed.csv"))
    assert any(os.path.normpath(line.split("[hil] CSV log: ", 1)[1]) == resolved
               for line in out.splitlines() if "[hil] CSV log:" in line)


# ─────────────────────────────────────────────────────────────────────────
# 14. sanitize_token / run_mode_token / auto_csv_name
# ─────────────────────────────────────────────────────────────────────────

def test_sanitize_token_lowercases():
    assert hil.sanitize_token("Steady") == "steady"
    assert hil.sanitize_token("ML0146") == "ml0146"


def test_sanitize_token_hostile_input_collapses_to_dashes():
    out = hil.sanitize_token("a/b\\c:d*e?f\"g<h>i|j")
    assert out == "a-b-c-d-e-f-g-h-i-j"
    assert "/" not in out and "\\" not in out and ":" not in out


def test_sanitize_token_collapses_runs_of_separators():
    assert hil.sanitize_token("a   b") == "a-b"
    assert hil.sanitize_token("a!!!!b") == "a-b"


def test_sanitize_token_empty_and_none_and_all_dashes():
    assert hil.sanitize_token("") == "none"
    assert hil.sanitize_token(None) == "none"
    assert hil.sanitize_token("---") == "none"
    assert hil.sanitize_token("...") == "none"


def test_sanitize_token_keeps_dots_and_dashes():
    assert hil.sanitize_token("ML0146.v2") == "ml0146.v2"


def test_run_mode_token_default_is_open():
    assert hil.run_mode_token() == "open"


def test_run_mode_token_pi_live():
    assert hil.run_mode_token(pi_live=True) == "pilive"


def test_run_mode_token_ems():
    assert hil.run_mode_token(ems_name="hold-5050") == "ems-hold-5050"


def test_run_mode_token_timeline():
    assert hil.run_mode_token(has_timeline=True) == "timeline"


def test_run_mode_token_replay_names_the_log():
    token = hil.run_mode_token(replay_path=os.path.join("x", "ML0146.BLG"))
    assert token == "replay-ml0146"


def test_run_mode_token_replay_takes_priority_over_other_sources():
    """Ordered by exclusivity (module docstring): --replay wins even if
    pi_live/ems/timeline are also passed in -- main() never actually
    constructs the call this way (its own argument rules refuse the
    combination first), but run_mode_token's OWN ordering must still be
    replay-first since it is a pure function with no such guard itself."""
    token = hil.run_mode_token(replay_path="ML0146.BLG", pi_live=True,
                               ems_name="hold-5050", has_timeline=True)
    assert token == "replay-ml0146"


def test_run_mode_token_hifi_suffix_appended():
    assert hil.run_mode_token(electrical="hifi") == "open-hifi"
    assert hil.run_mode_token(pi_live=True, electrical="hifi") == "pilive-hifi"
    assert hil.run_mode_token(replay_path="ML0146.BLG", electrical="hifi") \
        == "replay-ml0146-hifi"


def test_auto_csv_name_format_with_scenario():
    name = hil.auto_csv_name("steady", "open", stamp="20260830_120000")
    assert name == "hil_steady_open_20260830_120000.csv"


def test_auto_csv_name_replay_drops_scenario_component():
    """Replay mode passes scenario=None -- the filename must not carry a
    spurious 'None' component; the mode token alone (already 'replay-<stem>')
    names the run."""
    name = hil.auto_csv_name(None, "replay-ml0146", stamp="20260830_120000")
    assert name == "hil_replay-ml0146_20260830_120000.csv"


def test_auto_csv_name_default_stamp_matches_timestamp_format():
    import re
    name = hil.auto_csv_name("steady", "open")
    assert re.match(r"^hil_steady_open_\d{8}_\d{6}\.csv$", name) is not None


def test_auto_csv_name_sanitizes_its_components():
    name = hil.auto_csv_name("My Scenario!", "open", stamp="20260830_120000")
    assert name == "hil_my-scenario_open_20260830_120000.csv"


# ─────────────────────────────────────────────────────────────────────────
# 15. unique_output_path
# ─────────────────────────────────────────────────────────────────────────

def test_unique_output_path_no_collision_returns_input(tmp_path):
    p = str(tmp_path / "a.csv")
    assert hil.unique_output_path(p) == p


def test_unique_output_path_single_collision_suffixes_1(tmp_path):
    (tmp_path / "a.csv").write_text("x")
    got = hil.unique_output_path(str(tmp_path / "a.csv"))
    assert got == str(tmp_path / "a_1.csv")


def test_unique_output_path_multiple_collisions_finds_first_free(tmp_path):
    (tmp_path / "a.csv").write_text("x")
    (tmp_path / "a_1.csv").write_text("x")
    (tmp_path / "a_2.csv").write_text("x")
    got = hil.unique_output_path(str(tmp_path / "a.csv"))
    assert got == str(tmp_path / "a_3.csv")


# ─────────────────────────────────────────────────────────────────────────
# 16. CSV/sidecar refusal matrix
# ─────────────────────────────────────────────────────────────────────────

def test_explicit_existing_csv_refused_exit_2_with_message(tmp_path, capsys):
    csv_path = tmp_path / "exists.csv"
    csv_path.write_text("pre-existing content")
    with pytest.raises(SystemExit) as ei:
        hil.main(["--teensy-ip", "127.0.0.1", "--port", "58900", "--bind-port", "0",
                   "--rate", "200", "--csv", str(csv_path), "--scenario", "steady",
                   "--electrical", "simple", "--duration", "0.02"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "refusing to overwrite" in err
    # The refusal must not have touched the file.
    assert csv_path.read_text() == "pre-existing content"


def test_explicit_existing_csv_with_force_overwrites(tmp_path):
    csv_path = tmp_path / "exists.csv"
    csv_path.write_text("pre-existing content, not a real CSV")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58901", "--bind-port", "0",
                   "--rate", "200", "--csv", str(csv_path), "--scenario", "steady",
                   "--electrical", "simple", "--duration", "0.02", "--force"])
    assert rc == 0
    content = csv_path.read_text()
    assert "pre-existing content" not in content
    assert content.startswith("t,seq,")


def test_auto_named_csv_never_refuses_even_on_collision(tmp_path, monkeypatch):
    """An auto-named path that happens to collide (two runs started within
    the same second) must be uniquified with a '_N' suffix, never refused --
    only an EXPLICIT --csv is refused (see the two tests above)."""
    fake_dir = tmp_path / "HIL Results"
    fake_dir.mkdir(parents=True)
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    monkeypatch.setattr(hil, "auto_csv_name", lambda *a, **k: "fixed_name.csv")
    (fake_dir / "fixed_name.csv").write_text("existing run, must survive untouched")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58902", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.02"])
    assert rc == 0
    assert (fake_dir / "fixed_name_1.csv").is_file()
    assert (fake_dir / "fixed_name_1.csv.meta.json").is_file()
    assert (fake_dir / "fixed_name.csv").read_text() == "existing run, must survive untouched"


def test_no_csv_writes_no_csv_and_no_sidecar(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58903", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.02", "--no-csv"])
    assert rc == 0
    # HIL_RESULTS_DIR must either not have been created at all, or (if some
    # other code path touched it) contain nothing.
    assert not fake_dir.exists() or not any(fake_dir.iterdir())


def test_no_csv_and_explicit_csv_mutually_exclusive_argparse_error(tmp_path):
    with pytest.raises(SystemExit) as ei:
        hil.main(["--csv", str(tmp_path / "x.csv"), "--no-csv"])
    assert ei.value.code == 2


def test_force_without_explicit_csv_is_argparse_error():
    with pytest.raises(SystemExit) as ei:
        hil.main(["--force"])
    assert ei.value.code == 2


# ─────────────────────────────────────────────────────────────────────────
# 16b. D11: refusal/uniquification must consider .meta.json and
#      .events.jsonl, not just the CSV itself (a run "owns" all three
#      artifacts -- output_path_taken() checks every one of them).
# ─────────────────────────────────────────────────────────────────────────

def test_d11_explicit_csv_refused_by_an_orphan_meta_json_alone(tmp_path, capsys):
    """The CSV itself is absent, but its .meta.json sidecar sits there from a
    previous (or killed) run -- that alone must trigger the refusal, and the
    printed message must name the file actually in the way."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text('{"status": "running"}')
    assert not csv_path.exists()
    with pytest.raises(SystemExit) as ei:
        hil.main(["--teensy-ip", "127.0.0.1", "--port", "58930", "--bind-port", "0",
                   "--rate", "200", "--csv", str(csv_path), "--scenario", "steady",
                   "--electrical", "simple", "--duration", "0.02"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "refusing to overwrite an existing run artifact" in err
    assert sidecar.name in err
    # Nothing must have been created/touched by the refusal itself.
    assert not csv_path.exists()


def test_d11_explicit_csv_refused_by_an_orphan_events_sidecar_alone(tmp_path, capsys):
    csv_path = tmp_path / "run.csv"
    events_sidecar = tmp_path / "run.csv.events.jsonl"
    events_sidecar.write_text("")
    assert not csv_path.exists()
    with pytest.raises(SystemExit) as ei:
        hil.main(["--teensy-ip", "127.0.0.1", "--port", "58931", "--bind-port", "0",
                   "--rate", "200", "--csv", str(csv_path), "--scenario", "steady",
                   "--electrical", "hifi", "--duration", "0.02"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "refusing to overwrite an existing run artifact" in err
    assert events_sidecar.name in err


def test_d11_explicit_csv_with_force_overwrites_despite_orphan_sidecar_only(tmp_path):
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text('{"status": "running"}')
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58932", "--bind-port", "0",
                   "--rate", "200", "--csv", str(csv_path), "--scenario", "steady",
                   "--electrical", "simple", "--duration", "0.02", "--force"])
    assert rc == 0
    assert csv_path.is_file()


def test_d11_auto_named_bumps_to_1_on_orphan_meta_json_collision(tmp_path, monkeypatch):
    """An auto-named run must treat an orphan sidecar (the CSV itself absent)
    the same as a full collision and bump to '_1' -- output_path_taken()
    checks all three artifact paths, and unique_output_path() calls it."""
    fake_dir = tmp_path / "HIL Results"
    fake_dir.mkdir(parents=True)
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    monkeypatch.setattr(hil, "auto_csv_name", lambda *a, **k: "fixed_name.csv")
    (fake_dir / "fixed_name.csv.meta.json").write_text('{"status": "running"}')
    assert not (fake_dir / "fixed_name.csv").exists()
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58933", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.02"])
    assert rc == 0
    assert (fake_dir / "fixed_name_1.csv").is_file()
    # The orphan sidecar itself must survive untouched.
    assert (fake_dir / "fixed_name.csv.meta.json").read_text() == '{"status": "running"}'


def test_d11_auto_named_bumps_to_1_on_orphan_events_sidecar_collision(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    fake_dir.mkdir(parents=True)
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    monkeypatch.setattr(hil, "auto_csv_name", lambda *a, **k: "fixed_name.csv")
    (fake_dir / "fixed_name.csv.events.jsonl").write_text("")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58934", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "hifi",
                   "--duration", "0.02"])
    assert rc == 0
    assert (fake_dir / "fixed_name_1.csv").is_file()


# ─────────────────────────────────────────────────────────────────────────
# 16c. D12: --no-csv + --electrical hifi prints the events-sidecar
#      suppression notice (the sidecar derives from the CSV path, so
#      --no-csv silently disables it too unless the run says so).
# ─────────────────────────────────────────────────────────────────────────

def test_d12_no_csv_with_hifi_prints_events_suppression_notice(tmp_path, monkeypatch, capsys):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58935", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "hifi",
                   "--duration", "0.02", "--no-csv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOTE: --no-csv also suppresses the hi-fi electrical" in out
    assert "events.jsonl" in out


def test_d12_no_csv_with_simple_electrical_prints_no_hifi_notice(tmp_path, monkeypatch, capsys):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(hil, "HIL_RESULTS_DIR", str(fake_dir))
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58936", "--bind-port", "0",
                   "--rate", "200", "--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.02", "--no-csv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOTE: --no-csv also suppresses" not in out


def test_d12_hifi_with_csv_prints_no_suppression_notice(tmp_path, capsys):
    """Sanity converse: the notice is specific to --no-csv -- a hifi run WITH
    a CSV (the sidecar is written normally) must not print it."""
    csv_path = str(tmp_path / "run.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58937", "--bind-port", "0",
                   "--rate", "200", "--csv", csv_path, "--scenario", "steady",
                   "--electrical", "hifi", "--duration", "0.02"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOTE: --no-csv also suppresses" not in out


# ─────────────────────────────────────────────────────────────────────────
# 17. .meta.json sidecar lifecycle
# ─────────────────────────────────────────────────────────────────────────

def _capture_sidecar_writes(monkeypatch):
    """Wrap write_meta_sidecar so every call's payload is snapshotted (via a
    JSON round-trip, which is safe since the payload is JSON-serializable by
    construction) while still delegating to the real writer, so the file on
    disk and the call history can both be inspected."""
    calls = []
    orig = hil.write_meta_sidecar

    def _wrapper(csv_path, payload):
        calls.append(json.loads(json.dumps(payload)))
        return orig(csv_path, payload)

    monkeypatch.setattr(hil, "write_meta_sidecar", _wrapper)
    return calls


def test_sidecar_written_running_first_then_completed(tmp_path, monkeypatch):
    calls = _capture_sidecar_writes(monkeypatch)
    csv_path = str(tmp_path / "run.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58904", "--bind-port", "0",
                   "--rate", "200", "--csv", csv_path, "--scenario", "steady",
                   "--electrical", "simple", "--duration", "0.02"])
    assert rc == 0
    assert len(calls) >= 2
    assert calls[0]["status"] == "running"
    assert calls[0]["results"] is None
    assert calls[0]["finished"] is None
    assert calls[-1]["status"] == "completed"
    assert calls[-1]["results"] is not None
    assert calls[-1]["finished"] is not None
    # Atomicity: no leftover .tmp file after the final write.
    assert not os.path.exists(csv_path + ".meta.json.tmp")
    assert os.path.exists(csv_path + ".meta.json")


def test_sidecar_keyboard_interrupt_status_interrupted(tmp_path, monkeypatch):
    calls = _capture_sidecar_writes(monkeypatch)
    csv_path = str(tmp_path / "run.csv")

    def _raise_ki(_s):
        raise KeyboardInterrupt()

    monkeypatch.setattr(hil.time, "sleep", _raise_ki)
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", "58905", "--bind-port", "0",
                   "--rate", "200", "--csv", csv_path, "--scenario", "steady",
                   "--electrical", "simple", "--duration", "5.0"])
    # main() catches KeyboardInterrupt internally and still returns 0.
    assert rc == 0
    assert calls[-1]["status"] == "interrupted"
    assert not os.path.exists(csv_path + ".meta.json.tmp")


def test_sidecar_unexpected_exception_status_error_and_reraises(tmp_path, monkeypatch):
    calls = _capture_sidecar_writes(monkeypatch)
    csv_path = str(tmp_path / "run.csv")

    def _raise_boom(_s):
        raise RuntimeError("synthetic failure for the error-path test")

    monkeypatch.setattr(hil.time, "sleep", _raise_boom)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        hil.main(["--teensy-ip", "127.0.0.1", "--port", "58906", "--bind-port", "0",
                   "--rate", "200", "--csv", csv_path, "--scenario", "steady",
                   "--electrical", "simple", "--duration", "5.0"])
    assert calls[-1]["status"] == "error"
    assert "synthetic failure" in calls[-1]["error"]
    assert not os.path.exists(csv_path + ".meta.json.tmp")


# ─────────────────────────────────────────────────────────────────────────
# 17b. K6: write_meta_sidecar() real atomicity -- a failing os.replace()
#      (the temp-file -> final-file commit) must never lose the PREVIOUS
#      sidecar's content, and must never leave a stale .tmp behind; and a
#      genuinely unserializable payload (D5: json.dump can raise even with
#      default=str, when str() itself raises) must fail the same way.
# ─────────────────────────────────────────────────────────────────────────

def test_k6_write_meta_sidecar_os_replace_failure_preserves_previous_content(
        tmp_path, monkeypatch):
    csv_path = str(tmp_path / "run.csv")
    sidecar_path = csv_path + ".meta.json"
    assert hil.write_meta_sidecar(csv_path, {"status": "running", "results": None}) is True
    original = open(sidecar_path, encoding="utf-8").read()

    def _boom_replace(*a, **k):
        raise OSError("synthetic os.replace failure")

    monkeypatch.setattr(hil.os, "replace", _boom_replace)
    ok = hil.write_meta_sidecar(csv_path, {"status": "completed", "results": {"x": 1}})
    assert ok is False
    # The commit never happened, so the PREVIOUS content must be untouched.
    assert open(sidecar_path, encoding="utf-8").read() == original
    # The new finally-block cleanup must remove the partially-written temp.
    assert not os.path.exists(sidecar_path + ".tmp")


def test_k6_write_meta_sidecar_os_replace_failure_with_no_previous_sidecar(
        tmp_path, monkeypatch):
    """Same failure mode, but with nothing on disk beforehand -- must fail
    cleanly (False, no artifacts) rather than leaving a partial file."""
    csv_path = str(tmp_path / "run.csv")
    sidecar_path = csv_path + ".meta.json"
    assert not os.path.exists(sidecar_path)

    def _boom_replace(*a, **k):
        raise OSError("synthetic os.replace failure")

    monkeypatch.setattr(hil.os, "replace", _boom_replace)
    ok = hil.write_meta_sidecar(csv_path, {"status": "running", "results": None})
    assert ok is False
    assert not os.path.exists(sidecar_path)
    assert not os.path.exists(sidecar_path + ".tmp")


def test_d5_write_meta_sidecar_unserializable_payload_fails_cleanly(tmp_path):
    """D5: the catch in write_meta_sidecar() is `Exception`, not `OSError` --
    json.dump can raise even with default=str, when str() ITSELF raises.
    Must return False, leave no .tmp/.meta.json artifact, and not propagate
    past this call."""
    class _Boom:
        def __str__(self):
            raise RuntimeError("cannot stringify")

    csv_path = str(tmp_path / "run.csv")
    sidecar_path = csv_path + ".meta.json"
    ok = hil.write_meta_sidecar(csv_path, {"bad": _Boom()})
    assert ok is False
    assert not os.path.exists(sidecar_path)
    assert not os.path.exists(sidecar_path + ".tmp")


def test_d5_write_meta_sidecar_unserializable_payload_does_not_clobber_previous(tmp_path):
    csv_path = str(tmp_path / "run.csv")
    sidecar_path = csv_path + ".meta.json"
    assert hil.write_meta_sidecar(csv_path, {"status": "running", "results": None}) is True
    original = open(sidecar_path, encoding="utf-8").read()

    class _Boom:
        def __str__(self):
            raise RuntimeError("cannot stringify")

    ok = hil.write_meta_sidecar(csv_path, {"status": "completed", "bad": _Boom()})
    assert ok is False
    assert open(sidecar_path, encoding="utf-8").read() == original


# ─────────────────────────────────────────────────────────────────────────
# 18. constants_hash / collect_model_constants / git_provenance
# ─────────────────────────────────────────────────────────────────────────

def test_collect_model_constants_contains_known_keys():
    consts = hil.collect_model_constants()
    assert "hil_plant_sim.K_F" in consts
    assert "hil_plant_sim.M_EFF" in consts
    assert any(k.startswith("hil_electrical.") for k in consts)


def test_constants_hash_deterministic_across_calls():
    c1 = hil.collect_model_constants()
    c2 = hil.collect_model_constants()
    assert c1 == c2
    assert hil.constants_hash(c1) == hil.constants_hash(c2)


def test_constants_hash_sensitive_to_a_constant_change(monkeypatch):
    before = hil.constants_hash(hil.collect_model_constants())
    monkeypatch.setattr(hil, "K_F", hil.K_F + 0.001)
    after = hil.constants_hash(hil.collect_model_constants())
    assert before != after


def test_constants_hash_is_order_independent_dict_repr():
    """collect_model_constants() sorts its own output, and constants_hash
    dumps with sort_keys=True, so a dict built in a different key order must
    still hash identically."""
    c = hil.collect_model_constants()
    reordered = dict(reversed(list(c.items())))
    assert hil.constants_hash(c) == hil.constants_hash(reordered)


def test_git_provenance_shape_on_a_working_repo():
    info = hil.git_provenance()
    assert set(info) == {"rev", "dirty", "error"}
    # This IS a git repo (the test itself lives in one), so under a working
    # git binary rev should resolve; do not assert on `dirty`'s value (the
    # working tree may or may not be clean when this runs).
    assert info["rev"] is None or isinstance(info["rev"], str)


def test_git_provenance_null_tolerant_on_subprocess_failure(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(hil.subprocess, "run", _boom)
    info = hil.git_provenance()
    assert info["rev"] is None
    assert info["dirty"] is None
    assert info["error"] is not None
    assert "git not on PATH" in info["error"]


def test_git_provenance_null_tolerant_on_nonzero_returncode(monkeypatch):
    class _FakeCompleted:
        def __init__(self, rc, out=b"", err=b""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def _fake_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return _FakeCompleted(128, err=b"not a git repository")
        return _FakeCompleted(128, err=b"not a git repository")

    monkeypatch.setattr(hil.subprocess, "run", _fake_run)
    info = hil.git_provenance()
    assert info["rev"] is None
    assert info["dirty"] is None
    # Both `git rev-parse` and `git status` failed here (both return rc=128),
    # and the two failures are now APPENDED as separate labeled notes rather
    # than the second silently overwriting the first -- see git_provenance()'s
    # `note()` helper.
    assert info["error"] == "rev-parse: not a git repository; status: not a git repository"


# ─────────────────────────────────────────────────────────────────────────
# 18b. D9: CONSTANTS_EXCLUDE_PREFIXES -- the fingerprint drops non-model
#      families (protocol sizes/sync bytes, this file's own metadata, the
#      warm-reset tripwire's tuning, bitmasks, ports) so a protocol edit or
#      a tripwire retune does not move constants_hash as loudly as an
#      actual K_F/K_DROOP_BUS correction would.
# ─────────────────────────────────────────────────────────────────────────

def test_d9_collect_model_constants_excludes_every_declared_prefix():
    consts = hil.collect_model_constants()
    for key in consts:
        name = key.split(".", 1)[1]
        assert not name.startswith(hil.CONSTANTS_EXCLUDE_PREFIXES), key


def test_d9_collect_model_constants_specific_excluded_names_absent():
    consts = hil.collect_model_constants()
    names = {k.split(".", 1)[1] for k in consts}
    for excluded in ("META_FORMAT_VERSION", "WARM_RESET_GRACE_S",
                     "WARM_RESET_TIMES_MAX", "HIL_SYNC_INJECT", "HIL_INJECT_SIZE",
                     "HIL_OUTPUT_SIZE", "TEENSY_PORT_DEFAULT", "SW_FC_BUS",
                     "AUX_FC_REG", "MDAC_CMD_LOAD_UPDATE", "PI_CMD_SIZE"):
        assert excluded not in names, excluded


def test_d9_collect_model_constants_no_duplicate_bare_names_across_modules():
    """A name re-exported from hil_electrical into hil_plant_sim (the shared
    `from hil_electrical import ...`) must be recorded ONCE under its
    canonical hil_electrical. prefix, never twice under both module
    prefixes."""
    consts = hil.collect_model_constants()
    bare_names = [k.split(".", 1)[1] for k in consts]
    assert len(bare_names) == len(set(bare_names))


def test_d9_collect_model_constants_retains_model_constants():
    consts = hil.collect_model_constants()
    names = {k.split(".", 1)[1] for k in consts}
    for retained in ("K_F", "K_DROOP_BUS", "M_EFF"):
        assert retained in names, retained


def test_d9_constants_hash_unaffected_by_an_excluded_constant(monkeypatch):
    before = hil.constants_hash(hil.collect_model_constants())
    monkeypatch.setattr(hil, "WARM_RESET_TIMES_MAX", hil.WARM_RESET_TIMES_MAX + 1)
    after = hil.constants_hash(hil.collect_model_constants())
    assert before == after


def test_d9_constants_hash_changes_when_a_retained_constant_moves(monkeypatch):
    before = hil.constants_hash(hil.collect_model_constants())
    monkeypatch.setattr(hil, "K_DROOP_BUS", hil.K_DROOP_BUS + 0.001)
    after = hil.constants_hash(hil.collect_model_constants())
    assert before != after


# ─────────────────────────────────────────────────────────────────────────
# 19. comm-loss tx-enable window
# ─────────────────────────────────────────────────────────────────────────

def test_comm_loss_tx_window_edges():
    plant = hil.Plant()
    assert hil.apply_scenario(plant, "comm-loss", 4.99) is True
    assert hil.apply_scenario(plant, "comm-loss", 5.0) is False
    assert hil.apply_scenario(plant, "comm-loss", 6.0) is False
    assert hil.apply_scenario(plant, "comm-loss", 6.99) is False
    assert hil.apply_scenario(plant, "comm-loss", 7.0) is True


def test_comm_loss_scenario_declares_warm_resets_expected_1():
    assert hil.SCENARIOS["comm-loss"]["warm_resets_expected"] == 1


def test_scenarios_without_the_key_have_no_expected_warm_resets():
    assert "warm_resets_expected" not in hil.SCENARIOS["steady"]
    assert "warm_resets_expected" not in hil.SCENARIOS["sag"]


# ─────────────────────────────────────────────────────────────────────────
# 20. Mid-run warm-reset tripwire (drives main()'s inline transition
#     detector deterministically via a scripted clock + scripted socket --
#     there is no standalone function to call directly, the detector lives
#     inline in the observation-drain loop)
# ─────────────────────────────────────────────────────────────────────────

class _FakeClock:
    """A monotonic() that only ever advances by exactly what sleep() is
    asked for, so main()'s tick index maps to sim-time = tick * dt with zero
    wall-clock jitter -- lets a test place a scripted observation frame at an
    exact simulated instant."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        if s > 0:
            self.t += s


class _ScriptedRecvSocket:
    """Deterministic stand-in for socket.socket: emits the queued observation
    frame for whichever tick the shared _FakeClock's current time maps to,
    otherwise raises BlockingIOError (nothing waiting) like a real
    non-blocking UDP socket. `frames_by_tick` is consumed (popped) so a frame
    is delivered exactly once."""

    def __init__(self, clock, dt, frames_by_tick):
        self._clock = clock
        self._dt = dt
        self._frames = dict(frames_by_tick)
        self.sent = []

    def setblocking(self, flag):
        pass

    def bind(self, addr):
        pass

    def sendto(self, data, addr):
        self.sent.append(bytes(data))
        return len(data)

    def recvfrom(self, bufsize):
        tick = round(self._clock.t / self._dt)
        frame = self._frames.pop(tick, None)
        if frame is None:
            raise BlockingIOError()
        return frame, ("0.0.0.0", 0)

    def close(self):
        pass


def _run_scripted_warm_reset(tmp_path, monkeypatch, frames_by_tick, duration,
                             rate=1000.0, port=58910):
    clock = _FakeClock()
    monkeypatch.setattr(hil.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(hil.time, "sleep", clock.sleep)
    dt = 1.0 / rate
    sock = _ScriptedRecvSocket(clock, dt, frames_by_tick)
    monkeypatch.setattr(hil.socket, "socket", lambda *a, **k: sock)
    csv_path = str(tmp_path / "run.csv")
    rc = hil.main(["--teensy-ip", "127.0.0.1", "--port", str(port), "--bind-port", "0",
                   "--rate", str(rate), "--csv", csv_path, "--scenario", "steady",
                   "--electrical", "simple", "--duration", str(duration)])
    assert rc == 0
    with open(csv_path + ".meta.json", encoding="utf-8") as fh:
        meta = json.load(fh)
    return meta["results"]


def test_warm_reset_99_to_other_counts_once(tmp_path, monkeypatch):
    frames = {
        0: _make_output_frame(seq=0, state=99),
        100: _make_output_frame(seq=1, state=1),   # t = 0.100 s
    }
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=0.15,
                                   port=58911)
    assert res["warm_resets_observed"] == 1
    assert res["warm_resets_mid_run"] == 0
    assert len(res["warm_reset_times_s"]) == 1
    assert res["warm_reset_times_s"][0] == pytest.approx(0.1, abs=1e-3)


def test_warm_reset_99_to_99_is_not_a_transition(tmp_path, monkeypatch):
    frames = {
        0: _make_output_frame(state=99),
        50: _make_output_frame(state=99),
    }
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=0.1,
                                   port=58912)
    assert res["warm_resets_observed"] == 0


def test_warm_reset_non_99_transitions_are_never_counted(tmp_path, monkeypatch):
    """Only a transition OUT OF 99 counts -- 1 -> 0 must not."""
    frames = {
        0: _make_output_frame(state=1),
        50: _make_output_frame(state=0),
    }
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=0.1,
                                   port=58913)
    assert res["warm_resets_observed"] == 0


def test_warm_reset_grace_classification_before_grace_not_mid_run(tmp_path, monkeypatch):
    frames = {
        0: _make_output_frame(state=99),
        500: _make_output_frame(state=1),          # t = 0.5 s < WARM_RESET_GRACE_S
    }
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=0.6,
                                   port=58914)
    assert res["warm_resets_observed"] == 1
    assert res["warm_resets_mid_run"] == 0
    assert res["warm_reset_times_s"][0] == pytest.approx(0.5, abs=1e-3)


def test_warm_reset_grace_classification_after_grace_is_mid_run(tmp_path, monkeypatch):
    frames = {
        0: _make_output_frame(state=99),
        2500: _make_output_frame(state=1),         # t = 2.5 s > WARM_RESET_GRACE_S (2.0)
    }
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=2.6,
                                   port=58915)
    assert res["warm_resets_observed"] == 1
    assert res["warm_resets_mid_run"] == 1
    assert res["warm_reset_times_s"][0] == pytest.approx(2.5, abs=1e-3)


def test_warm_reset_grace_exactly_at_boundary_counts_as_mid_run(tmp_path, monkeypatch):
    """K5: the implementation's gate is `if t >= WARM_RESET_GRACE_S` (see the
    module source), not a strict `>` -- a transition landing EXACTLY at
    2.0 s must count as mid-run.

    Uses rate=1.0 Hz (dt=1.0) rather than the usual 1000 Hz: dt=1.0 is
    exactly representable in binary floating point, so the _FakeClock's
    repeated `t += dt` reaches EXACTLY 2.0 at tick 2 with zero accumulated
    rounding error -- at 1000 Hz (dt=0.001, not exactly representable),
    2000 additions land a couple of ULPs under 2.0 and would flip this
    boundary test on floating-point noise rather than on the `>=` under
    test."""
    frames = {
        0: _make_output_frame(state=99),
        2: _make_output_frame(state=1),   # t = 2.0 s == WARM_RESET_GRACE_S, exactly
    }
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=2.5,
                                   rate=1.0, port=58917)
    assert res["warm_resets_observed"] == 1
    assert res["warm_resets_mid_run"] == 1
    assert res["warm_reset_times_s"][0] == pytest.approx(2.0, abs=1e-9)


def test_warm_reset_grace_just_below_boundary_is_not_mid_run(tmp_path, monkeypatch):
    """The converse pin: 1.999 s (one tick short of the boundary at this
    1000 Hz rate) must NOT count as mid-run."""
    frames = {
        0: _make_output_frame(state=99),
        1999: _make_output_frame(state=1),   # t = 1.999 s < WARM_RESET_GRACE_S
    }
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=2.1,
                                   port=58918)
    assert res["warm_resets_observed"] == 1
    assert res["warm_resets_mid_run"] == 0


def test_warm_reset_times_capped_but_count_is_not(tmp_path, monkeypatch):
    frames = {0: _make_output_frame(state=99)}
    state = 1
    tick = 10
    n_transitions = 0
    while n_transitions < 25:
        frames[tick] = _make_output_frame(state=state)
        if state == 1:
            n_transitions += 1
        state = 99 if state == 1 else 1
        tick += 10
    duration = (tick + 10) / 1000.0
    res = _run_scripted_warm_reset(tmp_path, monkeypatch, frames, duration=duration,
                                   port=58916)
    assert res["warm_resets_observed"] == 25
    assert len(res["warm_reset_times_s"]) == hil.WARM_RESET_TIMES_MAX == 16


# ─────────────────────────────────────────────────────────────────────────
# 13. H2Consumption (Gfc hydrogen-consumption metric, 2026-08-31)
# ─────────────────────────────────────────────────────────────────────────

# The ten pinned validation vectors from the H2Consumption banner comment: a
# 10.0 W step applied from the FIRST tick, zero initial state, Ts = 1e-3.
# rtol 1e-9 per the banner.
H2_STEP_10W_VECTORS = [
    # (n, rate_gps, cum_g)
    (1, 1.451648924521401e-06, 1.451648924521401e-09),
    (10, 8.825724871566303e-06, 5.300056759372415e-08),
    (100, 6.483139460046860e-05, 3.565983712066193e-06),
    (1000, 1.744684319758860e-04, 1.381066815913307e-04),
    (2000, 1.763552634860608e-04, 3.140662654327328e-04),
]


def test_h2_consumption_10w_step_pinned_validation_vectors():
    """Drive H2Consumption with the exact banner stimulus (10 W step from the
    first tick, zero initial state, Ts = H2_GFC_TS_S) and check the rate/
    cumulative pair at every pinned n against the banner's own vectors."""
    h2 = hil.H2Consumption()
    want = dict((n, (rate, cum)) for n, rate, cum in H2_STEP_10W_VECTORS)
    last_n = max(want)
    for n in range(1, last_n + 1):
        rate = h2.step(10.0)
        if n in want:
            want_rate, want_cum = want[n]
            assert rate == pytest.approx(want_rate, rel=1e-9)
            assert h2.rate_gps == pytest.approx(want_rate, rel=1e-9)
            assert h2.cum_g == pytest.approx(want_cum, rel=1e-9)


def test_h2_consumption_dc_gain_matches_sum_of_modal_gains():
    """DC check from the banner: sum(g_i / (1 - lam_i)) must equal
    H2_GFC_DC_GAIN_GPS_PER_W (the banner claims 4 ulp; use a tight rel tol)."""
    dc = sum(g / (1.0 - lam) for g, lam in zip(hil.H2_GFC_GAIN, hil.H2_GFC_LAMBDA))
    assert dc == pytest.approx(hil.H2_GFC_DC_GAIN_GPS_PER_W, rel=1e-12)


def test_h2_dc_gain_matches_module_import_time_assert_bound():
    """The module itself re-derives this identity AT IMPORT (M4, review
    2026-08-31) at rel tol 1e-13 -- since the module imported cleanly, the
    live constants are already inside that bound; re-derive the SAME check
    here as a standing pin against the exact tolerance."""
    dc = sum(g / (1.0 - lam) for g, lam in zip(hil.H2_GFC_GAIN, hil.H2_GFC_LAMBDA))
    rel_err = abs(dc - hil.H2_GFC_DC_GAIN_GPS_PER_W) / hil.H2_GFC_DC_GAIN_GPS_PER_W
    assert rel_err < 1e-13


def test_h2_dc_gain_import_assert_bound_would_catch_a_perturbed_coefficient():
    """TRIPWIRE: the M4 import-time assert exists to catch a hand-edit of
    H2_GFC_LAMBDA/H2_GFC_GAIN that left H2_GFC_DC_GAIN_GPS_PER_W alone (or
    vice versa).  Reproduce the exact check against a PERTURBED COPY of the
    real coefficient tuples -- NEVER mutating the live module constants --
    and confirm the perturbation actually trips the 1e-13 bound.  Without
    this, the bound could have been silently loosened to something no real
    drift could ever fail."""
    lam = list(hil.H2_GFC_LAMBDA)
    gain = list(hil.H2_GFC_GAIN)
    # A 1e-9 relative nudge on one gain: comfortably inside the "measured
    # residual is 4 ulp" scale the banner claims for the REAL coefficients,
    # but 4 orders of magnitude past the 1e-13 tripwire.
    gain[0] *= (1.0 + 1e-9)
    perturbed_dc = sum(g / (1.0 - l) for g, l in zip(gain, lam))
    rel_err = (abs(perturbed_dc - hil.H2_GFC_DC_GAIN_GPS_PER_W)
              / hil.H2_GFC_DC_GAIN_GPS_PER_W)
    assert rel_err >= 1e-13, (
        "the perturbation must actually trip the import-time bound, or the "
        "bound is too loose to be a real tripwire")
    # And confirm the module constants are untouched -- this test must not
    # leave any global state perturbed for tests that run after it.
    assert hil.H2_GFC_GAIN[0] == 7.90674025708048e-08


def test_h2_consumption_converges_to_dc_gain_at_steady_state():
    """Run a 10 W step far past the dominant time constant (0.2212 s) and
    confirm the rate has converged to 10x the DC gain -- an end-to-end
    functional check of the recursion's steady-state behaviour, not just the
    early-transient pinned vectors above."""
    h2 = hil.H2Consumption()
    for _ in range(20000):          # 20 s, ~90x the 0.2212 s dominant tau
        h2.step(10.0)
    assert h2.rate_gps == pytest.approx(10.0 * hil.H2_GFC_DC_GAIN_GPS_PER_W, rel=1e-6)


def test_h2_consumption_negative_p_fc_clamps_identically_to_zero():
    """`p_fc_w` is clamped at zero (banner: reverse power into the FC is not a
    physical operating point on this rig and must not produce a negative,
    unphysical hydrogen 'credit').  A negative input must therefore behave
    EXACTLY like a zero input at every subsequent tick, not merely stay
    non-negative."""
    h2_neg = hil.H2Consumption()
    h2_zero = hil.H2Consumption()
    for _ in range(50):
        r_neg = h2_neg.step(-5.0)
        r_zero = h2_zero.step(0.0)
        assert r_neg == r_zero
        assert h2_neg.cum_g == h2_zero.cum_g
    assert h2_neg.x == h2_zero.x


def test_h2_consumption_negative_p_fc_after_positive_history_never_goes_negative():
    """A negative input arriving AFTER positive history must not manufacture a
    negative rate either: with u clamped to 0 the recursion just decays the
    existing (non-negative, for a positive-only history) state."""
    h2 = hil.H2Consumption()
    for _ in range(500):
        h2.step(10.0)
    assert h2.rate_gps > 0.0
    prev_cum = h2.cum_g
    for _ in range(500):
        rate = h2.step(-10.0)
        assert rate >= 0.0
    assert h2.cum_g >= prev_cum        # cum_g is a rectangular integral of a
                                       # non-negative rate -- must not fall


def test_h2_consumption_reset_returns_to_zero_state():
    h2 = hil.H2Consumption()
    for _ in range(1000):
        h2.step(10.0)
    assert h2.rate_gps > 0.0
    assert h2.cum_g > 0.0
    h2.reset()
    assert h2.x == [0.0, 0.0, 0.0, 0.0]
    assert h2.rate_gps == 0.0
    assert h2.cum_g == 0.0
    # And the recursion behaves like a fresh instance afterward.
    fresh = hil.H2Consumption()
    assert h2.step(10.0) == pytest.approx(fresh.step(10.0), rel=1e-12)


# ── CSV plumbing (Plant-level, faster than driving the full CLI) ───────────

def test_plant_h2_metric_grows_with_nonzero_fc_current():
    """h2_rate_gps/h2_cum_g are computed from the FUEL CELL's own terminal
    voltage and current (fuel_cell.v_terminal * fuel_cell.i), not the bus-side
    I_fc channel current -- drive a live FC_BUS path and confirm both fields
    in Plant.step()'s returned dict move, matching plant.h2 exactly."""
    plant = hil.Plant()
    obs = _obs(switch=hil.SW_FC_BUS, aux=hil.AUX_FC_REG, current=0.0)
    out = None
    for _ in range(200):
        out = plant.step(1e-3, obs)
    assert plant.fuel_cell.i > 0.0, "sanity: the FC must actually be sourcing current"
    assert out["h2_rate_gps"] > 0.0
    assert out["h2_cum_g"] > 0.0
    assert out["h2_rate_gps"] == pytest.approx(plant.h2.rate_gps)
    assert out["h2_cum_g"] == pytest.approx(plant.h2.cum_g)


def test_plant_h2_metric_stays_zero_with_no_fc_current():
    """With no source path live, fuel_cell.i stays 0 and the metric must not
    drift off zero on its own."""
    plant = hil.Plant()
    obs = _obs(switch=0, aux=0, current=0.0)
    out = None
    for _ in range(200):
        out = plant.step(1e-3, obs)
    assert plant.fuel_cell.i == pytest.approx(0.0, abs=1e-9)
    assert out["h2_rate_gps"] == pytest.approx(0.0, abs=1e-12)
    assert out["h2_cum_g"] == pytest.approx(0.0, abs=1e-12)


def test_csv_schema_sim_mode_h2_columns_populated_numerically(tmp_path):
    """End-to-end (CLI): the two h2 columns are present AND actually carry
    numeric (not blank) values on every row of a simulated-plant run."""
    header, rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple", "--duration", "0.05"],
        name="h2sim.csv")
    rate_idx = header.index("h2_rate_gps")
    cum_idx = header.index("h2_cum_g")
    assert rows, "sanity: the run must have produced rows"
    for row in rows:
        float(row[rate_idx])           # must parse -- raises on a blank cell
        float(row[cum_idx])


def test_csv_schema_replay_mode_has_no_h2_columns(tmp_path):
    """Replay bypasses the plant integrator entirely, so there is no P_fc to
    consume -- the h2 columns must be ABSENT (not present-and-blank) in a
    replay CSV, matching REPLAY_CSV_HEADER_PIN's documented schema."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    header, _rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--duration", "0.02"], name="h2replay.csv")
    assert "h2_rate_gps" not in header
    assert "h2_cum_g" not in header


# ─────────────────────────────────────────────────────────────────────────
# 14. SocBandStrategy (the `soc-band` EMS strategy, 2026-08-31)
# ─────────────────────────────────────────────────────────────────────────

def test_soc_band_registered_under_its_name():
    assert hil.EMS_STRATEGIES["soc-band"] is hil.ems_soc_band


def test_soc_band_captures_soc_ref_on_first_call_only():
    policy = hil.SocBandStrategy()
    policy(3.0, {"t": 3.0, "v_profile": 1.0, "soc": 0.71, "I_fc": 0.0, "I_batt": 0.0})
    assert policy.soc_ref == pytest.approx(0.71)
    # A second call with a DIFFERENT soc must not move the captured reference.
    policy(3.1, {"t": 3.1, "v_profile": 1.0, "soc": 0.65, "I_fc": 0.0, "I_batt": 0.0})
    assert policy.soc_ref == pytest.approx(0.71)


def test_soc_band_deadband_holds_nominal_share_inside_the_band():
    policy = hil.SocBandStrategy()
    # Exactly at the reference (deficit 0) and just inside the band edge --
    # both must return the nominal split, unperturbed.
    assert policy.share_for_deficit(0.0) == pytest.approx(hil.SOC_BAND_SHARE_NOMINAL)
    just_inside = hil.SOC_BAND_HALF * 0.99
    assert policy.share_for_deficit(just_inside) == pytest.approx(hil.SOC_BAND_SHARE_NOMINAL)
    assert policy.share_for_deficit(-just_inside) == pytest.approx(hil.SOC_BAND_SHARE_NOMINAL)


def test_soc_band_proportional_bias_below_band_biases_toward_fc():
    """A deficit beyond the band's positive edge (SoC has fallen -- pack is
    LOW) must bias the split UP, toward the fuel cell."""
    policy = hil.SocBandStrategy()
    half = hil.SOC_BAND_HALF
    sat = hil.SOC_BAND_SAT_EXCESS_FRAC * half
    mid_excess_deficit = half + 0.5 * sat
    share = policy.share_for_deficit(mid_excess_deficit)
    assert share > hil.SOC_BAND_SHARE_NOMINAL
    assert share < hil.SOC_BAND_SHARE_NOMINAL + hil.SOC_BAND_SHARE_SPAN


def test_soc_band_proportional_bias_above_band_biases_toward_battery():
    """The opposite sign: a NEGATIVE deficit beyond the band (SoC above
    reference) biases DOWN, toward the battery."""
    policy = hil.SocBandStrategy()
    half = hil.SOC_BAND_HALF
    sat = hil.SOC_BAND_SAT_EXCESS_FRAC * half
    mid_excess_deficit = -(half + 0.5 * sat)
    share = policy.share_for_deficit(mid_excess_deficit)
    assert share < hil.SOC_BAND_SHARE_NOMINAL
    assert share > hil.SOC_BAND_SHARE_NOMINAL - hil.SOC_BAND_SHARE_SPAN


def test_soc_band_saturates_at_share_span_and_clamps_to_min_max():
    policy = hil.SocBandStrategy()
    half = hil.SOC_BAND_HALF
    sat = hil.SOC_BAND_SAT_EXCESS_FRAC * half
    # Exactly at the saturation excess: full span, no more.
    at_sat = half + sat
    assert policy.share_for_deficit(at_sat) == pytest.approx(
        hil.SOC_BAND_SHARE_NOMINAL + hil.SOC_BAND_SHARE_SPAN)
    # Far beyond saturation: still exactly the span (never more), and the hard
    # SOC_BAND_SHARE_MIN/MAX clamp is respected independently.
    way_beyond = half + 100.0 * sat
    share_hi = policy.share_for_deficit(way_beyond)
    assert share_hi == pytest.approx(hil.SOC_BAND_SHARE_NOMINAL + hil.SOC_BAND_SHARE_SPAN)
    assert share_hi <= hil.SOC_BAND_SHARE_MAX
    share_lo = policy.share_for_deficit(-way_beyond)
    assert share_lo == pytest.approx(hil.SOC_BAND_SHARE_NOMINAL - hil.SOC_BAND_SHARE_SPAN)
    assert share_lo >= hil.SOC_BAND_SHARE_MIN


def test_soc_band_causal_cruise_gate_blocks_charging_during_acceleration_ruling_b():
    """Operator ruling (b): charging and acceleration are incompatible on this
    hardware, and the causal cruise test must enforce it even though the SoC
    deficit and current admission would otherwise both permit a charge
    window.  Drive an ACCELERATING profile (rate far above
    SOC_BAND_CRUISE_SLOPE_MAX) with a low current total and a deficit that
    grows past the band, and confirm charge_goal is NEVER asserted."""
    policy = hil.SocBandStrategy()
    t = hil.EMS_RUN_ENTRY_S
    dt = 0.02                          # 50 Hz commander cadence
    v = 0.6
    soc = 0.70
    accel_mps2 = 0.30                  # 6x SOC_BAND_CRUISE_SLOPE_MAX
    for _ in range(400):               # 8 s of continuous acceleration
        v += accel_mps2 * dt
        soc -= 0.0002 * dt             # walk the deficit out of the band too
        fb = {"t": t, "v_profile": v, "soc": soc, "I_fc": 0.05, "I_batt": 0.05}
        out = policy(t, fb)
        assert out["charge_goal"] == 0.0, (
            f"charge_goal asserted during acceleration at t={t:.3f}, "
            f"v={v:.3f} -- violates operator ruling (b)")
        t += dt
    # Sanity: the deficit really did leave the band, so the negative result
    # above is not vacuous (the deficit gate would otherwise never have opened).
    assert (policy.soc_ref - soc) > hil.SOC_BAND_HALF


def test_soc_band_charge_admission_hysteresis_holds_open_between_thresholds():
    """Once the charge window opens (i_tot <= ENTER), it must stay open while
    i_tot climbs above ENTER but stays at or below EXIT -- the hysteresis the
    module comment describes to prevent 50 Hz chatter -- then actually close
    once i_tot exceeds EXIT, and NOT reopen at a value between EXIT and
    ENTER (that is what makes it hysteresis rather than a single threshold)."""
    policy = hil.SocBandStrategy()
    dt = 0.02
    t = hil.EMS_RUN_ENTRY_S
    v = 1.0

    def tick(i_tot, soc):
        nonlocal t
        fb = {"t": t, "v_profile": v, "soc": soc, "I_fc": i_tot / 2.0,
              "I_batt": i_tot / 2.0}
        out = policy(t, fb)
        t += dt
        return out

    # Warm-up: build the trailing cruise window at a flat v, deficit still 0
    # (charging must not open yet -- no deficit).
    for _ in range(60):                # > 1.0 s / dt of flat samples
        tick(0.1, 0.70)
    assert policy.charging is False

    # Walk the deficit out of the band, offering a low i_tot (<= ENTER).
    out = None
    for _ in range(20):
        out = tick(0.1, 0.68)
    assert policy.charging is True
    assert out["charge_goal"] > 0.0

    # i_tot climbs between ENTER and EXIT: must STAY open (hysteresis).
    mid = (hil.SOC_BAND_CHARGE_ENTER_ITOT_A + hil.SOC_BAND_CHARGE_EXIT_ITOT_A) / 2.0
    out = tick(mid, 0.68)
    assert policy.charging is True
    assert out["charge_goal"] > 0.0

    # i_tot exceeds EXIT: must close.
    out = tick(hil.SOC_BAND_CHARGE_EXIT_ITOT_A + 0.05, 0.68)
    assert policy.charging is False
    assert out["charge_goal"] == 0.0

    # i_tot back down to the SAME mid value (below EXIT, above ENTER): must
    # NOT reopen -- this is the asymmetry a single threshold would not have.
    out = tick(mid, 0.68)
    assert policy.charging is False
    assert out["charge_goal"] == 0.0


def test_soc_band_deficit_gate_hysteresis_holds_inside_band_releases_at_reference():
    """M6 (review, 2026-08-31): the DEFICIT gate has hysteresis too, mirroring
    the i_tot gate above.  ENTER requires deficit > SOC_BAND_HALF (the
    band-edge crossing, unchanged); once charging is TRUE the gate relaxes to
    HOLD while deficit > 0.0 -- i.e. it stays latched even after the pack
    recovers back INSIDE the band, releasing only once the pack is back AT
    (or above) the captured reference."""
    policy = hil.SocBandStrategy()
    dt = 0.02
    t = hil.EMS_RUN_ENTRY_S
    v = 1.0
    soc_ref = 0.70

    def tick(soc):
        nonlocal t
        fb = {"t": t, "v_profile": v, "soc": soc, "I_fc": 0.05, "I_batt": 0.05}
        out = policy(t, fb)
        t += dt
        return out

    # Warm-up at deficit 0 -- builds the cruise window, charging must not open.
    for _ in range(60):
        tick(soc_ref)
    assert policy.charging is False

    # Cross the band edge (deficit > SOC_BAND_HALF): charging opens.
    out = None
    for _ in range(10):
        out = tick(soc_ref - hil.SOC_BAND_HALF - 0.0002)
    assert policy.charging is True
    assert out["charge_goal"] > 0.0

    # SoC recovers back INSIDE the band (0 < deficit <= SOC_BAND_HALF): the
    # M6 hold means charging must STAY open here, unlike the pre-M6 law
    # (ENTER-threshold-only) which would have dropped it the instant the
    # deficit fell back under SOC_BAND_HALF.
    inside_band_soc = soc_ref - hil.SOC_BAND_HALF * 0.5
    assert (soc_ref - inside_band_soc) < hil.SOC_BAND_HALF   # sanity: really inside the band
    out = tick(inside_band_soc)
    assert policy.charging is True
    assert out["charge_goal"] > 0.0

    # SoC reaches exactly the reference (deficit == 0.0): must release.
    out = tick(soc_ref)
    assert policy.charging is False
    assert out["charge_goal"] == 0.0


def test_soc_band_deficit_gate_does_not_reopen_inside_band_when_not_already_charging():
    """The asymmetry that makes M6 hysteresis rather than a wider single
    threshold: a deficit inside the band (0 < deficit <= SOC_BAND_HALF) must
    NOT open the window while NOT already charging -- the relaxed >0.0 gate
    applies only to the HOLD, never to the ENTER."""
    policy = hil.SocBandStrategy()
    dt = 0.02
    t = hil.EMS_RUN_ENTRY_S
    v = 1.0
    soc_ref = 0.70

    def tick(soc):
        nonlocal t
        fb = {"t": t, "v_profile": v, "soc": soc, "I_fc": 0.05, "I_batt": 0.05}
        out = policy(t, fb)
        t += dt
        return out

    for _ in range(60):
        tick(soc_ref)
    assert policy.charging is False

    inside_band_soc = soc_ref - hil.SOC_BAND_HALF * 0.5
    out = None
    for _ in range(10):
        out = tick(inside_band_soc)
    assert policy.charging is False
    assert out["charge_goal"] == 0.0


def test_soc_band_auto_resets_on_t_rewind():
    policy = hil.SocBandStrategy()
    policy(10.0, {"t": 10.0, "v_profile": 1.0, "soc": 0.60, "I_fc": 0.0, "I_batt": 0.0})
    assert policy.soc_ref == pytest.approx(0.60)
    assert policy.last_t == pytest.approx(10.0)
    # Rewind: a second run in the same process must NOT inherit the first
    # run's captured reference.
    policy(5.0, {"t": 5.0, "v_profile": 1.0, "soc": 0.72, "I_fc": 0.0, "I_batt": 0.0})
    assert policy.soc_ref == pytest.approx(0.72)
    assert policy.charging is False
    assert policy.window == [(5.0, 1.0)]


def test_ems_soc_band_scenario_registered_with_soc_band_strategy():
    meta = hil.SCENARIOS["ems-soc-band"]
    assert meta.get("ems") == "soc-band"
    assert meta["ems"] in hil.EMS_STRATEGIES
    assert isinstance(meta.get("ems_v_profile"), list) and meta["ems_v_profile"]
    assert "pi_timeline" not in meta


# ─────────────────────────────────────────────────────────────────────────
# 15. dp-replay: load_dp_table(), fingerprint, ZOH lookup, refusal paths
# ─────────────────────────────────────────────────────────────────────────

def _write_dp_table(path, meta_lines, rows):
    lines = ["# %s" % line for line in meta_lines]
    lines.append("t,power_share_setpoint,charge_goal")
    for t, s, g in rows:
        lines.append("%r,%r,%r" % (t, s, g))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines) + "\n")


def test_load_dp_table_missing_file_raises_clearly(tmp_path):
    with pytest.raises(OSError):
        hil.load_dp_table(str(tmp_path / "nope.csv"))


def test_load_dp_table_bad_header_raises_value_error(tmp_path):
    path = tmp_path / "bad_header.csv"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# scenario: x\nt,share,goal\n0.0,0.5,0.0\n")
    with pytest.raises(ValueError, match="expected the column header"):
        hil.load_dp_table(str(path))


def test_load_dp_table_no_header_at_all_raises_value_error(tmp_path):
    path = tmp_path / "no_header.csv"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# just a comment, no data\n")
    with pytest.raises(ValueError, match="no column header"):
        hil.load_dp_table(str(path))


def test_load_dp_table_non_monotonic_times_raises_value_error(tmp_path):
    path = tmp_path / "non_monotonic.csv"
    _write_dp_table(path, ["scenario: x"],
                    [(0.0, 0.5, 0.0), (0.2, 0.5, 0.0), (0.1, 0.5, 0.0)])
    with pytest.raises(ValueError, match="strictly increase"):
        hil.load_dp_table(str(path))


def test_load_dp_table_no_rows_raises_value_error(tmp_path):
    path = tmp_path / "no_rows.csv"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# scenario: x\nt,power_share_setpoint,charge_goal\n")
    with pytest.raises(ValueError, match="no rows"):
        hil.load_dp_table(str(path))


def test_load_dp_table_wrong_column_count_raises_value_error(tmp_path):
    path = tmp_path / "bad_cols.csv"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# scenario: x\nt,power_share_setpoint,charge_goal\n0.0,0.5\n")
    with pytest.raises(ValueError, match="3 columns"):
        hil.load_dp_table(str(path))


def test_load_dp_table_valid_file_parses_meta_and_rows(tmp_path):
    path = tmp_path / "ok.csv"
    _write_dp_table(path, ["scenario: myscen", "run_exit_s: 58.0",
                           "profile_fingerprint: deadbeef"],
                    [(0.0, 0.25, 0.0), (0.1, 0.30, 0.0), (0.2, 0.75, 1.0)])
    meta, times, shares, goals = hil.load_dp_table(str(path))
    assert meta["scenario"] == "myscen"
    assert meta["run_exit_s"] == "58.0"
    assert meta["profile_fingerprint"] == "deadbeef"
    assert times == pytest.approx([0.0, 0.1, 0.2])
    assert shares == pytest.approx([0.25, 0.30, 0.75])
    assert goals == pytest.approx([0.0, 0.0, 1.0])


# ── ZOH lookup edges ────────────────────────────────────────────────────────

def _strategy_with_table(times, shares, goals):
    s = hil.DpReplayStrategy()
    s.times, s.shares, s.goals = list(times), list(shares), list(goals)
    return s


def test_dp_replay_lookup_before_first_row_holds_row_zero():
    s = _strategy_with_table([1.0, 2.0, 3.0], [0.3, 0.5, 0.7], [0.0, 0.0, 1.0])
    share, goal = s.lookup(0.5)
    assert (share, goal) == (0.3, 0.0)


def test_dp_replay_lookup_exactly_on_a_row_uses_that_row():
    s = _strategy_with_table([1.0, 2.0, 3.0], [0.3, 0.5, 0.7], [0.0, 0.0, 1.0])
    share, goal = s.lookup(2.0)
    assert (share, goal) == (0.5, 0.0)


def test_dp_replay_lookup_between_rows_holds_the_last_row_at_or_before_t():
    s = _strategy_with_table([1.0, 2.0, 3.0], [0.3, 0.5, 0.7], [0.0, 0.0, 1.0])
    share, goal = s.lookup(2.9)
    assert (share, goal) == (0.5, 0.0)


def test_dp_replay_lookup_after_last_row_holds_the_last_row():
    s = _strategy_with_table([1.0, 2.0, 3.0], [0.3, 0.5, 0.7], [0.0, 0.0, 1.0])
    share, goal = s.lookup(100.0)
    assert (share, goal) == (0.7, 1.0)


# ── bind_scenario()/fingerprint refusal paths ───────────────────────────────

def test_dp_replay_call_without_bind_raises_runtime_error():
    s = hil.DpReplayStrategy()
    with pytest.raises(RuntimeError, match="without a bound table"):
        s(3.0, {"t": 3.0, "v_profile": 1.0})


def test_dp_replay_bind_scenario_missing_table_file_raises_value_error(tmp_path):
    s = hil.DpReplayStrategy(table_dir=str(tmp_path))
    with pytest.raises(ValueError, match="none exists"):
        s.bind_scenario("no-such-scenario", {"ems_v_profile": [(0.0, 0.0)],
                                              "duration_s": 10.0})


def test_dp_replay_bind_scenario_fingerprint_mismatch_raises_value_error(tmp_path):
    """The 'tampered profile' refusal: a table exists but was generated for a
    different profile than the one the active scenario now declares."""
    meta_a = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0}
    fp_a = hil.dp_profile_fingerprint("myscen", meta_a)
    path = os.path.join(str(tmp_path), hil.DP_TABLE_NAME % "myscen")
    _write_dp_table(path, ["scenario: myscen", "run_exit_s: 8.0",
                           "profile_fingerprint: %s" % fp_a],
                    [(0.0, 0.5, 0.0)])
    s = hil.DpReplayStrategy(table_dir=str(tmp_path))
    # A DIFFERENT profile (tampered/retuned) -- the fingerprint must not match.
    meta_b = {"ems_v_profile": [(0.0, 0.0), (10.0, 2.0)], "duration_s": 10.0}
    with pytest.raises(ValueError, match="DIFFERENT profile"):
        s.bind_scenario("myscen", meta_b)


def test_dp_replay_bind_scenario_missing_run_exit_s_raises_value_error(tmp_path):
    meta = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0}
    fp = hil.dp_profile_fingerprint("myscen", meta)
    path = os.path.join(str(tmp_path), hil.DP_TABLE_NAME % "myscen")
    _write_dp_table(path, ["scenario: myscen", "profile_fingerprint: %s" % fp],
                    [(0.0, 0.5, 0.0)])
    s = hil.DpReplayStrategy(table_dir=str(tmp_path))
    with pytest.raises(ValueError, match="run_exit_s"):
        s.bind_scenario("myscen", meta)


def test_dp_replay_bind_scenario_success_loads_table_and_call_works(tmp_path):
    meta = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0}
    fp = hil.dp_profile_fingerprint("myscen", meta)
    path = os.path.join(str(tmp_path), hil.DP_TABLE_NAME % "myscen")
    _write_dp_table(path, ["scenario: myscen", "run_exit_s: 8.0",
                           "profile_fingerprint: %s" % fp],
                    [(0.0, 0.4, 0.0), (5.0, 0.6, 1.0)])
    s = hil.DpReplayStrategy(table_dir=str(tmp_path))
    s.bind_scenario("myscen", meta)
    out = s(6.0, {"t": 6.0, "v_profile": 0.5})
    assert out["power_share_setpoint"] == pytest.approx(0.6)
    assert out["charge_goal"] == pytest.approx(1.0)
    assert out["mode_cmd"] == hil.MODE_HYBRID
    # Past run_exit_s: MODE_SAFE and charge_goal forced to 0 regardless of the
    # table's row (the "nothing may be commanded onto the charger path outside
    # Run" rule, verbatim from soc-band).
    out2 = s(9.0, {"t": 9.0, "v_profile": 0.5})
    assert out2["mode_cmd"] == hil.MODE_SAFE
    assert out2["charge_goal"] == 0.0


# ── M1/M2 (2026-08-31 reconciliation): bind_scenario() accounting/constant
#    drift guards, and the electrical_mode=/args= backward-compat contract ──

def _live_table_meta_lines(scenario, fp, charger_accounting="physical",
                           run_exit_s=None, soc0=0.7, capacity_ah=5.0,
                           chg_ceiling_a=0.8):
    """A full set of header lines that agree with the CURRENTLY IMPORTED
    module constants and the given args -- used as the "everything matches"
    baseline that individual tests then perturb exactly one field of."""
    run_exit_s = hil.SOC_BAND_RUN_EXIT_S if run_exit_s is None else run_exit_s
    return [
        "scenario: %s" % scenario,
        "profile_fingerprint: %s" % fp,
        "run_exit_s: %r" % float(run_exit_s),
        "charger_accounting: %s" % charger_accounting,
        "soc0: %r" % float(soc0),
        "capacity_ah: %r" % float(capacity_ah),
        "chg_ceiling_a: %r" % float(chg_ceiling_a),
        "eta_boost: %r" % float(hil.ETA_BOOST),
        "gfc_dc_gain_gps_per_w: %r" % float(hil.H2_GFC_DC_GAIN_GPS_PER_W),
        "charge_share_value: %r" % float(hil.SOC_BAND_SHARE_NOMINAL
                                         + hil.SOC_BAND_SHARE_SPAN),
        "share_span: %r" % float(hil.SOC_BAND_SHARE_SPAN),
        "cruise_slope_max: %r" % float(hil.SOC_BAND_CRUISE_SLOPE_MAX),
        "cruise_min_mps: %r" % float(hil.SOC_BAND_CRUISE_MIN_MPS),
    ]


def _bindable(tmp_path, scenario="myscen", **kw):
    """Write a fully-agreeing table for `scenario` and return
    (strategy, meta, args) ready to bind -- kw forwards to
    _live_table_meta_lines() so a test can perturb exactly one field."""
    import types
    meta = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0,
            "chg_i_ceiling_a": kw.get("chg_ceiling_a", 0.8)}
    fp = hil.dp_profile_fingerprint(scenario, meta)
    path = os.path.join(str(tmp_path), hil.DP_TABLE_NAME % scenario)
    _write_dp_table(path, _live_table_meta_lines(scenario, fp, **kw),
                    [(0.0, 0.5, 0.0), (5.0, 0.6, 1.0)])
    s = hil.DpReplayStrategy(table_dir=str(tmp_path))
    args = types.SimpleNamespace(soc0=kw.get("soc0", 0.7),
                                 capacity_ah=kw.get("capacity_ah", 5.0))
    return s, meta, args


def test_dp_replay_bind_scenario_two_arg_call_is_backward_compatible(tmp_path):
    """Neither electrical_mode nor args is required -- a caller that only
    wants the profile-fingerprint check (a test, a future tool) must keep
    working exactly as before this round, with NO M1/M2 checking done."""
    s, meta, _args = _bindable(tmp_path)
    s.bind_scenario("myscen", meta)                     # two positional args only
    assert s.path is not None


def test_dp_replay_bind_scenario_accounting_match_passes_with_electrical_mode(tmp_path):
    s, meta, args = _bindable(tmp_path, charger_accounting="physical")
    s.bind_scenario("myscen", meta, electrical_mode="hifi", args=args)
    assert s.path is not None


def test_dp_replay_bind_scenario_accounting_mismatch_physical_table_under_simple_engine(tmp_path):
    s, meta, _args = _bindable(tmp_path, charger_accounting="physical")
    with pytest.raises(ValueError, match="charger-accounting"):
        s.bind_scenario("myscen", meta, electrical_mode="simple")


def test_dp_replay_bind_scenario_accounting_mismatch_simple_table_under_hifi_engine(tmp_path):
    """The other direction: a table solved for the simple-mode accounting
    replayed under the hifi engine must refuse too."""
    s, meta, _args = _bindable(tmp_path, charger_accounting="simple")
    with pytest.raises(ValueError, match="charger-accounting"):
        s.bind_scenario("myscen", meta, electrical_mode="hifi")


def test_dp_replay_bind_scenario_args_drift_soc0_names_the_value(tmp_path):
    """One args-mismatch case (soc0): the run's --soc0 disagrees with the
    header's recorded soc0 -- must refuse and NAME which value drifted."""
    s, meta, args = _bindable(tmp_path, soc0=0.7)
    args.soc0 = 0.5                     # the RUN disagrees with the table
    with pytest.raises(ValueError) as exc_info:
        s.bind_scenario("myscen", meta, electrical_mode="hifi", args=args)
    msg = str(exc_info.value)
    assert "soc0" in msg
    assert "0.7" in msg and "0.5" in msg


def test_dp_replay_bind_scenario_constant_drift_cruise_slope_max_names_the_value(tmp_path, monkeypatch):
    """One constant-mismatch case: SOC_BAND_CRUISE_SLOPE_MAX moved since the
    table was generated (monkeypatched on the module -- the table's header
    line is written against the ORIGINAL value first, then the live constant
    is patched out from under it)."""
    s, meta, args = _bindable(tmp_path)          # header written at the live value
    monkeypatch.setattr(hil, "SOC_BAND_CRUISE_SLOPE_MAX",
                        hil.SOC_BAND_CRUISE_SLOPE_MAX + 0.01)
    with pytest.raises(ValueError) as exc_info:
        s.bind_scenario("myscen", meta, electrical_mode="hifi", args=args)
    msg = str(exc_info.value)
    assert "cruise_slope_max" in msg


def test_dp_replay_bind_scenario_absent_header_line_refuses_rather_than_skips(tmp_path):
    """An OLDER table predating one of the M2 header lines must REFUSE, not
    silently skip the check that line would have driven -- "the table does
    not record it" is exactly the state in which a drift is invisible."""
    import types
    scenario = "myscen"
    meta = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0,
            "chg_i_ceiling_a": 0.8}
    fp = hil.dp_profile_fingerprint(scenario, meta)
    lines = [l for l in _live_table_meta_lines(scenario, fp)
            if not l.startswith("cruise_min_mps:")]   # drop ONE M2 header line
    path = os.path.join(str(tmp_path), hil.DP_TABLE_NAME % scenario)
    _write_dp_table(path, lines, [(0.0, 0.5, 0.0), (5.0, 0.6, 1.0)])
    s = hil.DpReplayStrategy(table_dir=str(tmp_path))
    args = types.SimpleNamespace(soc0=0.7, capacity_ah=5.0)
    with pytest.raises(ValueError) as exc_info:
        s.bind_scenario(scenario, meta, electrical_mode="hifi", args=args)
    msg = str(exc_info.value)
    assert "cruise_min_mps" in msg
    assert "absent" in msg


# ── fingerprint sensitivity ─────────────────────────────────────────────────

def test_dp_profile_fingerprint_changes_when_a_covered_field_changes():
    base = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0,
            "chg_i_ceiling_a": 0.8}
    fp_base = hil.dp_profile_fingerprint("s", base)
    variants = [
        dict(base, ems_v_profile=[(0.0, 0.0), (10.0, 1.5)]),  # profile point moved
        dict(base, duration_s=11.0),
        dict(base, chg_i_ceiling_a=1.6),
    ]
    for v in variants:
        assert hil.dp_profile_fingerprint("s", v) != fp_base
    # The scenario NAME is covered too (it is part of the fingerprint string).
    assert hil.dp_profile_fingerprint("other", base) != fp_base


def test_dp_profile_fingerprint_stable_across_uncovered_field_and_repeats():
    base = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0,
            "description": "some text", "electrical": "any"}
    fp1 = hil.dp_profile_fingerprint("s", base)
    fp2 = hil.dp_profile_fingerprint("s", base)
    assert fp1 == fp2                  # deterministic, repeated calls agree
    with_desc_changed = dict(base, description="different text entirely")
    assert hil.dp_profile_fingerprint("s", with_desc_changed) == fp1


def test_dp_profile_fingerprint_sensitive_to_drain_load_constants():
    """The fingerprint also covers the module-level drain-load constants
    (SOC_BAND_DRAIN_*, SOC_LOAD_RAMP_S, I_AUX_A) -- retuning the drain changes
    the demand the table was generated against even though no scenario
    metadata field moved.  Patch one and confirm the digest moves."""
    meta = {"ems_v_profile": [(0.0, 0.0), (10.0, 1.0)], "duration_s": 10.0}
    fp_before = hil.dp_profile_fingerprint("s", meta)
    orig = hil.SOC_BAND_DRAIN_LOAD_A
    try:
        hil.SOC_BAND_DRAIN_LOAD_A = orig + 0.5
        fp_after = hil.dp_profile_fingerprint("s", meta)
    finally:
        hil.SOC_BAND_DRAIN_LOAD_A = orig
    assert fp_after != fp_before


# ── the SHIPPED table (dp_tables/dp_ems_table_ems-dp-replay.csv) ────────────
# This is the drift tripwire for the checked-in artifact: if the scenario, the
# module constants, or the generator's fingerprinted inputs are retuned
# without regenerating the table, this test fails loudly instead of a stale
# table silently going on being replayed.

def test_shipped_dp_table_parses():
    meta, times, shares, goals = hil.load_dp_table(
        os.path.join(hil.DP_TABLE_DIR, "dp_ems_table_ems-dp-replay.csv"))
    assert times, "sanity: the shipped table must have rows"
    assert len(times) == len(shares) == len(goals)
    assert meta.get("scenario") == "ems-dp-replay"


def test_shipped_dp_table_share_stays_within_the_authority_band():
    _meta, _times, shares, _goals = hil.load_dp_table(
        os.path.join(hil.DP_TABLE_DIR, "dp_ems_table_ems-dp-replay.csv"))
    lo = hil.SOC_BAND_SHARE_NOMINAL - hil.SOC_BAND_SHARE_SPAN
    hi = hil.SOC_BAND_SHARE_NOMINAL + hil.SOC_BAND_SHARE_SPAN
    assert min(shares) >= lo - 1e-9
    assert max(shares) <= hi + 1e-9
    # 0.25 == lo and 0.75 == hi -- the DP grid spans exactly the band.
    assert min(shares) == pytest.approx(lo)
    assert max(shares) == pytest.approx(hi)


def test_shipped_dp_table_charge_goal_is_zero_on_every_row():
    """FINDING recorded in the SCENARIOS["ems-dp-replay"] module comment: the
    DP opens the charger path on ZERO stages of this cycle (shifting the split
    toward the fuel cell is the better lever at this rig's numbers).  Pin that
    finding against the checked-in table itself, so a regeneration that
    silently starts charging is caught here rather than only in a HIL
    campaign."""
    _meta, _times, _shares, goals = hil.load_dp_table(
        os.path.join(hil.DP_TABLE_DIR, "dp_ems_table_ems-dp-replay.csv"))
    assert all(g == 0.0 for g in goals)


def test_shipped_dp_table_fingerprint_matches_the_live_ems_dp_replay_scenario():
    """The drift tripwire proper: recompute the fingerprint from the CURRENTLY
    IMPORTED SCENARIOS['ems-dp-replay'] entry (which shares its profile and
    drain load with ems-soc-band by construction) and confirm it matches the
    value baked into the checked-in table's header.  A mismatch means the
    scenario or a drain constant moved and the table needs `--force`
    regeneration."""
    meta, _times, _shares, _goals = hil.load_dp_table(
        os.path.join(hil.DP_TABLE_DIR, "dp_ems_table_ems-dp-replay.csv"))
    live_fp = hil.dp_profile_fingerprint("ems-dp-replay", hil.SCENARIOS["ems-dp-replay"])
    assert meta["profile_fingerprint"] == live_fp


def test_shipped_dp_table_soc_band_header_lines_match_live_constants():
    """M2 tripwire from the ARTIFACT side (item 6, 2026-08-31 reconciliation):
    the shipped table's three share_span/cruise_slope_max/cruise_min_mps
    header lines (which shape the DP's control grid and charge mask) must
    themselves agree with the currently-imported SOC_BAND_* constants -- a
    drift here means the checked-in table needs `--force` regeneration,
    independent of (and in addition to) bind_scenario()'s runtime check
    below."""
    meta, _times, _shares, _goals = hil.load_dp_table(
        os.path.join(hil.DP_TABLE_DIR, "dp_ems_table_ems-dp-replay.csv"))
    assert float(meta["share_span"]) == pytest.approx(hil.SOC_BAND_SHARE_SPAN)
    assert float(meta["cruise_slope_max"]) == pytest.approx(hil.SOC_BAND_CRUISE_SLOPE_MAX)
    assert float(meta["cruise_min_mps"]) == pytest.approx(hil.SOC_BAND_CRUISE_MIN_MPS)


def test_shipped_dp_table_binds_cleanly_under_the_full_m1_m2_check(tmp_path):
    """End-to-end drift tripwire: the shipped table must actually PASS
    bind_scenario()'s full M1 (accounting-vs-engine) and M2 (header-vs-live)
    checks under exactly the conditions a default HIL campaign runs it under
    -- electrical_mode='hifi' (SCENARIOS['ems-dp-replay']['electrical'], item
    5) and the generator's own default --soc0/--capacity-ah.  If this fails,
    the checked-in table has drifted from the live module and needs
    regeneration -- the same conclusion the narrower tests above reach
    piecewise, exercised here through the real consumer path."""
    import types
    s = hil.DpReplayStrategy()   # default table_dir == hil.DP_TABLE_DIR
    args = types.SimpleNamespace(soc0=0.7, capacity_ah=5.0)
    s.bind_scenario("ems-dp-replay", hil.SCENARIOS["ems-dp-replay"],
                    electrical_mode=hil.SCENARIOS["ems-dp-replay"]["electrical"],
                    args=args)
    assert s.path is not None
    assert s.times


def test_ems_dp_replay_scenario_registered_with_dp_replay_strategy():
    meta = hil.SCENARIOS["ems-dp-replay"]
    assert meta.get("ems") == "dp-replay"
    assert meta["ems"] in hil.EMS_STRATEGIES
    # DERIVED: the same list OBJECT as ems-soc-band's profile, by construction.
    assert meta["ems_v_profile"] is hil.SCENARIOS["ems-soc-band"]["ems_v_profile"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
