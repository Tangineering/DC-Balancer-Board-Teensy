#!/usr/bin/env python3
"""pytest suite for tools/hil_dashboard.py — the live terminal dashboard for
the HIL plant simulator, plus its wiring into hil_plant_sim.py (--dash) and
run_hil_suite.py (--dashboard).

Independent test-writer pass (Stage 2 of the orchestrated round): written
against the shipped code, not the implementer's own tests.

Run: cd tools && python -m pytest test_hil_dashboard.py -v
"""
import io
import os
import re
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hil_dashboard as hd  # noqa: E402
import hil_plant_sim as hil  # noqa: E402
import hil_replay_suite as hrs  # noqa: E402
import run_hil_suite as rhs  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# 1. Construction / lifecycle
# ─────────────────────────────────────────────────────────────────────────

class _FakeNonTtyStdout(io.StringIO):
    def isatty(self):
        return False


class _FakeTtyStdout(io.StringIO):
    def isatty(self):
        return True


def test_start_on_non_tty_returns_false_and_renders_nothing(monkeypatch):
    fake = _FakeNonTtyStdout()
    monkeypatch.setattr(hd.sys, "stdout", fake)
    dash = hd.Dashboard()
    assert dash.start() is False
    assert dash._thread is None
    assert dash._started is False
    # one explanatory line, printed via the (patched) sys.stdout, not the ANSI writer
    out = fake.getvalue()
    assert "--dash" in out and "not a terminal" in out
    dash.stop()  # must not raise even though start() never succeeded


def test_start_idempotent_returns_true_without_relaunching(monkeypatch):
    fake = _FakeTtyStdout()
    monkeypatch.setattr(hd.sys, "stdout", fake)
    dash = hd.Dashboard(refresh_hz=50.0)
    assert dash.start() is True
    th1 = dash._thread
    assert dash.start() is True
    assert dash._thread is th1  # no second thread spawned
    dash.stop()


def test_stop_idempotent(monkeypatch):
    fake = _FakeTtyStdout()
    monkeypatch.setattr(hd.sys, "stdout", fake)
    dash = hd.Dashboard(refresh_hz=50.0)
    assert dash.start() is True
    dash.stop()
    dash.stop()  # second call must be a safe no-op
    assert dash._thread is None


def test_stop_without_start_is_safe():
    dash = hd.Dashboard()
    dash.stop()  # never started -- must not raise, must not print junk
    dash.stop()


# ─────────────────────────────────────────────────────────────────────────
# 2. Renderer robustness (drive the thread against a captured fake tty)
# ─────────────────────────────────────────────────────────────────────────

def _run_dashboard_tick(monkeypatch, snapshot, refresh_hz=100.0):
    """Start a real Dashboard against a fake tty stdout, feed one snapshot,
    let the daemon thread render at least once, then stop and return
    (captured_text, dash.error)."""
    fake = _FakeTtyStdout()
    monkeypatch.setattr(hd.sys, "stdout", fake)
    dash = hd.Dashboard(refresh_hz=refresh_hz)
    assert dash.start() is True
    dash.snapshot = snapshot
    time.sleep(0.15)  # several render periods at 100 Hz
    dash.stop()
    return fake.getvalue(), dash.error


def test_render_survives_empty_snapshot(monkeypatch):
    text, error = _run_dashboard_tick(monkeypatch, {})
    assert error is None, "renderer must not die on an empty snapshot dict"
    assert "HIL dashboard" in text


def test_render_survives_missing_and_none_keys(monkeypatch):
    """A snapshot with every commonly-absent/None field the real feed can
    produce (share_act/v_sp None at rest, obs-derived fields None before the
    first observation frame, hifi fields None outside hifi mode)."""
    snap = {
        "t": 1.5, "source": "sim", "mode": "simple",
        "rate_hz": None, "tx": 0, "rx": 0, "bad": 0, "pi": 0,
        "v_sp": None, "v_act": None,
        "share_sp": None, "share_act": None,
        "V_bus": None, "I_tot": None, "I_fc": None, "I_bt": None,
        "I_chg": None, "ag105": None, "mppt_cnt": None,
        "state": None, "switch": None, "aux": None,
        "I_cmd": None, "faults": None,
        "hifi_hz": None, "hifi_events": 0, "hifi_chopper_w": None,
    }
    text, error = _run_dashboard_tick(monkeypatch, snap)
    assert error is None
    assert "HIL dashboard" in text


