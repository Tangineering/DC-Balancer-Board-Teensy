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


## Rotated 2026-09-01 (fw v8–v20 encoder/BLG era + HIL tooling bring-up) — every load-bearing fact verified to survive in docs/firmware-versions.md, PLAN.md, the HIL docs, or a retained bodge record

## Status & session addendum (2026-08-16, fw v8: encoder pin move, observability, slot count)

A bench report — `v_actual` pinned at 0.000 in the `'L'` stream while the encoder was visibly
producing a signal — turned out to be an unreconciled hardware bodge, and exposed a diagnosis dead
end and a scale error on the way there. **fw v8 (pending first flash);** ledger row in
`docs/firmware-versions.md` has full detail.

- **ROOT CAUSE — the encoder pins had moved and the firmware had not.** Bodge work relocated
  `ENC_A` 2 → **14** and `ENC_B` 8 → **15**, and hardwired the optical sensors to power, deleting
  the `ENC_ENABLE` net (pin 7). The firmware was attaching `CHANGE` interrupts to two pins the
  encoder was no longer wired to, so no ISR ever fired, `encoderPos` never moved, and `v_actual`
  read exactly 0.000. `ENC_ENABLE` is removed entirely — pin 7 is now **undriven** (no `pinMode`,
  no `digitalWrite` anywhere), and pins 2/8 are free. Teensy 4.1 pins 14/15 are A0/A1 and
  Serial3 TX/RX; neither alternate function is used here and both are interrupt-capable, so the
  ISR path is otherwise unchanged. The IO CSV was updated by the operator in lockstep (pin 7 row
  marked "No longer in use"), so the CSV remains the authority and the firmware follows it
  row-for-row. **Side effect worth knowing:** with the sensors hardwired, the encoder is live from
  power-on rather than from the State-0 `initControlPeripherals()` enable write — counts now
  appear before the bus is brought up.

- **The velocity chain had exactly ONE observable**, which is why the pin move above took a bench session to find rather than a `'S'` dump. `updateWheelSpeed()` is correct, so
  `v_actual == 0.000` can only mean `encoderPos` is not moving — but nothing printed `encoderPos`
  anywhere (not the State-98 `'S'` dump, not `printSensors()`, not telemetry). The ×2 decoder in
  `doEncoderA()`/`doEncoderB()` counts only when **both** channels transition in the right ORDER,
  so three distinct hardware faults collapse to an identical silent zero: a dead channel; a
  phototransistor swing that never crosses the Teensy's V_IL/V_IH (the OPB829DZ is a bare
  phototransistor with a pull-up (4.7 kΩ as designed; **bodged to 2.2 kΩ**, operator 2026-08-16)
  — no Schmitt, so "a signal on the scope" is compatible with
  zero interrupts); and two beams not 90° apart. Added `encEdgeCountA`/`encEdgeCountB` (volatile
  u32, bumped at the top of each ISR, read by nothing but the dumps), an `--- Encoder ---` block in
  the `'S'` dump, and the same line in the IDLE `printSensors()` dump. Diagnostic-only — no control
  path reads them.
- **`ENCODER_SLOTS_PER_REV` 60 → 120** (`ENCODER_COUNTS_PER_REV` 120 → **240**). The disc was
  counted directly: it physically carries 120 slots. fw v7's 60 was a **transcription error, not a
  competing measurement** — the 2026-08-13 figure of "120" was recorded as 120 `encoderPos` *counts*
  per hand-turned revolution and divided by the ×2 decode, when it was 120 *slots* and the decode
  multiplies. The observability gap above is the tell: no build through fw v7 could have read a
  count. **`v_actual` and BLG `v_act` HALVE** for identical motion vs fw v7 (fw 7 and fw 8 traces
  are not comparable; header `fwVersion` disambiguates). Chain vs fw ≤ 6: ×9.85.
  `VELOCITY_CHAIN_CALIBRATED` stays 1 — a direct slot count is a stronger source than the figure it
  replaces. (The `FLYWHEEL_RADIUS_M` disc-coupling `TODO(verify)` was untouched by the slot count — it was closed separately, below.)
- **CONFIRMED ON HARDWARE (2026-08-16, fw v8): one hand-turned flywheel revolution reads
  `encoderPos == 240`.** First time the counter has ever been read on this board. Two
  independent sources now agree (physical slot count, firmware counter), and the same reading
  independently confirms the ×2 decode factor, that both channels are alive and in quadrature,
  and that the pins-14/15 bodge is correctly reconciled. That settles the chain's *angular* half.
- **COUPLING RESOLVED (2026-08-16, operator) — surface/roller; the linear half is settled too, so
  the velocity SCALE chain is now complete.** The encoder is coupled to the flywheel and the
  **flywheel's own radius IS the rolling radius**, so the disc rim runs at surface speed and
  `FLYWHEEL_RADIUS_M = 0.0762` is correct as shipped. The wheel-*angular*-speed alternative — which
  would have forced the tire radius and made `v_actual` over-read by 2.31× — is retired, closing the
  fw v7 S3 residual. **No constant changes; this is a determination, not a measurement.**
  **Carry forward:** `v_actual` is flywheel **surface speed**, and `v_setpoint`, the State-98
  `'V'`/`'D'`/`'Y'` commands and the BLG `v_sp`/`v_act` columns are all in those same terms. There is
  no separate vehicle-speed scale in the firmware, and the 6.86:1 reduction (9.49 retired
  2026-08-16c, fw v14 K_F correction) and differentials do not
  enter the velocity loop — it closes on the encoded body, which is the flywheel.
- **The decoder had zero test coverage** — every prior test wrote `encoderPos` by hand. 11 new
  checks drive `doEncoderA`/`doEncoderB` from raw pin levels: forward/reverse ±2 per cycle, each of
  the three silent-zero failure modes asserted to yield zero counts *and* to stay diagnosable
  through the edge counters, and an ISR-driven end-to-end path to a non-zero `v_actual`. Both slot
  and count constants are pinned literally, because 120-slot/240-count and 60-slot/120-count both
  satisfy the "counts == slots × decode" identity. **Tests: 1663 production + 175 bench pass.**
- **Next bench:** the velocity SCALE chain is complete — counts/rev, decode factor, radius and
  coupling are all settled and the decoder is hardware-confirmed. Two items remain before a velocity
  run, both unrelated to scale: set the VESC Battery Current Max / Regen Max (§4, still open from
  fw v7), and calibrate `motorConstant` + the motor PI gains — which have never been tuned against a
  working `v_actual` at all, since none of the builds that could have tuned them were reading the
  encoder. Treat the first `'V'` run as gain identification from scratch, scope-armed, and prefer
  `'A'`/`'T'` (velocity-PI-free) first. **Drive-direction consequence — read before any `'V'`/`'D'` run:**
  fw v7 OVER-read `v_actual` by 2×, which shrank the velocity error and made the PI UNDER-drive.
  Correcting it restores the true error, so **fw v8 commands up to 2× the current fw v7 would have
  at the same `v_setpoint`** — the correction is toward truth, but the change on the bench is in
  the more aggressive direction, into the still-open fw v7 precondition (VESC Battery Current
  Max / Regen Max unset, §4; OC faults compiled out under `BENCH_TEST`; `MOTOR_I_CMD_MAX` 12 A).
  `motorConstant` and the motor PI gains remain uncalibrated against any scale, so treat the first
  `'V'`/`'D'` run as gain validation, scope-armed, and prefer `'A'`/`'T'` (velocity-PI-free) first.

## Status & session addendum (2026-08-16, fw v9: 'K' manual SD logging)

