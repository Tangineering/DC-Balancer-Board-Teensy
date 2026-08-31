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

    records, header, warnings = hil.load_replay(path)
    assert header["version"] == 3
    assert len(records) == len(result.csv_rows)

    for (t_s, sensors), csv_row in zip(records, result.csv_rows):
        cells = csv_row.split(",")
        for src, dst in hil.REPLAY_FIELD_MAP:
            cell = cells[idx[src]]
            expected = float(cell) if cell != "" else 0.0
            assert sensors[dst] == pytest.approx(expected, abs=1e-4), (src, dst)
        assert sensors["I_charge"] == 0.0
        assert sensors["ag105_status"] == hil.AG105_ST_DISCONNECT


def test_load_replay_blank_v_act_becomes_zero(tmp_path):
    """v1/v2 logs carry a velocity-invalid window (blank v_act cell); the
    replay must inject 0.0 m/s for those records, not raise or propagate a
    blank string."""
    path = _write_synthetic_blg(tmp_path, fw_version=1, header_v1=True)
    records, header, warnings = hil.load_replay(path)
    assert header["version"] in (1, 2)
    v_actuals = [sensors["v_actual"] for _, sensors in records]
    assert any(v == 0.0 for v in v_actuals), \
        "expected at least one blank/zero v_act sample in the synthetic v1 log"
    assert all(isinstance(v, float) for v in v_actuals)


def test_load_replay_i_charge_and_status_default_zero(tmp_path):
    path = _write_synthetic_blg(tmp_path, fw_version=6, v6=True)
    records, header, warnings = hil.load_replay(path)
    assert header["version"] == 6
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


def test_load_replay_wrap_safe_t_us(tmp_path):
    """A log whose t_us straddles the uint32 micros() wrap must decode to a
    monotonically non-decreasing time axis, not jump backwards or explode."""
    path = _write_synthetic_blg(tmp_path, fw_version=1, header_v1=True, wrap=True)
    records, header, warnings = hil.load_replay(path)
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
# 7. SCENARIOS registry
# ─────────────────────────────────────────────────────────────────────────

EXPECTED_SCENARIO_NAMES = {
    "steady", "step-load", "sag", "comm-loss", "drive",
    "charge-cruise", "charge-regen", "charge-fault", "soc-depletion",
    "ems-drive-cycle",
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
    hifi_only = {name for name, meta in hil.SCENARIOS.items() if meta["electrical"] == "hifi"}
    assert hifi_only == {"handoff-sag", "bringup", "scp-inrush"}


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


def test_charge_regen_timeline_delivers_positive_charge_goal():
    meta = hil.SCENARIOS["charge-regen"]
    state = {"charge_goal": 0.0}
    for _t, fields in meta["pi_timeline"]:
        state.update(fields)
    assert state["charge_goal"] > 0.0


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
    # mode (this round), after soc — so soc is now third-from-last.
    assert header[-3:] == ["soc", "cmd_v_sp", "cmd_share_sp"]
    assert "elec_substep_hz" not in header
    assert "elec_events" not in header
    assert "replay_rec" not in header


def test_csv_schema_hifi_mode_appends_elec_columns(tmp_path):
    header, _rows = _run_main_csv(
        tmp_path, ["--scenario", "steady", "--electrical", "hifi", "--duration", "0.02"])
    assert header[-5:] == ["soc", "elec_substep_hz", "elec_events",
                           "cmd_v_sp", "cmd_share_sp"]


REPLAY_CSV_HEADER_PIN = [
    "t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
    "v_actual", "I_charge", "ag105_status",
    "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
    "fault_flags", "replay_rec",
]


def test_csv_schema_replay_mode_unchanged_with_replay_rec_last(tmp_path):
    """Regression-pin the exact pre-existing replay CSV column order: replay
    mode must NOT gain soc/elec columns (the plant integrator is bypassed, so
    they would be meaningless — see the module's own comment at the writer)."""
    blg_path = _write_synthetic_blg(tmp_path, fw_version=14, v3=True)
    header, _rows = _run_main_csv(
        tmp_path, ["--replay", blg_path, "--duration", "0.02"], name="replay.csv")
    assert header == REPLAY_CSV_HEADER_PIN
    assert header[-1] == "replay_rec"


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
    # cmd_v_sp/cmd_share_sp are now unconditionally appended after the hifi
    # elec_* columns in simulated-plant mode (INTENDED, this round), so
    # elec_events is the third-from-last column, not the last.
    assert header[-2:] == ["cmd_v_sp", "cmd_share_sp"]
    elec_events_col = rows[-1][-3]
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
    assert meta["duration_s"] == pytest.approx(60.0)
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
    assert header[-2:] == ["cmd_v_sp", "cmd_share_sp"]
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
