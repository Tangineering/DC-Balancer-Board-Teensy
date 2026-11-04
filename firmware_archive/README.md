# Firmware archive

Historical Teensy sketches that are **not** part of the live firmware line. The
live firmware is `teensy_controller/teensy_controller.ino`. Its version history
is in git (`git log -- teensy_controller/teensy_controller.ino`) and in
`docs/firmware-versions.md`.

These sketches came from the PhD student's branch `phd/siddhesh-2026-11-03`
(commit `64fb553`, student folder `scale_car/Code/Teensy/`) and are copied
byte-for-byte. They live outside the `teensy_controller/` sketch folder on
purpose, because the Arduino IDE compiles every `.ino` in a sketch folder.

| Folder | What it is |
|---|---|
| `pre_board_Scale_Car_Teensy/` | The original pre-reconciliation sketch (564 lines): `CHARGER_ENABLE`, `CHARGER_OK`, `CHRG_CURRENT`, encoder on pins 2/8, written for a BQ25690 charger. This is the "stale firmware" that CLAUDE.md's reconciliation task describes. |
| `pre_board_Scale_Car_Teensy_Sid_2026-04-21/` | The student's 2026-04-21 fixes to that sketch: UDP ports 5000/5001, sync byte 0xBB, checksum span, ADC scaling, Pi watchdog, fault flags, mode-driven state transitions. |
| `fw19_sketch_aug25a/` | `FW_VERSION 19` (2026-08-25: the `'L'` stream's encoder fields and the conduction-aware handoff slew; see ledger row 19). The `.ino` was not committed to this repo until 2026-09, so this is the only fw v19 source in git. |

The student's `sketch_aug25a/` folder also held `drive_controller.h`,
`drive_controller_coeffs.h`, `share_controller.h` and
`share_controller_coeffs.h`. Those are byte-identical to the current copies in
`teensy_controller/`, so they were not duplicated here. To build fw v19, copy
the four headers from `teensy_controller/` into its folder. Whether the
current-era headers are the ones fw v19 actually shipped with is unverified.
