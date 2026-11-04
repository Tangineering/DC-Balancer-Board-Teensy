# rosbag_analysis: Pi rosbag analysis scripts

The PhD student's scripts for the ROS 2 bags the Pi records (`/vehicle_state`,
`/ems_command`, `/ems_diagnostics`, `/drive_cycle`, ...). The bags are in
`logs/rosbags/` (index: `logs/rosbags/README.md`). They come from
`phd/siddhesh-2026-11-03` (`64fb553`, student folder `scale_car/Analysis/`).
Apart from `scout_bags.py` (added 2026-11-04), the only edits are the default and example paths, which were changed from
`../Logs/...` to `../../logs/rosbags/...` to match where the bags now live.

The `.BLG` SD-card bench logs the Teensy writes itself are handled by
`tools/benchlog_analysis/` and `tools/decode_benchlog.py`, not by these scripts.

Run from this directory:

    python3 <script> ../../logs/rosbags/<bag directory>

Dependencies: `mcap_ros2` (the `mcap-ros2-support` package) for the scripts
that read the `.mcap` directly, plus `numpy`, `scipy` and `matplotlib`. Some
checks read `<bag>/csv/*.csv`, which `fchev_plot.py <bag> --csv` writes.

| Script | Reads | Purpose |
|---|---|---|
| `scout_bags.py` | mcap | Repo addition (not the student's): one-row-per-bag inventory and quick stats, `--npz` caches arrays for analysis agents; used by the `rosbag-agent-analysis` skill |
| `fchev_plot.py` | mcap | Four-panel overview (speed, share, currents, SoC/faults); `--csv` dumps every topic |
| `plot_power.py` | mcap | P_fc / P_batt / P_demand |
| `plot_ab.py` | csv | A/B overlay of clip vs no-clip sweep runs, written to `../../logs/rosbags/plots` |
| `check_sdp.py` | mcap | SoC band, mode occupancy, share tracking by current band, faults |
| `check_regen.py` | mcap | `switch_state` decode, regen arming, charge current |
| `check_err_vs_noise.py`, `check_noise.py`, `check_spectrum.py`, `check_wheel.py` | csv | Is the share-tracking error real or feedback noise; current-noise spectrum; is the ~4 Hz current oscillation locked to wheel rotation |
| `fit_fc.py` | mcap | Fuel-cell polarization-curve fit and the fuel map derived from it |
| `fit_pdemand.py` | mcap | Road-load (P_demand) fit |
| `make_tpm_newbuild.py`, `check_tpm.py` | mcap / .mat | Demand transition matrix built from bags (`TPM_newbuild.mat`); does the TPM carry real memory |
| `make_costtogo.py`, `make_costtogo_newbuild.py` | .mat | SDP cost-to-go by value iteration; `_newbuild` is an average-cost SDP with no SoC target (`CostToGo_newbuild.mat`; the Pi's dated tables are in `references/EMS/Pi_2026-11-03/EMS/ROS2/`) |

These scripts are separate from the repo's own EMS tooling (`tools/sdp_ems_solver.py`,
`tools/h2_map.py`, `references/EMS/`), and their models (road load, fuel map,
TPM grid) have not been reconciled with it.
