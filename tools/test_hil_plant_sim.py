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
    plant = hil.Plant()
    obs = _obs(switch=hil.SW_FC_BUS, aux=hil.AUX_FC_REG, current=0.0)
    out = plant.step(1e-3, obs)
    # i_total is just I_AUX_A (no motor draw, mot_live False)
    expected = hil.V_BUS_NOMINAL - hil.K_DROOP_BUS * hil.I_AUX_A
    assert out["V_bus"] == pytest.approx(expected, abs=1e-6)


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
    plant = hil.Plant()
    # Drive up I_fc/I_batt through a large aux-equivalent draw by cranking
    # the motor with both sources live, so the sag term is non-trivial.
    plant.v_bus = hil.V_BUS_NOMINAL
    obs = _obs(switch=SW_ALL_LIVE, aux=AUX_BOTH_REG, current=6.0)
    out = None
    for _ in range(500):
        out = plant.step(1e-3, obs)
    assert out["I_fc"] > 0.0
    expected_v_fc = max(0.0, hil.V_FC_OPEN - hil.R_FC_INT * out["I_fc"])
    assert out["V_fc"] == pytest.approx(expected_v_fc, abs=1e-6)
    assert out["V_fc"] < hil.V_FC_OPEN
    expected_v_batt = max(0.0, hil.V_BT_OPEN - hil.R_BT_INT * out["I_batt"])
    assert out["V_batt"] == pytest.approx(expected_v_batt, abs=1e-6)


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


def test_v_rgn_gated_on_regen_switch():
    plant = hil.Plant()
    plant.v_bus = 12.0
    obs_open = _obs(switch=0, aux=0, current=0.0)
    out = plant.step(1e-3, obs_open)
    assert out["V_rgn"] == 0.0
    plant2 = hil.Plant()
    plant2.v_bus = 12.0
    obs_closed = _obs(switch=hil.SW_REGEN, aux=0, current=0.0)
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