def test_render_survives_obs_none_fields(monkeypatch):
    """The real feed sets state/switch/aux/I_cmd/faults=0 (not None) when
    obs is None, but exercise the None case too since the dict is built by
    hand and a future edit could pass None through."""
    snap = {"t": 0.0, "state": None, "switch": None, "aux": None,
            "I_cmd": None, "faults": None}
    text, error = _run_dashboard_tick(monkeypatch, snap)
    assert error is None
    assert "HIL dashboard" in text


def _wide_terminal(monkeypatch):
    """Several sandboxed/CI stdouts report a near-zero terminal size, which
    the renderer's row-count clamp (max(rows-1, 5)) can shrink to as few as
    5 lines -- dropping even nominally 'always keep' (pri=0) rows past the
    5th. Pin a generous size so these content-specific tests assert on what
    the renderer produces on a normal terminal, not on the row-count clamp
    itself (which has its own dedicated narrow-terminal tests elsewhere)."""
    monkeypatch.setattr(hd.shutil, "get_terminal_size", lambda *_a, **_k: (120, 40))


def test_render_mppt_cnt_shows_count_and_volts(monkeypatch):
    """fw v24 reg-0x02 threshold count: a real count renders as 'N (V.VVV)'
    using AG105_MPPT_VOLTS (11.0 + 0.088*N)."""
    _wide_terminal(monkeypatch)
    text, error = _run_dashboard_tick(monkeypatch, {"mppt_cnt": 20})
    assert error is None
    # 11.0 + 0.088*20 = 12.76
    assert "mpptCnt=20 (12.76V)" in text


def test_render_mppt_cnt_none_is_em_dash(monkeypatch):
    _wide_terminal(monkeypatch)
    text, error = _run_dashboard_tick(monkeypatch, {"mppt_cnt": None})
    assert error is None
    assert "mpptCnt=—" in text


def test_render_mppt_cnt_resistor_mode_is_em_dash(monkeypatch):
    """>=251 (Table 7) is external-resistor mode / never-written, not a real
    threshold count -- must not render as a bogus volts figure."""
    _wide_terminal(monkeypatch)
    text, error = _run_dashboard_tick(monkeypatch, {"mppt_cnt": 255})
    assert error is None
    assert "mpptCnt=—" in text
    text2, error2 = _run_dashboard_tick(monkeypatch, {"mppt_cnt": 251})
    assert error2 is None
    assert "mpptCnt=—" in text2


def test_render_survives_garbage_types_without_propagating(monkeypatch):
    """Deliberately hostile snapshot: wrong types where the renderer expects
    numbers. The lightness contract says the sim must never see an exception
    from this path; the renderer thread must latch dash.error instead of
    crashing silently and pretending nothing happened."""
    snap = {"t": "not-a-number", "faults": "oops", "switch": {}, "state": []}
    fake = _FakeTtyStdout()
    monkeypatch.setattr(hd.sys, "stdout", fake)
    dash = hd.Dashboard(refresh_hz=100.0)
    assert dash.start() is True
    dash.snapshot = snap
    time.sleep(0.15)
    dash.stop()
    # Either it tolerated the garbage (error is None) or it latched an error
    # and stopped cleanly -- either way stop() must not hang/raise, and the
    # test process must still be alive to assert this.
    if dash.error is not None:
        assert isinstance(dash.error, str) and dash.error
    else:
        assert "HIL dashboard" in fake.getvalue()


# ─────────────────────────────────────────────────────────────────────────
# 3. sparkline()
# ─────────────────────────────────────────────────────────────────────────

def test_sparkline_monotone_increasing_maps_to_monotone_levels():
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    s = hd.sparkline(vals)
    idxs = [hd.SPARK_CHARS.index(c) for c in s]
    assert idxs == sorted(idxs)
    assert idxs[0] == 0
    assert idxs[-1] == len(hd.SPARK_CHARS) - 1


def test_sparkline_monotone_decreasing_is_monotone_non_increasing():
    vals = [4.0, 3.0, 2.0, 1.0, 0.0]
    s = hd.sparkline(vals)
    idxs = [hd.SPARK_CHARS.index(c) for c in s]
    assert idxs == sorted(idxs, reverse=True)


def test_sparkline_constant_data_does_not_divide_by_zero():
    s = hd.sparkline([5.0] * 10)
    assert len(s) == 10
    assert all(c == s[0] for c in s)  # flat span -> flat line, no crash


def test_sparkline_empty_history_returns_empty_string():
    assert hd.sparkline([]) == ""
    assert hd.sparkline([None, None, None]) == ""


