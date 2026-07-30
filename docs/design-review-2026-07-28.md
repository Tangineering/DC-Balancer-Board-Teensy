# DC Balancer Board Firmware and Bench-Readiness Review

**Review date:** 2026-07-28  
**Scope:** Read-only review of the current firmware, host-native tests, current PCB artifacts, and boost bring-up history.  
**Reviewed revision:** `5b1d4f1` (`main`)

## Verdict

**Do not begin powered VESC/motor or real-2S-pack testing with the current firmware and unknown as-built board state.**

The pin map, Ag105 implementation, ADC scaling, and the new 16 V droop model are substantially reconciled with the design. The remaining blockers are concentrated in State 98, where manual commands can bypass the sequencing protections added after the boost failures, plus several unresolved physical/as-built checks.

This review changed no firmware or hardware files. It is intended as a concrete handoff for the next implementation pass.

## Sources reviewed

- `teensy_controller/teensy_controller.ino`
- `test/test_main.cpp` and the host mocks/Makefile
- `references/Scale Car Teensy IO - IO.csv`
- `references/Scale Car Design PCB BOM 20260622.csv`
- `references/Scale Car DC Balancer Board Schematic 2026-06-22.pdf` (all four sheets)
- `references/Scale_Car_Board_20260624.sch` and `Scale Car Board PCB 20260625.brd`
- `docs/boost-bringup-debug.md`, `docs/boost-diagnostics-summary.md`
- `controller_design/system_model.md` and `controller_design/bench_calibration_manual.md`
- `PLAN.md`, `README.md`, `AGENTS.md` / `CLAUDE.md`

## What is confirmed

- The firmware pin block matches the authoritative IO CSV row-for-row, including the six RT1987 enables, `CBAL_DISABLE`, and the two additional ADC channels.
- The schematic confirms that `RGN_VOLTAGE` is derived from the V-MOT/regen node, so it is the intended measurement for the motor-node precharge guard. The threshold is still uncalibrated.
- The Ag105 control approach is structurally correct: lazy power-aware configuration, I2C status/current polling, and active-low `MPPT_DISABLE` behavior.
- The host suite builds cleanly with `-Wall -Wextra` and passes:
  - production configuration: **333 passed, 0 failed** (`-DBENCH_TEST=0`)
  - bench configuration: **6 passed, 0 failed** (`-DBENCH_TEST=1`)

Passing host tests is not a board-ready sign: they do not execute Arduino `setup()`/`loop()` on a Teensy target and do not exercise the unsafe State 98 path combinations below.

## Blocking findings

### P0-1: State 98 `G` is only safe from a dark state, but the code lets it run from any state

**Evidence**

- `doState98()` calls `bringUpBus()` directly for `G`: `teensy_controller/teensy_controller.ino:1468-1473`.
- `bringUpBus()` unconditionally raises `FC_BUS_ENABLE`, `BT_BUS_ENABLE`, and `MOT_PWR_ENABLE`: `:2000-2010`.
- It neither clears `FC_CHARGE_ENABLE` / `REGEN_ENABLE` nor calls `assertMotPwrEnable()`.

**Unsafe reproductions**

1. Press `5` to assert `FC_CHARGE_ENABLE`, then press `G`. `G` asserts `BT_BUS_ENABLE`, creating the IO-CSV-prohibited `FC_CHARGE_ENABLE + BT_BUS_ENABLE` combination. The default `BENCH_TEST=1` build compiles out the switch-conflict fault (`:812-832`).
2. With VBUS energized, turn `MOT_PWR_ENABLE` off, allow V-MOT to decay, then press `G`. The direct write can reconnect a discharged V-MOT/VESC stack at full bus, bypassing the Death-5 hot-plug guard (`assertMotPwrEnable()` at `:2041-2046`).

**Required fix direction**

Make `G` a preconditioned transition, not a raw GPIO macro. It must either refuse any non-dark/non-precharged state or first establish and verify a safe state: charge paths closed, no active motor command, motor-node condition checked, then use the same low-voltage sequencing state machine as production initialization. Add regressions for both reproductions.

### P0-2: A State 98 drive cycle can leave/reissue motor current after stop or natural completion

**Evidence**

