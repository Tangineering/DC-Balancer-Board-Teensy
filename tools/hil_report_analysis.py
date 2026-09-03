#!/usr/bin/env python3
"""Post-process an HIL suite report folder into per-run analysis packages.

Given a report folder produced by tools/run_hil_suite.py (a flat directory of
hil_scenario_*.csv / hil_replay_*.csv, their .meta.json / .events.jsonl
sidecars, the per-run child logs, and the shared REPORT.md / results.json /
plan.json / HIL_FINDINGS.md), this tool:

  1. Reorganizes each run's files into a per-run subfolder -- scenario_<name>
     or replay_<LOG>. Shared files stay in the parent. The move is idempotent:
     a second invocation finds the already-moved runs in their subfolders and
     re-analyzes them in place.
  2. Renders the bench-log figure pipeline (tools/benchlog_analysis/figures.py)
     against the HIL CSV, through an adapter that maps the HIL column schema
     onto the decode_benchlog data-dict schema. Builders whose signals the HIL
     CSV cannot supply (encoder diagnostics, drive-controller conditioning,
     ...) are skipped, not errors.
  3. Adds HIL-specific figures: firmware state / switch / aux / fault lanes,
     and the charger + SoC view.
  4. For replay runs, decodes the source .BLG and produces an overlay figure,
     an injection-fidelity residual figure, and a response-deviation figure
     with RMS / max |delta| metrics.
  5. Writes analysis.json + ANALYSIS.md per run, and ANALYSIS_SUMMARY.md +
     analysis_summary.json + two summary figures in the parent.

Usage:
    python tools/hil_report_analysis.py "HIL Results/hil_report_20260830_203006"
    python tools/hil_report_analysis.py hil_report_20260830_203006 --runs steady
    python tools/hil_report_analysis.py <dir> --no-move --force

Requires numpy and matplotlib (the benchlog venv has both; .venv_hil does
not). Never mutates a source CSV, results.json or REPORT.md.

REPLAY IS OPEN LOOP (docs addendum 2026-08-27b): the firmware's commands do
not influence the replayed trajectory, so a response deviation is a character
comparison, not a closed-loop tracking error. A source log from fw < 18 was
recorded on the 120-slot wheel under a different control law; its response
comparison is labelled accordingly everywhere it appears.
"""
from __future__ import annotations

import argparse
import csv as _csv
import json
import math
import os
import shutil
import sys
import traceback
from pathlib import Path

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "hil_report_analysis requires numpy (missing: %s). Use an interpreter "
        "that has numpy and matplotlib -- .venv_hil is stdlib-only; the "
        "benchlog venv (.venv_benchlog) carries both." % exc) from exc

# `np.trapezoid` is numpy >= 2 (L7, review 2026-09-02); `np.trapz` is the
# numpy 1.x spelling and is REMOVED in 2.x, so neither name alone is portable
# across the interpreters this repo uses. Resolve once, here, rather than at
# each call site.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz

# tools/hil_report_analysis.py -> tools -> repo root
TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from benchlog_analysis import common as bl_common
    from benchlog_analysis import figures as bl_figures
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "hil_report_analysis requires matplotlib via "
        "tools/benchlog_analysis/figures.py (missing: %s). Use an interpreter "
        "with numpy + matplotlib installed." % exc) from exc

plt = bl_figures.plt
COLORS = bl_figures.COLORS
TEXT_COLOR = bl_figures.TEXT_COLOR
DPI_DEFAULT = bl_figures.DPI_DEFAULT

HIL_RESULTS_DIRNAME = "HIL Results"

# Electrical-mode suffixes that run_hil_suite appends to a scenario CSV name
# (hil_scenario_<name>_<mode>.csv). A scenario name itself never contains an
# underscore -- the suite's SCENARIOS keys are hyphenated -- but stripping a
# known suffix rather than splitting on the last "_" keeps that assumption
# from silently corrupting a future underscored name.
ELECTRICAL_MODES = ("hifi", "simple")

# Source-log firmware below this was recorded on the 120-slot wheel and under
# a pre-general-Hanus control law (CLAUDE.md fw v18 addendum).
DIFFERENT_LAW_FW = 18

# Total-current floor below which the measured share ratio is meaningless
# (mirrors tools/hil_dashboard.py's 50 mA gate).
SHARE_I_MIN_A = 0.05

# Colour for a source-of-truth SD-log overlay trace: recessive grey, so the
# HIL trace stays the subject of the plot.
OVERLAY_COLOR = "#8a8a8a"
OVERLAY_LW = 0.9

FIGSIZE_STACK3 = (10, 9.5)
FIGSIZE_STACK4 = (10, 11.5)


# ==========================================================================
# Firmware bit tables (imported, never copied)
# ==========================================================================

def _plant_sim_module():
    """tools/hil_plant_sim.py, imported lazily (no import-time cost)."""
    import hil_plant_sim
    return hil_plant_sim


def _replay_suite_module():
    """tools/hil_replay_suite.py, imported lazily."""
    import hil_replay_suite
    return hil_replay_suite


def _ems_comparison_module():
    """tools/hil_ems_comparison.py, imported lazily.

    Deferred because that module imports THIS one: resolving the cycle at
    call time rather than at import time keeps both modules importable on
    their own.
    """
    import hil_ems_comparison
    return hil_ems_comparison


def ems_strategy_role(strategy_name):
    """("frontier"|"demonstration"|None) for an EMS strategy name.

    Reads hil_plant_sim.EMS_STRATEGY_META, not a copy: this module renders
    reports for runs the CURRENT checkout produced, and a run's own meta
    sidecar records the strategy name it used, so the role lookup is the one
    place the two must agree.  Returns None for a run with no EMS strategy and
    for a strategy this checkout does not know — an unknown name gets NO role
    label rather than being asserted into either camp, since the honest reading
    of "a strategy that no longer exists here" is "unclassified".
    """
    if not strategy_name:
        return None
    try:
        meta = _plant_sim_module().EMS_STRATEGY_META
    except (ImportError, AttributeError):     # older sim in the checkout
        return None
    if strategy_name not in meta:
        return None
    return "frontier" if meta[strategy_name].get("frontier_eligible") \
        else "demonstration"


def switch_bits():
    """[(mask, name)] for the observation frame's switch byte, ordered LSB
    first. Names are the SW_* constant names from hil_plant_sim, verbatim."""
    m = _plant_sim_module()
    return [(m.SW_FC_BUS, "FC_BUS"), (m.SW_BT_BUS, "BT_BUS"),
            (m.SW_MOT_PWR, "MOT_PWR"), (m.SW_REGEN, "REGEN"),
            (m.SW_FC_CHARGE, "FC_CHARGE"), (m.SW_BT_SEQ, "BT_SEQ")]


def aux_bits():
    """[(mask, name)] for the observation frame's aux byte, LSB first.

    Bits 0-3 are pin levels. Bits 4-5 (fw v26) are NOT: they mirror the source
    current-ceiling governor's per-channel clamp state, which is why their
    names read as states rather than as nets. They are appended, so every
    established lane in the aux panel of hil_state_and_switches() keeps its
    row and two new lanes appear above them. Masks come from hil_plant_sim so
    the two can never drift.
    """
    m = _plant_sim_module()
    return [(m.AUX_FC_REG, "FC_REG"), (m.AUX_BT_REG, "BT_REG"),
            (m.AUX_MPPT_DISABLE, "MPPT_DISABLE"),
            (m.AUX_CBAL_DISABLE, "CBAL_DISABLE"),
            (m.AUX_FC_CEILING, "fc_ceiling_active"),
            (m.AUX_BT_CEILING, "bt_ceiling_active")]


def fault_names():
    """{bit: name} from hil_replay_suite.FAULT_NAMES (the .ino FAULT_* set)."""
    return dict(_replay_suite_module().FAULT_NAMES)


def decode_fault_bits(flags):
    """Sorted fault names for an integer fault_flags word; [] when zero."""
    flags = int(flags)
    if flags == 0:
        return []
    names = [n for b, n in sorted(fault_names().items()) if flags & b]
    residual = flags & ~sum(fault_names())
    if residual:
        names.append("0x%04X" % residual)
    return names


def mdac_fraction(word):
    """0..1 droop-gain fraction from a raw AD5443 command word.

    Delegates to hil_plant_sim.mdac_fraction so the two can never drift.
    VERIFIED EQUIVALENCE with the BLG column: the firmware logs
    droop_gain_FC_actual (a 0..1 float) as the BLG `gFC` field, and
    setDroopMdac() (.ino:9979) writes MDAC_CMD_LOAD_UPDATE | (uint16)(clamp(g,
    0, 1) * MDAC_res) with MDAC_res = 4095. Recovering (word & 0x0FFF)/4095
    therefore returns the same quantity as the decoder's gFC, up to the one
    LSB (2.4e-4) lost to the firmware's truncating cast. A word whose control
    nibble is not load-and-update never reached the DAC register and maps to
    0.0, matching hil_plant_sim's convention.
    """
    return _plant_sim_module().mdac_fraction(int(word))


# ==========================================================================
# Report / run discovery
# ==========================================================================

class RunSpec:
    """One run's identity and file set inside a report folder."""

    def __init__(self, kind, name, csv_path, folder_name, elec_mode=None):
        self.kind = kind                  # "scenario" | "replay"
        self.name = name                  # "steady" | "ML0146"
        self.csv_path = Path(csv_path)
        # "scenario_steady_hifi" | "replay_ML0146"
        self.folder_name = folder_name
        self.elec_mode = elec_mode        # "hifi"/"simple" for scenarios
        self.moved = False                # already inside its subfolder?

    @property
    def key(self):
        """Identity within one report. The electrical mode is PART of it:
        a suite run with both --electrical simple and hifi writes
        hil_scenario_steady_simple.csv AND hil_scenario_steady_hifi.csv into
        the same folder, and keying on (kind, name) alone would silently drop
        one of them."""
        return (self.kind, self.name, self.elec_mode or "")

    @property
    def label(self):
        """Human-readable run identity for reports (== folder_name)."""
        return self.folder_name

    @property
    def meta_path(self):
        return self.csv_path.with_name(self.csv_path.name + ".meta.json")

    @property
    def events_path(self):
        return self.csv_path.with_name(self.csv_path.name + ".events.jsonl")

    def log_name(self):
        return "run_%s_%s.log" % (self.kind, self.name)

    def __repr__(self):  # pragma: no cover - debugging aid
        return "RunSpec(%s, %s)" % (self.kind, self.name)


def parse_csv_name(csv_name):
    """Parse a run CSV file name into (kind, name, elec_mode) or None.

    hil_scenario_steady_hifi.csv -> ("scenario", "steady", "hifi")
    hil_replay_ML0146.csv        -> ("replay", "ML0146", None)
    """
    if not csv_name.endswith(".csv"):
        return None
    stem = csv_name[:-4]
    if stem.startswith("hil_scenario_"):
        rest = stem[len("hil_scenario_"):]
        for mode in ELECTRICAL_MODES:
            if rest.endswith("_" + mode):
                return ("scenario", rest[:-(len(mode) + 1)], mode)
        return ("scenario", rest, None)
    if stem.startswith("hil_replay_"):
        return ("replay", stem[len("hil_replay_"):], None)
    return None


def folder_name_for(kind, name, elec_mode=None):
    """Deterministic subfolder name for a run, derived from the CSV stem.

    scenario_steady_hifi / scenario_steady_simple / replay_ML0146. The
    electrical mode is in the SCENARIO name because one report can hold both
    modes of the same scenario; a replay CSV has no mode component, so replay
    folders are unchanged.
    """
    if elec_mode:
        return "%s_%s_%s" % (kind, name, elec_mode)
    return "%s_%s" % (kind, name)


def resolve_report_dir(arg):
    """Resolve a report-dir argument against CWD, then repo-root HIL Results.

    Raises ValueError when neither candidate exists.
    """
    cand = Path(arg)
    if cand.is_dir():
        return cand.resolve()
    if not cand.is_absolute():
        alt = REPO_ROOT / HIL_RESULTS_DIRNAME / arg
        if alt.is_dir():
            return alt.resolve()
    raise ValueError(
        "report directory not found: %s (also tried %s)"
        % (arg, REPO_ROOT / HIL_RESULTS_DIRNAME / arg))


def discover_runs(report_dir):
    """Every run in report_dir, from the parent AND existing subfolders.

    A run found in its subfolder is returned with moved=True. A run whose CSV
    exists in BOTH places is returned once, as the subfolder copy (moved=True)
    -- move_run_files() then leaves the parent copy alone and warns.
    Runs are keyed by RunSpec.key, i.e. (kind, name, electrical mode), so the
    two electrical modes of one scenario are two distinct runs.
    Returns a list sorted by that key.
    """
    report_dir = Path(report_dir)
    found = {}

    # Already-moved runs first, so they win the key.
    for sub in sorted(p for p in report_dir.iterdir() if p.is_dir()):
        for csv_path in sorted(sub.glob("*.csv")):
            parsed = parse_csv_name(csv_path.name)
            if parsed is None:
                continue
            kind, name, mode = parsed
            if sub.name != folder_name_for(kind, name, mode):
                continue
            run = RunSpec(kind, name, csv_path, sub.name, mode)
            run.moved = True
            found[run.key] = run

    for csv_path in sorted(report_dir.glob("*.csv")):
        parsed = parse_csv_name(csv_path.name)
        if parsed is None:
            continue
        kind, name, mode = parsed
        run = RunSpec(kind, name, csv_path,
                      folder_name_for(kind, name, mode), mode)
        if run.key in found:
            continue
        found[run.key] = run

    return [found[k] for k in sorted(found)]


def move_run_files(run, report_dir):
    """Move run's CSV, sidecars and child log into its subfolder.

    Returns (dest_dir, warnings). Idempotent: a run already in its subfolder
    still gets its stragglers collected -- a child log left in the parent, or
    a sidecar orphaned there by an interrupted earlier move (the CSV, meta and
    events move one at a time, so a crash between them strands the rest).
    A source whose destination already exists is LEFT IN PLACE and warned
    about -- data is never overwritten or deleted.

    NOTE (theoretical, no behaviour attached): run names are compared
    case-sensitively while Windows and macOS filesystems are not, so two runs
    differing only in case (ml0146 vs ML0146) would target one folder. The
    suite emits a single canonical case per log, so no such pair exists;
    handling it would need a case-folded collision check here.
    """
    report_dir = Path(report_dir)
    dest = report_dir / run.folder_name
    dest.mkdir(parents=True, exist_ok=True)
    warnings = []

    candidates = []
    if run.moved:
        # The run is already in its subfolder. A same-named file still in the
        # parent is one of two things:
        #   * its destination EXISTS too -- a genuine duplicate (a re-run of
        #     the suite, a hand copy). Left exactly where it is and reported;
        #     never merged in over the copy being analyzed.
        #   * its destination does NOT exist -- an ORPHAN from an interrupted
        #     move. Healed here by moving it in, which is what the previous
        #     invocation would have done had it finished.
        for name in (run.csv_path.name, run.meta_path.name,
                     run.events_path.name):
            stray = report_dir / name
            if not stray.exists():
                continue
            if (dest / name).exists():
                warnings.append(
                    "%s exists in BOTH the parent and %s -- analyzing the "
                    "subfolder copy; the parent copy at %s was left untouched"
                    % (name, run.folder_name, stray))
            else:
                warnings.append(
                    "%s was orphaned in the parent by an interrupted move -- "
                    "moved into %s" % (name, run.folder_name))
                candidates.append(stray)
    else:
        for p in (run.csv_path, run.meta_path, run.events_path):
            if p.exists():
                candidates.append(p)
    # The child log lives in the parent under its own name whether or not the
    # CSV has already moved. Its name carries no electrical mode, so if one
    # report somehow holds both modes of a scenario the log follows whichever
    # mode is processed first and the other run simply has none -- the log is
    # never copied, so nothing is duplicated or lost.
    log_src = report_dir / run.log_name()
    if log_src.exists():
        candidates.append(log_src)

    for src in candidates:
        dst = dest / src.name
        if dst.exists():
            if src.resolve() != dst.resolve():
                warnings.append(
                    "%s already exists in %s -- left the parent copy at %s"
                    % (src.name, run.folder_name, src))
            continue
        try:
            os.replace(src, dst)
        except OSError:
            shutil.move(str(src), str(dst))

    if not run.moved:
        run.csv_path = dest / run.csv_path.name
        run.moved = True
    return dest, warnings


# ==========================================================================
# HIL CSV loading and adaptation
# ==========================================================================

