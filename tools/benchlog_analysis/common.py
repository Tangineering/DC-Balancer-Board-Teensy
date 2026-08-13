"""Shared helpers for the bench-log analysis toolkit.

Depends on numpy + stdlib only (the decoder itself, tools/decode_benchlog.py,
is stdlib-only). This module makes tools/decode_benchlog.py importable by
inserting its containing directory onto sys.path -- done lazily inside
_decoder_module() rather than at import time, so importing common.py never
has side effects. (Under the PyInstaller-frozen GUI exe the insert is inert:
decode_benchlog resolves from the bundle via its hidden-import, ahead of any
sys.path entry.)
"""
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

# tools/benchlog_analysis/common.py -> tools/benchlog_analysis -> tools -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG = {
    "filters": {
        "share_act_tau_s": 0.020,
        "I_fc_tau_s": 0.010,
        "I_batt_tau_s": 0.010,
    }
}

CSV_COLUMNS = ["t_us", "share_sp", "share_act", "v_sp", "v_act", "I_fc",
               "I_batt", "gFC", "gBT", "V_bus", "I_cmd", "fault_flags",
               "ps_phase", "dc_phase", "trap_phase", "flags"]

# v3 decode_benchlog CSVs (tools/decode_benchlog.py CSV_HEADER_V3) add four
# source/node voltage channels (V_fc, V_batt, V_chg, V_rgn) after I_cmd.
# load_csv() accepts either layout; the extra columns are simply extra keys
# in the returned dict -- no figure currently reads them. Format v4 changes
# only the .BLG HEADER (adds profileAmp/profileB, surfaced via
# decode_blg().header and the decode_report.txt banner line, not the CSV);
# v4 CSVs are byte-identical in header/layout to v3 CSVs and are matched by
# this same CSV_COLUMNS_V3 branch.
CSV_COLUMNS_V3 = ["t_us", "share_sp", "share_act", "v_sp", "v_act", "I_fc",
                  "I_batt", "gFC", "gBT", "V_bus", "I_cmd", "V_fc", "V_batt",
                  "V_chg", "V_rgn", "fault_flags", "ps_phase", "dc_phase",
                  "trap_phase", "flags"]

_decoder = None


def _decoder_module():
    """Import tools/decode_benchlog.py as a plain module, on first use.

    sys.path is extended (not restored) so repeated calls are cheap and the
    module identity stays stable across the process -- matches how the
    decoder is imported everywhere else in this package.
    """
    global _decoder
    if _decoder is None:
        tools_dir = str(TOOLS_DIR)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import decode_benchlog
        _decoder = decode_benchlog
    return _decoder


def decode_benchlog_module():
    """Public accessor for the lazily-imported decode_benchlog module."""
    return _decoder_module()


def _deep_fill(dst, defaults):
    """Recursively fill missing keys in dst from defaults, in place.

    Only fills keys absent from dst; never overwrites a key the user (or a
    prior run) already set, even to a value that looks like a default.
    """
    for key, default_val in defaults.items():
        if key not in dst:
            dst[key] = json.loads(json.dumps(default_val))  # deep copy
        elif isinstance(default_val, dict) and isinstance(dst[key], dict):
            _deep_fill(dst[key], default_val)
    return dst


def load_or_create_config(run_dir):
    """Load run_dir/analysis_config.json, creating it from defaults if absent.

    If the file exists, it is loaded as-is and any keys missing relative to
    DEFAULT_CONFIG are filled in IN MEMORY ONLY -- the file on disk is never
    rewritten by this function. This is a hard idempotency requirement: the
    user hand-edits taus in the file and re-runs ingestion, and their edits
    must never be clobbered.

    If the file does not exist, DEFAULT_CONFIG is written to it (indent=2,
    trailing newline) and a copy is returned.
    """
    run_dir = Path(run_dir)
    cfg_path = run_dir / "analysis_config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r") as f:
                cfg = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"{cfg_path} is not valid JSON ({e}) -- fix or delete the "
                f"file to regenerate it with defaults") from e
        _deep_fill(cfg, DEFAULT_CONFIG)
        return cfg

    # Atomic create: a crash / full disk mid-write must not leave a truncated
    # file behind -- the never-clobber rule above would then refuse to repair
    # it and every later run would fail parsing it.
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    tmp_path = cfg_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, cfg_path)
    return cfg


