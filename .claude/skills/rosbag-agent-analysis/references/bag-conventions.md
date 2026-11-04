# Pi rosbag data conventions (single source of truth for agent briefs)

Read this before analysing any bag in `logs/rosbags/`. The bridge source
(`references/EMS/Pi_2026-11-03/EMS/ROS2/teensy_bridge_node_2026-10-31A.py`) and the
firmware's telemetry packer are the authority over this file if they disagree.

## What a bag is

- ROS 2 Jazzy, `ros2 bag record -a`, one `.mcap` plus `metadata.yaml` per folder. Bag
  names are the Pi's local time and the EMS name (`sweep`, `sweep-clip`, `sweep-noclip`,
  `simple`, `sdp`, or none).
- Reader: `mcap_ros2.reader.read_ros2_messages` (`pip install mcap mcap-ros2-support`).
  Fastest path: `tools/rosbag_analysis/scout_bags.py BAG --npz --cache <dir>` once, then
  `np.load("<dir>/<bag>.npz")` -> `vs_t`, `vs` (N x 18), `ec_t`, `ec` (M x 5), `VS`, `EC`.
- Every topic is `std_msgs/Float64MultiArray`. Times are Pi **receive** times
  (`log_time`), seconds from the first message in the bag. The Teensy timestamp and
  packet counter are parsed by the bridge but NOT republished.

## Topics

| Topic | Width | Rate | Content |
|---|---|---|---|
| `/vehicle_state` | 18 | 50 Hz | the bridge's view of the latest v4 telemetry packet (index map below) |
| `/ems_command` | 5 | EMS rate | `v_setpoint, power_share_cmd, charge_goal, mode, droop_enable` - what the EMS ASKED; the bridge forwards it as the 22 B command |
| `/ems_diagnostics` | 7 or 9 | EMS rate | per-EMS internals; the layout differs by EMS node and version - read the node that wrote the bag |
| `/comms_status` | 4 | ~1 Hz | bridge link counters |
| `/drive_cycle`, `/drive_cycle_status` | 4 | cycle rate | drive-cycle node output |
| `/soc_diagnostics` | 6 | 50 Hz | only from bridge 2026-10-31A (EKF internals); absent in older bags |

