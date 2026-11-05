# fw v36 review and Pi rosbag analysis, focused on regen (2026-11-04)

Agentic round over the student's fw v31-v36 line and all 22 Pi rosbags (2026-09-07 .. 10-30).
Six agents: three firmware reviewers (the regen signal chain end to end; safety and sequencing;
functionality and tests) and three bag analysts (regen episodes and every decel; fault forensics;
sweeps, share tracking and trends). Bag method: `.claude/skills/rosbag-agent-analysis/`.
Every bag ran **fw <= v35** (v36 has never run); the exact build per bag is not recorded
(WORK_QUEUE 0j). Code line numbers are `teensy_controller/teensy_controller.ino` at `7588ed3`.

Orchestrator spot-checks: the Ag105 datasheet text "VBat- ... Must NOT be connected directly to
the GND pin" (p.4, pins 14/15) is verified; the V_rgn / V_bus ratio of 0.849-0.854 is verified
(per-bag medians, MOT_PWR on, REGEN off, 21 bags); `fig1` was read.

## 1. The symptom: regen returns no charge current

There is no single cause. The chain breaks at several independent points, any one of which is
sufficient, and the bags never reached the last links.

**What the bags show (fw <= v35):**

| Fact | Numbers |
|---|---|
| Charger never produced data | `charger_status` 0 and `I_charge` 0.000 A in every sample of all 22 bags |
| REGEN never stayed up long enough to configure the charger | 13 braking episodes, 54 ticks, longest 10 ticks (~200 ms); `AG105_SETTLE_MS` is 500 ms (:2360); each drop re-arms the session (`ag105Configured = false`, :14585) |
| Where REGEN did open, there was no regen energy | all 13 episodes are the < 0.7 m/s tail of UDDS ramps commanded at 0.2-0.36 m/s^2, gentler than the rig's coast-down (~0.6-0.87 m/s^2: 2.00 N + 0.534 v over 3.5 kg); REGEN flickered on 0.02-0.05 m/s encoder overshoot; V_rgn never moved; V_chg = V_bus - 0.09 V, i.e. **the charger was fed from the bus through MOT_PWR, not by regen** (`figs/sdp1029_regen_flicker.png`) |
| Where regen energy existed, REGEN never opened | `rosbag_sweep-noclip_2026-10-30_01-30-16` (RegenTest_v2): 6/6 decels lift V_rgn 13.5 -> 16.9-18.3 (ADC units) for 0.3-0.6 s, bus unloaded, V_bus flat; `charge_goal` 0 throughout, so the fw <= v35 gate kept REGEN at 0/10081 ticks (`figs/regentest_decels.png`) |
| The regen burst is shorter than the settle | V-MOT peaks 0.10-0.20 s after the setpoint falls and is back at bus level by 0.3-0.6 s, entirely inside the 500 ms settle; braking work above friction ~0.8-1.0 J per decel from 2 m/s, so ~0.7 J electrical, ~0.2 A for 0.4 s into the pack if captured |
| The EMS arms charging on every slowdown | the SDP node's `P_demand = m v a` (m = 5 kg, no friction term) sets `charge_goal` 1 on any setpoint decrease, so `charge_goal` 1 coexists with zero regen energy (seen in `/rosout`, "regen armed / released") |

**Ranked causes:**

1. **Firmware (fixed in v36): regen gated on `charge_goal`.** Explains the RegenTest bag completely.
2. **Test design: the UDDS decels never brake.** The rig decelerates faster on friction than the
   drive cycle asks, so the motor never regenerates. Not firmware. Regen tests must brake harder
   than coast-down, from >= 1 m/s.
3. **Firmware: no hold or hysteresis on the regen arm, and a 500 ms settle that is longer than the
   energy burst.** `regenActive = current < -0.1f` (:13747), one sample per 20 ms period; probe:
   a -0.09/-0.11 A dither toggles REGEN every period. The session resets on every drop, so the
   charger is never configured and the burst is over before `pollAg105()` trusts the charger.
   Even with v36, an armed REGEN would mostly charge the pack **from the bus** after the burst.
4. **Hardware (suspected, needs a ruling): Ag105 VBat- tied to GND.** The schematic (sheet 4, agent
   reading, not yet confirmed by the operator) runs VBat- to J-NTC pin 2 = GND; the datasheet
   forbids it. If the module senses current low-side, Bring-Up sees no current and reports
   "battery disconnect" (GENSTAT 000 -> status 0x00, STAT 1 pulse). A re-spin or Silvertel
   question; firmware cannot fix it.
