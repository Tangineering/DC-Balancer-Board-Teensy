# CLAUDE.md archive — superseded session addenda (2026-06-23 → 2026-08-13, fw v7)

Moved verbatim from CLAUDE.md on 2026-08-16 to reduce always-loaded context.
Facts here may be SUPERSEDED by later addenda in CLAUDE.md; the markers inside
each section say which. The RC-BT compensator bodge record (2026-07-10) stayed
in CLAUDE.md.

## Status & session addendum (2026-06-23)

**The reconciliation (§§1–10) is implemented.** `teensy_controller.ino` now targets the
20260622 board: rebuilt pin map, RT1987 power-path sequencing, Ag105 charger over I2C +
`MPPT_DISABLE`, BQ29200 `CBAL_DISABLE`, 12-bit ADC + recomputed scales, INA253A1 `K_sns = 0.1`,
v4/58-byte telemetry, State 98 test mode, and the host-native test suite. The changelog block at
the top of the `.ino` records the hardware delta.

A subsequent **correctness/robustness review round** then fixed a set of bugs and latent hazards
found in that firmware. Those changes and the design decisions behind them are catalogued in
**PLAN.md §11**; in brief:

- **Bugs fixed:** `doState0()` no longer swallows a charger-init fault (was demoting State 99 →
  Idle); Ag105 GENSTAT decode corrected (mask `0x07`; errors `0x05`/`0x06`/`0x07`; `0x04`
  Bring-Up is normal); `FAULT_UV_FC`/`FAULT_UV_BATT` gated to Run so unramped rails don't
  boot-lock State 99; `pollAg105()` I2C fault gated to the charging-relevant states.
- **Robustness:** State 3 and State 99 shutdowns are now **non-blocking** phase machines (no
  `delay()`), so `detectFaults()` stays live through the drain windows; State 98's drive cycle
  runs the real `chargingControl/motorControl/powerBalance`, flushes the VESC and parks all
  switches (`safeAllSwitches()`) on stop; the motor PI gained anti-windup
  (`MOTOR_I_CMD_MAX`); wheel-speed buffers reset between runs.
- **Docs:** telemetry corrected to v3/57-byte across PLAN.md; `K_sns` corrected to `0.1` V/A in
  PLAN.md (the A1 part fitted, not the A3).

A later change then **bumped telemetry to v4 / 58 bytes**: the `charger_status` byte (dropped in
v2) was reinstated at its historic offset 51, now carrying the **raw Ag105 Table 6 status byte**
(`ag105_status_raw`). This restores the old off/CC/CV/fault charger telemetry — and supersedes it,
since the Ag105 byte also exposes CC (bit 6), CV (bit 5), MPPT/Power-Tracking/Thermal-Limiting
flags, and the full GENSTAT fault set. `switch_state` and the trailing fields shift +1; the
checksum span is now bytes 1–56. The Pi bridge must be updated in lockstep (it parses fixed
offsets). Layout + bit decode in PLAN.md §6b.

All 177 host-native tests pass (`cd test && make`). Remaining work is bench calibration of the
`TODO(calibrate)` / `TODO(verify)` items (dividers, `motorConstant`, PI gains, `MOTOR_I_CMD_MAX`,
regen threshold, drain delays, AD5443 SPI verification).

---

## Status & session addendum (2026-06-23, bench bring-up)

Bench bring-up of the assembled board drove a set of changes. **These supersede parts of the
earlier addendum** — notably, `doState0()` no longer configures or faults on the charger at all.

