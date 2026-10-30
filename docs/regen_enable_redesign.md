# Regen-enable redesign — decouple the regen path from the Pi's charge request, gate it on an estimate of available regen power

Design brief, not yet a firmware version. Written 2026-10-30 against the fw v30 tree
(`767be0d`). **The PhD student's bench firmware is several versions ahead of this tree and is
not yet in the repository.** Every function and constant named here is named as it stands at
fw v30; section 11 lists what must be re-checked when the student's branch lands, before any
of this is implemented. The target firmware version number is left open.

## 1. Purpose and scope

The regen → charger path (`REGEN_ENABLE`, pin 30) is today opened only when the Pi has asked
for charging (`charge_goal > 0.05`) **and** the Teensy has commanded a braking current
(`current < −0.1 A`). On the bench the Pi's request is usually absent, so a drive cycle that
brakes hard from 2 m/s ten times in a row never arms the path once (observed 2026-10-29: 0 of
10081 samples armed, `I_charge` 0.0 A for the whole run). The braking energy that reaches the
VESC's input is burnt in the TL431/BSP170P chopper on the V-MOT node instead of reaching the
Ag105.

This brief does three things:

1. Removes `charge_goal` from the regen decision. The Pi's request comes to mean *fuel-cell
   charging* only; regen is harvested whenever it is physically available.
2. Replaces the bare commanded-current threshold with an estimate of the electrical power the
   VESC is returning, derived from the commanded current and the measured speed, with
   hysteresis and dwell so the path cannot chatter.
3. Rules that an open fuel-cell charge window is **not** pre-empted by a brake (section 7),
   and records what would have to change for the opposite rule (section 8).

Out of scope: a measured regen signal from the VESC (section 9.3), any change to the motor or
share controllers, any change to the FC charge window's own entry gates (fw v24 backoff,
fw v28 F1 conduction gate).

## 2. Current behaviour (fw v30)

`chargingControl()` runs at 50 Hz (`CHARGING_CTRL_PERIOD_US`) and is the only writer of
`REGEN_ENABLE` in Run. Its decision tree, in order:

1. `charge_goal <= 0.05` → `REGEN_ENABLE` LOW, `FC_CHARGE_ENABLE` LOW (through
   `assertFcChargeEnable(false)`), `MPPT_DISABLE` LOW (inhibited), `BT_BUS_ENABLE` restored
   unless the share latch owns it. **Return.** Nothing below runs.
2. `regenActive = (current < −0.1f)` where `current` is the post-clamp value the firmware
   last sent in `commandMotorCurrentLimited()` — a command, not a measurement. If true:
   `assertFcChargeEnable(false)`, `REGEN_ENABLE` HIGH, `MPPT_DISABLE` LOW, `BT_BUS_ENABLE`
   restored (plain `writeBusSwitch`, no hot-plug check — written for a bus held up by FC).
3. Else if the fw v24 undervoltage backoff is active: both paths closed.
4. Else (cruise with `charge_goal > 0`): `REGEN_ENABLE` LOW, FC window opened through the
   fw v28 F1 disarm + conduction gate, MPPT released once `ag105IsReady()` and the 1 s
   `MPPT_RELEASE_HOLDOFF_MS` have passed.

Three consequences matter here:

- **Regen needs the Pi.** With `charge_goal` at its boot value of 0 the path never opens.
- **The trigger is intent, not evidence.** It fires equally when the VESC is returning energy,
  when the 1.5 A Battery Current Regen Max is clipping it, when the motor is below the
  break-even speed and drawing from its input, when the wheels are locked, and during the
  ~428 ms post-reversal dead window (ML0151). In every one of those the path opens and the
  Ag105, with MPPT inhibited, charges from whatever V-MOT is — which with no regen flowing is
  the bus through `MOT_PWR`'s forward drop.
- **Today regen already pre-empts an open FC window.** Step 2 runs before step 4, so with
  `charge_goal > 0` a brake drops `FC_CHARGE`, raises `REGEN` and re-closes `BT_BUS`, and the
  window re-opens through the F1 gates when the brake ends. Section 7's rule is therefore a
  *change* of precedence, not a preservation of today's.

The Ag105 is powered only while `chargerHasPower()` = `FC_CHARGE_ENABLE || (REGEN_ENABLE &&
MOT_PWR_ENABLE)`; on every power edge it is re-configured lazily after `AG105_SETTLE_MS`
(500 ms), and `I_charge` is forced to 0.0 while unpowered. The bench readings `I_charge = 0.0`
and `REGEN_ENABLE` never HIGH are therefore the same fact, not two.

