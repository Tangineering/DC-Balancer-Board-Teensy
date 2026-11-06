# Pi rosbags (scale-car bench runs, 2026-09 through 2026-11)

ROS 2 bags (`.mcap` plus `metadata.yaml`) that the Raspberry Pi recorded during
the PhD student's bench runs. They come from `phd/siddhesh-2026-11-03`
(`64fb553`, student folder `scale_car/Logs/`) and are copied byte-for-byte.
They are a different kind of data from the `.BLG` SD-card logs in `logs/`
(`ML####`, `YP####`, ...), which the Teensy writes itself. To analyze these
bags use `tools/rosbag_analysis/` (README there), for example:

    cd tools/rosbag_analysis && python3 fchev_plot.py ../../logs/rosbags/rosbag_sdp_2026-10-30_01-49-38

`/vehicle_state` is the bridge's 18-element v4 array. Its index map is the
signal table `references/FCHEV_Signal_Table_2026-08-17A.xlsx` (bridge
`references/EMS/Pi_2026-11-03/EMS/ROS2/teensy_bridge_node_2026-10-31A.py`). A
`csv/` folder, where present, is the per-topic dump that
`fchev_plot.py --csv` writes.

## Runs

Bag names use the Pi's local time. The run type is the EMS named in the bag
(`sweep` / `sweep-clip` / `sweep-noclip` = `sweep_ems_node`, `simple`,
`sdp`). The student's README defines clip / no-clip as the dynamic share
ceiling `1.10 / I_total_filtered` switched on or off.

| Bag | EMS / run type | Duration (s) | /vehicle_state msgs | .mcap MB | csv/ |
|---|---|---:|---:|---:|---|
| `rosbag_2026-09-07_22-06-29` | (unlabelled) | 85 | 4260 | 1.5 |  |
| `rosbag_2026-09-10_22-10-26` | (unlabelled) | 139 | 6948 | 2.2 | yes |
| `rosbag_sdp_2026-10-26_23-57-14` | sdp | 246 | 12293 | 4.3 |  |
| `rosbag_sdp_2026-10-27_00-52-58` | sdp | 69 | 3446 | 1.5 |  |
| `rosbag_sdp_2026-10-28_20-46-53` | sdp | 235 | 11737 | 4.1 |  |
| `rosbag_sdp_2026-10-28_22-18-10` | sdp | 111 | 5562 | 2.0 |  |
| `rosbag_sdp_2026-10-29_19-51-48` | sdp | 235 | 11775 | 4.2 |  |
| `rosbag_sdp_2026-10-30_01-49-38` | sdp | 188 | 9380 | 3.3 |  |
| `rosbag_sdp_2026-11-05_20-09-52` | sdp (fw v37 rev 2, vehicle build; first bag with `/h2_usage`) | 167 | 8356 | 4.9 |  |
| `rosbag_simple_2026-10-20_00-38-02` | simple | 225 | 11239 | 4.4 | yes |
| `rosbag_sweep-clip_2026-10-22_23-18-00` | sweep-clip | 83 | 4170 | 1.4 | yes |
| `rosbag_sweep-noclip_2026-10-22_23-25-13` | sweep-noclip | 83 | 4165 | 1.3 | yes |
| `rosbag_sweep-noclip_2026-10-23_17-27-44` | sweep-noclip | 79 | 3938 | 1.3 | yes |
| `rosbag_sweep-noclip_2026-10-25_21-09-10` | sweep-noclip | 114 | 5614 | 2.0 | yes |
| `rosbag_sweep-noclip_2026-10-27_01-09-42` | sweep-noclip | 79 | 3944 | 1.4 |  |
| `rosbag_sweep-noclip_2026-10-27_02-52-00` | sweep-noclip | 99 | 4931 | 1.8 |  |
| `rosbag_sweep-noclip_2026-10-30_00-56-01` | sweep-noclip | 88 | 4407 | 1.6 |  |
| `rosbag_sweep-noclip_2026-10-30_01-30-16` | sweep-noclip | 202 | 10081 | 3.6 |  |
| `rosbag_sweep_2026-10-20_04-00-39` | sweep | 120 | 6018 | 1.9 | yes |
| `rosbag_sweep_2026-10-20_06-40-47` | sweep | 88 | 4376 | 1.4 | yes |
| `rosbag_sweep_2026-10-20_07-47-28` | sweep | 128 | 6420 | 2.1 | yes |
| `rosbag_sweep_2026-10-20_08-41-34` | sweep | 98 | 4878 | 1.6 | yes |
| `rosbag_sweep_2026-10-20_09-08-49` | sweep | 110 | 5509 | 2.0 | yes |