**fw v9 (pending first flash):** the State-98 `'K'` command became a single-line command
(`PEND_K_PARAMS`, same convention as `T`/`Y`/`W`) so the operator can log hand-driven runs:
empty line = the old status print; **`K 1`** opens a MANUAL log (`LOG_TYPE_MANUAL` 0x08, new
`ML####.BLG` prefix in the shared session counter, v4 header param flags 0 — no record/trailer
format change, no UDP change); **`K 0`** closes it via `logRequestClose(LOG_CLOSE_STOP)`.
Ownership is tracked by `logManualActive` (set only on a successful open; cleared in
`logFinishFile()` and `logDrainTick()`'s no-card clear). `K 1` is refused during the staged
bring-up (parse-time guard — the open path's directory scan + 32 MB preAllocate must not stall
the bring-up machine; the status form stays out of the keypress lockout), while any profile,
**`T` sweep**, or plot-arm is pending, and while a log is open/closing; `K 0` is refused on a
profile-owned log. `X`/`Q`/fault close a manual log through the normal drain; a profile start
over a live manual log force-finishes it (existing double-open branch). `logSampleTick()` is
unchanged — manual runs sample at 1 kHz with phase bytes `LOG_PHASE_NONE`.

Orchestrated round (Opus implementer, independent Sonnet test-writer, parallel Opus safety +
Sonnet correctness reviews). Safety S1 (MED): the `K 1` guard originally missed `tsweepActive` —
an ML open in a sweep's between-runs window would have silently cost the next sweep run its log
(the exact loss the sweep's WAIT_LOG gate exists to prevent); fixed with the sweep term.
Safety S2 / implementer-flagged: `printSdStatus()` now prints a "(manual — K 0 stops)" /
"(profile-owned)" ownership marker while a log runs. Correctness review: no logic bugs; three
coverage gaps closed (drain-window `K 1`, double `K 0`, plot-mode prompt). Decoder impact:
docstring-only (`profile_type` bit 3 = MANUAL; the tooling passes the bitmask through raw).
**Tests: 1777 production + 175 bench pass.** Ledger row in `docs/firmware-versions.md`;
command/table docs in PLAN.md §9 updated.

---

## Status & session addendum (2026-08-16, fw v10: Youla-H drive controller)

The drive-channel calibration campaign closed (motor ID, m_eff, b_eff three-way triangulated at
0.32 N·s/m, thermal Coulomb F_c = 1.2 ± 0.25 N, τ_v measured 1.0 ms, Td_v decided 2 ms — record:
`controller_design_MIMO/calibration/motor_id_20260815.md`) and two orchestrated rounds followed.
**fw v10 (pending first flash);** ledger row in `docs/firmware-versions.md` has full detail.

- **Round A — model + re-synthesis.** `plant_mimo.py` carries the measured constants (k_t
  4.266e-3, R_m 22.6 mΩ, m_eff 3.5 kg, r_t 0.0762 m flywheel rolling radius, b_eff 0.32 with
  `pole_factor ∈ {0.5, 3}`, F_c 1.2 N; the aero/C_rr/b_motor composite is RETIRED). Nominal
  plant: G22(0) = 1.411 (m/s)/A, pole −0.0914 rad/s, model-derived i_m0 = 4.07 A (0.6 % below
  the measured band's lower edge — a factor-of-4 correction attributed to the unmeasured η_dt,
  not closure). `synthesize_drive_siso.py` re-ran at **I_CLAMP = 12.0** (the fw MOTOR_I_CMD_MAX):
  chosen rung WC=55/Wu(0.15,300,7.5) → PM 49.6°, DM 54.2 ms, crossover 16.0 rad/s, worst-corner
  ‖S‖∞ 2.15 cont / 2.26 disc, all 24 corners stable, 22/22 gates. Replay reference vectors
  (`figures/drive_siso_replay.csv`) are generated from the FLOAT32-ROUNDED header coefficients at
  %.17e (review V1: double-generated vectors drift 1.7e-2 A through the near-unity mode);
  independent validator `validate_drive_siso.py` passes 15/16 — the one "failure" is the
  documented measurement that a float32 STATE recursion diverges ~1.4e-2 A (why the firmware
  state is double). **The MIMO-study artifacts are frozen on the retired plant and their pipeline
  currently fails its own gates** (compare_controllers clamp assert, synthesize_mimo 54/2,
  compute_Su DRIFT, mimo_crosscheck.m false-green) — bannered in the README/model doc/`.m`;
  regeneration is a future synthesis round, not a re-run.
- **Round B — firmware.** New `teensy_controller/drive_controller.h`: Hanus self-conditioned
  5-state realization (clamped u drives the state update — full-state anti-windup; integrator-only
  back-calculation measurably fails here, R's LF gain is 745.5 A/(m/s)), **double state vector**,
  float coefficients GENERATED into `teensy_controller/drive_controller_coeffs.h` by
  `synthesize_drive_siso.py` (one emitter, two copies with the study header — never hand-edit).
  `motorControl()` under `USE_YOULA_DRIVE_CONTROLLER` (default 1; PI verbatim at 0) sends the
  controller's AMPS straight through `commandMotorCurrent()` — no motorConstant division on this
  path (motorConstant is dead on the shipped build). Wrapper `youlaController_Drive()` gates the
  recursion to DRIVE_CTRL_TS_US − 200 µs (beat tolerance vs the equal-period rl_motor gate) and
  holds output between ticks. `resetDriveControlState()` at Idle→Run (which now also ZEROES
  v_setpoint — a stale Pi setpoint would rail the loop in 20–40 ms), the `'V'` entry edge only
  (a mid-run `V` is a setpoint step, deliberately not a reset), and `haltMotorOutput()` (covers
  all profile starts and every stop/`Q`/`X`/fault path). `constexpr` MOTOR_I_CMD_MAX +
  `static_assert` pins the clamp pairing (changing 12 A now breaks the build until re-synthesis).
  Safety review: no HIGHs; 1 MED (stale-setpoint rail at Run entry — fixed) + 3 LOWs applied.
  Correctness review: no logic bugs; double-state compile tripwire, v_setpoint-zeroing assert,
  and gate-edge test added; "velocity PI" wording swept (fallback/history references kept).
- **Tests: 2716 production + 175 bench pass** (replay-verified against the generated vectors,
  saturated episode included, via new `controller_design_MIMO/drive_replay_vectors.h`;
  `-I../controller_design_MIMO` added to the test Makefile).
- **Next bench (read before any velocity run):** the fw v7 S1 precondition is still open and
  sharper now — set the VESC Battery Current Max (≈4.2 A) / Regen Max (≈1.5 A) and tick
  `docs/VESC_MOTOR_INTEGRATION.md` §4 BEFORE any `'V'`/`'D'`/`'Y'` run; OC faults are compiled
  out under BENCH_TEST and the new loop rails at ±12 A within ~30 ms for |e| > ~16 mm/s. First
  `'V'` run is the synthesis validation: compare the small-signal step against
  `figures/drive_siso_step.csv`, scope-armed, small setpoints first.

---

## Status & session addendum (2026-08-16, fw v11: BLG v5 drive-controller observability)

Pre-velocity-run round (operator request): the SD bench log gains the drive controller's
internals so the Hanus conditioning is verifiable on hardware. **fw v11 (pending first flash —
fw v10 was never flashed, so the first flash carries both);** ledger row has full detail.

- **BLG RECORD FORMAT v5 (76 B, hdr[4] = 5).** Two float32 APPENDED (all v1–v4 offsets
  unchanged): `u_unsat` at 68 (drive controller PRE-clamp output, held between 500 Hz ticks —
  1 kHz logging duplicates it in pairs by design) and `drive_x0` at 72 (the exact-integrator
  state x[0]). Flags gain bit4 (command from the Youla DRIVE controller) and bit5 (share loop
  is the Youla build) so records are law-self-identifying; under a `USE_YOULA_DRIVE_CONTROLLER=0`
  flash the fields carry the PI's pre-clamp command and `pi_motor_accum` (A/B-comparable).
  During saturation, u_unsat hugging the rail = conditioning working; diverging beyond it =
  windup. Header layout otherwise v4-identical; trailer block grows with the record; UDP
  telemetry (v4/58 B) and the 'L' stream unchanged. Ring math re-verified at 76 B (6 rec/chunk,
  6.0× catch-up, ~7.4 min preallocation; no buffer grew).
- **Tooling:** `decode_benchlog.py` parses v5 (v1–v4 byte-identical, verified vs three
  checked-in logs); `benchlog_analysis` gains a `drive_controller_conditioning` figure
  (u_unsat vs I_cmd, ±12 A rails, saturated intervals shaded, x[0] subplot; skips pre-v5 logs);
  analyzer exe rebuilt; `make_test_blg.py --v5` defaults bits 4/5 ON.
- **Review round:** no firmware defects. D3: `setManualMotorCurrent()` ('A') now resets the
  drive controller (unconditional — 'A' never steps the loop, so there is no operating point to
  preserve; prevents a stale u_unsat/x0 trace with bit4 set in K-logged 'A' runs). D1/D2 (doc):
  **the operator set the VESC limits 2026-08-16 — Battery Current Max 6.0 A fwd / 1.5 A regen
  — closing the fw v7 S1 precondition**, but 6.0 A is 1.43× the §12.4-derived ≈4.2 A allowance
  and above its scope-gated 5.4 A conditional ceiling; §12.4 is annotated, and re-deriving it
  against 6.0 A (or lowering the setting) is the outstanding action before a vehicle run. Bench
  note: 6.0 A split evenly = exactly LIMIT_I_BT_MAX 3.0 A/channel, and FC-heavy setpoints
  exceed LIMIT_I_FC_MAX 1.4 A — with OC faults compiled out under BENCH_TEST, nothing in
  firmware catches either.
- **Tests: 2747 production + 175 bench pass.** New coverage: record size/offsets (append-only
  guarantee pinned via offsetof), hdr v5, bit4/bit5, pre-clamp value plumbing (saturating +
  unclamped), 500 Hz held-pair semantics, reset-to-zero; ring-wrap chunk math re-derived at 6
  records/chunk.
- **Next bench:** flash fw v11; first `'V'` run is the synthesis validation — small setpoints,
  scope-armed, compare against `figures/drive_siso_step.csv`, and read the new conditioning
  figure after each run.

---

## Status & session addendum (2026-08-16, fw v12: edge-period estimator + re-synthesis)

The first closed-loop `'V'` runs (ML0136–139, fw v11, steps 0.1/0.5/1.0 m/s) all limit-cycled
rail-to-rail at 2.3–2.6 Hz — the 16 rad/s design crossover. Four-agent log analysis converged on
the root cause: `updateWheelSpeed()`'s boxcar advanced once per main-loop tick, realizing a
~113 ms window (~56 ms group delay = 52–58° at crossover > the whole 49.6° PM; 0.0177 m/s
quantization), and the estimator was absent from the synthesis plant. The runs DID validate the
Hanus anti-windup on hardware (~150 rail episodes, u_unsat hugging the rail, clean releases) and
the DC friction model. **fw v12 (pending first flash — carries v10+v11+v12):**

- **Edge-period estimator (operator-specified).** Period measured same-edge-type (A-rising to
  A-rising) over one full slot pitch (2π·0.0762/120 = 3.990 mm) to cancel optical-sensor
  asymmetry; `ENC_PERIOD_AVG_N` = 2 period averaging (configurable); direction from the
  quadrature decode (Δ`encoderPos` = ±2 between A-risings; flip → ring invalidate); glitch
  drop < 200 µs without advancing the base; stale timeout max(1.5·lastPeriod, 150 ms) → 0;
  zero-speed floor ≈ 0.027 m/s; `PRIMASK` save/restore snapshots. **Safety-review MED-HIGH
  fixed: ring invalidation at speed HOLDS the last valid reading** (bounded by the stale
  timeout) instead of emitting a full-scale v=0 step into the 545 A/(m/s) controller — v_actual
  zeroes on exactly three events (boot, `encoderVelReset()`, stale timeout). Delay now
  (N+1)·pitch/(2v): ~3 ms at 2 m/s (was 56), ~12 ms at 0.5 m/s; quantization timer-limited.
  `'S'` dump gains a periods/dir line (fw v8 observability lesson).
- **Re-synthesis with the estimator in the plant** (separate Pade2 on the measured output only —
  the §4.4 coupling taps the physical speed; G22 4→6 states; corners × v0 ∈ {0.5, 2, 5} = 72).
  Bench gain datapoints refit (the 113 ms boxcar's ~93 ms fill dead-time explained the
  0.158-vs-0.198 (m/s²)/A spread; both converge to 0.186–0.204): **K_v recentred 1.25, corners
  {0.85, 1.25, 1.85}** (span narrows ×4.0 → ×2.2, which pays for the delay). Chosen rung WC=60 /
  Wu(0.25, 300, 12.5): **crossover 15.98 rad/s (unchanged), PM 51.9°, DM 56.7 ms, worst-corner
  ‖S‖∞ 2.42 cont / 2.52 disc, estimator phase at crossover 2.74° (was 51°), 0.5 m/s corner PM
  43.7°**; new gates pin both. **Validity floor: the design is gate-checked for v ≥ 0.5 m/s
  only** — below it the estimator is a deadband relay (needs ~3 edges/12 mm before a first
  reading) and low-setpoint steps are expected to limit-cycle; the ML0136/38 0.1 m/s runs are
  NOT covered by this fix. ⚠️ A v12 trace vs a v11 trace is two different control laws
  (K_v, weights, KI 73.6→53.4 all changed), not just two estimators.
- **Replay-vector hardening (test round caught it):** the regen vectors were knife-edged
  (float64 trajectory replayed open-loop through the float32 controller chattered ON the clamp
  boundary). Now generated closed-loop through the shipped float32 coefficients with
  stimulus-truncation gates; consumer tolerances embedded in the artifacts (small ≤1e-4 A;
  regen ~50 mA — the controller genuinely dithers across the ±12 A boundary during hard regen,
  82 clamp transitions in the design sim; tighter gates fail correct implementations).
  `tools/gen_drive_replay_header.py` is now a permanent tool (regenerate
  `drive_replay_vectors.h` whenever the synthesis regenerates the CSV).
- **Open items:** `m_eff` CHALLENGED — ramps vs cruise-hold gain datapoints contradict by ×2 in
  opposite directions and m_eff ≈ 1.6–2.0 kg (vs the operator's 3.5) is the single constant
  closing both, consistent with the coast-down residual; top bench item (re-measure J or a
  timestamped coast-down). `validate_mimo_model.py` G1.5/G1.6 now fail (truth model lacks the
  estimator + recentred K_v) — deferred to the MIMO regeneration round; staleness bannered.
- **Tests: 2785 production + 175 bench pass** (11 new estimator cases incl. the hold/timeout
  semantics and an ISR-driven end-to-end; C++ regen replay lands at 21 mA worst).
- **Next bench:** flash; first `'V'` at **≥ 0.5 m/s** (1–2 m/s preferred), scope-armed, overlay
  vs `figures/drive_siso_step.csv`, read the conditioning figure; expect clamp dither during
  hard regen (not a fault). Re-derive VESC doc §12.4 against the set 6.0 A before a vehicle run.

## Status & session addendum (2026-08-16, fw v14: K_F force-axis correction)

The `K_F` investigation the fw v13 freeze was waiting on has reported. The drive channel's
force axis was wrong on two independent counts; correcting both reconciles every
drive-channel measurement on record and **confirms `m_eff` = 3.5 kg**. **fw v14 (pending
first flash; the first flash now carries v10-v14);** ledger row in
`docs/firmware-versions.md` has full detail.

- **ROOT CAUSE - the force chain carried the wrong gear ratio AND the wrong radius.**
  `PHI` **9.49 -> 6.86**: the 9.49 was a STOCK-gearing web figure, and the fitted pinion is
  29T against a counted 70T spur. Triple-confirmed - Traxxas 4-Tec manual p.24 formula
  (spur/pinion)x2.85 gives 6.88, the manual's chart cell (29, 70) gives 6.87, operator
  rolling counts give 2.84-2.86 for the shaft/tire stage. The FORCE radius
  **0.0762 -> 0.033 m**: the rig is motor -> gearbox -> **tire** -> roller -> **flywheel**,
  so torque reaches the road through the tire while the encoder and the inertia belong to
  the flywheel. `plant_mimo.py` now splits the roles explicitly (`R_TIRE` for force/omega,
  `R_FLY` for encoder pitch and `J/r^2`). Net **`K_F` 0.4516 -> 0.7538 N/A, x1.669**.
- **The VESC-Tool RPM display reads x2 the true mechanical speed** (pole/pole-pair display
  convention, 4-pole motor) - which is why an operator flywheel-vs-motor spin count of ~32
  appeared to corroborate a larger reduction against the chain-predicted 6.86x(0.0762/0.033)
  = 15.8. **Display artifact only:** the lambda-vs-KV cross-check (1.451 predicted vs 1.422
  measured mWb at p = 2) is independent of it, so **`k_t` = 4.266e-3 N*m/A is untouched.**
  Halve anything read off that display before comparing it to a mechanical count.
- **The drag law rescales; `i_m0` does not.** `B_EFF_NOM` 0.32 -> **0.534 N*s/m**,
  `F_COULOMB` 1.2 -> **2.00 +- 0.42 N** (cold 2.19 / warm 1.75-1.84) - the raw data are hold
  CURRENTS and are unchanged; only their force conversion moved. `i_m0` = 4.07 A is
  therefore INVARIANT (drag is current-referenced), and its ~9 % shortfall against the
  measured 4.5 +- 0.4 A hold stands, still attributed to the unmeasured `eta_dt` = 0.85.
  Drive pole -0.0914 -> **-0.1526 rad/s**; `omega0` 249.1 -> **415.8 rad/s**.
- **Every contradiction on record closes, and `m_eff` = 3.5 kg is CONFIRMED.** The
  ramp-vs-cruise factor-of-2 dissolves (ramps x1.109-x1.213 vs cruise x0.905) for a stated
  reason: the cruise-implied gain IS the drag law and rescales with `K_F`, while the
  ramp-implied gain is `m_eff*a/I` and does not - one moves, the other does not. The
  coast-down closes too (ladder-predicted 0.37-0.45 -> x1.669 -> **0.62-0.75 m/s^2** vs
  observed 0.62). The 1.6-2.4 kg mass inferences were `F/a` fits reading `F = K_F*I`, so an
  understated `K_F` read back as an understated mass in exactly the observed ratio; x1.669
  moves all of them onto ~3.5 kg. **The operator's fw v13 ruling is confirmed and the
  investigation is RESOLVED** - the model and coefficients are no longer frozen.
  `eta_dt` stays 0.85 `TODO(calibrate)`: the ramp residual is now only x1.11-1.21, no longer
  the unphysical `eta_dt >= 1.0` that the retired axis implied.
- **`K_v` re-centred 1.25 -> 1.00, corners {0.85, 1.25, 1.85} -> {0.75, 1.00, 1.35}** (span
  x2.2 -> x1.8) - the axis no longer has to straddle a contradiction. Corners bracket both
  evidence bands with margin (0.75 is 10 % below the cruise band's 0.831; 1.35 is 11 % above
  the ramp band's 1.213). `G22(0)` = 1.4116 (m/s)/A; effective `K_F*K_v` 0.5645 -> 0.7538
  (**plant gain x1.34**).
- **Re-synthesis needed NO weight change.** The shipped rung (WC = 60, Wu(0.25, 300, 12.5))
  passes every gate on the corrected plant: crossover 17.52 rad/s, PM 50.8 deg, DM 50.6 ms,
  worst-corner ||S||inf 2.427 cont / 2.535 disc over 72 corners, 0 unstable, PM 41.8 deg at
  the 0.5 m/s validity floor. `validate_drive_siso.py` 15/16 (the one failure is the
  documented float32-STATE divergence). The ladder table in `synthesize_drive_siso.py` was
  NOT re-run and every non-chosen row is now indicative only - bannered in place.
- **Firmware effect is coefficient regeneration ONLY.** `FW_VERSION` 13 -> 14, the
  regenerated `drive_controller_coeffs.h`, and two stale comments quoting the old ratio.
  No pin, sequencing, fault, telemetry, BLG-format or command change; no control code
  edited. ⚠️ **A v14 `'V'` trace is a DIFFERENT CONTROL LAW from a v13 one** (new
  coefficients, new K_I, x1.34 plant gain). The **velocity chain is untouched** -
  `FLYWHEEL_RADIUS_M` 0.0762 m, 240 counts/rev and the edge-period estimator are all
  unchanged - so `v_act` traces ARE comparable across v13/v14.
- **Next bench:** unchanged from fw v13 - solder the Schmitt (74HC14 at 3.3 V) and verify
  the edge counter at 240/rev BEFORE any velocity run; then flash and run `'V'` at
  1-2 m/s scope-armed, overlaying against the regenerated `figures/drive_siso_step.csv`.
  Two model items remain open: `eta_dt` = 0.85 (now the largest surviving drive unknown),
  and **no-slip at the tire/roller contact**, which the corrected force chain makes an
  explicit assumption rather than an implicit one.

---

## Status & session addendum (2026-08-16, fw v13: estimator hardening + v_sp zero-cutoff)

The fw v12 fix-validation runs (ML0140-144 'V' steps 0.5-3 m/s + ML0145 forward stepladder)
showed the boxcar limit cycle gone (edge-period estimator confirmed live, timer-fine) but
exposed encoder EDGE CORRUPTION as the remaining sensor defect: spurious A-edges (v reads
1.33x/2x high - 100% contamination at low speed, ML0145) AND missed A-edges (2/3, 1/2
families, ML0143), plus blind holds under direction dither (ML0140: 120-560 ms; the stale
timeout, keyed to edge age, never fired) and a v_sp=0 relay (ML0144: closing the loop below
its own floor = 90% rail bang-bang; the same run at 1.0 m/s settled at 1.7% overshoot /
0.44 s rev-averaged). Scope capture 15: full-swing signals, ~0.5-1 ms analog edge ramps, no
hysteresis - root physical cause; a Schmitt bodge (SN74HC14N; check the pull-up rail - 2.2 k
bodged, possibly to 5 V, Teensy pins NOT 5 V tolerant) is the hardware fix. Direction
comparison: ML0135/TP reverse-direction data VALID (fwd vs rev within +-7%, sign-alternating
deviations). m_eff: operator RULING - 3.5 kg is a floor (flywheel J measured); the
apparent-mass discrepancy is assigned to K_F, under investigation in a separate session;
model/coefficients FROZEN meanwhile. fw v13 (pending flash; first flash carries v10-v13) -
the firmware backstop for the Schmitt:

- Adaptive period plausibility (ISR): EWMA reference (alpha=1/4 shifts); < 0.625x ref
  rejected without advancing the base (spurious halves merge); 1.5-3.5x ref reinterpreted as
  k=2/3 pitches (ring stores period/k); armed ONLY when ref < ENC_ADAPT_MAX_REF_US 13 ms
  (v > 0.307 m/s - safety review S1/S2: below that, genuine rail accel/decel legitimately
  breaks the ratio gates, and the k-branch has self-reinforcing poisoned fixed points at
  ref=T/2,T/3 reachable through rail decel at ~0.29 m/s; the 0.04-0.30 m/s band is
  UNMITIGATED by firmware and belongs to the Schmitt). Poison backstop:
  ENC_KBRANCH_RUN_MAX 4 consecutive k>1 acceptances -> full estimator reset.
- Reading-age stale bound: holds bounded by max(K x last reading sum, 100 ms) on the last
  ACCEPTED READING's age (not edge age) - fires even with edges arriving. Zero-speed floor
  now 0.0399 m/s. Sign embargo (S3): a cnt<2 reading whose sign differs from the last
  published holds (and does NOT refresh the reading age), publishing at cnt=2 - dither ages
  out to 0 instead of chattering single-pitch readings into the 545 A/(m/s) controller.
- Partial-ring live readings: cnt>=1 same-sign readings publish immediately (fast warm-up
  and flip recovery); reversal is data, not invalidation.
- V_SP_ZERO_THRESH 0.05 m/s zero-cutoff in motorControl() (both build paths): below it,
  0 A + entry-edge controller reset, no loop stepping (Idle-consistent; drive-cycle/combined
  standstill segments now COAST at 0 A; 'Y' parse warns if Vmax*0.2 < the threshold). PI
  fallback: pi_motor_lastMicros refreshes every cutoff tick (S4 - exit no longer integrates
  the whole cutoff window). static_asserts pin the floor ordering and LO_FRAC.
- Tests: 2858 production + 175 bench pass (adaptive-filter brackets, k-reinterpretation,
  poison guard, embargo ageing, arm-threshold bracket, zero-cutoff, ML0140 blind-hold
  regression). No coefficient/model/telemetry/BLG change.
- Next bench: solder the Schmitt (74HC14 at 3.3 V; move pull-ups to 3.3 V if they are on
  5 V), verify with a constant-speed edge-counter check (240/rev) and a repeat 'A' ladder
  (rungs gone), THEN flash fw v13 and re-run 'V' at 1-2 m/s scope-armed incl. a deliberate
  decel through 0.3 m/s (S1 doubling-signature check). K_F investigation results return here
  for the model/coefficient round.

---

## Status & session addendum (2026-08-17, fw v14 first-flash log round: ML0146-151 + YP0152)

First logs from the fw v14 flash (the flash carrying v10-v14), analyzed by a seven-agent
fan-out (one per log). No firmware change came out of this round. Analysis outputs live in
`logs/ML0146` ... `logs/YP0152`; runs: 'V' steps at 0.5/0.75/1.0/1.5/2.0 m/s (ML0146-150,
manual 'K' logs), a 0->2.66->0 m/s stepladder (ML0151, 56 s), and the first 'Y' combined
profile on the Youla drive controller (YP0152, Vmax 2.0, b 0.30, natural completion).
All decodes clean: zero drops, zero missed periods, zero faults.

- **K_F VALIDATED ON HARDWARE; the ML0141 gain excess is CLOSED.** Rail-acceleration check
  (ML0151, 0.7 s continuous +12 A): a_meas/a_model = 0.968. Hold currents at every cruise
  level 0.5-2.66 m/s across all seven logs sit at 0.89-0.92x the drag-law prediction
  i(v) = (2.00 + 0.534 v)/0.7538 (post-drag-event branch 1.10-1.15x; both inside the
  F_c = 2.00 +/- 0.42 N band). Incremental dv/dI at clean ladder transitions: 0.96-1.05x
  G22(0). The old 1.8-2.7x excess reproduces nowhere. The consistent ~10 % hold-current
  shortfall matches the still-open eta_dt = 0.85 in direction and rough scale.
- **The controller works.** SS error <= 2 mm/s at every level (std ~0.025-0.03 m/s). Hanus
  conditioning verified across ~90 saturation episodes (worst sustained u_unsat excursion
  +3.4 A past the rail, clean release every time, no windup). Zero-cutoff + controller
  reset verified on hardware in YP0152 (3951 coast ticks, I_cmd == 0 and x0 == 0
  throughout, clean re-entry). The 2.3-2.6 Hz boxcar limit cycle is confirmed gone
  (< 1 % band energy everywhere). Rise 0.08-0.10 s (1.3-1.6x faster than small-signal
  design) with 13-26 % overshoot vs 4.8 % design - plant slightly stiffer than nominal,
  consistent with the 0.89 hold ratio; watch, no action.
- **NEW: mechanical drag step-change, ML0151 t~27.5 s** (during the 2.0->2.5 step): real
  speed collapse 2.55->1.30 m/s, 688 ms full-rail recovery, and afterwards drag is
  PERMANENTLY ~2.2x higher (bus input at 2.0 m/s: 4.30 -> 9.44 W). Encoder edge rates match
  prediction on both sides, so it is physical (tire/roller contact or preload), not sensor.
  Inspect the rig before the next run; any drag-law refit must treat the two halves
  separately.
- **NEW: VESC ~428 ms dead window after hard regen->drive reversal** (ML0151 t=42.0 s):
  I_cmd +11.4 A commanded, delivered current < 50 mA, car still decelerating - the entire
  cause of the 2.66->2.0 step's 87 % undershoot (plus four 23-26 ms instances at low
  current). Not a firmware bug; characterize before any vehicle run.
- **Encoder verdict unchanged, sharpened.** Above 0.307 m/s: zero rung-family corruption in
  ~130k samples - the fw v13 adaptive filter holds; deliberate decels through 0.3 m/s
  (ML0150/151) were clean, no S1 doubling signature. Below ~0.4 m/s (YP0152 regions 13/14):
  sign reversals to -1.0 m/s driving full +/-12 A rails, 32 % saturation dwell. Residual
  defect at cruise: I_cmd chatter 3.5-5.6 Hz, up to ~11-13 A pk-pk while v_act ripples only
  ~0.03 m/s - estimator edge-jitter amplified by the ~545 A/(m/s) LF gain; current-side
  only, not a velocity limit cycle. The Schmitt (74HC14 at 3.3 V) remains the root fix and
  is now also the prerequisite for judging the chatter.
- **YP0152 was NOT a cross-coupling test:** total source current (median 0.13 A) never
  crossed the 0.60 A closed-loop entry gate, so the share loop ran open-loop feedforward
  for 99.8 % of the run (ML0146-151 had gFC = gBT = 0 outright). Repeat 'Y' with a real bus
  load >= 0.6 A (ideally >= 1.5 A) before drawing coupling conclusions. Bus health: V_bus
  15.87-15.95 V the whole profile - which is nominal, see below.
- **STALE-CONSTANT SWEEP: bus nominal is 16.0 V, not 17.5 V.** The round's one false alarm
  ("V_bus 1.6 V below nominal") traced to this file's own Section 6, which still taught the
  pre-retune 17.5 V / LIMIT_V_BUS_MAX 18.5f pair. The firmware has been right since the
  2026-07-11 RD1 = 215k FB retune (V_BUS_NOMINAL 16.0f, V0 = 15.91 V no-load,
  LIMIT_V_BUS_MAX = nominal + 1.5 = 17.5 V). Fixed in lockstep: CLAUDE.md Section 6,
  AGENTS.md, README.md (both 18.5 V references), PLAN.md (Section 6a + resolved-questions
  table), docs/modeling/bond-graph.md, and the two reconcile notes in
  papers/Droop_Control/sections/04_board_design.tex (now RESOLVED at 16.0 V). Historical
  bring-up narratives keep their as-was values. Do not reintroduce 17.5 V as nominal.
- **Next bench, in order:** (1) inspect the tire/roller contact (the ML0151 drag event
  moved the operating point mid-session); (2) solder the Schmitt; (3) characterize the VESC
  reversal dead window ('W'/'T' reversal test); (4) repeat 'Y' with a real bus load.
  Housekeeping: `.venv_benchlog` is missing pandas (agents worked around it) - repair
  before the next log round.

---

## Status & session addendum (2026-08-17, fw v15: dpos-based pitch count)

Operator-diagnosed, code-confirmed: the fw v13 adaptive period filter has an ABSORBING
slow-reading poison basin at ref ~ 2T. Real edges at T fail the 0.625 low-side gate
(T < 1.25T), are rejected without advancing the base (correct for genuine spurious edges),
and the next edge measures 2T -> ratio 1.0 -> accepted as ONE pitch, re-anchoring the EWMA
at 2T forever. v_actual reads exactly HALF; the drive controller doubles the real speed
("sudden 2x speed-up", bench 2026-08-17, no log). The ENC_KBRANCH_RUN_MAX tripwire was
structurally blind to it (every acceptance is k == 1, resetting the counter — it guarded
only the mirror ref ~ T/2 fast basin), and a tripwire reset taken mid-miss-burst could
SEED the basin (re-seed has no ratio gating). The ML0151 t~27.5 s "drag step-change" is a
CANDIDATE instance (v_act "collapse" ratio 2.55/1.30 = 1.96; the round's edge-rate
exoneration was circular — it predicted edge rate from v_act itself), though not settled:
bus input power genuinely changed, which pure re-scaling does not explain. **fw v15
(pending first flash; the first flash carries v10-v15):**

- **Pitch count is now a decoder MEASUREMENT, not a ratio inference.** In the accepted-
  interval path, pitches = nearest-integer(|dpos|/2) from dpos = encoderPos −
  encPosAtLastEdge ((|dpos|+1)>>1, floor 1, UNCAPPED, shift/add only). Sound because a
  rejected edge advances neither the time base nor the position reference, so dpos
  accumulates across rejections in lockstep with the period. Needs no reference and no
  speed arming (runs during seeding and below ENC_ADAPT_MAX_REF_US — the S1/S2 arming
  rationale is ratio ambiguity, which a count does not have). Both poison basins become
  non-stable: at ref~2T the merged 2T interval carries |dpos| = 4 -> stores/feeds T ->
  ref walks back; at ref~T/2 the true period passes the gate as one pitch.
- **Retired:** the ratio k = 2/3 branch, ENC_PERIOD_MAX_MULT, and the ENC_KBRANCH_RUN_MAX
  tripwire (encKBranchRun/encRefPoisonPending + the updateWheelSpeed() consumer) — under
  the new mechanism a run-length reset would fire during basin RECOVERY (consecutive
  pitches == 2 acceptances) and re-seed from the corrupted stream. **Kept:** the 0.625
  low-side gate + no-base-advance merge (and its speed arming, now governing only that
  gate), ENC_PERIOD_MIN_US, EWMA, ring, direction handling, dpos == 0 invalidation, and
  the ENTIRE reader side — v_act traces stay comparable with fw v12-v14.
- **Review round (two-lens, no HIGH/MED, 3 LOWs):** S1 (accepted, strengthened) — a
  PER-PITCH absolute floor: after the pitch division, per-pitch < ENC_PERIOD_MIN_US
  (200 us, incl. the integer-zero case) is dropped like a glitch (no store, no EWMA, no
  base advance). This is also the principled fast-direction backstop (per-pitch >= 200 us
  bounds indicated speed at ~20 m/s), which is why S2's arbitrary count cap was REJECTED.
  S3 (doc-only): the dpos == 0 branch still feeds the EWMA the raw elapsed interval,
  biasing ref high under dither — conservative direction only. Orchestrator liveness
  trace: persistent dpos corruption dropping every interval starves readings -> the fw v13
  reading-age bound fires within 100 ms -> v = 0 + clean reset. Bounded, safe direction.
- **Known residual (documented in the ISR):** a slot entirely unseen by channel A loses
  its decoder counts too (Afirst*/Bfirst* handshake), so |dpos|/2 under-reads by one and
  the interval stores SLOW — safe direction, EWMA-absorbed; the ratio cross-check that
  could catch it is exactly the ambiguous mechanism that created the basins, so it is
  deliberately not reinstated. The 0.04-0.30 m/s band and the un-Schmitted OPB829DZ edge
  corruption still belong to the 74HC14 hardware fix — v15 is a scale-stability fix, not
  a reason to defer the Schmitt.
- **Diagnostics:** encLastPitches/encMultiPitchCount (volatile, ISR-written, reset by
  encoderVelReset()) added to the State-98 'S' dump alongside ref (fw v8 observability
  lesson). No control path reads them. No pin/sequencing/fault/UDP/BLG/coefficient change.
- **Tests: 2913 production + 175 bench pass** (rebuilt from source, both builds). New:
  the 2T-basin escape regression (walks the estimator into the poisoned state, asserts it
  cannot stay locked), T/2-basin equivalent, uncapped multi-pitch counting (2/3/5),
  rounding (|dpos| = 1, 3), unconditional application (seeding + gate-dark), spurious-
  merge re-pin, dpos == 0 invalidation re-pin, tripwire-retirement negative (a persistent
  miss stream now yields correct readings and NO reset), diagnostics lifecycle, S1 floor
  (drop/boundary-at-200 us/zero-quotient), and negative-direction multi-pitch. Two
  pre-existing tests' "spurious" stimuli switched from full quadrature cycles to A-only
  wiggles — under dpos counting a full cycle IS real motion; the old stimulus was
  physically wrong, not the firmware.
- **Next bench:** unchanged order — inspect nothing further on the rig for the ML0151
  event until a v15 run separates the hypotheses (a repeat 2x event on v15 firmware would
  now be genuinely mechanical; v15 makes the encoder explanation impossible). Then:
  Schmitt (74HC14 at 3.3 V), VESC reversal dead-window characterization, 'Y' with a real
  bus load. On the first v15 'V' runs, watch encMultiPitchCount in the 'S' dump — a
  nonzero rate quantifies the real missed-edge frequency for the first time.

---

## Status & session addendum (2026-08-17, fw v16: BLG record format v6 — encoder diagnostics)

Follow-on to fw v15, operator-requested: the SD log gains the encoder ground truth and the
estimator's filter state, so scale errors, basin poisoning and miss/spurious rates are
readable offline — the fw v15 diagnosis took a bench session precisely because the log
carried only v_act. **fw v16 (pending first flash; the first flash carries v10-v16);**
ledger row 16 has full detail.

- **BLG RECORD FORMAT v6 (92 B, hdr[4] = 6).** Four fields APPENDED (all v1-v5 offsets
  unchanged): `encoder_pos` int32 at 76 (raw x2 quadrature count — differencing it gives an
  estimator-free truth velocity, count x pitch/2), `enc_period_ref_us` uint32 at 80 (the
  EWMA reference — a LEVEL, read directly, never differenced; parked at ~2T or ~T/2 IS the
  poison signature), `enc_multi_pitch_count` uint32 at 84, `enc_spurious_drop_count`
  uint32 at 88 (NEW ISR counter: one increment per dropped interval across all three drop
  paths — raw floor, 0.625 gate, per-pitch floor). The two counters are CUMULATIVE —
  decoders diff for a rate, and a NEGATIVE diff means encoderVelReset() cleared them
  mid-run (stale timeout / reading-age bound / between-run reset), not wrap. Sampled in
  logSampleTick()'s common section as plain volatile 32-bit reads (atomic on Cortex-M7, no
  IRQ masking; the four values are not snapshotted as a set — one-edge skew is irrelevant
  to trajectory-level consumption). Ring 92 KB DMAMEM, 5 rec/chunk (460 B), 5.0x catch-up,
  ~6.1 min preallocation. offsetof static_asserts pin every tail offset; a new
  static_assert pins LOG_REC_SIZE <= 255 (the one-byte hdr[5]). No UDP/command/sequencing/
  controller change; 'S' dump gains `spurDrop=`.
- **Tooling in lockstep (parallel implementer):** decode_benchlog.py parses v6 (26-column
  CSV; v1-v5 byte-identical — now pinned by a REAL-LOG regression test that decodes
  logs/ML0146.BLG against the committed CSV, skipping cleanly if absent); new
  `encoder_diagnostics` figure (scale-audit overlay of the encoder_pos-derived truth
  velocity vs v_act with >20 % deviation shading; implied speed pitch/ref vs v_act;
  per-second counter rates with negative-diff-as-NaN); make_test_blg.py --v6 (synthetic
  encoder_pos integrated from v_act, so the figure self-validates); analyzer exe rebuilt.
  108/108 Python tests pass.
- **Review round (three-lens: safety, correctness, data-integrity): no firmware HIGH/MED.**
  Accepted: F1 (MED, tooling — the real-log v5 regression was verified manually but not
  encoded as a test; now it is), the hdr[5] <= 255 static_assert, the prealloc arithmetic
  (5.8 -> 6.1 min), the decoder-contract wording (only the last TWO fields are counters —
  enc_period_ref_us is a level; the original "last three are cumulative" would have
  invited a meaningless differencing), and an int -> int32_t field-width note. Rejected: a
  literal hdr[5] pin (covered transitively). The safety lens confirmed the two shared-site
  drop paths are mutually exclusive by control flow (the 0.625 gate only evaluates when
  the raw floor passed) and that the dpos == 0 branch is an accept, not a drop —
  correctly uncounted.
- **Tests: 2945 production + 175 bench pass** (rebuilt from source). New coverage: v6
  offsets/sizeof/golden record incl. negative encoder_pos sign preservation, hdr bytes,
  logSampleTick() plumbing driven end-to-end, the spurious-drop counter driven through the
  real ISR (each drop path +1, accepted intervals +0, exactly-once on the shared site,
  reset clear), counter reset-visibility (the negative-diff contract), and the
  5-records/chunk ring re-derivation.
- **Next bench:** flash (v10-v16); the first 'V' runs now log the miss/spurious rates
  BEFORE the Schmitt lands — keep one pre-Schmitt run as the "before" baseline, then the
  same fields quantify exactly what the Schmitt fixed. The encoder_diagnostics figure's
  scale-audit panel is the standing tripwire for any future 2x-family event: encoder_pos
  is ground truth, so a v_act scale error can no longer hide. Bench order otherwise
  unchanged: Schmitt -> VESC reversal dead-window characterization -> 'Y' with a real bus
  load. `.venv_benchlog` still lacks pandas.

---

## Status & session addendum (2026-08-17b, logs 153-180: fw v16 flashed; x2 ROUNDING basin found)

Two analysis rounds since the fw v16 addendum. Round 1 (logs 153-162, still fw v14/BLG v5):
the fw v13 T/2 basin corrupted v_act to ~2x TRUE in 8 of 10 runs — invisible in closed loop;
the rail-acceleration bound (a_true <= (12*0.7538 - 2.00 - 0.534*v)/3.5 ~= 2.0 m/s^2) is the
standard discriminator, now in the benchlog skill's log-conventions.md. ML0151's t~27.5 s
"drag step-change" is near-certainly the same artifact. VESC regen delivery ceiling found
(-12 A commanded, ~6 % delivered — Battery Regen Max 1.5 A is a torque clip, not a dump path;
excess energy stays kinetic). Ag105 confirmed UNPOWERED in all State-98 runs (V_chg = 0; no
charger path open); the sustained regen rail drove V_rgn 13.3 -> 18.1 V peak — the TL431/
BSP170P chopper clamp — with V_bus unmoved; no V_rgn fault check exists.
Round 2 (logs 164-180, **fw v16/BLG v6 confirmed flashed** — encoder_pos ground truth live;
five-agent fan-out):

- **The x2 basin SURVIVES fw v15, by a ROUNDING path.** A spurious mid-pitch A-edge carries
  dpos = 1 and (|dpos|+1)>>1 rounds the half-pitch UP to a full pitch: a self-consistent
  T/2 lock the dpos count is structurally blind to. Confirmed exactly: accepted-interval
  rate 2.00/true slot, ref/T_true = 0.500 (ML0164, ML0168 — locked breakaway-to-stop; the
  operator's 0.5/1.0/1.5 m/s setpoints delivered HALF). Seeding at breakaway (0.08-0.24
  m/s, every run in the batch); escape speed-gated at ~1.0-1.6 m/s true (chatter can no
  longer supply one mid-pitch survivor per slot). The 0.625 gate GUARDS the locked basin.
  The pre-Schmitt front end emits ~480-560 spurious A-edges/s at cruise (~1 per true pitch;
  20-30/pitch at breakaway) — first quantified baseline; Schmitt acceptance: < ~0.05
  drops/pitch at breakaway. enc_multi_pitch_count ~ 0 does NOT exonerate missed edges (it
  is structurally blind to the dominant miss mode).
- **Mid-run v=0 injections (2 events).** YP0166 t~26.24 s: fresh readings -> encoderVelReset
  -> v_act 0 for ~6 ms at true 1.49 m/s -> +/-12 A rail pair in 12 ms. TP0171: a reset
  re-seeded INTO the x2 basin (recovered ~15 ms, v_sp=0). Mechanism unresolved at analysis
  time — neither reader stale path should fire with ~1 ms-fresh readings; root cause
  assigned to the fw v17 round.
- **Clean-axis validations** (everything below from scale-audited segments only): drive SS
  error <= 1 mm/s per ML0165 rung, <= 8 mm/s at a true 3.0 m/s (ML0169). Friction-
  disturbance rejection (ML0169, the clean run of the operator's two): dF 4.2-5.0 N on a
  3.8 N baseline; 30 % dip recovered in 0.738 s at 87 % rail — actuator-limited, correct;
  Hanus verified through 2.2 s continuous saturation. ML0168's disturbances were on the
  corrupted axis (true speed 0.75, not 1.5 m/s). drive_x0 "ratcheting" retired: it tracks
  load and decays. Holds run 1.05-1.12x the drag law across all clean runs (post-ML0151
  branch; the ML0169 9.9 A "hold" was operator hands ~half the run — momentum-balanced true
  hold 5.03 A).
- **First genuine closed-loop share dataset**: TP0170-0180, 11-point share_sp sweep at a
  6 A trapezoid (Itot ~ 0.72 A at hold). sp=0.5 tracks 0.503 +/- 0.028; rails pass through
  clean; the ~0.41/~0.59 "clip bands" are exactly the SHARE_MINORITY_I_MIN_A governor span
  [0.30/Itot, 1-0.30/Itot] — working as designed. NOTE: a manual 'V' run NEVER steps the
  share loop unless powerBalanceLive is armed (frozen gains != gate failure); profiles step
  it unconditionally.
- **TP0178 bus sag 12.15 V, no fault** (0.15 V above LIMIT_V_BUS_MIN; 10 ms < 20 ms dwell):
  I_fc dropped to zero at the share=1.0 rail and BT's ideal diode picked up only REACTIVELY
  after the sag — a handoff-gap hazard at the share rails. Leading trigger candidate
  (operator disclosure): the bench supplies were SWAPPED for batches 153-180 — stiffer on
  BT, LOOSER ON FC; a sub-ms FC-supply transient (UNCONFIRMED — census: TP0176/177 FC-only
  43-45 % of run, zero dropouts). Entry + discriminators in docs/boost-bringup-debug.md.
  Cross-batch caveat: V_fc/V_batt stiffness comparisons vs pre-153 logs compare different
  supplies.
- **Tooling trap**: encoder_diagnostics panel 2 was SELF-CONFIRMING (pitch/ref vs v_act —
  same corrupted quantity); fix assigned to fw v17 round (T1). Counter-rate trap: divide
  counter sums by run duration (t[-1]-t[0]), never t[-1] — the CSV t axis is
  session-absolute.
- **Next bench:** flash fw v17 when it lands (rounding-basin + reset-injection fixes), keep
  one pre-Schmitt run as baseline, then Schmitt (74HC14 at 3.3 V) -> VESC regen-ceiling
  characterization -> matched-Itot share sweep -> refit F_c/b_eff on ML0169 tail+coast.
  `.venv_benchlog` still lacks pandas.

---

## Status & session addendum (2026-08-17c, fw v17: fractional-pitch ledger + TOCTOU reset fix)

Orchestrated round (Opus implementer, independent Sonnet test-writer, Opus safety + Sonnet
correctness reviews) implementing the logs 164-180 findings. **fw v17 (pending flash; fw v16
is on the board, so this flash carries v17 alone).** Ledger row 17 has full detail. No BLG/
UDP/command/pin/sequencing/fault/controller/coefficient change.

- **Fractional-pitch ledger (kills the x2 rounding basin).** The stored per-pitch period in
  doEncoderA() is now `period*2/|dpos|` — |dpos| is already in half-pitch units, so a
  spurious mid-pitch edge (|dpos|=1 over T/2) stores T instead of T/2. |dpos|==2 takes an
  arithmetic-free fast path, BYTE-IDENTICAL to fw v12-v16 (clean-stream v_act comparability
  preserved); |dpos|=3 stores 2/3*period; still one UDIV, none in the common case; the
  per-pitch 200 us floor applies to the fractional value; a >2^31 overflow-escape branch is
  documented as non-conservative and unreachable (100 ms stale timeout forecloses it).
  encLastPitches/encMultiPitchCount keep whole-pitch semantics (v6 field meaning unchanged).
- **Mid-run v=0 injection ROOT-CAUSED: a TOCTOU race, not a semantics gap.**
  updateWheelSpeed() latched `now = micros()` BEFORE snapshotting encLastEdgeUs; an edge
  accepted in that window makes the unsigned age wrap to ~2^32 and unconditionally fires
  encoderVelReset() — ~0.5 expected hits per 25 s run at cruise, matching the two observed
  (YP0166, TP0171) with no signal precondition. Fixed with SIGNED age comparisons in both
  stale tests (a future timestamp has age 0). The clamp's wrap-safety depends on
  updateWheelSpeed() running unconditionally from loop() — documented at the site; any
  future state-gating of that call must add a wrap guard.
- **Post-reset corroboration hold (defence in depth).** A reset taken while the last
  published |v| > ENC_VEL_CORROB_MIN_MPS (0.30 m/s) captures and HOLDS that reading instead
  of publishing 0, until a FULL-ring reading of EITHER sign corroborates (depth-only gate —
  safety review MED-1 removed the sign term: a full-ring opposite-sign reading is a vetted
  genuine reversal, and holding the old sign against it would feed the loop a wrong-SIGN
  value). Bounded at 100 ms from the reset; the two genuine stale paths disarm it. The
  "forced to 0" contract is now THREE events (boot, edge-age stale, reading-age stale).
  The gate is a depth/latency gate, NOT a magnitude safeguard — the magnitude defence
  against the TP0171 re-seed is the fractional ledger. Log-trace change: a State-3 reset
  above 0.30 m/s now holds the true coasting value up to 100 ms into Idle (control impact
  nil; Idle commands 0 A without reading v_actual).
- **Per-path drop counters** encDropRawFloor/encDropLowGate/encDropPitchFloor (volatile
  diagnostics, 'S' dump only; encSpuriousDropCount stays the logged sum, BLG stays v6).
  Tooling: encoder_diagnostics panel (b) now compares implied speed against the encoder_pos
  TRUTH velocity (the old v_act pairing was self-confirming inside a basin).
- **"What NOT to change" exception (explicit, matching the v12/v13/v15 precedent):** the
  encoder velocity TAP in doEncoderA() and updateWheelSpeed()'s hold logic were modified;
  the quadrature decode block itself is untouched and clean-stream output is bit-identical.
- **Reviews:** safety — no HIGH, 1 MED (sign term, removed) + 4 LOWs (all applied, incl.
  ENC_VEL_CORROB_MIN_MS -> _MPS rename); correctness — no code bugs, 1 doc-HIGH (stale
  sign-term wording from the mid-round fix, corrected in .ino + ledger) + LOWs applied.
  Untested-behavior list (boundary equalities, double-reset overwrite, overflow branch) is
  in the correctness report — acceptable residuals, none control-reachable.
- **Tests: 3007 production + 175 bench pass** (rebuilt from source, both builds, orchestrator-
  verified). New coverage: the x2-basin regression (fails under fw v16 semantics), fractional
  arithmetic (|dpos| 1/2/3/4 + floor), the TOCTOU race (future timestamp does NOT reset;
  genuine stale still does), the corroboration hold state machine (arm/hold/either-sign
  full-ring publish/timeout/low-speed no-arm/stale disarm), per-path counter sum invariant,
  and the TP0171 reset-into-basin regression. NOTE: the test build now needs
  `-I../controller_design_MIMO` (the test skill's command block predates it).
- **Next bench:** flash fw v17 (alone). First runs: watch the 'S' dump per-path drop split —
  encDropLowGate is the number the Schmitt must remove. Bench order unchanged: one
  pre-Schmitt baseline run -> Schmitt (74HC14 at 3.3 V) -> VESC regen-ceiling
  characterization -> matched-Itot share sweep -> F_c/b_eff refit (ML0169 tail + coast).

---

## Status & session addendum (2026-08-25, fw v20: BLG v7 — edge counters + phase/duty geometry)

Orchestrated round (Opus implementer, tooling implementer, independent Sonnet test-writer,
parallel Opus safety + Sonnet correctness reviews). **fw v20 (pending flash; the next flash
carries v18 + v19 + v20).** Ledger row 20 has full detail. Observability only — no pin/
sequencing/fault/command/controller/UDP change (telemetry stays v4/58 B).

- **BLG RECORD FORMAT v7 (106 B, hdr[4] = 7).** Five fields APPENDED (all v1–v6 offsets
  unchanged): `enc_edge_count_a`/`b` (uint32 at 92/96 — raw per-channel ISR edge counts,
  the direct Schmitt before/after metric and the offline dead-channel/dead-estimator
  discriminator) and `enc_phase_ewma`/`enc_duty_a_ewma`/`enc_duty_b_ewma` (uint16 at
  100/102/104 — quadrature mount-phase and per-channel optical duty, shift EWMA α = 1/4,
  fixed-point 1/256 pitch, computed in the ISRs; replaces a scope for verifying the
  sensor offset under rotation). Ring math re-derived: 106 KB ring, 4 rec/chunk = 424 B,
  4.0× catch-up, prealloc ~5.3 min.
- **THREE decoder field classes now** — mixing them up produces plausible nonsense:
  LEVELS (`enc_period_ref_us` + the three EWMAs; read directly, never differenced; 0 =
  "no measurement yet"); RESET-CLEARED counters (`enc_multi_pitch_count`,
  `enc_spurious_drop_count`; negative diff = mid-run `encoderVelReset()`); BOOT-MONOTONIC
  counters (the edge counts; NEVER cleared — negative diff = uint32 wrap or MCU reset).
  Do not add a clear site for the edge counters ('L'/'S' consumers rely on monotonicity).
- **Convention (operator-confirmed): healthy phase = 0.25 pitch, A leads B forward.** The
  90-slot wheel's 43° offset = 10.75 pitches (fractional 0.75), but the sensors were
  PHYSICALLY SWAPPED at wheel install, so the measured A-rise→B-rise fraction is the
  complement. Phase is direction-gated (forward only) and plausibility-gated (dt < ref);
  a confirmed direction flip CLEARS the phase EWMA (safety MED-1: the reviewer's literal
  latch-clear fix was a provable no-op; the implementer's accumulator-clear discards the
  stale-window contamination — under ML0140-class dither φ reads 0 = honestly unmeasured,
  never the 0.5 aligned-edges fault signature). Duty EWMAs are NOT direction-gated or
  flip-cleared (no handedness).
- **Duty acceptance is post-Schmitt-only (safety MED-2, annotated not filtered):** under
  the un-Schmitted front end duty A biases HIGH and duty B LOW by construction; the
  one-shot arming fix was rejected to preserve raw-edge visibility. Bench acceptance,
  first spin, 'S' dump: phase 0.25 ± 0.05; duties 0.50 ± 0.05 each POST-Schmitt (their
  pre-Schmitt deviation direction identifies the chattering channel). Phase drift toward
  0.0/0.5 = aligned-edges failure. Once the 74HC14 lands, the duty bias vanishing is a
  second independent Schmitt-acceptance metric alongside the drop counters.
- **Taps are the fw v15/v17 exception class:** quadrature decode blocks verified
  byte-identical; the taps write no estimator/decoder input. One divide per φ/duty sample,
  confined to the rising/falling branches; the accepted-period common path gains none.
  uint16 overflow is bounded STRUCTURALLY by the dt < ref gate (fp < 256) — no explicit
  clamp exists; weakening that gate requires adding one.
- **Tooling in lockstep:** decoder parses v7 (31-column CSV; the three EWMA columns are
  pre-divided by 256 into direct fractions), `make_test_blg.py --v7`, new
  `encoder_phase_duty` figure (0.25 ref + ±0.05 band + 0.75 swapped-sensor signature;
  0.50 duty ref), edgeA/edgeB rate lines in encoder_diagnostics panel (c). v1–v6 parsing
  byte-identical (ML0146 real-log regression green). Analyzer exe STILL needs a rebuild.
- **Tests: 3442 production + 175 bench, 135 + 174 Python — all green** (orchestrator-
  rebuilt from source, both builds). New: v7 layout/golden/plumbing via the real ISRs,
  boot-monotonic vs reset-cleared on one reset call, `encFoldPitchFraction()` unit
  (seed/fold/both gates), ISR-driven φ at ¼ and ¾, flip-clear + one-sample re-seed,
  dither never parks at 128, asymmetric duty, 'S' dump lines. Accepted residuals
  (correctness review L1–L3): EWMA boundary at ref-cap, pre-seed early-fold numerics,
  fractional-pitch-ledger × tap timing — none control-reachable.
- **Next bench:** flash (v18+v19+v20); on a forward hand-spin read the 'S' dump
  `phase=`/`dutyA=`/`dutyB=` FIRST and confirm 0.25/0.50/0.50 before trusting any
  velocity number on the new wheel; keep one pre-Schmitt run as the edge-rate baseline.
  Then the fw v18 order unchanged: Schmitt → VESC regen-ceiling → matched-Itot share
  sweep → F_c/b_eff refit. Housekeeping: analyzer exe rebuild; .venv_benchlog pandas/scipy.

---

## Status & session addendum (2026-08-27, fw v21: HIL mode — Teensy as DUT vs a simulated plant)

Orchestrated round (Opus implementer, Sonnet test-writer, parallel Opus safety + Sonnet
correctness reviews, fix round). **fw v21 (pending flash; the next flash carries v21 alone).**
Ledger row 21 has full detail; docs/HIL_MODE.md is the reference (frame tables, H1–H5 test
plan, limitations).

- **New compile flag `HIL_SIM` (default 0; requires `USE_ETHERNET=1`, `#error` otherwise).**
  Signal-level controller-HIL: a 35-byte UDP injection frame (sync 0xB5, seq, 8×float32 LE —
  the 7 rails + v_actual in engineering units, XOR bytes 1–33) overrides updateSensors();
  a 16-byte observation frame (0xB6: seq echo, mainState, switch_state via the factored
  `readSwitchState()`, aux pin bits, post-clamp `current`, MDAC mirrors from the
  setDroopMdac() chokepoint, fault_flags, XOR bytes 1–14) streams at 1 kHz to the learned
  host. Codec compiled unconditionally (testable in every build); only the wiring is gated.
  detectFaults(), sequencing guards and both controllers run UNMODIFIED on injected values —
  fault injection is the purpose. v4 telemetry (58 B) and the 22-byte command packet are
  byte-identical; no protocol bump.
- **Link-loss is two-stage hold-then-zero**: ≤50 ms fresh; 50–250 ms HOLD (a missed tick is
  a host artefact, not a plant event) with `haltMotorOutput()` on the stale ENTRY EDGE
  (review MED-2: a frozen v_actual is live feedback to a ~454 A/(m/s) loop with a real VESC
  attached); >250 ms force zeros, unbind the host, and latch
  `triggerFault(FAULT_HIL_LINK, ERR_HIL_STALE)` (FAULT_HIL_LINK ALIASES FAULT_PI_TIMEOUT —
  fault_flags has no free bit and is protocol-frozen; ERR_HIL_STALE = 0x10 disambiguates).
- **receiveCommands() is now a bounded drain loop** (UDP_DRAIN_MAX_PER_TICK 8, review
  MED-1): all 22-byte commands dispatch in order via the extracted, byte-identical
  `processPiCommandPacket()`; only the NEWEST valid injection frame per tick is committed;
  drain counters in the 'S' dump. Host learned on FIRST accepted frame only; foreign-source
  frames ignored + counted (LOW-3). BLG record flags **bit6 = HIL build** (LOW-1; decoder
  update is open tooling follow-up). "(INJECTED)" provenance markers in the dumps (LOW-2).
  MED-3 (skipping updateWheelSpeed() vs the fw v17 wrap-guard invariant) is documented at
  both sites — any future "revert to real sensors" fallback must add the wrap guard.
- **tools/hil_plant_sim.py** (stdlib-only, 1 kHz drift-corrected): mechanical plant from the
  fw v14 constants (m_eff 3.5, K_F 0.7538, F_c 2.00, b_eff 0.534), simple droop-bus
  electrical model honoring switch semantics, scenarios steady/step-load/sag/comm-loss/
  drive, CSV logging. Known limitations: signal-level only (no power-HIL), charger path NOT
  simulated (Ag105 I2C real and unpowered; I_charge not injectable — frame extension is the
  known follow-up), encoder estimator bypassed. Production (BENCH_TEST=0) HIL boot REQUIRES
  the simulator streaming before power-on (~800 ms INIT_FAIL otherwise; bannered).
- **Tests: 3523 production + 175 bench + 3625 HIL-build (new third build,
  -DHIL_SIM=1 -DUSE_ETHERNET=1), all pass, rebuilt from source.** Coverage incl. golden
  frames both directions, NaN/Inf reject (a checksum admits NaN patterns that would poison
  the drive recursion), dispatch interleaving/newest-wins/cap, hold/zero/fault/recovery
  edges, State-99-keeps-injecting regression, hilSendTick content, host lock, BLG bit6.
  mock_ethernet.h gained remoteIP/remotePort + a multi-packet RX queue.
- **Next:** flash a bare Teensy (no PCB needed — that is the point) + Ethernet, run the H1–H5
  plan in docs/HIL_MODE.md. Open follow-ups: decode_benchlog.py bit6 label, Ag105/I_charge
  injection, a --replay mode feeding decoded BLGs back as injection frames (would turn
  recorded bench incidents into regression stimuli).

---

## Status & session addendum (2026-08-27b, HIL follow-up rounds: plant doc, decoder bit6, charger injection, replay)

Four orchestrated follow-up rounds on the fw v21 HIL mode, all on `main` (the feature branch
was merged and work moved to main at the operator's request). FW_VERSION stays 21 — the HIL
frame was never flashed, so the injection-frame extension is a clean pre-release bump.

- **`docs/HIL_PLANT.md` (new, ~330 lines + review pass):** the plant-side deep dive — 
  architecture, real-time loop (drift-corrected 1 kHz, why soft-RT suffices vs the 17.25 rad/s
  crossover), mechanical/electrical models with constants-provenance tables, actuator mapping,
  scenarios, CSV/BLG correlation, fidelity boundaries. Simulator-only tuning values
  (V_STICTION, K_DROOP_BUS, R_BUS_BLEED, ETA_BOOST, I_AUX_A, R_FC/BT_INT, AG105_TAU_S,
  AG105_V_IN_MIN) are honestly `TODO(verify)` — do not launder them into calibrated facts.
- **HIL injection frame 35 → 40 B** (I_charge float32 at 34, raw Ag105 Table-6 status byte at
  38, XOR span 1..38): under HIL_SIM with an active link, `pollAg105()` skips real I2C entirely
  and mirrors the real path's semantics from injected values (unpowered → cleared/invalid;
  powered → injected status + ag105DataValid; settled → configured by fiat; NO transport
  faults; GENSTAT fault decode stays live). Stale 35-B frames drop on length with accepts
  pinned at 0 (loud failure). The simulator gained a status-level charger model (Table-6 bytes
  from the JSON, settle → charging ramp to 2.5 A, input-rail floor, MPPT_DISABLE tracking-bit
  behavior). What is still NOT simulated: I2C config writes, CV taper/SoC, the MPPT loop.
- **BLG flags bit6 in the tooling:** decode_benchlog.py exposes `header["hil_build"]` + a
  decode-report warning; make_test_blg.py grew `--flags-bit6-on/off` (default OFF, unlike
  bit4/5); every analysis figure gets a red "HIL_SIM LOG" banner via `_suptitle()`. The
  PyInstaller analyzer exe STILL needs its standing rebuild to show any of this.
- **`--replay` mode in hil_plant_sim.py:** decodes a .BLG (via decode_benchlog's API, columns
  resolved by name at runtime) and plays it back as injection frames at wall-clock pacing
  through the same scheduler; `--replay-speed`, `--loop`; plant integrator bypassed,
  observation/CSV/status paths live; CSV gains an appended `replay_rec` column. OPEN-LOOP by
  construction — the firmware's commands do not influence the replayed trajectory; BLG v1–v7
  carry no I_charge/ag105_status so those inject as 0/0x00. Smoke-verified frame-perfect vs
  the decoder's own CSV (synthetic 40 k-record log + ML0146 at 20×, 1000.0 Hz achieved).
- **Tests, orchestrator-rebuilt from source:** 3535 production + 175 bench + 3662 HIL-build
  C++; new tools/test_hil_plant_sim.py (58) + test_decode_benchlog.py pytest set = 82 pytest
  green, decoder harness 145/145, figures suite 191/191 (needs a numpy/matplotlib venv —
  .venv_benchlog STILL lacks pandas/scipy). Known un-covered: the sim's main() socket loop,
  apply_scenario() internals, CSV-writer path, exact AG105_SETTLE_S boundary tick.
- **Next:** flash the (now 40-B-frame) fw v21 on a bare Teensy + Ethernet and run H1–H5
  (docs/HIL_MODE.md), then replay a recorded incident (ML0151) as an H6-class regression.
  Housekeeping: analyzer exe rebuild; .venv_benchlog pandas/scipy.

---

## Status & session addendum (2026-08-27c, HIL Updates 2026-08-26a: hi-fi electrical sim, source models, replay suite, suite runner)

Orchestrated tooling round implementing the USER_NOTES.md "HIL Updates 2026-08-26a" block
(4 research agents -> 3 Opus implementers -> Sonnet test-writer -> Opus data-integrity +
Sonnet contract reviews -> fix round -> orchestrator final review). All on main; Python
tooling only — FW_VERSION stays 21, wire protocol frozen (40 B inject / 16 B observe).

- **K_DROOP_BUS is now MEASURED, mode-aware:** 0.074 V/A both-sources / 0.16 single-source
  (V0 15.95; fit of TP0170-0180 excl. TP0178, ML0165, ML0169; parallel-Thevenin mode ratio
  exactly 2; FC/BT symmetric <2 %). **OPEN FINDING: realized droop is ~4x BELOW the MDAC
  droop-chain design value** (0.30 V/A at g=0.298, k_d=0.3) — flagged in the code comment,
  HIL_PLANT.md §4.2 and every suite REPORT.md; do not launder.
- **tools/hil_electrical.py (new, ~1100 lines, stdlib):** opt-in hi-fi electrical engine
  (--electrical hifi), 6-node backward-Euler network at an adaptive substep rate (~30-40 kHz
  measured, decoupled from the 1 kHz mechanical tick, achieved rate reported honestly).
  RT1987 per-switch state machines (8 ms t_D_ON, CSS soft-start 100 nF FC/BT/MOT vs 5.6 nF
  others, foldback SCP 250 us trip + 64 ms retry, 35 mV forward servo, -50 mV fast reverse
  comparator — the TP0178/TP0201 reactive-pickup handoff gap falls out of this), droop as
  true FB-node superposition (RE_MAX 2.014), body-diode passthrough of a disabled boost,
  regen chopper (47 ohm, clamp 18.1 V bench-calibrated 2026-08-27, 20 W dissipation check), analytic parasitic-ring events (long
  1.538/3.480 nH FastHenry, short ~1.5 nH TODO(verify)) — NOT integrated (nH-uF ~100 MHz is
  unintegrable in real-time Python; documented). The literal TPS61288 gm/Z_comp loop was
  built and REPLACED (crossover at substep Nyquist diverged): channels use the repo's
  validated reduced form; no boost-stability claims from this engine.
- **Source models (user scope extension):** FuelCellSource + BatterySource per Yadav &
  Assadian, Energies 2025 (references/Robust Energy Management...pdf), cited by equation.
  FC: Nernst/Tafel/concentration + 20 ms stack RC, fitted 12.97 V OC / 0.447 ohm effective
  at 2 A (FC_R_SERIES_RIG 0.41 ohm harness term); battery: 2S OCV(SOC) 9-point generic
  TODO(calibrate), coulomb-counted (charge current raises SOC; Ag105 now reaches FULL with
  CV taper at SOC>=0.995), --soc0/--capacity-ah. Both modes share one instance each.
- **PiCommander:** the sim can now drive the firmware's 22-byte Pi command packet (layout
  verified against .ino:4806-4852, sync 0xBB, XOR 1..20) — charging scenarios command
  charge_goal without an operator. 7 new scenarios (charge-cruise/-regen/-fault,
  soc-depletion, hifi-only handoff-sag/bringup/scp-inrush) in a SCENARIOS registry.
- **tools/hil_replay_suite.py + docs/HIL_REPLAY_LOGS.md (new):** 26-entry curated replay
  suite (15 conformance / 11 deviation) from a full 206-log census; 8 declarative check
  kinds; fault_latched replays the firmware's own leaky UV-dwell integrator over the
  injected V_bus and fails INCONCLUSIVE if the stimulus no longer qualifies; FW_DELTA_NOTES
  per version; pre-v18 = different wheel + law, stability-not-trace-match. Excluded:
  ML0182/0183 (defective-wheel diagnostics), ML0135, fw v3-v8 bulk (3 UV-collapse
  representatives kept as deviation stimuli: TP0010/TP0053/WP0097 — modern fw must latch
  UV where the old firmware died silent). The doc is the maintained ledger — update it
  with every added log.
- **tools/run_hil_suite.py (new):** runs the full 38-run plan (12 scenarios + 26 replays,
  ~29 min), subprocess-isolated with SIGTERM-then-SIGKILL timeouts, per-run results.json
  rewrite (Ctrl-C keeps completed runs, meta.partial rendered), REPORT.md + results.json
  with the K_DROOP x4 finding always present. Exit 0/1/2(board unreachable)/130.
- **Review round (2 HIGH, 6 MED, 9 LOW + 2 contract MED — all accepted, all fixed):**
  H1 regen into an open MOT_PWR node ran the solver to ~10 kV and manufactured a FALSE
  Death-5 over_absmax banner (fixed: bounded Norton motor stamp, 2x-absmax node_runaway
  backstop, plausibility-gated sw_ring verdict); H2 the no-soft-start re-arm flag survived
  an EN-low cycle, defeating foldback on exactly the hot-plug case (fixed: cleared on any
  EN-low). M-class: retry-timer freeze across EN toggle, NaN guard + sticky numeric_fault,
  events sidecar now streamed per-tick (SIGKILL no longer loses evidence), per-run output
  rewrite, v_bus_offset -> v_bus_sense_offset (hi-fi sag is a SENSOR-PATH injection, not a
  plant event — documented asymmetry, deviation from the stamp-it-real fix), soft-start
  charge non-conservation documented. Orchestrator-applied fix: REPLAY_SUITE paths were
  CWD-dependent (all 26 logs "missing" when run from tools/) — anchored to REPO_ROOT.
- **Tests: 255 pytest green** (89 plant + 39 electrical + 47 replay-suite + 56 wrapper +
  24 decoder), rebuilt and rerun by the orchestrator; --verify-logs green from any CWD.
  Known residuals (test-writer, accepted): _drain_electrical_events() event throughput not
  unit-testable without a live peer (wiring covered black-box); a NaN persisting across two
  consecutive substeps restores to a NaN previous value (unreachable via any constructed
  actuator path; sticky flag still trips); exit-code tail of run_hil_suite.main() inline.
- **Next bench:** flash fw v21 + Ethernet, `python3 tools/run_hil_suite.py --teensy-ip <ip>`
  for the first full HIL report; hifi handoff-sag needs on-board verification (the share
  cut latch actually opening BT_BUS was not verifiable without hardware). Housekeeping
  unchanged: analyzer exe rebuild; .venv_benchlog pandas/scipy.

---

## Status & session addendum (2026-08-27d, HIL live terminal dashboard)

Orchestrated tooling round (Opus implementer, Sonnet test-writer, Opus combined-lens review,
Sonnet fix round). Python tooling only; FW_VERSION stays 21; wire protocol/CSV untouched.

- **tools/hil_dashboard.py (new, stdlib):** ANSI live dashboard (plain ESC[H redraw, not
  curses — Windows Terminal/MSYS2 compatible via the os.system("") VT trick). Shows v_sp/
  v_act, share_sp/share_act (sp from the PiCommander timeline when pi-driven, else "—";
  share_act = I_fc/I_tot above 50 mA), V_bus/I_tot/I_fc/I_bt with ~12 s sparklines, named
  switch/aux indicators, firmware state, decoded fault names, frame counters, hifi substep
  rate/chopper peak. Terminal-size adaptive (per-frame get_terminal_size, ANSI-safe
  truncation, priority-based line dropping); non-tty stdout → polite refusal, normal prints.
- **Lightness contract (user prime directive, review-verified):** the 1 kHz loop's only
  obligation is ONE scalar-only dict build + one attribute assignment per tick — no locks,
  no I/O, no time syscalls, provably no torn reads (fresh dict of scalars each tick); a 5 Hz
  daemon thread owns history rings and rendering; O(60) per render regardless of run length.
  Measured: 999.9 Hz with rendering vs 1000.0 Hz without (pty, dead IP). Zero-cost when off
  (one local-bool branch). Renderer exceptions latch dash.error, restore the cursor, never
  propagate; the sim resumes normal 1 Hz status prints on renderer death (review F2).
- **Flags:** `hil_plant_sim.py --dash` (suppresses the scrolling status lines while active;
  banners/exit summary unaffected); `run_hil_suite.py --dashboard` (default OFF per the
  "in case it affects the simulation" requirement) passes --dash to every child with stdout
  passed through — the REPORT.md rate gate is explicitly SKIPPED-and-labeled for such runs
  (F3), and --dashboard without a tty is refused at argparse (F4).
- **Review round: 4 MED + 6 LOW, all accepted/fixed** (narrow-terminal wrap corruption,
  renderer-death silence, silent rate-gate drop, piped-wrapper dead zone; + cosmetic LOWs).
  Orchestrator applied the two mechanical F2 test ripples. **Tests: 296 pytest green**
  (34 new dashboard tests incl. a FAULT_NAMES equality pin against hil_replay_suite and a
  code-shape guard that the sim touches only dash.snapshot/start/stop/error).

---

## Status & session addendum (2026-08-27e, HIL Mode A/B: emulated EMS + Pi-in-the-loop + user manual)

Orchestrated tooling round (Opus implementer, Sonnet test-writer, Opus combined-lens review,
Sonnet fix round). Python tooling + docs only; FW_VERSION stays 21; wire protocol frozen.

- **Mode A — emulated Pi EMS (`hil_plant_sim.py --ems STRATEGY`):** EMS_STRATEGIES registry;
  a policy is `policy(t, fb) -> {v_setpoint|power_share_setpoint|charge_goal|mode_cmd}`
  (POLICY_ALLOWED_FIELDS-gated, unknown keys raise; unset fields hold, matching
  .ino:4869/4874-4876). `fb` is built only on due 50 Hz commander ticks and carries plant
  truth + last obs + `obs_age_s`; FB_TELEMETRY_EQUIV_KEYS names the subset a real Pi would
  see (verified field-by-field against sendTelemetry(), .ino:4988-5069) — policies meant
  for the real Pi must restrict to it. First strategy `hold-5050` (share 0.5 constant,
  MODE_HYBRID at 3 s, MODE_SAFE at 55 s). New scenario `ems-drive-cycle` (60 s, 8-point
  accelerate/cruise/step/decel profile; decel 0.167 m/s² stays gentler than coast — no
  regen entry). `--ems` requires `--scenario`, replaces a pi_timeline with a notice.
- **Mode B — real Pi in the loop (`--pi-live`):** the sim injects sensors ONLY; PiCommander
  is never constructed; refused with `--ems`, `--replay`, and on any EMS/pi_timeline
  scenario. VERIFIED FROM SOURCE: telemetry destination is FIXED 192.168.1.100:5000
  (.ino:2541-2542, 5065) — a Pi elsewhere commands blind; the HIL stale clock keys on
  ACCEPTED INJECTION FRAMES ONLY (.ino:4970-4976) and the Pi watchdog (PI_TIMEOUT_MS 500,
  armed State 2/3 after pi_ever_connected, .ino:4817-4826/2788) is fully independent — so
  comm-loss keeps its required 0x0010 under pi-live, and Mode A's 50 Hz cadence is
  load-bearing in Run state.
- **Suite:** `run_hil_suite.py --pi-live` skips EMS/pi_timeline scenarios AND the entire
  replay half (the operator's Pi is an uncontrolled second stimulus over a replayed
  trajectory) as SKIPPED-rendered records; cmd_mode tagging in results.json/REPORT.md;
  all-skips exits 1. **Review F1 (HIGH): the pi-live PI_TIMEOUT excusal was a NO-OP**
  (triggerFault() always ORs FAULT_ERROR 0x8000, so the old mask left 0x8000 unexcused
  while printing that it excused) — replaced by the narrowest rule: excused only when the
  union is EXACTLY 0x8010 AND the child's own injection stream was continuous (tx >= 98%,
  0 send errors, parsed from the child summary); otherwise "cannot attribute to the Pi".
  Residual documented: error_code is not on the observation frame, so PI_TIMEOUT vs
  HIL_STALE (0x0010 alias) is not distinguishable — frame extension is future protocol
  work. CSV: `cmd_v_sp`/`cmd_share_sp` appended unconditionally in simulated mode (blank
  without a commander; replay schema untouched).
- **docs/HIL_USER_MANUAL.md (new):** operator manual — three modes, hardware/network
  (unmanaged switch, static IPs, ~0.5 Mbit/s), build flags (note: the source defaults were
  flipped to BENCH_TEST 0 / USE_ETHERNET 1 by the operator for Arduino-IDE builds;
  HIL_SIM still defaults 0 and must be flipped for an HIL flash), Mode-A walkthrough +
  strategy template, Mode-B THREE-NODE SEQUENCING (network → simulator streaming →
  board power [BUS_CHARGE_TIMEOUT_MS 800, .ino:1381] → Pi last; shutdown Pi → sim →
  board), per-step failure signatures with the real 0xA000/0x8010 literals, and the open
  item that the Pi's v4 telemetry parser has never been audited.
- **Review round: 1 HIGH + 4 MED + 9 LOW — all accepted, all fixed** (ems-scenario
  pi-live refusal gap [also found independently by the test-writer], replay-half second-
  stimulus gap, skip records rendered as fake-clean PASSes, wrong hold-on-reject anchor,
  --ems scenario requirement now enforced, obs_age_s staleness signal added, per-tick
  closure hoisted off the no-policy hot path).
- **Tests: 357 pytest green** (~55 new). Also this round: the operator flashed fw v21
  (first HIL-capable flash) after the Arduino prototype fix; logs ML0218/ML0221 landed
  (bench runs, not HIL-build). The accidentally-tracked Linux test binaries
  (test/run_tests*) were untracked and gitignored; the Windows .exe artifacts stay.
- **Next:** Mode-A smoke on the bench (`--ems hold-5050 --scenario ems-drive-cycle
  --dash`), then the Mode-B bring-up per the manual; audit the Pi bridge's v4 parser
  before the first pi-live run.

---

## Status & session addendum (2026-08-30, fw v22: HIL sequential runs + regen-node topology fix)

First real HIL bench session (fw v21 flashed, Mode A). Three orchestrated rounds; ledger row 22.

- **HIL regen-node TOPOLOGY FIX (tooling).** The first bring-up attempts latched INIT_FAIL then
  MOT_HOTPLUG: the simulator had the REGEN switch between V-MOT and the RGN sense/chopper node.
  **Schematic sheet 4 + operator confirm:** the RGN-V divider and TL431/BSP170P chopper sit ON
  V-MOT, upstream of D-BC-RG; D-BC-RG and D-BC-FC outputs join at the shared VCHG-IN node
  (CHG-V divider) into the Ag105. Fixed in hil_electrical.py (REGEN links N_MOT→N_CHG, V_rgn
  reads N_MOT, chopper on N_MOT, charger always draws N_CHG; N_RGN retired as an index-padding
  node) and the simple model (V_rgn follows MOT_PWR; V_chg fed by either path). PSCAD_SIM_DESIGN,
  HIL_PLANT and the chopper "V_bus unaffected" claims reconciled (coupling through closed
  MOT_PWR ≈ 0.03–0.06 V — consistent with the bench). **Validated on hardware:** staged bring-up
  P0–P3 DONE on injected sensors; full 60 s ems-drive-cycle ran clean (median |v_act−v_sp|
  1 mm/s, zero faults in Run).
- **Known open tooling defect:** the hifi RT1987 SOFT-state clamp detector computes demand as
  (target−v_out)/R_ON with a one-substep-stale v_out, so the two 5.6 nF charger-path switches
  (REGEN, FC_CHARGE) false-SCP-cut forever and the Ag105 can never power in hifi charge
  scenarios. Needs its own round (physical C·dV/dt ramp current).
- **HIL Results/ output convention (tooling round):** every HIL artifact defaults into repo-root
  `HIL Results/` (relative --csv resolved there, absolute honored; suite reports
  `HIL Results/hil_report_<ts>/`); gitignored. `.venv_hil` (uv, stdlib-only + pytest/pyserial)
  is the HIL interpreter — bare `python` is the MS-Store stub. Bench PC Ethernet needs the
  static IP 192.168.1.10 (APIPA 169.254.* = forgot it; manual §4.1 has the check).
- **fw v22 (pending flash): HIL sequential runs without power-cycle.** (a) Under HIL_SIM,
  doState0() waits for a FRESH injection link (1 Hz notice; zeros published pre-first-frame so
  floating ADCs cannot OV-latch — S7) then runs the STAGED bring-up in BOTH BENCH_TEST values —
  the T/G/Q dance and the fw v21 boot-order race are gone on HIL builds (non-HIL bench keeps
  the dark-boot + 'G' doctrine verbatim). (b) doState99() phase 3 auto-recovers from the
  dead-link latch: admission = fault_flags EXACTLY 0x8010 AND error_code ERR_HIL_STALE AND
  500 ms continuously-fresh link (HIL_RECOVER_DEBOUNCE_MS, re-armed on any staleness) AND the
  BLG fully closed; action = hilWarmReset() (software-state-only boot restore incl.
  droopSlew_prev/shareHandoffPrevRatio re-anchored to the re-initialized MDACs' 0.5 — S2;
  NO pin writes) → State 0 → auto bring-up. Any other fault (incl. genuine ERR_PI_TIMEOUT,
  same 0x8010 union — error_code disambiguates, first-cause-only) stays latched forever.
  (c) Link death DURING bring-up aborts to the wait gate instead of racing the phase timeouts
  into an unrecoverable INIT_FAIL (S3; the abort predicate is link-freshness, not hilZeroed —
  the hold window is the race window). Mode-B warning: a persistent Pi must restart its
  timeline on observing mainState 99→0 or it commands a mid-profile setpoint into a
  freshly-reset drive loop.
- **HIL_SIM source default flipped back to 0 (operator decision, S1 HIGH):** the operator's
  IDE flip had made EVERY build HIL — including the test Makefile's "production"/"bench"
  targets, which were silently compiling the HIL path (correctness HIGH-1; the bench 175→169
  drop was the dead dark-boot test). Makefile now passes -DHIL_SIM=0 explicitly on both non-HIL
  targets. **An HIL flash now requires editing HIL_SIM to 1** (manual §2.4); a default flash is
  a normal bench build again, and a HIL_SIM=1 build without a simulator sits visibly in the
  State-0 wait loop (no serial console there — flip the flag back for bench work).
- **Tests: 3535 production (-DHIL_SIM=0) + 175 bench (-DHIL_SIM=0) + 3909 HIL, all green,
  orchestrator-rebuilt.** New coverage: wait gate, auto bring-up, recovery admission matrix
  (exact-flags/extra-bit/PI_TIMEOUT/debounce/phase-3/open-log), ~35-global warm-reset audit
  (pins untouched, boot-monotonic counters preserved), two-run sequential regression, mode_cmd
  gating, mid-bring-up abort. Mock gained a tracked-millis fresh-link model
  (g_mock_millis_track).
- **Next bench:** flash fw v22 (edit HIL_SIM 0→1 first); verify sequential Mode-A runs and a
  full run_hil_suite pass without power-cycles; keep the hifi SOFT-SCP fix and the Pi-bridge
  v4 parser audit on the list. `.venv_benchlog` still lacks pandas/scipy; analyzer exe rebuild
  still pending.

---

## Status & session addendum (2026-08-30b, hifi RT1987 SOFT-state physics fix)

fw v22 VALIDATED ON HARDWARE (operator ran two back-to-back Mode-A cycles, no power-cycle).
The first BENCH_TEST=0 HIL boot then latched FAULT_OC_FC (0x8001, from state 0) — the
production build's single-sample OC check (LIMIT_I_FC_MAX 1.4 A) had never met a bring-up
before, and the injected I_fc read amps. **Root cause: the fw v22 addendum's "known open
tooling defect" — the RT1987 SOFT-state stale-demand bug — now FIXED (orchestrated round);
that "open defect" line is SUPERSEDED by this addendum.** The firmware is untouched and
needs no OC persistence filter: the physical pre-charge inrush is C·dV/dt ≈ 28 mA.

- **Fix (tools/hil_electrical.py):** `_soft_operating_point()` evaluates the ramp target at
  the SAME instant as the solved v_out (the old next-instant target put rate·h/R ≈ 30-36 A
  of pure discretization into the demand); reported current (the INA253 sense) is
  i_phys = max(c_load·rate, (target_prev − v_out)/R) clamped by the fold limit; the fold
  stamp uses the overdrive-ratio resistance r·(i_phys/i_fold) (continuous at the boundary,
  degrades toward open). All three symptoms gone in one change: (1) REGEN/FC_CHARGE (5.6 nF)
  reach ON — hifi charge scenarios can finally power the Ag105; (2) bring-up channel currents
  are physical (P0 peak 0.22 A vs 1.98 A before; full staged bring-up ≤ 0.47 A, under the
  1.4 A OC limit with margin); (3) genuine overloads still fold and SCP-cut (scp-inrush 6 A
  margin case folds at ~5.6 A, cuts, 64 ms retry; persistent short latches the retry loop;
  released overload completes to ON).
- **Review round (data-integrity + contract lenses):** no HIGHs. F1 MED — the new tests ran
  unpinned `_n_sub` and the physical current converges only for substeps ≲ 125 µs (4.27 A at
  _n_sub=1 vs 0.22 A converged): all pinned via `_pin_and_step` now. LOWs applied: guard-vs-
  regression test banner, the i_track-floor assumption comment (c_load·rate < 2.5 A for all
  shipped c_load; a ≥10 mF c_vesc_f would break it), M6 charge-non-conservation note updated
  to the post-fix imbalance, the 28 ms→19.8 ms tON figure, and the sw_ring population note
  (SOFT-state opens at physical mA no longer emit rings — correct). Accepted residual: the
  ratio-form comment slightly overstates generality in the unreachable i_track-fold branch.
- **Tests: 371 pytest green** (54 in test_hil_electrical.py incl. 9 new: charger-path
  switches reach ON, the OC-regression current pins, overload/short SCP guards, _h==0
  degradation). Firmware suites untouched (3535/175/3909 from the fw v22 round stand).
- **Next bench:** power-cycle (the OC latch is correctly non-recoverable), then a
  BENCH_TEST=0 HIL boot should reach Idle unattended; validate sequential runs + mid-run
  sim-kill recovery + the first powered-Ag105 hifi charge scenario, then the full
  run_hil_suite. The operator's local .ino flag flip (BENCH_TEST 0 / HIL_SIM 1) is the
  CURRENT FLASH's config and stays uncommitted — repo defaults remain BENCH_TEST 1 /
  HIL_SIM 0.

---

## Status & session addendum (2026-08-30c, fw v23: any-fault HIL recovery + CSV sidecar/tripwire tooling)

Two orchestrated rounds after the first run_hil_suite attempt latched FAULT_UV_BUS in one
scenario and every later run found the board latched (fw v22 recovered only the exact
0x8010/ERR_HIL_STALE dead-link signature). **fw v23 (pending flash)**; ledger row 23.

- **fw v23 — recovery admits ANY latched fault, gated on a RUN BOUNDARY.** The deadLinkOnly
  signature test is gone (it could not be widened: triggerFault() ORs bits into fault_flags
  while error_code stays first-cause, so "real fault, then sim stops" has no equality
  signature). A run boundary is `HIL_RUN_BOUNDARY_MS` (1000 ms) of link silence **anchored
  at the last accepted frame (`hilLastFrameMs`)** — the review round's headline fix (S1/C1):
  anchoring at the first dead State-99 tick would have added the 250 ms HIL_ZERO_MS latency
  and made a literal 1 s host gap unrecoverable. Sticky `hilRunBoundarySeen`; tracking runs
  in every State-99 phase; admission stays phase-3 + log-closed + 500 ms fresh debounce;
  one recovery attempt per boundary (hilWarmReset() clears the flag); a mid-scenario fault
  with the sim still streaming cannot self-clear (replay fault_latched semantics preserved).
  Other accepted findings: hilWarmReset() prints the outgoing error_code/fault_flags/
  error_source_state before clearing (S3 — the cause is not on the observation frame); the
  1 Hz [STATE 99] line carries live boundary/arm/phase status (S4 — 'S' is unreachable from
  State 99); three stale exact-0x8010 comments rewritten (C2); linkFresh hoisted (C3).
  Residual documented hazard (S2): a >=1 s host stall MID-scenario followed by resumed
  streaming forges a boundary and can warm-reset mid-run — mitigated host-side (below), not
  in firmware.
- **Tooling — self-describing HIL runs.** hil_plant_sim.py now logs CSV BY DEFAULT
  (auto-name `hil_<scenario>_<mode>_<ts>.csv` into HIL Results/; `--no-csv` opts out — note
  it also suppresses the hifi .events.jsonl); an explicit `--csv` whose CSV or either
  sidecar exists is REFUSED exit 2 without `--force` (suite children and
  hil_replay_suite --argv-for emit --force themselves). Every CSV gets `<csv>.meta.json`:
  written at start (status "running") and finalized atomically at exit
  (completed/interrupted/error) with scenario, argv, resolved config, a model-constants
  sha256 fingerprint (non-model families excluded, re-exports deduped; hash-different does
  not strictly imply model-different), git rev+dirty, and end-of-run results.
- **Mid-run warm-reset tripwire (review S2).** The sim counts observed mainState 99→non-99
  transitions (grace window 2.0 s classes the legitimate start-of-run recovery; a
  transition at exactly 2.0 s counts as mid-run); run_hil_suite marks a non-whitelisted
  mid-run reset INCONCLUSIVE (passed=false, rendered distinctly, "also FAILED n checks"
  when real checks failed too — INCONCLUSIVE never masks FAIL). comm-loss now REQUIRES
  exactly one mid-run reset (its tx gap widened 1 s → 2 s: exactly 1.0 s is knife-edge
  against the 1000 ms boundary); more than expected → INCONCLUSIVE, fewer → FAIL;
  unmeasured (old sim build / dead child) renders UNVERIFIED, never as zero. Stale-sidecar
  guards: results non-None + csv path match + created >= launch. --settle-s < 1.5 s warns
  (boundary may not reliably be crossed; child teardown/startup also counts toward the
  dead window).
- **Reviews:** firmware two-lens — 1 HIGH (S7: the operator's local BENCH_TEST/HIL_SIM
  flips must stay out of the commit), 4 MED (S1/C1 anchor, S2 tripwire, S3 evidence print,
  C2 stale comments), rest LOW — all accepted/applied except the S2 threshold raise
  (rejected: conflicts with comm-loss under the anchor fix). Tooling two-lens — no HIGH,
  8 MED (suite children refused by the new guard without --force; stale-sidecar trust;
  INCONCLUSIVE-masks-FAIL; sidecar exception-safety; error-path finalize-before-close;
  HIL_MODE "cannot self-clear" claims; K4 end-to-end coverage gap; D15 whitelist
  overcount), 12+ LOW — all accepted (3 partial), all applied.
- **Tests: 3535 production + 175 bench + 3993 HIL (C++) and 487 pytest + 7 skipped — all
  green, orchestrator-rebuilt from source.** New coverage highlights: exact-equality
  boundary tick, non-cumulation of separate dead windows, the anchor regression that would
  have caught S1/C1, never-had-a-frame fallback, warm-reset evidence print, end-to-end
  _run_plan/render_report inconclusive paths, real sidecar atomicity (os.replace raising),
  constants-filter sensitivity both directions.
- **Next bench:** flash fw v23 (edit HIL_SIM 0→1 first — repo defaults unchanged), rerun
  the full run_hil_suite and confirm a real-fault scenario no longer costs the rest of the
  plan; the hifi powered-Ag105 charge scenario and the Pi-bridge v4 parser audit remain
  from the fw v22 list. Housekeeping unchanged: analyzer exe rebuild; .venv_benchlog
  pandas/scipy.

---

## Status & session addendum (2026-08-30d, suite fix round + campaign 2 + SOFT-start TRCB fix + hil-agent-analysis skill)

Three orchestrated tooling rounds and a full HIL campaign in one session. FW stays v23
(no firmware change); tooling commits 7802466 and bfcd33f. All on main.

- **Suite/scenario fix round (7802466),** implementing the campaign-1 findings under two
  operator rulings — (a) LIMIT_I_FC_MAX stays 1.4 A (bench logs exceeding it used DC
  supplies; OC_FC on those traces is correct hardware replication) and (b) FC-charge +
  hard accel is infeasible BY DESIGN (scenarios demanding both must expect OC_FC).
  Grace-aware scoring (post-grace fault union judged, WARM_RESET_GRACE_S single-sourced,
  carried-in settle latches excused and named — the 23-false-FAIL fix); FAULT_EXPECTATIONS
  replaces FAULT_REQUIRED/FAULT_ALLOWED (require/allow_only/not_before_s/survive_to/
  events_require/signals_require, per-entry citations); scenario redesigns: charge-cruise
  REQUIRES OC_FC (ruling b), charge-regen is EMS-driven (`regen-harvest`: charge_goal only
  inside interpolated braking windows — a stepped timeline physically cannot sustain
  regen), charge-fault gains `chg_i_ceiling_a` 0.8 A and reaches its t=20 collapse,
  soc-depletion staggered/2.2 A/880 s, handoff-sag re-derived around the share-cut
  setpoint latch (the 0.60 A governor gate does NOT own the cut), scp-inrush 5.0 A from
  t=0 (fold binds at ~5.36 A > OC sum 4.4 A — no load folds without an OC), drive
  operator_required (--with-operator). Replay half: 2.5 s synthetic bring-up preamble +
  absent-rail nominals (BLG v1/v2 runnable), per-entry i_fc_clamp_a 1.3 (TP0010/53 keep
  UV-latch coverage; ruling-a honest), skip_preamble (ML0217 cold-boot INIT_FAIL),
  OC-quartet reclassification (ML0165/169/203/WP0097). Two-lens reviews: 2 HIGH (TP0010/53
  would OC before UV; ML0217+preamble can't INIT_FAIL) + 7 MED + contract lens, all fixed.
- **Campaign 2 (hil_report_20260830_203006): 38 runs — 36 PASS / 1 FAIL / 1 SKIP, every
  verdict correct.** Firsts: regen path end-to-end ×3 windows (path/sequencing only — the
  plant floors regen power; SOC fell), GENSTAT input-collapse response, share-cut latch
  (12 ms, guard at 24% margin), SOFT-state SCP cut (6.29 A), replay UV/INIT_FAIL coverage
  alive. Repeatability: bring-up ~1 ms/~1 mA across campaigns; UV dwell 19.992 ms;
  ems-drive-cycle sub-1%. Discovery: the hifi engine implements the DESIGN droop
  (0.316/0.633 Ω, ratio exactly 2.000) — ~4× bench K_DROOP_BUS; bannered, sag depths not
  bench-comparable. The FAIL (comm-loss) was a REAL OC_FC 3 ms after a validated recovery
  (Δ 1.1 ms) — root cause below. Ledger + HIL_SUMMARY.md in the report folder.
- **SOFT-start pre-charged-node fix + TRCB (bfcd33f, hil_electrical.py):** the comm-loss
  artifact (t_on recomputed from sagging v_in while v_ss_start latched; 3.9-6.8× current
  on a warm MOT_PWR close — the one path that closes into a pre-charged node). Both
  originally-adjudicated fixes REJECTED on measurement (latching t_on regresses cold
  0.2226→3.81 A; a stamp-skip clamp goes bang-bang 6.95 A); shipped: per-episode VIN
  high-water mark scoped to pre-charged entries (warm 6.82×→1.02×, cold byte-identical),
  then the focused review found the min(target,v_in) cap could sink −55 to −345 A of
  phantom charge (no reverse handling in SOFT) → replaced with the datasheet TRCB block
  (RT1987 §17.4/§17.6/Table 1: reverse comparator not restricted to post-soft-start;
  TD_ON admission gate; auto-restart without soft-start). scp-inrush re-verified on the
  faithful staged-bring-up sequence: scp_cut i_cut 6.2852 A vs hardware 6.290 (0.07%) —
  no event stolen (P3 closes onto a DARK node, +13.9 V forward; reverse trips need a
  pre-charged node). Known residual (documented, future work): the model ramp conflates
  slope with endpoint (true slew 645.5 V/s VIN-independent; cold +25% / warm −10% bias)
  — a constant-slew redesign moves the hardware-corroborated cold pins, needs its own A/B.
- **New skill `.claude/skills/hil-agent-analysis`:** the campaign-analysis pipeline (LIVE
  mode with finalization-aware sidecar watcher + dispatch-as-runs-land, POST-HOC mode;
  per-run briefs with the "PASS for the right reason" recomputation standard; FAIL
  classification scoring-defect/sim-artifact/scenario-gap/board-real; HIL_FINDINGS.md
  ledger + HIL_SUMMARY.md digest with manual-review pointers). references/ carries
  hil-conventions.md and both campaign ledgers as exemplars.
- **Tests: 602 passed + 14 skipped** across the five HIL pytest suites (TRCB-in-SOFT,
  TD_ON hold, warm/cold A/B pins, signals/events/grace-boundary coverage). Firmware
  suites untouched (3535/175/3993 from fw v23 stand).
- **Next bench:** rerun the suite — comm-loss PASSing is the acceptance test for the
  SOFT-start fix; soc-depletion (880 s) still needs a slot. Operator items: UV-dwell
  objective home (unreachable on the BT rail behind OC_BT — retire from handoff-sag or a
  v_bus_sense_offset scenario), Ag105 lazy-re-config + FC_CHARGE open-through-loss policy
  on real hardware, chopper coverage (needs energy into the motor node), Pi-bridge v4
  parser audit. Untracked/unowned in the tree: PSCAD/ — provenance unconfirmed this
  session, deliberately not committed. (tools/hil_report_analysis.py + test were this
  round's parallel session's mid-flight work — owned; see the 2026-08-30e addendum.)
  Housekeeping unchanged: analyzer exe rebuild; .venv_benchlog pandas/scipy.

---

## Status & session addendum (2026-08-30e, HIL report analysis pipeline: tools/hil_report_analysis.py)

Orchestrated tooling round (Opus implementer, independent Sonnet test-writer, parallel
Opus data-integrity + Sonnet contract reviews, fix round). Python tooling + skill docs
only; no firmware, wire-protocol, or benchlog_analysis change (reuse is all by import —
zero edits there).

- **tools/hil_report_analysis.py (new, ~1730 lines):** post-campaign analyzer for a
  `run_hil_suite.py` report folder. Per run: moves the CSV + `.meta.json` +
  `.events.jsonl` + child log into `scenario_<name>_<mode>` / `replay_<LOG>` subfolders
  (idempotent; orphaned-sidecar heal; shared parent files provably never moved), adapts
  the HIL CSV into the benchlog data-dict schema (`current`→`I_cmd`, `mdac_*` via
  `hil_plant_sim.mdac_fraction` — verified equal to the BLG `gFC` convention up to
  1 LSB; `share_act` derived with the 50 mA mask) and renders the `figures.py`
  `FIGURES` registry (KeyError/None = clean skip, anything else propagates) plus two
  HIL-specific figures (state/switch/aux/fault lanes; charger/SoC/substep). Replays
  additionally decode the source BLG (header fw wins over the sidecar, disagreement
  reported; corrupt BLG degrades, never kills the run), align on `replay_rec`
  (preamble/blind rows dropped), and get overlay, injection-fidelity, and
  response-deviation figures with RMS/max metrics into per-run
  `analysis.json`/`ANALYSIS.md`. Parent gets `ANALYSIS_SUMMARY.md`/`analysis_summary.json`
  + two summary figures. Honesty markings: post-grace vs whole-run fault unions kept
  separate; open-loop replay caveat everywhere; pre-v18 different-law `*`; unknown
  source fw = `?` "comparability UNVERIFIED", never silently same-law. PNG writes are
  tmp+`os.replace` atomic and mtime-invalidated against the CSV; a non-report parent is
  refused (exit 2). Needs numpy+matplotlib (miniforge python; NOT `.venv_hil`).
- **Validated on the real campaign** (copy of hil_report_20260830_203006): 37/37 runs,
  0 errors, idempotent second pass byte-identical. Two data findings: injection
  fidelity is CSV-rounding-clean (RMS ≤ 3e-5); gFC/gBT deviation vs a source log that
  never armed the share loop is a constant 0.298 (r=0.5 default vs logged 0) — real,
  explainable, and near-meaningless for such logs (a detector to suppress those rows is
  flagged, not built).
- **Reviews:** no HIGH; 5 MED (orphan-sidecar heal, two-electrical-modes-of-one-scenario
  silently dropped, non-atomic/stale figure writes, law caveat trusting the sidecar over
  the decoded header, corrupt-BLG killing whole-run analysis) + 8 LOW — all accepted and
  fixed except the case-insensitive-name collision (rejected, comment only).
- **Tests: 110 pytest green** (`miniforge3\python.exe -m pytest
  tools/test_hil_report_analysis.py`); existing HIL suites unaffected (602 + 14 skips).
  No committed venv holds numpy+matplotlib+pytest together — standing gap.
- **hil-agent-analysis skill updated (operator request):** POST-HOC Stage 0 now runs
  the tool BEFORE dispatch (briefs reference the subfolders + pre-built figures and
  paste `analysis.json` metrics); LIVE mode runs it as close-out step 0 after
  `partial: false` — NEVER while the suite is running (it moves the suite's files).

---

## Status & session addendum (2026-08-31, HIL command replay + suite fixes + duration trims)

Orchestrated tooling round (Opus implementer, independent Sonnet test-writer, parallel
Opus data-integrity + Sonnet contract reviews, fix round). Python tooling + docs only;
FW_VERSION stays 23; wire protocol frozen (40 B inject / 16 B observe / 22 B command).

- **`--replay-commands` (hil_plant_sim.py):** replay mode can now drive the firmware's
  22-byte Pi command packet at 50 Hz from the BLG's own recorded `v_sp`/`share_sp`
  (columns exist in every format v1-v7; blank velocity-invalid `v_sp` → 0.0). MODE_SAFE
  during the 2.5 s preamble, MODE_HYBRID after; charge_goal 0; values ZOH'd from THIS
  tick's already-sampled replay record so `--replay-speed` axis alignment is structural
  (the RATE stays 50 Hz of wall clock — speed > 1 under-samples the setpoint; use 1.0
  for fidelity). Requires `--replay`; --ems/--pi-live exclusions transitive. OPEN-LOOP
  on the plant side by construction — injected v_actual never responds; the drive loop
  fighting the trajectory is the stimulus. Replay CSV appends `cmd_v_sp`/`cmd_share_sp`
  after `replay_rec` unconditionally (blank without the flag; the column is the 1 kHz
  ZOH axis, the wire lags ≤ 20 ms). PiCommander gained `always_active`.
- **Replay suite de-vacuation (hil_replay_suite.py):** new `drive_loop_stepped` check
  kind (≥ 0.05 A on ≥ 50 recorded-window samples); 14 of 26 entries opt in
  (`replay_commands: True` + the check ordered first): ML0203/0137/0140/0146/0149/0151/
  0153/0164/0165/0169, YP0152/0166/0196/0214. The UV trio (TP0010/0053, WP0097), ML0217,
  TP0178/0201 and every v_sp≡0 current-mode 'T'/'W' log stay command-free (stimulus
  purity; measured, not assumed). Motor-response checks on command-free entries now tag
  "NOT EXERCISED (no command replay)" (passed=True + counters) instead of reading as
  plain vacuous PASSes. ⚠️ ML0203 replays a FULL-RANGE share_sp (0.0-1.0) — it actuates
  updateShareSetpointCutoff() both directions by design; share axis actuation rule added
  to the decision-rules comment. `build_sim_argv()` mirrors the flag (third modifier).
- **A5 fixed:** replay runs' results.json `metrics` was hardcoded `{}` — the latched
  end-state (the 0x8001 that carried into campaign 214819) was invisible.
  `ReplayCsv.metrics()` now populates final_fault_flags/final_state/unions from the
  single parse, and REPORT.md renders the fault line per replay entry.
- **A1 fixed (soc-depletion):** the `signal_soc_fell` 0.05 threshold was physically
  unreachable at soc0 0.15 (latch is a STATE condition at soc≈0.113 → ΔSOC_max 0.037;
  budget used bus-side 2.2 A where the pack draws ≈6.19 A). Now a disjunctive
  `soc_depleted` gate (new `any_of` spec kind + `fault_latch_bit` leaf: bit ∧ 0x8000 at
  t ≥ after_t), soc0 0.20, duration 400 s (latch est. ≈266 s; ~480 s cheaper).
- **Scenario durations trimmed** (operator request: ≤ ~3 s dead time after the last
  stimulus event): steady 10, step-load 10, sag 9, comm-loss 12, charge-cruise 15,
  charge-fault 25, ems-drive-cycle 58, handoff-sag 24, bringup 8, scp-inrush 6;
  drive (operator time) and charge-regen (profile to t=43) kept; soc-depletion kept at
  400 (model-uncertain latch). Suite wall time 34.4 → ~23.4 min pre-A1, and the import-
  time assert now walks not_before_s / survive_to.t / t_window uppers / any_of after_t
  against each duration. `bringup` gained survive_to {t:4.0, states {1,2}} (its
  completion was only ever asserted negatively); steady/step-load deliberately NOT
  given entries (would cost the --pi-live PI_TIMEOUT excusal for nothing).
  ⚠️ Baseline-statistics windows shrink vs campaigns 203006/214819 — medians/variances
  are not directly comparable across the boundary; per-event measurements are.
- **A3:** HIL_PLANT.md note — phase-0 VBUS→Ag105 bleed is a no-op under 8 ms TD_ON vs
  the 10 ms dwell. **A4 (early-exit guard) deferred** — A1's duration cut removed most
  of the dark-tail cost. Docs updated in lockstep (HIL_MODE/HIL_REPLAY_LOGS incl. Cmds
  column + checklist step, HIL_USER_MANUAL, PSCAD_SIM_DESIGN stale 60 s refs,
  hil-conventions.md two-class replay statement).
- **Tests: 674 passed + 25 numpy-skips (.venv_hil, five suites) / 718 with miniforge
  (incl. test_hil_report_analysis.py 113)** — orchestrator-rerun. hil_report_analysis
  adapter now drops all-NaN cmd_* columns (clean figure skip for plain replays).
- **Overnight autonomous session (operator away):** decisions taken without sign-off are
  logged in `OVERNIGHT_LOG.md` at repo root with the commit ledger for choosing a
  resume point.

---

# Rotated 2026-09-01e — addenda 2026-08-31b through 2026-08-31i (overnight campaigns 1–4, Rounds A/B/C, TPM toolchain, SDP sdp-v1, campaign 191509 + suite evaluation, sdp_policy_v2 fix round)

## Status & session addendum (2026-08-31b, overnight campaigns 1–4: 156 runs, zero board defects)

Four back-to-back full-suite campaigns run autonomously overnight (operator away;
`OVERNIGHT_LOG.md` has the decision log + resume points), each analyzed under the
hil-agent-analysis skill, with two fix rounds between. Commits 817295d → 9612369 →
82c8f75; report folders hil_report_20260831_{000518,010145,015024,021553} (local-only).

- **Round 1 (39/39 — first fully-green campaign on record, every PASS verified for the
  right reason):** the TRCB/SOFT-start fix CONFIRMED ON HARDWARE (comm-loss warm
  MOT_PWR re-close 1.041× physical, was 3.9×; reverse_block observed in soft-start;
  bleed τ to 0.02%); command replay proven at scale 1.00 by the V_SP_ZERO_THRESH bin
  scan (the I_cmd zero/nonzero boundary lands exactly on the firmware's 0.07 m/s —
  a constant the replay path never applies); replay-half vacuity 40.5% → 6.6%;
  soc-depletion A1 redesign validated (both gate arms independently green, latch
  270.704 s vs ~266 predicted, +1.8% fully explained by the rising pack current);
  duration trims cost nothing; the INA253 sense-side question (B1) was raised by an
  analysis agent and REFUTED same night against the schematic (output-side confirmed —
  sheets 1/2/4; margin claims stand). Fix round → 9612369: `share_loop_actuated`
  check kind (the share axis had ZERO checks across 122), `drive_min_frac` floors at
  ~half round-1 measured activity (a degraded command path now fails), i_cut band,
  `fault_first_t_whole_run` (the post-grace-scoped map mis-reads in-grace latch
  onsets), `switch_transitions`.
- **Round 2 (38/39):** the one FAIL exposed the scp-inrush KNIFE-EDGE — the sim's SCP
  cut (tick S+1 after the 8 ms TD_ON admission) races the firmware's OC teardown at
  S+L where **L = the observation round-trip = 1 or 2 ticks** (sub-ms host phase); the
  sim applies the observed switch word BEFORE stepping the solver, so a tie goes to
  the firmware. The celebrated 0.076% i_cut "repeat" was two draws of the same L=2
  coin. Plant trace bit-identical; board correct in both orderings. A headless bench
  proved the re-margin fix INFEASIBLE (a tick-S cut needs ~12.7 A = 1.49× RT_I_FOLD_HIGH
  — a hard short, not the SCP-margin case; the 5.0 A stimulus's claimed 15% fold margin
  also never existed — bench threshold ~5.53 A). Adopted instead (82c8f75): two-outcome
  `events_any_of` — A_fold_fired (1 scp_cut, i_cut 6.0–6.6, STRONGER) / B_fold_approached
  (0 cuts + MOT_PWR sw_ring 3.5–5.5 A + the OC latch, WEAKER) — the check names the
  outcome and tracks the L distribution instead of scoring a coin flip. The
  deterministic-fold path (stimulus TIMING redesign) is an open operator item.
  Everything else REPEAT CLEAN (comm-loss re-close 0.3696 A/ch EXACT; bringup peaks
  exact to 4 decimals).
- **Rounds 3–4 (39/39 both; round 4 ZERO structural diffs vs 3):** both branches of the
  two-outcome check validated live (L record across five campaigns: A,A,B,B,A —
  bimodal by mechanism). The handoff-sag cut-latency tracker (round-1 anomaly, −65%
  vs baseline) CLOSED with a corrected model: datapoint #5 (13.130 ms) broke the
  assumed [0,12) window and revealed the true one — uniform command-arrival phase over
  the **20 ms share tick** (all five points 2.850–13.130 ms fit [0,20); campaign-2's
  11.968 ms was never a distinct mode). Reopen only on a value ≥ 20 ms.
- **Tests: 712 passed + 25 numpy-skips (.venv_hil, five suites) / 756 (miniforge incl.
  test_hil_report_analysis).** All tooling; FW stays v23; wire protocol frozen.
- **Standing items** (unchanged unless noted): scp timing redesign (optional,
  operator); FU4 Idle→Run setpoint-arrival synthetic entry; Rs(SOC) calibration vs a
  real 2S pack (still sets soc_latch 0.113); early-exit guard (now minor); analyzer
  exe rebuild; .venv_benchlog pandas/scipy; Pi-bridge v4 parser audit.

---

## Status & session addendum (2026-08-31c, Round A: scp deterministic fold + FU4 synthetic replay entry)

Orchestrated tooling round (two parallel Opus implementers, independent Sonnet test-writer,
parallel Opus data-integrity + Sonnet contract reviews, orchestrator fix pass). Python
tooling + one committed data file + docs; FW stays v23; wire protocol frozen. Closes the
two operator-queued items from the ratification review: the scp deterministic-fold
stimulus redesign and FU4.

- **scp-inrush is now DETERMINISTIC — the two-outcome check is retired from the table.**
  Root cause of the old S+1 race (feasibility bench): the flat t=0 load faded in through
  the plant's 1.0 V Norton load floor (`V_MOT_LOAD_FLOOR`, hil_electrical.py:197), so the
  fold engaged ~1.3 ms after SOFT entry and the cut landed one tick past admission —
  racing the firmware's OC teardown at L=1/2. New three-phase stimulus (hil_plant_sim.py
  `SCP_INRUSH_*` block): the P3 ramp runs UNLOADED; a 6.5 A fold pulse steps in when
  V-MOT crosses `SCP_INRUSH_ARM_V` 1.2 V mid-soft-start (above the floor -> full current
  in one substep -> fold binds and CUTS INSIDE THAT SAME 1 kHz TICK, >= 600 us before any
  board word can arrive); a one-shot latch withdraws it (the 64 ms retry soft-starts
  clean to ON); a 5.0 A run load at +110 ms latches OC_FC deterministically. The load
  moved 5.0 -> 6.5 A because at 5.0 A the fold needed v_in > 15.2 V, which the P3 gate
  (13.5 V) does not guarantee. The one-shot re-arms on the observed mainState 99->non-99
  edge (review M1 — a forged-boundary warm reset re-runs bring-up and must get a clean
  phase-1 ramp, not a standing run load). `FAULT_EXPECTATIONS["scp-inrush"]` is
  single-outcome `events_require` again (count 1, where MOT_PWR); `events_any_of` STAYS
  in the codebase, table-unused, for future races.
- **VALIDATED ON HARDWARE + BAND DERIVED LIVE: i_cut = 6.3797373 A BIT-IDENTICAL across
  three live board runs** (fresh-boot cut at t~0.102; post-latch runs at ~0.602 behind
  the fw v23 500 ms recovery debounce; full cut->retry->ON->run-load->OC_FC->teardown
  sequence every time). Band pinned [6.15, 6.55] bracketing the headless substep sweep
  (6.256-6.398 over n_sub 8-100). The feasibility bench's 5.79-5.88 A figure was its own
  rig's bring-up-emulation artifact. A `provisional_note` expectation mechanism (renders
  a [PROVISIONAL: ...] qualifier into events_require check details) was added for
  not-yet-derived thresholds and the scp key deleted same-day once the band was measured.
- **FU4 — synthetic Idle->Run setpoint-arrival replay entry `SY0001`** (new SY prefix =
  synthetic, logs/SY0001.BLG, BLG v3/fw 23, 2500 records, committed + byte-deterministic
  from stdlib-only tools/gen_fu4_replay_log.py, sha pinned by test). Stimulus: v_sp held
  2.0 m/s from record 0 (doState1() zeroes v_setpoint on the transition regardless of
  payload, .ino:5382-5410, so the real setpoint structurally lands on the SECOND 50 Hz
  packet), step back to 0 at +1.5 s through the V_SP_ZERO_THRESH cutoff; v_actual pinned
  0 (isolates the setpoint stimulus; open-loop rail during the hold is EXPECTED per the
  suite's FU5 note). New check kind `steps_onto_rail_within` (|I_cmd| >= 11 A within
  0.15 s of the preamble boundary; budget includes the Run-transition packet the
  original 0.08 s spec missed, + packet-loss headroom note). Entry is `provisional` (no
  drive_min_frac until a first campaign measures the baseline, FU3 precedent). Suite is
  now 40 runs / 27 replays.
- **Review round:** 1 HIGH (H1 — the "no not_before_s/survive_to" derivation cited a
  0.7 s grace window; the constant is 2.0 s, and a require+not_before_s would FAIL
  against the post-grace-scoped fault_first_t, not vacuously pass — comment rewritten),
  3 MED (M1 re-arm above; M2 HIL_PLANT.md taught the retired flat load; M3
  provisional_note), 7 LOW + 2 contract findings — all accepted, all applied
  (orchestrator-applied directly; L1 rename deferred to a comment fix).
- **Tests: 738 passed + 25 skipped (.venv_hil, five suites) / 113 (miniforge
  report-analysis) — orchestrator-rerun.** New coverage: three-phase state machine incl.
  re-arm-after-reset, single-outcome band edges at the live values, events_any_of
  synthetic-table mechanism regression, provisional_note suffix mechanism,
  steps_onto_rail_within three branches, SY0001 sha/header/determinism pins.
- **Standing items CLOSED: "scp timing redesign (optional)" and "FU4".** Next rounds
  queued: Round B (DP-informed EMS routes 2+1 + the Gfc H2 metric — research digested,
  see the round report), Round C (scenario expansion: Y-profile EMS x4, FTP75 per
  strategy, MPPT tracking, +3 orchestrator proposals).

---

## Status & session addendum (2026-08-31d, Round B: DP-informed EMS + Gfc H2 metric)

Orchestrated tooling round (two sequential Opus implementers [Route 2 then Route 1],
independent Sonnet test-writer with a reconciliation pass, parallel Opus data-integrity +
Sonnet contract reviews, Opus fix round). Python tooling + docs; FW stays v23; wire
protocol frozen. Implements the operator's DP brief (routes 2+1) + the Gfc H2 transfer
function.

- **H2 metric (Gfc).** `H2Consumption` in hil_plant_sim.py: the PhD student's Gfc
  (== the commented-out H2_tf at references/EMS/DPtrial.m:51-52), ZOH modal/parallel
  first-order at 1 kHz (Tustin REJECTED — the 1.887e6 rad/s pole maps to z=-0.9997
  Nyquist ringing; tf2sos biquads REJECTED at 8.2e-3 err), update-then-read, input =
  STACK power (FuelCellSource v_terminal x i, not the bus-side product), ten pinned
  validation vectors at rtol 1e-9, import-time DC-gain assert (rel 1e-13) tripwires
  silent coefficient edits. CSV columns h2_rate_gps/h2_cum_g (simulated mode only,
  append-only tail) + exit summary. **SCALE PORTABILITY RESOLVED (operator ruling
  2026-08-31): the 720 in den[0]=1044=720x1.45 is the full-size FUEL CELL's OCV, and
  the TF needs NO adjustment — P_fc (W) in and g/s out both ride the system's energy
  scaling (references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf,
  Tan/Yadav/Assadian).** H2 figures are the model's estimate proper; surviving caveat is
  stack identification only (TODO(calibrate); DC gain implies eta 47.25% vs the DP's own
  55% static proxy, +16.4% — a model-choice note).
- **`soc-band` (Route 2)** — causal charge-sustaining EMS strategy: SoC0 capture,
  +/-SOC_BAND_HALF deadband, proportional share bias saturating at [0.25, 0.75], causal
  cruise gate (trailing window, never future profile points — operator ruling b), charge
  admission with dual hysteresis (i_tot 0.60/1.30 A; deficit enter-at-band-edge /
  hold-to-zero). SIM-ONLY flagged (fb["soc"] is plant truth outside
  FB_TELEMETRY_EQUIV_KEYS; V_batt-based estimation is the portable path, future work).
  Scenario `ems-soc-band` (61 s two-cruise-level profile, 1.0 A drain t=10-38,
  chg_i_ceiling_a 0.8, four signals_require). Route 2's own offline walk caught + fixed
  a real defect (a charge window admitted at the 1.5 m/s cruise -> single-source FC
  1.42 A > LIMIT_I_FC_MAX; drain end moved 35->38 s).
- **`dp-replay` (Route 1)** — offline-optimal benchmark: tools/gen_dp_ems_table.py
  (miniforge numpy) ports the MATLAB DP's STRUCTURE with three declared defect fixes
  (linear interpolation of J — nearest-grid quantized away ~99% of realistic steps;
  stored argmin policy; raise-on-infeasible), solves against the sim's nonlinear
  BatterySource (declared divergence from the constant-720V lossless MATLAB pack),
  stage cost on the Gfc DC gain, charging masked to cruise (ruling b), --lambda-dev
  default 0 (a running penalty re-ranks and broke the lower bound by 0.07% — measured),
  --match-terminal-soc bisection (residual +1.6e-6). Checked-in table
  tools/dp_tables/dp_ems_table_ems-dp-replay.csv (byte-deterministic; .gitattributes
  -text guards CRLF; header carries every consumed tunable) played through the 50 Hz
  commander by strategy `dp-replay` with startup refusals: profile fingerprint,
  charger-accounting vs resolved engine, and ten header-vs-live drift comparisons
  (three constants escape the fingerprint — measured by mutation). Scenario
  `ems-dp-replay` is hifi-only (accounting match; "any" would hard-fail a simple-pref
  campaign). Comparison surface: final_h2_cum_g/delta_soc scenario metrics in
  results.json/REPORT.md.
- **OFFLINE RESULT: DP -14.33% hydrogen vs soc-band at matched terminal SoC**
  (1.17564e-2 vs 1.37227e-2 g), and **the DP opens the charger on ZERO stages** — 
  share-shifting buys 0.405 SoC/gram vs the Ag105's 0.169; a finding, not a gap.
  **VALIDATED LIVE (first hardware execution of both):** soc-band 0.012842 g, dp-replay
  0.011640 g (-9.4% live; the DP's live total within 1.0% of its own offline
  prediction), both 61 s fault-free, share endpoints as designed (0.689 FC-biased vs
  the table's 0.250 rail).
- **Reviews:** contract 1 HIGH (the operator's scale-portability ruling needed a
  9-site sweep beyond the primary banners — applied everywhere incl. the regenerated
  table + REPORT renderer) + 1 MED; data-integrity 2 HIGH (same sweep; the standing
  .ino-flags commit exclusion) + 6 MED (accounting runtime guard; fingerprint drift
  guards; match-residual header lines + hard-fail without --allow-unmatched; the
  DC-gain assert; constants_hash changelog — the hash MOVED 2026-08-31, 20 additive
  names, pre-2026-08-31 hashes not comparable; deficit-gate hysteresis) + 9 LOW — all
  accepted, all applied. Table regenerated: sha256 08ddc077...; comparison numbers
  UNMOVED.
- **Tests: 811 passed + 27 skipped (.venv_hil, six suites incl. new
  test_gen_dp_ems_table.py) / 761 (miniforge incl. report-analysis) — orchestrator-
  rerun.** references/EMS/ now holds the PhD student's MATLAB (DPtrial,
  DP_EnergyManagement2, NEW SDP_EnergyManagement2 + TPM.mat — stochastic-DP source
  material for a future round); the ~330 MB simulink_pdem_output_stochastic_*.mat
  outputs are gitignored, local-only.
- **Next: Round C** (scenario expansion: 4 synthetic Y-profile EMS scenarios spanning
  {0.30/0.70 vs 0/1 share band} x {1 vs 3 m/s Vmax}; FTP75 scaled to 3 m/s peak per
  EMS strategy; Ag105 MPPT-tracking emulation; +3 orchestrator proposals). The SDP
  material suggests a future stochastic-DP route beyond Round C.

---

## Status & session addendum (2026-08-31e, Round C: scenario expansion — Y-profiles, FTP75, MPPT, watchdog, staircase, charge-to-full)

Orchestrated tooling round in two implementation waves (Opus x2), independent Sonnet
test-writer (synchronized hold-and-reconcile across the fix round), Opus data-integrity +
Sonnet contract reviews (the latter with two verification sub-agents), Opus fix round.
Python tooling + committed data + docs; FW stays v23; wire protocol frozen. Ten new
scenarios (15 -> 21 registered; plan 52 runs), two prerequisites, five check-kind
extensions, one datasheet correction, one open hardware question.

- **Prerequisites:** per-scenario `ems_run_exit_s` (module run-exit constants would have
  ended a 350 s cycle at t=55) and generic `aux_preload_a` (ramped; import-assert refuses
  it on bespoke-branch and dp-replay scenarios — the DP fingerprint does not cover it,
  deferred until a second DP table lands). Existing scenarios byte-identical.
- **Four `ems-y-*` scenarios**: the firmware's 16-region State-98 'Y' COMBINED_PROFILE
  (.ino:3162-3179) transcribed verbatim (assert-pinned, 40000 ms) with
  `advanceComboRegion()` semantics reproduced exactly (clip AFTER interpolation), one
  factory over {b 0.30/0.00} x {Vmax 1/3}. Split-by-band objectives: b30 + 0.60 A preload
  = genuinely closed-loop share tracking; b00 unloaded = setpoint-latch cut/restore
  topology coverage — the RESTORE assertions are the suite's first-ever latch-release
  checks. **Live: BT cut 22.021/restore 23.503, FC cut 34.311 (predicted 34.31)/restore
  36.51 — millisecond agreement, fault-free.**
- **Two `ems-ftp75-*` scenarios** (hold-5050, soc-band) on the FIRST 340 s of the EPA
  FTP75 (operator-directed, matching references/Systemic_Scaling_...pdf; the cut lands in
  a native standstill, 0 mph from t=333). Raw ftpcol.txt committed under
  references/drive_cycles/ (sha-pinned, .gitattributes -text guards autocrlf — review M2)
  -> stdlib generator -> generated tools/ftp75_profile.py (234 points, err 4.4e-16,
  import-bound to its generator's constants so a stale/hand-edited module is an
  ImportError — review M3). Peak 56.7 mph @ t=240 -> 3.0 m/s. FTP75_PRELOAD_A 0.65
  (closed-loop gate 100% of the run). socband variant allows OC_FC (ruling b; mechanism
  is the share-bias-at-peak transient — the preload forecloses the charge window, NOT the
  spec'd charging path). Suite gate `--with-ftp75` (default OFF; SKIP records; +11.7 min).
  DP-table variant deferred (~21 min offline; generalizations landed).
- **Ag105 MPPT CORRECTED + EMULATED; open hardware question R1.** Datasheet p.10: the
  MPPT is an INPUT-VOLTAGE-THRESHOLD regulator (default 18 V, MPPTS open), NOT
  perturb-and-observe — CLAUDE.md §3 corrected (see the dated note there), the two stale
  .ino comments (:10029, :10047) deferred to the next firmware round. Threshold gate
  emulated behind `mppt_emulation` (default False, existing traces byte-identical). NEW
  scenario `mppt-tracking` (mppt-harvest strategy, cruise + braking charge windows):
  **the predicted release/re-assert HUNT is CONFIRMED ON HARDWARE — 138 MPPT_DISABLE
  toggles, ~40 ms period (the "80 ms" first recorded here was a mis-derivation —
  corrected by the 2026-08-31 campaign's measured 40.05 ms median, which the
  toggle count itself requires), status 0x09 released-and-refusing observed.** Under the
  datasheet-default threshold, cruise harvest CANNOT hold on a 15.95 V bus: if no MPPTS
  resistor is fitted (R1, operator to check the MPPTSEL header), the real charger hunts
  the same way and the fix is firmware writing reg 0x02 (~12 V).
- **`pi-silence`**: the Pi watchdog's FIRST-EVER exercise — injection alive, commands
  muted at t=8 (PiCommander.mute_after). **Live: carried-in latch cleared at 0.501 s,
  watchdog re-latch at 8.498 s (PI_TIMEOUT_MS 500 + phase), motor halted, State 99 held**
  (injection alive -> no fw v23 run boundary -> latch persists, as derived). New
  `child_tx_healthy` check (shared child_stream_continuity() with the --pi-live excusal)
  is the PI_TIMEOUT-vs-HIL_STALE discriminator (same 0x8010 bit; error_code still not on
  the observation frame — standing protocol item).
- **`share-staircase`**: two-phase characterization (governor rails at 1.2 A: I_fc swept
  0.915 -> 0.300 live vs predicted 0.90/0.30; cut/restore excursions at 0.55 A). New
  `switch_fall_latency_ms` check kind (+ edge:"rise") turns the closed handoff-latency
  tracker into per-campaign measured data — live latencies 16/15/4/17 ms, all in the
  [0,20)+L model. Premise corrected in-source: the 20 ms is COMMAND-ARRIVAL phase
  (PI_CMD_HZ 50), not a firmware tick (SHARE_CTRL_TS_US is 1000 us).
- **`charge-to-full`**: first-ever FULL/CV coverage (suite --soc0 0.990 override). **Live:
  GENSTAT FULL at t=100.32 (predicted ~100), CV flag, full taper, FC_CHARGE held open —
  the firmware's documented no-action-on-FULL baseline asserted positively.**
- **Check-kind extensions** (all with import-shape asserts): aux_bit, value_mask/
  value_equals (closes the hex-string ag105_status float() silent-skip trap),
  signals-side max_value (unmeasured FAILS), switch_fall_latency_ms, child_tx_healthy.
  Plus: strictly_decreases_by windows must clear pi_timeline entries by >= one command
  period (review H2 — the staircase check opened ON its stimulus and lost the 50 Hz
  phase race ~19/20), max_ticks-only bit specs need a companion or vacuity_note, max_ms
  specs refuse stray tick bounds. `run_hil_suite --list` cp1252 crash fixed permanently
  (stdout/stderr utf-8 reconfigure + the two replay-description arrows -> ASCII).
- **Reviews:** data-integrity 2 HIGH (the standing .ino staging exclusion; H2 above) +
  4 MED (M1 mppt toggle ceiling re-derived 10000->2200 vs the reachable 3000; M2
  .gitattributes; M3 generator binding; M4 dp-replay/preload guard) + 9 LOW; contract
  (with sub-agents): Y-table CLEAN row-by-row (both reviewers independently), 3 MED
  (two .ino citation fixes; constants_hash changelog — 19 additive names enumerated by
  running the collector, pre-Round-C hashes not comparable) + LOWs. All accepted, all
  applied.
- **Tests: 927 passed + 27 skipped (.venv_hil, six suites) / 1233 (miniforge, all
  tools/) — orchestrator-rerun.** Live smokes: all six board-testable new scenarios ran
  against fw v23 with the designed outcomes (details above); the four ems-y/ftp75
  variants not smoked live (b30-v1, b00-v3, both ftp75) exercise the same code paths.
- **Untracked, other-session-owned, deliberately NOT committed:** tools/tpm_generator.py
  + test, references/EMS/TPM_{fullsize,scaled}.mat + TPM_generator.m + Pdem_cycles/ +
  generated/ (and the Round-B TPM.mat is deleted in that workstream), docs/
  HIL_SCENARIOS.md, PSCAD/. The owning session should commit them.
- **Next:** first full campaign over the 52-run plan (the new entries' modelled
  thresholds calibrate there); R1 answer (MPPTSEL header) settles the mppt-tracking
  expectation + the reg-0x02 firmware question; FTP75 DP table when wanted
  (--with-ftp75 + ~21 min offline solve).

---

## Status & session addendum (2026-08-31f, TPM toolchain: Markov demand-transition generator)

Parallel EMS-strategizing session's round, committed and recorded here by the SDP session
that consumed it (the TPM session deferred its addendum). Commit db6e7ce; Python tooling
only, FW stays v23.

- **tools/tpm_generator.py (miniforge numpy/scipy; NOT .venv_hil):** Python port of the
  PhD student's references/EMS/TPM_generator.m. Decodes the ten opaque MCOS Simulink
  Pdem cycle files (~315 MB, gitignored, sha256es pinned in the sidecars), replicates
  MATLAB interp1-spline/discretize/colon semantics, and at dt=1.0 reproduces
  TPM_scaled.mat BIT-IDENTICALLY (`--validate` gate; sE cancels under normalization so
  TPM_fullsize.mat is the same matrix). Library API: load_pdem_cycle, build_tpm,
  rescale_gamma (gamma_eff = gamma_base**(dt/dt_base)), matlab_discretize, SM/SL/SE.
  104 tests (tools/test_tpm_generator.py, miniforge pytest).
- **Artifacts in references/EMS/generated/** (each with a .provenance.json sidecar):
  `TPM_dt1_hil.mat` is the primary SDP input — 25x25, `--hil` preset (V2 dropped as a
  bit-identical duplicate of V1, V3 truncated to its native 600 s, cross-file boundary
  transitions excluded, empty rows = self-transition), 0 zero rows, diagonal mass 76.2%.
  Also dt0p5, and parity artifacts incl. TPM_scaled_dt0p02.mat (99.0% diagonal — why
  20 ms is the wrong decision step). Sidecars carry the UNITLESS contract: bins
  partition normalized [0,1]; the CONSUMER owns energy scaling via
  `normalization.p_dem_scaled_min_w/max_w` (-1.1248/+1.6398 W), clamping out-of-range
  to end bins. Sidecar JSONs are LF-normalized with a `* -text` .gitattributes (SDP
  round fix MED-1) so recorded hashes are checkout-independent.
- docs/HIL_SCENARIOS.md (suite scenario catalog) landed with this round.

---

## Status & session addendum (2026-08-31g, SDP EMS strategy: sdp-v1 + ems-sdp + H2 proxy)

Orchestrated tooling round (two parallel Opus implementers, Sonnet test-writer x2 rounds,
parallel Opus data-integrity + Sonnet contract reviews, sequenced fix rounds). Python
tooling + docs; FW stays v23; wire protocol frozen. Ports the PhD student's
references/EMS/SDP_EnergyManagement2.m onto the HIL sim, consuming the TPM toolchain.

- **tools/sdp_ems_solver.py (new, miniforge):** infinite-horizon value iteration over
  (SoC grid 101 pts [0.55,0.65] x 25 TPM demand bins) from TPM_dt1_hil.mat + sidecar
  (min/max read at solve time per the operator ruling), gamma 0.95 via rescale_gamma,
  declared decisions D1-D10. **D1 is load-bearing: per-1s-step |dSoC| is 4.4e-5 vs 1e-3
  grid spacing, so nearest-grid transitions (the MATLAB's min-abs rule) move NOTHING —
  measured: the un-interpolated policy is share=0 everywhere.** J is linearly
  interpolated over SoC (the Round-B DP fix, again). **alpha re-derived 500 ->
  0.2569444** via coulombic-energy scaling (500 x (7.4V x 5Ah)/(720V x 100Ah)) — the
  marginal rate preserving the full-size trade-off; the level-form alternative (0.01367)
  is measurably degenerate (share=0 everywhere; --alpha-mode level keeps it reachable).
  Actions: 21-step share ladder x charge_goal {0,1}; operator ruling (b) baked as
  charge_forbidden_bins 12-24 (dwell-quantile 0.90 + an FC-budget rule). Converged 455
  sweeps, delta 9.8e-13. Bakes tools/sdp_policies/sdp_policy_v1.json (schema
  sdp-policy-v1; policy-block sha256 dbe42d1b... — the STABLE identity; the byte sha
  moves with generated_utc on every --force, never pin it).
- **sdp-v1 strategy (hil_plant_sim.py, stdlib):** SIM-ONLY (fb["soc"] is plant truth).
  SoC0-RELATIVE regulation (soc_rel = 0.6 + soc - soc0, soc-band's capture convention)
  so ems-sdp runs at default soc0 0.7 and is three-way comparable. 1 s decision ZOH
  under the 50 Hz commander. P_dem = V_bus x (I_fc + I_batt) (telemetry-equivalent keys
  only), normalized via the artifact's sidecar-derived min/max, END-BIN CLAMPED —
  **real bus demand (~1-20 W) exceeds the ideal-scaling range (-1.12..+1.64 W), so
  residency pins to bin 24 in practice; counted and reported, a scale-fidelity boundary
  not a bug.** **Hardware-envelope share clamp [0.15, 0.85]** (soc-band's exact clamp;
  fix round): the raw table rails at 1.0, which cuts BT_BUS and runs single-source FC
  into LIMIT_I_FC_MAX (OC_FC at ~13 s, run truncated — the original design, reworked).
  Clamped: governed I_fc 1.16 A at the 1.45 A drain peak, 17% OC margin, fault-free
  full-length run; last_share_raw + clamp counter keep the rail visible. Loader
  validates finiteness + ranges (a NaN share would otherwise emit 0.15 via max()
  semantics; a raw NaN charge_goal diverges logged-vs-board state). Per-run provenance:
  bind_scenario() shas the artifact; meta sidecar gains config.sdp_policy for sdp-v1
  runs. Known documented degeneracy: the SoC-grid FLOOR node (row 0) commands share 0.0
  (D3 clamp-tie, tie-break picks least-hydrogen) — unreachable in ems-sdp (needs 0.05
  SoC fall vs ~0.006), pinned by test.
- **h2_sdp_cum_g CSV column:** the student's static proxy P_fc_stack/(0.5 x 120000),
  same clamped input as the Gfc integrator by construction (one step(), one reset());
  proxy under-reads Gfc ~5.5%. Suite metric final_h2_sdp_cum_g alongside final_h2_cum_g.
  The solver's J is BUS-side P_fc; never difference a J against a logged hydrogen total.
- **ems-sdp scenario:** stimulus IDENTICAL to ems-soc-band (same profile list object,
  duration 61 s, ceiling 0.8 A, drain branch) — the comparison set is now
  soc-band (causal heuristic) / sdp-v1 (causal optimal-policy) / dp-replay (non-causal
  bound) on one stimulus. FAULT_EXPECTATIONS: fault-free, survive_to t=50, five signal
  checks incl. cmd_share_sp >= 0.84 (discriminates vs 0.75 and 0.50) and I_fc >= 1.00 A.
  Charging is structurally unreachable here (bin 24 is forbidden) — asserted, not hoped.
- **Reviews:** contract — 1 MED (undeclared convergence-ordering deviation -> D10: the
  MATLAB's break-before-update keeps a one-sweep-stale J, likely its own bug) + the
  floor-node banner falsity + gamma dt_base note; data-integrity — 4 MED (checkout-
  dependent sidecar sha -> LF + -text fix; missing per-run artifact recording; the alpha
  rationale's "~31x smaller" was wrong in VALUE AND DIRECTION (per watt-second the rig
  moves 1946x MORE; the true figure is the 18.8x per-stage ratio) -> artifact
  regenerated; loader finiteness/range) + LOWs incl. the .gitattributes overclaim. All
  accepted, all applied. Reviewer perturbation sweep: the charge decision is ROBUST
  (600 charge cells under +/-5% alpha, 0.5-0.9 A ceiling, 12-16.5 V bus, -20% capacity;
  flips only at 1.2 A where the FC-budget rule forbids all) — supersedes the
  implementer's "knife-edge ~1.07" impression.
- **Tests: 984 passed + 26 skipped (.venv_hil five-suite set) / 147 (miniforge:
  sdp_ems_solver + gen_dp_ems_table + tpm_generator) / 113 (report-analysis) —
  orchestrator-rerun.** Provenance pins: tpm.sha256 + sidecar sha vs the tree, the
  policy-block digest, the floor-node exception.
- **Untested residuals (declared):** bind_scenario's banner/ignored-args, the solver's
  load_sidecar error branches.
- **Next:** full campaign (all scenarios incl. --with-ftp75) with live
  hil-agent-analysis, then a higher-level utility evaluation of the HIL suite for the
  EMS-testing mission (operator-queued in this round's brief).

---

## Status & session addendum (2026-08-31h, campaign 191509: first full post-A/B/C+SDP campaign + suite evaluation)

Full 53-run campaign (`--with-ftp75`; drive operator-gated SKIP) live-analyzed under
the hil-agent-analysis skill (10 per-run agents + adversarial replay audit + tool
pass). **52 PASS / 0 FAIL / 0 INCONCLUSIVE — every scenario verdict recomputed
right-for-the-right-reason; zero scoring defects; zero board defects.** Ledger:
`HIL Results/hil_report_20260831_191509/HIL_FINDINGS.md`; digest HIL_SUMMARY.md;
program evaluation `HIL Results/HIL_SUITE_EVALUATION_20260831.md`.

- **EMS lever pricing hardware-measured on two independent stimuli:** share-shift
  0.409-0.415 SoC/g (61 s cycle AND 340 s FTP75, 2.3% apart; offline 0.405);
  Ag105 charging ~0.156 SoC/g (offline 0.169) — charging confirmed the ~2.6x
  worse lever. h2 totals repeat Round-B smokes to <0.05%.
- **Three-way EMS on one stimulus:** sdp-v1 0.0125424 g/-0.00166 SoC beat soc-band
  0.0128475/-0.00206 on both axes; dp-replay 0.0116403/-0.00203 (-9.40%);
  dp-vs-sdp sit on the same frontier (equivalent-H2 0.003% apart). HONESTY:
  sdp-v1 emitted a constant clamped 0.85 (demand pinned to TPM bin 24 ~98% of
  decisions under the ruled sidecar map) — plumbing/provenance validated, policy
  interior unreachable. Operator decision queued: re-normalized consumer demand
  map (+ re-solve) vs accepting a constant-0.85 benchmark leg.
- **Firsts validated:** scp i_cut 6.3797373196569644 A now 4/4 bit-exact; fw v23
  any-fault recovery cleared a carried ERR_PI_TIMEOUT (fw v22 would have refused);
  latch-RESTORE both channels/directions; watchdog latch triple-attributed
  (485-vs-250 ms discriminator); FULL/CV repeat to 0.01%; MPPT hunt reproduced;
  FTP75 drive tracking p95 2.96 mm/s incl. the 3 m/s peak; observation round-trip
  floor L ~= 1.9 ms measured; SY0001 rail step 27.92 ms vs 150 ms budget.
- **Fix queue (ranked, in the ledger): 5 MED** — ems-sdp coverage companion;
  dp-table sidecar provenance block; cmd_* CSV column semantics doc (columns move
  at the NOMINAL timeline instant, not the send tick); uv_not_latched on
  TP0178/TP0201 vacuous-untagged (+ the TP0178 "10 ms dwell" record correction);
  fc_bus_restored knife-edge (min_ticks 1500 = 100% of its window — one dropped
  frame fails a correct board) — **plus LOWs** (FTP75 threshold bands + preload
  budget -2.6%; socband_fc_carried re-derivation (governor falsifies its idle
  justification); Y_AUX_LOAD_A ~0.85 for a deliverable b30 bound; SY0001
  drive_min_frac 0.30 de-provisionalization; first-boot fault-bit variability
  note (0xA010 this time — third distinct signature); key_metrics warm-reset
  label). The mppt "80 ms" record error is corrected in place (true period 40 ms).
- **Suite evaluation verdict** (full document in HIL Results/): ready TODAY for
  relative EMS ranking (Mode A) + firmware preemption; one audit away (Pi v4
  parser) from Mode B; one calibration away (Gfc stack identification) from
  absolute H2 prediction. Recommended order: fix round -> Pi parser audit ->
  Mode-B EMS-trio campaign -> SDP re-normalization -> measured-droop sim mode ->
  stack ID.

---

## Status & session addendum (2026-08-31i, fix round + SDP demand-map re-normalization: sdp_policy_v2)

Orchestrated tooling round (two sequential Opus implementers, Sonnet test-writer, parallel
Opus data-integrity + Sonnet contract reviews, Opus fix round) implementing the
campaign-191509 fix queue AND the operator-approved SDP scale-gap fix. Python tooling +
docs; FW stays v23; wire protocol frozen.

- **SDP demand map is now CONSUMER-OWNED at rig scale (solver decision D11).**
  `sdp_ems_solver.py --demand-map MIN MAX` (default **[0, 25] W**, from campaign-191509
  measured P_dem 0–22.887 W; `--demand-map-sidecar` keeps the old path and reproduces
  v1's policy block BIT-IDENTICALLY — the re-map is provably the only change). Re-solved
  → `tools/sdp_policies/sdp_policy_v2.json` (455 sweeps; policy-block sha
  `740c802e99dd…`; charge_forbidden_bins [12..24]→**[6..24]** — the FC-budget rule
  finally binds at real watts; 294 charge-enabled cells vs v1's 0; share ladder
  {0, 0.90, 0.95, 1.00}). Strategy renamed **`sdp-v1` → `sdp-v2`** (no alias — a
  results.json can never silently mix laws); alpha unchanged (map-invariant). Offline
  walk over the campaign trace: **13 demand bins visited (v1: 1), zero clamps, a
  charge window t = 41–58 s** that v1 structurally could not produce. HONESTY: the
  emitted share is STILL a constant 0.8500 — every table value exceeds the [0.15, 0.85]
  hardware clamp; the bang-bang is structural (piecewise-linear stage cost → vertex
  optima). Discriminators are therefore (a) the new **`cmd_share_sp_raw`** CSV tail
  column (pre-clamp table request; None-seeded, blank until the first decision) and
  (b) the **FC_CHARGE switch actually opening** — both scored in the re-derived 8-check
  ems-sdp entry, whose three new checks carry a `provisional_note` (first-campaign
  thresholds; rendering extended so provisional qualifiers ride signals_require too,
  not just events). ⚠️ Derived prediction: **~1 Hz FC_CHARGE chatter** (memoryless
  policy, no hysteresis; charger draw pushes demand into a forbidden bin) — within all
  current budgets; hysteresis is an operator decision if the first v2 campaign shows it
  undesirable. ⚠️ Campaign-191509 sdp-v1 EMS totals are a DIFFERENT DECISION LAW — never
  quote them against v2 runs.
- **Fix queue: all 16 items landed.** Highlights: `config.dp_table` sidecar provenance
  (file sha + LF-normalized data-rows-only `table_sha256`, positional header exclusion);
  TP0178/TP0201 uv_not_latched de-vacuated via new replay check kind
  `v_bus_min_in_band` (12.0, 12.30] — and the TP0178 record CORRECTED: the "10 ms
  dwell" did not survive replay (V_bus floor 12.1489 V is ABOVE the limit, dwell
  0.0 ms); `fault_latched` gained `not_before_s` (ML0217 0.5 s) computed from the
  PERSISTED latch only (review DI-MED-4: the raw whole-run first sighting reads a
  predecessor's carried-in latch and would false-FAIL a back-to-back rerun);
  share-staircase fc_bus_restored 1500→**900** (the 60 % restore-margin rule; measured
  1500/1500 = knife-edge); socband_fc_carried 0.55→**0.95 A** re-derived
  peak-over-window (review DI-MED-1: 0.70 was beaten by the constant-0.50 sibling's own
  0.8275 A window peak); **Y_AUX_LOAD_A 0.60→0.85** (b30 bounds deliverable for the
  first time — at 0.60 BOTH bounds were structurally unreachable) with `_Y_FC_BIAS_W`
  narrowed to R3 and `_Y_FC_FLOOR` re-derived FROM MEASUREMENT to {1.0: 0.50,
  3.0: 0.66} (the modelled {0.58, 0.80} would have failed a correct board — campaign
  true-run R3 peaks 0.5659/0.7606 A); FTP75 h2 totals now two-sided bands as TWO specs
  each (a new import guard REFUSES min_value+max_value on one spec — `_judge_signal_leaf`
  tests min before max and silently drops the ceiling); SY0001 de-provisionalized
  (drive_min_frac 0.30); mppt 40 ms record fixed in the three prose docs too;
  key_metrics label; first-boot variability + charge-sag doc notes.
- **Reviews:** contract lens 2 MED + 1 LOW; data-integrity lens **5 MED + 8 LOW, no
  HIGH** — every finding accepted except the cmd_share_sp_raw analysis figure (queued).
  The data-integrity lens recomputed every changed threshold against the campaign CSVs
  and reproduced the v2 artifact bit-exactly from source; both reviewers confirmed the
  rename sweep, the no-laundering rule, and the CRLF-safety of the new digests.
- **Tests: 1042 passed + 26 skipped (.venv_hil, five suites) / 272 (miniforge, four
  suites) — orchestrator-rerun.** ~50 new tests across solver CLI/artifact pins, digest
  stability, check-kind branches, import guards, provenance blocks, and the
  carried-in/persisted regression.
- **`WORK_QUEUE.md` (repo root, NEW)** is the operator-facing queue: SDP interior
  scenario round (S1 soc_ref-offset FTP75 flip, S2 charge-and-cross limit cycle,
  S3-partial braking-heavy cycle; S4 demand-above-FC-max TABLED pending solver
  action-feasibility masking; true regen harvest TABLED pending the regen-fidelity
  model), **fw v24 dynamic Ag105 MPPT threshold** (operator ruling 2026-08-31: droop
  sags the bus, so reg 0x02 must track dynamically; EPROM-wear budget + hysteresis
  deadband + power-gated writes + ~12.3 V floor; R1 MPPTSEL check still gates the
  value; also fixes the two stale P&O .ino comments), Pi-bridge v4 parser audit →
  Mode B, measured-droop sim mode, Gfc stack ID, FTP75 DP table, and standing
  housekeeping.
- **Next:** first v2 campaign calibrates the three provisional ems-sdp checks and
  observes the predicted chatter. Overnight autonomous plan authorized by the operator
  (2026-08-31): work WORK_QUEUE.md, judgment calls via a Fable-high + Opus-xhigh
  decision pair adjudicated by the orchestrator, up to five suite+analysis+fix cycles
  on the current fw v23 flash, fw v24 prepared but NOT flashed; decisions and findings
  in OVERNIGHT_LOG.md.

---