## 3. Physics the estimator rests on

Motor: Castle 1406 1900KV, 2 pole pairs, VESC Tool FOC detection 2026-08-15
(`controller_design_MIMO/calibration/motor_id_20260815.md`): R = 22.6 mΩ, λ = 1.422 mWb,
k_t = (3/2)·p·λ = 4.266e-3 N·m/A in the q-axis-peak convention `setCurrent()` commands.
Driveline: φ = 6.86, tire radius 0.033 m (`plant_mimo.py`). Hence motor mechanical speed
ω_m = v · φ / r_t = 207.9 · v rad/s per m/s of ground speed.

With braking current I (positive magnitude) and ground speed v:

| Quantity | Expression | Value (2 m/s, 12 A) |
|---|---|---|
| Shaft power into the motor | P_shaft = k_t · ω_m · I = **0.887 · v · I** W | 21.3 W |
| Copper loss (q-axis peak convention) | P_cu = (3/2) · R · I² = **0.0339 · I²** W | 4.88 W |
| Power leaving the VESC input (before inverter loss) | P_out = P_shaft − P_cu | 16.4 W |
| Break-even speed | v_be = (3/2)·R·I / (k_t·φ/r_t) = **0.0382 · I** m/s | 0.459 m/s |
| Fraction of braking energy lost in the windings | P_cu / P_shaft = **0.0382 · I / v** | 23 % |

Below v_be the VESC *draws* from its input to brake. Every stop ends below v_be. A locked wheel
is v_be → ∞: the flywheel encoder still reads speed, the motor is stalled, and the whole
command is copper loss supplied from the input.

Inverter conduction/switching and 470 µF link losses are **unmeasured**. The HIL plant carries
`ETA_REGEN = 0.80` as a modelling choice, not a measurement (`tools/hil_plant_sim.py`,
`TODO(verify)`), and `VESC_REGEN_I_MAX_A = 1.5` applied motor-side, also `TODO(verify)`.

The returned power is bounded above by the VESC's Battery Current Regen Max: 1.5 A at a V-MOT
of 13.5–18.1 V is 20–27 W, above anything the rig produces from 2 m/s, so at the rig's speeds
the clip is not the binding term. The August logs (153–162) nevertheless measured ~6 % of a
−12 A command delivered; the commanded-vs-delivered mapping has never been characterised
(WORK_QUEUE "VESC regen commanded-versus-delivered mapping") and remains the largest unknown.

## 4. The estimator

A pure function, no state, no I/O, so the host suite can pin it and the plant can port it
byte-for-byte:

```
float regenPowerEstimateW(float v_mps, float i_cmd_a)
    // i_cmd_a is the post-clamp commanded current (the `current` mirror); braking is i_cmd_a < 0.
    // Returns the electrical power estimated to leave the VESC input, in W; ≤ 0 means none.
    I   = -i_cmd_a                        // 0 if not braking
    if (I <= 0) return 0
    I   = min(I, REGEN_I_DELIVERED_MAX_A) // VESC-side clip, motor-referred (TODO(calibrate))
    v   = |v_mps|
    P   = REGEN_K_SHAFT_W_PER_MPS_A * v * I - REGEN_K_CU_W_PER_A2 * I * I
    return REGEN_ETA_INV * P              // negative below break-even: left negative on purpose
```

Constants, each with its source comment in the firmware:

| Constant | Value | Source | Status |
|---|---|---|---|
| `REGEN_K_SHAFT_W_PER_MPS_A` | 0.887 | k_t · φ / r_t from the measured λ, counted gears, measured tire | derived from measurements |
| `REGEN_K_CU_W_PER_A2` | 0.0339 | (3/2) · R, R from FOC detection | derived from a measurement |
| `REGEN_ETA_INV` | 0.80 | the plant's `ETA_REGEN` | `TODO(calibrate)` |
| `REGEN_I_DELIVERED_MAX_A` | 12.0 (= `MOTOR_I_CMD_MAX`, i.e. no clip until measured) | — | `TODO(calibrate)`; the 1.5 A battery-referred VESC setting is not motor-referred and must not be pasted in |
| `REGEN_P_ARM_W` | 3.0 | working figure: ~2 × the Ag105's first-half-second ramp loss at the rig's typical brake, and above the drive controller's cruise excursions (section 5) | `TODO(calibrate)` |
| `REGEN_P_RELEASE_W` | 1.0 | hysteresis: 1/3 of arm | `TODO(calibrate)` |

