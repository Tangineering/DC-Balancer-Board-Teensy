# Full-scale governor penalty sub-project

Python reproduction of the PhD student's MATLAB study of the power-share
governor's hydrogen penalty on the full-size vehicle, and the ablation that
explains why the full-scale study reports a 3 to 15 % penalty while the bench
HIL campaigns report none.

Sources: `references/EMS/SDP_EnergyManagement_Governor3.m`,
`references/EMS/sweep_governor_scale.m`, `references/EMS/matlab_governor_results.jpg`.
Design note: `docs/modeling/fullscale_governor_penalty_20260908.md`.

## Files

| File | Role |
|---|---|
| `sdp_governor3.py` | Port of `SDP_EnergyManagement_Governor3.m`: SDP value iteration with the stack on/off flag and start cost, convex hydrogen map, and the forward simulation with the student's scaled-up governor (setpoint latch, min-load gate, minority clip, conduction-aware slew, PI share-controller stub). Validated against MATLAB to four decimals on every table column. |
| `sweep_governor_scale.py` | Port of `sweep_governor_scale.m`: the S_I sweep at alpha 200 and 500, printing the student's table. |
| `udds_demand.py` | Builds the stand-in UDDS demand used before the student's file arrived (see below). |
| `attribution.py` | Ablation run: default / no-slew / linear-map / no-start-cost. |
| `compare_with_matlab.py` | Row-by-row check of a MATLAB sweep JSON against a Python sweep JSON. |
| `matlab/run_sweep_synth.m`, `matlab/run_sweep_student.m` | The student's sweep with the demand loaded from a plain `.mat` / from his Simulink file with his loader (env `PDEM_FILE`, `OUT_JSON`), used for the ground-truth runs. |
| `python_sweep_student_20260908.json`, `attribution_student_20260908.log` | The sweep and ablation on the student's demand. |
| `matlab/matlab_sweep_synth_20260908.json`, `python_sweep_synth_20260908.json` | The first MATLAB-vs-Python validation pair, on the stand-in demand. |

Interpreter: miniforge (`C:/Users/ricky/miniforge3/python.exe`), numpy + scipy.

## Inputs

The student's `references/EMS/simulink_pdem_output_UDDS.mat` (supplied 2026-09-08) is the demand
the sweep uses; pass it straight to `--pdem`. The loader decodes the opaque Simulink `out.simout`
object through `tools/tpm_generator.py` and resamples it exactly as the MATLAB does. A decoded
1 Hz copy with provenance is under `references/EMS/generated/udds_pdem_student_1hz.*`.

On that file the port reproduces every number on his slide (`matlab_governor_results.jpg`).
The slide's alpha 200, S_I = 127.8 penalty reads +8.82 %; 69.67 g against 63.49 g is +9.73 %,
which is what the port (and his own grams) give.

`udds_demand.py` builds the stand-in that was used before the file arrived (road-load fit to
the shipped stochastic cycles, R^2 0.98; `references/EMS/generated/udds_pdem_synth_20260908.*`).
It is kept for provenance of the first MATLAB-vs-Python validation run and is not needed now.

## Running

```bash
C:/Users/ricky/miniforge3/python.exe tools/fullscale_governor/sweep_governor_scale.py --pdem references/EMS/simulink_pdem_output_UDDS.mat --json out.json
```

```bash
C:/Users/ricky/miniforge3/python.exe tools/fullscale_governor/attribution.py --pdem references/EMS/generated/udds_pdem_student_1hz.npy
```

Ground truth (about 6 minutes; MATLAB R2024b):

```bash
PDEM_FILE="$PWD/references/EMS/simulink_pdem_output_UDDS.mat" OUT_JSON="$PWD/matlab_out.json" "/c/Program Files/MATLAB/R2024b/bin/matlab.exe" -batch "run('$PWD/tools/fullscale_governor/matlab/run_sweep_student.m')"
```


## Port discipline

`sdp_governor3.py` is the student's transcription of the fw v25 governor spec,
not `tools/governor_model.py` (the firmware port). The two differ in the
share-controller stub, the latch release rules and the absence of the fw v26
ceilings and fw v27 battery-only start. Do not align this file with the
firmware port without recording it here; the difference is part of what is
being measured. The one addition over the MATLAB is the `sp_preclip`
experiment knob (default `None` = MATLAB behaviour).