- Natural completion only clears `v_setpoint` and `driveCycleActive`: `teensy_controller/teensy_controller.ino:1617-1622`.
- The already-entered drive branch still executes `motorControl()` in that tick: `:1588-1595`; later ticks send no explicit zero command.
- Manual motor mode is not cleared when a drive cycle starts or stops (`:1441-1465`). The standalone branch immediately calls `applyManualMotor()` when a stale manual mode exists (`:1605-1610`).

**Concrete failure case**

Set manual current with `A`, start `D`, then press `D` to stop. The stop handler sends one `vesc.setCurrent(0)`, but falls through to the standalone branch in the same invocation and can reissue the old manual current. Natural completion has the same stale-manual issue, plus no final zero flush.

**Required fix direction**

Give the drive cycle one ownership model for motor output. On every drive-cycle exit path (manual stop, natural completion, fault/exit), clear manual mode, zero the VESC command, reset `current`, and transition through a controlled stop path. Add a regression that starts with an active manual current, then stops and naturally completes a drive cycle.

### P0-3: `MOTOR_I_CMD_MAX` does not limit the actual VESC command

**Evidence**

- `motorControl()` sends `PI_Controller_Motor(...)/motorConstant` directly: `teensy_controller/teensy_controller.ino:2049-2053`.
- `MOTOR_I_CMD_MAX` limits only the PI integrator contribution: `:2069-2075`.
- The proportional term is unbounded; `motorConstant` and velocity units are explicitly TODO/calibration items (`:320-323`, `:2418-2425`).

For example, a 5 m/s velocity error with the current `motorConstant = 0.1` produces a 50 A proportional command before the integral term. The State 98 manual-current path does clamp, but manual velocity, the drive cycle, and UDP velocity control use the unbounded path.

**Required fix direction**

Clamp the final finite current command immediately before `vesc.setCurrent()`, validate/reject non-finite or out-of-range UDP setpoints, and add a test that asserts the emitted VESC current never exceeds the approved bench limit. Do not run velocity or drive-cycle testing before this is resolved and the safe ceiling is calibrated.

### P0-4: The firmware's assumed as-built power stage is not verified

The source schematic/BOM is a design baseline, not an as-built record. The current code assumes these post-build changes:

- both `RD1` values bodged from 237 kOhm to 215 kOhm, yielding about 16 V nominal;
- `RC-BT` changed from 27.4 kOhm to 61.2 kOhm;
- a 10 uF + 0.1 uF output-cap bodge at the BT boost; and
- a working/replaced FC TPS61288 plus an equivalent FC output-cap bodge.

The first three are recorded in the firmware header (`teensy_controller/teensy_controller.ino:78-83`, `:175-189`) and model. The FC repair/cap bodge is **not** recorded as complete. The latest debug log still says the FC regulator needs replacement and the FC caps should be added at that time (`docs/boost-bringup-debug.md:202-207`).

The original CAD/BOM says `RD1=237 kOhm` and `RC-BT=27.4 kOhm`; an older manufacturing export says `RD1=243 kOhm` and both RC values 61.2 kOhm. None proves what is installed today.

**Required physical gate before power**

Visually inspect and DMM-confirm both boost ICs, both local 10 uF + 0.1 uF cap bodges, both RD1 values, and both RC values. If the 215 kOhm bodges are absent, firmware's 16 V nominal / 17 V OV limit is wrong for the board. Do not infer as-built values from any repository artifact.

## High-priority findings

### P1-1: State 98 stop/exit paths contradict the motor-node precharge policy

`D`/`R` early stops call `safeAllSwitches()` immediately after one zero-current UART write (`teensy_controller/teensy_controller.ino:1457-1465`, `:1538-1544`). It closes `REGEN_ENABLE` and then `MOT_PWR_ENABLE` without a decay/zero-speed confirmation (`:1981-1988`). `Q` similarly writes `MOT_PWR_ENABLE` low (`:1571-1579`).

That differs from the post-Death-5 policy to retain V-MOT through Idle/Run, and from State 99's controlled regen-drain sequencing (`:1265-1273`). A zero UART write is asynchronous and is not proof a spinning motor cannot regenerate.

Also, after `Q` cuts V-MOT but leaves VBUS energized, a later State 2 entry will safely fault rather than hot-plug the motor node. That is safe-but-unusable: State 98 cannot cleanly return to normal Run without a fault/power cycle.

**Required fix direction:** replace the raw State 98 switch-off helper with a nonblocking stop/exit state that follows the validated motor-node policy. Decide explicitly whether test exit retains precharge or performs a controlled State-99-style drain, then cover it end-to-end.