`/vehicle_state` index map: 0 `v_actual` m/s, 1 `V_batt`, 2 `I_batt` (bus-side BT boost
current, unipolar), 3 `I_charge` (Ag105 reg 0x06 x 0.011 A, I2C-polled), 4 `V_fc`, 5 `I_fc`
(bus-side FC boost current), 6 `V_bus`, 7 `V_rgn`, 8 `V_chg`, 9 `power_share_actual`
(computed BY THE BRIDGE as |I_fc|/(|I_fc|+|I_batt|), held at its last value under the
bridge's minimum-current gate - not a firmware quantity), 10 `droop_FC`, 11 `droop_BT`,
12 `charger_status` (raw Ag105 Table 6 byte), 13 `switch_state`, 14 `fault_flags`, 15
`error_code`, 16 `error_source_state`, 17 `SOC` (Pi-side estimate: EKF from bridge
2026-10-31A, complementary filter before - absolute SoC is not trustworthy, R0/OCV
uncalibrated).

## Bit fields (teensy_controller.ino)

- `switch_state`: 0x01 FC_BUS, 0x02 BT_BUS, 0x04 MOT_PWR, 0x08 REGEN, 0x10 FC_CHARGE,
  0x20 BT_SEQ.
- `fault_flags`: 0x0001 OC_FC, 0x0002 UV_BATT, 0x0004 OV_BUS, 0x0008 SWITCH_CONFLICT,
  0x0010 PI_TIMEOUT, 0x0020 OV_BATT, 0x0040 UV_FC, 0x0080 OC_BT, 0x0100 UV_BUS, 0x0200
  OV_RGN, 0x0400 OV_CHG, 0x0800 I2C_CHARGER, 0x1000 CHARGER_STAT, 0x2000 INIT_FAIL,
  0x4000 MOT_HOTPLUG, 0x8000 ERROR (latched, State 99). Several bits are TRANSIENT
  indications (UV_FC on an H-20 purge dip sets 0x0040 without latching) - a bit seen
  once is not a fault; `error_code` != 0 is.
- `error_code`: 1 OC_FC, 2 UV_BATT, 3 OV_BUS, 4 SWITCH_CONFLICT, 5 PI_TIMEOUT, 6 OV_BATT,
  7 UV_FC, 8 OC_BT, 9 UV_BUS, 10 OV_RGN, 11 OV_CHG, 13 CHARGER_STAT, 14 INIT_FAIL, 15
  MOT_HOTPLUG. `error_source_state` = the main state at the fault (0 Init, 1 Idle, 2 Run,
  3 Finish, 98 Test, 99 Error).
- `charger_status` = 0 has TWO meanings: the firmware zeroes it whenever the charger is
  unpowered or not yet settled/ACKing, AND 0x00 is a real Table-6 status. Treat a bag
  that reads 0 throughout as "no charger data ever", never as a charger state.

## Sampling traps (the anti-artifact block)

1. **50 Hz snapshots of a 1 kHz controller.** `switch_state`, currents and voltages are
   the values in whichever telemetry packet the bridge last parsed - one sample every
   20 ms. A switch that toggles for less than 20 ms can be missed entirely or appear as a
   single tick. Count REGEN episodes as lower bounds; never infer a duration below
   ~40 ms. The BLG SD log (1 kHz) is the instrument for sub-20 ms timing.
2. **Commands are what the EMS asked, not what the firmware did.** `power_share_cmd` is
   pre-governor; the firmware's selector, clamp and governor can deliver something else.
   `charge_goal` > 0.05 is the firmware's FC-charge intent threshold. Every committed
   v31-v36 build has `FC_CHARGE_ALLOWED 0`, so FC_CHARGE should read 0 regardless.
3. **Firmware version is NOT in the bag.** Bound it from dates (logs/rosbags/README.md
   "Which firmware ran each bag") and state the bound in every finding. Do not compare
   behaviour across bags as if one build ran them all.
4. **Bridge version is not in the bag either.** `/soc_diagnostics` present means bridge
   2026-10-31A or later. SoC semantics changed between bridge versions.
5. **Receive-time jitter.** The Pi stamps on receipt; gaps > 25 ms are Pi/UDP stalls
   (one 316 ms gap seen on 2026-10-27_00-52). Check `max(diff(t))` before reading a
   rate or a dwell from the timeline.
6. **`v_actual` is the firmware's encoder estimate** (flywheel surface speed); a
   wheel-locked deceleration reads 0 well before the wheel truly stops.
7. **No motor current in telemetry.** The VESC commanded current (`current`, whose sign
   arms regen: `regenActive = current < -0.1 A`) is not in the packet. Infer braking
   only from `v_setpoint` falling and `v_actual` decelerating; say it is inferred.
8. **Unipolar current sensors.** INA253s see only each boost's forward current. Regen and
   charge current never appear on `I_batt`/`I_fc`; the only charge-current observable is
   `I_charge` (I2C, only while the Ag105 is powered, settled and configured).
9. **Gate ratios.** `power_share_actual` and any I_fc/I_tot ratio are meaningless under
   ~0.3 A total.
10. **Statistics hygiene.** Report counts with their denominators (ticks, seconds,
    episodes), medians with ranges, and name the time window.

## Provenance / comparability

- Firmware: dates only (see trap 3). Pi node: the dated-file guess in
  `references/EMS/Pi_2026-11-03/README.md`. Plots in `logs/rosbags/plots/` are the
  student's; re-derive numbers from the bag, do not read them off a PNG.
- The student's own scripts (`tools/rosbag_analysis/`) are references, not
  authorities; `check_regen.py`'s docstring logic is a hypothesis to test.
