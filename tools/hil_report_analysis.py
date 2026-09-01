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
    """[(mask, name)] for the observation frame's aux byte, LSB first."""
    m = _plant_sim_module()
    return [(m.AUX_FC_REG, "FC_REG"), (m.AUX_BT_REG, "BT_REG"),
            (m.AUX_MPPT_DISABLE, "MPPT_DISABLE"),
            (m.AUX_CBAL_DISABLE, "CBAL_DISABLE")]


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


def compute_replay_metrics(hil, blg, hil_idx, blg_idx):
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


HIL_FIGURES = [
    ("hil_state_and_switches", hil_state_and_switches),
    ("hil_charger_and_soc", hil_charger_and_soc),
    ("hil_share_raw_vs_emitted", hil_share_raw_vs_emitted),
    ("hil_h2_and_soc", hil_h2_and_soc),
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


def analyze_run(run, report_dir, results_json, no_move=False, force=False):
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

    metrics = compute_replay_metrics(hil, blg, hil_idx, blg_idx)
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
             "| signal | n | RMS Δ | max abs Δ | mean Δ |",
             "|---|---|---|---|---|"]
    for key, m in sorted(table.items()):
        lines.append("| %s | %d | %s | %s | %s |"
                     % (key, m.get("n", 0), _fmt(m.get("rms")),
                        _fmt(m.get("max_abs")), _fmt(m.get("mean"))))
    return lines


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


def render_summary_markdown(meta, analyses, errors):
    """ANALYSIS_SUMMARY.md body for a whole report."""
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
            if rep.get("different_control_law"):
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
                   log=print):
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
                            force=force)
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

    write_json_atomic(report_dir / "analysis_summary.json",
                      {"meta": meta,
                       "runs": analyses,
                       "errors": [{"run": n, "error": m} for n, m in errors]})
    write_text_atomic(report_dir / "ANALYSIS_SUMMARY.md",
                      render_summary_markdown(meta, analyses, errors))
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
    args = ap.parse_args(argv)

    try:
        report_dir = resolve_report_dir(args.report_dir)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        analyses, errors = analyze_report(report_dir, only=args.runs,
                                          no_move=args.no_move,
                                          force=args.force)
    except NotAReportError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print("[hil_report_analysis] %d run(s) analyzed, %d error(s); wrote %s"
          % (len(analyses), len(errors), report_dir / "ANALYSIS_SUMMARY.md"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
