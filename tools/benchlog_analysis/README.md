# benchlog_analysis — bench-log analysis toolkit

Turns a raw `.BLG` bench log written by the Teensy's SD logger into a decoded
CSV plus a set of thesis-ready figures for the two control loops on the DC
balancer board:

* the **velocity loop** — setpoint `v_sp`, measurement `v_act` [m/s], control
  effort `I_cmd` (motor current command) [A];
* the **power-share loop** — setpoint `share_sp`, measurement `share_act`
  (unitless, fuel-cell fraction of total channel current), control effort
  `gFC` / `gBT` (the two droop-MDAC gain commands, unitless).

`I_fc` / `I_batt` are the fuel-cell and battery boost channel currents [A].

## Pipeline

```
logs/NAME.BLG                (drop the SD-card log here)
      |  ingest_log.py       decode
      v
logs/NAME/
      NAME.csv               decoded samples (regenerated every run)
      decode_report.txt      decoder's report lines (regenerated every run)
      analysis_config.json   filter taus (created once, NEVER overwritten)
      |  make_figures.py     render
      v
      tracking_subplots.png, error_subplots.png,
      effort_subplots.png, currents_and_share.png, share_controller.png,
      bus_and_share.png                            (overwritten every run)
      charge_regen_and_currents.png                       (v3+ logs only)
      drive_controller_conditioning.png                    (v5 logs only)
```

**Idempotency rule:** `analysis_config.json` is written exactly once — on the
first ingest of a run — and never rewritten afterwards. Hand-edit the taus and
re-run as often as you like; the CSV, the report and the PNGs are all derived
artefacts and are regenerated (silently overwritten) on every run, but your
config edits survive. Keys missing from an older config are filled from the
defaults *in memory only*.

## Interpreter

A dedicated venv at the repo root, `.venv_benchlog/`:

```powershell
uv venv .venv_benchlog
uv pip install --python .venv_benchlog/Scripts/python.exe numpy matplotlib pyinstaller
```

All commands below use `.venv_benchlog/Scripts/python.exe`, run from the repo
root.

## Commands

Decode one log into its run directory:

```powershell
.venv_benchlog/Scripts/python.exe tools/benchlog_analysis/ingest_log.py logs/TEST0001.BLG
```

Render all figures for an already-ingested run:

```powershell
.venv_benchlog/Scripts/python.exe tools/benchlog_analysis/make_figures.py logs/TEST0001
```

Or do both in one shot — pass the `.BLG` and it ingests first:

```powershell
.venv_benchlog/Scripts/python.exe tools/benchlog_analysis/make_figures.py logs/TEST0001.BLG
```

`make_figures.py` prints each saved PNG path. It is also importable:
`make_figures.make_all(run_dir, data=None, cfg=None) -> list[Path]` loads the
run directory's single `*.csv` and its config when they are not passed in,
renders every registered figure at dpi=150, and returns the saved paths.
A run directory with zero samples (header-only CSV, e.g. a fully truncated
capture) raises `ValueError`, the same clean-error path as a missing or
ambiguous CSV.

Generate a synthetic log for development (no hardware needed) with
`make_test_blg.py`; it writes a `.BLG` (e.g. `logs/TEST0001.BLG`) containing a
velocity trapezoid, power-share steps, plausible channel currents and a
deliberate velocity-invalid NaN window, which is what the figures are eyeballed
against. `--truncate` simulates a power-loss capture (no trailer), `--wrap`
starts the timestamps just below the 2^32 µs `micros()` rollover so the run
straddles the wrap (both the decoder and `common.load_csv`'s elapsed-time
reconstruction are wrap-safe). `--v3` writes the format-v3 header/record
layout instead of v1/v2 (see below).

**Format v3 (fw v5):** appends four source/node voltage channels — `V_fc`,
`V_batt`, `V_chg`, `V_rgn` — to the 52 B v1/v2 record (68 B total), inserted
after `I_cmd` in the CSV column order. `ingest_log.py` and `common.load_csv`
accept both layouts transparently (the CSV header line identifies which one).
`charge_regen_and_currents.png` reads two of the four new columns (`V_chg`,
`V_rgn`) and is skipped on pre-v3 logs; `V_fc` / `V_batt` are still unread by
any figure. See `tools/decode_benchlog.py` for the exact byte layout.

**Format v5 (fw v11):** appends two more fields — `u_unsat` (drive
controller pre-clamp output, PI-fallback builds: the PI pre-clamp command)
and `drive_x0` (Youla drive controller integrator state x[0], PI-fallback
builds: `pi_motor_accum`) — to the 68 B v3/v4 record (76 B total), inserted
right after `V_rgn` in the CSV column order. `flags` gains two more raw
pass-through bits: bit4 (0x10) = drive command came from the Youla drive
controller this tick (clear = PI fallback); bit5 (0x20) = the share loop is
the Youla share controller this tick (clear = PI fallback) — same
raw-passthrough treatment as bit0-bit3, no new columns from the bits
themselves. `common.load_csv` accepts v1/v2, v3/v4, and v5 CSVs
transparently. `--v5` on `make_test_blg.py` writes the format-v5
header/record layout for pipeline testing.

## `analysis_config.json`

```json
{
  "filters": {
    "share_act_tau_s": 0.020,
    "I_fc_tau_s": 0.010,
    "I_batt_tau_s": 0.010
  }
}
```

Each value is the time constant τ, **in seconds**, of a causal single-pole
low-pass (`common.lowpass`, per-sample dt taken from the timestamps, NaN
transparent — the filter holds state across a NaN and emits NaN there, so log
gaps stay gaps). Larger τ = smoother and more lag. These three signals —
`share_act`, `I_fc`, `I_batt` — are the *only* filtered signals; setpoints and
everything else are always plotted raw. Figure legends read the τ out of this
file, so the labels can never disagree with the filtering actually applied.
Set a τ to 0 to disable that filter.

