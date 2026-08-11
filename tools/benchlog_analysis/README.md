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
      tracking_overlay.png, tracking_subplots.png, error_subplots.png,
      effort_subplots.png, currents_and_share.png, share_controller.png,
      bus_and_share.png                            (overwritten every run)
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
reconstruction are wrap-safe).

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
| `tracking_overlay.png` | Both loops on one dual-axis (twinx) plot: velocity ref+act on the left axis in the upper band, share ref+act+filtered on the right axis in the lower band, with a clear gap between the bands and the axis labels/ticks coloured to their family. |
| `tracking_subplots.png` | The same tracking data with no scale tricks: velocity ref vs act on top, share ref vs act (raw + filtered) below, shared x. |
| `error_subplots.png` | Tracking error of both loops: `v_sp − v_act` on top, `share_sp − share_act` (raw + filtered) below, each with a zero reference line. |
| `effort_subplots.png` | Control effort: motor current command `I_cmd` [A] on top, droop MDAC gains `gFC` / `gBT` below. |
| `currents_and_share.png` | Channel currents `I_fc` / `I_batt` (raw + filtered) [A] on top, the resulting power share (ref, raw, filtered) below. |
| `share_controller.png` | Power-share loop detail: share tracking (ref, raw, filtered) on top; share error (left axis) against the commanded share ratio `r_cmd = gBT/(gFC+gBT)` (right axis) below. `r_cmd` is the controller output immediately before the droop-gain mapping, reconstructed exactly from the firmware's `g = K_DROOP/(RE_MAX·r)` relation with no calibration constants needed. |
| `bus_and_share.png` | Bus behaviour: `V_bus` with a dashed no-load nominal line (`V_BUS_NOMINAL` = 15.9 V, a constant in `figures.py`) on the left axis, total bus current `I_fc + I_batt` (raw + filtered) on the right axis; power-share tracking below. |

Style is centralised in `figures.py`: a fixed role→colour map (velocity blue,
share orange, FC aqua, BT violet, commanded ratio green) that holds across
every figure, dashed setpoints drawn above their measured traces, filtered
overlays drawn in a darker shade of their hue on top of a faint raw trace,
light recessive grid behind the data, no markers (runs are ~40k points), and
NaN gaps left as gaps.

**Velocity-less runs** (R and PS profiles log no velocity chain, so `v_sp` /
`v_act` are entirely blank): the velocity panels are omitted altogether —
`tracking_overlay` becomes a plain single-axis share plot, and
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
with no Python install. Note that `figures.py` selects the headless `Agg`
matplotlib backend at import time, which is what lets the same code render
figures inside the windowed exe.
