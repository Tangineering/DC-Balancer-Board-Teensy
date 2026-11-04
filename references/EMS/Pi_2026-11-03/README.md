# Pi software snapshot, 2026-11-03

The Raspberry Pi ROS 2 software as the PhD student committed it on
`phd/siddhesh-2026-11-03` (commit `64fb553`, student folder `scale_car/Code/Pi/`).
Files are byte-for-byte copies. This folder sits next to the earlier snapshot
`../Pi_2026-09-01/` and follows the same layout. The student versions nodes by
date-suffixed filenames, not by git, so the filenames are kept as they were.

**Telemetry protocol: still v4, 58 bytes.** `teensy_bridge_node_2026-10-31A.py`
asserts `T2P_SIZE == 58`, and fw v31 through v36 do not change the packet. No
lockstep change is pending.

## Probable latest file per node

This table goes by filename, size and the student's README. Several files' `Rev:` header
lines were not bumped (for example `sdp_ems_node_newbuild.py` and `_2026-10-28B.py` both
say `Rev: 2026-10-26A`), so check with the student which file is deployed on the Pi.

| Node | Latest | Notes |
|---|---|---|
| Bridge | `EMS/ROS2/teensy_bridge_node_2026-10-31A.py` | EKF state-of-charge estimator replaces the complementary filter; publishes `/vehicle_state` (18 elements) and `/soc_diagnostics` |
| SDP EMS | `EMS/ROS2/sdp_ems_node_newbuild.py` (largest; the dated files end at `_2026-10-28B`) | Commands a power-share ratio held inside (0.15, 0.85) exclusive, with a `1.10 / I_total_filtered` ceiling |
| Simple EMS | `EMS/ROS2/simple_ems_node_2026-10-20A.py` | |
| Sweep EMS | `EMS/ROS2/sweep_ems_node.py` (`_V1`, `_V2` are earlier) | Used for the `rosbag_sweep*` runs |
| Drive cycle | `EMS/ROS2/drive_cycle_node_newbuild.py` | Plays the speed traces in `references/drive_cycles/` |
| Launcher | `fchev_run.sh` (Rev 2026-10-19A); `fchev_run_2026-10-26A.sh` adds the cost-to-go path override and the regen on/off prompt | tmux launcher. Deployed on the Pi at `~/fchev/fchev_run.sh` |

The cost-to-go tables `EMS/ROS2/CostToGo_J_*_2026-10-2xX.mat` match the
dated SDP nodes. The scripts that generate them are in `tools/rosbag_analysis/`
(`make_costtogo*.py`, `make_tpm_newbuild.py`).

## Not carried over from the student folder

- `Code/Pi.zip`: an archive of the 2026-08-21 Pi tree, the same content as
  `../Pi_2026-09-01/`.
- `EMS/files.zip` (22 bytes, an empty archive) and `EMS/sdp_ems_run.log`
  (0 bytes).
- `EMS/ROS2/FCHEV Bench Bring-Up — 20 October 2026.pptx`, moved to
  `docs/slides/FCHEV_Bench_Bring-Up_2026-10-20.pptx`.

Ten files here are byte-identical to `../Pi_2026-09-01/` (the 2026-03-16A / 04-06A / 08-17A simple
nodes and everything under `EMS/SDP/` and `EMS/Simple/`). The student's `teensy_bridge_node_2026-08-17Aold2.py`
is the file `../Pi_2026-09-01/` has as `teensy_bridge_node_2026-08-17A.py`. The
student's current `_2026-08-17A.py` is a later edit under the same name.