### P1-2: The default bench build is intentionally missing most software protection

`BENCH_TEST` defaults to `1` (`teensy_controller/teensy_controller.ino:405-407`). It disables FC/BT overcurrent, UV, switch-conflict, and charger-status faults (`:812-862`). It is appropriate only for a dark, controlled bring-up; `detectFaults()` running in State 98 is not equivalent to full protection.

This is especially problematic because `LIMIT_V_BATT_MAX = 10.0 V` is above the physical BT-divider range (8.646 V), so battery OV can never trip (`:184-189`). In the default build it is effectively the only battery-related firmware protection left.

**Required fix direction:** separate the "do not auto-bring up power at boot" behavior from disabling essential safety interlocks, or make the powered-bench build choice unmistakable. Do not connect a real 2S pack/charger until a reachable, calibrated OV limit is used (the source comment recommends 8.5 V) and the battery UV floor is reconciled with the 7.4 V operating floor in the current model.

### P1-3: State 98 can command regen without establishing the regen path

Manual current accepts negative values (`teensy_controller/teensy_controller.ino:1782-1803`). The manual and power-share-profile branches deliberately do not call `chargingControl()` (`:1596-1610`), so an operator can request regen while `REGEN_ENABLE` is low, `FC_CHARGE_ENABLE` is high, MPPT is released, or the battery sequence path is off.

`G` also does not raise `BT_SEQUENCE_ENABLE`; unlike production State 0 (`:1091-1093`), it only handles the bus/boost pins (`:2000-2010`). A manual regen test after `G` can therefore route energy toward a charger whose battery terminal remains disconnected.

**Required fix direction:** prohibit negative manual current except in an explicit regen-test mode that atomically establishes `FC_CHARGE=LOW`, `REGEN=HIGH`, `MPPT_DISABLE=LOW`, and confirmed battery-path readiness. Gate motor tests on VBUS, V-MOT, and battery sequence readiness rather than only `MOT_PWR_ENABLE`.

### P1-4: State 98 boost-enable toggles are not staged

The `F`/`B` handlers blindly flip TPS61288 enables (`teensy_controller/teensy_controller.ino:1358-1369`) even while a manual command, drive cycle, or power-share profile is active. Current notes suggest the RT1987 has reverse isolation, so this is not claimed as the same proven body-diode failure mode. It can still abruptly drop a live source/bus while the VESC or paths are active, with no fault backstop in `BENCH_TEST`.

**Required fix direction:** make F/B setup-only commands, require the corresponding bus path and motor command to be safely inactive, or implement an explicit staged source-drop procedure. Add a host test.

### P1-5: The motor hot-plug guard depends on an uncalibrated ADC proxy

`motPwrHotPlugUnsafe()` uses `V_rgn` and `MOT_HOTPLUG_MARGIN = 3.0 V` (`teensy_controller/teensy_controller.ino:224-230`, `:2030-2046`). The schematic supports the net relationship, but the debug record explicitly requires an ADC/DMM correlation and margin calibration before trusting it (`docs/boost-bringup-debug.md:181-193`). Host tests only inject ideal floats.

**Required action:** measure V-MOT, RGN ADC voltage, and reported `V_rgn` with MOT power open and closed; calibrate a margin with noise/settling accounted for before any VESC-connected test relies on the guard.

### P1-6: VESC diagnostic reads can stall State 98 safety processing while current is active

`E` issues two blocking VESC reads (up to about 200 ms total), and `W` issues a blocking read every 500 ms (`teensy_controller/teensy_controller.ino:1695-1701`, `:1733-1746`). The watch is suppressed for the timed profiles but not manual current/velocity. During a stall, the prior VESC current command stays active and no sensor/fault pass occurs.

**Required fix direction:** disallow `E`/`W` while any motor command is active, or first zero the motor and prove it is inactive. At minimum, make this an explicit bench-procedure restriction.

## Correctness and observability findings

### P2-1: `I_charge` telemetry becomes stale on charger power loss or I2C failure

`pollAg105()` clears `ag105Configured`, validity, and status on loss/failure, but does not clear `I_charge` (`teensy_controller/teensy_controller.ino:2275-2281`, `:2307-2317`). `sendTelemetry()` always sends the old float (`:974-993`). The Pi can therefore receive a positive charge current while `charger_status=0` and the charger is unpowered.

**Required fix direction:** clear `I_charge` when data becomes invalid or add an explicit validity field; test the telemetry after power loss and NACK.