- **Charger config is now power-aware and lazy (supersedes "doState0 no longer swallows a
  charger-init fault").** The Ag105 is unpowered until a charger power path is open
  (`chargerHasPower()` = `FC_CHARGE_ENABLE || (REGEN_ENABLE && MOT_PWR_ENABLE)`), so it cannot
  ACK I2C in Init — a State-0 config could never succeed on hardware. `doState0()` no longer
  calls `initAg105Charger()`. Instead `pollAg105()` lazily writes the config the first time the
  charger is powered, past the `AG105_SETTLE_MS` bring-up window, and ACKing; tracked by
  `ag105Configured` (re-arms on power loss; EPROM makes the re-write idempotent).
  `initAg105Charger()` now returns `bool` and raises no fault itself.
- **Charger fault-sensing is power-gated, not just state-gated.** `pollAg105()` faults
  (`FAULT_I2C_CHARGER` / `FAULT_INIT_FAIL`) only when `chargerHasPower() && settled &&
  (State 2|3)`. Unpowered or within the settle window is never a fault; State 98 is excluded.
  The `detectFaults()` GENSTAT check is unchanged (already guarded on `ag105_status_raw != 0`).
- **`chargingControl()` FC-path deadlock fixed.** Cruise opens `FC_CHARGE_ENABLE` on intent
  (`charge_goal > 0`) to power/boot the charger; only the MPPT release is gated on
  `ag105IsReady()`. Without this the FC harvest path could never bootstrap.
- **`BENCH_TEST` flag** (`#ifndef`-overridable): relaxes `detectFaults()` to overvoltage-only
  so the board reaches Idle on the bench with unpowered rails. Defaults to `1` for bench
  flashing; the **test suite compiles `-DBENCH_TEST=0`** (production fault behavior). Charger
  config/faults are no longer tied to `BENCH_TEST` — power-gating handles bench safety.
  Also: `USE_ETHERNET` flag + `networkUp` guard so the UDP functions no-op (don't hard-fault)
  when Ethernet isn't initialized; State-98 `I` I2C-scan command; State-99 1 Hz error print.
- **Test suite path fixed:** the `.ino` now lives in `teensy_controller/`; `test_main.cpp`
  include and the Makefile `-I` were updated. **All 205 host-native tests pass** (run with
  MSYS2 UCRT64 g++: `cd test && mingw32-make`, or g++ directly — there is no `make` on this
  machine). New `AG105_SETTLE_MS` is a `TODO(calibrate)`.

---

## Status & session addendum (2026-06-24, VBUS controlled bring-up)

A bench-test mishap drove a safety fix. In State 98 the operator enabled `BT_BUS_ENABLE` while
both boosts were already running (~17.5 V) and VBUS sat at 0 V; the BT TPS61288 boost was
destroyed (VIN/SW/VOUT all shorted to GND) and the Teensy browned out off USB.

- **Root cause (reconciled against the new `references/Datasheets/RT1987_DS-00.pdf` + schematic
  sheet 4).** The RT1987 has **back-to-back integrated FETs** (full VIN/VOUT isolation when
  disabled — *no* body-diode passthrough) and **soft-start + start-up SCP that re-run on every EN
  edge** (board `CSS = 5.6 nF` → tON ≈ 1.17 ms; POVP→GND → OVP ≈ 33 V). VBUS carries a **470 µF**
  bulk cap, which a 1.17 ms ramp cannot charge within ISCP, so a hot-plug makes the RT1987
  SCP-clamp and burst-retry. The real kill was the **shared 9 V test rail**: `VBT` feeds the BT
  boost *and* the LM1084 logic reg, so the burst browned out the MCU and stressed the boost.
  FC-first worked because FC's source is isolated and pre-charged the bus → BT then saw a ~0 V
  step. Takeaway: **never hot-plug a running boost onto a discharged 470 µF bus.**
- **Boosts default OFF in `setup()`.** They are enabled by `doState0()` *after* the bus switches.
- **`doState0()` is now a non-blocking phase machine** that brings the bus up gently: bus switches
  first (RT1987 soft-starts the bus to ~Vbatt), settle `BUS_SETTLE_MS`, then boosts (their own
  soft-start ramps the bus to 17.5 V). State 0→1 is **gated on `V_bus ≥ V_BUS_CHARGED_THRESH`**,
  with `BUS_CHARGE_TIMEOUT_MS` → `FAULT_INIT_FAIL` (dead boost / failed switch / no source).
- **`doState3()` (Finish) no longer drains the bus.** It stops the motor and closes the
  motor/regen/charge paths but **leaves the boosts + `FC_BUS`/`BT_BUS` ON**, so the bus stays
  armed and Idle→Run never re-hot-plugs. Only **State 99** tears the bus down (latched → power
  cycle → State-0 gentle bring-up). This drops the old two-phase cap/regen drain (the disabled-
  boost back-feed hazard does not apply while the boosts stay enabled).
- **State 98 guard + `G` command.** `1`/`2` refuse to turn a `*_BUS_ENABLE` ON when the matching
  boost is ON and `V_bus` is low (`busHotPlugUnsafe()`); new `G` runs `bringUpBus()` (switches →
  settle → boosts) for a safe manual bring-up.
- No telemetry layout change (reuses `FAULT_INIT_FAIL`/`ERR_INIT_FAIL`). New
  `V_BUS_CHARGED_THRESH`, `BUS_SETTLE_MS`, `BUS_CHARGE_TIMEOUT_MS` are `TODO(calibrate)`.
  The BT TPS61288 has been replaced and the board is functioning again.

### Corrected failure analysis + BENCH_TEST bypass (supersedes the inrush framing above)

Bench bring-up from a **current-limited supply** (no fuel cell, `VBT` from a DC supply) repeated the
`VBT→GND` short. Diagnosis was refined, and two earlier theories were wrong — recorded so the
code/docs stop repeating them:
- **Inrush is NOT the cause.** The 470 µF bulk cap is on the **V-MOT / regen node behind
  `MOT_PWR_ENABLE`**, not on VBUS. With `MOT_PWR_ENABLE` off, VBUS carries only ~30–40 µF (the
  RT1987 ceramics), so bus inrush is negligible — and `MOT_PWR_ENABLE` was off in the original
  State-98 failure too.
- **The recurring killer is the BT boost on a collapsing input.** The Teensy is **board-powered**
  (LM1084 off `VBT`). On a supply that can't carry the logic baseline (Teensy + Ethernet PHY ≈
  150–250 mA through the linear reg), `VBT` sags → Teensy browns out → resets → `doState0()`
  re-enables the boost → **motorboating**. Switching with built-up inductor current on a
  sagging/recovering rail then destroys the power stage. **Exact mechanism is UNCONFIRMED** (pending
  a SW/VOUT scope capture): most likely a **VOUT overshoot past the 20 V SW/VOUT abs-max** — the
  TPS61288 OVP is at 19 V (≤19.5 V), leaving only ~0.5 V margin, and the 3×22 µF output caps
  DC-derate to ~30 µF, so an inductor-commutation spike (½·L·I² at the 15 A limit into ~30 µF) rings
  over 20 V — and/or **transient reverse conduction**. Either way the destructive energy comes from
  the boost's own inductor / output cap, so a **supply current limit does not bound it**. (An
  earlier note here asserted reverse conduction specifically; the datasheet's PFM negative-current
  blocking weakens that, so overshoot is now the leading candidate — to be settled by scope.) Same
  class of event as the first incident (weak 9 V battery sagging under load); replacing the TPS61288
  fixed that one, confirming the boost (not the `VBT` tantalum) is the failure point.