## Figures

| File | Contents |
|------|----------|
| `tracking_subplots.png` | Both loops' tracking, one loop per subplot: velocity ref vs act on top, share ref vs act (raw + filtered) below, shared x. |
| `error_subplots.png` | Tracking error of both loops: `v_sp − v_act` on top, `share_sp − share_act` (raw + filtered) below, each with a zero reference line. |
| `effort_subplots.png` | Control effort: motor current command `I_cmd` [A] on top, droop MDAC gains `gFC` / `gBT` below. |
| `currents_and_share.png` | Channel currents `I_fc` / `I_batt` (raw + filtered) [A] on top, the resulting power share (ref, raw, filtered) below. |
| `share_controller.png` | Power-share loop detail: share tracking (ref, raw, filtered) on top; share error (left axis) against the commanded share ratio `r_cmd = gBT/(gFC+gBT)` (right axis) below. `r_cmd` is the controller output immediately before the droop-gain mapping, reconstructed exactly from the firmware's `g = K_DROOP/(RE_MAX·r)` relation with no calibration constants needed. |
| `bus_and_share.png` | Bus behaviour: `V_bus` with a dashed no-load nominal line (`V_BUS_NOMINAL` = 15.9 V, a constant in `figures.py`) on the left axis, total bus current `I_fc + I_batt` (raw + filtered) on the right axis; power-share tracking below. |
| `charge_regen_and_currents.png` (v3+ logs only) | Power-path nodes against the current they carry: the regen-node voltage `V_rgn` and the charger-input voltage `V_chg` (both raw) on top; the two boost channel currents `I_fc` / `I_batt` (raw + filtered) and their total `I_fc + I_batt` (raw + filtered) below. The filtered total is the elementwise sum of the two individually-filtered channels, each at its own τ — deliberately not a low-pass of the total at any single τ, and with unequal τ (or a NaN gap in only one channel) not equal to filtering the summed signal; the legend carries both τ values. Single-axis subplots, no banding. Skipped (no PNG, noted on stderr) for pre-v3 logs, which have no `V_chg`/`V_rgn` columns. |
| `drive_controller_conditioning.png` (v5 logs only) | Hanus-conditioning verification: `u_unsat` (drive controller pre-clamp output) against the ±12 A actuator rails on top, with intervals where `abs(u_unsat) >= 12 A` shaded as saturated; `drive_x0` (Youla drive controller integrator state) on the same time axis below, with the same saturation shading. Skipped (no PNG, noted on stderr) for pre-v5 logs, which have no `u_unsat`/`drive_x0` columns. |

Style is centralised in `figures.py`: a fixed role→colour map (velocity blue,
share orange, FC aqua, BT violet, commanded ratio green) that holds across
every figure, dashed setpoints drawn above their measured traces, filtered
overlays drawn in a darker shade of their hue on top of a faint raw trace,
light recessive grid behind the data, no markers (runs are ~40k points), and
NaN gaps left as gaps.

**Velocity-less runs** (R and PS profiles log no velocity chain, so `v_sp` /
`v_act` are entirely blank): the velocity panels are omitted altogether —
`tracking_subplots` / `error_subplots` collapse to their share subplot at full
figure size. `share_controller` and the other share/current figures are
unaffected.

## Adding a figure

1. Write a builder in `figures.py`:

   ```python
   def my_figure(data, cfg):
       """data = common.load_csv() dict, cfg = analysis_config dict."""
       ...
       return fig   # never save, never close — the driver owns file I/O
   ```

   Use the `COLORS` map and the `_style_axes` / `_legend` / `_suptitle`
   helpers so it matches the rest.

2. Append one entry to the registry at the bottom of `figures.py`:

   ```python
   FIGURES = [
       ...,
       ("my_figure", my_figure),
   ]
   ```

The name becomes the output filename (`<name>.png` in the run directory), and
`make_figures.py` picks it up with no further changes.

## GUI and standalone exe

`analyze_gui.py` is a tkinter file-picker front-end over exactly this pipeline
— pick one or **several** `.BLG` files (the dialog is multi-select, and opens
in the repo's `logs/` folder, found by walking up from the exe's location)
and they are processed sequentially through the same `ingest_log.ingest` /
`make_figures.make_all` entry points, so the GUI and the CLI can never drift
apart. One log failing does not stop the rest; a single combined summary is
shown at the end, and Explorer opens on the run dir (one log) or the common
parent folder (several). `analyze_gui.py FILE.BLG --no-popup` runs the
same thing headlessly (note: the frozen `--noconsole` exe has no stdout —
redirect it to a file to capture the summary). Unexpected crashes in the exe
are appended to `BenchLogAnalyzer_error.log` next to the exe.

`build_exe.ps1` packages the GUI into a standalone Windows executable with
PyInstaller (onefile), producing `tools/benchlog_analysis/dist/BenchLogAnalyzer.exe`:

```powershell
powershell -File tools\benchlog_analysis\build_exe.ps1
```

The exe bundles Python, numpy and matplotlib, so it runs on a bench machine
with no Python install. **Because it bundles a frozen copy of the package,
any edit to `figures.py`, `common.py` or `make_figures.py` — adding, removing
or renaming a figure included — requires re-running `build_exe.ps1`;** until
you do, the exe keeps rendering the figure registry it was built against,
so the PNG set in a run directory depends on which front-end ingested it. Note that `figures.py` selects the headless `Agg`
matplotlib backend at import time, which is what lets the same code render
figures inside the windowed exe.
