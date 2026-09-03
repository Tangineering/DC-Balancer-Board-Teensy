#!/usr/bin/env python3
"""pytest suite for tools/governor_model.py -- stdlib-only port of the firmware
share-delivery governor (updateShareSetpointCutoff/updateShareSlewMode/
powerBalance/applyShareRatio/setDroopMdac/busSwitchBlanked).

STDLIB ONLY -- this file must collect and pass under BOTH
    .venv_hil\\Scripts\\python.exe -m pytest tools/test_governor_model.py -v
and a miniforge interpreter. It imports nothing beyond stdlib + pytest +
governor_model.

The firmware regions were re-read directly (not trusted from the module's own
comments) at:
    .ino:2160-2303 (RE_MAX/K_DROOP/DROOP_R_MIN/MAX/SHARE_* constants)
    .ino:3240-3420 (SHARE_CUT_SURVIVOR_BLANK_MS derivation, busSwitchBlanked,
                    writeBusSwitch chokepoint, refusal-counter semantics)
    .ino:9756      (SHARE_SP_CHANGE_EPS)
    .ino:10740-10748 (setDroopMdac word format, MDAC_res=4095)
    .ino:1845      (MDAC_res 4095)
    .ino:2455      (POWER_BAL_PERIOD_US 1000)
"""
import math
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO_ROOT = os.path.dirname(HERE)
INO_PATH = os.path.join(REPO_ROOT, "teensy_controller", "teensy_controller.ino")

