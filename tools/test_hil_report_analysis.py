#!/usr/bin/env python3
"""pytest suite for tools/hil_report_analysis.py -- the HIL report
post-processor (run discovery/move, HIL-to-benchlog adaptation, replay
alignment/metrics, figure rendering, and the per-run/summary reports).

Requires numpy + matplotlib (same interpreter as test_figures.py; .venv_hil
is stdlib-only). The whole module is skipped cleanly if either is missing.

Run: cd tools && python -m pytest test_hil_report_analysis.py -v
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

np = pytest.importorskip("numpy")
pytest.importorskip("matplotlib")

import hil_report_analysis as hra  # noqa: E402
from hil_plant_sim import mdac_fraction as sim_mdac_fraction  # noqa: E402
import hil_plant_sim as _sim  # noqa: E402

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


@pytest.fixture(autouse=True)
def _close_all_figures():
    """matplotlib figures leak across tests (module-level pyplot registry) --
    close everything before AND after each test so a builder crash in one
    test can't pollute plt.get_fignums() for the next."""
    plt.close("all")
    yield
    plt.close("all")


# ─────────────────────────────────────────────────────────────────────────
# Fixture builders
# ─────────────────────────────────────────────────────────────────────────

SCEN_HEADER = ["t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn",
               "I_fc", "I_batt", "v_actual", "I_charge", "ag105_status",
               "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
               "fault_flags", "soc", "elec_substep_hz", "elec_events",
               "cmd_v_sp", "cmd_share_sp"]

REPLAY_HEADER = ["t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn",
                 "I_fc", "I_batt", "v_actual", "I_charge", "ag105_status",
                 "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
                 "fault_flags", "replay_rec", "cmd_v_sp", "cmd_share_sp"]


def _mdac_word(frac):
    """A raw AD5443 command word carrying `frac` in the LOAD_UPDATE nibble,
    using hil_plant_sim's own MDAC_CMD_LOAD_UPDATE/MDAC_RES constants so this
    fixture can never silently disagree with mdac_fraction's decode."""
    frac = max(0.0, min(1.0, frac))
    return _sim.MDAC_CMD_LOAD_UPDATE | int(round(frac * _sim.MDAC_RES))


def scen_folder(name, mode="hifi"):
    """The subfolder name the tool computes for a scenario run -- a literal
    re-derivation (NOT calling into hra.folder_name_for) so tests that use
    this helper still pin the tool's naming convention rather than trivially
    agreeing with whatever the tool currently does."""
    return "scenario_%s_%s" % (name, mode)


def replay_folder(name):
    return "replay_%s" % name


def make_scenario_csv(path, n=20, dt=0.05, state=2, fault_flags=0,
                       v_actual_fn=None, mdac_fc=0.3, mdac_bt=0.3,
                       ag105_status=0x00, blank_rows=()):
    """Write a minimal but realistic hil_scenario_*.csv."""
    rows = []
    for i in range(n):
        t = i * dt
        v_act = v_actual_fn(t) if v_actual_fn else 1.0 + 0.01 * i
        row = {
            "t": t, "seq": i, "V_fc": 13.0, "V_batt": 8.0, "V_bus": 16.0,
            "V_chg": 13.0, "V_rgn": 16.0, "I_fc": 0.5, "I_batt": 0.5,
            "v_actual": v_act, "I_charge": 0.1,
            "ag105_status": "0x%02X" % ag105_status, "state": state,
            "switch": 0x3F, "aux": 0x0F, "current": 1.2,
            "mdac_fc": _mdac_word(mdac_fc), "mdac_bt": _mdac_word(mdac_bt),
            "fault_flags": fault_flags, "soc": 0.5, "elec_substep_hz": 30000.0,
            "elec_events": 0, "cmd_v_sp": v_act, "cmd_share_sp": 0.5,
        }
        rows.append(row)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SCEN_HEADER)
        for i, row in enumerate(rows):
            cells = [row[c] for c in SCEN_HEADER]
            if i in blank_rows:
                cells = ["" for _ in cells]
                cells[0] = row["t"]  # keep a time axis even on a blank row
            w.writerow(cells)
    return path


