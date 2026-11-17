"""ngspice_run.py - drive KiCad 9.0's bundled ngspice shared library through ctypes.

Public API
----------
run_deck(deck, vectors=None, plots="all", ngbehavior=None, codemodels=True,
         use_subprocess=True, background=False, timeout_s=600, extra_commands=None)
    -> SimResult

    deck            netlist text (str containing a newline) or a path to a deck file.
                    The deck must contain its own analysis line (.tran/.dc/.ac/.op) and .end.
    vectors         list of vector names to return (case-insensitive). None = every vector
                    of every requested plot.
    plots           "all" (every plot produced by this run, e.g. tran1, dc1, ac1) or "last"
                    (only the plot that is current when the run finishes).
    ngbehavior      None, or a compatibility mode string ("ps", "psa", "lt", "lta", "kia", ...).
                    Issued as 'set ngbehavior=<mode>' before the circuit is parsed.
    codemodels      True loads every XSPICE .cm in KiCad's lib/ngspice folder (analog, digital,
                    xtradev, xtraevt, table, spice2poly, tlines) before the circuit is parsed.
                    KiCad 9.0 ships no spinit, so this is the only route to XSPICE models.
    use_subprocess  True (default) runs each deck in a fresh Python process, so every run starts
                    from a cleanly initialised DLL. False runs in-process (faster; the runner
                    issues 'destroy all' + 'remcirc' between decks).
    background      True uses 'bg_run' and polls ngSpice_running(); False uses blocking 'run'.
    extra_commands  list of ngspice control commands issued after the run (e.g. 'print ...');
                    their output lands in the captured log.

SimResult fields
    plots   dict plot_name -> dict vec_name(lower) -> numpy array (complex for AC data)
    vec     dict vec_name -> array from the LAST plot that contains it (convenience)
    meas    dict meas_name(lower) -> float, parsed from '.meas' lines in stdout
    log     full captured stdout/stderr text
    ok      True when no fatal error was detected
    errors  list of error lines

Command-line
    python ngspice_run.py --selftest     runs the verification tests and prints PASS/FAIL.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from ctypes import (CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_double,
                    c_int, c_short, c_void_p)
from dataclasses import dataclass, field

import numpy as np

KICAD_ROOT = os.environ.get("KICAD_NGSPICE_ROOT", r"C:\Program Files\KiCad\9.0")
DLL_PATH = os.path.join(KICAD_ROOT, "bin", "ngspice.dll")
CM_DIR = os.path.join(KICAD_ROOT, "lib", "ngspice")
CODEMODELS = ["analog.cm", "digital.cm", "xtradev.cm", "xtraevt.cm",
              "table.cm", "spice2poly.cm", "tlines.cm"]

SCRATCH_DIR = os.environ.get("NGRUN_SCRATCH",
                             r"C:\Users\ricky\AppData\Local\Temp\claude\sim_2026-11-14")

_MEAS_RE =re.compile(r"^\s*([A-Za-z_][\w.]*)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


@dataclass
class SimResult:
    plots: dict = field(default_factory=dict)
    vec: dict = field(default_factory=dict)
    meas: dict = field(default_factory=dict)
    log: str = ""
    ok: bool = True
    errors: list = field(default_factory=list)

    def __getitem__(self, name):
        return self.vec[name.lower()]


def _short_path(path: str) -> str:
    """Return the Windows 8.3 short form of an existing path (unchanged elsewhere)."""
    if os.name != "nt" or " " not in path:
        return path
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
    return buf.value if 0 < n < 1024 else path


# --------------------------------------------------------------------------- ctypes layer
class _NgComplex(Structure):
    _fields_ = [("cx_real", c_double), ("cx_imag", c_double)]


class _VectorInfo(Structure):
    _fields_ = [("v_name", c_char_p), ("v_type", c_int), ("v_flags", c_short),
                ("v_realdata", POINTER(c_double)), ("v_compdata", POINTER(_NgComplex)),
                ("v_length", c_int)]


_SendChar = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
_SendStat = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
_ControlledExit = CFUNCTYPE(c_int, c_int, c_bool, c_bool, c_int, c_void_p)
_SendData = CFUNCTYPE(c_int, c_void_p, c_int, c_int, c_void_p)
_SendInitData = CFUNCTYPE(c_int, c_void_p, c_int, c_void_p)
_BGThreadRunning = CFUNCTYPE(c_int, c_bool, c_int, c_void_p)


class NgSpice:
    """One loaded instance of ngspice.dll (one per process)."""

    _instance = None

    def __init__(self):
        if os.path.isdir(os.path.dirname(DLL_PATH)) and hasattr(os, "add_dll_directory"):
            self._dll_dir = os.add_dll_directory(os.path.dirname(DLL_PATH))
        os.environ.setdefault("SPICE_LIB_DIR", CM_DIR)
        self.lib = ctypes.CDLL(DLL_PATH)
        self._lines: list[str] = []
        self._bg_running = False
        self._exited = False
        # keep references so the callbacks are not garbage collected
        self._cb = (_SendChar(self._send_char), _SendStat(self._send_stat),
                    _ControlledExit(self._controlled_exit), _SendData(0),
                    _SendInitData(0), _BGThreadRunning(self._bg_thread))
        self.lib.ngSpice_Init.argtypes = [_SendChar, _SendStat, _ControlledExit, _SendData,
                                          _SendInitData, _BGThreadRunning, c_void_p]
        self.lib.ngSpice_Command.argtypes = [c_char_p]
        self.lib.ngSpice_Command.restype = c_int
        self.lib.ngSpice_Circ.argtypes = [POINTER(c_char_p)]
        self.lib.ngSpice_Circ.restype = c_int
        self.lib.ngGet_Vec_Info.argtypes = [c_char_p]
        self.lib.ngGet_Vec_Info.restype = POINTER(_VectorInfo)
        self.lib.ngSpice_CurPlot.restype = c_char_p
        self.lib.ngSpice_AllPlots.restype = POINTER(c_char_p)
        self.lib.ngSpice_AllVecs.argtypes = [c_char_p]
        self.lib.ngSpice_AllVecs.restype = POINTER(c_char_p)
        self.lib.ngSpice_running.restype = c_bool
        self.lib.ngSpice_Init(self._cb[0], self._cb[1], self._cb[2], self._cb[3],
                              self._cb[4], self._cb[5], None)
        self.codemodels_loaded = False

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = NgSpice()
        return cls._instance

    # callbacks
    def _send_char(self, text, _id, _user):
        s = text.decode("utf-8", "replace") if text else ""
        for prefix in ("stdout ", "stderr "):
            if s.startswith(prefix):
                s = (s[len(prefix):] if prefix == "stdout " else "[stderr] " + s[len(prefix):])
                break
        self._lines.append(s)
        return 0

    def _send_stat(self, _text, _id, _user):
        return 0

    def _controlled_exit(self, status, unload, quit_, _id, _user):
        self._exited = True
        self._lines.append(f"[controlled_exit status={status} unload={unload} quit={quit_}]")
        return 0

    def _bg_thread(self, not_running, _id, _user):
        self._bg_running = not not_running
        return 0

    # commands
    def cmd(self, command: str) -> int:
        return self.lib.ngSpice_Command(command.encode("utf-8"))

    def take_log(self) -> str:
        out = "\n".join(self._lines)
        self._lines = []
        return out

    def load_codemodels(self):
        if self.codemodels_loaded:
            return
        for cm in CODEMODELS:
            path = os.path.join(CM_DIR, cm)
            if os.path.isfile(path):
                # ngspice's codemodel command neither strips quotes nor accepts spaces, so the
                # 8.3 short form of "C:\Program Files\..." is passed instead.
                self.cmd(f"codemodel {_short_path(path).replace(chr(92), '/')}")
        self.codemodels_loaded = True

    def load_circuit(self, text: str) -> int:
        lines = [ln for ln in text.splitlines()]
        arr = (c_char_p * (len(lines) + 1))()
        arr[:-1] = [ln.encode("utf-8") for ln in lines]
        arr[-1] = None
        return self.lib.ngSpice_Circ(arr)

    def all_plots(self) -> list[str]:
        p = self.lib.ngSpice_AllPlots()
        out, i = [], 0
        while p and p[i]:
            out.append(p[i].decode())
            i += 1
        return out

    def all_vecs(self, plot: str) -> list[str]:
        p = self.lib.ngSpice_AllVecs(plot.encode())
        out, i = [], 0
        while p and p[i]:
            out.append(p[i].decode())
            i += 1
        return out

    def get_vec(self, plot: str, name: str):
        info = self.lib.ngGet_Vec_Info(f"{plot}.{name}".encode())
        if not info:
            return None
        v = info.contents
        n = v.v_length
        if n <= 0:
            return np.zeros(0)
        if v.v_realdata:
            return np.ctypeslib.as_array(v.v_realdata, shape=(n,)).copy()
        if v.v_compdata:
            raw = np.ctypeslib.as_array(ctypes.cast(v.v_compdata, POINTER(c_double)),
                                        shape=(2 * n,)).copy()
            return raw[0::2] + 1j * raw[1::2]
        return np.zeros(0)


# --------------------------------------------------------------------------- in-process run
def _read_deck(deck: str) -> str:
    if "\n" not in deck and os.path.isfile(deck):
        with open(deck, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return deck


def _run_inproc(deck, vectors=None, plots="all", ngbehavior=None, codemodels=True,
                background=False, timeout_s=600, extra_commands=None) -> SimResult:
    ng = NgSpice.get()
    text = _read_deck(deck)
    res = SimResult()
    # reset any previous circuit / data
    ng.cmd("destroy all")
    ng.cmd("remcirc")
    ng.take_log()
    if ngbehavior:
        ng.cmd(f"set ngbehavior={ngbehavior}")
    else:
        ng.cmd("unset ngbehavior")
    if codemodels:
        ng.load_codemodels()
    plots_before = set(ng.all_plots())
    ng.load_circuit(text)
    if background:
        ng.cmd("bg_run")
        t0 = time.time()
        time.sleep(0.05)
        while ng.lib.ngSpice_running():
            if time.time() - t0 > timeout_s:
                ng.cmd("bg_halt")
                res.errors.append(f"timeout after {timeout_s} s")
                break
            time.sleep(0.02)
    else:
        ng.cmd("run")
    for c in extra_commands or []:
        ng.cmd(c)
    all_now = ng.all_plots()
    new_plots = [p for p in all_now if p not in plots_before and p != "const"]
    cur = ng.lib.ngSpice_CurPlot()
    cur = cur.decode() if cur else None
    if plots == "last":
        new_plots = [cur] if cur and cur != "const" else []
    want = None if vectors is None else {v.lower() for v in vectors}
    for p in new_plots:
        d = {}
        for name in ng.all_vecs(p):
            if want is not None and name.lower() not in want:
                continue
            arr = ng.get_vec(p, name)
            if arr is not None:
                d[name.lower()] = arr
        res.plots[p] = d
    # plots are listed newest first by ngspice; fill .vec so the newest plot wins
    for p in reversed(new_plots):
        res.vec.update(res.plots.get(p, {}))
    res.log = ng.take_log()
    _post_process(res)
    return res


def _post_process(res: SimResult):
    for ln in res.log.splitlines():
        low = ln.lower()
        if ("error" in low and "no error" not in low) or "fatal" in low or "simulation interrupted" in low \
                or "timestep too small" in low:
            res.errors.append(ln.strip())
        m = _MEAS_RE.match(ln)
        if m and not ln.lstrip().lower().startswith(("doing", "note", "warning", "reference",
                                                      "initial", "total", "source", "no.", "circuit")):
            try:
                res.meas[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    fatal = [e for e in res.errors if "fatal" in e.lower() or "timestep too small" in e.lower()
             or "interrupted" in e.lower() or "timeout" in e.lower()]
    res.ok = not fatal and (bool(res.plots) and any(len(v) for v in res.plots.values()))


# --------------------------------------------------------------------------- subprocess run
def run_deck(deck, vectors=None, plots="all", ngbehavior=None, codemodels=True,
             use_subprocess=True, background=False, timeout_s=600, extra_commands=None) -> SimResult:
    if not use_subprocess:
        return _run_inproc(deck, vectors, plots, ngbehavior, codemodels, background,
                           timeout_s, extra_commands)
    text = _read_deck(deck)
    scratch = SCRATCH_DIR if os.path.isdir(SCRATCH_DIR) else None
    with tempfile.TemporaryDirectory(prefix="ngrun_", dir=scratch, ignore_cleanup_errors=True) as td:
        deck_path = os.path.join(td, "deck.cir")
        with open(deck_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        spec = dict(deck=deck_path, vectors=vectors, plots=plots, ngbehavior=ngbehavior,
                    codemodels=codemodels, background=background, timeout_s=timeout_s,
                    extra_commands=extra_commands, out=os.path.join(td, "out.npz"))
        spec_path = os.path.join(td, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as fh:
            json.dump(spec, fh)
        try:
            proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--worker", spec_path],
                                  capture_output=True, text=True, timeout=timeout_s + 60,
                                  encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            r = SimResult(ok=False, errors=[f"subprocess timeout after {timeout_s + 60} s"])
            return r
        res = SimResult()
        logp = spec["out"] + ".log"
        if os.path.isfile(logp):
            with open(logp, "r", encoding="utf-8", errors="replace") as fh:
                res.log = fh.read()
        if proc.returncode != 0 or not os.path.isfile(spec["out"]):
            res.ok = False
            res.log += "\n[worker stdout]\n" + proc.stdout + "\n[worker stderr]\n" + proc.stderr
            res.errors.append(f"worker exit code {proc.returncode}")
            _post_process(res)
            res.ok = False
            return res
        with np.load(spec["out"], allow_pickle=False) as z:
            for key in z.files:
                p, _, name = key.partition("|")
                res.plots.setdefault(p, {})[name] = np.array(z[key])
        with open(spec["out"] + ".order", "r", encoding="utf-8") as fh:
            order = json.load(fh)
        # rebuild in ngspice order (newest first) and fill .vec newest-wins
        res.plots = {p: res.plots.get(p, {}) for p in order}
        for p in reversed(order):
            res.vec.update(res.plots[p])
        _post_process(res)
        return res


def _worker(spec_path):
    with open(spec_path, "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    out = spec.pop("out")
    res = _run_inproc(**spec)
    flat = {f"{p}|{n}": a for p, d in res.plots.items() for n, a in d.items()}
    np.savez(out, **flat)
    with open(out + ".order", "w", encoding="utf-8") as fh:
        json.dump(list(res.plots.keys()), fh)
    with open(out + ".log", "w", encoding="utf-8") as fh:
        fh.write(res.log)
    # flush-free hard exit: ngspice's atexit handlers on Windows can hang the process
    sys.stdout.flush()
    os._exit(0)


def ngspice_version() -> str:
    r = run_deck("* ver\nV1 1 0 1\nR1 1 0 1\n.op\n.end\n", extra_commands=["version -s"])
    for ln in r.log.splitlines():
        if "ngspice" in ln.lower() and any(ch.isdigit() for ch in ln):
            return ln.strip()
    return "unknown"


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        _worker(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)
        import test_ngspice_run  # noqa: E402
        sys.exit(test_ngspice_run.main())
    else:
        print(__doc__)