5. **Hardware (check): D-BT-SQ orientation.** The schematic puts the RT1987 with VIN = charger
   VBAT+ (VCHG) and VOUT = pack; `docs/boost-bringup-debug.md:43` describes it the other way. If
   built that way, charge current is blocked outright. One DMM reading on VCHG settles it.
6. **Measurement: V_rgn reads 0.85 x true.** V_chg uses the same 78.7k/10k divider and reads
   right; V_rgn reads 0.849-0.854 x V_bus at rest. So the "18.1 V chopper clamp" is ~21.3-21.5 V
   true (design 22.1 V), and `LIMIT_V_RGN_MAX` 28 V (:2160) trips at ~32.9 V true, above the
   RT1987's 32 V operating range. The idle 13.5 V is this artefact. Cause on the pin-39 path
   unknown (TL431 REF loading is the leading candidate).
   **Superseded 2026-11-05 (`docs/vrgn_measurement_error_2026-11-05.md`):** the 0.85 ratio stands (present since the first V_rgn log, TP0074, and temperature-dependent), but 18.1 V is NOT the chopper clamp - the chopper has never been shown to trip; ADC chain and channel carry-over ruled out.
7. **Policy: MPPT inhibited during regen with the charger bus-fed.** `MPPT_DISABLE` LOW does not
   stop charging (datasheet section 2.9). A configured Ag105 on REGEN would draw up to ~24 W,
   ~1.5 A, from the bus (battery -> BT boost -> bus -> charger -> battery: a net loss, and near the
   H-20's 23.4 W). The regen branch also outranks the charger UV backoff (:13784 before :13806).
8. **VESC:** "Battery Current Regen Max" 1.5 A caps braking at ~1.1 N, about half the friction
   force; V-MOT regen is cut back after ~0.4 s while the command presumably stays negative
   (VESC input-voltage regen limit suspected, unverified).

## 2. The rest of the fw v36 review

**Verified correct** (safety agent): FC_CHARGE vs BT_BUS/REGEN mutual exclusion on every path; no
new back-feed into a disabled boost; all four BT re-close sites in `chargingControl()` are
hot-plug-guarded (:13767, :13804, :13836, :13967; the v31c regression is gone); no new MOT_PWR
writes; every teardown drives REGEN LOW; `FC_CHARGE_ALLOWED 0` keeps the Run path closed (~150 k
samples, FC_CHARGE 0 outside State 99); timers wrap-safe; nothing blocking.

**Flash recommendation for v36:** flash for an attended bench session only, scope on the charger
input. It introduces no interlock regression, but it makes the chattering, bus-fed regen path
live on every run, and its first sustained regen in Run may latch `ERR_I2C_CHARGER` (probe: 520 ms
of regen with a silent charger latches 0x8800, error 12; the Ag105 has never been seen ACKing).

| Sev | Finding | Where |
|---|---|---|
| HIGH | Regen arm chatters (no hysteresis/hold), hot-plugs the never-scoped charger input up to 25 Hz; arms on current sign, so reverse motoring and v = 0 overshoot count as regen | :13747 |
| HIGH | "Regen" is bus-fed charging with MPPT disabled, and outranks the UV backoff | :13784-13806, `chargerHasPower()` :14672 |
| MED | `ERR_I2C_CHARGER` / `INIT_FAIL` latch exposed in Run by v36 | `pollAg105()` :14604, :14636, :14655 |
| MED | With FC charging off, `charge_goal` > 0 still disarms the source selector and sets the re-arm inhibit every cruise period (the SDP EMS loses battery-only start / FC-only selection) | :13887-13908 |
| MED | `FC_CHG_COOLDOWN_MS` only applies after the dwell lockout, not after an ordinary close; `fcChgClosedMs` stamps are otherwise unread (dead while ALLOWED 0) | :13917, :2507 |
| MED | Purge lockout cannot protect the first purge (from boot or > 30 s since the last) | `fcUvLockoutActive()` :2301 |
| MED | OC_FC trips on one raw 1 kHz sample; 4 of 7 latches in the bags, 3 at mean I_fc 0.7-0.85 A (crests of a real 3.9-4.7 Hz oscillation + ~0.05 A sample noise); the sweep latch sat at the 1.25 A governor ceiling with 0.15 A margin | :6744; `figs/ocfc_1029.png` |
| LOW | Charge-window timers never reset (backoff, State 3, State 99, Run entry); `fcChgOpenedMs == 0` doubles as the "shut" sentinel | :2511-2513 |
| LOW | State-98 'D' natural completion leaves REGEN at its last level | `advanceDriveCycle()` :8982 |
| LOW | `FC_CHARGE_ALLOWED` not honoured by '5' and the State-99 drain (benign: both bus switches LOW); not on any wire | :8283, :7932 |
| LOW | `FC_CHARGE_ALLOWED` has no `#ifndef` guard, so tests cannot build ALLOWED=1 | :2492 |
| DOC | .ino changelog stops at v30; stale comments at :13738, :13785, :2507 | |

**Tests:** v36 builds 4553/10, bench 210/0, HIL 4860/10, encoder 51/0, 0 warnings. All 10
failures are STALE (9 FC-charge-path tests from v31b's `FC_CHARGE_ALLOWED 0`, plus the
`FW_VERSION == 30` pin). `reset_test_state()` also misses the three v35 window timers, which makes
two of the stale tests fail even with ALLOWED=1. No test covers the v32a limits, the v33b gate, or
v36's regen arming.

**The 2026-10-28 "FC charge window" did not happen in any recorded run.** Every FC_CHARGE sample
in all 22 bags is `0x34` on or after a latch tick: the State-99 phase-0 cap drain (:7932). The
only UV_FC + UV_BUS latch (0x8140) is 10-27 00:52, recovered from `/rosout` (FC-only bus at
standstill, share 1.00, a purge). The 10-28 bags latched OC_FC and UV_FC respectively. The v33b
gate's stated motivation is therefore misattributed (the gate is still sound).

**Other bag findings:**

- Faults: 09-07 PI_TIMEOUT = orderly Pi shutdown (the bridge's 500 ms SAFE fallback can never beat
  the Teensy's 500 ms watchdog); 10-28 22:18 UV_FC = the stack lost voltage (not a purge; supply
  loss or starvation, inferred; `figs/uvfc_1028_2218.png`); the simple-EMS OC_FC = rail dither
  (0.065/0.935 commands from a jittering SoC step table, 516 topology changes in 121 s). No fault
  involved regen.
- H-20 purges every 10.34 s, ~1.8-2.3 V deep, 100-140 ms; harmless on a two-source bus (V_bus to
  ~15.7 V), but four bags start FC-only at standstill and the first purge sags V_bus to
  12.9-14.6 V before BT closes (`figs/purge_two_source_vs_fc_only.png`).
- Share tracking: within +/-0.01 for commands 0.35-0.65; the extremes are the 0.125 A
  minority floor; the loop follows a 2 s triangle (amplitude 0.79-0.87, ~45 ms lag incl. two Pi
  hops). Clip vs no-clip: no delivery or bus difference.
- FC health: no decline 10-20 -> 10-30 (V0 10.4-10.7 V, ~2 ohm bus-side). The 11-03 "FC not
  delivering" has no bag.
- Battery: rest voltage 8.22 -> 7.77 V over 10 days, monotone; no charging anywhere
  (`figs/fc_batt_trend.png`).
- 09-07, 09-10 and 10-20 before 06:40 ran on a flat ~8.3 V source (not the H-20) with a softer
  battery and a different droop signature: do not pool them.

## 3. fw v37 proposal

Gate before any regen firmware: **bench test B1 below**. If the Ag105 cannot charge when held
powered for 5 s, the firmware changes cannot help and the hardware items come first.

**B1 - zero-code bench test (State 98, today's keys):** `G` (bus and motor node up) -> `4` (REGEN
HIGH; the charger now sees ~15.8 V from the bus) -> wait >= 5 s -> `I` (does 0x30 ACK?) -> `S`
(status byte, CHARGER_STAT, `ag105Configured`, I_charge) -> `N` (reg 0x02, input V) -> `M` (release
MPPT) -> `S` -> `4` off. Clamp-meter the charger VBAT+ lead and watch I_batt / V_bus. Plus: DMM on
VCHG with BT_SEQ high and the charger unpowered (~0 V = schematic orientation of D-BT-SQ; ~pack
voltage = reversed), and DMM on V-MOT vs the pin-39 reading (V_rgn calibration). Outcomes:
no ACK -> charger/I2C; status 0x00 + 1-pulse STAT + no current -> the VBat- wiring; charging ->
the firmware path is the remaining blocker.

**(a) Fixes:**

1. **Regen power-path policy (needs an operator ruling, R1).** Preferred: keep the charger
   powered whenever MOT_PWR is HIGH in Run (REGEN held open, no per-tick arming), write reg 0x02
   once to a count above the bus and below the true chopper clamp (e.g. count 78 = 17.86 V, above
   `LIMIT_V_BUS_MAX` 17.5 V and below ~21.4 V) and **release** MPPT, so the Ag105 charges only
   when V-MOT rises above the bus, i.e. on genuine regen. This removes the settle latency (the
   0.3-0.6 s burst is otherwise lost) and the bus-fed loop. Depends on two datasheet unknowns:
   how fast the Ag105 starts charging when its input crosses the threshold, and whether it
   switches or regulates at the threshold. Conflicts with the v24 threshold manager's [12.3, 13.4]
   V window, which must become mode-aware before FC charging returns.
   Fallback if B1 shows the threshold is not usable: an arm with hysteresis and hold - enter on
   real-regen evidence (calibrated V_rgn > V_bus + 0.3 V, or `current < -0.5 A` for >= 10 ms with
   `current * v_actual < 0`), release after >= 2 s with no evidence - plus charge-current-sign
   checks so a bus-fed charge is visible.
2. **Precedence:** the UV backoff closes REGEN (backoff before regen).
3. **V_rgn calibration:** `SCALE_V_RGN` x 1/0.8505 as `TODO(calibrate)` (or a runtime ratio
   calibration against V_bus with MOT_PWR on, REGEN off, |current| < 0.1 A); re-derive
   `LIMIT_V_RGN_MAX` to <= ~26 V true, under the RT1987 32 V limit.
4. **Charger faults in a regen-powered session:** do not latch `ERR_I2C_CHARGER` / `INIT_FAIL`
   until the charger has ACKed once this boot ("charger proven"); count and degrade instead.
5. **Gate the F1 selector disarm on `FC_CHARGE_ALLOWED`** (or on a window actually being able to
   open).
6. **OC_FC persistence:** N consecutive 1 kHz samples (or a few-ms integrator) at 1.4 A, plus an
   instantaneous trip at a higher level for a real short (figures `TODO(calibrate)` against a 1
   kHz BLG of the oscillation).
7. **Housekeeping:** `#ifndef` guard on `FC_CHARGE_ALLOWED`; reset the window timers at every
   close and on Run entry, with a separate open flag; cooldown after any close; REGEN LOW on 'D'
   completion; .ino changelog v31-v37; `FW_VERSION` 37.

**(b) Diagnostics:**

1. **BLG v10** (decoder bump, same 116 B record): `switch_state` in spare @115, `ag105_status_raw`
   in pad[0], a charger flag byte in pad[1] (`ag105DataValid`, `ag105Configured`, settled,
   `MPPT_DISABLE`, `ag105MeasUnavailable`, `chargerHasPower`, regen armed). `I_cmd`, `V_rgn`,
   `V_chg` are already at 1 kHz. A `'K'` log of a RegenTest decel is then the definitive capture.
2. **State-98 regen exerciser key:** B1 automated, printing at 10 Hz: V_chg, V_rgn raw and
   calibrated, V_bus, ACK, decoded status, regs 0x00/0x01/0x02/0x05/0x06/0x07, MPPT pin, STAT;
   optional phase with negative motor current and REGEN held.
3. **STAT-pin pulse decoder** (Table 5: mode 0-7 without I2C), in `S`.
4. **Serial regen counters** (no wire change): arm events, longest REGEN window, charger power
   sessions, sessions settled, sessions configured, NAKs, max I_charge, max (V_rgn - V_bus), time
   with real regen.
5. **Telemetry v5** (protocol bump, Pi lockstep): `FW_VERSION` (WORK_QUEUE 0j), commanded motor
   current, and the charger flag byte. Recommend bundling into one bump.

**Pi / EMS side (not firmware):** arm `charge_goal` regen only when commanded deceleration
exceeds coast-down (add friction to `P_demand`); bridge SAFE fallback <= 250 ms or SAFE on node
shutdown; record the fw version per bag; re-run RegenTest_v2 on the next build.

## 4. Rulings needed

- **R1** Regen power-path policy: always-powered charger with the threshold above the bus (preferred),
  or a held arm on real-regen evidence.
- **R2** Suspected hardware defects: confirm the VBat- wiring on the schematic or board, and decide
  whether to ask Silvertel. Check the D-BT-SQ orientation.
- **R3** Whether the bus may ever feed the charger (i.e. FC/battery -> pack charging through the
  regen path) or whether that is forbidden like `FC_CHARGE_ALLOWED 0`.
- **R4** The telemetry v5 bump with v37, or BLG-only diagnostics first.

## Figures

`figs/regentest_decels.png`, `figs/sdp1029_regen_flicker.png`, `figs/charge_goal_ab_same_decel.png`,
`figs/ocfc_1029.png`, `figs/uvfc_1028_2218.png`, `figs/purge_two_source_vs_fc_only.png`,
`figs/fc_batt_trend.png`.