def load_hil_csv(csv_path):
    """Parse an HIL sim CSV into {column: float64 array} plus t_s.

    Columns are resolved BY NAME (a simple-electrical scenario CSV lacks elec_*;
    a replay CSV lacks soc and adds replay_rec), blank cells become NaN, and
    `ag105_status` is parsed from its 0x-hex text. `t_s` is a copy of `t` -- the
    simulator already writes seconds from run start.

    NOTE (2026-08-30): a replay CSV DOES carry cmd_v_sp/cmd_share_sp now -- they
    were appended unconditionally to the replay schema when --replay-commands
    landed -- but they are blank (all-NaN) unless that flag was passed. See
    adapt_to_benchlog(), which drops an all-NaN cmd_* column rather than emit one.
    """
    csv_path = Path(csv_path)
    with open(csv_path, "r", newline="") as f:
        reader = _csv.reader(f)
        header = next(reader)
        rows = list(reader)

    n = len(rows)
    data = {col: np.full(n, np.nan, dtype=np.float64) for col in header}
    for i, row in enumerate(rows):
        if len(row) != len(header):
            raise ValueError(
                "%s: row %d has %d cells, expected %d -- partial/corrupt CSV"
                % (csv_path, i + 2, len(row), len(header)))
        for col, cell in zip(header, row):
            if cell == "":
                continue
            if col == "ag105_status":
                data[col][i] = float(int(cell, 16))
            else:
                data[col][i] = float(cell)

    data["t_s"] = (data["t"].copy() if "t" in data
                   else np.arange(n, dtype=np.float64) / 1000.0)
    return data


def _mdac_column(words):
    """Vectorized mdac_fraction over a float array of raw command words."""
    out = np.full(words.shape, np.nan, dtype=np.float64)
    for i, w in enumerate(words):
        if np.isfinite(w):
            out[i] = mdac_fraction(int(w))
    return out


def adapt_to_benchlog(hil):
    """Map an HIL CSV dict onto the decode_benchlog data-dict schema.

    Only signals the HIL observation/injection frames actually carry are
    emitted; there is no HIL equivalent of u_unsat, drive_x0 or any encoder
    diagnostic, so those keys are simply absent and the figure builders that
    need them decline (KeyError or a None return, both handled by the caller).

    `flags` is synthesized as 0x40 on every sample -- bit6, the firmware's
    HIL_SIM build flag (fw v21). NOTE that no figure builder reads it: this
    tool does not go through make_figures.make_all(), so
    hil_build_from_data() is never called, and the red "HIL_SIM LOG" banner
    comes from analyze_run() setting cfg["_hil_build"] = True directly (every
    run here is by definition a HIL run). The column is kept because it makes
    the adapted dict self-describing for any consumer that DOES apply the
    decode_benchlog flags convention -- it is provenance data, not a live
    pathway.
    """
    n = hil["t_s"].shape[0]
    out = {"t_s": hil["t_s"].copy()}

    direct = {"V_bus": "V_bus", "V_fc": "V_fc", "V_batt": "V_batt",
              "V_chg": "V_chg", "V_rgn": "V_rgn", "I_fc": "I_fc",
              "I_batt": "I_batt", "fault_flags": "fault_flags"}
    for dst, src in direct.items():
        if src in hil:
            out[dst] = hil[src].copy()

    if "v_actual" in hil:
        out["v_act"] = hil["v_actual"].copy()
    if "current" in hil:
        out["I_cmd"] = hil["current"].copy()
    if "mdac_fc" in hil:
        out["gFC"] = _mdac_column(hil["mdac_fc"])
    if "mdac_bt" in hil:
        out["gBT"] = _mdac_column(hil["mdac_bt"])
    # L4: a replay CSV now carries cmd_v_sp/cmd_share_sp too, but they are BLANK
    # (-> all-NaN) on a plain --replay, where no commander exists. Emitting an
    # all-NaN column would replace the clean "column absent -> figure skipped"
    # path with a figure drawn on nothing, so drop it instead. A --replay-commands
    # run, and every simulated run with a commander, has real values and is
    # unaffected.
    for _src, _dst in (("cmd_v_sp", "v_sp"), ("cmd_share_sp", "share_sp")):
        if _src in hil and not np.all(np.isnan(hil[_src])):
            out[_dst] = hil[_src].copy()

    if "I_fc" in hil and "I_batt" in hil:
        out["share_act"] = share_actual(hil["I_fc"], hil["I_batt"])

    out["flags"] = np.full(n, float(0x40), dtype=np.float64)
    return out


def share_actual(i_fc, i_batt, i_min_a=SHARE_I_MIN_A):
    """I_fc / (I_fc + I_batt), NaN where the total is below i_min_a.

    Mirrors tools/hil_dashboard.py's 50 mA gate: below it the ratio is
    numerically dominated by the INA offset and reads as noise.
    """
    total = i_fc + i_batt
    with np.errstate(divide="ignore", invalid="ignore"):
        share = i_fc / total
    share = np.where(np.abs(total) < i_min_a, np.nan, share)
    return share


# ==========================================================================
# Source-BLG decoding and alignment (replay runs)
# ==========================================================================

def locate_source_blg(meta, report_dir=None):
    """Path to a replay's source .BLG, or None.

    meta["replay_source"]["path"] first (as recorded by the simulator), then
    the repo-root logs/<basename> fallback for a report copied off the
    machine that produced it.
    """
    src = (meta or {}).get("replay_source") or {}
    path = src.get("path")
    if path:
        p = Path(path)
        if p.is_file():
            return p
    basename = src.get("basename")
    if basename:
        p = REPO_ROOT / "logs" / basename
        if p.is_file():
            return p
    return None


def decode_source_blg(blg_path):
    """Decode a .BLG into (data_dict, header_dict) without touching disk.

    Uses the established decoder API (benchlog_analysis.common
    .decode_benchlog_module().decode_blg) and parses the result's own
    csv_header/csv_rows in memory, so this never shells out and never writes
    an ingest directory next to the source log.
    """
    blg_path = Path(blg_path)
    decoder = bl_common.decode_benchlog_module()
    result = decoder.decode_blg(blg_path.read_bytes())
    columns = result.csv_header.split(",")
    rows = result.csv_rows
    n = len(rows)
    data = {c: np.full(n, np.nan, dtype=np.float64) for c in columns}
    for i, line in enumerate(rows):
        cells = line.split(",")
        if len(cells) != len(columns):
            raise ValueError("%s: record %d has %d cells, expected %d"
                             % (blg_path.name, i, len(cells), len(columns)))
        for col, cell in zip(columns, cells):
            if cell != "":
                data[col][i] = float(cell)
    return data, dict(result.header)


def align_replay(hil, blg_len):
    """Index pairs linking HIL rows to source-BLG records.

    Returns (hil_idx, blg_idx) int arrays. A row is aligned when its
    replay_rec is >= 0 (past the synthetic preamble), in range for the
    decoded log, and its `state` cell is present (an observation frame came
    back for that tick -- a row without one carries no firmware response to
    compare).
    """
    rec = hil.get("replay_rec")
    if rec is None:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    state = hil.get("state")
    ok = np.isfinite(rec) & (rec >= 0) & (rec < blg_len)
    if state is not None:
        ok &= np.isfinite(state)
    hil_idx = np.nonzero(ok)[0]
    blg_idx = rec[hil_idx].astype(int)
    return hil_idx, blg_idx


def _stats(x):
    """{mean,std,min,max,n} over the finite entries of x (all NaN if none)."""
    x = np.asarray(x, dtype=np.float64)
    f = x[np.isfinite(x)]
    if f.size == 0:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
    return {"n": int(f.size), "mean": float(f.mean()), "std": float(f.std()),
            "min": float(f.min()), "max": float(f.max())}


def _is_identically_zero(stats):
    """True when a `_stats()` block describes a series that is exactly zero
    everywhere it was measured.  False for an empty/absent block: "no samples"
    is not "all zero", and tagging a row on absent data would be a claim."""
    if not stats or not stats.get("n"):
        return False
    lo, hi = stats.get("min"), stats.get("max")
    return lo == 0.0 and hi == 0.0


def deviation_metrics(hil_vals, blg_vals):
    """RMS, max |delta| and mean delta between two aligned traces."""
    d = np.asarray(hil_vals, dtype=np.float64) - np.asarray(blg_vals,
                                                            dtype=np.float64)
    f = d[np.isfinite(d)]
    if f.size == 0:
        return {"n": 0, "rms": None, "max_abs": None, "mean": None}
    return {"n": int(f.size), "rms": float(np.sqrt(np.mean(f * f))),
            "max_abs": float(np.max(np.abs(f))), "mean": float(f.mean())}


# Signals injected by the simulator from the source log -- these should match
# the source almost exactly; a residual is an injection-path defect.
INJECTED_PAIRS = [("V_fc", "V_fc"), ("V_batt", "V_batt"), ("V_bus", "V_bus"),
                  ("I_fc", "I_fc"), ("I_batt", "I_batt"),
                  ("v_actual", "v_act")]
# Signals the firmware PRODUCES -- these are the comparison of interest, and
# the open-loop caveat applies to every one of them.
RESPONSE_PAIRS = [("current", "I_cmd"), ("gFC", "gFC"), ("gBT", "gBT")]


def compute_replay_metrics(hil, blg, hil_idx, blg_idx, replay_commands=None):
    """Injection-fidelity + response-deviation metrics for one replay run.

    hil must already carry the adapter's derived gFC/gBT columns (see
    attach_derived()). Signals absent from either side are skipped -- a BLG
    v1-v4 decode has no u_unsat, and a simple-electrical HIL CSV has no soc.
    """
    out = {"aligned_ticks": int(hil_idx.size), "injection": {},
           "response": {}, "source_stats": {}, "hil_stats": {}}
    if hil_idx.size == 0:
        return out

    for hil_key, blg_key in INJECTED_PAIRS:
        if hil_key in hil and blg_key in blg:
            out["injection"][blg_key] = deviation_metrics(
                hil[hil_key][hil_idx], blg[blg_key][blg_idx])
    for hil_key, blg_key in RESPONSE_PAIRS:
        if hil_key in hil and blg_key in blg:
            out["response"][blg_key] = deviation_metrics(
                hil[hil_key][hil_idx], blg[blg_key][blg_idx])
    for hil_key, blg_key in INJECTED_PAIRS + RESPONSE_PAIRS:
        if blg_key in blg:
            out["source_stats"][blg_key] = _stats(blg[blg_key][blg_idx])
        if hil_key in hil:
            out["hil_stats"][blg_key] = _stats(hil[hil_key][hil_idx])

    # ── WHICH RESPONSE ROWS ARE NOT A COMPARISON AT ALL (2026-09-02) ────────
    # Campaign 20260902_011926's replay audit found the two cases, both of
    # which read as ordinary deviations and are not:
    #   * NO COMMAND REPLAY (12 of 27 entries).  Without `replay_commands` the
    #     board never leaves Idle and its motor command is identically 0 A, so
    #     the "deviation" IS the source log's own trajectory.  ML0144's 8.635 —
    #     the largest number in the whole ANALYSIS_SUMMARY — is a board that
    #     commanded nothing.
    #   * NO MDAC CHANNEL IN THE SOURCE (10 entries).  A BLG without gFC/gBT
    #     decodes them as identically zero, so the row is the HIL value
    #     verbatim.  ML0151's gFC 0.8599 is not a divergence.
    # THE I_cmd TAG IS DECIDED FROM `replay_commands`, NOT FROM THE SERIES
    # (2026-09-02, review L3).  The flat-zero series cannot tell the two cases
    # apart: a board that was never commanded and a board that was commanded a
    # v_setpoint of identically zero produce the SAME identically-zero motor
    # command, and TP0178/TP0201 are exactly the second case (v_sp == 0
    # profiles).  Tagging those "no command replay" would be false, and it
    # would hide the one reading that IS a comparison there — a commanded board
    # that answered zero.  `replay_commands` comes off the run's own sidecar
    # (config.replay_commands / replay_source.replay_commands), so it is the
    # run's declared intent; the flat-zero series is kept as CORROBORATION and
    # the tag is withheld when the two disagree, because a run that replayed no
    # commands and still moved its motor command is a finding, not a caveat.
    # `replay_commands=None` (an older sidecar, or a caller that does not know)
    # falls back to the series alone, i.e. to the previous behaviour.
    for key, m in out["response"].items():
        flat_hil = _is_identically_zero(out["hil_stats"].get(key))
        flat_src = _is_identically_zero(out["source_stats"].get(key))
        if key == "I_cmd" and flat_hil and replay_commands is not True:
            m["not_exercised"] = (
                "NOT EXERCISED (%s): the HIL board's motor command is "
                "identically 0 A over the aligned window, so this residual is "
                "the SOURCE LOG's own trajectory, not a deviation"
                % ("no command replay" if replay_commands is False else
                   "no command replay recorded in the sidecar"))
        elif key == "I_cmd" and flat_hil:
            # Commanded AND identically zero: a real reading, kept untagged so
            # it is read as the comparison it is (a v_sp == 0 profile answered
            # correctly, or a board that failed to act on a command).
            m["commanded_but_zero"] = (
                "the run REPLAYED COMMANDS and the board's motor command is "
                "still identically 0 A over the aligned window — a real "
                "comparison (a v_setpoint == 0 profile answers this way), not "
                "a not-exercised row")
        elif key in ("gFC", "gBT") and flat_src:
            m["not_exercised"] = (
                "NOT COMPARABLE (source has no MDAC channel): the source "
                "log's %s is identically 0 over the aligned window, so this "
                "residual is the HIL value verbatim" % key)

    if "fault_flags" in hil and "fault_flags" in blg:
        h = hil["fault_flags"][hil_idx]
        b = blg["fault_flags"][blg_idx]
        both = np.isfinite(h) & np.isfinite(b)
        if both.any():
            mismatch = both & (h != b)
            out["fault_mismatch_fraction"] = float(
                mismatch.sum() / float(both.sum()))
            hil_union = int(np.bitwise_or.reduce(
                h[both].astype(np.int64))) if both.any() else 0
            blg_union = int(np.bitwise_or.reduce(b[both].astype(np.int64)))
            out["hil_fault_union"] = hil_union
            out["blg_fault_union"] = blg_union
            out["hil_fault_names"] = decode_fault_bits(hil_union)
            out["blg_fault_names"] = decode_fault_bits(blg_union)
    return out


def attach_derived(hil):
    """Add gFC/gBT fraction columns to an HIL dict, in place. Returns it."""
    if "mdac_fc" in hil and "gFC" not in hil:
        hil["gFC"] = _mdac_column(hil["mdac_fc"])
    if "mdac_bt" in hil and "gBT" not in hil:
        hil["gBT"] = _mdac_column(hil["mdac_bt"])
    return hil


# ==========================================================================
# HIL-specific figure builders
# ==========================================================================

def _hil_suptitle(fig, cfg, what):
    """figures._suptitle, so HIL figures carry the same banner and run name."""
    bl_figures._suptitle(fig, cfg, what)


def _bit_lane(ax, t_s, values, bits, title):
    """Stacked on/off lanes, one per bit, newest bit at the top of the axes."""
    labels = []
    for row, (mask, name) in enumerate(bits):
        v = np.where(np.isfinite(values),
                     (np.nan_to_num(values).astype(np.int64) & mask) > 0,
                     np.nan).astype(np.float64)
        ax.step(t_s, row + 0.78 * v, where="post", linewidth=1.2,
                color=COLORS["I_fc"] if row % 2 == 0 else COLORS["I_batt"])
        ax.axhline(row, color="#dddddd", linewidth=0.6, zorder=0)
        labels.append(name)
    ax.set_yticks(np.arange(len(bits)) + 0.39)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_ylim(-0.3, len(bits))
    bl_figures._style_axes(ax, ylabel=None)
    ax.set_title(title, color=TEXT_COLOR, fontsize=10, loc="left")


def hil_state_and_switches(data, cfg):
    """Firmware state, switch/aux bit lanes, and shaded fault regions.

    `data` here is the RAW HIL CSV dict (not the benchlog-adapted one) -- the
    state/switch/aux bytes have no decode_benchlog equivalent.
    """
    t = data["t_s"]
    fig, axes = plt.subplots(4, 1, figsize=FIGSIZE_STACK4, sharex=True)

    ax = axes[0]
    ax.step(t, data.get("state", np.full(t.shape, np.nan)), where="post",
            color=COLORS["velocity"], linewidth=1.4)
    ax.set_yticks([0, 1, 2, 3, 98, 99])
    ax.set_yticklabels(["0 INIT", "1 IDLE", "2 RUN", "3 FIN", "98 TEST",
                        "99 ERR"], fontsize=8)
    bl_figures._style_axes(ax, ylabel="Firmware state")

    _bit_lane(axes[1], t, data.get("switch", np.full(t.shape, np.nan)),
              switch_bits(), "Power-path switches (observation frame)")
    _bit_lane(axes[2], t, data.get("aux", np.full(t.shape, np.nan)),
              aux_bits(), "Aux control pins")

    ax = axes[3]
    flags = data.get("fault_flags", np.full(t.shape, np.nan))
    ax.step(t, flags, where="post", color=COLORS["V_bus"], linewidth=1.2)
    ax.set_yscale("symlog", linthresh=1.0)
    bl_figures._style_axes(ax, ylabel="fault_flags", xlabel="Time [s]")

    nz = np.isfinite(flags) & (flags != 0)
    if nz.any():
        ax.fill_between(t, 0, 1, where=nz, transform=ax.get_xaxis_transform(),
                        color=COLORS["V_bus"], alpha=0.10, step="post",
                        linewidth=0)
        union = int(np.bitwise_or.reduce(
            np.nan_to_num(flags[nz]).astype(np.int64)))
        names = ", ".join(decode_fault_bits(union)) or "none"
        ax.text(0.01, 0.92, "fault union: " + names, transform=ax.transAxes,
                color=TEXT_COLOR, fontsize=9, va="top")
    else:
        ax.text(0.01, 0.92, "fault union: none", transform=ax.transAxes,
                color=TEXT_COLOR, fontsize=9, va="top")

    _hil_suptitle(fig, cfg, "firmware state, switches and faults")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return fig