### P2-2: State 98's written watchdog-reset requirement is not implemented

The requirements call for refreshing the Pi watchdog timestamp upon State 98 entry/exit. The renamed `last_rx_ms` is set only by `receiveCommands()` (`teensy_controller/teensy_controller.ino:920`), not by State 98 entry or `Q` exit (`:1133-1139`, `:1560-1582`). The state guard makes an immediate fault unlikely, but the stated invariant is unmet and untested.

### P2-3: Current-test coverage gives a false sense of bench protection

The bench executable intentionally runs only the six State-0 bench-bypass tests. It does not exercise `setup()`, `loop()`, State 98 sequencing, the `G` path, manual regen, live boost toggles, or the deployed `BENCH_TEST=1` fault profile. The production suite checks many primitives but not the unsafe stateful combinations described above.

## Documentation and configuration drift

Several documents are unsafe to use as current bench instructions without reconciliation:

- `README.md` still says `MOT_PWR_ENABLE` is Run-only/low in Idle, reports old 17.5 V/18.5 V limits, and tells the operator to turn motor power off after a drive cycle. This conflicts with the Death-5 precharge policy and current 16 V firmware constants.
- `PLAN.md` is partly historical and contains pre-retune State-98/threshold guidance and outdated test counts.
- `docs/boost-bringup-debug.md` correctly keeps the high-bandwidth ring measurement as a blocking task, but its 16 V discussion is older than the current firmware header and does not establish FC repair completion.
- Original BOM/CAD, old manufacturing BOM, the firmware header, and the system model disagree on several resistor values. Treat the board itself as the only as-built authority until it is measured.

Create one dated, operator-facing "as-built and approved bench configuration" page before the next flash. It should specify the measured component changes, firmware build flags, measured voltage thresholds, and the exact safe State 98 command sequence.

## Required physical preflight, in order

1. **Do not connect the VESC or a real 2S pack yet.** Begin with the VESC disconnected and an appropriate electronic load, as the calibration manual directs.
2. Verify that the FC TPS61288 is not shorted and has actually been replaced if necessary. Verify the FC 10 uF + 0.1 uF local-output caps and the mandatory BT equivalents.
3. DMM-confirm `RD1-FC`, `RD1-BT`, `RC-FC`, and `RC-BT`; record the exact as-built values. Confirm that the firmware's 16 V assumptions agree.
4. Power logic from a separate supply. Do not rely on a 9 V battery, a soft source, or an input-current limit as boost protection.
5. Before VESC/load work, obtain the required high-bandwidth, 10x-probe, ground-spring SW/VOUT capture. The prior BT fix was validated by survival, but its original captures were too low-bandwidth to establish margin.
6. Correlate `V_rgn` ADC telemetry with V-MOT using a DMM/scope, then calibrate `MOT_HOTPLUG_MARGIN`.
7. Keep first BT-channel/load work at or below the conservative model/manual envelope (about 3 A/channel) rather than treating the 6 A firmware OC threshold as validated.
8. Only after the P0 firmware changes and the above measurements: re-enable a safe, explicit battery-protection configuration before testing charge or regen with a real 2S pack.

## Required regression tests for the fix pass

- `G` with `FC_CHARGE_ENABLE=HIGH` must refuse or first close the conflicting path.
- `G` with VBUS high and V-MOT discharged must refuse; it must not directly write a hot-plugged motor power enable.
- Drive-cycle early stop and natural completion must leave `manualMotorMode=OFF`, `current=0`, VESC command zero, and paths in the selected safe state.
- Final VESC current from UDP/drive/manual velocity must clamp to the approved ceiling, including positive, negative, non-finite, and large-error cases.
- Negative manual current must not be accepted unless the validated regen path is active.
- State 98 F/B toggles must be refused while a relevant bus/motor path is live.
- Charger telemetry must report zero/invalid charge current after a power loss or I2C failure.
- The intended State 98 exit/precharge policy and watchdog timestamp behavior must be tested end-to-end.

## Handoff recommendation

Claude should first implement and test the three P0 firmware fixes (`G` sequencing, drive-cycle ownership/stop, final motor-current clamp). Then reconcile State 98 teardown/regen behavior with the post-Death-5 hardware policy before authorizing any VESC-connected testing. Hardware inspection and the high-bandwidth scope capture remain independent gates; no firmware change substitutes for them.
