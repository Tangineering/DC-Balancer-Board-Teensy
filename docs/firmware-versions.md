# Firmware version ledger

`FW_VERSION` is a monotonic u16 defined near the top of
`teensy_controller/teensy_controller.ino`. **Bump it on every flash-worthy
behavioral change** — control law, pin/sequencing, scaling, logging format —
and add a row here in the same commit. Comment/doc-only changes do not bump.

The version is:
- stamped into every `.BLG` bench-log header (format v2, u16 at offset 18),
  so every logged dataset is attributable to the firmware that produced it
  (`decode_benchlog` prints it; it lands in each run's `decode_report.txt`);
- printed at boot (`[BOOT] DC balancer firmware vN`);
- printed by the State-98 `S` status dump (`FW_VERSION: N`).

Version **0 / "pre-versioning"** is reserved for all firmware before this
ledger existed. Format-v1 `.BLG` files (no fw_version field) decode as
`fw_version=pre-versioning`; that covers `PS0001`–`PS0002` (pre-averaging)
and `PS0003`–`TP0005` (`analogReadAveraging(8)`).

| FW | Date | Flashed changes (vs previous) | Logs produced |
|----|------|-------------------------------|---------------|
| 0 | — | Everything before versioning. Notable sub-states: PS0001/PS0002 ran the pre-averaging build (Teensyduino default averaging 4); PS0003/TP0004/TP0005 ran the `analogReadAveraging(8)` build; the 2026-08-11 share-setpoint sweep TP0007–TP0013 also decodes as fw 0 (format-v1 headers). | PS0001–TP0005, TP0007–TP0013 |
| 1 | 2026-08-11 | `analogReadAveraging(16)` (was 8). Share-integrator minimum-load hold at `SHARE_I_TOT_MIN_A` = 75 mA. Full-span share command semantics: setpoints/ratios valid over [0,1]; `applyShareRatio()` actuation layer — droop-band clip [0.15, 0.85] moved inside it, out-of-band ratios cut the starved channel off the bus via its RT1987 bus switch (never the boost enable) with 0.01 re-entry hysteresis and a charged-bus re-entry guard; `O`/`P` commands unclamped to [0,1]; Youla anti-windup authority span widened to [0,1]. BLG header format v2 (fw_version stamp). State-98 combined profiles: `Y` (velocity + share) and `W` (commanded current + share) sweep both axes from one shared 16-region table via `advanceComboRegion()`, logged to `YPnnnn`/`WPnnnn`; **the VESC watch moved from `W` to `U`**; both profiles warn when the committed share band reaches the cutoff region and re-close a latched channel cutoff on natural completion; `pollVescWatch()` suppressed during the staged bring-up. | *(never flashed — superseded by v2 before first flash)* |
| 2 | 2026-08-11 | Share-loop limit-cycle mitigation (TP0010/TP0013 sweep + capture 12; whitepaper `docs/share_sweep_whitepaper`): setpoint governor clips the effective in-band share setpoint so the commanded minority-channel current stays ≥ `SHARE_MINORITY_I_MIN_A` = 0.20 A (collapses to 0.5 below 2×; out-of-band setpoints incl. 0/1 bypass — the cutoff path owns them); droop-ratio slew limit `DROOP_RATIO_SLEW_PER_TICK` = 0.02/tick in `applyShareRatio()` (full band in 35 ms, no rail-to-rail MDAC slams); `resetShareControlState()` at every profile start (`R`/`D`/`T`/`Y`/`W`) — runs no longer inherit the prior run's controller state. ΔV₀ CAL-1 recorded in the model (+0.05 V, bench supplies); shipped Youla coefficients unchanged. | *(never flashed — superseded by v3 before first flash)* |
| 3 | 2026-08-11 | State-98 `T` sweep extension: `T <Imax> <hold> <rate> [t,r1,...,rn]` runs one trapezoid per closed-loop share setpoint `r_i` (max 16), each to its own `TPnnnn.BLG`, with the next run gated on the logger being fully idle (`!logActive && !logCloseRequested` — an early start would silently lose that run's dataset) and separated by a `t`-second motor cool-off dwell. Share setpoint applied via `setPowerShareSetpointLive()` BEFORE each run opens its log; setpoint restored to 0.5 / `powerBalanceLive` cleared on completion and on every cancel path (`T`-stop, `X`, `Q`, a new `T` line, or any other profile start). Sweep list refused under plot mode (`L`); the grammar's 4th field ends the old trailing-junk tolerance (any unparsable tail now rejects the whole line). `inputBuf` 32 → 96 B, and `[`/`,`/`]` accepted at the trapezoid prompt only. Automates the hand-run TP0007–TP0013 sweep. | *(pending first flash)* |