import governor_model as gm  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Firmware constant pin
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ino_text():
    with open(INO_PATH, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


# name in GOV_CONST -> (regex to find the firmware literal, expected value)
# ⚠️ `const` OR `constexpr` (2026-09-02).  The firmware moved several of these
# declarations from `const float` to `constexpr float`; the VALUES are
# unchanged, and this scrape is about the values.  Matching only `const float`
# turned a declaration-style edit into "could not find firmware literal", which
# reads as a drift and is not one.  The optional group keeps the check on the
# NUMBER, which is what the governor model has to agree with.
_FW_CONST_PATTERNS = {
    "K_DROOP": r"const(?:expr)?\s+float\s+K_DROOP\s*=\s*([0-9.]+)f",
    "DROOP_R_MIN": r"const(?:expr)?\s+float\s+DROOP_R_MIN\s*=\s*([0-9.]+)f",
    "DROOP_R_MAX": r"const(?:expr)?\s+float\s+DROOP_R_MAX\s*=\s*([0-9.]+)f",
    "SHARE_I_TOT_MIN_A": r"const(?:expr)?\s+float\s+SHARE_I_TOT_MIN_A\s*=\s*([0-9.]+)f",
    "SHARE_MINORITY_I_MIN_A": r"const(?:expr)?\s+float\s+SHARE_MINORITY_I_MIN_A\s*=\s*([0-9.]+)f",
    "SHARE_CUT_MAX_HANDOFF_A": r"const(?:expr)?\s+float\s+SHARE_CUT_MAX_HANDOFF_A\s*=\s*([0-9.]+)f",
    "SHARE_GOV_OL_HYST_A": r"const(?:expr)?\s+float\s+SHARE_GOV_OL_HYST_A\s*=\s*([0-9.]+)f",
    "DROOP_RATIO_SLEW_PER_TICK": r"const(?:expr)?\s+float\s+DROOP_RATIO_SLEW_PER_TICK\s*=\s*([0-9.]+)f",
    "SHARE_HANDOFF_MIN_A": r"const(?:expr)?\s+float\s+SHARE_HANDOFF_MIN_A\s*=\s*([0-9.]+)f",
    "DROOP_RATIO_SLEW_HANDOFF_PER_TICK": r"const(?:expr)?\s+float\s+DROOP_RATIO_SLEW_HANDOFF_PER_TICK\s*=\s*([0-9.]+)f",
    "SHARE_HANDOFF_LIVE_A": r"const(?:expr)?\s+float\s+SHARE_HANDOFF_LIVE_A\s*=\s*([0-9.]+)f",
    "SHARE_HANDOFF_DWELL_MAX_TICKS": r"const\s+int\s+SHARE_HANDOFF_DWELL_MAX_TICKS\s*=\s*(\d+)",
    "SHARE_GOV_FILT_ALPHA": r"const(?:expr)?\s+float\s+SHARE_GOV_FILT_ALPHA\s*=\s*([0-9.]+)f",
    # fw v26 source current-ceiling governor.  These three are `constexpr float`
    # in the firmware BY DESIGN -- the static_asserts at the constants are
    # written against the symbols -- so the optional `expr` group above is
    # load-bearing here rather than merely tolerant.
    "SHARE_GOV_I_FC_CEIL_A": r"const(?:expr)?\s+float\s+SHARE_GOV_I_FC_CEIL_A\s*=\s*([0-9.]+)f",
    "SHARE_GOV_I_BT_CEIL_A": r"const(?:expr)?\s+float\s+SHARE_GOV_I_BT_CEIL_A\s*=\s*([0-9.]+)f",
    "SHARE_GOV_CEIL_HYST_A": r"const(?:expr)?\s+float\s+SHARE_GOV_CEIL_HYST_A\s*=\s*([0-9.]+)f",
    "SHARE_CUTOFF_HYST": r"const(?:expr)?\s+float\s+SHARE_CUTOFF_HYST\s*=\s*([0-9.]+)f",
    "SHARE_CUT_SURVIVOR_BLANK_MS": r"const\s+uint32_t\s+SHARE_CUT_SURVIVOR_BLANK_MS\s*=\s*(\d+)u",
    "SHARE_SP_CHANGE_EPS": r"const(?:expr)?\s+float\s+SHARE_SP_CHANGE_EPS\s*=\s*([0-9.eE+-]+)f",
    "MDAC_RES": r"const\s+int\s+MDAC_res\s*=\s*(\d+)",
    "POWER_BAL_PERIOD_US": r"#define\s+POWER_BAL_PERIOD_US\s+(\d+)u",
}


@pytest.mark.parametrize("name", sorted(_FW_CONST_PATTERNS))
def test_gov_const_matches_firmware(ino_text, name):
    pattern = _FW_CONST_PATTERNS[name]
    m = re.search(pattern, ino_text)
    assert m, "could not find firmware literal for %s (pattern out of date?)" % name
    fw_val = float(m.group(1))
    assert gm.GOV_CONST[name] == pytest.approx(fw_val, rel=1e-9, abs=1e-12)


def test_re_max_derivation(ino_text):
    # RE_MAX = K_sns * A_v * (RD1/RINJ); .ino:2163-2166.
    m_ksns = re.search(r"K_sns\s*=\s*([0-9.]+)f", ino_text)
    m_av = re.search(r"A_v\s*=\s*([0-9.]+)f", ino_text)
    m_rd1 = re.search(r"RD1_OVER_RINJ\s*=\s*([0-9.]+)f\s*/\s*([0-9.]+)f", ino_text)
    assert m_ksns and m_av and m_rd1
    k_sns = float(m_ksns.group(1))
    a_v = float(m_av.group(1))
    rd1_over_rinj = float(m_rd1.group(1)) / float(m_rd1.group(2))
    expected = k_sns * a_v * rd1_over_rinj
    assert gm.GOV_CONST["RE_MAX"] == pytest.approx(expected, rel=1e-9)


def test_mdac_cmd_load_update_matches_firmware_nop_convention(ino_text):
    # .ino:10742-10744: bare code == control 0000 == NOP; the firmware ORs in a
    # non-zero control nibble to get LOAD+UPDATE. GOV_CONST names the nibble
    # 0x1000. Pin it against the module's own r_from_codes/mdac_fraction usage:
    # a code with the wrong nibble must decode as 0.0 (NOP), never as data.
    word_wrong_nibble = 0x2ABC  # any nonzero, non-0x1000 high nibble
    assert gm.mdac_fraction(word_wrong_nibble) == 0.0
    word_right_nibble = gm.GOV_CONST["MDAC_CMD_LOAD_UPDATE"] | 0x0ABC
    assert gm.mdac_fraction(word_right_nibble) == pytest.approx(0x0ABC / 4095.0)


# ─────────────────────────────────────────────────────────────────────────────
# r_from_codes / mdac_fraction
# ─────────────────────────────────────────────────────────────────────────────
def test_mdac_code_round_trip_via_gain_map():
    r = 0.3
    k_droop = gm.GOV_CONST["K_DROOP"]
    re_max = gm.GOV_CONST["RE_MAX"]
    g_fc = k_droop / (re_max * r)
    g_bt = k_droop / (re_max * (1.0 - r))
    code_fc = gm._mdac_code(g_fc)
    code_bt = gm._mdac_code(g_bt)
    r_back = gm.r_from_codes(code_fc, code_bt)
    # Quantization to 12 bits limits precision; loose but not vacuous.
    assert r_back == pytest.approx(r, abs=2.0 / gm.GOV_CONST["MDAC_RES"])


def test_r_from_codes_none_safety():
    assert gm.r_from_codes(None, 100) is None
    assert gm.r_from_codes(100, None) is None
    assert gm.r_from_codes(None, None) is None


def test_mdac_fraction_non_load_update_nibble_is_zero():
    # A control nibble that is neither 0 (NOP) nor 0x1000 (LOAD+UPDATE) still
    # is not "our" data word.
    assert gm.mdac_fraction(0x3ABC) == 0.0


def test_r_from_codes_both_codes_zero_is_none():
    zero_word = gm.GOV_CONST["MDAC_CMD_LOAD_UPDATE"] | 0x000
    assert gm.r_from_codes(zero_word, zero_word) is None


def test_mdac_code_truncates_not_rounds_at_boundary():
    # gain*4095 landing just under an integer boundary must floor, not round.
    res = gm.GOV_CONST["MDAC_RES"]
    # Choose a gain whose product is X.999...: 2047.9999/4095
    gain = 2047.9999 / res
    word = gm._mdac_code(gain)
    code = word & 0x0FFF
    assert code == 2047, "expected truncation toward zero, got round-to-nearest"


# ─────────────────────────────────────────────────────────────────────────────
# Min-load freeze
# ─────────────────────────────────────────────────────────────────────────────
def test_min_load_freeze_holds_r_prev_and_no_filter_advance():
    g = gm.GovernorModel(seed_r=0.6)
    r0 = g.state.r_prev
    filt0 = g.state.filt_total
    tiny = gm.GOV_CONST["SHARE_I_TOT_MIN_A"] * 0.5
    for k in range(20):
        out = g.step(0.5, tiny / 2.0, tiny / 2.0, True, True, k * 1e-3)
        assert out.mode == gm.MODE_FROZEN
        assert out.r_applied == pytest.approx(r0)
    assert g.state.filt_total == pytest.approx(filt0), \
        "governor load filter must not advance while frozen"


# ─────────────────────────────────────────────────────────────────────────────
# Closed-loop entry/exit hysteresis, no chatter, OL->CL reseed
# ─────────────────────────────────────────────────────────────────────────────
def _drive_to_closed_loop(g, i_each=0.5, ticks=40, t0=0.0):
    for k in range(ticks):
        out = g.step(0.5, i_each, i_each, True, True, t0 + k * 1e-3)
    return out


def test_closed_loop_entry_and_exit_hysteresis():
    entry = 2.0 * gm.GOV_CONST["SHARE_MINORITY_I_MIN_A"]  # 0.60 A
    exit_ = entry - gm.GOV_CONST["SHARE_GOV_OL_HYST_A"]   # 0.55 A

    g = gm.GovernorModel(seed_r=0.5)
    # Drive filt_total above 0.60 -> must enter closed loop.
    for k in range(400):
        out = g.step(0.5, 0.35, 0.35, True, True, k * 1e-3)
    assert g.state.closed_loop_mode is True
    assert g.state.filt_total > entry

    # Now drop load (but stay above the min-load freeze floor, or filt_total
    # never advances at all) so filtered total decays below 0.55 -> must exit.
    low = gm.GOV_CONST["SHARE_I_TOT_MIN_A"] * 1.5 / 2.0
    for k in range(400, 800):
        out = g.step(0.5, low, low, True, True, k * 1e-3)
        if g.state.filt_total < exit_:
            break
    assert g.state.filt_total < exit_
    assert g.state.closed_loop_mode is False


def test_no_chatter_dithering_at_0p575_of_entry_threshold():
    # 0.575 A sits strictly between exit (0.55) and entry (0.60): once closed,
    # dithering the filtered total across 0.575 A alone must never re-trigger
    # entry/exit (only crossing 0.60 or 0.55 does).
    g = gm.GovernorModel(seed_r=0.5)
    for k in range(400):
        g.step(0.5, 0.35, 0.35, True, True, k * 1e-3)
    assert g.state.closed_loop_mode is True

    transitions = 0
    prev_mode = g.state.closed_loop_mode
    # Dither instantaneous total around 0.575 A (well inside the band); the EMA
    # filter itself damps this, but even inspecting closed_loop_mode directly
    # after every tick must show zero flips.
    for k in range(400, 1200):
        i_each = (0.30 if (k % 2 == 0) else 0.275)
        g.step(0.5, i_each, i_each, True, True, k * 1e-3)
        if g.state.closed_loop_mode != prev_mode:
            transitions += 1
        prev_mode = g.state.closed_loop_mode
    assert transitions == 0


def test_open_to_closed_reseed_from_r_prev_not_0p5():
    g = gm.GovernorModel(seed_r=0.5)
    # Force a nonstandard r_prev while still open-loop. Command the SAME
    # setpoint (0.7) so the open-loop feedforward walk does not itself slew
    # r_prev away from 0.7 before closed-loop mode engages -- otherwise the
    # reseed value would be confounded with the feedforward's own motion.
    g.state.r_prev = 0.7
    g.state.handoff_prev_ratio = 0.7
    g.state.ctrl_out = 0.5  # deliberately mismatched, to prove reseed happens
    for k in range(400):
        out = g.step(0.7, 0.35, 0.35, True, True, k * 1e-3)
        if g.state.closed_loop_mode:
            break
    assert g.state.closed_loop_mode is True
    # The reseed happens on the tick closed_loop_mode flips; ctrl_out must have
    # been set to r_prev (~0.7, the physically-applied ratio), not the stale 0.5.
    assert g.state.ctrl_out == pytest.approx(0.7, abs=0.05)


# ─────────────────────────────────────────────────────────────────────────────
# Open-loop HOLD / feedforward re-arm
# ─────────────────────────────────────────────────────────────────────────────
def test_open_loop_hold_no_write_on_unchanged_setpoint():
    g = gm.GovernorModel(seed_r=0.5)
    # First closed-loop-run tick to set closed_loop_run True, then drop to
    # min-load-safe-but-open-loop territory is awkward; instead directly probe
    # the open-loop branch by keeping total under the entry threshold and
    # issuing the SAME setpoint repeatedly after one feedforward tick.
    out1 = g.step(0.5, 0.1, 0.1, True, True, 0.0)
    assert out1.mode == gm.MODE_OPEN_FF
    r_after_ff = g.state.r_prev
    g.state.closed_loop_run = True
    g.state.acted_sp = 0.5
    out2 = g.step(0.5, 0.1, 0.1, True, True, 1e-3)
    assert out2.mode == gm.MODE_OPEN_HOLD
    assert g.state.r_prev == pytest.approx(r_after_ff), "HOLD must not write"


def test_open_loop_setpoint_change_rearms_feedforward():
    g = gm.GovernorModel(seed_r=0.5)
    g.step(0.5, 0.1, 0.1, True, True, 0.0)
    g.state.closed_loop_run = True
    g.state.acted_sp = 0.5
    out = g.step(0.6, 0.1, 0.1, True, True, 1e-3)
    assert out.mode == gm.MODE_OPEN_FF
    assert g.state.closed_loop_run is False


def test_open_loop_outstanding_iso_rearms_without_clearing_closed_loop_run():
    g = gm.GovernorModel(seed_r=0.5)
    g.step(0.5, 0.1, 0.1, True, True, 0.0)
    g.state.closed_loop_run = True
    g.state.acted_sp = 0.5
    # The claim must be genuine (switch actually LOW), else the self-heal at
    # the top of _setpoint_cutoff() drops it as orphaned before the open-loop
    # branch ever sees it (.ino:9801-9817 self-heal, ported verbatim).
    g.state.iso_fc = True
    out = g.step(0.5, 0.1, 0.1, False, True, 1e-3)  # unchanged setpoint, FC dark
    assert out.mode == gm.MODE_OPEN_FF, \
        "an outstanding iso claim must re-arm feedforward even with sp unchanged"
    assert g.state.closed_loop_run is True, \
        "iso-outstanding re-arm must not clear closed_loop_run (only sp_changed does)"


def test_f1_out_of_band_setpoint_open_loop_not_actuated():
    g = gm.GovernorModel(seed_r=0.5)
    r0 = g.state.r_prev
    # A single-sourced bus (sw_bt False) blocks the setpoint-latch's cut ENTRY
    # (the "last source" guard requires both switches high), so this out-of-
    # band setpoint reaches the open-loop dispatch instead of the latch --
    # isolating the F1 mechanism from the latch that would otherwise own it.
    out = g.step(0.05, 0.1, 0.1, True, False, 0.0)  # below DROOP_R_MIN
    # F1 has its OWN mode (MODE_OPEN_F1_IDLE), distinct from MODE_OPEN_FF, so a
    # mode census cannot mistake this idle tick for actuation.
    assert out.mode == gm.MODE_OPEN_F1_IDLE
    assert out.wrote is False
    assert g.state.r_prev == pytest.approx(r0), "F1: no write for out-of-band OL setpoint"


# ─────────────────────────────────────────────────────────────────────────────
# Setpoint latch (updateShareSetpointCutoff)
# ─────────────────────────────────────────────────────────────────────────────
def test_setpoint_latch_cuts_only_with_both_switches_high():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.r_prev = 0.5
    # sw_bt False -> "last source" guard blocks the cut path entirely.
    out = g.step(0.05, 0.1, 0.1, False, True, 0.0)
    assert g.state.sp_cut_fc is False and g.state.sp_cut_bt is False
    assert out.mode != gm.MODE_LATCHED


def test_setpoint_latch_deferred_when_doomed_channel_over_handoff():
    g = gm.GovernorModel(seed_r=0.5)
    cut = gm.GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]
    # sp < R_MIN wants to cut FC; FC carrying more than the handoff ceiling.
    out = g.step(0.05, cut + 0.3, 0.1, True, True, 0.0)
    assert g.state.deferred_fc is True
    assert g.state.sp_cut_fc is False
    assert g.state.refused_load == 1