def test_sparkline_none_gaps_render_as_space_and_preserve_length():
    vals = [None, 1.0, None, 3.0, None]
    s = hd.sparkline(vals)
    assert len(s) == len(vals)
    assert s[0] == " " and s[2] == " " and s[4] == " "
    assert s[1] != " " and s[3] != " "


def test_sparkline_explicit_lo_hi_clips_beyond_range():
    # value below lo and above hi should still clamp into range, not crash
    s = hd.sparkline([-100.0, 0.0, 1.0, 100.0], lo=0.0, hi=1.0)
    assert len(s) == 4
    idxs = [hd.SPARK_CHARS.index(c) for c in s]
    assert idxs[0] == 0                      # clamped to bottom
    assert idxs[-1] == len(hd.SPARK_CHARS) - 1  # clamped to top


# ─────────────────────────────────────────────────────────────────────────
# 4. Fault/state/switch decoding — pinned against the sibling modules
# ─────────────────────────────────────────────────────────────────────────

def test_fault_names_equals_hil_replay_suite_fault_names():
    """The implementer's own comment flags this as an intentional duplicate
    (leaf-module import-cost reasons) that must be kept in lockstep. Pin
    equality as a mapping, independent of dict-vs-tuple representation."""
    dash_map = dict(hd.FAULT_NAMES)
    assert dash_map == hrs.FAULT_NAMES


def test_fault_names_no_duplicate_bits_and_covers_16_bits():
    bits = [bit for bit, _ in hd.FAULT_NAMES]
    assert len(bits) == len(set(bits))
    assert len(hd.FAULT_NAMES) == 16
    assert set(bits) == {1 << i for i in range(16)}


def test_decode_faults_zero_is_none():
    assert hd.decode_faults(0) == "none"
    assert hd.decode_faults(None) == "none"


def test_decode_faults_single_and_multi_bit():
    assert hd.decode_faults(0x0001) == "OC_FC"
    combo = hd.decode_faults(0x0001 | 0x0004)
    assert "OC_FC" in combo and "OV_BUS" in combo


def test_decode_faults_unknown_bit_falls_back_to_hex():
    # every bit 0..15 is named, so force an out-of-range value; the function
    # only names bits found in the table, unnamed bits are silently dropped
    # unless NO bit is named at all, in which case it prints hex.
    huge = 1 << 20
    assert hd.decode_faults(huge) == "0x%04X" % huge


def test_decode_error_code_none_is_not_err_none():
    """The distinction the whole column rests on: '-' (the frame has no such
    byte) and NONE(0x00) (the board latched nothing) are different facts."""
    assert hd.decode_error_code(None) == hd.DASH
    assert hd.decode_error_code(0) == "NONE(0x00)"
    assert hd.decode_error_code(0x05) == "PI_TIMEOUT(0x05)"
    assert hd.decode_error_code(0x10) == "HIL_STALE(0x10)"
    # APPEND-ONLY enum: an unrecognised code means newer firmware, so it is
    # rendered raw rather than suppressed.
    assert hd.decode_error_code(0x7F) == "0x7F?"


def test_dashboard_error_code_names_agree_with_hil_plant_sim():
    """Two copies of the firmware enum exist (leaf-module rule); they must not
    drift.  The dashboard uses short labels, so compare on VALUES and on the
    substring, not on equality of the strings."""
    for val, name in hil.ERROR_CODE_NAMES.items():
        assert val in hd.ERROR_CODE_NAMES
        assert hd.ERROR_CODE_NAMES[val] == name[len("ERR_"):]
    assert set(hd.ERROR_CODE_NAMES) == set(hil.ERROR_CODE_NAMES)


def test_render_fault_line_carries_the_error_code(monkeypatch):
    _wide_terminal(monkeypatch)
    text, error = _run_dashboard_tick(
        monkeypatch, {"faults": 0x8010, "error_code": 0x10, "state": 99})
    assert error is None
    assert "err=HIL_STALE(0x10)" in text
    # A pre-v25 board renders the em-dash on the same line -- never NONE.
    text, error = _run_dashboard_tick(
        monkeypatch, {"faults": 0x8010, "error_code": None, "state": 99})
    assert error is None
    assert ("err=" + hd.DASH) in text


def test_state_names_covers_required_states():
    for s in (0, 1, 2, 3, 98, 99):
        assert s in hd.STATE_NAMES
    assert hd.STATE_NAMES[0] == "INIT"
    assert hd.STATE_NAMES[1] == "IDLE"
    assert hd.STATE_NAMES[2] == "RUN"
    assert hd.STATE_NAMES[3] == "FINISH"
    assert hd.STATE_NAMES[98] == "TEST"
    assert hd.STATE_NAMES[99] == "ERROR"


