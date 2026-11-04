# Bench operations documents (scale car)

The PhD student's operating documents for the Pi/ROS 2 side of the bench. They
are copied byte-for-byte from `phd/siddhesh-2026-11-03` (`64fb553`, student
folders `scale_car/Documentation/Operation Guide/` and `Checklists/`).

| File | What it is |
|---|---|
| `FCHEV_Experiment_Operations_Guide_2026-08-21A.docx` | Current experiment operations guide. Its sections 2.4 / 9.4 point at `simple_ems_test_2026-03-16A.py`, which cannot parse v4 packets; use `fchev_run.sh --teensy` instead (`references/EMS/Pi_2026-11-03/fchev_run.sh` header) |
| `FCHEV_Experiment_Operations_Guide_2026-04-22A.docx` | Earlier revision |
| `FCHEV_PostRun_Analysis_WSL2.docx` | Post-run bag analysis under WSL2 (see `tools/rosbag_analysis/`) |
| `checklists/Pi_Setup_Checklist_2026-03-16A/B, 2026-04-16A.xlsx` | Pi setup checklist revisions |
| `checklists/FCHEV_SSH_ROS2_Plan_2026-04-06A.xlsx` | SSH / ROS 2 setup plan |
| `checklists/FCHEV_NextSteps_Plan_2026-04-16A.xlsx` | 2026-04 next-steps plan |

Not imported: an Office lock file (`~$HEV_Experiment_Operations_Guide_2026-04-22A.docx`)
and `test car data log/balancer_board_showcase_20260817.zip`, which is
byte-identical to `docs/balancer_board_showcase_20260817.zip`.