def hil_charger_and_soc(data, cfg):
    """Charge current, Ag105 status byte, and (when present) SoC / substep rate.

    Returns None when the CSV carries no charger columns at all.

    From fw v24 the V_chg panel also carries the MPPT THRESHOLD IN FORCE as a
    dashed overlay on the same axis, converted from the `mppt_thresh_cnt`
    column (observation-frame byte 15).  Reading it is the point: the threshold
    must sit BELOW V_chg, and a run where it does not is the fw v23 refusal that
    produced the release/re-assert hunt.  Absent or all-blank columns skip the
    overlay rather than drawing a line at zero.
    """
    t = data["t_s"]
    if "I_charge" not in data and "ag105_status" not in data:
        return None
    has_extra = "soc" in data or "elec_substep_hz" in data
    nrows = 3 if has_extra else 2
    fig, axes = plt.subplots(nrows, 1,
                             figsize=(10, 3.2 * nrows), sharex=True)
    axes = np.atleast_1d(axes)

    ax = axes[0]
    if "I_charge" in data:
        ax.plot(t, data["I_charge"], color=COLORS["I_fc"],
                linewidth=bl_figures.LW_RAW, label="I_charge")
    bl_figures._style_axes(ax, ylabel="Charge current [A]")
    bl_figures._legend(ax, loc="upper left")

    ax = axes[1]
    if "ag105_status" in data:
        ax.step(t, data["ag105_status"], where="post", color=COLORS["V_chg"],
                linewidth=1.2, label="ag105_status (Table 6 raw)")
    if "V_chg" in data:
        ax2 = ax.twinx()
        ax2.plot(t, data["V_chg"], color=COLORS["V_rgn"],
                 linewidth=bl_figures.LW_RAW, alpha=0.7, label="V_chg")
        ax2.set_ylabel("V_chg [V]", color=COLORS["V_rgn"], fontsize=10)
        ax2.tick_params(axis="y", colors=COLORS["V_rgn"], labelsize=9)
        # MPPT THRESHOLD IN FORCE (fw v24).  `mppt_thresh_cnt` is the reg-0x02
        # count the firmware believes it wrote (observation-frame byte 15); in
        # VOLTS it is directly comparable to V_chg, and the whole point of the
        # fw v24 round is that the dashed line must sit BELOW the solid one --
        # a threshold above V_chg is the refusal that produced the fw v23 hunt.
        # Drawn on the V_chg axis for exactly that comparison.
        #
        # ABSENT / ALL-BLANK COLUMNS ARE A CLEAN SKIP, mirroring the adapter's
        # all-NaN cmd_* rule: a pre-fw-v24 CSV has no column at all, and a run
        # against a fw v21-v23 flash has the column but never a value (the
        # 16-byte frame carries no such byte).  Drawing an empty dashed line
        # over either would read as "the threshold was zero".
        thr_cnt = data.get("mppt_thresh_cnt")
        if thr_cnt is not None and np.any(np.isfinite(thr_cnt)):
            # Counts >= 251 are external-resistor mode, which has no volts value
            # of its own (Ag105 Table 7) -- NaN them rather than extrapolating
            # 11 + 0.088*255 = 33.4 V, a threshold the register cannot express.
            _ps = _plant_sim_module()      # constants imported, never copied
            volts = np.full(thr_cnt.shape, np.nan, dtype=np.float64)
            ok = np.isfinite(thr_cnt) & (thr_cnt <= _ps.AG105_MPPT_N_MAX)
            volts[ok] = (_ps.AG105_MPPT_V_BASE
                         + _ps.AG105_MPPT_V_PER_CNT * thr_cnt[ok])
            if np.any(np.isfinite(volts)):
                ax2.plot(t, volts, color=COLORS["V_rgn"], linewidth=1.1,
                         linestyle="--", alpha=0.9,
                         label="MPPT threshold in force (reg 0x02)")
                bl_figures._legend(ax2, loc="upper right")
    bl_figures._style_axes(ax, ylabel="Ag105 status byte")
    bl_figures._legend(ax, loc="upper left")

    if has_extra:
        ax = axes[2]
        if "soc" in data:
            ax.plot(t, data["soc"], color=COLORS["I_batt"],
                    linewidth=bl_figures.LW_FILT, label="SoC")
            bl_figures._style_axes(ax, ylabel="SoC [-]")
        if "elec_substep_hz" in data:
            axr = ax.twinx()
            axr.plot(t, data["elec_substep_hz"], color=COLORS["share"],
                     linewidth=0.9, alpha=0.7)
            axr.set_ylabel("elec substep [Hz]", color=COLORS["share"],
                           fontsize=10)
            axr.tick_params(axis="y", colors=COLORS["share"], labelsize=9)
        bl_figures._legend(ax, loc="upper left")
    axes[-1].set_xlabel("Time [s]", color=TEXT_COLOR, fontsize=10)

    _hil_suptitle(fig, cfg, "charger, SoC and electrical solver")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


# The hardware-envelope clamp SdpStrategy.clamp_share() applies on emission,
# which is also SocBandStrategy's [SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX] and
# the firmware's [DROOP_R_MIN, DROOP_R_MAX] cutoff band (.ino:9231-9257, strict
# `<`/`>`, so the endpoints themselves are IN band).  Duplicated as literals
# rather than imported: this module renders reports offline, from CSVs whose
# producing sim may be any revision, and a band drawn from THIS checkout's
# constants would silently relabel an older trace.
SHARE_CLAMP_LO = 0.15
SHARE_CLAMP_HI = 0.85


def hil_share_raw_vs_emitted(data, cfg):
    """The policy's PRE-clamp request against what it actually commanded.

    Queued from the SDP round and earned by campaign 20260831_222036: under the
    sdp-v2 policy every table value in (0.85, 1.0] emits the SAME clamped
    0.8500, so `cmd_share_sp` alone cannot distinguish one demand map from
    another, or a live demand axis from a saturated one.  `cmd_share_sp_raw`
    is the column that can, and nothing plotted it.

    Returns None (a clean skip) unless the CSV carries `cmd_share_sp_raw` with
    at least one real value — it is written only by strategies that HAVE a
    pre-clamp request, and is blank on every other run.
    """
    raw = data.get("cmd_share_sp_raw")
    if raw is None or not np.any(np.isfinite(raw)):
        return None
    t = data["t_s"]
    fig, ax = plt.subplots(figsize=(10, 4.0))

    # The band is the readable part of the figure: raw INSIDE it means the
    # clamp did nothing, raw OUTSIDE it means the policy asked for a rail that
    # would have cut a source off the bus.
    ax.axhspan(SHARE_CLAMP_LO, SHARE_CLAMP_HI, color=COLORS["share"],
               alpha=0.08, zorder=0)
    for level in (SHARE_CLAMP_LO, SHARE_CLAMP_HI):
        ax.axhline(level, color=COLORS["share"], alpha=0.45, linewidth=0.9,
                   linestyle="--", zorder=1)

    ax.step(t, raw, where="post", color=COLORS["V_bus"],
            linewidth=1.3, label="cmd_share_sp_raw (table request, pre-clamp)")
    if "cmd_share_sp" in data:
        ax.step(t, data["cmd_share_sp"], where="post", color=COLORS["I_fc"],
                linewidth=1.3, label="cmd_share_sp (emitted)")
    if "I_fc" in data and "I_batt" in data:
        ax.plot(t, share_actual(data["I_fc"], data["I_batt"]),
                color=COLORS["velocity"], linewidth=bl_figures.LW_RAW,
                alpha=0.85, label="share_act = I_fc/I_tot (delivered)")

    n_clamped = int(np.count_nonzero(
        np.isfinite(raw) & ((raw < SHARE_CLAMP_LO) | (raw > SHARE_CLAMP_HI))))
    n_real = int(np.count_nonzero(np.isfinite(raw)))
    # Headroom above 1.0 so a legend in the upper-left cannot sit on the rail
    # the raw request spends most of its time at.
    ax.set_ylim(-0.08, 1.28)
    bl_figures._style_axes(ax, ylabel="Power share [-]")
    ax.set_xlabel("Time [s]", color=TEXT_COLOR, fontsize=10)
    bl_figures._legend(ax, loc="upper left")
    _hil_suptitle(
        fig, cfg,
        "share: table request vs emitted (clamp [%.2f, %.2f]; %d/%d samples "
        "clamped)" % (SHARE_CLAMP_LO, SHARE_CLAMP_HI, n_clamped, n_real))
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def hil_h2_and_soc(data, cfg):
    """Estimated hydrogen consumption (Gfc) and battery SoC, stacked on t.

    Returns None (a clean skip) unless `soc` is present with at least one
    real value -- SoC is the anchor signal: a replay CSV has neither soc nor
    any h2 column, and a plain (non-EMS) simulated run has soc but no h2
    columns at all (the Gfc integrator is EMS-strategy tooling, landed
    2026-08-31, Round B).

    When `soc` is present but every h2 column is absent/all-NaN (a
    pre-2026-08-31 campaign), the top panel is NOT left empty -- an explicit
    annotation says so, per the project's "no silent empty axis" honesty
    rule (mirrors the charger figure's MPPT-overlay skip comment above).
    """
    t = data["t_s"]
    if "soc" not in data or not np.any(np.isfinite(data["soc"])):
        return None

    h2_cum = data.get("h2_cum_g")
    have_h2 = h2_cum is not None and np.any(np.isfinite(h2_cum))
    h2_sdp = data.get("h2_sdp_cum_g")
    have_h2_sdp = h2_sdp is not None and np.any(np.isfinite(h2_sdp))
    h2_rate = data.get("h2_rate_gps")
    have_h2_rate = h2_rate is not None and np.any(np.isfinite(h2_rate))

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=bl_figures.FIGSIZE_STACK2,
                                   sharex=True)

    if have_h2:
        ax0.plot(t, h2_cum, color=COLORS["V_bus"], linewidth=bl_figures.LW_FILT,
                 label="h2_cum_g (Gfc integral)")
        final_h2 = float(h2_cum[np.isfinite(h2_cum)][-1])
        ax0.text(0.01, 0.92, "final h2_cum_g = %.6f g" % final_h2,
                 transform=ax0.transAxes, color=TEXT_COLOR, fontsize=9,
                 va="top")
        if have_h2_sdp:
            ax0.plot(t, h2_sdp, color=COLORS["u_unsat"],
                     linewidth=bl_figures.LW_RAW, linestyle="--",
                     label="h2_sdp_cum_g (static proxy: "
                           "P_fc_stack / (0.5*120 kW))")
            final_sdp = float(h2_sdp[np.isfinite(h2_sdp)][-1])
            ax0.text(0.01, 0.83, "final h2_sdp_cum_g = %.6f g" % final_sdp,
                     transform=ax0.transAxes, color=TEXT_COLOR, fontsize=9,
                     va="top")
        if have_h2_rate:
            axr = ax0.twinx()
            axr.plot(t, h2_rate, color=COLORS["edge_expected"], linewidth=0.8,
                     alpha=0.6, label="h2_rate_gps")
            axr.set_ylabel("h2_rate_gps", color=COLORS["edge_expected"],
                           fontsize=10)
            axr.tick_params(axis="y", colors=COLORS["edge_expected"],
                            labelsize=9)
        bl_figures._style_axes(ax0, ylabel="H2 consumed, cumulative [g]")
        bl_figures._legend(ax0, loc="upper left")
    else:
        bl_figures._style_axes(ax0, ylabel="H2 consumed, cumulative [g]")
        ax0.text(0.5, 0.5,
                 "H2 columns not present in this log "
                 "(pre-2026-08-31 tooling)",
                 transform=ax0.transAxes, color=TEXT_COLOR, fontsize=10,
                 ha="center", va="center")
        ax0.set_xticks([])
        ax0.set_yticks([])

    soc = data["soc"]
    ax1.plot(t, soc, color=COLORS["I_batt"], linewidth=bl_figures.LW_FILT,
             label="soc")
    finite = np.isfinite(soc)
    soc0 = float(soc[finite][0])
    soc_end = float(soc[finite][-1])
    ax1.axhline(soc0, color=COLORS["I_batt"], alpha=0.35, linewidth=0.9,
               linestyle="--")
    ax1.text(0.01, 0.92,
             "soc0 = %.6f, final = %.6f (delta_soc = %.6f)"
             % (soc0, soc_end, soc_end - soc0),
             transform=ax1.transAxes, color=TEXT_COLOR, fontsize=9, va="top")
    bl_figures._style_axes(ax1, ylabel="SoC [-]")
    ax1.set_xlabel("Time [s]", color=TEXT_COLOR, fontsize=10)

    _hil_suptitle(fig, cfg, "hydrogen consumption and battery SoC")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