def test_setpoint_latch_refused_inside_survivor_blank_window():
    g = gm.GovernorModel(seed_r=0.5)
    blank = gm.GOV_CONST["SHARE_CUT_SURVIVOR_BLANK_MS"]
    # BT (the survivor for an FC cut) just rose at t=0ms.
    g._write_switch("BT", True, 0.0)
    g._write_switch("FC", True, 0.0)
    g.state.sw_init = True
    out = g.step(0.05, 0.1, 0.1, True, True, blank / 1000.0 / 2.0)  # inside window
    assert g.state.sp_cut_fc is False
    assert g.state.refused_blank == 1


def test_setpoint_latch_releases_only_in_band_with_hysteresis():
    g = gm.GovernorModel(seed_r=0.5)
    # Force the latch directly by issuing an out-of-band setpoint at standstill
    # current (small enough to pass the handoff guard) with both switches high.
    g.step(0.05, 0.1, 0.1, True, True, 0.0)
    assert g.state.sp_cut_fc is True
    r_min = gm.GOV_CONST["DROOP_R_MIN"]
    # A setpoint still below R_MIN must not release.
    out = g.step(r_min - 0.01, 0.1, 0.1, False, True, 1e-3)
    assert g.state.sp_cut_fc is True
    assert out.mode == gm.MODE_LATCHED
    # A setpoint at/above R_MIN releases (release path uses sp >= R_MIN, not
    # R_MIN + hyst -- CLAUDE.md/.ino:9827 "sp >= _R_MIN"). Confirm mechanism
    # fired via v_bus_ok gating + switch closing.
    out2 = g.step(r_min, 0.1, 0.1, False, True, 2e-3)
    assert g.state.sp_cut_fc is False
    assert g.state.sw_fc is True


def test_setpoint_latch_freezes_loop_while_latched():
    g = gm.GovernorModel(seed_r=0.5)
    g.step(0.05, 0.1, 0.1, True, True, 0.0)
    assert g.state.sp_cut_fc is True
    filt_before = g.state.filt_total
    out = g.step(0.05, 5.0, 5.0, False, True, 1e-3)  # large current, still latched
    assert out.mode == gm.MODE_LATCHED
    assert g.state.filt_total == pytest.approx(filt_before), \
        "the governor load filter must not advance while latched"


