> **Imported 2026-11-04.** This is the PhD student's `scale_car/README.md` from
> `phd/siddhesh-2026-11-03` (`64fb553`), kept verbatim below this note. The
> student's `scale_car/` folder was not imported as one tree. Its contents were
> split into the repo's own layout:
>
> | Student path | Now in this repo |
> |---|---|
> | `Code/Teensy/teensy_controller*`, `Teensy_v31b/c`, `v35`, `v36` | `teensy_controller/teensy_controller.ino`, one commit per version (`git log -- teensy_controller/teensy_controller.ino`); ledger rows 31-36 in `docs/firmware-versions.md` |
> | `Code/Teensy/Scale_Car_Teensy*`, `sketch_aug25a` | `firmware_archive/` |
> | `Code/Pi/` | `references/EMS/Pi_2026-11-03/` (the bring-up deck is in `docs/slides/`) |
> | `Analysis/` | `tools/rosbag_analysis/` |
> | `Logs/` | `logs/rosbags/` (index and firmware-version notes in its README) |
> | `Documentation/Drive Cycles/` | `references/drive_cycles/` (see PROVENANCE.md) |
> | `Documentation/Signal Table/` | `references/FCHEV_Signal_Table_*.xlsx` |
> | `Documentation/Operation Guide/`, `Checklists/` | `docs/operations/` |
>
> The "Layout" section below describes the student's folder, not this repo.
> Paths such as `Code/Teensy/` and `Logs/` refer to the table above.

# Scale Car — FCHEV Test Platform

Scaled fuel-cell hybrid electric vehicle testbed, UC Davis Future Mobility Lab.
A Teensy 4.1 on a DC balancer board handles the power path and low-level control;
a Raspberry Pi runs the energy management strategy over ROS 2 and logs telemetry.

## Hardware

| Part | Notes |
|---|---|
| Fuel cell | Horizon H-20, 20 W PEM. ~14 cells (inferred from the datasheet fuel map, not confirmed) |
| Battery | Buddy RC 2S 18650, 5 Ah / 36 Wh, nominal 7.2 V |
| Charger | Silvertel Ag105 MPPT, I2C |
| Power path | RT1987 ideal-diode switches: FC→bus, BT→bus, bus→motor, regen→charger, FC→charger |
| Motor | VESC-driven, flywheel dyno |
| Bus | nominal 16 V |

Road load fitted on the dyno (W, v in m/s, a in m/s²):

    P = 4.0297·v + 0.4658·v² + max(1.1695 · 3.5 · v·a, 0)

Effective inertia is 4.09 kg. Coast-down from drag alone is roughly
0.7–1.2 m/s², which sets the deceleration a brake event has to beat before
any energy can come back.

## Layout

    Code/Teensy/          firmware, one folder per version
    Code/                 ROS 2 nodes for the Pi
    Analysis/             bag analysis and table generation
    Documentation/        drive cycles, notes
    Logs/                 rosbags and plots

## Firmware

v30 is the baseline in the DC-Balancer-Board-Teensy repo. Everything here
descends from it.

| Version | State | Change |
|---|---|---|
| v31–v34 | superseded | FC charge path work, undervoltage debugging |
| v35 | **flashed** | FC charge-window safeties (entry/max/cooldown), FC UV lockout, `FC_CHARGE_ALLOWED 0` |
| v36 | not flashed | ungates regen from `charge_goal` |

The v36 change: `chargingControl()` returned early when `charge_goal <= 0.05`,
thirteen lines before `regenActive` was computed, so the regen path could not
open unless the Pi was separately requesting fuel-cell charging. The fuel cell
never charges the battery on this build, so the two conditions should never
have been coupled.

## Pi software

`teensy_bridge_node` speaks a 58-byte UDP protocol (v4) with the Teensy at
50 Hz and publishes `/vehicle_state` (18 elements) and `/soc_diagnostics`.
State of charge is an EKF over coulomb counting, corrected by terminal voltage
through the OCV curve.

`sdp_ems_node` runs the stochastic dynamic programming policy at 20 Hz and
commands a **power-share ratio**, not a power. The Teensy realises it through
droop, so delivered FC current is `share × I_total`. Two constraints follow:

- the share must stay inside `(0.15, 0.85)` **exclusive** — the firmware's
  selector test is inclusive, and commanding a rail cuts a source off the bus
- a dynamic ceiling caps the share at `1.10 / I_total_filtered` so `I_fc`
  cannot reach the 1.4 A single-sample overcurrent trip

`drive_cycle_node` plays a speed trace and publishes demand from the fitted
road load above.

## Analysis

    fchev_plot.py       four-panel overview: speed, share, currents, SOC/faults
    plot_power.py       P_fc / P_batt / P_demand
    check_sdp.py        SOC band, mode occupancy, share tracking by current band, faults
    check_regen.py      switch_state decode, regen arming, charge current
    make_tpm_*.py       demand transition matrix
    make_costtogo_*.py  SDP cost-to-go tables

Usage is `python3 <script> <bag directory>`.

## Calibration status

Two pack parameters are still placeholders and the absolute SOC number should
not be trusted until they are measured:

- `pack_r_int_ohm` is 0.050, a guess. At 0.8 A that is 40 mV of IR against
  roughly 23 mV of OCV swing across a whole run, so R0 error dominates.
- the OCV curve is a generic 2S NMC shape, not this pack. It sets the EKF's
  measurement Jacobian, so it scales every correction.

Hydrogen usage follows Faraday's law from stack current; the datasheet fuel
map is that law with the polarisation curve folded in. The purge term is
separate and has not been measured — the timing is known (100 ms every
10.34 s) but not the flow it vents.

## Open

- regenerative braking still returns no charge current, cause under investigation
- the fuel cell is not delivering power as of 3 Nov 2026, undiagnosed