def hil_power_balance(data, cfg):
    """Per-tick power balance: motor, sources, chopper, and the residual.

    Two panels on a shared time axis.  The top panel carries the power terms
    and, dashed, their sum `p_fc + p_batt + p_chop`; the bottom panel carries
    the residual `p_bal = p_mot + p_chg_loss - (p_fc + p_batt + p_chop)` with
    the auxiliary load overlaid and `p_bal + p_aux` beside it.

    THE CHARGER LOSS IS A NAMED COMPONENT (2026-09-01).  Before that date the
    plant's Ag105 was a 1:1 current transfer element, so the whole
    `i_charge * (V_chg - V_batt)` -- about 11 W on a 1.4 A charge window --
    fell into the residual unnamed.  The plant now bills the charger through
    a static efficiency and writes its dissipation out as a seventh column,
    `p_chg_loss_w`.  This figure plots that column on the top panel and names
    it in the residual panel's caption, so a charge window no longer reads as
    an unexplained imbalance.

    THE IDENTITY IS STILL NOT EXACT, AND THE FIGURE SAYS SO.  The residual's
    remaining named components, in descending magnitude, are the auxiliary
    housekeeping load (`I_AUX_A` plus any scenario preload or drain, on VBUS
    -- plotted, so it can be subtracted by eye), bulk-capacitor storage, the
    hi-fi motor stamp's transient term, and the RT1987 ideal-diode drops
    between VBUS and the V-MOT node.

    THREE DATA PATHS, and the annotation states which one rendered:

    1. NEW SCHEMA (a simulator CSV written AFTER the charger-efficiency round
       of 2026-09-01) carries all seven `p_*_w` columns and every term above is
       the plant's own arithmetic.
    1b. PRE-ETA NEW SCHEMA (2026-09-01f up to and including campaign
       `20260901_151156`) carries the first six but NOT `p_chg_loss_w`, because
       the charger had no efficiency then.  The charger trace is omitted and
       the residual panel says so: on those runs the charge term is inside
       `p_bal_w`, which is what makes their charge windows read as ~11 W of
       imbalance.
    2. BACKFILL, for every campaign up to and including `20260901_151156` and
       for every replay CSV.  ONLY the two source powers are derivable:
           p_fc  = V_bus * I_fc          (exact, same definition)
           p_batt= V_bus * I_batt        (GROSS: no charge term is available,
                                          so a charge window reads as pure draw)
       The motor, regen, charging and chopper terms are NOT derivable, so this
       path draws no motor trace and NO RESIDUAL PANEL at all; the lower axes
       carries the explanatory annotation instead.  ⚠️ A `V_rgn * current`
       motor proxy was tried and removed: `current` is the VESC PHASE-current
       command (up to 12 A), not a bus-side current, and it over-read by 4-6x,
       producing a residual that read as a real imbalance.  On a REPLAY CSV
       `current` is the bench log's recorded command, the same class of
       quantity and equally unusable as a power.

    Returns None (a clean skip) only when neither path is available, i.e. when
    `V_bus`, `I_fc` and `I_batt` are all absent or all-NaN.  A present-but-empty
    axis is never drawn (project honesty rule).
    """
    t = data["t_s"]

    def _col(name):
        arr = data.get(name)
        if arr is not None and np.any(np.isfinite(arr)):
            return arr
        return None

    p_mot = _col("p_mot_w")
    p_fc = _col("p_fc_w")
    p_batt = _col("p_batt_w")
    p_chop = _col("p_chop_w")
    p_aux = _col("p_aux_w")
    p_bal = _col("p_bal_w")
    # APPENDED 2026-09-01, so it is absent from every CSV written before the
    # charger-efficiency round.  `None` here means "pre-eta era", NOT "zero
    # loss": those runs put the charger term inside `p_bal_w` instead.
    p_chg_loss = _col("p_chg_loss_w")
    native = p_mot is not None and p_fc is not None and p_batt is not None

    if not native:
        # ── LEGACY BACKFILL: the two SOURCE powers, and nothing else ────────
        # A motor proxy `V_rgn * current` was tried here and REMOVED (fix
        # round, 2026-09-01f).  `current` is the VESC PHASE-current command,
        # up to 12 A, NOT a bus-side current, so the proxy over-read by 4-6x:
        # 70-100 W against 5-25 W of real source power on campaign
        # `hil_report_20260831_000518`, i.e. a mean residual of +44 W (188 % of
        # the proxy's own mean) that READ AS A GENUINE IMBALANCE.  An
        # annotation does not rescue a trace that wrong, so the honest
        # rendering omits it, and the residual panel goes with it — a residual
        # against an absent motor term is not defined.
        v_bus, i_fc, i_batt = _col("V_bus"), _col("I_fc"), _col("I_batt")
        if v_bus is None or i_fc is None or i_batt is None:
            return None
        p_fc = v_bus * i_fc
        p_batt = v_bus * i_batt
        p_sum = p_fc + p_batt

        fig, (ax0, ax1) = plt.subplots(2, 1, figsize=bl_figures.FIGSIZE_STACK2,
                                       sharex=True)
        ax0.axhline(0.0, color=TEXT_COLOR, alpha=0.35, linewidth=0.8)
        ax0.plot(t, p_fc, color=COLORS["I_fc"], linewidth=bl_figures.LW_RAW,
                 label="p_fc (V_bus * I_fc)")
        ax0.plot(t, p_batt, color=COLORS["I_batt"],
                 linewidth=bl_figures.LW_RAW,
                 label="p_batt (V_bus * I_batt, GROSS: no charge term)")
        ax0.plot(t, p_sum, color=COLORS["u_unsat"],
                 linewidth=bl_figures.LW_RAW, linestyle="--",
                 label="p_fc + p_batt")
        bl_figures._style_axes(ax0, ylabel="Power [W]")
        bl_figures._legend(ax0, loc="upper left")

        # The lower axes carries the annotation INSTEAD of a residual trace:
        # never a silent empty axis (project honesty rule), and clear of the
        # upper panel's legend.
        bl_figures._style_axes(ax1, ylabel="Residual power [W]")
        ax1.text(0.5, 0.5,
                 "motor, regen, charging and chopper terms not derivable from "
                 "legacy columns\n(pre-2026-09-01f CSV; `current` is the VESC "
                 "phase-current command, not bus current)",
                 transform=ax1.transAxes, color=TEXT_COLOR, fontsize=10,
                 ha="center", va="center")
        # Y ticks only: the axes SHARE x, so clearing the x ticks here would
        # strip the time axis off the upper panel as well and leave the figure
        # with no time reference at all.
        ax1.set_yticks([])
        ax1.set_xlabel("Time [s]", color=TEXT_COLOR, fontsize=10)

        _hil_suptitle(fig, cfg,
                      "power balance: source powers only (legacy CSV)")
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        return fig

    # ── NEW SCHEMA ──────────────────────────────────────────────────────────
    # The seven columns are written as one block (six of them before the
    # charger-efficiency round), so `native` above establishes the whole set of
    # whichever era the CSV came from.  The defensive fallbacks below cost
    # nothing and close a
    # real inconsistency: if a hand-edited or truncated CSV lost `p_chop_w` or
    # `p_bal_w` alone, the logged residual would no longer be the residual of
    # the plotted sum.  Recompute it whenever any term is missing.
    zeros = np.zeros(t.shape, dtype=np.float64)
    p_chop_arr = p_chop if p_chop is not None else zeros
    # A pre-eta CSV has no charger-loss column; on those runs the term is
    # inside `p_bal_w`, so the recomputation fallback must add nothing.
    p_chg_arr = p_chg_loss if p_chg_loss is not None else zeros
    p_sum = p_fc + p_batt + p_chop_arr
    if p_bal is None or p_chop is None:
        p_bal = p_mot + p_chg_arr - p_sum

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=bl_figures.FIGSIZE_STACK2,
                                   sharex=True)

    ax0.axhline(0.0, color=TEXT_COLOR, alpha=0.35, linewidth=0.8)
    ax0.plot(t, p_mot, color=COLORS["I_cmd"], linewidth=bl_figures.LW_FILT,
             label="p_mot_w (motor node; + draw, - regen)")
    ax0.plot(t, p_fc, color=COLORS["I_fc"], linewidth=bl_figures.LW_RAW,
             label="p_fc_w (V_bus * I_fc)")
    ax0.plot(t, p_batt, color=COLORS["I_batt"], linewidth=bl_figures.LW_RAW,
             label="p_batt_w (+ sourcing, - charging)")
    if p_chop is not None:
        ax0.plot(t, p_chop, color=COLORS["V_rgn"], linewidth=bl_figures.LW_RAW,
                 label="p_chop_w (braking shunt)")
    if p_chg_loss is not None:
        # COLORS has no charger-loss role; "I_total" is the one entry unused
        # by either panel of this figure, so it cannot collide with a trace a
        # reader is comparing against.
        ax0.plot(t, p_chg_loss, color=COLORS["I_total"],
                 linewidth=bl_figures.LW_RAW,
                 label="p_chg_loss_w (Ag105 dissipation)")
    ax0.plot(t, p_sum, color=COLORS["u_unsat"], linewidth=bl_figures.LW_RAW,
             linestyle="--", label="p_fc + p_batt + p_chop")
    bl_figures._style_axes(ax0, ylabel="Power [W]")
    bl_figures._legend(ax0, loc="upper left")

    ax1.axhline(0.0, color=TEXT_COLOR, alpha=0.35, linewidth=0.8)
    ax1.plot(t, p_bal, color=COLORS["V_bus"], linewidth=bl_figures.LW_FILT,
             label=("p_bal_w = p_mot + p_chg_loss - (p_fc + p_batt + p_chop)"
                    if p_chg_loss is not None else
                    "p_bal_w = p_mot - (p_fc + p_batt + p_chop)"))
    if p_aux is not None:
        ax1.plot(t, -p_aux, color=COLORS["edge_expected"],
                 linewidth=bl_figures.LW_RAW, label="-p_aux_w (V_bus * i_aux)")
        # The named-component list on this label is the honest one for the
        # era the CSV came from: the charger loss is a plotted term on a
        # post-eta run and an unnamed resident of the residual before that.
        # THE BRAKING TERM IS NAMED (2026-09-02, review PLANT-R1-F3).  The
        # residual puts `p_chop` on the SOURCE side, and in braking `p_mot` is
        # NEGATIVE while the chopper is dissipating — so the residual carries
        # roughly -2*p_chop there and is a diagnostic, not an imbalance.  It was
        # already an observer column; what was missing was the label saying so
        # where the reader meets the trace.
        ax1.plot(t, p_bal + p_aux, color=COLORS["V_chg"],
                 linewidth=bl_figures.LW_RAW, linestyle="--",
                 label=("p_bal_w + p_aux_w (storage, motor stamp, RT1987 "
                        "drops; in BRAKING also ~-2*p_chop_w)"
                        if p_chg_loss is not None else
                        "p_bal_w + p_aux_w (CHARGER, storage, RT1987 drops; "
                        "in BRAKING also ~-2*p_chop_w)"))
    finite = np.isfinite(p_bal)
    if np.any(finite):
        mean_bal = float(np.mean(p_bal[finite]))
        max_bal = float(np.max(np.abs(p_bal[finite])))
        mot_finite = np.isfinite(p_mot)
        mean_mot = (float(np.mean(np.abs(p_mot[mot_finite])))
                    if np.any(mot_finite) else 0.0)
        pct = ("%.1f %% of mean |p_mot|" % (100.0 * max_bal / mean_mot)
               if mean_mot > 1e-9 else "mean |p_mot| is zero")
        # Same statement in the numeric annotation, because a reader who
        # quotes the residual figure is usually quoting this line.
        brake = ("" if not np.any(np.isfinite(p_chop_arr)
                                  & (p_chop_arr > 1e-9)) else
                 "  [BRAKING TICKS: p_chop sits on the SOURCE side while p_mot "
                 "is negative, so the residual carries ~-2*p_chop there — a "
                 "diagnostic, not an imbalance]")
        era = ("" if p_chg_loss is not None else
               "  [PRE-ETA CSV: the Ag105 was a 1:1 current transfer element, "
               "so its ~i_charge*(V_chg - V_batt) dissipation is INSIDE this "
               "residual]")
        ax1.text(0.01, 0.06,
                 "residual: mean %+.4f W, max |.| %.4f W (%s)%s%s"
                 % (mean_bal, max_bal, pct, era, brake),
                 transform=ax1.transAxes, color=TEXT_COLOR, fontsize=9,
                 va="bottom")
    bl_figures._style_axes(ax1, ylabel="Residual power [W]")
    ax1.set_xlabel("Time [s]", color=TEXT_COLOR, fontsize=10)
    bl_figures._legend(ax1, loc="upper left")

    _hil_suptitle(fig, cfg, "power balance: motor vs sources, chopper, residual")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


HIL_FIGURES = [
    ("hil_state_and_switches", hil_state_and_switches),
    ("hil_charger_and_soc", hil_charger_and_soc),
    ("hil_share_raw_vs_emitted", hil_share_raw_vs_emitted),
    ("hil_h2_and_soc", hil_h2_and_soc),
    ("hil_power_balance", hil_power_balance),
]


# ==========================================================================
# Replay comparison figures
# ==========================================================================

def _law_caveat(blg_fw):
    """Caveat line for a replay comparison, given the source log's fw.

    Three cases, and the third is NOT the same as the first: an unknown source
    firmware cannot be assumed comparable, because a log old enough to carry
    no fw field (BLG format v1) predates the current control law by
    definition. It gets its own explicit hedge.
    """
    base = ("Replay is OPEN LOOP: firmware commands do not influence the "
            "injected trajectory.")
    if blg_fw is None:
        return (base + "\nControl-law comparability UNVERIFIED (source fw "
                "version unknown — no decoded header and no sidecar value); "
                "treat the response comparison as unqualified.")
    if blg_fw < DIFFERENT_LAW_FW:
        return (base + "\nSource fw %d < %d — different wheel and control "
                "law; stability/character comparison only, NOT a trace match."
                % (blg_fw, DIFFERENT_LAW_FW))
    return base


# HIL column -> (BLG column, axis label). One dedicated overlay figure carries
# every shared family; hooking the overlay into the existing builders would
# mean editing figures.py, which this tool deliberately does not do.
OVERLAY_PANELS = [
    (["v_actual"], ["v_act"], "Velocity [m/s]"),
    (["I_fc", "I_batt"], ["I_fc", "I_batt"], "Channel current [A]"),
    (["V_bus"], ["V_bus"], "Bus voltage [V]"),
    (["gFC", "gBT"], ["gFC", "gBT"], "Droop gain [-]"),
    (["current"], ["I_cmd"], "Motor current cmd [A]"),
]


def hil_replay_overlay(hil, blg, hil_idx, blg_idx, cfg, blg_fw=None):
    """HIL traces with the source SD-log traces overlaid, one panel per family."""
    t = hil["t_s"][hil_idx]
    fig, axes = plt.subplots(len(OVERLAY_PANELS), 1, figsize=(10, 13),
                             sharex=True)
    for ax, (hil_keys, blg_keys, ylabel) in zip(axes, OVERLAY_PANELS):
        for hk, bk in zip(hil_keys, blg_keys):
            color = COLORS.get(bk, COLORS["velocity"])
            if hk in hil:
                ax.plot(t, hil[hk][hil_idx], color=color,
                        linewidth=bl_figures.LW_RAW, label="%s (HIL)" % bk)
            if bk in blg:
                ax.plot(t, blg[bk][blg_idx], color=OVERLAY_COLOR,
                        linewidth=OVERLAY_LW, linestyle="--",
                        label="%s (SD log)" % bk)
        bl_figures._style_axes(ax, ylabel=ylabel)
        bl_figures._legend(ax, loc="upper right", ncol=2)
    axes[-1].set_xlabel("Time [s]  (HIL run clock)", color=TEXT_COLOR,
                        fontsize=10)
    axes[0].text(0.01, 1.02, _law_caveat(blg_fw), transform=axes[0].transAxes,
                 color=TEXT_COLOR, fontsize=8, va="bottom")
    _hil_suptitle(fig, cfg, "replay overlay vs source SD log")
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


def hil_replay_injection_fidelity(hil, blg, hil_idx, blg_idx, cfg,
                                  blg_fw=None):
    """Injected rail minus source-log value at every aligned record.

    These residuals should be ~0: the simulator's only job in replay mode is
    to hand the recorded samples back to the firmware unchanged.
    """
    t = hil["t_s"][hil_idx]
    fig, axes = plt.subplots(2, 1, figsize=FIGSIZE_STACK3[0:1] + (8.0,),
                             sharex=True)
    volt = [(h, b) for h, b in INJECTED_PAIRS if b.startswith("V_")]
    rest = [(h, b) for h, b in INJECTED_PAIRS if not b.startswith("V_")]
    for ax, group, ylabel in ((axes[0], volt, "Voltage residual [V]"),
                              (axes[1], rest, "Current / velocity residual")):
        for hk, bk in group:
            if hk in hil and bk in blg:
                ax.plot(t, hil[hk][hil_idx] - blg[bk][blg_idx],
                        color=COLORS.get(bk, COLORS["velocity"]),
                        linewidth=0.9, label=bk)
        ax.axhline(0.0, color=bl_figures.ZERO_LINE_COLOR, linewidth=0.8)
        bl_figures._style_axes(ax, ylabel=ylabel)
        bl_figures._legend(ax, loc="upper right", ncol=3)
    axes[-1].set_xlabel("Time [s]  (HIL run clock)", color=TEXT_COLOR,
                        fontsize=10)
    _hil_suptitle(fig, cfg, "replay injection fidelity (HIL − SD log)")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


def hil_replay_response_deviation(hil, blg, hil_idx, blg_idx, cfg,
                                  blg_fw=None, metrics=None):
    """Firmware response under HIL vs what the bench run recorded."""
    t = hil["t_s"][hil_idx]
    fig, axes = plt.subplots(4, 1, figsize=FIGSIZE_STACK4, sharex=True)

    ax = axes[0]
    if "current" in hil:
        ax.plot(t, hil["current"][hil_idx], color=COLORS["I_cmd"],
                linewidth=bl_figures.LW_RAW, label="I_cmd (HIL)")
    if "I_cmd" in blg:
        ax.plot(t, blg["I_cmd"][blg_idx], color=OVERLAY_COLOR,
                linewidth=OVERLAY_LW, linestyle="--", label="I_cmd (SD log)")
    bl_figures._style_axes(ax, ylabel="Motor current cmd [A]")
    bl_figures._legend(ax)

    ax = axes[1]
    if "current" in hil and "I_cmd" in blg:
        ax.plot(t, hil["current"][hil_idx] - blg["I_cmd"][blg_idx],
                color=COLORS["I_cmd"], linewidth=0.9)
    ax.axhline(0.0, color=bl_figures.ZERO_LINE_COLOR, linewidth=0.8)
    bl_figures._style_axes(ax, ylabel="I_cmd residual [A]")

    ax = axes[2]
    for key in ("gFC", "gBT"):
        if key in hil:
            ax.plot(t, hil[key][hil_idx], color=COLORS[key],
                    linewidth=bl_figures.LW_RAW, label="%s (HIL)" % key)
        if key in blg:
            ax.plot(t, blg[key][blg_idx], color=OVERLAY_COLOR,
                    linewidth=OVERLAY_LW, linestyle="--",
                    label="%s (SD log)" % key)
    bl_figures._style_axes(ax, ylabel="Droop gain [-]")
    bl_figures._legend(ax, ncol=2)

    ax = axes[3]
    if "fault_flags" in hil and "fault_flags" in blg:
        h = hil["fault_flags"][hil_idx]
        b = blg["fault_flags"][blg_idx]
        mism = np.isfinite(h) & np.isfinite(b) & (h != b)
        ax.fill_between(t, 0, 1, where=mism,
                        transform=ax.get_xaxis_transform(),
                        color=COLORS["V_bus"], alpha=0.25, step="post",
                        linewidth=0)
        ax.step(t, h, where="post", color=COLORS["V_bus"], linewidth=1.1,
                label="fault_flags (HIL)")
        ax.step(t, b, where="post", color=OVERLAY_COLOR, linewidth=0.9,
                linestyle="--", label="fault_flags (SD log)")
        ax.set_yscale("symlog", linthresh=1.0)
    if "state" in hil:
        axr = ax.twinx()
        axr.step(t, hil["state"][hil_idx], where="post",
                 color=COLORS["velocity"], linewidth=0.9, alpha=0.6)
        axr.set_ylabel("HIL state", color=COLORS["velocity"], fontsize=10)
        axr.tick_params(axis="y", colors=COLORS["velocity"], labelsize=9)
    bl_figures._style_axes(ax, ylabel="fault_flags", xlabel="Time [s]")
    bl_figures._legend(ax, loc="upper left")

    lines = [_law_caveat(blg_fw)]
    if metrics:
        for key, m in sorted((metrics.get("response") or {}).items()):
            if m.get("rms") is not None:
                lines.append("%s: RMS %.4g, max|Δ| %.4g"
                             % (key, m["rms"], m["max_abs"]))
        if metrics.get("fault_mismatch_fraction") is not None:
            lines.append("fault-flag mismatch: %.2f%% of aligned ticks"
                         % (100.0 * metrics["fault_mismatch_fraction"]))
    axes[0].text(0.01, 1.02, "\n".join(lines), transform=axes[0].transAxes,
                 color=TEXT_COLOR, fontsize=8, va="bottom")
    _hil_suptitle(fig, cfg, "replay response deviation")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