def test_switch_bits_match_hil_plant_sim_sw_constants():
    expected = {
        hil.SW_FC_BUS: "FC_BUS", hil.SW_BT_BUS: "BT_BUS",
        hil.SW_MOT_PWR: "MOT_PWR", hil.SW_REGEN: "REGEN",
        hil.SW_FC_CHARGE: "FC_CHG", hil.SW_BT_SEQ: "BT_SEQ",
    }
    assert dict(hd.SWITCH_BITS) == expected


def test_aux_bits_match_hil_plant_sim_aux_constants():
    expected = {
        hil.AUX_FC_REG: "FC_REG", hil.AUX_BT_REG: "BT_REG",
        hil.AUX_MPPT_DISABLE: "MPPT_DIS", hil.AUX_CBAL_DISABLE: "CBAL_DIS",
    }
    assert dict(hd.AUX_BITS) == expected


# ─────────────────────────────────────────────────────────────────────────
# 5. hil_plant_sim wiring
# ─────────────────────────────────────────────────────────────────────────

def test_dash_flag_exists_in_argparser():
    # Parse a minimal argv that would otherwise be valid, with --dash added,
    # and confirm argparse accepts it (would raise SystemExit on an unknown
    # flag).
    import argparse
    # Reach into main()'s parser indirectly: just confirm --dash is a legal
    # flag by building args through main() with --list-scenarios (early
    # exit) plus --dash, which argparse must still accept even though it's
    # unused on that path.
    rc = hil.main(["--list-scenarios", "--dash"])
    assert rc == 0


def _base_argv(tmp_path, extra, name="run.csv", rate="200"):
    csv_path = str(tmp_path / name)
    return (["--teensy-ip", "127.0.0.1", "--port", "58993",
              "--bind-port", "0", "--rate", rate, "--csv", csv_path] + extra,
            csv_path)


def test_without_dash_behavior_unchanged_csv_header_and_scenario_list(tmp_path, capsys):
    """Re-pin: omitting --dash must not perturb the CSV header or the
    --list-scenarios output."""
    argv, csv_path = _base_argv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple", "--duration", "0.02"])
    rc = hil.main(argv)
    assert rc == 0
    import csv as csvmod
    with open(csv_path, newline="") as fh:
        header = next(csvmod.reader(fh))
    # cmd cols appended by the EMS round; h2_rate_gps/h2_cum_g appended after
    # them by the 2026-08-31 H2-metric round; h2_sdp_cum_g appended after
    # THAT by the 2026-08-31 SDP round; cmd_share_sp_raw appended after THAT
    # by the 2026-08-31 ledger fix queue (MED-1, the SDP table's pre-clamp
    # request, blank on this non-SDP run).
    # mppt_thresh_cnt appended after all of them by the fw v24 lockstep round
    # (observation-frame byte 15; appended in BOTH schemas, so it is last).
    # error_code appended after THAT by fw v25, and the six power columns
    # after THAT by the 2026-09-01f power-balance round -- all three in BOTH
    # schemas, so the eight of them are the tail in that order.
    assert header[-8:] == ["mppt_thresh_cnt", "error_code",
                           "p_mot_w", "p_fc_w", "p_batt_w",
                           "p_chop_w", "p_aux_w", "p_bal_w"]
    assert header[-15:-8] == ["soc", "cmd_v_sp", "cmd_share_sp",
                              "h2_rate_gps", "h2_cum_g", "h2_sdp_cum_g",
                              "cmd_share_sp_raw"]

    rc2 = hil.main(["--list-scenarios"])
    assert rc2 == 0
    out = capsys.readouterr().out
    assert "steady" in out
    assert "charge-cruise" in out


class _CapturingDashboard:
    """Stand-in for hil_dashboard.Dashboard: captures every snapshot
    assignment (via a data-descriptor property, since a plain attribute
    wouldn't let us intercept without changing the hot-path contract) and
    reports started=True without touching the real terminal."""

    def __init__(self, *a, **k):
        self.snapshots = []
        self._snapshot = None
        self.error = None       # F2: the sim's 1 Hz block reads dash.error

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
    """Monkeypatch hil_dashboard.Dashboard (the name hil_plant_sim imports
    lazily inside main()) so a real --dash run captures every per-tick
    snapshot instead of touching a terminal."""
    captured = {}

    def _install():
        instance_holder = []
        real_cls = _CapturingDashboard

        class _Recording(real_cls):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                instance_holder.append(self)

        monkeypatch.setitem(sys.modules, "hil_dashboard",
                             type(sys)("hil_dashboard"))
        sys.modules["hil_dashboard"].Dashboard = _Recording
        captured["instances"] = instance_holder
        return instance_holder

    _install()
    return captured


