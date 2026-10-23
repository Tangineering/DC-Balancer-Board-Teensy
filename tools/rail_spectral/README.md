# rail_spectral — voltage-rail spectra vs flywheel speed

Asks whether the board's voltage signals (`V_bus`, `V_fc`, `V_batt`, `V_chg`,
`V_rgn`) carry content that tracks the dyno flywheel's rotation, using every
SD bench log in `logs/`.

```
python tools/rail_spectral/rail_spectral.py            # all of logs/, ~2 min
python tools/rail_spectral/test_rail_spectral.py       # self-test, ~10 s
```

Output goes to `logs/rail_spectral/` (git-ignored): `report.txt` and three
figures. Needs numpy and scipy; the figures also need matplotlib.

| File | Role |
|---|---|
| `blg_arrays.py` | Vectorised `.BLG` reader. Same record constants and end-of-data rules as `tools/decode_benchlog.py`, checked against it by the self-test. |
| `rail_spectral.py` | Windowing, statistics, tone tests, figures. The method is in its module docstring. |
| `test_rail_spectral.py` | Loader vs decoder on synthetic v1/v3/v6 logs, plus recovery of an injected order-locked tone. |

## Method in brief

- Non-HIL runs on fw v8 or later only. Earlier firmware had the encoder on
  the wrong pin.
- Each run is resampled to a uniform grid at its median interval (≈885 Hz,
  so the usable band ends near 440 Hz).
- Runs are cut into 2 s Hann windows at a 0.5 s hop. Windows with a fault
  flag are dropped.
- Rotation rate comes from `encoder_pos` (BLG v6+) or from `|v_act|`.
- Every spectrum is also re-plotted against **order** (frequency ÷ flywheel
  rev rate), where tones tied to a shaft line up. Each tone test runs
  against a null with speeds shuffled across windows.

Drivetrain orders come from `controller_design_MIMO/mimo_system_model.md`:

| Shaft | Order (× flywheel rev rate) | Derivation |
|---|---|---|
| Tire | 2.309 | r_fly / r_t |
| Intermediate | 6.56 | 15.84 ÷ (70/29) |
| Motor | 15.84 | 2.309 × 6.86 |

The encoder disc has 120 slots before fw v18 and 90 from fw v18 on; the
slot count is selected per run from the header's firmware version.

## Findings (2026-10-23, 90 runs, 1,881 steady windows)

**Broadband ripple tracks load current, not speed.** Speed and source current
are collinear on the rig (ρ = 0.85). With current held fixed, speed adds
nothing.

**Tones locked to shaft orders.** The rails carry tones at the drivetrain's
shaft orders, led by **2× the motor shaft rate** (order 31.7):

- on V_batt it is 10× the surrounding floor, in 68% of windows against 24%
  for the shuffled null;
- it reaches ≈14 mV rms on V_batt and ≈34 mV on V_fc near 3 m/s.

The tone is present in the measured `I_batt` / `I_fc` but absent from
`I_cmd`. The motor/ESC draws the pulsating current; the drive controller
does not inject it.

**The data recovers the drivetrain.** The peak positions reproduce the
6.86:1 reduction and the 70T/29T stage. They put the effective tire radius
at ≈0.0333 m, against the model's 0.033 m.

**Caveat:** above 2 m/s, run ML0135 (fw v9) supplies 158 of the 433 steady
windows.