# ==========================================================================
# Per-run analysis
# ==========================================================================

def _save(fig, path):
    """Render a figure to path atomically (temp file + os.replace).

    A savefig interrupted partway (Ctrl-C, full disk) would otherwise leave a
    truncated PNG at the final name, which the exists() short-circuit then
    treats as a finished figure forever. Writing to <name>.png.tmp first means
    the final name only ever appears complete.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    # format= is REQUIRED: matplotlib infers the format from the extension,
    # and the temp name ends in ".tmp", which it rejects outright.
    fmt = path.suffix.lstrip(".").lower() or "png"
    try:
        fig.savefig(tmp, dpi=DPI_DEFAULT, bbox_inches="tight", format=fmt)
    finally:
        plt.close(fig)
    os.replace(tmp, path)
    return path


def _needs_render(out_path, csv_path, force=False):
    """True when out_path must be (re)rendered.

    Renders when the PNG is missing, when --force was passed, or when the PNG
    is OLDER than the run's CSV -- a re-run of the suite over the same folder
    replaces the CSV, and a figure predating it describes data that is gone.
    An unreadable mtime on either side is treated as "render", the safe
    direction.
    """
    out_path = Path(out_path)
    if force or not out_path.exists():
        return True
    try:
        return out_path.stat().st_mtime < Path(csv_path).stat().st_mtime
    except OSError:
        return True


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_json_atomic(path, obj):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
        f.write("\n")
    os.replace(tmp, path)
    return path


def write_text_atomic(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def suite_result_for(results_json, run):
    """The results.json entry for a run, or None.

    For a SCENARIO the entry's `mode` is the electrical mode, so it
    disambiguates two modes of one scenario; an entry matching name and mode
    is preferred and a name-only match is the fallback (a report predating
    mode-aware identity, or a mode the sidecar did not record). For a REPLAY
    `mode` is the suite's conformance/deviation class, not an electrical
    mode, so it is never matched on.
    """
    fallback = None
    for r in (results_json or {}).get("results", []):
        if r.get("kind") != run.kind or r.get("name") != run.name:
            continue
        if run.kind != "scenario" or run.elec_mode is None:
            return r
        if r.get("mode") == run.elec_mode:
            return r
        if fallback is None:
            fallback = r
    return fallback


def _build_one(builder, data, cfg):
    """Call a builder, closing any figure it left open when it raises.

    A builder that fails partway (typically a KeyError after plt.subplots)
    leaks its figure into pyplot's registry; over a 37-run report that is
    hundreds of retained figures and matplotlib's max_open_warning. Close
    every figure the builder opened before re-raising.
    """
    before = set(plt.get_fignums())
    try:
        return builder(data, cfg)
    except Exception:
        for num in set(plt.get_fignums()) - before:
            plt.close(num)
        raise


def run_standard_figures(data, hil, cfg, dest, csv_path, force=False):
    """Render figures.FIGURES (adapted data) + HIL_FIGURES (raw HIL data).

    The two registries take DIFFERENT dicts. The benchlog builders read the
    decode_benchlog column names, so they get the adapter's output; the HIL
    builders read state/switch/aux/ag105_status/soc, which exist only in the
    raw HIL CSV dict and have no decode_benchlog equivalent.

    Returns (saved_names, skipped) where skipped is [(name, reason)].

    ONLY a KeyError counts as a skip: that is the shape of "this builder wants
    a signal the HIL frame does not carry", alongside a builder returning None
    (the same contract make_figures.make_all honours). Any OTHER exception is
    a real defect in the builder or in the adapter's output and PROPAGATES to
    the per-run error handler, rather than being filed as a routine decline
    where nobody would look at it again.
    """
    saved, skipped = [], []
    registries = ([(n, b, data) for n, b in bl_figures.FIGURES]
                  + [(n, b, hil) for n, b in HIL_FIGURES])
    for name, builder, src in registries:
        out_path = dest / ("%s.png" % name)
        if not _needs_render(out_path, csv_path, force):
            saved.append(name)
            continue
        try:
            fig = _build_one(builder, src, cfg)
        except KeyError as exc:  # builder needs a signal this run lacks
            skipped.append((name, "KeyError: %s" % exc))
            continue
        if fig is None:
            skipped.append((name, "builder declined (signals not applicable)"))
            continue
        _save(fig, out_path)
        saved.append(name)
    return saved, skipped


def load_run_config(dest, report_dir):
    """Figure config for a run, WITHOUT creating a file outside a run folder.

    benchlog_analysis.common.load_or_create_config() writes
    analysis_config.json when absent, which is correct inside a run subfolder
    (the user hand-edits its taus and re-runs) but wrong in the report parent:
    under --no-move `dest` IS the parent, and a suite report folder must not
    collect a stray config that belongs to no run. In that case the defaults
    are returned in memory only.
    """
    dest, report_dir = Path(dest), Path(report_dir)
    if dest.resolve() == report_dir.resolve():
        return json.loads(json.dumps(bl_common.DEFAULT_CONFIG))
    return bl_common.load_or_create_config(dest)


# ==========================================================================
# Delta-SoC-matched DP baseline (WORK_QUEUE section 1, 2026-09-01)
# ==========================================================================

# The module-level preload constant each EMS scenario's stimulus is built on.
# A run's meta sidecar records the whole constant set it executed under, so a
# run from an earlier era can be given the load the board ACTUALLY saw rather
# than the load this checkout declares. A scenario absent from this map either
# has no preload or carries it inside its own bespoke branch, and is solved on
# the current metadata.
SCENARIO_PRELOAD_CONSTANT = {
    "ems-ftp75-5050": "FTP75_PRELOAD_A",
    "ems-ftp75-socband": "FTP75_PRELOAD_A",
    "ems-ftp75-dp": "FTP75_PRELOAD_A",
    "ems-ftp75-sdp": "FTP75_SDP_PRELOAD_A",
    "ems-y-b30-v1": "Y_AUX_LOAD_A",
    "ems-y-b30-v3": "Y_AUX_LOAD_A",
}

# Standing boundaries on every matched-DP comparison this tool renders. Both
# are properties of the DP's demand model, not of a particular run.
MATCHED_DP_REGEN_NOTE = (
    "DP demand model carries a regen term ONLY in the regen era "
    "(gen_dp_ems_table.build_demand's `eta_regen`, 2026-09-02). Outside "
    "it a regen-bearing scenario compares against a regen-free bound, "
    "which at a matched terminal SoC is INFLATED by the energy the run "
    "got back from braking; `regen_bound` below prices that per run. In "
    "the regen era the bound earns the same credit and `regen_bound` "
    "goes to zero. Read `stimulus_era.plant_era.eta_regen` to tell which")

# The two hydrogen totals in the comparison are computed by DIFFERENT halves
# of one model, and the difference is systematic rather than random: the run's
# `h2_cum_g` is the DYNAMIC Gfc integrator (hil_plant_sim.H2Consumption, a ZOH
# discretization of the transfer function), while the DP's stage cost is the
# Gfc DC GAIN times stage energy. The two agree at steady state and differ
# through every transient, always in one direction for a given transient
# shape, so a deviation of a few tenths of a percent is inside this bias and
# is not a policy result.
MATCHED_DP_GFC_NOTE = (
    "run hydrogen is the DYNAMIC Gfc integrator (H2Consumption, ZOH) while "
    "the DP stage cost is the Gfc DC gain: a small, systematic, "
    "one-directional bias between the two totals")

def matched_dp_cost_estimate_s(duration_s):
    """Rough wall time [s] of one matched DP baseline for a cycle of this
    length.

    The cost is SUPERLINEAR in duration: a matched baseline is 15 to 25 DP
    solves, each of which sweeps the stage count AND an SoC grid whose span is
    the cycle's own reachable window, so both dimensions grow together. The
    estimate is a power law anchored on the only two figures on record — 13 s
    measured for the 61 s EMS cycles, and the 20 to 30 min recorded for the
    340 s FTP-75 cycle — which places the exponent near 2.7.

    It is an ORDER-OF-MAGNITUDE figure for deciding whether to start a solve,
    not a prediction. Two anchor points cannot separate the exponent from the
    constant, and neither anchor was measured across a range of durations.
    """
    if not duration_s or duration_s <= 0.0:
        return 13.0
    return 13.0 * (duration_s / 61.0) ** 2.7


# Scenario duration above which a --matched-dp solve is refused without
# --matched-dp-allow-long. A matched baseline is a bisection over 15 to 25 DP
# solves whose cost scales with the stage count, so the 61 s cycles cost
# seconds and the 340 s FTP-75 cycle costs tens of minutes. An analysis pass
# must not silently become a half-hour job.
MATCHED_DP_LONG_DURATION_S = 100.0


def _last_finite(arr):
    """The last finite value of a float array, or None."""
    finite = np.isfinite(arr)
    if not finite.any():
        return None
    return float(arr[np.nonzero(finite)[0][-1]])


def _first_finite(arr):
    finite = np.isfinite(arr)
    if not finite.any():
        return None
    return float(arr[np.nonzero(finite)[0][0]])


def _run_era_preload(scenario, meta):
    """(run_era_value, current_value, status) for a scenario's aux preload.

    `status` is "known", "unknown" (the sidecar carries no constants block) or
    "not_applicable" (the scenario has no mapped preload constant)."""
    sim = _plant_sim_module()
    name = SCENARIO_PRELOAD_CONSTANT.get(scenario)
    if name is None:
        return None, None, "not_applicable"
    current = getattr(sim, name, None)
    current = None if current is None else float(current)
    consts = meta.get("constants")
    if not consts:
        return None, current, "unknown"
    raw = consts.get("hil_plant_sim.%s" % name, consts.get(name))
    if raw is None:
        return None, current, "unknown"
    try:
        return float(raw), current, "known"
    except (TypeError, ValueError):
        return None, current, "unknown"


def _era_overrides(scenario, meta, scen_meta, era_preload, era_status):
    """Run-era values for every DP fingerprint key the sidecar can supply.

    The profile fingerprint covers hil_plant_sim.DP_FINGERPRINT_META_KEYS, of
    which the auxiliary preload is only one. Reconstructing the preload alone
    left every other key at this checkout's value, so a scenario-metadata
    change elsewhere in the set refused an archived run outright (MED,
    2026-09-01: the FTP-75 preload moved and `ems-ftp75-socband` gained a
    charge ceiling in a parallel round, and both archived FTP-75 runs then
    failed the fingerprint check). Every key this function can source is
    overridden; the ones it cannot are named in the refusal message.

    Sources, in order of authority:
      * the sidecar's own `scenario` block -- the run-era metadata verbatim.
        It carries `duration_s` today and will carry more as the simulator
        records more of the meta; whatever it holds is taken as-is.
      * `config.chg_i_ceiling_a` -- the RESOLVED ceiling the run applied.
        Deliberately the resolved value, not the run-era declaration: the
        sidecar does not record whether the scenario declared a ceiling or
        inherited AG105_I_MAX, and the resolved number is the one the demand
        model consumes. The fingerprint's job here is to identify the problem
        the baseline answers, and both sides of the comparison compute it the
        same way, so the convention is self-consistent.
      * the constants block, for the preload (already resolved by the caller).

    A key the sidecar cannot source is simply absent from the returned dict,
    which leaves the live value in place and makes it a named suspect if the
    fingerprint then fails to reconcile."""
    sim = _plant_sim_module()
    cfg = meta.get("config") or {}
    side_scen = meta.get("scenario") or {}
    over = {}
    for key in sim.DP_FINGERPRINT_META_KEYS:
        if key in side_scen:
            over[key] = side_scen[key]
    if cfg.get("chg_i_ceiling_a") is not None:
        over["chg_i_ceiling_a"] = float(cfg["chg_i_ceiling_a"])
    if era_status == "known" and era_preload is not None:
        over["aux_preload_a"] = float(era_preload)
    # An override equal to the live value is noise in the record and in the
    # refusal message; drop it, since applying it is a no-op by construction.
    return {k: v for k, v in over.items()
            if repr(scen_meta.get(k)) != repr(v)}


def _matched_dp_regen_bound(hil, fields, h2_run):
    """Regen energy this run returned, priced as an upper bound in grams.

    Returns None when the run carries no `p_mot_w` column (every campaign
    before 2026-09-01) or when the column never goes negative — i.e. when the
    scenario is not regen-bearing and the boundary costs nothing.  Pure."""
    # `t_s` is load_hil_csv()'s canonical seconds axis; `t` is the raw column.
    t = hil.get("t_s")
    if t is None:
        t = hil.get("t")
    p_mot = hil.get("p_mot_w")
    if t is None or p_mot is None:
        return None
    t = np.asarray(t, dtype=float)
    p = np.asarray(p_mot, dtype=float)
    ok = np.isfinite(t) & np.isfinite(p)
    if ok.sum() < 2:
        return None
    t, p = t[ok], p[ok]
    # Trapezoid over the NEGATIVE part only: `p_mot_w` is signed at the motor
    # node (+ draw, - regen) and its two branches are exclusive by
    # construction, so clipping is a selection, not an approximation.
    regen_j = float(_trapezoid(np.minimum(p, 0.0), t))
    if not np.isfinite(regen_j) or regen_j >= 0.0:
        return None
    gain = fields.get("gfc_dc_gain")
    grams = None if not gain else abs(regen_j) * float(gain)
    pct = (None if (grams is None or not h2_run)
           else 100.0 * grams / float(h2_run))
    note = ("regen-bearing: bound optimistic by <= %s (%.3f J returned at the "
            "motor node). PRE-REGEN-ERA STATEMENT, and it is CORRECT ONLY "
            "WHEN THE BASELINE WAS SOLVED WITHOUT THE CREDIT: from 2026-09-02 "
            "a baseline solved with `eta_regen` earns the same braking credit "
            "the run does, and this bound then goes to ZERO rather than "
            "merely being small. Read `stimulus_era.plant_era.eta_regen` "
            "alongside it. The DP's demand omits regen, so at a matched "
            "terminal SoC it buys with hydrogen what this run got back from "
            "braking — its total is inflated by at most that energy priced at "
            "the Gfc DC gain, and the deviation below is biased in the run's "
            "favour by the same amount. An UPPER bound: the motor-node-to-pack "
            "path is lossy and the plant floors regen at VESC_REGEN_I_MAX_A"
            % ("an unpriced amount" if grams is None
               else "%.6g g%s" % (grams, "" if pct is None
                                  else " (%.2f %% of the run's total)" % pct),
               abs(regen_j)))
    return {"regen_j": regen_j, "bound_optimistic_g": grams,
            "bound_optimistic_pct_of_run": pct, "note": note}


def matched_dp_for_run(analysis, meta, hil, mode="lookup",
                       tol_soc=None, log=print, strict=False,
                       allow_long=False):
    """The delta-SoC-matched DP hydrogen baseline for one scenario run.

    Returns None for a run this comparison does not apply to (a replay, a
    scenario with no drive profile, a CSV with no SoC column). Otherwise a
    dict describing the baseline, INCLUDING the failure cases: a lookup miss
    records `no_cached_solve` with the key the operator can prefill, and any
    exception records `error` rather than failing the run's analysis.

    In `lookup` mode this function NEVER solves. Solves are minutes of compute
    for a drive cycle and belong in `tools/dp_results_db.py prefill`.

    `strict` refuses a cached record whose simulator constant set differs from
    this checkout's, turning provenance drift into a visible miss instead of a
    footnote. `allow_long` lifts the MATCHED_DP_LONG_DURATION_S refusal that
    keeps a `solve` pass from silently becoming a half-hour job."""
    if mode == "off":
        return None
    scenario = analysis.get("name")
    if analysis.get("kind") != "scenario" or not scenario:
        return None
    soc = hil.get("soc")
    if soc is None or not np.isfinite(soc).any():
        return None

    import dp_results_db as dpdb
    if tol_soc is None:
        tol_soc = dpdb.DP_DB_LOOKUP_TOL
    sim = _plant_sim_module()
    scen_meta = (sim.SCENARIOS or {}).get(scenario)
    if not scen_meta or not scen_meta.get("ems_v_profile"):
        return None

    cfg = meta.get("config") or {}
    soc0 = cfg.get("soc0")
    if soc0 is None:
        soc0 = _first_finite(soc)
    target = _last_finite(soc)
    if soc0 is None or target is None:
        return None
    accounting = "physical" if cfg.get("electrical") == "hifi" else "simple"
    # THE DEMAND-MODEL ERA (2026-09-02), resolved from the RUN's own config the
    # way `accounting` above is and the way `eta_chg` is below.  The map is a
    # `--droop design --asymmetry measured` hi-fi number; a run in any other
    # configuration -- and every `--electrical simple` run -- resolves to None,
    # the loss-map-free model, because pricing a simple-mode run against a
    # hi-fi map would bound it with losses its plant never took.
    run_loss_map = sim.loss_map_for_config(
        cfg.get("electrical"), cfg.get("droop_mode"), cfg.get("asymmetry"))
    # THE ROAD-LOAD AND REGEN ERAS (2026-09-02), resolved from the RUN's own
    # config on the identical argument.  `config.drag` is written
    # UNCONDITIONALLY by every run from that date, so an ABSENT key is a
    # pre-round sidecar and resolves to the measured rig road load - the era
    # sentinel, not a default.  `eta_regen` is then read from the run's
    # `scenario` block, where `plant_eta_regen()` already resolved it against
    # the run's drag mode, and falls back to that resolution for a sidecar
    # written before the key existed.
    run_drag = sim.plant_drag_mode(cfg.get("drag"))
    _scen_blk = meta.get("scenario") or {}
    run_eta_regen = _scen_blk.get("eta_regen")
    if run_eta_regen is None:
        run_eta_regen = sim.plant_eta_regen(cfg.get("drag"))
    run_eta_regen = (None if run_eta_regen is None else float(run_eta_regen))
    capacity_ah = float(cfg.get("capacity_ah") or 5.0)
    # Resolved against the run's own config first: `chg_i_ceiling_a` there is
    # the ceiling the run APPLIED, which is what its demand carried, whatever
    # the scenario declares today.
    chg_a = cfg.get("chg_i_ceiling_a")
    chg_a = (sim.dp_chg_ceiling_a(scen_meta) if chg_a is None
             else float(chg_a))
    era_run_exit = (meta.get("scenario") or {}).get("ems_run_exit_s")
    run_exit = (float(sim.SOC_BAND_RUN_EXIT_S)
                if (era_run_exit if era_run_exit is not None
                    else scen_meta.get("ems_run_exit_s")) is None
                else float(era_run_exit if era_run_exit is not None
                           else scen_meta["ems_run_exit_s"]))

    era_run, era_current, era_status = _run_era_preload(scenario, meta)
    era_overrides = _era_overrides(scenario, meta, scen_meta, era_run,
                                   era_status)
    notes = [MATCHED_DP_REGEN_NOTE]
    if era_status == "unknown":
        stimulus_era = "unknown"
        aux = scen_meta.get("aux_preload_a")
        notes.append(
            "meta sidecar carries no `constants` block: the run-era auxiliary "
            "preload is UNKNOWN and the baseline is solved on the CURRENT "
            "scenario metadata")
    elif era_status == "known":
        aux = era_run
        overridden = (era_current is None
                      or abs(era_run - era_current) > 1e-12)
        stimulus_era = {"aux_preload_a_run": era_run,
                        "aux_preload_a_current": era_current,
                        "overridden": bool(overridden)}
        if overridden:
            notes.append(
                "auxiliary preload differs between the run (%.4f A) and this "
                "checkout (%s A): the baseline is solved on the RUN's value"
                % (era_run, "unknown" if era_current is None
                   else "%.4f" % era_current))
    else:
        aux = scen_meta.get("aux_preload_a")
        stimulus_era = {"aux_preload_a_run": None,
                        "aux_preload_a_current": (
                            None if aux is None else float(aux)),
                        "overridden": False}

    # The fingerprint is taken over the RUN-ERA metadata, so an era override
    # is visible in the key rather than hidden behind it -- and so a later
    # `prefill --key-fields` reconstructs the same meta and reaches the same
    # fingerprint instead of being refused for drift.
    fp_meta = dpdb.apply_era_overrides(scen_meta, era_overrides)
    if aux is not None:
        fp_meta["aux_preload_a"] = float(aux)
        era_overrides.setdefault("aux_preload_a", float(aux))
    if run_loss_map is not None:
        # The map has to reach the FINGERPRINT, not only the key field, or the
        # record a prefill stores is unreachable by this lookup -- the M4(b)
        # argument dp_results_db makes for `eta_chg`, verbatim.
        fp_meta["loss_map"] = run_loss_map
        era_overrides.setdefault("loss_map", dict(run_loss_map))
    # Both new eras reach the FINGERPRINT for the same reason, and `drag`
    # doubly so: it is the only one of the four era keys a SCENARIO declares,
    # so a run that overrode it with `--drag` would otherwise fingerprint
    # against the registry's value rather than its own.
    if run_drag is not None:
        fp_meta["drag"] = run_drag
        era_overrides.setdefault("drag", run_drag)
    elif fp_meta.get("drag") is not None:
        # The run resolved to the RIG profile while the scenario declares a
        # compensated one, i.e. a deliberate `--drag rig` zero-regen control.
        # The override must be recorded, or the baseline is solved against the
        # compensated demand the run did not draw.
        fp_meta["drag"] = sim.DRAG_MODE_RIG
        era_overrides.setdefault("drag", sim.DRAG_MODE_RIG)
    if run_eta_regen is not None:
        fp_meta["eta_regen"] = run_eta_regen
        era_overrides.setdefault("eta_regen", run_eta_regen)
    if isinstance(stimulus_era, dict):
        stimulus_era["overrides"] = dict(era_overrides)
        stimulus_era["fingerprint_keys"] = list(sim.DP_FINGERPRINT_META_KEYS)
        # THE PLANT-ERA FIELDS AN ANALYST MUST READ before comparing this run
        # with one from another campaign, recorded HERE so the comparison does
        # not depend on anybody opening the sidecar. `droop_mode` joined the
        # list 2026-09-02: it is not merely descriptive any more, because the
        # DP's static-loss map is a `--droop design` fit and resolves to NO MAP
        # in any other mode, so a `--droop measured` run is priced against a
        # different demand model without saying so anywhere else.
        stimulus_era["plant_era"] = {
            "electrical": cfg.get("electrical"),
            "droop_mode": cfg.get("droop_mode"),
            "asymmetry": cfg.get("asymmetry"),
            "eta_chg": cfg.get("eta_chg"),
            "loss_map": (None if run_loss_map is None
                         else sim.loss_map_canonical(run_loss_map)),
            "drag": run_drag,
            "eta_regen": run_eta_regen,
        }
    fields = dpdb.problem_fields(
        scenario,
        profile_fingerprint=sim.dp_profile_fingerprint(scenario, fp_meta),
        soc0=float(soc0), capacity_ah=capacity_ah,
        charger_accounting=accounting, stage_dt=0.1, n_share=41,
        soc_step=5.0e-6, chg_a=chg_a, lambda_dev=0.0,
        aux_preload_a=aux, run_exit_s=run_exit, target_soc=float(target),
        era_overrides=era_overrides,
        # THE CHARGER ERA, resolved from the SAME run-era metadata the
        # fingerprint is taken over (fix, 2026-09-01).  `problem_fields`
        # defaults this to None, which is the PRE-efficiency era; leaving the
        # default in place while `fp_meta` carried the sidecar's `eta_chg` 0.88
        # made every post-efficiency run key against a 1:1-era baseline. The
        # lookup then missed silently, and a `--matched-dp solve` produced a
        # baseline for a plant the run was never executed against.
        eta_chg=sim.dp_eta_chg(fp_meta),
        # THE DEMAND-MODEL ERA, on the identical argument: `problem_fields`
        # defaults it to None (the loss-map-free era), and leaving the default
        # in place on a loss-map-era run would key the run against a baseline
        # solved on a different demand model.
        loss_map=run_loss_map,
        # THE ROAD-LOAD AND REGEN ERAS, on the identical argument again: the
        # defaults are the pre-round configuration, and leaving them in place
        # on a compensated regen-era run would key it against a baseline
        # solved on a demand model 4.5x larger with no braking credit.
        drag=fp_meta.get("drag"),
        eta_regen=run_eta_regen)
    key = dpdb.make_key(fields)

    h2_run = _last_finite(hil["h2_cum_g"]) if "h2_cum_g" in hil else None
    notes.append(MATCHED_DP_GFC_NOTE)
    # The demand-model era, stated on EVERY run: which of the two models the
    # baseline was priced with is the single largest source of deviation the
    # 2026-09-02 decomposition found, and a reader comparing two runs across
    # the boundary must see it without opening the key fields.
    notes.append(
        "DEMAND MODEL: the baseline is priced against %s. The loss-map era "
        "carries the plant's static losses (the per-node bleed on N_BUS and "
        "N_MOT) and the realized `--droop design` bus law, which makes the "
        "bound TIGHTER and BLEED-INVARIANT: the run and its bound then move "
        "together when the bleed is retuned. A baseline in one era is NOT "
        "comparable with one in the other -- the two differed by 4.35 %% on "
        "`ems-ftp75-dp` and -0.20 %% on `ems-dp-replay` when the map landed."
        % sim.loss_map_era_label(run_loss_map))
    # ── QUANTIFY THE REGEN BOUNDARY FOR *THIS* RUN (2026-09-02) ─────────────
    # MATCHED_DP_REGEN_NOTE states the boundary qualitatively on every run.
    # A run that actually brakes deserves the MAGNITUDE, because the direction
    # is knowable and it flatters the run: the DP's demand is
    # `max(0, F*v)` (gen_dp_ems_table.build_demand), so the DP never receives
    # the braking energy the live plant returns to the pack, and at a MATCHED
    # terminal SoC it must therefore buy that SoC with hydrogen instead. Its
    # total is inflated by at most the returned energy priced at the Gfc DC
    # gain, and the run's `pct_deviation` is biased in the run's favour by the
    # same amount. `regen_j` is the energy the plant actually returned
    # (integral of min(p_mot_w, 0)); the gram figure is an UPPER bound because
    # every conversion between the motor node and the pack is lossy and the
    # plant floors regen at VESC_REGEN_I_MAX_A.
    regen = _matched_dp_regen_bound(hil, fields, h2_run)
    if regen is not None:
        notes.append(regen["note"])
    out = {"key": key, "key_fields": fields, "target_soc": float(target),
           "soc0": float(soc0), "accounting": accounting,
           "h2_run_g": h2_run,
           "delta_soc_run": float(target) - float(soc0),
           "regen_bound": regen,
           "stimulus_era": stimulus_era, "notes": notes}

    duration_s = float(scen_meta.get("duration_s") or 0.0)
    try:
        rec = dpdb.lookup(fields, tol_soc=tol_soc, strict=strict)
        source = "cache"
        if rec is None and mode == "solve":
            est_s = matched_dp_cost_estimate_s(duration_s)
            if duration_s > MATCHED_DP_LONG_DURATION_S and not allow_long:
                out.update({"status": "solve_refused_long", "source": None})
                out["notes"].append(
                    "scenario duration %.0f s exceeds the %.0f s solve "
                    "gate; the baseline costs of the order of %.0f min. Pass "
                    "--matched-dp-allow-long, or prefill it separately."
                    % (duration_s, MATCHED_DP_LONG_DURATION_S, est_s / 60.0))
                return out
            log("[hil_report_analysis] solving DP baseline for %s "
                "(target SoC %.6f, %.0f s cycle, order of %.0f s)"
                % (scenario, target, duration_s, est_s))
            rec = dpdb.solve_and_store(fields, float(target), log=log)
            source = "solve"
    except Exception as exc:                     # never fail a run's analysis
        out.update({"status": "error",
                    "error": "%s: %s" % (type(exc).__name__, exc)})
        return out

    if rec is None:
        out.update({"status": "no_cached_solve", "source": None})
        # The hint reproduces the KEY, not an approximation of it: a prefill
        # rebuilt from a handful of flags can miss an input (the charge
        # ceiling, the run-era preload, the run-exit time) and solve a
        # different problem that then never satisfies this lookup (MED-5).
        out["notes"].append(
            "no stored solve within %g SoC of the target%s. Solve exactly "
            "this problem with `python tools/dp_results_db.py prefill "
            "--key-fields @<file>` where <file> holds this block's "
            "`key_fields` object -- INCLUDING its `era_overrides`, which is "
            "what rebuilds the run-era scenario metadata and so avoids a "
            "fingerprint-drift refusal -- or approximately with `--scenario %s "
            "--soc0 %r --accounting %s --capacity-ah %r --chg-a %r "
            "--aux-preload %r --run-exit %r%s --dsoc-span=%.5f:%.5f:1`"
            % (tol_soc,
               " (strict provenance matching is ON)" if strict else "",
               scenario, float(soc0), accounting, capacity_ah, chg_a,
               fields["aux_preload_a"], run_exit,
               # The DEMAND-MODEL ERA has to be on the approximate command
               # too, or the prefill it suggests solves the wrong problem and
               # this lookup misses again on the next pass.
               "" if run_loss_map is None else " --loss-map plant",
               target - soc0, target - soc0))
        return out

    h2_dp = rec["h2_g"] if accounting == "physical" else rec["h2_plant_g"]
    out.update({
        "status": "ok", "source": source,
        "h2_dp_g": rec["h2_g"], "h2_dp_plant_g": rec["h2_plant_g"],
        "h2_dp_compared_g": h2_dp,
        "residual_soc": rec.get("residual_soc"),
        "converged": rec.get("converged"),
        "lambda_term": rec.get("lambda_term"),
        "delta_soc_dp": rec.get("delta_soc"),
        "stored_target_soc": rec.get("target_soc"),
        "wall_s": rec.get("wall_s"),
        "provenance_drift": bool(rec.get("provenance_drift")),
        "pct_deviation": (None if (h2_run is None or not h2_dp)
                          else 100.0 * (h2_run - h2_dp) / h2_dp),
    })
    if rec.get("provenance_drift"):
        out["notes"].append(
            "PROVENANCE DRIFT: this baseline was solved under a different "
            "hil_plant_sim constant set than the current checkout. The hash "
            "moves on any module-level constant, including ones this solve "
            "never reads, so treat it as a warning; re-run with "
            "--matched-dp-strict to refuse a drifted record outright")
    if abs(float(rec.get("target_soc", target)) - target) > 1e-9:
        out["notes"].append(
            "baseline was solved at terminal SoC %.6f, the run ended at "
            "%.6f (within the %g lookup tolerance)"
            % (rec["target_soc"], target, tol_soc))
    if not rec.get("converged"):
        out["notes"].append(
            "the DP's own terminal-SoC bisection did NOT converge (residual "
            "%+.2e); quote the residual with the deviation"
            % (rec.get("residual_soc") or 0.0))
    return out


def analyze_run(run, report_dir, results_json, no_move=False, force=False,
                matched_dp="lookup", matched_dp_tol=None,
                matched_dp_strict=False, matched_dp_allow_long=False):
    """Analyze one run end to end. Returns the per-run analysis dict."""
    warnings = []
    if no_move:
        dest = run.csv_path.parent
    else:
        dest, move_warnings = move_run_files(run, report_dir)
        warnings.extend(move_warnings)

    meta = _read_json(run.meta_path) or {}
    suite = suite_result_for(results_json, run)
    hil = attach_derived(load_hil_csv(run.csv_path))

    blg_fw = ((meta.get("replay_source") or {}).get("blg_fw_version")
              if run.kind == "replay" else None)
    cfg_fw = blg_fw if blg_fw is not None else \
        (results_json or {}).get("meta", {}).get("target_fw")

    cfg = dict(load_run_config(dest, report_dir))
    cfg["_run_name"] = run.folder_name
    cfg["_fw_version"] = cfg_fw
    cfg["_hil_build"] = True

    data = adapt_to_benchlog(hil)
    saved, skipped = run_standard_figures(data, hil, cfg, dest,
                                          run.csv_path, force=force)

    analysis = {
        "kind": run.kind,
        "name": run.name,
        "folder": run.folder_name,
        "electrical_mode": run.elec_mode,
        "csv": str(run.csv_path),
        "rows": int(hil["t_s"].shape[0]),
        "duration_s": (float(hil["t_s"][-1]) if hil["t_s"].size else 0.0),
        "meta_mode": meta.get("mode"),
        "meta_status": meta.get("status"),
        # The EMS strategy this run was driven by, and its ROLE (2026-09-01).
        # Recorded from the run's OWN meta sidecar, so a re-analysis of an old
        # report names the strategy that ran rather than the one the scenario
        # currently declares.
        "ems_strategy": meta.get("ems_strategy"),
        "ems_role": ems_strategy_role(meta.get("ems_strategy")),
        "suite_passed": (suite or {}).get("passed"),
        "suite_mode": (suite or {}).get("mode"),
        "suite_cmd_mode": (suite or {}).get("cmd_mode"),
        "suite_checks": [{"name": c.get("name"), "passed": c.get("passed"),
                          "detail": c.get("detail")}
                         for c in (suite or {}).get("checks", [])],
        "figures": saved,
        "skipped_figures": [{"name": n, "reason": r} for n, r in skipped],
        "warnings": warnings,
        "cfg_fw_version": cfg_fw,
    }
    grace_s = float(((meta.get("results") or {}).get("warm_reset_grace_s"))
                    or DEFAULT_GRACE_S)
    analysis.update(_observation_summary(hil, grace_s))

    if run.kind == "replay":
        analysis["replay"] = _analyze_replay(hil, meta, cfg, dest, blg_fw,
                                             run.csv_path, force=force)

    mdp = matched_dp_for_run(analysis, meta, hil, mode=matched_dp,
                             tol_soc=matched_dp_tol,
                             strict=matched_dp_strict,
                             allow_long=matched_dp_allow_long)
    if mdp is not None:
        analysis["matched_dp"] = mdp

    write_json_atomic(dest / "analysis.json", analysis)
    write_text_atomic(dest / "ANALYSIS.md", render_run_markdown(analysis))
    return analysis


# Seconds of run start that run_hil_suite excludes from its fault verdicts:
# a latch carried in from the PREVIOUS run's settle window clears through the
# fw v23 warm reset inside it. meta.json's results.warm_reset_grace_s carries
# the value the simulator actually used; this is the fallback.
DEFAULT_GRACE_S = 2.0


def _observation_summary(hil, grace_s=DEFAULT_GRACE_S):
    """Observation coverage, final state, and BOTH fault unions for a run.

    Two unions are reported because they answer different questions:
      * fault_union -- every bit seen anywhere in the run, including the
        carried-in latch from the predecessor run's settle window.
      * fault_union_post_grace -- bits seen at t >= grace_s, which is the
        window run_hil_suite judges its fault checks on. This is the one the
        summary table shows; the whole-run union reads as a fault on almost
        every run in a sequential suite and would bury the real outcomes.
    """
    t = hil["t_s"]
    n = t.shape[0]
    state = hil.get("state")
    obs = np.isfinite(state) if state is not None else np.zeros(n, bool)
    flags = hil.get("fault_flags")

    def _union(mask):
        if flags is None:
            return 0
        m = mask & np.isfinite(flags)
        if not m.any():
            return 0
        return int(np.bitwise_or.reduce(flags[m].astype(np.int64)))

    union = _union(np.ones(n, bool))
    union_pg = _union(t >= grace_s)
    final_state = None
    if state is not None and obs.any():
        final_state = int(state[obs][-1])
    return {
        "obs_frames": int(obs.sum()),
        "obs_coverage": (float(obs.sum()) / n) if n else 0.0,
        "grace_s": float(grace_s),
        "final_state": final_state,
        "fault_union": union,
        "fault_names": decode_fault_bits(union),
        "fault_union_post_grace": union_pg,
        "fault_names_post_grace": decode_fault_bits(union_pg),
    }


def resolve_source_fw(sidecar_fw, header_fw):
    """(effective_fw, provenance, disagreement_note) for a replay source.

    The DECODED header is authoritative when a decode succeeded: it is read
    from the log itself, while the sidecar's blg_fw_version is a value the
    simulator recorded at replay time and could be stale (a re-decoded or
    replaced log under the same name). When they disagree the header wins and
    the disagreement is reported, never silently resolved.

    Returns effective_fw = None when NEITHER is available -- which is NOT the
    same as "same control law" and must be surfaced as a hedge, since a log
    old enough to have no fw field in its header (format v1) is precisely the
    kind that predates the current law.
    """
    note = None
    if header_fw is not None and sidecar_fw is not None \
            and int(header_fw) != int(sidecar_fw):
        note = ("source fw version disagreement: decoded header says v%d, the "
                "run's meta.json sidecar says v%d -- the decoded header is "
                "authoritative and was used" % (int(header_fw),
                                                int(sidecar_fw)))
    if header_fw is not None:
        return int(header_fw), "decoded BLG header", note
    if sidecar_fw is not None:
        return int(sidecar_fw), "meta.json sidecar (no decode)", note
    return None, "unknown", note


def _analyze_replay(hil, meta, cfg, dest, blg_fw, csv_path, force=False):
    """Source-BLG decode, alignment, deviation figures and metrics.

    Degrades rather than raising on a missing OR undecodable source log: the
    run's base figures and observation summary are produced either way, and
    the reason lands in analysis.json / ANALYSIS.md.
    """
    info = {"sidecar_fw_version": blg_fw,
            "blg_version": (meta.get("replay_source") or {}).get("blg_version")}

    def _finish_without_source(reason):
        fw, prov, note = resolve_source_fw(blg_fw, None)
        info.update(_law_fields(fw, prov, note))
        info["note"] = reason
        return info

    blg_path = locate_source_blg(meta)
    if blg_path is None:
        info["source_available"] = False
        return _finish_without_source(
            "source .BLG not found (meta replay_source.path and "
            "logs/<basename> both missing) -- deviation figures skipped")
    info["source_available"] = True
    info["source_path"] = str(blg_path)

    try:
        blg, header = decode_source_blg(blg_path)
    except Exception as exc:
        # A truncated or corrupt source log must not cost this run its base
        # figures, its observation summary, or its analysis.json -- degrade
        # exactly like "source not found" and record why.
        info["source_decode_error"] = "%s: %s" % (type(exc).__name__, exc)
        return _finish_without_source(
            "source .BLG at %s could not be decoded (%s) -- deviation figures "
            "skipped" % (blg_path, info["source_decode_error"]))

    header_fw = header.get("fw_version")
    info["blg_header_fw_version"] = header_fw
    eff_fw, prov, disagree = resolve_source_fw(blg_fw, header_fw)
    info.update(_law_fields(eff_fw, prov, disagree))

    blg_len = blg["t_us"].shape[0] if "t_us" in blg else 0
    hil_idx, blg_idx = align_replay(hil, blg_len)
    info["source_records"] = int(blg_len)
    info["aligned_ticks"] = int(hil_idx.size)
    if hil_idx.size == 0:
        info["note"] = ("no aligned samples (all rows in the preamble or "
                        "without an observation frame) -- figures skipped")
        return info

    # L3: the run's own declared command-replay intent, from the sidecar.
    _rc = (meta.get("replay_source") or {}).get("replay_commands")
    if _rc is None:
        _rc = (meta.get("config") or {}).get("replay_commands")
    metrics = compute_replay_metrics(hil, blg, hil_idx, blg_idx,
                                     replay_commands=_rc)
    info["metrics"] = metrics

    rendered = []
    for name, builder in (
            ("hil_replay_overlay", hil_replay_overlay),
            ("hil_replay_injection_fidelity", hil_replay_injection_fidelity),
            ("hil_replay_response_deviation", hil_replay_response_deviation)):
        rendered.append(name)
        out = dest / ("%s.png" % name)
        if not _needs_render(out, csv_path, force):
            continue
        if name == "hil_replay_response_deviation":
            fig = builder(hil, blg, hil_idx, blg_idx, cfg, eff_fw, metrics)
        else:
            fig = builder(hil, blg, hil_idx, blg_idx, cfg, eff_fw)
        _save(fig, out)
    info["figures"] = rendered
    return info


def _law_fields(eff_fw, provenance, disagreement):
    """The control-law comparability block shared by every replay path."""
    return {
        "effective_fw_version": eff_fw,
        "fw_version_provenance": provenance,
        "fw_version_disagreement": disagreement,
        "control_law_known": eff_fw is not None,
        "different_control_law": bool(eff_fw is not None
                                      and eff_fw < DIFFERENT_LAW_FW),
        "caveat": _law_caveat(eff_fw),
    }


# ==========================================================================
# Markdown rendering
# ==========================================================================

def _fmt(v, spec="%.4g"):
    if v is None:
        return "—"
    if isinstance(v, float) and not math.isfinite(v):
        return "—"
    return spec % v if isinstance(v, float) else str(v)


def _metrics_table(title, table):
    lines = ["", "**%s**" % title, "",
             "| signal | n | RMS Δ | max abs Δ | mean Δ | note |",
             "|---|---|---|---|---|---|"]
    notes = []
    for key, m in sorted(table.items()):
        # A row that is not a comparison says so IN THE ROW (2026-09-02): the
        # numbers are still printed, because suppressing them would hide the
        # evidence for the tag, but they are no longer readable as deviations.
        tag = m.get("not_exercised")
        if tag:
            notes.append("- `%s`: %s." % (key, tag))
        elif m.get("commanded_but_zero"):
            # L3: a REAL comparison that looks like a not-exercised row. Said
            # in the notes so the reader is not left to infer which it is.
            notes.append("- `%s`: %s." % (key, m["commanded_but_zero"]))
        lines.append("| %s | %d | %s | %s | %s | %s |"
                     % (key, m.get("n", 0), _fmt(m.get("rms")),
                        _fmt(m.get("max_abs")), _fmt(m.get("mean")),
                        "NOT EXERCISED" if tag else ""))
    if notes:
        lines += [""] + notes
    return lines


def _render_matched_dp_block(a):
    """The matched-DP section of one run's ANALYSIS.md.  [] when absent."""
    m = a.get("matched_dp")
    if not m:
        return []
    L = ["## Delta-SoC-matched DP baseline", ""]
    status = m.get("status")
    if status == "ok":
        L += ["- run hydrogen: %s g" % _fmt(m.get("h2_run_g")),
              "- DP baseline (%s accounting): %s g"
              % (m.get("accounting"), _fmt(m.get("h2_dp_compared_g"))),
              "- deviation from the DP bound: %s"
              % ("—" if m.get("pct_deviation") is None
                 else "%+.2f %%" % m["pct_deviation"]),
              "- terminal SoC: run %.6f (delta %+.6f), DP baseline solved at "
              "%.6f (delta %+.6f)"
              % (m.get("target_soc", float("nan")),
                 m.get("delta_soc_run") or 0.0,
                 m.get("stored_target_soc", float("nan")),
                 m.get("delta_soc_dp") or 0.0),
              "- bisection residual: %s SoC (converged: %s)"
              % ("—" if m.get("residual_soc") is None
                 else "%+.2e" % m["residual_soc"],
                 "yes" if m.get("converged") else "no"),
              "- source: %s (key `%s`)%s"
              % (m.get("source") or "—", (m.get("key") or "")[:16],
                 "  **provenance drift**" if m.get("provenance_drift")
                 else "")]
    elif status == "solve_refused_long":
        L += ["- solve REFUSED: this scenario is longer than the "
              "%.0f s gate. Pass `--matched-dp-allow-long`, or prefill the "
              "baseline separately." % MATCHED_DP_LONG_DURATION_S]
    elif status == "no_cached_solve":
        L += ["- NO CACHED SOLVE for this run's terminal SoC "
              "(%.6f). The comparison is not made; prefill the results "
              "database and re-run the analysis."
              % m.get("target_soc", float("nan")),
              "- key: `%s`" % (m.get("key") or "")]
    else:
        L += ["- baseline unavailable: %s" % m.get("error", status)]
    L += [""]
    for note in m.get("notes") or []:
        L.append("> %s" % note)
    L += [""]
    return L