def test_snapshot_dict_keys_and_share_act_none_at_negligible_current(
        tmp_path, capturing_dashboard):
    argv, csv_path = _base_argv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple",
                   "--duration", "0.03", "--dash"])
    rc = hil.main(argv)
    assert rc == 0
    instances = capturing_dashboard["instances"]
    assert len(instances) == 1, "exactly one Dashboard must be constructed"
    dash = instances[0]
    assert dash.snapshots, "the loop must feed at least one snapshot"

    required_keys = {
        "v_sp", "v_act", "share_sp", "share_act",
        "V_bus", "I_tot", "I_fc", "I_bt",
        "switch", "aux", "state", "faults",
        "mppt_cnt",
    }
    for snap in dash.snapshots:
        assert required_keys <= set(snap.keys())
        # I_tot is derivable / present directly
        assert "I_tot" in snap

    last = dash.snapshots[-1]
    # "steady" has no pi_timeline -> v_sp must be None throughout
    assert all(s["v_sp"] is None for s in dash.snapshots)
    # steady's source currents are near the fixed aux load only, well under
    # the 50 mA share_act gate for the currents this scenario draws at
    # t<=0.03s with sources not yet ramped -- assert the CONTRACT (some
    # entries with tiny I_tot map to share_act None), not a specific value,
    # so this doesn't depend on precise plant timing.
    tiny_current_entries = [s for s in dash.snapshots if s["I_tot"] is not None
                             and s["I_tot"] <= 0.05]
    assert all(s["share_act"] is None for s in tiny_current_entries)
    del last  # not otherwise asserted on; keeps intent readable


def test_snapshot_populated_from_pi_timeline_for_charge_cruise(
        tmp_path, capturing_dashboard):
    meta = hil.SCENARIOS["charge-cruise"]
    assert meta.get("pi_timeline"), "test assumes charge-cruise drives a PiCommander timeline"
    argv, csv_path = _base_argv(
        tmp_path, ["--scenario", "charge-cruise", "--electrical", "simple",
                   "--duration", "0.05", "--dash"])
    rc = hil.main(argv)
    assert rc == 0
    instances = capturing_dashboard["instances"]
    dash = instances[0]
    assert dash.snapshots
    # At least one snapshot must carry a real (non-None) v_sp/share_sp once
    # the commander has sent its first packet.
    assert any(s["v_sp"] is not None for s in dash.snapshots)
    assert any(s["share_sp"] is not None for s in dash.snapshots)


# ─────────────────────────────────────────────────────────────────────────
# 6. Status-line suppression while --dash is active
# ─────────────────────────────────────────────────────────────────────────

def test_status_lines_suppressed_with_dash_active(tmp_path, capturing_dashboard, capsys):
    argv, csv_path = _base_argv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple",
                   # F5: 1.6 s vs the 1.0 s status cadence gives >0.5 s margin
                   # instead of 0.2 s -- the old 1.2 s duration was flaky on a
                   # cold start.
                   "--rate", "2000", "--duration", "1.6", "--dash"])
    rc = hil.main(argv)
    assert rc == 0
    out = capsys.readouterr().out
    # The per-second status line format is "[hil] t=...s  state=...".
    assert not re.search(r"\[hil\] t=\s*\d+\.\d+s\s+state=", out), \
        "1 Hz status lines must be suppressed while the dashboard owns the screen"


def test_status_lines_present_without_dash(tmp_path, capsys):
    argv, csv_path = _base_argv(
        tmp_path, ["--scenario", "steady", "--electrical", "simple",
                   "--rate", "2000", "--duration", "1.6"])  # F5: see above
    rc = hil.main(argv)
    assert rc == 0
    out = capsys.readouterr().out
    assert re.search(r"\[hil\] t=\s*\d+\.\d+s", out), \
        "control: without --dash the normal status line must still print"


# ─────────────────────────────────────────────────────────────────────────
# 7. run_hil_suite wiring
# ─────────────────────────────────────────────────────────────────────────