Topics seen across bags: `/comms_status`, `/drive_cycle`, `/drive_cycle_status`, `/ems_command`, `/ems_diagnostics`, `/vehicle_state`

## Which firmware ran each bag: NOT RECORDED

Neither the v4 telemetry nor the bags carry `FW_VERSION`. Only the dated
references in the firmware itself bound it (git history of
`teensy_controller/teensy_controller.ino`, fw v31-v36):

- **2026-10-27, SDP EMS: ERR_UV_BUS** (source-less bus while `charge_goal` was up
  with no braking current). This led to fw v31 rev b and rev c, so the
  10-27 SDP bags ran fw v31 rev a or earlier.
- **2026-10-28: the student's "UV_FC + UV_BUS within seconds of the first FC charge window"
  is not in any bag** (review 2026-11-04, `docs/reviews/fw36_regen_2026-11-04/`). The two 10-28
  bags latched OC_FC and UV_FC; every FC_CHARGE sample in all 22 bags is the State-99 phase-0
  drain (`0x34`) after a latch, and charge_goal > 0.05 opened no window - consistent with
  `FC_CHARGE_ALLOWED 0`. The only UV_FC + UV_BUS latch is 10-27 00:52 (in its `/rosout`).
- **`rosbag_sweep-noclip_2026-10-30_01-30-16`**: cited by fw v36 as the evidence
  that regen never arms with `charge_goal` 0 (charge_goal 0/4033 samples,
  REGEN_ENABLE high 0/10081 across six wheel-locking decelerations). It ran
  fw <= v35.
- fw v35 was the flashed build as of 2026-11-03. fw v36 has not run on the board.
- The 2026-09-07 / 09-10 bags are from around the time fw v30 was written (2026-09-16 ledger date), so they
  ran an earlier build. Unverified.

- **`rosbag_sdp_2026-11-05_20-09-52`**: fw v37 rev 2 (`da0746c`), vehicle build. The student's
  `Teensy_v37.ino` (`6b1ca57` on `phd/siddhesh-2026-11-03`) differs from `da0746c` only in
  `BENCH_TEST 0` and `USE_ETHERNET 1`. Bridge 2026-11-03A (`references/EMS/Pi_2026-11-05/`).

Record the firmware version with every future bag (for example in the bag name
or a sidecar note) so the next round does not have to infer it.

## Other files

- `plots/`: the student's PNG figures (SDP runs 1-6, sweep and FC/BAT sweeps,
  regen decel sweep and v2, clip/no-clip A/B). Most are named after the bag they
  show. `FCHEV_SDP_run*` and `FCHEV_Test_*` do not name their bag.
- `fuel_cell_v_plots/mslg0001.mat`, `mslg0002.mat`: fuel-cell voltage captures
  (MATLAB `.mat`). Their source and capture setup are undocumented.

## Open items from the student's README (2026-11-03)

- Regenerative braking still returns no charge current. Cause under
  investigation. fw v36 fixes one cause (regen was gated on `charge_goal`).
- The fuel cell was not delivering power as of 2026-11-03. Undiagnosed.
- SoC: `pack_r_int_ohm` 0.050 is a guess and the OCV curve is a generic 2S NMC
  shape, so absolute SoC from the EKF should not be trusted yet.