`static_assert(REGEN_P_RELEASE_W < REGEN_P_ARM_W)`. Both thresholds must be re-derived once
`REGEN_ETA_INV` is measured; the bench procedure is section 10.

What the estimate is and is not:

- It is a **necessary** condition. If it says no power is available, none is, under any
  delivered current ≤ commanded.
- It is **not sufficient**. It overestimates when the VESC clips, during the dead window, and
  with locked wheels (section 3). Those cases open the path onto a V-MOT that carries no
  regen; the cost is the fw v24-class "charger charging from the bus through MOT_PWR" loop
  for the dwell time, which is a loss, not a hazard — but it is why section 6's dwells are
  bounded and why section 9.1's confirmation is wanted.
- It uses `v_actual`, the flywheel surface speed, which is the only speed the Teensy has.
  Under `HIL_SIM` it is injected and the estimator runs unchanged.

## 5. Why a bare current threshold is not enough

The fw v30 `−0.1 A` threshold is marked `TODO(calibrate)` and was never calibrated. The
Youla-H drive controller dithers across zero in cruise and across the ±12 A boundary in hard
regen (the replay-vector hardening note of the fw v12 log round, `docs/claude-md-archive.md`:
"the controller genuinely dithers across the ±12 A boundary during hard regen, 82 clamp
transitions in the design sim"). Freed from `charge_goal`, a −0.1 A trigger
would toggle `REGEN_ENABLE` at up to the 50 Hz call rate in ordinary cruise. Each toggle is an
RT1987 event on the V-MOT node, a bus-topology change (two-source ↔ single-source when an FC
window is involved), and — when the firmware-side power flag flaps — an Ag105 power edge that
resets `ag105Configured` and restarts the 500 ms settle, so the charger never reaches a state
in which it banks anything. The power estimate at −0.1 A and 2 m/s is 0.18 W; at the 3 W arm
threshold the current must exceed ~1.7 A at 2 m/s, ~3.5 A at 1 m/s — a deliberate brake, not
a controller excursion.

## 6. The regen gate — state machine

Replaces `regenActive` in `chargingControl()`. Evaluated every `chargingControl()` tick
(50 Hz). Two states plus timers:

```
REGEN_OFF:
    if P_est >= REGEN_P_ARM_W for REGEN_ARM_DWELL_MS consecutively   -> REGEN_ON (record t_on)
REGEN_ON:
    if P_est <  REGEN_P_RELEASE_W for REGEN_RELEASE_DWELL_MS         -> REGEN_OFF
    if (now - t_on) < REGEN_MIN_ON_MS                                -> stay ON regardless
```

| Constant | Value | Rationale |
|---|---|---|
| `REGEN_ARM_DWELL_MS` | 40 ms (2 ticks) | rejects a one-tick spike; a brake lasting less than this harvests nothing anyway (Ag105 settle 500 ms) |
| `REGEN_RELEASE_DWELL_MS` | 200 ms | spans the controller's hard-regen rail dither and the 1 kHz / 50 Hz phase |
| `REGEN_MIN_ON_MS` | 500 ms | one Ag105 settle window: once we paid for the power edge, keep the charger up long enough to bank |
| `REGEN_MAX_TRANSITIONS_PER_MIN` | 20 | backstop: beyond this the gate holds OFF until the minute window clears and increments a counter visible in the `'S'` dump and BLG |

Exits that bypass the dwells (all force REGEN_OFF immediately): State change out of Run,
`triggerFault()`, the fw v24 undervoltage backoff asserting, `MOT_PWR_ENABLE` LOW (the
`chargerHasPower()` conjunction is false anyway), and section 7's FC-window precedence.

What the ON state drives, unchanged from fw v30's regen branch: `assertFcChargeEnable(false)`
(no-op when the window is closed, see section 7), `REGEN_ENABLE` HIGH, `MPPT_DISABLE` LOW,
`mpptReleased = false`. **Change:** the `BT_BUS_ENABLE` restore in this branch gains the
same two refusals the fw v24 backoff branch has — `!shareSpCutBT` and
`!busHotPlugUnsafe(BT_REG_ENABLE)` — since under section 8 (and under the fw v30 ordering)
this branch can run with BT freshly dropped by a window.

What the OFF state drives: `REGEN_ENABLE` LOW; `MPPT_DISABLE` is then owned by the FC-window
logic exactly as in fw v30's cruise branch.

## 7. Precedence rule for this round: an open FC charge window is not pre-empted

**Rule.** While `FC_CHARGE_ENABLE` reads HIGH, the regen gate is held in REGEN_OFF and its
dwell timers are reset. A brake during an FC window is braked by the VESC as today and its
energy goes to the chopper. When the window closes for any reason (`charge_goal` dropped,
fw v24 backoff, F1 disarm, state exit) the gate resumes on the next tick.

**Why this rule for now.** The alternative (section 8) repeats, at every brake, the
single-source → two-source → single-source hand-off that fw v27/v28 spent two campaigns
making safe in one direction, and it does so at the end of a brake, when the drive controller
is about to ramp current back up onto an FC boost that then carries motor + aux + ~1 A of
charge against `LIMIT_I_FC_MAX` 1.4 A and the H-20's 23.4 W ceiling. The regen energy lost
to this rule is bounded by the brakes that fall inside FC windows, which the EMS can be made
to avoid scheduling (section 9.2).

**Decision tree after the change** (replaces fw v30 steps 1–4):

```
backoff state update (unchanged, first and unconditional)
if FC_CHARGE_ENABLE reads HIGH:
    regen gate forced OFF
    run the fw v30 FC-window maintenance (cruise branch: MPPT release gating, backoff close)
    -- charge_goal <= 0.05 or backoff active closes the window exactly as today
else:
    regen gate steps (section 6)
    if REGEN_ON:   drive the ON set (section 6)
    else if charge_goal > 0.05 and not backoff:
                   fw v30 cruise branch: REGEN LOW, F1-gated window open, MPPT release gating
    else:          REGEN LOW, FC_CHARGE LOW (guard), MPPT inhibited, BT restored (fw v30 step 1)
```

Note the hand-off that remains: a brake that starts with the window **closed** (not yet open,
or closed by backoff) arms regen, and when the brake ends and `charge_goal > 0` the window
opens through the F1 gates — the fw v30 regen → cruise transition, which campaigns I and II
measured clean on every trigger. This round adds no transition type; it removes the
window → regen direction.

**`charge_goal` semantics after the change.** `charge_goal > 0.05` = "open the FC charge
window when the gates allow". It no longer influences regen. The Pi has no regen veto in this
round; see section 9.2 for the extension.

## 8. Requirements if regen is later given precedence over an open FC window

Recorded so the decision can be reversed with its costs known. Each item is a requirement,
not a suggestion; several already have bench evidence behind them.

1. **Return-path load gate.** Re-opening the window after a brake cuts BT onto an FC boost
   with the drive controller ramping. Require, in addition to the F1 conduction gate: the
   filtered total bus current (`I_tot_filt`, the share loop's) plus the configured charge
   current (`chg_i_ceiling`, 1.0 A on the HIL legs) under `LIMIT_I_FC_MAX` with margin, and
   under the H-20 P_MAX bus equivalent (1.247 A). Otherwise hold two-source with both paths
   closed until it is. The charge-cruise leg's 1.40 A OC_FC latch at 92.8 % of P_MAX
   (campaign II) is the case this prevents.
2. **Return dwell.** `REGEN_TO_FC_REOPEN_DWELL_MS` ≥ 1000 ms after REGEN_OFF before the
   window may re-open, so a brake-release-brake sequence does not perform two full hand-offs.
3. **Transition-rate cap applied to hand-offs**, not only to regen toggles: more than N
   window ↔ regen hand-offs per minute degrades to regen-only (window held closed) for the
   rest of the window's intent.
4. **BT re-close on window → regen must pass `busHotPlugUnsafe()`** (section 6 already
   requires it) and the fw v25 survivor-blanking: BT re-closed within `SHARE_CUT_SURVIVOR_
   BLANK_MS` of its own rise must not be cut again by the return path — the F1 gate tests
   FC's conduction, not BT's, so add the symmetric check on the return.
5. **Share-loop topology handling across the hand-off.** fw v28 rev 4 keys the k_d hold on
   exactly one bus switch HIGH; the re-entry into two-source on inherited MDAC codes
   overshoots (F7, ~0.24 A for ~12 ms, campaign G). At brake rates this is tolerable; at
   dither rates it is not — the rate cap (item 3) is what bounds it.
6. **Ag105 input continuity.** `FC_CHARGE` turns off in ~100 µs; the REGEN RT1987 turns on
   in ~8 ms (`RT1987_T_D_ON_MS`). The module rides its input capacitance across the gap while
   `chargerHasPower()` reports continuous power. Scope VCHG-IN across a hand-off before
   adopting the rule; if the module drops out, the firmware's `ag105Configured`/settle state
   is wrong until the next poll shows it, and `pollAg105()` needs a GENSTAT-driven
   "unexpected reset" re-arm.
7. **MPPT release holdoff economics.** Every pre-emption asserts `MPPT_DISABLE`; the window's
   release afterwards waits `MPPT_RELEASE_HOLDOFF_MS` (1 s) plus the module's ramp. On a
   stop-and-go cycle the window is open but harvests little. Either shorten the holdoff for
   *regen-caused* re-asserts (distinguish them from readiness-driven ones, which is what the
   holdoff was built for) or accept the loss explicitly in the EMS.
8. **MPPT threshold manager sampling.** `ag105ManageMpptThreshold()` samples `V_chg` only
   while `fcChargePathIsPowering()` and skips 150 ms after path-open. A hand-off every few
   seconds keeps the window inside that skip; verify the manager still converges, or lengthen
   the window-open requirement before sampling.
9. **Tests**: every item above as a host-native case, plus the F1 fixtures re-run with the
   window → regen → window sequence inserted at each of the three recorded F1 triggers.
10. **HIL**: a `regen-in-window` scenario with brakes placed inside the `mppt-tracking`
    cruise-charge windows, scored on UV_BUS ticks (expect 0), OC_FC (expect 0), hand-off count
    and `charge_edges_safe`.

## 9. Interfaces

### 9.1 Confirmation signal (recommended follow-on, not in this round)

`RGN_VOLTAGE` (pin 39) is read every loop. Regen cannot flow back into VBUS (`MOT_PWR` is an
ideal diode), so energy leaving the VESC raises V-MOT above the bus — the August logs show
V_rgn 13.3 → 18.1 V with V_bus unmoved. `V_rgn > V_bus + margin` is therefore direct evidence
that the estimate is right. **Blocked** on explaining the resting V_rgn of 13.3–13.5 V against
a 15.9 V bus (an ideal-diode node should sit within tens of mV of the bus with `MOT_PWR`
closed). Until that offset is understood — divider calibration, a real drop, or a scale error
— V_rgn cannot gate anything. Add it as a bench item; record the finding in `SCALE_V_RGN`'s
comment.

### 9.2 Pi command packet

No layout change in this round (22 bytes, protocol v4). Two extensions are flagged, each a
`protocol-bump` round with the Pi bridge in lockstep:

- **Regen veto.** The reserved `droop_enable` byte (offset per PLAN.md §6b, parsed into
  `droop_enable_reserved` and discarded) is the natural carrier: bit 0 = `regen_inhibit`.
  Until then the Pi cannot stop regen; the firmware's own guards (OV_BATT 8.5 V, Ag105 8.4 V
  termination, BQ29200 OVP) are the pack protection.
- **EMS awareness.** Under section 7 the EMS should avoid scheduling FC windows across
  predicted brakes. That is a tools change (`tools/mpc_ems.py`, the SDP stage model), not a
  firmware one, and belongs to the held EMS queue.

### 9.3 Telemetry, BLG, HIL frame

- Telemetry v4/58 B: unchanged. `switch_state` already carries `REGEN_ENABLE`.
- BLG v9/116 B: byte 115 is spare. Proposed: bits 0–1 regen gate state (OFF/ARMING/ON), bit 2
  rate-cap active, bits 3–7 `P_est` quantised at 1 W/count saturating at 31 W. Decoder
  (`tools/benchlog_analysis`) in lockstep; the record stays v9 if the spare is used, else v10.
- HIL observation frame 18 B: unchanged. The aux byte is full; the gate state is inferred from
  `REGEN_ENABLE` in `switch_state`.
- `'S'` dump: add `P_est`, gate state, arm/release dwell ages, transitions this minute,
  rate-cap trips.

### 9.4 State 98

- `'D'`, `'Y'`, `'W'` profiles run `chargingControl()` unmodified, so the gate is exercised by
  the existing drive cycles with **no `charge_goal` required** — this is the bench
  observability win the student asked for.
- `'4'` (manual `REGEN_ENABLE` toggle) stays as is; the gate does not run in manual-switch
  mode (it runs only where `chargingControl()` runs).
- A new one-line `'J'` (free letter — verify against the student's branch) prints the
  estimator's inputs and output live, so a stop can be watched tick by tick.

### 9.5 Tools mirror

`tools/hil_plant_sim.py` already carries `VESC_REGEN_I_MAX_A` and `ETA_REGEN` and models
`charge_goal`-gated regen in `mppt-harvest`/`regen-harvest`. The firmware port of
`regenPowerEstimateW()` goes into the plant's EMS/strategy layer with an equivalence test
against the host build (the governor_model harness pattern: identical inputs, code delta 0).
Every regen-scored HIL leg's expectation changes (regen no longer waits for the strategy's
`charge_goal`) — that is a scoring re-pin round, held with the EMS queue.

## 10. Bench measurement that gates the constants

One session, State 98, SD logging on, scope on VCHG-IN and V-MOT:

1. **VESC Tool readout** (USB, motor stopped): record Motor Current Max Brake, Battery Current
   Max, Battery Current Max Regen, control type (FOC), and whether "short LS on zero duty" is
   set. These have never been written down; §4 of `docs/VESC_MOTOR_INTEGRATION.md` gets the
   values.
2. **Delivered vs commanded.** From 2 m/s, brakes at −1, −2, −3 A… up to −12 A, each held
   ≥ 1 s. VESC Tool realtime `avgInputCurrent` and `avgMotorCurrent` (or the `'E'` snapshot
   between brakes) against the command. Fit `REGEN_I_DELIVERED_MAX_A` and the slope.
3. **Inverter efficiency.** At each brake, `P_in = avgInputCurrent × V_mot` against the
   estimator's `P_shaft − P_cu`. Fit `REGEN_ETA_INV`. Expect it to fall at low current.
4. **Break-even.** Watch the sign of `avgInputCurrent` as speed falls through
   `0.0382 × I`; the crossing calibrates `REGEN_K_CU_W_PER_A2 / REGEN_K_SHAFT_W_PER_MPS_A`
   together.
5. **V_rgn offset.** With the car stationary and `MOT_PWR` closed, `V_rgn` vs `V_bus`, and
   with a DMM at the divider input. Resolves section 9.1.
6. **Thresholds.** From 2–4, pick `REGEN_P_ARM_W` so the first half-second of a typical brake
   (the Ag105 settle) is worth paying for, and `REGEN_P_RELEASE_W` under the cruise
   controller's largest observed excursion.

Record in a new `controller_design_MIMO/calibration/regen_id_<date>.md` and update the
constants' source comments.

## 11. Rebase notes — read before implementing

This brief is against fw v30 (`767be0d`). The student's firmware is ahead on another branch
and may have touched any of:

- `chargingControl()` and the `regenActive` line — re-derive the decision tree of section 2
  from the student's tree first; if a `charge_goal` bypass or a different threshold already
  exists there, section 6 supersedes it rather than stacking on it.
- `assertFcChargeEnable()`, the F1 gate, `writeBusSwitch()`/`busSwitchBlanked()` — section
  6's BT re-close refusals assume the fw v30 signatures.
- The State 98 key map (`'J'` is proposed on the fw v30 map).
- BLG version and the byte-115 spare.
- `MOTOR_I_CMD_MAX` (12 A at fw v30; `REGEN_I_DELIVERED_MAX_A` defaults to it).
- The drive cycle the student built (repeated stops, −1.0 to −3.5 m/s²) — adopt it as the
  bench profile for section 10 if it is in the tree; it is exactly the ladder step 2 needs.

Implement as an `orchestrated-feature` round with the spec seeded from sections 4, 6, 7 and
9.3, followed by `self-review` and the full test build (`run_tests`, `run_tests_bench`,
`run_tests_hil`). Section 8 is **not** implemented in that round; it is the reversal record.

## 12. Open questions for the operator

1. Confirm section 7's rule (FC window not pre-empted) as the first-round behaviour.
2. `REGEN_P_ARM_W` 3.0 W / `REGEN_P_RELEASE_W` 1.0 W as working figures until section 10.
3. Whether the Pi needs a regen veto in this round (section 9.2) or the firmware guards
   suffice for the bench phase.
4. Whether to spend the BLG byte-115 spare on the gate (section 9.3).