def render_run_markdown(a):
    """ANALYSIS.md body for one run."""
    L = ["# %s" % a["folder"], "",
         "- kind: %s" % a["kind"],
         "- electrical mode: %s" % (a.get("electrical_mode") or "—"),
         "- simulator mode: %s (status %s)" % (a.get("meta_mode") or "—",
                                               a.get("meta_status") or "—"),
         "- rows: %d over %.3f s" % (a["rows"], a["duration_s"]),
         "- observation-frame coverage: %.2f%% (%d frames)"
         % (100.0 * a["obs_coverage"], a["obs_frames"]),
         "- final state: %s" % _fmt(a["final_state"]),
         "- fault union (whole run): 0x%04X (%s)"
         % (a["fault_union"], ", ".join(a["fault_names"]) or "none"),
         "- fault union (t >= %.1f s, the suite's judged window): 0x%04X (%s)"
         % (a.get("grace_s", DEFAULT_GRACE_S), a["fault_union_post_grace"],
            ", ".join(a["fault_names_post_grace"]) or "none"),
         "- suite verdict: %s" % ("PASS" if a.get("suite_passed") else
                                  ("FAIL" if a.get("suite_passed") is False
                                   else "—")),
         ""]
    if a.get("ems_strategy"):
        L.insert(-1, "- EMS strategy: `%s`%s"
                 % (a["ems_strategy"],
                    "" if not a.get("ems_role") else " (%s)" % a["ems_role"]))
    if a.get("ems_role") == "demonstration":
        # Said BEFORE any of this run's numbers are read: its h2/delta_soc pair
        # measures a mechanism, not a competitive energy-management score, and
        # run_hil_suite.py's EMS frontier check excludes it by construction.
        L += ["> **DYNAMICS DEMONSTRATION — not on the EMS frontier.** The "
              "strategy `%s` is registered `frontier_eligible: False`; this "
              "run is exercised for the MECHANISM it puts on the wire. Do NOT "
              "rank its `h2_cum_g` / `delta_soc` against the frontier legs."
              % a["ems_strategy"], ""]

    L += _render_matched_dp_block(a)

    if a.get("suite_checks"):
        L += ["## Suite checks", "", "| check | result | detail |",
              "|---|---|---|"]
        for c in a["suite_checks"]:
            detail = (c.get("detail") or "").replace("|", "\\|")
            L.append("| %s | %s | %s |" % (c["name"],
                                           "PASS" if c["passed"] else "FAIL",
                                           detail))
        L.append("")

    L += ["## Figures", ""]
    for name in a["figures"]:
        L.append("- %s.png" % name)
    if a.get("replay", {}).get("figures"):
        for name in a["replay"]["figures"]:
            L.append("- %s.png" % name)
    L.append("")
    if a["skipped_figures"]:
        L += ["### Skipped", ""]
        for s in a["skipped_figures"]:
            L.append("- %s — %s" % (s["name"], s["reason"]))
        L.append("")

    rep = a.get("replay")
    if rep:
        L += ["## Replay deviation", "",
              "- source: %s" % (rep.get("source_path") or "unavailable"),
              "- source BLG format v%s" % rep.get("blg_version"),
              "- source fw: v%s (from %s)"
              % (rep.get("effective_fw_version"),
                 rep.get("fw_version_provenance")),
              "- aligned ticks: %s" % _fmt(rep.get("aligned_ticks")), ""]
        if rep.get("fw_version_disagreement"):
            L += ["> WARNING: %s" % rep["fw_version_disagreement"], ""]
        if not rep.get("control_law_known", True):
            L += ["> Control-law comparability UNVERIFIED — the source "
                  "firmware version is unknown, so this run's response "
                  "comparison carries no law-equivalence claim.", ""]
        if rep.get("source_decode_error"):
            L += ["> Source decode FAILED: %s" % rep["source_decode_error"],
                  ""]
        if rep.get("caveat"):
            L += ["> " + rep["caveat"].replace("\n", "  \n> "), ""]
        if rep.get("note"):
            L += ["Note: %s" % rep["note"], ""]
        m = rep.get("metrics") or {}
        if m.get("injection"):
            L += _metrics_table(
                "Injection fidelity (HIL injected − source log)",
                m["injection"])
        if m.get("response"):
            L += _metrics_table(
                "Response deviation (HIL firmware − source log)",
                m["response"])
        if m.get("fault_mismatch_fraction") is not None:
            L += ["",
                  "Fault-flag mismatch: %.3f%% of aligned ticks "
                  "(HIL union %s; source union %s)."
                  % (100.0 * m["fault_mismatch_fraction"],
                     ", ".join(m.get("hil_fault_names") or []) or "none",
                     ", ".join(m.get("blg_fault_names") or []) or "none"), ""]

    if a["warnings"]:
        L += ["## Warnings", ""] + ["- %s" % w for w in a["warnings"]] + [""]
    return "\n".join(L) + "\n"