- **`BENCH_TEST` bypass.** `doState0()` now wraps the bring-up in `#if BENCH_TEST`: under
  `BENCH_TEST` (the default bench flash) it boots **straight to Idle with the power stage dark**
  (boosts, bus switches, and `BT_SEQUENCE` all stay LOW; no `V_bus` gate) — so a soft bench supply
  can't trigger the motorboating loop. Bring the bus up manually with the State-98 `G` command on a
  **stiff** supply. Production (`BENCH_TEST=0`) keeps the full bring-up + gate. Source-agnostic init
  is shared via `initControlPeripherals()`.
- **Bench rule:** the supply must comfortably exceed the logic baseline (≥ ~0.5–1 A) or the
  board-powered Teensy browns out; bring the bus up only on a stiff supply (the killer is the boost
  on a collapsing input, independent of any current limit).
- **Tests:** the suite gains a second `-DBENCH_TEST=1` build (`run_tests_bench`) covering the
  bypass (`test_dostate0_bench_bypass`); the `-DBENCH_TEST=0` build keeps the production `doState0`
  tests. `cd test && mingw32-make` builds and runs both.

### ✅ RESOLVED (2026-07-07) — battery boost VBUS-connect deaths: hot-loop layout, fixed with caps

Four battery-side TPS61288 boosts were destroyed on `BT_BUS_ENABLE` bus-connect. **Root cause: the
BT channel's output caps sit 240 mil from the IC output (FC: 40 mil) → ~2.7× output-cap hot-loop
inductance → SW/VOUT overshoot past the 20 V abs-max when driving the bus.** Fix: **10 µF + 0.1 µF
ceramics bodged directly at the BT boost output** — validated by four consecutive surviving `G`
bring-ups under Death-4 conditions (single-variable test; scope captures in
`references/scope_captures/`). **Any future BT boost install must keep these caps** (or a respun
layout with Cout at the IC). **Update 2026-07-08 — Death 5 (FC boost):** the overshoot mechanism is
current-scaled and system-wide. Closing `MOT_PWR_ENABLE` at full bus onto an attached VESC (RT1987
soft-start can't charge 470 µF + VESC caps → SCP burst-retry → 15 A load-dumps) killed the FC boost
from a stiff supply; 9 V batteries sag/UVLO before lethal current, which is why battery runs
survive. Plan: 16 V nominal bus, motor-node pre-charge sequencing (firmware), FC output bodge caps,
high-BW SW-ring margin check (now blocking). Full history, datapoints, and remaining steps in
**`docs/boost-bringup-debug.md`**. **Update 2026-08-06 — Capture 10 (non-destructive):** a
dual-source `G` with the VESC attached, on the old (pre-staged-bring-up) firmware, produced a
**non-converging 15.5 Hz SCP cut/retry limit cycle** (period = RT1987 tSCP_RST 64 ms): each retry
adds ~+1.6 V to the ~1–1.5 mF motor+VESC node, the VESC's brownout-band boot attempts drain it
back, and the ratchet sticks at ~5.5–7 V forever — VESC LED blinks, audible clicking, ~930
Death-5-class load dumps/min sourced by the FC boost (which carries hot-loop bodge caps —
operator correction 2026-08-11; an earlier version of this note said un-bodged). The low-voltage motor-node
pre-charge doctrine is bench-falsified with a VESC attached; VESC-attached `G` runs are blocked
until the 100 nF `D-MT-EN` CSS bodge + staged-bring-up flash land (debug log, capture-10 entry).

---

## Status & session addendum (2026-07-01, full-codebase audit round)

A full audit against the authoritative sources verified the pin map (matches the IO CSV
row-for-row), all Ag105 register values/scales/GENSTAT codes (match Tables 3/4/6/7), the
telemetry v4 arithmetic, and the sequencing guards. It also found and fixed the following —
full detail in **PLAN.md §14**:

- **VESC UART fix (safety-critical, needs bench verification).** `setup()` called
  `pinMode(RX/TX, …)` *after* `Serial1.begin()`; on Teensy 4.x that reassigns pins 0/1 from
  LPUART6 to GPIO, silently killing all VESC communication (including the `setCurrent(0)`
  safety flushes). The two lines are deleted — never call `pinMode()` on pins 0/1. Not
  host-testable (mock `pinMode` is a no-op).
- **PI live-output semantics (user-approved change to "What NOT to change" code).** Both PIs
  returned a 0.0f sentinel on sub-`sampleTime` ticks, which chopped the motor command and
  slammed the droop split to the 0.01 extreme. The integrator update stays `sampleTime`-gated;
  the output is now always computed. The power-share PI also gained anti-windup (`Ki·accum`
  clamped to ±1.0, the droop ratio's full authority). Note: during FC-charge cruise the EMS on
  the Pi commands `power_share_setpoint ≈ 1.0` (BT is off the bus), so the share error is ~0
  by design — the clamp is a defensive backstop.
- **`ag105DataValid`.** GENSTAT 0x00 = Battery Disconnect is a real Table 6 status, so raw==0
  no longer doubles as the stale marker; validity is tracked out-of-band and gates both
  `ag105IsReady()` and the `detectFaults()` GENSTAT fault.
- **State 98:** `'2'` refuses BT_BUS while FC_CHARGE is HIGH (the CSV's illegal combination);
  `'Q'` now closes FC_CHARGE/REGEN on exit so a charge path can't stay latched into Idle.
- **`LIMIT_V_BATT_MAX` left at 10.0f per user decision** (9V-battery bench testing) but it is
  UNREACHABLE — the BT divider saturates the ADC at 8.646V, so OV_BATT cannot trip (and under
  BENCH_TEST the OV checks are the only armed faults). Change to **8.5f** when 9V testing ends;
  a `TODO` comment marks it.
- **`USE_ETHERNET`** is `#ifndef`-overridable and a `#warning` fires on
  `BENCH_TEST=0 && USE_ETHERNET=0` (production faults, no Pi link, inert watchdog); the test
  Makefile suppresses it with `-DNO_ETH_WARNING`.
- Stale comments corrected (SCALE_I mA/count figure, `doState99()`/`doState3()` shutdown
  rationale vs the corrected failure analysis, `updateWheelSpeed()` unit-chain TODO).

**All 283 host-native tests pass** (278 production + 5 bench build). Build caution: running
`mingw32-make` from PowerShell can silently reuse stale binaries (the recipe's `PATH=` prefix
doesn't resolve there) — build from an MSYS2 shell, or invoke g++ directly and check the
executable timestamps.

---

## Status & session addendum (2026-07-10, robust power-share controller)

The droop power-share loop got a full model → H∞/Youla-H design → firmware round, recorded in
**`controller_design/`** (`system_model.md` = plant + parameter source of truth,
`controller_synthesis.md` = design record; both thesis-ready). User-approved exception to the
"don't change the PI controllers" rule for the power-share loop only.

- **Droop MDAC mapping bug FIXED (firmware).** The old `k_eq/r/K_sns/A_v` gain omitted the FB
  injection attenuation `RD1/Rinj = 237k/53.6k = 4.42`; with `k_eq = 0.45`, `g > 1` for all
  `r < 0.896`, so both MDACs sat clamped at full scale and the share loop saw a **zero-gain
  plant**. New mapping `g = K_DROOP/(RE_MAX·r)` with `RE_MAX = K_sns·A_v·RD1/RINJ = 2.220 Ω`,
  `K_DROOP = 0.33 Ω` (TODO(calibrate); hard bound 0.3329), ratio span
  `[DROOP_R_MIN, DROOP_R_MAX] = [0.15, 0.85]` (the old 0.01/0.99 clamps are gone from the droop
  path). `k_eq` removed.
- **Power-share PI replaced by a Youla-H robust controller** (`USE_YOULA_SHARE_CONTROLLER`,
  default 1; PI kept compiled as the 0-fallback). Runtime in `teensy_controller/share_controller.h`
  (3 DF2T biquads + trapezoidal integrator, back-calculation anti-windup, 200 Hz measured-share
  prefilter); coefficients **GENERATED** into `share_controller_coeffs.h` by
  `controller_design/synthesize_controller.py` — never hand-edit; regenerate after bench
  calibration (recalibration loop: `controller_synthesis.md` §7). Wrapper
  `youlaController_Power(setpoint, alphaRaw)` gates updates to 1 kHz and holds output between
  ticks. Design numbers: γ = 0.686, T(0) = 1 exact, all 60 plant-corner closed loops stable,
  delay margin 11.7 ms, worst-corner discrete ‖S‖∞ 1.87 (legacy PI: 26.9).
- **Python toolchain:** no MATLAB/slycot on this machine — H∞ synthesis implemented from scratch
  in `controller_design/hinf_synthesis.py` (Hamiltonian/Schur Riccati, DGKF central controller,
  self-tested against scipy; every controller a-posteriori gate-checked ‖Tzw‖∞ ≤ γ). Env:
  `uv venv` + `uv pip install numpy scipy matplotlib` (system pythons are externally managed —
  use uv, not pip/pacman). `droop_plant.m` mirrors the design for MATLAB cross-check.
- **Tests: 316 production + 6 bench pass** (`-I../controller_design` added to the Makefile; the
  C++ controller is replay-verified against generated Python reference vectors incl. a saturated
  episode).
- Remaining: bench calibration items in `system_model.md` §9 (ΔV0, τr/Td step test, k_d
  decision, TPS61288 Vref = 0.6 V verification), then regenerate coefficients.

### Full-order TPS61288 validation model (2026-07-11)

Added `controller_design/full_order_validation.md` + `tps61288_full_model.py` +
`full_order_model.m` (MATLAB mirror): an independently-built full-order small-signal model
(complete TPS61288 DS §9.2.2.5 dynamics — both channels' gm-amp compensators, Norton power
stages with RHP/ESR zeros, droop-injection FB network, bus coupling, INA sense; 11 states)
that **empirically validates** the simplified §6d design plant. Result: < 4% nominal / < 6%
envelope (432 operating points) in-band deviation, closed loop with the shipped controller
432/432 stable, worst ‖S‖∞ 1.24 (better than the simplified corner family's 1.87), step
overlay < 0.001 share. The simplified model, synthesized controller, coefficients, firmware,
and tests are ALL UNCHANGED — this is additive validation only. Re-run `tps61288_full_model.py`
last in the recalibration loop (it re-parses share_controller_coeffs.h).

---

## Status & session addendum (2026-08-03, staged bring-up round)

**The §2 `MOT_PWR_ENABLE` doctrine is SUPERSEDED** (second revision — the Death-5 low-voltage
pre-charge never functioned on the bench; captures 5–9 in `docs/boost-bringup-debug.md`).
Current doctrine: the bus (~40 µF — the 470 µF bulk is on V-MOT *behind* `MOT_PWR_ENABLE`) is
brought up ALONE (P0, MOT_PWR held LOW), the boosts regulate it (P1), regulation must hold
(P2), and only then is the motor node connected from the regulated bus via D-MT-EN's 100 nF-CSS
soft-start (P3) — implemented as the shared non-blocking `busBringupTick()` machine used by
`doState0()` and the State-98 `G` command ('X'/'Q' abort → power stage dark).
`motPwrHotPlugUnsafe()` is renamed/inverted to `motPwrConnectBlocked()`: MOT_PWR ON is allowed
ONLY at a regulated bus (a discharged node there is the sanctioned CSS-controlled connect;
dark-/mid-ramp-bus connects are refused). `FAULT_OV_BUS` is persistence-filtered (10 ms + 3
consecutive samples; decaying bring-up parks flicker the telemetry bit without latching).
`bringUpBus()` is deleted. `LIMIT_V_BUS_MAX` stays +1.5 (17.5 V) until the staged bring-up is
bench-validated, then optionally returns to +1.0. Hardware prerequisite for any P3 run: 100 nF
CSS on `D-MT-EN` (fitted on `D-BT-EN` 2026-08-03, validated capture 8). RT1987 timing at
100 nF: tD_ON 8 ms + tON ~20 ms ≈ 28 ms per connect (capture-8 measured, 1.8 % match).

---

## Status & session addendum (2026-08-11, share-sweep analysis + limit-cycle mitigation)

The seven-run share-setpoint sweep (TP0007–TP0013, trapezoid `T 6 3 1`, fw 0) validated the
Youla share loop across the full [0,1] span (steady-state bias < 10⁻³ everywhere) but found a
**17–18.5 Hz minority-channel dropout limit cycle at asymmetric in-band setpoints (0.30, 0.85)
under low total current (< ~1.2 A)** — worst case TP0010: bus collapse to 6.5 V ×64, 3.6 A
reconnect spikes, no fault latched (BENCH_TEST arms OV only). Full analysis:
`docs/share_sweep_whitepaper/` (thesis-ready PDF); event + scope capture 12 logged in
`docs/boost-bringup-debug.md` (capture 12 corrected reading: total source-feed dropout,
`D-MT-EN` ruled out, droop-blocking vs source-switch SCP still open — both downstream of the
droop loop railing).

- **CAL-1 partial (ΔV0):** bench-supply sweep at r = 0.5 → **ΔV0 = +0.05 V** (envelope
  ±0.10 V), 8× inside the ±0.40 design budget → **shipped Youla coefficients kept, no
  regeneration**. Data `controller_design/calibration/dv0_sweep_20260811.csv`; model rows
  updated (system_model.md §8/§9). Vehicle-source ΔV0 still TODO(calibrate).
- **fw v2 mitigation (pending flash; ledger `docs/firmware-versions.md`):** (a) setpoint
  governor — effective in-band setpoint clipped so commanded minority-channel current ≥
  `SHARE_MINORITY_I_MIN_A` = 0.20 A (empirical floor — light-load nonlinearity, NOT the ΔV0
  linear bound; collapses to 0.5 below 2×; out-of-band setpoints incl. 0/1 bypass — the fw v1
  cutoff path owns them); (b) `DROOP_RATIO_SLEW_PER_TICK` = 0.02 slew limit on the
  **controller path only** (one-shot paths — operator `O`, guard fallback, completion
  restore — land exact and re-seed `droopSlew_prev`, which tracks the ratio physically on the
  MDACs and deliberately survives resets); (c) `resetShareControlState()` at every profile
  start (`R`/`D`/`T`/`Y`/`W`) — runs no longer inherit the prior run's controller state
  (the sweep's cross-run contamination). Production Run-state entry deliberately does NOT
  reset (resumption, not experiment).
- **Tests: 1261 production + 95 bench pass.** New coverage: governor clip/relax/collapse/
  out-of-band-bypass, slew ceiling + walk + one-shot exactness, profile-entry reset (incl.
  slew-tracker survival).
- **Next bench:** ⭐ FIX VALIDATION re-entry of the TP0010 condition on fw v2 (scope-armed);
  quasi-static dropout-boundary mapping to refine `SHARE_MINORITY_I_MIN_A`; vehicle-source
  ΔV0. Sweep hygiene: interleave setpoint order (session drift +44 % was monotonic with run
  order); the asymmetric-setpoint safety restriction stands until the fix validates.

**Addendum (2026-08-11, later): `T` sweep extension (fw v3, pending flash).** The State-98
trapezoid command gained an optional sweep list, `T <Imax> <hold> <rate> [t,r1,...,rn]`: one
trapezoid per closed-loop share setpoint r_i (max 16, full [0,1] span), each to its own
`TPnnnn.BLG`, next run gated on the SD logger being fully idle (an early start silently loses
that run's log), separated by a t-second motor cool-off. Non-blocking `tsweepTick()`
(RUNNING → WAIT_LOG → COOLDOWN) with fire-time precondition re-checks; every operator stop
('T' during a run OR between runs, 'X', 'Q', a new 'T' line, any other profile start) cancels
the whole sweep and restores share_sp = 0.5 / powerBalanceLive = false. Sweep refused under
plot mode; the old trailing-junk tolerance after the third 'T' value is gone (whole line
rejected); `inputBuf` 32 → 96 B. Automates the TP0007–TP0013 hand-run sweep for the fw v2
FIX-VALIDATION re-sweep. **Tests: 1332 production + 95 bench pass.**

---

## Status & session addendum (2026-08-12, fw v4: validation-sweep findings hardened)

The fw v3 validation sweep (TP0014–TP0038 25-point ladder via the automated `T` sweep, plus
`W` runs WP0039/WP0040; whitepaper §6) validated the fw v2 mitigation across 0.18–0.85 —
including the original failure points 0.30 and 0.85, both now clean — but found three
boundary failures, fixed in **fw v4 (pending first flash)**:

- **`SHARE_MINORITY_I_MIN_A` 0.20 → 0.30 A.** The sweep bracketed the empirical conduction
  floor: 0.245 A commanded minority cycles (TP0016, sp 0.15, bus to 8.2 V), 0.29 A clean
  (TP0017, sp 0.18). Collapse-to-0.5 threshold rises to 0.60 A automatically.
- **Setpoint-latched channel cutoff (Option C).** The old design had a structural gap: the
  governor bypassed out-of-band setpoints while the cutoff fired on the controller OUTPUT r —
  sp 0.87 needs only r ≈ 0.84, engaged neither, and ran the cycle unmitigated at 19.5 Hz
  (TP0037); sp 0.12 cutoff-hunted at 20 Hz via integrator re-entry (TP0015). Now an
  out-of-band SETPOINT cuts the starved channel immediately (`shareSpCutFC/BT`,
  `updateShareSetpointCutoff()` first in `powerBalance()`, controller frozen while latched),
  releases only on setpoint re-entry (charged-bus + boost-enabled gated, controller reset
  seeded from `droopSlew_prev`). Review-round hardening: external re-closers
  (`doState2()`, `chargingControl()`) are latch-aware; an orphaned latch self-heals to live
  control; `assertFcChargeEnable(true)` restores FC to the bus before cutting BT (never cuts
  the last source; scoped to the share loop's own claim so the State-99 drain is unaffected);
  bring-up P0/abort and State 99 clear the latches; all four re-close/re-entry sites also
  require the channel's boost enabled (back-feed rule).
- **`FAULT_UV_BUS` reworked** — armed under BENCH_TEST too (WP0039 sagged to 7.6 V through
  89 dropout cycles with zero faults and ended in an MCU brownout; TP0016 hit 8.2 V), with
  persistence filtering mirroring the OV filter (10 ms + 3 samples + 5 ms gap guard) and
  bus-up arming instead of the old Run-state gate: arms at `V_BUS_CHARGED_THRESH` with a bus
  switch closed AND a boost enabled; disarms when the stage is commanded dark, both boosts
  are off (the routine `'F'`/`'B'` bench sequence), or the staged bring-up is active (P3's
  sanctioned sags exceed the 1.5 V arm-to-limit margin). `LIMIT_V_BUS_MIN` stays 12.0 V
  (TODO(calibrate): possible 14.0 tightening after the re-sweep).

Process: implemented via orchestrated agents (Opus implementer → Sonnet test-writer → parallel
Opus safety + Sonnet correctness reviews → fixes by the original agents → orchestrator final
review); the safety review found 4 HIGHs (S1–S4 above) that the implementer and tests missed —
all integration-surface bugs (who else writes these switches / feeds these arming terms). See
`.claude/skills/orchestrated-feature`. **Tests: 1437 production + 133 bench pass.**

---

## Status & session addendum (2026-08-12, fw v5: relay-cycle root fix + log v3)

The fw v4 validation sweep (TP0041–TP0068, WP0069–WP0073; whitepaper §6 "Second validation
sweep") validated the setpoint latch and the 0.30 A floor at every fw v3 failure point, but
found (a) a **source-commutation relay cycle** at FC-heavy setpoints — ignited by the
governor's own collapse-to-0.5 fallback in the 0.075–0.60 A window, where 0.5 commands a
split below the floor it enforces; six ERR_UV_BUS latches with bus collapse to 7–9 V;
(b) the UV window filter evaded for 1.0–1.3 s by the relay's 9/51 ms duty; (c) two MCU
brownouts (WP0072/73) with the bus in regulation — the collapsing source rail is unlogged.
**fw v5 (pending first flash; ledger row has full detail):**

- **Governor open-loop fallback (user-specified design).** powerBalance() is bimodal on the
  filtered total (closed-loop above 0.60 A, exit below 0.55 A, `SHARE_GOV_OL_HYST_A`):
  open-loop feeds the RAW setpoint forward slew-limited until closed-loop has run once
  (`shareClosedLoopRun`), then HOLDs the last applied ratio — with two exceptions (changed
  setpoint → feedforward at the new setpoint; outstanding `shareIso*` → fall through so
  applyShareRatio()'s guarded re-entry keeps evaluating). Out-of-band setpoints are never
  actuated by the feedforward (F1 — the release tick's one-live-tick guarantee). The
  collapse-to-0.5 branch is deleted. Constant floor 0.30 A kept per user decision
  (predictable for the EMS); the fraction-vs-absolute floor question stays open pending the
  two-axis sweep.
- **UV leaky-dwell filter.** `UV_BUS_DWELL_LATCH_MS` 20 / `UV_BUS_DWELL_LEAK` 0.05 /
  `UV_BUS_DWELL_DT_CAP_MS` 5 replace the `UV_BUS_PERSIST_*` window: TP0053-class relay
  latches in ≈180 ms (was 1.0–1.3 s), WP0069-class sparse transients still pass. Arming now
  requires a **matched** switch+boost pair (S7). Bus-referenced only — the source-rail UV
  fault is deferred until logged V_batt data from the next brownout sets a threshold.
- **BLG format v3 (68 B records).** `V_fc`/`V_batt`/`V_chg`/`V_rgn` logged after `I_cmd`;
  flags bit2/bit3 = closed-loop-mode/closed-loop-run (HOLD decodes as bit3 without bit2).
  `tools/decode_benchlog.py` + `benchlog_analysis` read v3 and keep v1/v2 byte-identical;
  analyzer exe rebuilt. Pi telemetry unchanged (this is the SD bench log, not UDP).
- **Process:** orchestrated round (parallel firmware + tooling implementers, independent
  test-writer, two-lens reviews). Safety review: S1 HIGH (HOLD stranding a `shareIso*`
  cutoff / doState2-orphaned claim) + S2–S9. Test-writer caught F1 (release-tick side-flip
  feedforward firing the opposite r-cutoff unslewed, mis-claimed as `shareIso*`) — a class
  both reviewers missed. Correctness review: no logic bugs; six coverage gaps closed (T1–T7).
  **Tests: 1524 production + 142 bench pass.**
- **Next bench:** flash fw v5; re-enter TP0053/TP0055 (relay region) and the WP b-ladder
  (b = 0.20/0.22) scope-armed with VBT + LM1084 input probed; two-axis floor sweep
  (Imax × setpoint) to settle fraction vs absolute; vehicle-source ΔV0 still open.

---

## Status & session addendum (2026-08-12, fw v6: cut-guard, source-rail UV, header v4)

The fw v5 validation sweep (TP0074–TP0094 all clean incl. every fw v4 relay setpoint;
WP0095–WP0101; whitepaper "Third validation sweep") found: the setpoint latch cutting BT under
2 A collapses the FC source (knee ~2.1 A, positive-feedback runaway, I_fc spikes to 6.1 A) in
~40 ms (WP0097/0101 ERR_UV_BUS); three MCU-stop truncations with V_fc < 5 V while the bus read
15.7 V (no source-rail fault exists); capture 14 resolves a sub-ms V_bt dip to ~4–5 V (leading
MCU-stop candidate, invisible at 870 Hz); all five W failures were R6-entry events (full Imax +
extreme share). **fw v6 (pending first flash; ledger row has full detail):**

- **Load-aware handoff guard** on the setpoint-latch entry: `SHARE_CUT_MAX_HANDOFF_A` = 0.50 A
  (TODO(calibrate); bracket open between 0 A clean and 1.3 A fatal). Blocked → **deferred**
  (`shareCutDeferredFC/BT`, per-tick derived + cleared in `resetShareControlState()`): the CL
  reference is clipped onto the doomed side's band edge (migration), and `applyShareRatio()`'s
  r-based cutoff is suppressed on that side (review S1 HIGH: without both, the unguarded r-cutoff
  executed the same handoff ~10–30 ms later under `shareIso*`, invisible to the external
  re-closers — TP0053-class cycling). Residual (accepted): at high load the migration may never
  clear the guard — the loop sits at the band edge running the rail-saturated dropout cycle.
- **Dwell-filtered `FAULT_UV_FC`** (armed under BENCH_TEST, block ABOVE the bus UV block so a
  same-tick double-cross names the true cause): trip `LIMIT_V_FC_MIN` 6.0 V, arm
  `V_FC_ARM_THRESH` 7.0 V (C1: arm==trip had zero margin), matched FC pair + healthy-observed
  arming (single-source bench with V_fc≈0 can never arm → no boot-lock), reuses the
  UV_BUS dwell shape (own `UV_FC_DWELL_LATCH_MS` 20 ms). V_batt UV still deferred (threshold
  blocked on the LM1084 input+output capture through a truncation).
- **Effective-setpoint slew** `share_spEffPrev` (0.02/tick on the CL reference, seeded from
  `droopSlew_prev` via `resetShareControllerCore()`): removes the OL→CL handover reference step
  (raw → floor-clipped, was 0.15→0.50 instant). Verified arithmetic: clipping the OL feedforward
  instead is inert-or-harmful (in OL mode the governor bound is always ≥ 0.5) — that's why the
  fix lives on the CL side.
- **W/Y table R5/R6/R7**: R5 ramps v 1.0→0.3, R6 (share hi-bound excursion) runs at 0.3·Imax
  (~0.6 A total, under the FC knee), R7 steps the share down at low load then ramps v back to
  1.0 (preserves R8's down-step). Latch-vs-governor ownership at R6 is b-dependent (b < 0.15
  → latch; else governor) and the "cut fires here" claim is Imax-conditional — both documented.
- **BLG header v4** (`hdr[4]=4`, record unchanged 68 B): `hdr[7]` param-valid flags, float
  Imax/Vmax at 20–23, float b at 24–27, derived from typeMask + committed profile globals (the
  fw v5 failure cluster was initially mislabelled because b was unrecoverable from the log).
  Byte 19 is fwVersion's high byte, NOT reserved (reserved = 28–31 only). Decoder/tooling
  updated (v4 parse + banner passthrough; v1–v3 byte-identical, verified vs three checked-in
  logs); analyzer exe rebuilt.
- **Process:** orchestrated round (Opus firmware + Sonnet tooling implementers, independent
  test-writer, Opus safety + Sonnet correctness reviews). Safety S1 HIGH (deferral fell through
  to the unguarded r-cutoff) + S2–S7; correctness C1 (arm margin) + E1 (deferral mechanism had
  zero tests — five added). **Tests: 1643 production + 175 bench + 79 tooling pass.**
- **Next bench:** flash fw v6; scope-armed truncation re-entry with LM1084 input AND output
  probed (settles the MCU-stop mechanism); per-channel-direction two-axis floor sweep (floor law
  is structurally wrong — 27 mV bus-vs-reference separatrix, BT-only asymmetry); bracket
  `SHARE_CUT_MAX_HANDOFF_A`; W/Y runs with b < 0.30 stay blocked until R6 rework is validated.

---

## Status & session addendum (2026-08-13, fw v7: velocity chain calibrated, 10 A ceiling)

Bench measurements landed and **fw v7 (pending first flash)** opens closed-loop velocity in
test mode. Orchestrated round (Opus implementer, independent Sonnet test-writer, parallel
Opus safety + Sonnet correctness reviews); ledger row in `docs/firmware-versions.md` has full
detail.

- **Velocity chain calibrated (2026-08-13 bench measurement).** `ENCODER_SLOTS_PER_REV`
  512 → 60 (120 counts per hand-turned flywheel revolution at the verified ×2 quadrature
  decode) and `FLYWHEEL_RADIUS_M` 0.033 → 0.0762 m (3.00 in, measured). Net `v_actual` scale
  change ×19.70 — fw ≤ 6 and fw 7 `v_act` BLG traces are NOT comparable (header `fwVersion`
  disambiguates; BLG flags bit1 now sets by default). ⚠️ **The 60 is SUPERSEDED by fw v8's
  120** — that "120" was 120 *slots*, not counts, so the ×2 decode was applied backwards; see
  the 2026-08-16 addendum. `VELOCITY_CHAIN_CALIBRATED` defaults
  **1**: State-98 `'V'`/`'D'`/`'Y'` velocity paths ship open; interlock machinery kept for
  overrides. Residual (S3, TODO(verify)): 0.0762 m implies surface/roller coupling — if the
  disc is angular-coupled to the wheel, `v_actual` over-reads 2.31× (conservative direction).
  ⚠️ **S3 CLOSED 2026-08-16:** the coupling IS surface/roller — the encoder is coupled to the
  flywheel and the flywheel's radius is the rolling radius, so 0.0762 m is correct and the 2.31×
  alternative is retired. See the 2026-08-16 addendum.
- **`MOTOR_I_CMD_MAX` 5.0 → 10.0 A (operator decision; amended 2026-08-15 → 12.0 A pre-flash,
  Castle 1406 1900KV fitted, drive-controller bring-up).** VESC-side phase-current ceiling at
  the `commandMotorCurrent()` chokepoint; also the `'A'` manual-current clamp (same constant).
  `W_IMAX_DEFAULT` (5 A), `TRAP_I_ABS_MAX` (25 A), `MANUAL_MOTOR_V_MAX` (5 m/s) deliberately
  unchanged; PI anti-windup `integMax` rescales symbolically. **S1 HIGH (open precondition):
  bus current is currently bounded NOWHERE** — the VESC Battery Current Max (≈4.2 A) / Regen
  Max (≈1.5 A) are recorded in `docs/VESC_MOTOR_INTEGRATION.md` §4 as *not set / not tracked*,
  and a BENCH_TEST flash compiles the OC faults out. Set them in VESC Tool and tick §4 before
  any velocity-path run at 10 A.
- **`'L'` plot stream is 8 fields**: `sp`/`act` renamed `share_sp`/`share_act`; `v_sp`
  (`v_setpoint`) and `v_act` (`v_actual`) appended (order: share_sp, share_act, gFC, gBT, ifc,
  ibt, v_sp, v_act; all 3 dp). Backpressure guard 80 → 110 B (worst-case line computed 109 B).
  No BLG or UDP layout change; no external parser of the plot labels exists.
- **FW_VERSION 6 → 7.** Review round: S1 HIGH (precondition wording + §4 annotations) and
  S3–S7 applied; C1 (vacuous shipped-default tests — reseeded from the macro) and C2
  (positional 8-field order assertion) applied. **Tests: 1652 production + 175 bench pass.**
- **Next bench:** set the VESC battery-current limits (S1) BEFORE any velocity run; first
  velocity runs scope-armed, `'V'` small setpoints before `'D'` (the drive cycle's coast→regen
  step is a −3.5 m/s error → −10 A onto the regen path); `motorConstant` and the motor PI
  gains are still uncalibrated against the corrected scale — treat the first `'V'`/`'D'` run
  as gain validation, and prefer `'A'`/`'T'` (velocity-PI-free) first.

---