def make_replay_csv(path, n=20, dt=0.05, replay_rec_fn=None,
                     state_blank_at=(), fault_flags=0,
                     cmd_v_sp_fn=None, cmd_share_sp_fn=None):
    """Write a minimal hil_replay_*.csv. replay_rec_fn(i) -> int (default i-2,
    so the first two rows are the synthetic preamble at -2/-1).

    cmd_v_sp_fn/cmd_share_sp_fn(i) -> value, matching the real 2026-08-30
    replay schema where cmd_v_sp/cmd_share_sp are ALWAYS present as columns
    but are BLANK cells on a plain --replay (no commander) and populated
    under --replay-commands. Default None -> every cell blank (the plain-
    replay CSV shape), so existing call sites are unaffected."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(REPLAY_HEADER)
        rrf = replay_rec_fn if replay_rec_fn is not None else (lambda i: i - 2)
        for i in range(n):
            t = i * dt
            state = "" if i in state_blank_at else 2
            cmd_v_sp = "" if cmd_v_sp_fn is None else cmd_v_sp_fn(i)
            cmd_share_sp = "" if cmd_share_sp_fn is None else cmd_share_sp_fn(i)
            row = [t, i, 13.0, 8.0, 16.0, 13.0, 16.0, 0.5, 0.5,
                   1.0 + 0.01 * i, 0.1, "0x00", state, 0x3F, 0x0F, 1.2,
                   _mdac_word(0.3), _mdac_word(0.3), fault_flags,
                   rrf(i), cmd_v_sp, cmd_share_sp]
            w.writerow(row)
    return path


def make_meta(mode="scenario_hifi", status="completed", replay_source=None,
              warm_reset_grace_s=2.0):
    return {
        "format_version": 1, "tool": "hil_plant_sim.py", "status": status,
        "mode": mode, "replay_source": replay_source,
        "results": {"warm_reset_grace_s": warm_reset_grace_s},
    }


def make_results_json(entries, target_fw=23):
    return {"meta": {"date": "2026-08-30", "target_fw": target_fw,
                     "teensy_ip": "192.168.1.50", "port": 5001,
                     "electrical_pref": "hifi", "mode": "scenario"},
            "results": entries}


def build_report(tmp_path, dirname="hil_report_20260830_000000"):
    """A bare report folder (no runs yet)."""
    d = tmp_path / dirname
    d.mkdir()
    return d


def add_scenario_run(report_dir, name="steady", mode="hifi", **csv_kwargs):
    csv_name = "hil_scenario_%s_%s.csv" % (name, mode)
    csv_path = report_dir / csv_name
    make_scenario_csv(csv_path, **csv_kwargs)
    meta = make_meta(mode="scenario_%s" % mode)
    with open(str(csv_path) + ".meta.json", "w") as f:
        json.dump(meta, f)
    return csv_path


def add_replay_run(report_dir, name="ML0146", blg_path=None,
                    blg_fw_version=23, blg_version=7, **csv_kwargs):
    csv_name = "hil_replay_%s.csv" % name
    csv_path = report_dir / csv_name
    make_replay_csv(csv_path, **csv_kwargs)
    replay_source = {"path": str(blg_path) if blg_path else None,
                     "basename": (blg_path.name if blg_path else
                                  "%s.BLG" % name),
                     "blg_fw_version": blg_fw_version,
                     "blg_version": blg_version}
    meta = make_meta(mode="replay", replay_source=replay_source)
    with open(str(csv_path) + ".meta.json", "w") as f:
        json.dump(meta, f)
    return csv_path


def fake_blg_data(n=20, fw_version=23):
    """A decode_source_blg()-shaped (data, header) pair with a truth
    trajectory offset from the HIL trace by a KNOWN constant, so deviation
    metrics have a known answer."""
    t_us = (np.arange(n) * 50000).astype(np.float64)
    data = {
        "t_us": t_us,
        "V_fc": np.full(n, 13.0), "V_batt": np.full(n, 8.0),
        "V_bus": np.full(n, 16.0),
        "I_fc": np.full(n, 0.5), "I_batt": np.full(n, 0.5),
        "v_act": 1.0 + 0.01 * np.arange(n, dtype=np.float64) + 0.02,
        "I_cmd": np.full(n, 1.2) + 0.1,
        "gFC": np.full(n, 0.3), "gBT": np.full(n, 0.3),
        "fault_flags": np.zeros(n),
    }
    header = {"version": 7, "fw_version": fw_version}
    return data, header


def add_source_blg(tmp_path, name):
    """A dummy source-log file locate_source_blg() will find (it only checks
    is_file(); decode_source_blg is monkeypatched wherever the bytes need to
    parse as something specific)."""
    p = tmp_path / ("%s.BLG" % name)
    p.write_bytes(b"")
    return p


# ─────────────────────────────────────────────────────────────────────────
# 1. Discovery: parse_csv_name
# ─────────────────────────────────────────────────────────────────────────

def test_parse_csv_name_scenario_with_mode():
    assert hra.parse_csv_name("hil_scenario_steady_hifi.csv") == \
        ("scenario", "steady", "hifi")


def test_parse_csv_name_scenario_simple_mode():
    assert hra.parse_csv_name("hil_scenario_steady_simple.csv") == \
        ("scenario", "steady", "simple")


def test_parse_csv_name_scenario_no_mode_suffix():
    assert hra.parse_csv_name("hil_scenario_charge-cruise.csv") == \
        ("scenario", "charge-cruise", None)


def test_parse_csv_name_replay():
    assert hra.parse_csv_name("hil_replay_ML0146.csv") == \
        ("replay", "ML0146", None)


def test_parse_csv_name_unknown_prefix_returns_none():
    assert hra.parse_csv_name("hil_dashboard_snapshot.csv") is None


def test_parse_csv_name_non_csv_returns_none():
    assert hra.parse_csv_name("hil_scenario_steady_hifi.csv.meta.json") is None


def test_parse_csv_name_mode_suffix_only_stripped_when_it_is_the_whole_suffix():
    # A hypothetical scenario literally named "hifi" would collide with the
    # mode-suffix strip; parse_csv_name has no way to disambiguate ("_hifi"
    # is always read as the mode). Documented via this pin rather than
    # asserted as a defect -- CLAUDE.md/registry names are hyphenated and the
    # module docstring already flags underscored names as unsupported.
    assert hra.parse_csv_name("hil_scenario_hifi_hifi.csv") == \
        ("scenario", "hifi", "hifi")


def test_folder_name_for_scenario_includes_mode():
    assert hra.folder_name_for("scenario", "steady", "hifi") == \
        "scenario_steady_hifi"
    assert hra.folder_name_for("scenario", "steady", "simple") == \
        "scenario_steady_simple"


def test_folder_name_for_replay_has_no_mode_component():
    assert hra.folder_name_for("replay", "ML0146", None) == "replay_ML0146"


def test_runspec_key_includes_electrical_mode():
    r_hifi = hra.RunSpec("scenario", "steady", Path("a.csv"),
                        "scenario_steady_hifi", "hifi")
    r_simple = hra.RunSpec("scenario", "steady", Path("b.csv"),
                          "scenario_steady_simple", "simple")
    assert r_hifi.key != r_simple.key
    assert r_hifi.key == ("scenario", "steady", "hifi")


def test_runspec_key_replay_mode_is_empty_string():
    r = hra.RunSpec("replay", "ML0146", Path("a.csv"), "replay_ML0146", None)
    assert r.key == ("replay", "ML0146", "")


# ─────────────────────────────────────────────────────────────────────────
# 2. Discovery: discover_runs
# ─────────────────────────────────────────────────────────────────────────

def test_discover_runs_from_parent_unmoved(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady")
    add_replay_run(d, "ML0146")
    runs = hra.discover_runs(d)
    assert [(r.kind, r.name) for r in runs] == [("replay", "ML0146"),
                                                ("scenario", "steady")]
    assert all(not r.moved for r in runs)


def test_discover_runs_from_subfolder_moved(tmp_path):
    d = build_report(tmp_path)
    sub = d / scen_folder("steady")
    sub.mkdir()
    add_scenario_run(sub, "steady")
    runs = hra.discover_runs(d)
    assert len(runs) == 1
    assert runs[0].moved is True
    assert runs[0].folder_name == scen_folder("steady")


def test_discover_runs_mixed_moved_and_unmoved_no_double_processing(tmp_path):
    d = build_report(tmp_path)
    sub = d / scen_folder("steady")
    sub.mkdir()
    add_scenario_run(sub, "steady")
    add_replay_run(d, "ML0146")
    runs = hra.discover_runs(d)
    assert len(runs) == 2
    kinds = sorted((r.kind, r.name, r.moved) for r in runs)
    assert kinds == [("replay", "ML0146", False), ("scenario", "steady", True)]


def test_discover_runs_duplicate_in_both_places_wins_subfolder_copy(tmp_path):
    d = build_report(tmp_path)
    sub = d / scen_folder("steady")
    sub.mkdir()
    add_scenario_run(sub, "steady", v_actual_fn=lambda t: 9.0)  # subfolder copy
    add_scenario_run(d, "steady", v_actual_fn=lambda t: 1.0)    # parent copy
    runs = hra.discover_runs(d)
    assert len(runs) == 1
    assert runs[0].moved is True
    assert runs[0].csv_path.parent.name == scen_folder("steady")


def test_discover_runs_unknown_csv_ignored(tmp_path):
    d = build_report(tmp_path)
    (d / "unrelated.csv").write_text("a,b\n1,2\n")
    assert hra.discover_runs(d) == []


def test_discover_runs_sorted_by_kind_then_name(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "zzz")
    add_scenario_run(d, "aaa")
    add_replay_run(d, "ML0001")
    runs = hra.discover_runs(d)
    assert [(r.kind, r.name) for r in runs] == [
        ("replay", "ML0001"), ("scenario", "aaa"), ("scenario", "zzz")]


def test_discover_runs_two_electrical_modes_of_one_scenario_are_distinct(
        tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady", mode="hifi")
    add_scenario_run(d, "steady", mode="simple")
    runs = hra.discover_runs(d)
    assert len(runs) == 2
    folders = sorted(r.folder_name for r in runs)
    assert folders == [scen_folder("steady", "hifi"),
                       scen_folder("steady", "simple")]
    # Both share (kind, name) but differ in elec_mode -- neither was dropped
    # by a (kind, name)-only key.
    assert {r.elec_mode for r in runs} == {"hifi", "simple"}


# ─────────────────────────────────────────────────────────────────────────
# 3. Mover: move_run_files
# ─────────────────────────────────────────────────────────────────────────

def test_move_run_files_moves_csv_meta_and_events(tmp_path):
    d = build_report(tmp_path)
    csv_path = add_scenario_run(d, "steady")
    events = csv_path.with_name(csv_path.name + ".events.jsonl")
    events.write_text("{}\n")
    run = hra.discover_runs(d)[0]
    dest, warnings = hra.move_run_files(run, d)
    assert warnings == []
    assert dest == d / scen_folder("steady")
    assert (dest / csv_path.name).exists()
    assert (dest / (csv_path.name + ".meta.json")).exists()
    assert (dest / (csv_path.name + ".events.jsonl")).exists()
    assert not csv_path.exists()
    assert not events.exists()


def test_move_run_files_picks_up_child_log(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady")
    (d / "run_scenario_steady.log").write_text("log\n")
    run = hra.discover_runs(d)[0]
    dest, _ = hra.move_run_files(run, d)
    assert (dest / "run_scenario_steady.log").exists()
    assert not (d / "run_scenario_steady.log").exists()


def test_move_run_files_leaves_shared_files_untouched(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady")
    for name in ("REPORT.md", "results.json", "plan.json", "HIL_FINDINGS.md",
                "unrelated_notes.txt"):
        (d / name).write_text("x")
    run = hra.discover_runs(d)[0]
    hra.move_run_files(run, d)
    for name in ("REPORT.md", "results.json", "plan.json", "HIL_FINDINGS.md",
                "unrelated_notes.txt"):
        assert (d / name).exists()


def test_move_run_files_duplicate_source_and_dest_warns_and_leaves_source(tmp_path):
    d = build_report(tmp_path)
    sub = d / scen_folder("steady")
    sub.mkdir()
    add_scenario_run(sub, "steady")           # already moved
    stray = add_scenario_run(d, "steady")     # a stray parent copy
    run = hra.discover_runs(d)[0]
    assert run.moved is True
    dest, warnings = hra.move_run_files(run, d)
    assert any("BOTH the parent" in w for w in warnings)
    assert stray.exists()  # left in place, not deleted


def test_move_run_files_idempotent_second_call(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady")
    run = hra.discover_runs(d)[0]
    dest1, w1 = hra.move_run_files(run, d)
    assert w1 == []
    # Rediscover as the caller would on a second invocation.
    run2 = hra.discover_runs(d)[0]
    assert run2.moved is True
    dest2, w2 = hra.move_run_files(run2, d)
    assert dest2 == dest1
    assert w2 == []
    assert (dest1 / run.csv_path.name).exists()


def test_move_run_files_heals_orphaned_meta_and_events(tmp_path):
    """F1: a run whose CSV made it into the subfolder but whose sidecars did
    not (an earlier move interrupted between the CSV and meta/events moves)
    gets those sidecars healed into the subfolder on the next call, with a
    warning distinguishing this from a genuine duplicate."""
    d = build_report(tmp_path)
    sub = d / scen_folder("steady")
    sub.mkdir()
    csv_name = "hil_scenario_steady_hifi.csv"
    make_scenario_csv(sub / csv_name, n=5)
    meta = make_meta(mode="scenario_hifi")
    (d / (csv_name + ".meta.json")).write_text(json.dumps(meta))
    (d / (csv_name + ".events.jsonl")).write_text('{"a": 1}\n')

    run = hra.discover_runs(d)[0]
    assert run.moved is True
    dest, warnings = hra.move_run_files(run, d)

    assert any("orphaned" in w and "meta.json" in w for w in warnings)
    assert any("orphaned" in w and "events.jsonl" in w for w in warnings)
    assert (dest / (csv_name + ".meta.json")).exists()
    assert (dest / (csv_name + ".events.jsonl")).exists()
    assert not (d / (csv_name + ".meta.json")).exists()
    assert not (d / (csv_name + ".events.jsonl")).exists()


def test_move_run_files_orphan_heal_is_warn_only_when_dest_also_exists(
        tmp_path):
    """The other half of F1: when BOTH the parent stray AND the subfolder
    copy exist, that is a genuine duplicate (not an orphan) -- warn and leave
    the parent copy untouched, never silently merge it in."""
    d = build_report(tmp_path)
    sub = d / scen_folder("steady")
    sub.mkdir()
    csv_name = "hil_scenario_steady_hifi.csv"
    make_scenario_csv(sub / csv_name, n=5)
    (sub / (csv_name + ".events.jsonl")).write_text('{"kept": true}\n')
    stray_events = d / (csv_name + ".events.jsonl")
    stray_events.write_text('{"stray": true}\n')

    run = hra.discover_runs(d)[0]
    dest, warnings = hra.move_run_files(run, d)
    assert any("events.jsonl" in w and "BOTH the parent" in w
              for w in warnings)
    assert stray_events.exists()
    assert stray_events.read_text() == '{"stray": true}\n'
    assert (dest / (csv_name + ".events.jsonl")).read_text() == \
        '{"kept": true}\n'


# ─────────────────────────────────────────────────────────────────────────
# 4. Adapter
# ─────────────────────────────────────────────────────────────────────────

def test_load_hil_csv_blank_cells_become_nan(tmp_path):
    p = tmp_path / "s.csv"
    make_scenario_csv(p, n=5, blank_rows=(2,))
    hil = hra.load_hil_csv(p)
    assert np.isnan(hil["V_bus"][2])
    assert not np.isnan(hil["V_bus"][0])


def test_load_hil_csv_hex_ag105_status_parsed(tmp_path):
    p = tmp_path / "s.csv"
    make_scenario_csv(p, n=3, ag105_status=0x2A)
    hil = hra.load_hil_csv(p)
    assert hil["ag105_status"][0] == pytest.approx(0x2A)


def test_load_hil_csv_row_length_mismatch_raises(tmp_path):
    p = tmp_path / "bad.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SCEN_HEADER)
        w.writerow([0.0])  # short row
    with pytest.raises(ValueError, match="corrupt CSV"):
        hra.load_hil_csv(p)


def test_adapt_to_benchlog_direct_column_mapping(tmp_path):
    p = tmp_path / "s.csv"
    make_scenario_csv(p, n=5)
    hil = hra.load_hil_csv(p)
    data = hra.adapt_to_benchlog(hil)
    assert np.array_equal(data["V_bus"], hil["V_bus"])
    assert np.array_equal(data["v_act"], hil["v_actual"])
    assert np.array_equal(data["I_cmd"], hil["current"])


def test_adapt_to_benchlog_mdac_word_maps_to_gain_fraction(tmp_path):
    p = tmp_path / "s.csv"
    make_scenario_csv(p, n=3, mdac_fc=0.75, mdac_bt=0.10)
    hil = hra.load_hil_csv(p)
    data = hra.adapt_to_benchlog(hil)
    assert data["gFC"][0] == pytest.approx(0.75, abs=2e-3)
    assert data["gBT"][0] == pytest.approx(0.10, abs=2e-3)


def test_mdac_column_wrong_control_nibble_maps_to_zero():
    # A word whose top nibble is not the load-and-update control code never
    # reached the DAC register; mdac_fraction (and therefore _mdac_column)
    # maps it to 0.0.
    bogus = np.array([0x0FFF], dtype=np.float64)  # control nibble 0x0
    out = hra._mdac_column(bogus)
    assert out[0] == 0.0
    assert out[0] == pytest.approx(sim_mdac_fraction(0x0FFF))


def test_adapt_to_benchlog_share_act_low_current_masked_nan(tmp_path):
    p = tmp_path / "s.csv"
    # Force I_fc/I_batt total under the 50 mA gate.
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SCEN_HEADER)
        row = {"t": 0.0, "seq": 0, "V_fc": 13.0, "V_batt": 8.0, "V_bus": 16.0,
               "V_chg": 13.0, "V_rgn": 16.0, "I_fc": 0.01, "I_batt": 0.01,
               "v_actual": 1.0, "I_charge": 0.0, "ag105_status": "0x00",
               "state": 2, "switch": 0, "aux": 0, "current": 0.0,
               "mdac_fc": 0, "mdac_bt": 0, "fault_flags": 0, "soc": 0.5,
               "elec_substep_hz": 0.0, "elec_events": 0, "cmd_v_sp": 0.0,
               "cmd_share_sp": 0.0}
        w.writerow([row[c] for c in SCEN_HEADER])
    hil = hra.load_hil_csv(p)
    data = hra.adapt_to_benchlog(hil)
    assert np.isnan(data["share_act"][0])


def test_share_actual_known_ratio_above_gate():
    i_fc = np.array([0.3, 1.0])
    i_batt = np.array([0.7, 0.0])
    out = hra.share_actual(i_fc, i_batt)
    assert out[0] == pytest.approx(0.3)
    assert out[1] == pytest.approx(1.0)


def test_adapt_to_benchlog_missing_optional_columns_absent_not_nan_filled(
        tmp_path):
    """A simple-electrical / replay-shaped CSV without soc/elec_* simply has
    no v_sp/share_sp keys in the adapted dict -- the adapter must not
    synthesize them as all-NaN columns (that would make a KeyError-based
    figure skip look like a real-but-empty signal)."""
    p = tmp_path / "r.csv"
    make_replay_csv(p, n=4)
    hil = hra.load_hil_csv(p)
    data = hra.adapt_to_benchlog(hil)
    assert "v_sp" not in data
    assert "share_sp" not in data


# ─────────────────────────────────────────────────────────────────────────
# L4 (fix round, 2026-08-30): a replay CSV now carries cmd_v_sp/cmd_share_sp
# unconditionally (--replay-commands landed), but they are blank (all-NaN)
# unless that flag was passed. adapt_to_benchlog() must drop an all-NaN cmd_*
# column rather than emit one an empty figure would be drawn on.
# ─────────────────────────────────────────────────────────────────────────

def test_adapt_to_benchlog_replay_csv_plain_cmd_columns_present_but_all_nan_dropped(
        tmp_path):
    """Plain --replay (no --replay-commands): cmd_v_sp/cmd_share_sp exist as
    CSV COLUMNS (unconditional append) and load_hil_csv() parses them into
    the raw `hil` dict as all-NaN arrays -- but adapt_to_benchlog() must drop
    both from the adapted dict entirely, not pass the all-NaN arrays through."""
    p = tmp_path / "r_plain.csv"
    make_replay_csv(p, n=6)   # cmd_v_sp_fn/cmd_share_sp_fn default None -> blank cells
    hil = hra.load_hil_csv(p)
    assert "cmd_v_sp" in hil
    assert "cmd_share_sp" in hil
    assert np.all(np.isnan(hil["cmd_v_sp"]))
    assert np.all(np.isnan(hil["cmd_share_sp"]))

    data = hra.adapt_to_benchlog(hil)
    assert "v_sp" not in data
    assert "share_sp" not in data


def test_adapt_to_benchlog_replay_csv_command_replay_cmd_columns_present_and_kept(
        tmp_path):
    """--replay-commands: cmd_v_sp/cmd_share_sp carry real (non-NaN) values,
    and adapt_to_benchlog() must map them through to v_sp/share_sp -- the
    all-NaN drop must not also swallow a genuinely populated column."""
    p = tmp_path / "r_cmds.csv"
    make_replay_csv(p, n=6,
                    cmd_v_sp_fn=lambda i: 1.5 + 0.1 * i,
                    cmd_share_sp_fn=lambda i: 0.5)
    hil = hra.load_hil_csv(p)
    assert not np.any(np.isnan(hil["cmd_v_sp"]))
    assert not np.any(np.isnan(hil["cmd_share_sp"]))

    data = hra.adapt_to_benchlog(hil)
    assert "v_sp" in data
    assert "share_sp" in data
    assert np.array_equal(data["v_sp"], hil["cmd_v_sp"])
    assert np.array_equal(data["share_sp"], hil["cmd_share_sp"])
    assert data["v_sp"][0] == pytest.approx(1.5)
    assert data["share_sp"][0] == pytest.approx(0.5)


def test_adapt_to_benchlog_replay_csv_partially_populated_cmd_column_is_kept():
    """A column with SOME NaN and some real values (e.g. the synthetic
    preamble rows still blank, the handover rows populated) must NOT be
    treated as all-NaN -- np.all(isnan(...)) is False, so it passes through,
    NaNs and all (a figure builder downstream is expected to handle that, the
    same as any other partially-observed column)."""
    n = 6
    v_sp = np.array([np.nan, np.nan, 1.0, 1.1, 1.2, 1.3])
    hil = {"t_s": np.arange(n, dtype=np.float64),
           "cmd_v_sp": v_sp,
           "cmd_share_sp": np.full(n, np.nan)}
    data = hra.adapt_to_benchlog(hil)
    assert "v_sp" in data
    assert np.array_equal(data["v_sp"], v_sp, equal_nan=True)
    assert "share_sp" not in data   # this one genuinely is all-NaN


def test_adapt_to_benchlog_flags_column_is_hil_banner_bit():
    p_data = {"t_s": np.zeros(3)}
    out = hra.adapt_to_benchlog(p_data)
    assert np.all(out["flags"] == float(0x40))


# ─────────────────────────────────────────────────────────────────────────
# 5. Alignment: align_replay
# ─────────────────────────────────────────────────────────────────────────

def test_align_replay_excludes_negative_preamble():
    hil = {"replay_rec": np.array([-2.0, -1.0, 0.0, 1.0, 2.0]),
           "state": np.array([np.nan, np.nan, 2.0, 2.0, 2.0])}
    hil_idx, blg_idx = hra.align_replay(hil, blg_len=10)
    assert list(hil_idx) == [2, 3, 4]
    assert list(blg_idx) == [0, 1, 2]


def test_align_replay_excludes_blank_state_rows():
    hil = {"replay_rec": np.array([0.0, 1.0, 2.0]),
           "state": np.array([2.0, np.nan, 2.0])}
    hil_idx, blg_idx = hra.align_replay(hil, blg_len=10)
    assert list(hil_idx) == [0, 2]
    assert list(blg_idx) == [0, 2]


def test_align_replay_out_of_range_record_indices_excluded_not_crash():
    hil = {"replay_rec": np.array([0.0, 5.0, 999.0]),
           "state": np.array([2.0, 2.0, 2.0])}
    hil_idx, blg_idx = hra.align_replay(hil, blg_len=6)
    assert list(hil_idx) == [0, 1]
    assert list(blg_idx) == [0, 5]


def test_align_replay_no_replay_rec_column_returns_empty():
    hil_idx, blg_idx = hra.align_replay({}, blg_len=10)
    assert hil_idx.size == 0 and blg_idx.size == 0


def test_align_replay_no_state_column_still_aligns_on_rec_alone():
    hil = {"replay_rec": np.array([0.0, 1.0])}
    hil_idx, blg_idx = hra.align_replay(hil, blg_len=5)
    assert list(hil_idx) == [0, 1]


# ─────────────────────────────────────────────────────────────────────────
# 6. Metrics
# ─────────────────────────────────────────────────────────────────────────

def test_deviation_metrics_known_answer():
    hil_vals = np.array([1.0, 2.0, 3.0, 4.0])
    blg_vals = np.array([1.0, 2.0, 3.0, 8.0])  # one +4 outlier
    m = hra.deviation_metrics(hil_vals, blg_vals)
    assert m["n"] == 4
    assert m["max_abs"] == pytest.approx(4.0)
    assert m["mean"] == pytest.approx(-1.0)
    assert m["rms"] == pytest.approx(np.sqrt((0 + 0 + 0 + 16) / 4.0))


def test_deviation_metrics_nan_rows_excluded_not_poisoning_rms():
    hil_vals = np.array([1.0, np.nan, 3.0])
    blg_vals = np.array([1.0, 100.0, 3.0])
    m = hra.deviation_metrics(hil_vals, blg_vals)
    assert m["n"] == 2
    assert m["rms"] == pytest.approx(0.0)


def test_deviation_metrics_all_nan_returns_none_fields():
    m = hra.deviation_metrics(np.array([np.nan]), np.array([np.nan]))
    assert m == {"n": 0, "rms": None, "max_abs": None, "mean": None}


def test_compute_replay_metrics_fault_mismatch_fraction():
    hil = {"fault_flags": np.array([0.0, 1.0, 1.0, 0.0])}
    blg = {"fault_flags": np.array([0.0, 0.0, 1.0, 0.0])}
    idx = np.arange(4)
    out = hra.compute_replay_metrics(hil, blg, idx, idx)
    assert out["fault_mismatch_fraction"] == pytest.approx(0.25)
    assert out["hil_fault_union"] == 1
    assert out["blg_fault_union"] == 1


def test_compute_replay_metrics_signals_absent_from_one_side_skipped():
    hil = {"V_fc": np.array([1.0, 2.0])}  # no matching blg key
    blg = {}
    idx = np.arange(2)
    out = hra.compute_replay_metrics(hil, blg, idx, idx)
    assert out["injection"] == {}
    assert out["response"] == {}


def test_compute_replay_metrics_empty_alignment_returns_zeroed_shell():
    out = hra.compute_replay_metrics({}, {}, np.array([], dtype=int),
                                     np.array([], dtype=int))
    assert out["aligned_ticks"] == 0
    assert out["injection"] == {} and out["response"] == {}


def test_decode_fault_bits_zero_is_empty_list():
    assert hra.decode_fault_bits(0) == []


def test_decode_fault_bits_unknown_residual_bit_hex_formatted():
    # De-vacuated: pin the ACTUAL residual formatting, not just "some name
    # somewhere starts with 0x". FAULT_OC_FC == 0x0001 (hil_replay_suite.py)
    # is the lowest named bit, so it sorts first; the unnamed high bit must
    # render as its own exact hex literal, appended after the named bits.
    known_mask = 0
    for bit in hra.fault_names():
        known_mask |= bit
    residual_bit = 0x00010000
    assert residual_bit & known_mask == 0  # precondition: truly unnamed
    flags = 0x0001 | residual_bit
    names = hra.decode_fault_bits(flags)
    assert names[0] == hra.fault_names()[0x0001]
    assert names[-1] == "0x%04X" % residual_bit
    assert len(names) == 2


# ─────────────────────────────────────────────────────────────────────────
# 7. Figure driver
# ─────────────────────────────────────────────────────────────────────────

def test_build_one_closes_figures_left_open_by_a_raising_builder():
    def bad_builder(data, cfg):
        plt.figure()  # opens a figure, then blows up before returning it
        raise KeyError("v_sp")

    before = set(plt.get_fignums())
    with pytest.raises(KeyError):
        hra._build_one(bad_builder, {}, {})
    assert set(plt.get_fignums()) == before


def test_run_standard_figures_keyerror_builder_is_skipped_not_raised(
        tmp_path):
    p = tmp_path / "s.csv"
    make_scenario_csv(p, n=5)
    hil = hra.attach_derived(hra.load_hil_csv(p))
    data = hra.adapt_to_benchlog(hil)
    dest = tmp_path / "out"
    dest.mkdir()
    cfg = {"_run_name": "test", "filters": {}}
    saved, skipped = hra.run_standard_figures(data, hil, cfg, dest, p)
    # currents_and_share / drive_controller_conditioning / encoder_* need
    # signals a minimal scenario CSV doesn't carry (u_unsat, encoder_pos...);
    # they must land in `skipped`, and the run must not raise.
    skipped_names = {n for n, _ in skipped}
    assert "drive_controller_conditioning" in skipped_names
    assert "encoder_diagnostics" in skipped_names
    # Every skip reason is either a KeyError (signal genuinely absent, run_
    # standard_figures' own catch) or a declined None return -- never a bare
    # pass-through of some other exception type.
    for name, reason in skipped:
        assert reason.startswith("KeyError:") or \
            reason == "builder declined (signals not applicable)"
    assert saved  # something legitimate DID render
    for name in saved:
        assert (dest / ("%s.png" % name)).stat().st_size > 0


def test_run_standard_figures_non_keyerror_exception_propagates(tmp_path):
    """F6: only KeyError is a skip. Any other exception (a real defect in the
    builder or the adapted data) must propagate to the caller."""
    def bad_builder(data, cfg):
        raise TypeError("not a signal-availability problem")

    orig_figures = hra.bl_figures.FIGURES
    orig_hil_figures = hra.HIL_FIGURES
    try:
        hra.bl_figures.FIGURES = [("bad_fig", bad_builder)]
        hra.HIL_FIGURES = []
        with pytest.raises(TypeError):
            hra.run_standard_figures({"t_s": np.zeros(2)}, {}, {}, tmp_path,
                                     tmp_path / "x.csv")
    finally:
        hra.bl_figures.FIGURES = orig_figures
        hra.HIL_FIGURES = orig_hil_figures


def test_run_standard_figures_none_returning_builder_is_skipped(tmp_path):
    def none_builder(data, cfg):
        return None
    # Exercise the contract directly via a tiny registry substitute instead of
    # monkeypatching module globals (keeps this test independent of the real
    # FIGURES/HIL_FIGURES registry order).
    orig_figures = hra.bl_figures.FIGURES
    orig_hil_figures = hra.HIL_FIGURES
    try:
        hra.bl_figures.FIGURES = [("none_fig", none_builder)]
        hra.HIL_FIGURES = []
        saved, skipped = hra.run_standard_figures(
            {"t_s": np.zeros(2)}, {}, {}, tmp_path, tmp_path / "x.csv")
    finally:
        hra.bl_figures.FIGURES = orig_figures
        hra.HIL_FIGURES = orig_hil_figures
    assert saved == []
    assert skipped == [("none_fig", "builder declined (signals not applicable)")]


def test_run_standard_figures_skips_existing_unless_forced(tmp_path):
    p = tmp_path / "s.csv"
    make_scenario_csv(p, n=5)
    hil = hra.attach_derived(hra.load_hil_csv(p))
    data = hra.adapt_to_benchlog(hil)
    dest = tmp_path / "out"
    dest.mkdir()
    cfg = {"_run_name": "test", "filters": {}}
    saved1, _ = hra.run_standard_figures(data, hil, cfg, dest, p)
    assert saved1
    mtime1 = (dest / ("%s.png" % saved1[0])).stat().st_mtime_ns
    saved2, _ = hra.run_standard_figures(data, hil, cfg, dest, p)  # force=False
    mtime2 = (dest / ("%s.png" % saved2[0])).stat().st_mtime_ns
    assert mtime1 == mtime2
    saved3, _ = hra.run_standard_figures(data, hil, cfg, dest, p, force=True)
    mtime3 = (dest / ("%s.png" % saved3[0])).stat().st_mtime_ns
    assert mtime3 != mtime1


def test_run_standard_figures_regenerates_stale_png_without_force(tmp_path):
    """F3: a PNG older than its run's CSV is regenerated even without
    --force -- a re-run of the suite over the same folder replaces the CSV,
    and a stale figure would otherwise describe data that is gone."""
    p = tmp_path / "s.csv"
    make_scenario_csv(p, n=5)
    hil = hra.attach_derived(hra.load_hil_csv(p))
    data = hra.adapt_to_benchlog(hil)
    dest = tmp_path / "out"
    dest.mkdir()
    cfg = {"_run_name": "test", "filters": {}}
    saved1, _ = hra.run_standard_figures(data, hil, cfg, dest, p)
    png = dest / ("%s.png" % saved1[0])
    csv_mtime = p.stat().st_mtime
    old_mtime = csv_mtime - 1000.0
    os.utime(png, (old_mtime, old_mtime))

    saved2, _ = hra.run_standard_figures(data, hil, cfg, dest, p)  # no force

    assert saved1[0] in saved2
    assert png.stat().st_mtime > old_mtime
    assert not png.with_name(png.name + ".tmp").exists()


def test_needs_render_true_when_png_missing(tmp_path):
    assert hra._needs_render(tmp_path / "missing.png", tmp_path / "x.csv") \
        is True


def test_needs_render_true_when_png_older_than_csv(tmp_path):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("a")
    png = tmp_path / "x.png"
    png.write_bytes(b"PNG")
    now = time.time()
    os.utime(png, (now - 1000.0, now - 1000.0))
    os.utime(csv_path, (now, now))
    assert hra._needs_render(png, csv_path) is True


def test_needs_render_false_when_png_newer_than_csv(tmp_path):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("a")
    png = tmp_path / "x.png"
    png.write_bytes(b"PNG")
    now = time.time()
    os.utime(csv_path, (now - 1000.0, now - 1000.0))
    os.utime(png, (now, now))
    assert hra._needs_render(png, csv_path) is False


def test_needs_render_true_when_forced_even_if_fresh(tmp_path):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("a")
    png = tmp_path / "x.png"
    png.write_bytes(b"PNG")
    now = time.time()
    os.utime(png, (now + 1000.0, now + 1000.0))  # "newer" than the CSV
    assert hra._needs_render(png, csv_path, force=True) is True


def test_save_writes_png_atomically_no_tmp_residue(tmp_path):
    fig = plt.figure()
    out = tmp_path / "fig.png"
    hra._save(fig, out)
    assert out.exists()
    assert out.stat().st_size > 0
    assert not out.with_name(out.name + ".tmp").exists()


def test_hil_state_and_switches_carries_hil_banner_in_suptitle():
    n = 5
    data = {"t_s": np.arange(n, dtype=np.float64),
           "state": np.full(n, 2.0), "switch": np.full(n, 0x3F),
           "aux": np.full(n, 0x0F), "fault_flags": np.zeros(n)}
    fig = hra.hil_state_and_switches(data, {"_hil_build": True,
                                            "_run_name": "run"})
    assert "HIL_SIM LOG" in fig._suptitle.get_text()


def test_hil_state_and_switches_no_banner_when_flag_false():
    n = 3
    data = {"t_s": np.arange(n, dtype=np.float64),
           "state": np.full(n, 2.0), "switch": np.zeros(n),
           "aux": np.zeros(n), "fault_flags": np.zeros(n)}
    fig = hra.hil_state_and_switches(data, {"_hil_build": False,
                                            "_run_name": "run"})
    assert "HIL_SIM" not in fig._suptitle.get_text()


def test_hil_charger_and_soc_returns_none_without_charger_columns():
    data = {"t_s": np.arange(3, dtype=np.float64)}
    assert hra.hil_charger_and_soc(data, {}) is None


# ── fw v24: the MPPT threshold overlay on the V_chg panel ─────────────────
#
# `mppt_thresh_cnt` is observation-frame byte 15 -- the Ag105 reg-0x02 count
# the firmware believes is in force. Converted to volts it is directly
# comparable to V_chg on the same axis, and the whole point of the fw v24
# round is that the dashed threshold must sit BELOW the solid rail. Absent
# and all-blank columns must skip the overlay, not draw a line at zero.

def _charger_data(n=6, thresh=None):
    data = {"t_s": np.arange(n, dtype=np.float64),
            "I_charge": np.full(n, 0.9),
            "ag105_status": np.full(n, float(0x58)),
            "V_chg": np.full(n, 13.4)}
    if thresh is not None:
        data["mppt_thresh_cnt"] = np.asarray(thresh, dtype=np.float64)
    return data


def _threshold_line(fig):
    """The dashed overlay's Line2D, or None -- searched across every axis
    (it lives on a twinx, which is a separate Axes on the same figure)."""
    for ax in fig.axes:
        for line in ax.get_lines():
            if line.get_label().startswith("MPPT threshold"):
                return line
    return None


def test_charger_figure_overlays_the_threshold_when_the_column_has_values():
    n = 4
    fig = hra.hil_charger_and_soc(_charger_data(n, thresh=[15] * n), {})
    assert fig is not None
    line = _threshold_line(fig)
    assert line is not None
    # 11.0 + 0.088 * 15 = 12.32 V -- and it is UNDER the 13.4 V rail, which is
    # the fw v24 condition the overlay exists to make readable.
    ys = np.asarray(line.get_ydata(), dtype=np.float64)
    assert np.allclose(ys, 12.32)
    assert np.all(ys < 13.4)
    assert line.get_linestyle() == "--"


def test_charger_figure_skips_the_overlay_when_the_column_is_absent():
    """A pre-fw-v24 CSV has no such column at all -- clean skip, figure fine."""
    fig = hra.hil_charger_and_soc(_charger_data(), {})
    assert fig is not None
    assert _threshold_line(fig) is None


def test_charger_figure_skips_the_overlay_when_the_column_is_all_blank():
    """A fw v21-v23 flash produces the column but never a value (16-byte
    frame -> mppt_cnt None -> blank cell -> NaN). Drawing an empty dashed
    line there would read as 'the threshold was zero'."""
    n = 5
    fig = hra.hil_charger_and_soc(_charger_data(n, thresh=[np.nan] * n), {})
    assert fig is not None
    assert _threshold_line(fig) is None


def test_charger_figure_nans_resistor_mode_counts_rather_than_extrapolating():
    """Counts >= 251 are external-resistor mode and have no volts value.

    Plotting 11 + 0.088*255 = 33.4 V would invent a threshold the register
    cannot express. The in-band samples still plot; the 255s are gaps.
    """
    fig = hra.hil_charger_and_soc(
        _charger_data(4, thresh=[255, 255, 19, 19]), {})
    line = _threshold_line(fig)
    assert line is not None
    ys = np.asarray(line.get_ydata(), dtype=np.float64)
    assert np.isnan(ys[0]) and np.isnan(ys[1])
    assert np.allclose(ys[2:], 11.0 + 0.088 * 19)


def test_charger_figure_skips_the_overlay_when_every_count_is_resistor_mode():
    """All-0xFF is 'never written' -- no threshold volts exist to draw."""
    fig = hra.hil_charger_and_soc(_charger_data(3, thresh=[255] * 3), {})
    assert fig is not None
    assert _threshold_line(fig) is None


def test_load_and_adapt_tolerate_the_new_column(tmp_path):
    """The loader is name-resolved, so a new column needs no loader change --
    pinned anyway, because that tolerance is what lets the schema grow.

    The adapter must simply IGNORE it: `mppt_thresh_cnt` has no
    decode_benchlog equivalent, so it belongs to the raw-HIL dict the
    HIL_FIGURES builders read, not to the adapted benchlog dict.
    """
    csv_path = tmp_path / "run.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t", "V_bus", "I_fc", "I_batt", "current",
                    "ag105_status", "mppt_thresh_cnt"])
        w.writerow(["0.000", "15.9", "0.5", "0.5", "1.0", "0x58", ""])
        w.writerow(["0.001", "15.9", "0.5", "0.5", "1.0", "0x58", "15"])
    data = hra.load_hil_csv(csv_path)
    assert "mppt_thresh_cnt" in data
    assert np.isnan(data["mppt_thresh_cnt"][0])      # blank -> NaN, not 0
    assert data["mppt_thresh_cnt"][1] == 15.0
    adapted = hra.adapt_to_benchlog(data)
    assert "mppt_thresh_cnt" not in adapted
    assert "I_cmd" in adapted                        # the adapter still works


# ── hil_share_raw_vs_emitted: the pre-clamp request (SDP round) ────────────
#
# Under sdp-v2 every table value in (0.85, 1.0] emits the SAME clamped 0.8500,
# so `cmd_share_sp` alone cannot distinguish one demand map from another.
# `cmd_share_sp_raw` is the column that can, and nothing plotted it.

def _share_raw_data(raw, n=6):
    return {"t_s": np.arange(n, dtype=np.float64),
            "cmd_share_sp_raw": np.asarray(raw, dtype=np.float64),
            "cmd_share_sp": np.full(n, 0.85),
            "I_fc": np.full(n, 0.85), "I_batt": np.full(n, 0.15)}


def test_hil_share_raw_vs_emitted_renders_when_the_raw_column_has_values():
    # Two in band (0.85 itself is IN — the firmware's cutoff is strict), one
    # over the high clamp, one under the low one.
    fig = hra.hil_share_raw_vs_emitted(
        _share_raw_data([0.85, 0.50, 1.00, 0.05], n=4), {})
    assert fig is not None
    # The clamp count is the figure's headline number, so it is asserted.
    assert "2/4 samples clamped" in fig._suptitle.get_text()


def test_hil_share_raw_vs_emitted_skips_when_the_column_is_absent():
    """A clean skip, not a figure drawn on nothing — the column is written
    only by strategies that HAVE a pre-clamp request."""
    data = {"t_s": np.arange(3, dtype=np.float64),
            "cmd_share_sp": np.full(3, 0.5)}
    assert hra.hil_share_raw_vs_emitted(data, {}) is None


def test_hil_share_raw_vs_emitted_skips_an_all_nan_column():
    """Every non-SDP run carries the column BLANK, which loads as all-NaN. A
    figure there would be an empty axes with a confident title."""
    n = 4
    data = {"t_s": np.arange(n, dtype=np.float64),
            "cmd_share_sp_raw": np.full(n, np.nan)}
    assert hra.hil_share_raw_vs_emitted(data, {}) is None


def test_hil_share_raw_vs_emitted_counts_only_finite_samples():
    """A partly-blank column must report its clamp count over the samples that
    exist, not over the row count."""
    n = 6
    raw = np.array([np.nan, np.nan, 1.0, 0.5, 0.5, np.nan])
    data = _share_raw_data(raw, n)
    fig = hra.hil_share_raw_vs_emitted(data, {})
    assert "1/3 samples clamped" in fig._suptitle.get_text()


def test_hil_share_raw_vs_emitted_clamp_band_matches_the_firmware_band():
    """The shaded band is the firmware's own cutoff band (.ino:9231-9257) and
    SocBandStrategy/SdpStrategy's emission clamp. Pinned literally: these are
    duplicated in this module on purpose (an offline report must not relabel
    an older trace with this checkout's constants), so nothing else would
    catch a drift."""
    assert (hra.SHARE_CLAMP_LO, hra.SHARE_CLAMP_HI) == (0.15, 0.85)


def test_hil_share_raw_vs_emitted_is_registered():
    assert "hil_share_raw_vs_emitted" in dict(hra.HIL_FIGURES)


# ── hil_h2_and_soc: hydrogen consumption + battery SoC (WP-D) ─────────────

def _h2_soc_data(n=None, soc=None, h2_cum=None, h2_sdp=None, h2_rate=None):
    if n is None:
        for candidate in (soc, h2_cum, h2_sdp, h2_rate):
            if candidate is not None:
                n = len(candidate)
                break
        else:
            n = 6
    data = {"t_s": np.arange(n, dtype=np.float64)}
    if soc is not None:
        data["soc"] = np.asarray(soc, dtype=np.float64)
    if h2_cum is not None:
        data["h2_cum_g"] = np.asarray(h2_cum, dtype=np.float64)
    if h2_sdp is not None:
        data["h2_sdp_cum_g"] = np.asarray(h2_sdp, dtype=np.float64)
    if h2_rate is not None:
        data["h2_rate_gps"] = np.asarray(h2_rate, dtype=np.float64)
    return data


def test_hil_h2_and_soc_skips_when_soc_absent():
    """A replay CSV carries neither soc nor h2 columns -- clean skip."""
    data = {"t_s": np.arange(4, dtype=np.float64)}
    assert hra.hil_h2_and_soc(data, {}) is None


def test_hil_h2_and_soc_skips_when_soc_all_nan():
    data = _h2_soc_data(soc=[np.nan] * 4)
    assert hra.hil_h2_and_soc(data, {}) is None


def test_hil_h2_and_soc_renders_both_columns_present():
    soc = np.linspace(0.70, 0.68, 6)
    h2 = np.linspace(0.0, 0.012345, 6)
    h2_sdp = np.linspace(0.0, 0.013000, 6)
    data = _h2_soc_data(soc=soc, h2_cum=h2, h2_sdp=h2_sdp)
    fig = hra.hil_h2_and_soc(data, {})
    assert fig is not None
    ax0, ax1 = fig.axes[0], fig.axes[-1]
    # final-value + delta_soc annotations are the headline numbers
    texts0 = " ".join(t.get_text() for t in ax0.texts)
    texts1 = " ".join(t.get_text() for t in ax1.texts)
    assert "0.012345" in texts0
    assert "0.013000" in texts0
    assert "delta_soc" in texts1
    assert "-0.020000" in texts1 or "-0.02" in texts1


def test_hil_h2_and_soc_soc_only_degraded_render_has_annotation():
    """Pre-2026-08-31 campaigns carry soc with no h2 columns at all. The H2
    panel must render an explicit note, never a silently empty axes."""
    data = _h2_soc_data(soc=np.linspace(0.65, 0.64, 5))
    fig = hra.hil_h2_and_soc(data, {})
    assert fig is not None
    ax0 = fig.axes[0]
    texts0 = " ".join(t.get_text() for t in ax0.texts)
    assert "not present" in texts0
    assert "2026-08-31" in texts0


def test_hil_h2_and_soc_proxy_overlay_absent_when_h2_sdp_missing():
    soc = np.linspace(0.70, 0.69, 5)
    h2 = np.linspace(0.0, 0.005, 5)
    data = _h2_soc_data(soc=soc, h2_cum=h2)
    fig = hra.hil_h2_and_soc(data, {})
    assert fig is not None
    ax0 = fig.axes[0]
    labels = [line.get_label() for line in ax0.get_lines()]
    assert not any("h2_sdp_cum_g" in lbl for lbl in labels)


def test_hil_h2_and_soc_proxy_overlay_skipped_when_all_nan():
    soc = np.linspace(0.70, 0.69, 5)
    h2 = np.linspace(0.0, 0.005, 5)
    data = _h2_soc_data(soc=soc, h2_cum=h2, h2_sdp=[np.nan] * 5)
    fig = hra.hil_h2_and_soc(data, {})
    assert fig is not None
    ax0 = fig.axes[0]
    labels = [line.get_label() for line in ax0.get_lines()]
    assert not any("h2_sdp_cum_g" in lbl for lbl in labels)


def test_hil_h2_and_soc_h2_rate_overlay_present_when_column_has_values():
    soc = np.linspace(0.70, 0.69, 5)
    h2 = np.linspace(0.0, 0.005, 5)
    rate = np.full(5, 0.0002)
    data = _h2_soc_data(soc=soc, h2_cum=h2, h2_rate=rate)
    fig = hra.hil_h2_and_soc(data, {})
    assert fig is not None
    # A twinx axes was added for the rate overlay: more than the base 2 axes.
    assert len(fig.axes) >= 3


def test_hil_h2_and_soc_soc0_marker_uses_first_finite_sample():
    """soc0 must come from the first FINITE sample, not index 0 blindly."""
    soc = np.array([np.nan, 0.70, 0.69, 0.68])
    h2 = np.array([np.nan, 0.0, 0.003, 0.006])
    data = _h2_soc_data(n=4, soc=soc, h2_cum=h2)
    fig = hra.hil_h2_and_soc(data, {})
    ax1 = fig.axes[-1]
    texts1 = " ".join(t.get_text() for t in ax1.texts)
    assert "soc0 = 0.700000" in texts1


def test_hil_h2_and_soc_is_registered():
    assert "hil_h2_and_soc" in dict(hra.HIL_FIGURES)


# ─────────────────────────────────────────────────────────────────────────
# 8. suite_result_for (F2)
# ─────────────────────────────────────────────────────────────────────────

def test_suite_result_for_scenario_prefers_mode_matching_entry():
    run = hra.RunSpec("scenario", "steady", Path("x.csv"),
                      scen_folder("steady"), "hifi")
    results = {"results": [
        {"kind": "scenario", "name": "steady", "mode": "simple",
         "passed": False},
        {"kind": "scenario", "name": "steady", "mode": "hifi",
         "passed": True},
    ]}
    r = hra.suite_result_for(results, run)
    assert r["mode"] == "hifi"
    assert r["passed"] is True


def test_suite_result_for_scenario_falls_back_to_name_only_match():
    run = hra.RunSpec("scenario", "steady", Path("x.csv"),
                      scen_folder("steady"), "hifi")
    results = {"results": [
        {"kind": "scenario", "name": "steady", "mode": "simple",
         "passed": False},
    ]}
    r = hra.suite_result_for(results, run)
    assert r is not None
    assert r["mode"] == "simple"  # only candidate, used as fallback


def test_suite_result_for_replay_never_mode_matched():
    run = hra.RunSpec("replay", "ML0146", Path("x.csv"),
                      replay_folder("ML0146"), None)
    results = {"results": [
        {"kind": "replay", "name": "ML0146", "mode": "deviation",
         "passed": True},
    ]}
    r = hra.suite_result_for(results, run)
    assert r is not None
    assert r["mode"] == "deviation"  # matched on name alone


def test_suite_result_for_no_match_returns_none():
    run = hra.RunSpec("scenario", "steady", Path("x.csv"),
                      scen_folder("steady"), "hifi")
    assert hra.suite_result_for({"results": []}, run) is None


def test_analyze_report_two_electrical_modes_both_in_summary(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady", mode="hifi", n=5)
    add_scenario_run(d, "steady", mode="simple", n=5)
    analyses, errors = hra.analyze_report(d, log=lambda *a, **k: None)
    assert errors == []
    folders = sorted(a["folder"] for a in analyses)
    assert folders == [scen_folder("steady", "hifi"),
                       scen_folder("steady", "simple")]
    summary_md = (d / "ANALYSIS_SUMMARY.md").read_text()
    assert scen_folder("steady", "hifi") in summary_md
    assert scen_folder("steady", "simple") in summary_md


# ─────────────────────────────────────────────────────────────────────────
# 9. Control-law provenance (F4)
# ─────────────────────────────────────────────────────────────────────────

def test_resolve_source_fw_header_wins_when_they_agree():
    fw, prov, note = hra.resolve_source_fw(23, 23)
    assert fw == 23
    assert prov == "decoded BLG header"
    assert note is None


def test_resolve_source_fw_header_wins_and_records_disagreement():
    fw, prov, note = hra.resolve_source_fw(14, 23)  # sidecar=14, header=23
    assert fw == 23
    assert prov == "decoded BLG header"
    assert note is not None
    assert "v23" in note and "v14" in note


def test_resolve_source_fw_sidecar_only_when_no_decoded_header():
    fw, prov, note = hra.resolve_source_fw(14, None)
    assert fw == 14
    assert prov == "meta.json sidecar (no decode)"
    assert note is None


def test_resolve_source_fw_unknown_when_neither_available():
    fw, prov, note = hra.resolve_source_fw(None, None)
    assert fw is None
    assert prov == "unknown"
    assert note is None


def test_law_caveat_unknown_fw_gets_unverified_hedge():
    caveat = hra._law_caveat(None)
    assert "UNVERIFIED" in caveat


def test_law_caveat_old_fw_gets_different_law_hedge_not_unverified():
    caveat = hra._law_caveat(14)
    assert "different wheel and control" in caveat
    assert "UNVERIFIED" not in caveat


def test_law_caveat_current_fw_gets_neither_hedge():
    caveat = hra._law_caveat(23)
    assert "UNVERIFIED" not in caveat
    assert "different wheel" not in caveat


def test_law_fields_unknown_fw_sets_control_law_known_false():
    fields = hra._law_fields(None, "unknown", None)
    assert fields["control_law_known"] is False
    assert fields["different_control_law"] is False
    assert "UNVERIFIED" in fields["caveat"]


def test_law_fields_known_old_fw_sets_different_control_law_true():
    fields = hra._law_fields(14, "decoded BLG header", None)
    assert fields["control_law_known"] is True
    assert fields["different_control_law"] is True


def test_analyze_run_replay_unknown_fw_end_to_end(tmp_path, monkeypatch):
    """F4: neither the sidecar nor the decoded header knows the source fw ->
    control_law_known False, UNVERIFIED hedge in the caveat and ANALYSIS.md,
    and a '?' (not '*') marker in the summary table row."""
    d = build_report(tmp_path)
    blg_path = add_source_blg(tmp_path, "ML0200")
    add_replay_run(d, "ML0200", blg_path=blg_path, blg_fw_version=None, n=10)
    monkeypatch.setattr(hra, "decode_source_blg",
                        lambda p: fake_blg_data(n=10, fw_version=None))
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    rep = analysis["replay"]
    assert rep["effective_fw_version"] is None
    assert rep["control_law_known"] is False
    assert rep["different_control_law"] is False
    assert "UNVERIFIED" in rep["caveat"]

    md = (d / replay_folder("ML0200") / "ANALYSIS.md").read_text()
    assert "UNVERIFIED" in md

    analyses, errors = hra.analyze_report(d, log=lambda *a, **k: None)
    assert errors == []
    summary_md = (d / "ANALYSIS_SUMMARY.md").read_text()
    row = next(l for l in summary_md.splitlines()
              if l.startswith("| %s " % replay_folder("ML0200")))
    assert "?" in row
    assert "*" not in row


def test_analyze_run_replay_header_disagrees_with_sidecar(tmp_path,
                                                          monkeypatch):
    """F4: the decoded header (23) wins over a stale sidecar value (14), and
    the disagreement is recorded, not silently resolved."""
    d = build_report(tmp_path)
    blg_path = add_source_blg(tmp_path, "ML0250")
    add_replay_run(d, "ML0250", blg_path=blg_path, blg_fw_version=14, n=10)
    monkeypatch.setattr(hra, "decode_source_blg",
                        lambda p: fake_blg_data(n=10, fw_version=23))
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    rep = analysis["replay"]
    assert rep["effective_fw_version"] == 23
    assert rep["fw_version_provenance"] == "decoded BLG header"
    assert rep["fw_version_disagreement"] is not None
    assert "v23" in rep["fw_version_disagreement"]
    assert "v14" in rep["fw_version_disagreement"]
    md = (d / replay_folder("ML0250") / "ANALYSIS.md").read_text()
    assert "WARNING" in md and "disagreement" in md


def test_render_summary_markdown_question_mark_for_unknown_control_law():
    analyses = [
        {"folder": "replay_ML0200", "kind": "replay", "suite_mode": None,
         "electrical_mode": None, "suite_passed": True, "obs_coverage": 1.0,
         "final_state": 2, "fault_names_post_grace": [],
         "replay": {"different_control_law": False,
                    "control_law_known": False,
                    "metrics": {"response": {"I_cmd": {"rms": 0.7,
                                                       "max_abs": 1.1}}}}},
    ]
    md = hra.render_summary_markdown({}, analyses, [])
    row = next(l for l in md.splitlines()
              if l.startswith("| replay_ML0200 "))
    assert "?" in row
    assert "*" not in row


# ─────────────────────────────────────────────────────────────────────────
# 10. Source-decode degradation (F5)
# ─────────────────────────────────────────────────────────────────────────

def test_analyze_run_replay_corrupt_blg_degrades_not_errors(tmp_path):
    """F5: a corrupt source .BLG (bad magic) must not cost the run its base
    figures or its analysis.json -- it degrades exactly like a missing
    source, with the decode error recorded."""
    d = build_report(tmp_path)
    blg_path = tmp_path / "ML0300.BLG"
    blg_path.write_bytes(b"NOT-A-REAL-BLG-FILE" + b"\x00" * 20)
    add_replay_run(d, "ML0300", blg_path=blg_path, blg_fw_version=23, n=10)
    # No monkeypatch: exercise the real decoder's rejection of bad magic.
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})  # must not raise
    rep = analysis["replay"]
    assert "source_decode_error" in rep
    assert "figures" not in rep
    assert analysis["figures"]  # base (non-replay) figures still rendered
    assert (d / replay_folder("ML0300") / "analysis.json").exists()
    md = (d / replay_folder("ML0300") / "ANALYSIS.md").read_text()
    assert "Source decode FAILED" in md


def test_analyze_report_corrupt_blg_run_is_not_counted_as_an_error(tmp_path):
    d = build_report(tmp_path)
    blg_path = tmp_path / "ML0301.BLG"
    blg_path.write_bytes(b"garbage")
    add_replay_run(d, "ML0301", blg_path=blg_path, n=10)
    analyses, errors = hra.analyze_report(d, log=lambda *a, **k: None)
    assert errors == []
    assert len(analyses) == 1
    assert "source_decode_error" in analyses[0]["replay"]


# ─────────────────────────────────────────────────────────────────────────
# 11. analyze_run / reports (per-run)
# ─────────────────────────────────────────────────────────────────────────

def test_analyze_run_scenario_writes_analysis_json_and_md(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady", n=10)
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    dest = d / scen_folder("steady")
    assert (dest / "analysis.json").exists()
    assert (dest / "ANALYSIS.md").exists()
    assert analysis["kind"] == "scenario"
    assert analysis["rows"] == 10
    assert analysis["figures"]


def test_analyze_run_replay_with_metrics_pre_v18_caveat(tmp_path, monkeypatch):
    d = build_report(tmp_path)
    blg_path = add_source_blg(tmp_path, "ML0100")
    add_replay_run(d, "ML0100", blg_path=blg_path, blg_fw_version=14, n=20)
    monkeypatch.setattr(hra, "decode_source_blg",
                        lambda p: fake_blg_data(n=20, fw_version=14))
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    rep = analysis["replay"]
    assert rep["different_control_law"] is True
    assert rep["control_law_known"] is True
    assert rep["effective_fw_version"] == 14
    assert rep["aligned_ticks"] > 0
    assert "different wheel and control" in rep["caveat"]

    md = (d / replay_folder("ML0100") / "ANALYSIS.md").read_text()
    assert "different wheel and control law" in md

    # De-vacuated: pin the '*' marker specifically on THIS run's summary row,
    # not merely "a '*' exists somewhere in the document" (which the marker
    # legend text alone would already satisfy).
    analyses, errors = hra.analyze_report(d, log=lambda *a, **k: None)
    assert errors == []
    summary_md = (d / "ANALYSIS_SUMMARY.md").read_text()
    row = next(l for l in summary_md.splitlines()
              if l.startswith("| %s " % replay_folder("ML0100")))
    assert "*" in row
    assert "?" not in row


def test_analyze_run_replay_source_missing_notes_and_skips_figures(tmp_path):
    d = build_report(tmp_path)
    add_replay_run(d, "ML9999", blg_path=None, n=5)
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    rep = analysis["replay"]
    assert rep["source_available"] is False
    assert "not found" in rep["note"]
    assert "figures" not in rep


def test_analyze_run_populates_fault_union_and_post_grace_split(tmp_path):
    d = build_report(tmp_path)
    csv_path = add_scenario_run(d, "faulted", n=10, dt=0.5, fault_flags=0)
    # Hand-edit one early row (t < grace) and one late row (t >= grace) with
    # different fault bits so the two unions provably differ.
    rows = list(csv.reader(open(csv_path)))
    header, body = rows[0], rows[1:]
    fault_col = header.index("fault_flags")
    body[0][fault_col] = "1"   # t=0.0 < grace
    body[-1][fault_col] = "2"  # t=4.5 >= grace
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(body)
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    assert analysis["fault_union"] == 1 | 2
    assert analysis["fault_union_post_grace"] == 2


def test_analyze_run_meta_status_interrupted_surfaces_in_analysis(tmp_path):
    d = build_report(tmp_path)
    csv_path = add_scenario_run(d, "steady", n=5)
    meta_path = Path(str(csv_path) + ".meta.json")
    meta = json.loads(meta_path.read_text())
    meta["status"] = "interrupted"
    meta_path.write_text(json.dumps(meta))
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    assert analysis["meta_status"] == "interrupted"
    md = (d / scen_folder("steady") / "ANALYSIS.md").read_text()
    assert "interrupted" in md


def test_analyze_run_meta_status_running_surfaces_in_analysis(tmp_path):
    d = build_report(tmp_path)
    csv_path = add_scenario_run(d, "steady", n=5)
    meta_path = Path(str(csv_path) + ".meta.json")
    meta = json.loads(meta_path.read_text())
    meta["status"] = "running"
    meta_path.write_text(json.dumps(meta))
    run = hra.discover_runs(d)[0]
    analysis = hra.analyze_run(run, d, {})
    assert analysis["meta_status"] == "running"


def test_render_run_markdown_suite_checks_table_and_pass_verdict():
    a = {"folder": "scenario_steady_hifi", "kind": "scenario",
        "electrical_mode": "hifi", "meta_mode": "scenario_hifi",
        "meta_status": "completed", "rows": 10, "duration_s": 1.0,
        "obs_coverage": 1.0, "obs_frames": 10, "final_state": 2,
        "fault_union": 0, "fault_names": [], "grace_s": 2.0,
        "fault_union_post_grace": 0, "fault_names_post_grace": [],
        "suite_passed": True,
        "suite_checks": [{"name": "final_state", "passed": True,
                          "detail": "state==2"}],
        "figures": ["tracking_subplots"], "skipped_figures": [],
        "warnings": []}
    md = hra.render_run_markdown(a)
    assert "PASS" in md
    assert "final_state" in md
    assert "tracking_subplots.png" in md


def test_render_summary_markdown_run_table_and_star_annotation():
    analyses = [
        {"folder": "scenario_steady_hifi", "kind": "scenario",
         "suite_mode": "conformance", "electrical_mode": "hifi",
         "suite_passed": True, "obs_coverage": 1.0, "final_state": 2,
         "fault_names_post_grace": [], "replay": None},
        {"folder": "replay_ML0100", "kind": "replay", "suite_mode": None,
         "electrical_mode": None, "suite_passed": False, "obs_coverage": 0.5,
         "final_state": 99, "fault_names_post_grace": ["OC_FC"],
         "replay": {"different_control_law": True,
                    "control_law_known": True,
                    "metrics": {"response": {"I_cmd": {"rms": 1.5,
                                                       "max_abs": 3.0}}}}},
    ]
    md = hra.render_summary_markdown({"date": "x", "target_fw": 23,
                                      "teensy_ip": "1.2.3.4", "port": 1,
                                      "electrical_pref": "hifi",
                                      "mode": "scenario"}, analyses, [])
    assert "scenario_steady_hifi" in md and "replay_ML0100" in md
    assert "1.5" in md  # rms
    row = next(l for l in md.splitlines() if l.startswith("| replay_ML0100 "))
    assert "*" in row
    assert "runs analyzed: 2" in md


def test_render_summary_markdown_errors_section_present_when_errors():
    md = hra.render_summary_markdown({}, [], [("scenario_bad", "boom")])
    assert "## Errors" in md
    assert "scenario_bad" in md and "boom" in md


# ─────────────────────────────────────────────────────────────────────────
# 12. load_run_config (F8)
# ─────────────────────────────────────────────────────────────────────────

def test_load_run_config_no_move_case_returns_defaults_without_writing_file(
        tmp_path):
    d = build_report(tmp_path)
    cfg = hra.load_run_config(d, d)  # dest == report_dir: the --no-move case
    assert cfg == json.loads(json.dumps(hra.bl_common.DEFAULT_CONFIG))
    assert not (d / "analysis_config.json").exists()


def test_load_run_config_normal_run_folder_writes_config_file(tmp_path):
    d = build_report(tmp_path)
    sub = d / scen_folder("steady")
    sub.mkdir()
    hra.load_run_config(sub, d)
    assert (sub / "analysis_config.json").exists()


def test_analyze_report_no_move_writes_no_analysis_config_in_parent(
        tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady", n=5)
    hra.analyze_report(d, no_move=True, log=lambda *a, **k: None)
    assert not (d / "analysis_config.json").exists()


# ─────────────────────────────────────────────────────────────────────────
# 13. CLI / driver
# ─────────────────────────────────────────────────────────────────────────

def test_analyze_report_one_failing_run_does_not_abort_others(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "good", n=8)
    bad_path = add_scenario_run(d, "bad", n=8)
    # Corrupt the "bad" run's CSV after the fact: truncate one row short.
    lines = bad_path.read_text().splitlines()
    lines[2] = lines[2].rsplit(",", 3)[0]  # drop trailing cells
    bad_path.write_text("\n".join(lines) + "\n")

    analyses, errors = hra.analyze_report(d, log=lambda *a, **k: None)
    assert len(errors) == 1
    assert errors[0][0] == scen_folder("bad")
    assert len(analyses) == 1
    assert analyses[0]["folder"] == scen_folder("good")
    assert (d / "ANALYSIS_SUMMARY.md").exists()


def test_analyze_report_no_move_leaves_layout_untouched(tmp_path):
    d = build_report(tmp_path)
    csv_path = add_scenario_run(d, "steady", n=5)
    hra.analyze_report(d, no_move=True, log=lambda *a, **k: None)
    assert csv_path.exists()  # still in the parent, never moved
    assert not (d / scen_folder("steady")).exists()


def test_analyze_report_runs_subset_by_name(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady", n=5)
    add_scenario_run(d, "step-load", n=5)
    analyses, errors = hra.analyze_report(d, only=["steady"],
                                          log=lambda *a, **k: None)
    assert [a["name"] for a in analyses] == ["steady"]
    assert errors == []


def test_analyze_report_runs_subset_by_folder_name(tmp_path):
    d = build_report(tmp_path)
    add_scenario_run(d, "steady", n=5)
    add_scenario_run(d, "step-load", n=5)
    analyses, _ = hra.analyze_report(
        d, only=[scen_folder("step-load")], log=lambda *a, **k: None)
    assert [a["name"] for a in analyses] == ["step-load"]


def test_resolve_report_dir_cwd_relative(tmp_path, monkeypatch):
    d = tmp_path / "myreport"
    d.mkdir()
    monkeypatch.chdir(tmp_path)
    assert hra.resolve_report_dir("myreport") == d.resolve()


def test_resolve_report_dir_repo_root_hil_results_fallback(monkeypatch,
                                                           tmp_path):
    fake_results = tmp_path / "HIL Results"
    fake_results.mkdir()
    target = fake_results / "hil_report_x"
    target.mkdir()
    monkeypatch.setattr(hra, "REPO_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path / "somewhere_else" if
                      (tmp_path / "somewhere_else").exists() else tmp_path)
    assert hra.resolve_report_dir("hil_report_x") == target.resolve()


def test_resolve_report_dir_missing_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.setattr(hra, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError):
        hra.resolve_report_dir("no-such-report-anywhere")


def test_main_returns_2_on_bad_report_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hra, "REPO_ROOT", tmp_path)
    rc = hra.main(["definitely-not-a-report"])
    assert rc == 2


def test_main_returns_1_when_any_run_errors(tmp_path, monkeypatch):
    d = build_report(tmp_path, dirname="hil_report_main_test")
    add_scenario_run(d, "good", n=5)
    bad = add_scenario_run(d, "bad", n=5)
    lines = bad.read_text().splitlines()
    lines[1] = lines[1].rsplit(",", 3)[0]
    bad.write_text("\n".join(lines) + "\n")
    rc = hra.main([str(d)])
    assert rc == 1


def test_main_returns_0_when_all_runs_succeed(tmp_path):
    d = build_report(tmp_path, dirname="hil_report_main_ok")
    add_scenario_run(d, "steady", n=5)
    rc = hra.main([str(d)])
    assert rc == 0


# ─────────────────────────────────────────────────────────────────────────
# 14. NotAReportError (F7)
# ─────────────────────────────────────────────────────────────────────────

def test_analyze_report_raises_not_a_report_error_on_empty_directory(
        tmp_path):
    d = tmp_path / "not_a_report_at_all"
    d.mkdir()
    with pytest.raises(hra.NotAReportError):
        hra.analyze_report(d, log=lambda *a, **k: None)
    assert not (d / "ANALYSIS_SUMMARY.md").exists()
    assert not (d / "analysis_summary.json").exists()


def test_analyze_report_with_only_results_json_is_not_an_error(tmp_path):
    """A report with zero runs but a real results.json (a suite run that
    produced no artifacts, or an already-fully-analyzed empty subset) is
    still a legitimate report folder."""
    d = build_report(tmp_path)
    hra.write_json_atomic(d / "results.json", make_results_json([]))
    analyses, errors = hra.analyze_report(d, log=lambda *a, **k: None)
    assert analyses == [] and errors == []
    assert (d / "ANALYSIS_SUMMARY.md").exists()


def test_main_returns_2_on_report_dir_with_no_runs_and_no_results_json(
        tmp_path):
    d = tmp_path / "hil_report_empty"
    d.mkdir()
    rc = hra.main([str(d)])
    assert rc == 2
    assert not (d / "ANALYSIS_SUMMARY.md").exists()
    assert not (d / "analysis_summary.json").exists()


# ─────────────────────────────────────────────────────────────────────────
# 15. Atomicity / integrity
# ─────────────────────────────────────────────────────────────────────────

def test_source_csv_bytes_identical_after_analysis(tmp_path):
    d = build_report(tmp_path)
    csv_path = add_scenario_run(d, "steady", n=10)
    original_bytes = csv_path.read_bytes()
    hra.analyze_report(d, log=lambda *a, **k: None)
    moved = d / scen_folder("steady") / csv_path.name
    assert moved.read_bytes() == original_bytes


def test_write_json_atomic_no_leftover_tmp_file(tmp_path):
    out = tmp_path / "x.json"
    hra.write_json_atomic(out, {"a": 1})
    assert out.exists()
    assert not out.with_name(out.name + ".tmp").exists()
    assert json.loads(out.read_text()) == {"a": 1}


def test_write_text_atomic_no_leftover_tmp_file(tmp_path):
    out = tmp_path / "x.md"
    hra.write_text_atomic(out, "hello\n")
    assert out.exists()
    assert not out.with_name(out.name + ".tmp").exists()
    assert out.read_text() == "hello\n"


# ─────────────────────────────────────────────────────────────────────────
# 16. End-to-end
# ─────────────────────────────────────────────────────────────────────────

def test_end_to_end_synthetic_report_full_artifact_set_and_idempotent(
        tmp_path, monkeypatch):
    # Deliberately put a space in the fixture directory name (Windows-path
    # trap) and use a report dirname resembling the real convention.
    root = tmp_path / "HIL Results dir"
    root.mkdir()
    d = root / "hil_report_20260830_120000"
    d.mkdir()

    add_scenario_run(d, "steady", n=15, state=2)
    add_scenario_run(d, "step-load", n=15, state=2)
    blg_path = add_source_blg(tmp_path, "ML0146")
    add_replay_run(d, "ML0146", blg_path=blg_path, n=15, blg_fw_version=23)

    monkeypatch.setattr(hra, "decode_source_blg",
                        lambda p: fake_blg_data(n=15, fw_version=23))

    results_json = make_results_json([
        {"kind": "scenario", "name": "steady", "mode": "hifi",
         "cmd_mode": "sim", "passed": True,
         "checks": [{"name": "final_state", "passed": True, "detail": ""}]},
        {"kind": "scenario", "name": "step-load", "mode": "hifi",
         "cmd_mode": "sim", "passed": False,
         "checks": [{"name": "no_fault", "passed": False, "detail": "OC"}]},
        {"kind": "replay", "name": "ML0146", "mode": None,
         "cmd_mode": "sim", "passed": True, "checks": []},
    ])
    hra.write_json_atomic(d / "results.json", results_json)

    analyses, errors = hra.analyze_report(d, log=lambda *a, **k: None)
    assert errors == []
    assert len(analyses) == 3

    for folder in (scen_folder("steady"), scen_folder("step-load"),
                  replay_folder("ML0146")):
        sub = d / folder
        assert (sub / "analysis.json").exists()
        assert (sub / "ANALYSIS.md").exists()
        assert sub.is_dir()

    assert (d / "ANALYSIS_SUMMARY.md").exists()
    assert (d / "analysis_summary.json").exists()
    summary = json.loads((d / "analysis_summary.json").read_text())
    assert len(summary["runs"]) == 3
    assert summary["errors"] == []

    # Idempotence: re-run over the now-moved layout and get the same run set,
    # no duplication, no errors.
    analyses2, errors2 = hra.analyze_report(d, log=lambda *a, **k: None)
    assert errors2 == []
    assert sorted(a["folder"] for a in analyses2) == \
        sorted(a["folder"] for a in analyses)
    # No stray parent-level copies were created by the second pass.
    parent_csvs = list(d.glob("hil_*.csv"))
    assert parent_csvs == []


# ---------------------------------------------------------------------------
# EMS strategy ROLE labelling (2026-09-01)
# ---------------------------------------------------------------------------

def _analysis_stub(**over):
    a = {"folder": "scenario_ems-sdp_hifi", "kind": "scenario",
         "electrical_mode": "hifi", "meta_mode": "scenario_hifi",
         "meta_status": "completed", "rows": 10, "duration_s": 1.0,
         "obs_coverage": 1.0, "obs_frames": 10, "final_state": 2,
         "fault_union": 0, "fault_names": [], "grace_s": 2.0,
         "fault_union_post_grace": 0, "fault_names_post_grace": [],
         "suite_passed": True, "suite_checks": [],
         "figures": [], "skipped_figures": [], "warnings": []}
    a.update(over)
    return a


def test_ems_strategy_role_reads_the_sim_registry():
    """The role is LOOKED UP, never copied -- a second table here could let a
    demonstration run be labelled a frontier one after somebody moved the role
    in hil_plant_sim and not here."""
    assert hra.ems_strategy_role("sdp-v3") == "frontier"
    assert hra.ems_strategy_role("soc-band") == "frontier"
    assert hra.ems_strategy_role("dp-replay") == "frontier"
    assert hra.ems_strategy_role("sdp-v2") == "demonstration"
    assert hra.ems_strategy_role("hold-5050") == "demonstration"
    # No strategy at all, and a strategy this checkout does not know: NO label
    # rather than an assertion into either camp.
    assert hra.ems_strategy_role(None) is None
    assert hra.ems_strategy_role("") is None
    assert hra.ems_strategy_role("strategy-from-an-older-checkout") is None


def test_render_run_markdown_labels_a_demonstration_run():
    md = hra.render_run_markdown(
        _analysis_stub(folder="scenario_ems-sdp-cross_hifi",
                       ems_strategy="sdp-v2", ems_role="demonstration"))
    assert "- EMS strategy: `sdp-v2` (demonstration)" in md
    assert "DYNAMICS DEMONSTRATION" in md
    assert "frontier_eligible: False" in md


def test_render_run_markdown_labels_a_frontier_run_without_the_banner():
    md = hra.render_run_markdown(
        _analysis_stub(ems_strategy="sdp-v3", ems_role="frontier"))
    assert "- EMS strategy: `sdp-v3` (frontier)" in md
    assert "DYNAMICS DEMONSTRATION" not in md


def test_render_run_markdown_omits_the_line_for_a_non_ems_run():
    md = hra.render_run_markdown(_analysis_stub(folder="scenario_steady_hifi"))
    assert "EMS strategy" not in md
    assert "DYNAMICS DEMONSTRATION" not in md
