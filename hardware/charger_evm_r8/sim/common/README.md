# sim/common: the shared ngspice runner

This folder holds `ngspice_run.py`, the Python module that drives the ngspice shared library bundled with KiCad 9.0,
and `test_ngspice_run.py`, its verification tests. Every simulation under `sim/` uses this runner, so that all decks
run on the same simulator build with the same code-model set.

## 1. Simulator

| Item | Value |
|---|---|
| Library | `C:\Program Files\KiCad\9.0\bin\ngspice.dll` (loaded with `ctypes.CDLL`; its folder is added with `os.add_dll_directory`) |
| Version | ngspice-46 (build date 14 Apr 2026, reported by `version -s`) |
| XSPICE code models | `C:\Program Files\KiCad\9.0\lib\ngspice\{analog,digital,xtradev,xtraevt,table,spice2poly,tlines}.cm` |
| `spinit` | None is shipped with KiCad 9.0. The runner therefore loads every `.cm` file with the `codemodel` command before it parses each circuit. |
| Python | `C:\Users\ricky\miniforge3\python.exe` (numpy required; matplotlib for the simulation scripts) |

The `codemodel` command neither strips quotation marks nor accepts a path that contains a space. The runner
therefore passes the 8.3 short form of the path (`C:/PROGRA~1/KiCad/9.0/lib/ngspice/analog.cm`). If 8.3 names are
disabled on the volume, the code models do not load and the log contains `Error opening code model`; in that case,
set the environment variable `KICAD_NGSPICE_ROOT` to a copy of the KiCad folder at a path without spaces.

## 2. API

```python
import sys; sys.path.insert(0, r"C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy\hardware\charger_evm_r8\sim\common")
from ngspice_run import run_deck

r = run_deck(deck_text_or_path,
             vectors=None,          # list of vector names to keep; None keeps all
             plots="all",           # "all" plots of this run, or "last" (the current plot only)
             ngbehavior=None,       # e.g. "ps", "psa", "lt", "lta", "kia"
             codemodels=True,       # load the XSPICE .cm files
             use_subprocess=True,   # fresh Python process per deck (default)
             background=False,      # True: 'bg_run' and poll ngSpice_running()
             timeout_s=600,
             extra_commands=None)   # control commands run after the analysis, e.g. ["print v(out)"]
```

`run_deck` returns a `SimResult` with these fields:

| Field | Content |
|---|---|
| `plots` | `dict` plot name (`tran1`, `dc1`, `ac1`, `op1`, ...) to `dict` vector name (lower case) to `numpy` array. AC vectors are complex. |
| `vec` | All vectors of all returned plots merged; where two plots hold the same name, the newest plot wins. `r["out"]` is shorthand for `r.vec["out"]`. |
| `meas` | `.meas` results parsed from the simulator's standard output, `dict` name (lower case) to `float`. A failed measurement is absent. |
| `log` | The complete captured standard output and standard error of ngspice (standard-error lines carry the prefix `[stderr]`). |
| `ok` | `True` when the run produced at least one non-empty plot and the log holds no fatal error, `timestep too small` or interruption. |
| `errors` | Every log line that contains "error", "fatal" or "timestep too small". |

Node voltages appear under the node name (`out`), branch currents under `<source>#branch`. The sweep variable of a
`.dc` analysis is `v-sweep` (or the source name, depending on the sweep). A deck must carry its own analysis lines and
`.end`. Callers must check `r.ok` and must inspect `r.errors`, because ngspice reports some convergence problems only
as log text.

The `ngspice_version()` helper returns the version line.

## 3. Execution model

With `use_subprocess=True` (the default), `run_deck` writes the deck and a JSON specification to a temporary folder
under `C:\Users\ricky\AppData\Local\Temp\claude\sim_2026-11-14\` (or the system temporary folder if that path does not
exist; override with the environment variable `NGRUN_SCRATCH`), starts `ngspice_run.py --worker` in a new process,
and reads the vectors back from an `.npz` file. Each deck therefore starts from a freshly initialised DLL. The
overhead is approximately 0.15 s per deck.

With `use_subprocess=False`, the deck runs in the calling process. The runner issues `destroy all` and `remcirc`
before each deck and sets or unsets `ngbehavior`, so that no vector, circuit or compatibility mode carries over. This
mode is faster for large parameter sweeps of small decks. However, a simulator crash then terminates the calling
process, and an ngspice internal state that `destroy`/`remcirc` does not clear would carry over. The subprocess mode
is the recommended default for result-producing scripts.

## 4. Verification

The command `python ngspice_run.py --selftest` (equivalently `python test_ngspice_run.py`) runs ten tests. All ten
passed on 2026-11-14 in 2.1 s:

| Test | Check | Result |
|---|---|---|
| `rc_transient_vs_analytic` | RC step response (R = 1 kOhm, C = 1 uF) against 1 - exp(-t/RC) over 0-5 ms | max error 0.5 uV |
| `dc_sweep_divider` | `.dc` sweep of a 3:1 divider | max error 8.9e-16 V |
| `meas_capture` | `.meas` FIND, WHEN and AVG parsed from standard output | t_half = 0.69315 ms (analytic RC ln 2) |
| `bsource_behavioural` | B-source with a ternary expression and a `tanh` current source | errors 0 and 2.2e-16 |
| `xspice_digital_and_with_bridges` | `adc_bridge` to `d_and`, `d_or`, `d_inverter` to `dac_bridge` | NAND and OR truth tables hold on 720 samples |
| `diode_model` | Diode at 1 mA against N Vt ln(I/IS + 1) | 0.65512 V, equal to the analytic value |
| `multiple_plots_and_ac` | `.op`, `.ac` and `.tran` in one deck; complex AC data | three plots; H(100 Hz) matches 1/(1 + jf/fc) to 1e-6 |
| `psa_compat_mode` | `ngbehavior=psa`: PSpice `VALUE={IF(...)}` E-source with a `.param` | exact; log reports the compatibility mode |
| `bg_run_and_inprocess_reset` | `bg_run` path; two in-process decks in sequence | no stale vectors in the second run |
| `deck_file_path_input` | A deck passed as a file path | accepted |

A further manual check confirmed that `ngbehavior=ps` accepts a PSpice `E ... POLY(1)` source and a `.subckt` with a
brace-expression resistor value, and that the compatibility mode does not persist into the next in-process run.

## 5. Limitations

- PSpice compatibility (`ps`, `psa`) covers the common syntax (`VALUE`, `TABLE`, `POLY`, `IF`, brace expressions,
  `.param`, `.func`). Encrypted vendor models do not run in ngspice in any mode. Models that use PSpice-only devices or
  undocumented functions can still fail; each simulation states which mode its models need and whether they ran.
- The `.meas` parser reads lines of the form `name = value`. A measurement that fails prints no such line, so it is
  absent from `meas`; callers must treat a missing key as a failed measurement.
- `SimResult.ok` does not detect every numerical problem. A transient that ngspice completes with a reduced time step
  is reported as `ok`. Each simulation checks its own convergence (time-step control, `.options`) and states it.
- KiCad's ngspice build supports the OpenMP-free shared-library interface only through this `ctypes` binding; no
  standalone `ngspice.exe` or `ngspice_con.exe` is shipped or used.