def _render_matched_dp_summary(analyses):
    """The campaign's cross-strategy matched-DP table.  [] when no run has one.

    This is the per-campaign form of the WORK_QUEUE section 1 deliverable: one
    row per drive-cycle run, each ranked against a DP bound solved to that
    run's OWN terminal SoC, so the hydrogen figures in the `pct deviation`
    column are comparable to each other."""
    rows = [a for a in analyses if a.get("matched_dp")]
    if not rows:
        return []
    rows.sort(key=lambda a: (a.get("name") or "",
                             (a["matched_dp"].get("pct_deviation")
                              if a["matched_dp"].get("pct_deviation")
                              is not None else float("inf"))))
    L = ["## Delta-SoC-matched DP comparison", "",
         "| run | strategy | role | h2 run (g) | h2 DP (g) | pct deviation |"
         " delta SoC (run) | residual | status |",
         "|---|---|---|---|---|---|---|---|---|"]
    for a in rows:
        m = a["matched_dp"]
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                 % (a["folder"],
                    "`%s`" % a["ems_strategy"] if a.get("ems_strategy")
                    else "—",
                    a.get("ems_role") or "—",
                    _fmt(m.get("h2_run_g")),
                    _fmt(m.get("h2_dp_compared_g")),
                    "—" if m.get("pct_deviation") is None
                    else "%+.2f %%" % m["pct_deviation"],
                    "—" if m.get("delta_soc_run") is None
                    else "%+.6f" % m["delta_soc_run"],
                    "—" if m.get("residual_soc") is None
                    else "%+.1e" % m["residual_soc"],
                    m.get("status") or "—"))
    L += ["",
          "Each row's DP baseline is solved to THAT run's terminal state of "
          "charge, which is the only condition under which two strategies' "
          "hydrogen totals rank anything. A `no_cached_solve` row has no "
          "baseline in `tools/dp_db/`; its ANALYSIS.md carries the key to "
          "prefill.",
          "",
          "> %s" % MATCHED_DP_REGEN_NOTE,
          "",
          "> %s" % MATCHED_DP_GFC_NOTE, ""]
    return L