# ─────────────────────────────────────────────────────────────────────────────
# r-based cut twin (applyShareRatio) + fw v25 controller-only clip
# ─────────────────────────────────────────────────────────────────────────────
def test_r_based_cut_load_guard():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.sw_fc = True
    g.state.sw_bt = True
    cut = gm.GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]
    ok, rl, rb = g._apply_share_ratio(0.05, cut + 0.3, 0.1, 0.0,
                                       from_controller=True)
    assert rl is True
    assert g.state.iso_fc is False, "load-guarded cut must not actually isolate"


def test_r_based_cut_survivor_blank_guard():
    g = gm.GovernorModel(seed_r=0.5)
    blank = gm.GOV_CONST["SHARE_CUT_SURVIVOR_BLANK_MS"]
    g.state.sw_fc = True
    g._write_switch("BT", True, 0.0)  # BT (the survivor of an FC cut) just rose
    ok, rl, rb = g._apply_share_ratio(0.05, 0.1, 0.1, blank / 2.0,
                                       from_controller=True)
    assert rb is True
    assert g.state.iso_fc is False


def test_r_based_refused_cut_band_edge_clip_controller_path_only():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.r_prev = gm.GOV_CONST["DROOP_R_MIN"] + 0.05
    g.state.sw_fc = True
    g.state.sw_bt = True
    cut = gm.GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]
    slew = g.state.slew_step
    # Controller path: refused load -> clip lands within slew of r_prev, at the
    # band edge side (constrain toward DROOP_R_MIN).
    ok, rl, rb = g._apply_share_ratio(gm.GOV_CONST["DROOP_R_MIN"] - 0.2,
                                       cut + 0.3, 0.1, 0.0, from_controller=True)
    assert rl is True
    expected = max(gm.GOV_CONST["DROOP_R_MIN"] + 0.05 - slew,
                    gm.GOV_CONST["DROOP_R_MIN"])
    assert g.state.r_prev == pytest.approx(expected, abs=1e-9)