def _rhs_args(**overrides):
    import argparse
    base = dict(
        out="/tmp/hil_report_test_dash", only=[], skip=[],
        replay_only=False, scenarios_only=False,
        electrical_pref="hifi", teensy_ip="192.168.1.50", port=5001,
        settle_s=5.0, keep_going=False, dashboard=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_dashboard_flag_appends_dash_to_child_argv():
    plan = rhs.build_plan(_rhs_args(only=["steady"]))
    item = plan[0]
    argv = rhs.full_argv(item, _rhs_args(dashboard=True))
    assert "--dash" in argv


def test_dashboard_flag_off_by_default_leaves_argv_unchanged():
    plan = rhs.build_plan(_rhs_args(only=["steady"]))
    item = plan[0]
    argv_default = rhs.full_argv(item, _rhs_args())               # dashboard=False
    argv_explicit_off = rhs.full_argv(item, _rhs_args(dashboard=False))
    assert "--dash" not in argv_default
    assert argv_default == argv_explicit_off


def test_dashboard_missing_attr_treated_as_off():
    """getattr(args, "dashboard", False) — confirm a Namespace without the
    attribute at all (e.g. an older caller) behaves as off, not a crash."""
    import argparse
    plan = rhs.build_plan(_rhs_args(only=["steady"]))
    item = plan[0]
    ns = argparse.Namespace(teensy_ip="192.168.1.50", port=5001)
    argv = rhs.full_argv(item, ns)
    assert "--dash" not in argv


def test_run_child_marks_stdout_passthrough_with_dashboard(monkeypatch, tmp_path):
    plan = rhs.build_plan(_rhs_args(only=["steady"]))
    item = dict(plan[0])
    item["log"] = str(tmp_path / "steady.log")
    item["timeout_s"] = 5

    class _FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", b""

        def terminate(self):
            pass

        def kill(self):
            pass

    captured_kwargs = {}

    def _fake_popen(argv, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(rhs.subprocess, "Popen", _fake_popen)
    rec = rhs.run_child(item, _rhs_args(dashboard=True))
    assert rec.get("stdout_passthrough") is True
    assert captured_kwargs.get("stdout") is None       # passed through to the real terminal
    assert captured_kwargs.get("stderr") == rhs.subprocess.PIPE


def test_run_child_no_passthrough_marker_without_dashboard(monkeypatch, tmp_path):
    plan = rhs.build_plan(_rhs_args(only=["steady"]))
    item = dict(plan[0])
    item["log"] = str(tmp_path / "steady2.log")
    item["timeout_s"] = 5

    class _FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", None

    def _fake_popen(argv, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(rhs.subprocess, "Popen", _fake_popen)
    rec = rhs.run_child(item, _rhs_args(dashboard=False))
    assert "stdout_passthrough" not in rec


# ─────────────────────────────────────────────────────────────────────────
# 8. Hot-path lightness guard (code-shape check)
# ─────────────────────────────────────────────────────────────────────────

def test_hot_path_feed_is_a_single_snapshot_assignment_no_other_dash_calls():
    """Static code-shape guard: within main()'s tick loop, the only
    interaction with the `dash` object other than the lifecycle
    start()/stop() calls (outside the loop) must be the
    `dash.snapshot = {...}` drop-box assignment -- no lock acquisition, no
    file I/O, no method calls, per the module's own PRIME DIRECTIVE.
    Implemented as a source inspection since Dashboard exposes no lock or
    I/O primitive on its public surface to assert against black-box."""
    src_path = os.path.join(HERE, "hil_plant_sim.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    # Every occurrence of `dash.<name>` other than `dash.snapshot`, `dash.start(`
    # and `dash.stop(` would indicate a heavier per-tick interaction.
    calls = re.findall(r"\bdash\.(\w+)\s*(\(?)", src)
    allowed = {"snapshot", "start", "stop", "error"}  # error: F2, read at 1 Hz only
    unexpected = sorted({name for name, _paren in calls if name not in allowed})
    assert not unexpected, (
        "hil_plant_sim.py touches dash.%s beyond the documented "
        "snapshot/start/stop surface -- re-check the lightness contract"
        % unexpected)
    # And confirm the snapshot assignment itself is a plain `=`, not e.g.
    # `dash.snapshot.update(...)` (which would mutate the previous dict
    # in place instead of doing an atomic drop-box swap).
    assert re.search(r"dash\.snapshot\s*=\s*\{", src), \
        "expected an atomic dict-literal assignment to dash.snapshot"
    assert "dash.snapshot.update(" not in src
    assert "dash.snapshot[" not in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