def render_summary_markdown(meta, analyses, errors, ems_comparison=None):
    """ANALYSIS_SUMMARY.md body for a whole report.

    `ems_comparison` is the relative path of the EMS-strategy comparison
    document when hil_ems_comparison rendered one for this campaign, and None
    when the campaign holds no comparable group. The link is emitted only in
    the first case: a link to a file that was never written is worse than no
    link at all.
    """
    L = ["# HIL report analysis summary", "",
         "- report date: %s" % meta.get("date", "—"),
         "- target fw: v%s" % meta.get("target_fw", "—"),
         "- board: %s:%s" % (meta.get("teensy_ip", "—"), meta.get("port", "—")),
         "- electrical preference: %s" % meta.get("electrical_pref", "—"),
         "- command mode: %s" % meta.get("mode", "—"),
         "- runs analyzed: %d (errors: %d)" % (len(analyses), len(errors)),
         "",
         "This file covers the runs analyzed by the invocation that wrote it. "
         "A `--runs` invocation rewrites it with that subset only; re-run "
         "without `--runs` for the whole report.",
         "",
         "## Runs", "",
         "| run | kind | mode | suite | obs cov | final state |"
         " fault union (post-grace) | I_cmd RMS Δ | I_cmd max Δ |",
         "|---|---|---|---|---|---|---|---|---|"]
    for a in analyses:
        rep = a.get("replay") or {}
        resp = ((rep.get("metrics") or {}).get("response") or {}).get("I_cmd")
        rms = _fmt((resp or {}).get("rms"))
        mx = _fmt((resp or {}).get("max_abs"))
        # Markers qualify a NUMBER; appending one to the "no metric" dash
        # would read as a qualified value that does not exist.
        if resp and resp.get("rms") is not None:
            # NOT EXERCISED first (2026-09-02): on an entry that replayed no
            # commands these two columns are the SOURCE log's trajectory, not a
            # deviation, and the largest number in the whole table (ML0144's
            # 8.635) was one of them. The law markers qualify a comparison; this
            # says there was none, so it replaces rather than joins them.
            if resp.get("not_exercised"):
                rms += " x"
                mx += " x"
            elif rep.get("different_control_law"):
                rms += " *"
            elif not rep.get("control_law_known", True):
                rms += " ?"
        L.append("| %s | %s | %s | %s | %.1f%% | %s | %s | %s | %s |"
                 % (a["folder"], a["kind"],
                    a.get("suite_mode") or a.get("electrical_mode") or "—",
                    "PASS" if a.get("suite_passed") else
                    ("FAIL" if a.get("suite_passed") is False else "—"),
                    100.0 * a["obs_coverage"], _fmt(a["final_state"]),
                    ", ".join(a["fault_names_post_grace"]) or "none",
                    rms, mx))
    L += ["",
          "Fault unions are taken over t >= the run's grace bound (default "
          "%.1f s), the window run_hil_suite judges its fault checks on; a "
          "latch carried in from the previous run's settle window is "
          "excluded. Each run's ANALYSIS.md carries the whole-run union too."
          % DEFAULT_GRACE_S,
          "",
          "`x` the entry replayed NO commands: the board's motor command is "
          "identically 0 A, so the two I_cmd columns are the SOURCE log's own "
          "trajectory and not a deviation of anything. "
          "`*` source log firmware < v%d — different wheel and control law; "
          "the response deviation is a character comparison, not a trace "
          "match. `?` source firmware version unknown — control-law "
          "comparability is UNVERIFIED, not assumed equal. Every replay is "
          "OPEN LOOP: firmware commands do not influence the injected "
          "trajectory." % DIFFERENT_LAW_FW,
          "",
          "Scenario runs are identified by name AND electrical mode "
          "(`scenario_<name>_<mode>`), so the two modes of one scenario are "
          "separate rows.", ""]

    L += _render_matched_dp_summary(analyses)

    if ems_comparison:
        L += ["## EMS strategy comparison", "",
              "The cross-strategy comparison of this campaign's "
              "energy-management runs, grouped by drive stimulus, is in "
              "[%s](%s). Its figures are under `%s/` and every number it "
              "quotes is in `%s`."
              % (ems_comparison, ems_comparison,
                 _ems_comparison_module().FIGURE_SUBDIR,
                 _ems_comparison_module().JSON_NAME),
              ""]

    if errors:
        L += ["## Errors", ""]
        for name, msg in errors:
            L.append("- %s — %s" % (name, msg))
        L.append("")

    L += ["## Summary figures", "",
          "- summary_replay_deviation.png",
          "- summary_run_health.png", ""]
    return "\n".join(L) + "\n"


# ==========================================================================
# Summary figures
# ==========================================================================

def summary_replay_deviation(analyses):
    """Bar chart of per-replay RMS I_cmd deviation. None if no replay data."""
    rows = []
    for a in analyses:
        rep = a.get("replay") or {}
        resp = ((rep.get("metrics") or {}).get("response") or {}).get("I_cmd")
        if resp and resp.get("rms") is not None:
            rows.append((a["name"], resp["rms"],
                         a.get("suite_mode") or "—",
                         bool(rep.get("different_control_law")),
                         not rep.get("control_law_known", True)))
    if not rows:
        return None
    rows.sort(key=lambda r: r[1], reverse=True)
    names = [r[0] + (" (law?)" if r[4] else "") for r in rows]
    vals = [r[1] for r in rows]
    colors = [COLORS["share"] if r[2] == "deviation" else COLORS["I_cmd"]
              for r in rows]
    hatch = ["//" if r[3] else "" for r in rows]

    fig, ax = plt.subplots(figsize=(10, max(4.0, 0.32 * len(rows) + 2.0)))
    bars = ax.barh(np.arange(len(rows)), vals, color=colors, height=0.7)
    for bar, h in zip(bars, hatch):
        if h:
            bar.set_hatch(h)
            bar.set_edgecolor(TEXT_COLOR)
    ax.set_yticks(np.arange(len(rows)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    bl_figures._style_axes(ax, ylabel=None, xlabel="RMS Δ I_cmd [A]  "
                           "(HIL − source SD log, aligned ticks)")
    handles = [plt.Line2D([], [], color=COLORS["I_cmd"], linewidth=6,
                          label="conformance"),
               plt.Line2D([], [], color=COLORS["share"], linewidth=6,
                          label="deviation"),
               plt.Line2D([], [], color="#ffffff", markeredgecolor=TEXT_COLOR,
                          marker="s", markerfacecolor="#ffffff", linewidth=0,
                          label="hatched: source fw < v%d (different law); "
                          "'(law?)': source fw unknown, comparability "
                          "unverified" % DIFFERENT_LAW_FW)]
    bl_figures._legend(ax, handles, [h.get_label() for h in handles],
                       loc="lower right")
    fig.suptitle("Replay response deviation (open loop)", color=TEXT_COLOR,
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


def summary_run_health(analyses):
    """Observation-frame coverage per run, coloured by fault outcome."""
    if not analyses:
        return None
    names = [a["folder"] for a in analyses]
    cov = [100.0 * a["obs_coverage"] for a in analyses]
    colors = [COLORS["V_bus"] if a["fault_union_post_grace"]
              else COLORS["I_fc"] for a in analyses]

    fig, ax = plt.subplots(figsize=(10, max(4.0, 0.32 * len(names) + 2.0)))
    ax.barh(np.arange(len(names)), cov, color=colors, height=0.7)
    ax.set_yticks(np.arange(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 105)
    bl_figures._style_axes(ax, ylabel=None,
                           xlabel="Observation-frame coverage [%]")
    for i, a in enumerate(analyses):
        if a["fault_union_post_grace"]:
            ax.text(min(cov[i] + 1.0, 101.0), i,
                    ", ".join(a["fault_names_post_grace"]), va="center",
                    fontsize=7, color=TEXT_COLOR)
    handles = [plt.Line2D([], [], color=COLORS["I_fc"], linewidth=6,
                          label="no post-grace fault bits"),
               plt.Line2D([], [], color=COLORS["V_bus"], linewidth=6,
                          label="post-grace fault bits set")]
    bl_figures._legend(ax, handles, [h.get_label() for h in handles],
                       loc="lower right")
    fig.suptitle("Run health: observation coverage and post-grace fault "
                 "outcome",
                 color=TEXT_COLOR, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


# ==========================================================================
# Driver
# ==========================================================================

class NotAReportError(ValueError):
    """The target directory is not a run_hil_suite report folder.

    Raised instead of writing summary artifacts into an unrelated directory
    (most plausibly 'HIL Results/' itself, one level too high).
    """


def analyze_report(report_dir, only=None, no_move=False, force=False,
                   log=print, matched_dp="lookup", matched_dp_tol=None,
                   matched_dp_strict=False, matched_dp_allow_long=False):
    """Analyze every run in report_dir. Returns (analyses, errors).

    Raises NotAReportError when the directory holds neither a run nor a
    results.json -- see that exception.
    """
    report_dir = Path(report_dir)
    results_json = _read_json(report_dir / "results.json") or {}
    runs = discover_runs(report_dir)
    if not runs and not (report_dir / "results.json").is_file():
        # Pointing at 'HIL Results/' itself (or any unrelated directory) would
        # otherwise silently drop ANALYSIS_SUMMARY.md and analysis_summary.json
        # into it. A real report has runs, a results.json, or both.
        raise NotAReportError(
            "%s holds no HIL runs and no results.json -- this does not look "
            "like a run_hil_suite report folder. Pass the hil_report_<ts> "
            "directory itself, not its parent." % report_dir)
    if only:
        wanted = set(only)
        runs = [r for r in runs
                if r.name in wanted or r.folder_name in wanted]
    log("[hil_report_analysis] %d run(s) in %s" % (len(runs), report_dir))

    analyses, errors = [], []
    for run in runs:
        try:
            a = analyze_run(run, report_dir, results_json, no_move=no_move,
                            force=force, matched_dp=matched_dp,
                            matched_dp_tol=matched_dp_tol,
                            matched_dp_strict=matched_dp_strict,
                            matched_dp_allow_long=matched_dp_allow_long)
        except Exception as exc:
            errors.append((run.folder_name, "%s: %s" % (type(exc).__name__,
                                                        exc)))
            log("[hil_report_analysis] ERROR %s: %s"
                % (run.folder_name, exc))
            traceback.print_exc(file=sys.stderr)
            continue
        analyses.append(a)
        for w in a["warnings"]:
            log("[hil_report_analysis] warning (%s): %s" % (run.folder_name, w))
        log("[hil_report_analysis] %s: %d figures, %d skipped"
            % (run.folder_name, len(a["figures"]), len(a["skipped_figures"])))

    meta = results_json.get("meta", {})
    # The summary figures are stale if ANY analyzed run's CSV is newer than
    # them, so they are staleness-checked against the newest CSV in the set.
    newest_csv = None
    newest_mtime = -1.0
    for a in analyses:
        try:
            mtime = Path(a["csv"]).stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime, newest_csv = mtime, Path(a["csv"])
    for name, builder in (("summary_replay_deviation",
                           summary_replay_deviation),
                          ("summary_run_health", summary_run_health)):
        out = report_dir / ("%s.png" % name)
        if newest_csv is None:
            if out.exists() and not force:
                continue
        elif not _needs_render(out, newest_csv, force):
            continue
        fig = builder(analyses)
        if fig is None:
            log("[hil_report_analysis] skipping %s (no applicable runs)" % name)
            continue
        _save(fig, out)

    # ── EMS-STRATEGY COMPARISON STAGE ───────────────────────────────────────
    # Runs AFTER every per-run analysis.json exists, because it reads those
    # files rather than the in-memory analyses, and BEFORE ANALYSIS_SUMMARY.md
    # is written, so the summary can link only a document that exists.
    #
    # ALWAYS in `lookup` mode: a matched-DP solve is tens of minutes for one
    # FTP-75 leg, and a routine analysis pass must never silently become that.
    # A missing bound renders as a status in the comparison table; the operator
    # fills it in with an explicit
    # `hil_ems_comparison.py --matched-dp solve --matched-dp-allow-long` pass.
    #
    # A `--runs` invocation is skipped outright: the comparison ranks runs
    # against each other, and a subset rewrite would silently drop legs from a
    # published document.
    ems_doc = None
    if not only:
        try:
            payload = _ems_comparison_module().build_ems_comparison(
                report_dir, matched_dp="lookup", matched_dp_tol=matched_dp_tol,
                matched_dp_strict=matched_dp_strict, force=force, log=log)
            if payload:
                ems_doc = _ems_comparison_module().MARKDOWN_NAME
        except Exception as exc:            # never fail the analysis pass
            log("[hil_report_analysis] EMS comparison stage failed: %s: %s"
                % (type(exc).__name__, exc))
            traceback.print_exc(file=sys.stderr)

    write_json_atomic(report_dir / "analysis_summary.json",
                      {"meta": meta,
                       "runs": analyses,
                       "errors": [{"run": n, "error": m} for n, m in errors]})
    write_text_atomic(report_dir / "ANALYSIS_SUMMARY.md",
                      render_summary_markdown(meta, analyses, errors,
                                              ems_comparison=ems_doc))
    return analyses, errors


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report_dir",
                    help="HIL suite report folder (resolved against CWD, then "
                         "repo-root 'HIL Results/')")
    ap.add_argument("--runs", nargs="+", metavar="NAME",
                    help="restrict to these run names (steady, ML0146, ...) "
                         "or folder names (scenario_steady). NOTE: "
                         "ANALYSIS_SUMMARY.md is rewritten to cover only the "
                         "restricted subset")
    ap.add_argument("--no-move", action="store_true",
                    help="analyze in place; do not reorganize into subfolders")
    ap.add_argument("--force", action="store_true",
                    help="regenerate figures that already exist")
    ap.add_argument("--matched-dp", default="lookup",
                    choices=["off", "lookup", "solve"],
                    help="delta-SoC-matched DP hydrogen baseline for every "
                         "drive-cycle run. 'lookup' (default) reads "
                         "tools/dp_db/ and NEVER solves - a miss is recorded "
                         "with the key to prefill; 'solve' computes and stores "
                         "a missing baseline, which costs seconds for a 61 s "
                         "cycle and tens of minutes for FTP-75; 'off' skips "
                         "the comparison entirely")
    ap.add_argument("--matched-dp-tol", type=float, default=None,
                    help="terminal-SoC tolerance a cached baseline may differ "
                         "by (default dp_results_db.DP_DB_LOOKUP_TOL = 1e-5). "
                         "Widening it trades a miss, which is visible, for a "
                         "baseline solved at a different SoC outcome, which "
                         "is not")
    ap.add_argument("--matched-dp-strict", action="store_true",
                    help="refuse a cached baseline whose hil_plant_sim "
                         "constants_hash differs from this checkout's. "
                         "Without it a drifted record is USED and annotated, "
                         "because the hash also moves on constants the solve "
                         "never reads")
    ap.add_argument("--matched-dp-allow-long", action="store_true",
                    help="permit `--matched-dp solve` on a scenario longer "
                         "than %.0f s (FTP-75 costs tens of minutes)"
                         % MATCHED_DP_LONG_DURATION_S)
    args = ap.parse_args(argv)

    try:
        report_dir = resolve_report_dir(args.report_dir)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        analyses, errors = analyze_report(report_dir, only=args.runs,
                                          no_move=args.no_move,
                                          force=args.force,
                                          matched_dp=args.matched_dp,
                                          matched_dp_tol=args.matched_dp_tol,
                                          matched_dp_strict=args.matched_dp_strict,
                                          matched_dp_allow_long=args.matched_dp_allow_long)
    except NotAReportError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print("[hil_report_analysis] %d run(s) analyzed, %d error(s); wrote %s"
          % (len(analyses), len(errors), report_dir / "ANALYSIS_SUMMARY.md"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