def load_csv(csv_path):
    """Parse a decode_benchlog CSV into a dict of float64 numpy arrays.

    Accepts either the v1/v2 (16-column, CSV_COLUMNS) or the v3 (20-column,
    CSV_COLUMNS_V3 -- adds V_fc, V_batt, V_chg, V_rgn after I_cmd) header;
    the matching column list is used to parse the rest of the file, so a
    v1/v2 CSV's returned dict has exactly the same 16 keys it always has,
    and a v3 CSV's dict additionally has the four new voltage keys. Blank
    cells (v_sp, v_act, ps_phase, dc_phase, trap_phase can all be blank per
    the decoder's CSV format) become NaN. A derived key
    t_s = (t_us - t_us[0]) / 1e6 (seconds since the first sample) is added.
    """
    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    if header == CSV_COLUMNS:
        columns = CSV_COLUMNS
    elif header == CSV_COLUMNS_V3:
        columns = CSV_COLUMNS_V3
    else:
        raise ValueError(
            f"unexpected CSV header in {csv_path}: {header!r}, "
            f"expected {CSV_COLUMNS!r} (v1/v2) or {CSV_COLUMNS_V3!r} (v3)")

    n = len(rows)
    data = {col: np.full(n, np.nan, dtype=np.float64) for col in columns}
    for i, row in enumerate(rows):
        if len(row) != len(columns):
            # A short row means a partially-written CSV (e.g. ingest was
            # interrupted mid-write); silently zipping it would leave the
            # missing columns as garbage that plots as real data.
            raise ValueError(
                f"{csv_path}: row {i + 2} has {len(row)} cells, expected "
                f"{len(columns)} -- partial/corrupt CSV, re-ingest the .BLG")
        for col, cell in zip(columns, row):
            data[col][i] = float(cell) if cell != "" else np.nan

    if n > 0:
        # t_us is micros() and wraps every 2^32 us (~71.6 min); the decoder is
        # deliberately wrap-safe, so a run CAN straddle a wrap. Rebuild elapsed
        # time from the modular per-sample steps rather than raw differences.
        t_us = data["t_us"]
        steps = np.diff(t_us) % 2.0**32
        data["t_s"] = np.concatenate(([0.0], np.cumsum(steps))) / 1.0e6
    else:
        data["t_s"] = np.empty(0, dtype=np.float64)

    return data


def lowpass(x, t_s, tau_s):
    """Single-pole causal IIR low-pass filter, per-sample dt from t_s.

    y[n] = y[n-1] + (1 - exp(-dt_n / tau)) * (x[n] - y[n-1])

    - tau_s <= 0 returns an unfiltered copy of x.
    - dt_n <= 0 (non-increasing timestamp) holds the previous output.
    - NaN input holds the filter state (does not reset it) and produces a
      NaN output at that sample; the first valid (non-NaN) sample
      initializes y to x at that sample. dt is measured from the last VALID
      sample, so the filter advances by the full elapsed time across a NaN
      gap instead of a single nominal sample period.
    """
    x = np.asarray(x, dtype=np.float64)
    t_s = np.asarray(t_s, dtype=np.float64)
    if x.shape != t_s.shape:
        raise ValueError(
            f"lowpass: x and t_s must have the same shape "
            f"({x.shape} vs {t_s.shape})")
    n = x.shape[0]
    y = np.empty(n, dtype=np.float64)

    if tau_s <= 0:
        y[:] = x
        return y

    have_state = False
    state = np.nan
    t_last_valid = np.nan
    for i in range(n):
        xi = x[i]
        if np.isnan(xi):
            y[i] = np.nan
            continue
        if not have_state:
            state = xi
            have_state = True
            t_last_valid = t_s[i]
            y[i] = state
            continue
        dt = t_s[i] - t_last_valid
        if dt <= 0:
            y[i] = state
            continue
        alpha = 1.0 - np.exp(-dt / tau_s)
        state = state + alpha * (xi - state)
        t_last_valid = t_s[i]
        y[i] = state

    return y