def test_one_shot_write_lands_exactly_at_band_edge_not_clipped():
    # Same refusal, but from_controller=False (a State-98 one-shot / operator
    # write): the fw v25 clip is controller-path-only, so the write lands at
    # the constrained ratio itself, not slew-limited toward r_prev.
    g = gm.GovernorModel(seed_r=0.5)
    g.state.r_prev = gm.GOV_CONST["DROOP_R_MIN"] + 0.05
    g.state.sw_fc = True
    g.state.sw_bt = True
    cut = gm.GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]
    ok, rl, rb = g._apply_share_ratio(gm.GOV_CONST["DROOP_R_MIN"] - 0.2,
                                       cut + 0.3, 0.1, 0.0, from_controller=False)
    assert rl is True
    assert g.state.r_prev == pytest.approx(gm.GOV_CONST["DROOP_R_MIN"], abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Slew mode (updateShareSlewMode)
# ─────────────────────────────────────────────────────────────────────────────
def test_handoff_rate_selected_while_channel_dark():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.dark_fc = True
    g.state.dark_bt = False
    g._slew_mode(0.0, 0.4)
    assert g.state.slew_step == pytest.approx(
        gm.GOV_CONST["DROOP_RATIO_SLEW_HANDOFF_PER_TICK"])


def test_dwell_cap_consumed_only_on_motion():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.dark_fc = True
    g.state.dark_bt = False
    g.state.handoff_i_fc_filt = 0.0
    g.state.handoff_i_bt_filt = 0.4
    # Static hold: r_prev never changes across many ticks.
    g.state.r_prev = 0.5
    g.state.handoff_prev_ratio = 0.5
    for _ in range(300):
        g._slew_mode(0.0, 0.4)
    assert g.state.handoff_dwell == 0, "a static hold must not spend the dwell cap"

    # Now simulate real motion each tick.
    g2 = gm.GovernorModel(seed_r=0.5)
    g2.state.dark_fc = True
    g2.state.dark_bt = False
    g2.state.handoff_i_fc_filt = 0.0
    g2.state.handoff_i_bt_filt = 0.4
    r = 0.5
    for _ in range(GOV_MAX_TICKS := gm.GOV_CONST["SHARE_HANDOFF_DWELL_MAX_TICKS"] + 5):
        g2.state.r_prev = r
        g2._slew_mode(0.0, 0.4)
        r += 0.001  # actual motion each tick
    assert g2.state.handoff_dwell >= gm.GOV_CONST["SHARE_HANDOFF_DWELL_MAX_TICKS"]
    assert g2.state.slew_step == pytest.approx(
        gm.GOV_CONST["DROOP_RATIO_SLEW_PER_TICK"]), \
        "full rate must be restored once the dwell cap is exhausted"


def test_handoff_allowance_rearms_only_via_live_threshold():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.dark_fc = True
    g.state.dark_bt = False
    g.state.handoff_i_fc_filt = gm.GOV_CONST["SHARE_HANDOFF_LIVE_A"] - 0.01
    g._slew_mode(gm.GOV_CONST["SHARE_HANDOFF_LIVE_A"] - 0.01, 0.4)
    # Below LIVE: still dark, dwell continues to be trackable (not re-armed).
    assert g.state.dark_fc is True
    # Cross LIVE threshold via the EMA -- feed enough live current for several
    # ticks so the filter actually crosses.
    for _ in range(50):
        g._slew_mode(1.0, 0.4)
    assert g.state.dark_fc is False, "channel must go live once filtered current >= LIVE"
    # And going dark again requires dropping below SHARE_HANDOFF_MIN_A, not LIVE.
    for _ in range(200):
        g._slew_mode(0.0, 0.4)
    assert g.state.dark_fc is True


# ─────────────────────────────────────────────────────────────────────────────
# Governor clip in closed loop
# ─────────────────────────────────────────────────────────────────────────────
def test_governor_clip_lo_equals_minority_over_filtered_total():
    r_max = gm.GOV_CONST["DROOP_R_MAX"]  # 0.85, the top of the legal in-band span
    g = gm.GovernorModel(seed_r=0.5)
    for k in range(400):
        g.step(r_max, 0.35, 0.35, True, True, k * 1e-3)
    assert g.state.closed_loop_mode is True
    lo_expected = gm.GOV_CONST["SHARE_MINORITY_I_MIN_A"] / g.state.filt_total
    hi_expected = 1.0 - min(lo_expected, 0.5)
    # An in-band request at DROOP_R_MAX sits above the minority-governor's hi
    # ceiling (since I_MINORITY/filt_total > 1 - DROOP_R_MAX here), so sp_eff
    # slews toward and settles at that ceiling.
    assert hi_expected < r_max
    for k in range(400, 2400):
        g.step(r_max, 0.35, 0.35, True, True, k * 1e-3)
    assert g.state.sp_eff_prev == pytest.approx(hi_expected, abs=1e-3)


def test_governor_clip_lo_greater_than_half_clamped():
    g = gm.GovernorModel(seed_r=0.5)
    # Very small filtered total -> lo = MINORITY/filt_total >> 0.5.
    g.state.closed_loop_mode = True
    g.state.filt_total = gm.GOV_CONST["SHARE_MINORITY_I_MIN_A"] * 0.1
    out = g._closed_loop(0.5, 0.05, 0.05, 0.1, 0.0)
    # sp_eff_prev must land clipped to [0.5, 0.5] (lo clamped to 0.5, hi=0.5).
    assert 0.499 <= g.state.sp_eff_prev <= 0.501


def test_effective_setpoint_slew_limited():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.closed_loop_mode = True
    g.state.filt_total = 1.0
    g.state.sp_eff_prev = 0.5
    slew = g.state.slew_step
    g._closed_loop(0.9, 0.5, 0.5, 1.0, 0.0)
    assert g.state.sp_eff_prev == pytest.approx(0.5 + slew, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Self-heal
# ─────────────────────────────────────────────────────────────────────────────
def test_self_heal_orphaned_iso_claim_dropped():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.iso_fc = True
    g.state.sw_fc = False
    g.step(0.5, 0.1, 0.1, True, True, 0.0)  # observed sw_fc HIGH this tick
    assert g.state.iso_fc is False


def test_self_heal_orphaned_sp_cut_claim_dropped():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.sp_cut_fc = True
    g.state.iso_fc = True
    g.state.sw_fc = False
    g.step(0.5, 0.1, 0.1, True, True, 0.0)  # switch re-closed by someone else
    assert g.state.sp_cut_fc is False
    assert g.state.iso_fc is False


# ─────────────────────────────────────────────────────────────────────────────
# delivered_share / dV0 law
# ─────────────────────────────────────────────────────────────────────────────
def test_delivered_share_cut_channels():
    g = gm.GovernorModel()
    assert g.delivered_share(0.5, 1.0, False, True) == 0.0
    assert g.delivered_share(0.5, 1.0, True, False) == 1.0
    assert g.delivered_share(0.5, 1.0, False, False) == 0.0


def test_delivered_share_dv0_law_hand_computed():
    g = gm.GovernorModel(dv0_v=0.05, k_droop=0.30)
    r = 0.4
    i_tot = 1.0
    expected = r + 0.05 * r * (1.0 - r) / (0.30 * i_tot)
    got = g.delivered_share(r, i_tot, True, True)
    assert got == pytest.approx(expected, rel=1e-12)


def test_delivered_share_inverse_consistent_at_nonzero_dv0():
    g = gm.GovernorModel(dv0_v=0.05, k_droop=0.30)
    i_tot = 1.2
    r = 0.6
    alpha = g.delivered_share(r, i_tot, True, True)
    r_back = g._ratio_for_delivered(alpha, i_tot)
    assert r_back == pytest.approx(r, abs=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Negative / validation
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kwargs", [
    dict(dt_s=0.0), dict(dt_s=-1.0),
    dict(seed_r=-0.1), dict(seed_r=1.1),
    dict(k_droop=0.0), dict(k_droop=-0.1),
    dict(conv_tau_s=-1.0),
])
def test_invalid_constructor_args_raise(kwargs):
    with pytest.raises(ValueError):
        gm.GovernorModel(**kwargs)


def test_replay_governor_blank_steps_skip_and_do_not_score():
    lu = gm.GOV_CONST["MDAC_CMD_LOAD_UPDATE"]
    word = str(lu | 0x800)
    rows = [
        {"t": "0.0", "cmd_share_sp": "0.5", "I_fc": "", "I_batt": "0.1",
         "switch": "3", "mdac_fc": word, "mdac_bt": word, "state": "2"},
        {"t": "0.001", "cmd_share_sp": "0.5", "I_fc": "0.1", "I_batt": "0.1",
         "switch": "3", "mdac_fc": word, "mdac_bt": word, "state": "2"},
    ]
    res = gm.replay_governor(rows)
    assert res["n"] == 1, "the blank I_fc row must be skipped entirely"


def test_replay_governor_blank_state_rows_not_ticked_by_default_step_states():
    # `step_states` (default (2, 98)) gates whether the model is TICKED at
    # all -- a blank/unparseable state is not in that set, so these rows are
    # skipped upstream of scoring entirely (n stays 0, not just n_scored).
    rows = []
    r = 0.5
    for k in range(5):
        code = gm._mdac_code(gm.GOV_CONST["K_DROOP"] /
                              (gm.GOV_CONST["RE_MAX"] * r))
        rows.append({
            "t": str(k * 1e-3), "cmd_share_sp": "0.5",
            "I_fc": "0.3", "I_batt": "0.3", "switch": "3",
            "mdac_fc": str(code), "mdac_bt": str(code),
            "state": "",  # no state recorded
        })
    res = gm.replay_governor(rows, state_filter=2)
    assert res["n"] == 0
    assert res["n_scored"] == 0
    assert math.isnan(res["rms"])


def test_replay_governor_step_states_none_ticks_unconditionally():
    # `step_states=None` restores unconditional ticking regardless of state,
    # so the same blank-state rows above ARE now ticked (n advances) even
    # though they still cannot be SCORED under state_filter=2 (state != 2).
    rows = []
    r = 0.5
    for k in range(5):
        code = gm._mdac_code(gm.GOV_CONST["K_DROOP"] /
                              (gm.GOV_CONST["RE_MAX"] * r))
        rows.append({
            "t": str(k * 1e-3), "cmd_share_sp": "0.5",
            "I_fc": "0.3", "I_batt": "0.3", "switch": "3",
            "mdac_fc": str(code), "mdac_bt": str(code),
            "state": "",  # no state recorded
        })
    res = gm.replay_governor(rows, state_filter=2, step_states=None)
    assert res["n"] == 5
    assert res["n_scored"] == 0
    assert math.isnan(res["rms"])


def test_replay_governor_scored_rows_excluded_by_state_filter_mismatch():
    # Rows in an admitted TICK state (Run, "2") but whose state does not
    # match the SCORING filter (here state_filter=98, Test) are ticked
    # (n advances) but never scored (n_scored stays 0) -- the two gates
    # (step_states vs state_filter) act at different points in the pipeline.
    rows = []
    r = 0.5
    for k in range(5):
        code = gm._mdac_code(gm.GOV_CONST["K_DROOP"] /
                              (gm.GOV_CONST["RE_MAX"] * r))
        rows.append({
            "t": str(k * 1e-3), "cmd_share_sp": "0.5",
            "I_fc": "0.3", "I_batt": "0.3", "switch": "3",
            "mdac_fc": str(code), "mdac_bt": str(code),
            "state": "2",
        })
    res = gm.replay_governor(rows, state_filter=98)
    assert res["n"] == 5
    assert res["n_scored"] == 0
    assert math.isnan(res["rms"])


# ─────────────────────────────────────────────────────────────────────────────
# replay_governor smoke against a short synthetic row list
# ─────────────────────────────────────────────────────────────────────────────
def test_replay_governor_smoke_synthetic_rows_constant_ratio_is_unscored():
    # A constant observed ratio never MOVES, so this run is agreement with a
    # constant -- the module's own vacuity guard must report it as such rather
    # than as evidence of tracking.
    rows = []
    r = 0.5
    k_droop = gm.GOV_CONST["K_DROOP"]
    re_max = gm.GOV_CONST["RE_MAX"]
    for k in range(200):
        code_fc = gm._mdac_code(k_droop / (re_max * r))
        code_bt = gm._mdac_code(k_droop / (re_max * (1.0 - r)))
        rows.append({
            "t": str(k * 1e-3), "cmd_share_sp": "0.5",
            "I_fc": "0.35", "I_batt": "0.35", "switch": "3",
            "mdac_fc": str(code_fc), "mdac_bt": str(code_bt), "state": "2",
        })
    res = gm.replay_governor(rows)
    assert res["n"] == 200
    assert res["n_scored"] > 0
    assert res["rms"] < 0.05
    assert res["n_moving"] == 0
    assert res["verdict"] == "UNSCORED"
    assert math.isnan(res["rms_moving"])


def test_replay_governor_smoke_synthetic_rows_moving_ratio_is_scored():
    # A ramping observed ratio (a real minority-current-governor style walk
    # from 0.5 toward 0.6) DOES move, so the run must be marked SCORED and
    # rms_moving must be a real (non-NaN) figure.
    rows = []
    k_droop = gm.GOV_CONST["K_DROOP"]
    re_max = gm.GOV_CONST["RE_MAX"]
    for k in range(400):
        r = 0.5 + min(0.001 * k, 0.1)
        code_fc = gm._mdac_code(k_droop / (re_max * r))
        code_bt = gm._mdac_code(k_droop / (re_max * (1.0 - r)))
        rows.append({
            "t": str(k * 1e-3), "cmd_share_sp": "0.6",
            "I_fc": "0.35", "I_batt": "0.35", "switch": "3",
            "mdac_fc": str(code_fc), "mdac_bt": str(code_bt), "state": "2",
        })
    res = gm.replay_governor(rows)
    assert res["n"] == 400
    assert res["n_moving"] > 0
    assert res["verdict"] == "SCORED"
    assert not math.isnan(res["rms_moving"])
    assert res["n_scored_moving_window"] > 0


_STAIRCASE_LOG_DIR = os.path.join(
    REPO_ROOT, "HIL Results", "hil_report_20260901_080905")


def test_replay_governor_against_real_campaign_if_present():
    path = os.path.join(_STAIRCASE_LOG_DIR,
                         "scenario_share-staircase_hifi", "events.csv")
    if not os.path.isfile(path):
        pytest.skip("HIL Results campaign log not present (gitignored, local-only)")
    res = gm.replay_csv(path)
    assert res["n_scored"] > 0
    assert res["rms"] < 0.02


# ─────────────────────────────────────────────────────────────────────────────
# charge_path_owns_bt / _charge_path_claim_bt (assertFcChargeEnable() ownership
# override, .ino:9260-9286)
# ─────────────────────────────────────────────────────────────────────────────
def test_charge_path_claim_bt_drives_bt_low_and_clears_bt_claims():
    g = gm.GovernorModel(seed_r=0.5)
    g.state.sw_bt = True
    g.state.iso_bt = False
    g.state.sp_cut_bt = False
    out = g.step(0.5, 0.1, 0.1, True, True, 0.0, charge_path_owns_bt=True)
    assert g.state.sw_bt is False, \
        "the charge path must drive BT_BUS low unconditionally"
    assert g.state.iso_bt is False
    assert g.state.sp_cut_bt is False


def test_charge_path_claim_bt_restores_fc_when_share_loop_held_it_off():
    g = gm.GovernorModel(seed_r=0.5)
    # FC held off by the share loop's own claim (not the charge path's).
    g.state.sw_fc = False
    g.state.iso_fc = True
    g.state.sp_cut_fc = True
    g.step(0.5, 0.1, 0.1, False, True, 0.0, charge_path_owns_bt=True)
    assert g.state.sw_fc is True, \
        "S2 ordering: FC restored before BT is cut, when the share loop held it"
    assert g.state.iso_fc is False
    assert g.state.sp_cut_fc is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_the_setpoint_cut_port_covers_both_directions_and_both_guards():
    """THE PORT THE MPC's SINGLE-SOURCE CANDIDATES WILL DEPEND ON.

    The MPC is to gain 0 and 1 commands as candidates (operator ruling,
    2026-09-02), and those go through the firmware's setpoint latch rather than
    through the share loop.  Before that work can be scheduled the port has to
    be known to cover the firmware's whole sequence, in BOTH directions, with
    the fw v25 guards.  This test is that verification, asserted through
    behaviour rather than by reading the source.

    Four properties, each one a thing a partial port would get wrong."""
    C = gm.GOV_CONST
    cut = C["SHARE_CUT_MAX_HANDOFF_A"]

    def _fresh():
        g = gm.GovernorModel(dt_s=1e-3, seed_r=0.5)
        g.v_bus_ok = True
        return g

    # 1. THE LOAD GUARD REFUSES a cut whose doomed channel is carrying current,
    #    and COUNTS the refusal.  This is the fw v25 guard, and it is the one
    #    the MPC's feasibility test has to respect.
    g = _fresh()
    for k in range(50):
        g.step(0.05, 2.0, 0.2, True, True, k * 1e-3)   # sp below the rail, FC hot
    assert g.state.sp_cut_fc is False, "a cut was taken over a hot channel"
    assert g.state.refused_load > 0, "the refusal was not counted"

    # 2. ... AND ALLOWS it once that channel is under the guard.
    g = _fresh()
    for k in range(50):
        g.step(0.05, 0.5 * cut, 0.9, True, True, k * 1e-3)
    assert g.state.sp_cut_fc is True, "a legal cut was refused"

    # 3. THE RESTORE PATH exists and clears the latch when the setpoint comes
    #    back in band -- a port with only the cut would leave it latched.
    for k in range(50, 120):
        g.step(0.5, 0.0, 0.9, False, True, k * 1e-3)
    assert g.state.sp_cut_fc is False, "the latch never released"

    # 4. THE SLEW CONSTANT the restore runs at is the firmware's, and is what a
    #    candidate's rollout must carry across a restore.
    assert C["DROOP_RATIO_SLEW_HANDOFF_PER_TICK"] == 0.002
    assert C["SHARE_CUT_SURVIVOR_BLANK_MS"] == 30.0


# ─────────────────────────────────────────────────────────────────────────────
# fw v26 — source current-ceiling governor
#
# The FIRMWARE-EQUIVALENCE evidence for the clamp lives in
# tools/test_governor_ceiling_equivalence.py, which drives the real
# applyShareCurrentCeilings() and this port through one scripted sequence. The
# tests below assert the things that file cannot: the constants' relation to
# the fault limits, the reachability threshold as a WHOLE-LOOP property, and
# the clamp's interaction with the rest of powerBalance().
# ─────────────────────────────────────────────────────────────────────────────
def test_ceiling_constants_sit_below_their_fault_limits(ino_text):
    """The four firmware static_asserts, re-asserted against the live
    constants. A ceiling at or above its fault limit would make the clamp chase
    a latch it can never beat."""
    C = gm.GOV_CONST
    m_fc = re.search(r"#define\s+LIMIT_I_FC_MAX\s+([0-9.]+)f", ino_text)
    m_bt = re.search(r"#define\s+LIMIT_I_BT_MAX\s+([0-9.]+)f", ino_text)
    assert m_fc and m_bt, "could not find the two fault limits in the firmware"
    lim_fc, lim_bt = float(m_fc.group(1)), float(m_bt.group(1))
    assert C["SHARE_GOV_I_FC_CEIL_A"] < lim_fc
    assert C["SHARE_GOV_I_BT_CEIL_A"] < lim_bt
    # Each ceiling above the light-load conduction floor, so a ceiling can never
    # demand a channel current below it. This is what makes the minority clip
    # and the ceiling clamp provably non-conflicting.
    assert C["SHARE_GOV_I_FC_CEIL_A"] > C["SHARE_MINORITY_I_MIN_A"]
    assert C["SHARE_GOV_I_BT_CEIL_A"] > C["SHARE_MINORITY_I_MIN_A"]
    # The release hysteresis stays inside the fuel-cell margin, so a released
    # clamp is still under the fault limit.
    assert C["SHARE_GOV_CEIL_HYST_A"] < lim_fc - C["SHARE_GOV_I_FC_CEIL_A"]


def test_reachability_threshold_is_1p55_a_through_the_whole_loop():
    """1.55 A of TWO-SOURCE total is the governing number for this feature.

    Asserted through step(), not through the clamp alone, because the threshold
    is a property of the ORDER: the minority-current clip caps the commanded
    fuel-cell fraction at 1 - SHARE_MINORITY_I_MIN_A/I_tot, and only that cap
    puts the first engagement at I_FC_CEIL + I_MINORITY rather than at
    I_FC_CEIL / DROOP_R_MAX = 1.47 A."""
    assert gm.CEILING_REACHABLE_I_TOT_A == pytest.approx(1.55, abs=1e-12)

    def first_engagement(sp):
        tot = 1.40
        while tot <= 2.20:
            g = gm.GovernorModel(dt_s=1e-3, seed_r=0.5)
            d = 0.5
            for k in range(3000):
                i_fc = d * tot
                o = g.step(sp, i_fc, tot - i_fc, True, True, k * 1e-3)
                d = g.delivered_share(o.r_applied, tot, o.fc_bus_req,
                                      o.bt_bus_req)
                if o.ceil_fc:
                    return tot
            tot = round(tot + 0.05, 4)
        return None

    at = first_engagement(gm.GOV_CONST["DROOP_R_MAX"])
    assert at is not None, "the clamp never engaged up to 2.20 A"
    assert at >= 1.55 - 1e-9, ("engaged at %.4f A, below the 1.55 A "
                               "reachability threshold" % at)
    assert at <= 1.60 + 1e-9, ("engaged at %.4f A, more than one 0.05 A sweep "
                               "step above 1.55 A" % at)


def test_clamp_is_inert_and_bit_identical_below_the_ceilings():
    """fw v26 is arithmetically identical to fw v25 below the ceilings. Two
    identical runs at a total under the threshold must produce the same MDAC
    codes and never raise a flag."""
    def run(tot, sp):
        g = gm.GovernorModel(dt_s=1e-3, seed_r=0.5)
        d = 0.5
        codes = []
        flags = 0
        for k in range(2000):
            i_fc = d * tot
            o = g.step(sp, i_fc, tot - i_fc, True, True, k * 1e-3)
            d = g.delivered_share(o.r_applied, tot, o.fc_bus_req, o.bt_bus_req)
            codes.append((o.code_fc, o.code_bt))
            flags += int(o.ceil_fc or o.ceil_bt)
        return codes, flags, g.state.ceil_ticks

    codes_a, flags_a, ticks_a = run(1.20, 0.85)
    codes_b, flags_b, ticks_b = run(1.20, 0.85)
    assert codes_a == codes_b
    assert flags_a == 0 and flags_b == 0
    assert ticks_a == 0 and ticks_b == 0


def test_clamp_holds_the_fuel_cell_at_the_ceiling_and_the_battery_takes_it():
    """The mechanism, stated as a measurement: at 2.0 A of two-source total and
    a commanded share of 0.75 the unclamped fuel-cell demand is 1.50 A. The
    clamp must hold the delivered fuel-cell current at the ceiling and put the
    remaining 0.75 A on the battery."""
    tot = 2.0
    g = gm.GovernorModel(dt_s=1e-3, seed_r=0.5)
    d = 0.5
    for k in range(4000):
        i_fc = d * tot
        o = g.step(0.75, i_fc, tot - i_fc, True, True, k * 1e-3)
        d = g.delivered_share(o.r_applied, tot, o.fc_bus_req, o.bt_bus_req)
    assert o.ceil_fc is True and o.ceil_bt is False
    i_fc = d * tot
    assert i_fc == pytest.approx(gm.GOV_CONST["SHARE_GOV_I_FC_CEIL_A"],
                                 abs=1e-3)
    assert tot - i_fc == pytest.approx(0.75, abs=1e-3)
    # And the clamp never opened a bus switch.
    assert o.fc_bus_req and o.bt_bus_req
    assert gm.GOV_CONST["DROOP_R_MIN"] <= o.r_applied \
        <= gm.GOV_CONST["DROOP_R_MAX"]
    assert g.ceiling_fraction() > 0.5


def test_clamp_state_is_dropped_on_the_minimum_load_return():
    """A frozen loop is by definition not clamping anything. Leaving a flag set
    would publish a stale clamp on all three observables for as long as the
    freeze lasts."""
    tot = 2.0
    g = gm.GovernorModel(dt_s=1e-3, seed_r=0.5)
    d = 0.5
    for k in range(3000):
        i_fc = d * tot
        o = g.step(0.75, i_fc, tot - i_fc, True, True, k * 1e-3)
        d = g.delivered_share(o.r_applied, tot, o.fc_bus_req, o.bt_bus_req)
    assert o.ceil_fc is True, "the fixture never clamped"

    o2 = g.step(0.75, 0.01, 0.01, True, True, 3.0)
    assert o2.mode == gm.MODE_FROZEN
    assert o2.ceil_fc is False and o2.ceil_bt is False
    assert g.state.gov_fc_clamped is False


def test_clamp_is_suppressed_while_a_deferred_cut_owns_the_setpoint():
    """One owner per tick. A deferral has parked the reference on a band edge
    to starve a doomed channel, and the fuel-cell ceiling would claw it back
    off that edge. The clamp is suppressed and its flags dropped."""
    g = gm.GovernorModel(dt_s=1e-3, seed_r=0.5)
    tot = 2.0
    # An out-of-band setpoint with the DOOMED channel hot. The doomed channel
    # for sp > DROOP_R_MAX is the BATTERY, so the battery must be the one
    # carrying more than SHARE_CUT_MAX_HANDOFF_A for the cut to be refused on
    # load and the deferral to stand.
    o = None
    for k in range(200):
        o = g.step(0.95, 0.25 * tot, 0.75 * tot, True, True, k * 1e-3)
    assert g.state.deferred_bt is True, "the fixture never deferred"
    assert g.state.gov_fc_clamped is False and g.state.gov_bt_clamped is False
    assert o.ceil_fc is False and o.ceil_bt is False


def test_ceiling_bounded_share_is_the_converged_image_of_the_dynamic_clamp():
    """The demand models use the hysteresis-free helper. It must agree with the
    dynamic port wherever the dynamic port has converged, which is the only
    regime a stage-level demand model claims to describe.

    ⚠️ THE TOTALS ARE AT OR ABOVE CEILING_REACHABLE_I_TOT_A, and that is the
    contract rather than a convenience. The dynamic port is entered from
    `step()` only AFTER the minority-current clip has run, so its caller
    guarantees the total is one at which the clamp can act. The scalar helper
    has no such caller and carries the reachability threshold itself; below it
    the two DELIBERATELY differ, and
    `test_ceiling_bounded_share_is_the_identity_below_the_threshold` pins that
    difference."""
    for tot in (gm.CEILING_REACHABLE_I_TOT_A, 1.6, 2.0, 2.5, 3.0, 4.0, 4.4,
                6.0):
        for sp in (0.15, 0.25, 0.5, 0.75, 0.85):
            g = gm.GovernorModel(dt_s=1e-3)
            g.state.filt_total = tot
            got = None
            for _ in range(5):
                got = g._apply_share_current_ceilings(sp)
            assert got == pytest.approx(gm.ceiling_bounded_share(sp, tot),
                                        abs=1e-12), (tot, sp)


def test_ceiling_bounded_share_is_the_identity_below_the_threshold():
    """THE REACHABILITY GUARD, on the scalar helper the demand models call.

    Below 1.55 A of two-source total the board's minority-current clip has
    already capped the commanded fuel-cell current under the 1.25 A ceiling, so
    no clamp occurs and the helper must return its argument. Without this the
    demand models clamped in (1.47, 1.55) -- 250 of `ems-dp-replay`'s 34 827
    cells did, at I_tot 1.47137 A where the board delivers 1.1714 A."""
    naive_onset = gm.GOV_CONST["SHARE_GOV_I_FC_CEIL_A"] / gm.GOV_CONST[
        "DROOP_R_MAX"]
    assert naive_onset < gm.CEILING_REACHABLE_I_TOT_A
    for tot in (0.5, 1.0, 1.2, naive_onset, 1.47137, 1.50,
                gm.CEILING_REACHABLE_I_TOT_A - 1e-9):
        for sp in (0.15, 0.5, 0.75, 0.84, 0.85):
            assert gm.ceiling_bounded_share(sp, tot) == sp, (tot, sp)
    # The threshold itself is live: the guard is a threshold, not an off switch.
    assert gm.ceiling_bounded_share(0.85, gm.CEILING_REACHABLE_I_TOT_A) < 0.85
    # The DYNAMIC port, whose caller owns the clip, still clamps below it --
    # which is why the two helpers must not be assumed interchangeable.
    g = gm.GovernorModel(dt_s=1e-3)
    g.state.filt_total = 1.50
    assert g._apply_share_current_ceilings(0.85) < 0.85


def test_ceiling_bounded_share_resolves_the_infeasible_pair_to_the_fuel_cell():
    """Above I_FC_CEIL + I_BT_CEIL = 3.95 A no split keeps both channels under
    their ceilings. The fuel-cell bound is applied second and must win; the
    commanded battery current is knowingly pushed over its own ceiling, and
    FAULT_OC_BT is the intended latch from 4.25 A of total."""
    C = gm.GOV_CONST
    assert C["SHARE_GOV_I_FC_CEIL_A"] + C["SHARE_GOV_I_BT_CEIL_A"] == \
        pytest.approx(3.95)
    tot = 4.40
    sp = gm.ceiling_bounded_share(0.15, tot)
    assert sp * tot == pytest.approx(C["SHARE_GOV_I_FC_CEIL_A"], abs=1e-9)
    i_bt = (1.0 - sp) * tot
    assert i_bt == pytest.approx(3.15, abs=1e-9)
    assert i_bt > C["SHARE_GOV_I_BT_CEIL_A"]


def test_the_clamp_never_leaves_the_droop_band():
    """A reference outside the band IS the channel-cutoff signal. A current
    ceiling must never open a bus switch, so the constraint is structural."""
    for tot in (1.5, 2.0, 4.0, 8.0, 8.34, 12.0, 40.0):
        for sp in (0.0, 0.15, 0.5, 0.85, 1.0):
            out = gm.ceiling_bounded_share(sp, tot)
            if out != sp:
                assert gm.GOV_CONST["DROOP_R_MIN"] <= out \
                    <= gm.GOV_CONST["DROOP_R_MAX"], (tot, sp, out)


def test_hysteresis_delays_the_release_but_not_the_engagement():
    """The clamp engages when the demand exceeds the ceiling and releases only
    when it falls SHARE_GOV_CEIL_HYST_A below it. Asserted on the clamp
    directly, because the release boundary is the half a converged demand model
    cannot see."""
    C = gm.GOV_CONST
    g = gm.GovernorModel(dt_s=1e-3)
    tot = 2.0
    ceil = C["SHARE_GOV_I_FC_CEIL_A"]
    hyst = C["SHARE_GOV_CEIL_HYST_A"]
    # Just under the ceiling: no engagement.
    g.state.filt_total = tot
    g._apply_share_current_ceilings((ceil - 1e-6) / tot)
    assert g.state.gov_fc_clamped is False
    # Just over: engagement.
    g._apply_share_current_ceilings((ceil + 1e-6) / tot)
    assert g.state.gov_fc_clamped is True
    # Back to a demand inside the hysteresis band: still engaged.
    g._apply_share_current_ceilings((ceil - 0.5 * hyst) / tot)
    assert g.state.gov_fc_clamped is True
    # Below the band: released.
    g._apply_share_current_ceilings((ceil - 1.5 * hyst) / tot)
    assert g.state.gov_fc_clamped is False


def test_an_out_of_band_setpoint_is_never_clamped():
    """THE SETPOINT LATCH OWNS OUT-OF-BAND, NOT THE CEILING CLAMP.

    In the firmware there is no path on which a setpoint outside
    [DROOP_R_MIN, DROOP_R_MAX] reaches applyShareCurrentCeilings(): the latch
    either freezes the whole loop or defers, and the deferral branch suppresses
    the clamp explicitly. A demand model whose share grid spans the full [0, 1]
    -- the stochastic dynamic program's does -- therefore keeps its full-span
    single-source commands intact.

    This was found by a real failure: applying the bound to the SDP solver's
    grid pulled its share-1.0 commands into the droop band and changed the
    shipped policy."""
    for tot in (1.6, 2.0, 4.0, 8.0):
        for sp in (0.0, 0.05, 0.1499, 0.8501, 0.95, 1.0):
            assert gm.ceiling_bounded_share(sp, tot) == sp, (tot, sp)
    # And the band edges themselves ARE clamped, so the gate is a strict
    # out-of-band test and not an off-by-one that disables the clamp at 0.85.
    assert gm.ceiling_bounded_share(0.85, 2.0) < 0.85
