# Host-native encoder-defect harness

Opened by WORK_QUEUE section 7d (2026-09-08). This document is the formal register of the
harness: what it is, how to run both of its modes, the signatures it pins, and the results of the
first sweep. Every number in section 5 is a measurement taken by the harness on firmware v27
rev 2 (`153562f`), production build.

---

## 1. Purpose and scope

The hardware-in-the-loop rig cannot exercise the encoder path. Under `HIL_SIM` the 40-byte
injection frame carries `v_actual` in metres per second at offset 30, and `updateSensors()`
returns before it reaches `updateWheelSpeed()`. Therefore `doEncoderA()`, `doEncoderB()`, the
A-rising period estimator, the reject gates (`ENC_PERIOD_MIN_US` 200 us and `ENC_PERIOD_LO_FRAC`
0.625) and the halving and doubling basins never execute on a HIL board. A plant-side wheel model
would produce a number that the firmware copies.

The harness closes that gap. Encoder edges are applied to the host-native mock pins
(`g_pin_value[ENC_A]`, `g_pin_value[ENC_B]`, `g_mock_micros`) and the two interrupt service
routines are called directly. `updateWheelSpeed()` and `motorControlGated()` then run unmodified,
and the firmware's own post-clamp motor command is read back into the plant's mechanical law. The
drive loop is therefore closed on the firmware's own speed estimate.

Edges and the plant step run at 1 kHz. The drive loop is called through `motorControlGated()`, so
it runs at the shipped `MOTOR_CTRL_PERIOD_US` of 2000 us (500 Hz) and a skipped tick is the
firmware's own zero-order hold. Calling the ungated `motorControl()` would double the loop rate
and change the dynamics the estimator's transients are judged against.

The harness is a separate `test/` target and is never a `run_hil_suite.py` scenario. Every HIL leg
is a board reading; this one touches no board.

Out of scope: `powerBalance()`, `chargingControl()`, interrupt latency and GPIO jitter. The
motor axis only. Interrupt latency is covered solely by the physical route named in section 7.

---

## 2. Components

| File | Role |
|---|---|
| `tools/encoder_edge_script.py` | Offline edge-list generator and JSON defect manifest writer |
| `tools/test_encoder_edge_script.py` | Host pytest suite for the generator (41 checks) |
| `test/encoder_defect_harness.cpp` | The `run_tests_encoder` target: regression, sweep and verify modes |
| `test/Makefile` | Carries the `run_tests_encoder` target and includes it in `all` |
| `logs/encoder_harness/` | Results folder, gitignored |

### 2.1 Division of labour

The generator produces edge scripts from an **open-loop** `I_cmd` stream. It is the offline
reference: it writes the manifests, it supports inspection, and it is the source of the edge
scripts for the physical pulse generator of section 7.

The harness does **not** read those files. A closed-loop wheel position is not known ahead of
time, because it depends on what the firmware commands, so the harness emits edges incrementally
from its own live position. It therefore carries a port of the generator's geometry. The two are
pinned against each other by the `--verify` mode, which checks every event of a generated file
against the harness's own level law.

### 2.2 Constants

The four mechanical constants have one source, `tools/hil_plant_sim.py`: `M_EFF` 3.5 kg, `K_F`
0.7538 N/A, `F_COULOMB` 2.00 N, `B_EFF` 0.534 N s/m. The generator imports them. C++ cannot
import them, so `test/encoder_defect_harness.cpp` mirrors them in one labelled block; a divergence
changes the true trajectory only and never the firmware path under test.

The mechanical *law* has the same single source. Both ports, `step_velocity()` in the generator and
`plant_step()` in the harness, are verbatim transcriptions of the `k_air == 0.0` (rig-profile)
branch of `PlantState.step` in `tools/hil_plant_sim.py`, which is the law the firmware faces on the
HIL bench. Three details of that branch are load-bearing: the static test is `abs(v) < V_STICTION`;
inside the deadband with `abs(f_drive) <= F_COULOMB` the plant sets the velocity to zero outright
rather than decaying it viscously; and the friction zero-crossing inhibit lives only in the moving
branch and is gated on `f_drive == 0.0` exactly. An earlier re-derivation differed on all three.
`tools/test_encoder_edge_script.py::test_step_velocity_matches_plant_reference` steps the generator
port and `PlantState.step` itself from identical states across six stiction-crossing cases and
requires bit-identical trajectories.

Correcting the two ports moved one published number in section 5 and no other: the 0.3 m/s
single-deleted-slot window-minimum spread, whose upper end read 0.7310 under the re-derivation and
reads **0.7309** under the plant's own law. The correction is confined to the launch-from-standstill
regime, where the wheel sits inside the stiction band; every settled result, every basin count, the
flagged-run total (1033 of 2676) and every onset in section 5 are unchanged.

The encoder geometry has a different source, the firmware itself: `ENCODER_SLOTS_PER_REV` 90 and
`FLYWHEEL_RADIUS_M` 0.0762 m, giving `ENC_SLOT_PITCH_M` 5.3198 mm. The generator asserts both
against the `.ino` `#define`s by grep-and-compare at run time. The harness asserts them by direct
comparison, because it includes the `.ino`.

---

## 3. How to run

The harness is built with the production flags. That build is the only one whose interrupt and
estimator path matches the bench board.

Regression mode, which is what `make` runs:

    cd test
    PATH="/c/msys64/ucrt64/bin:$PATH" g++ -std=c++17 -Wall -Wextra -I. \
      -I../teensy_controller -I../controller_design -I../controller_design_MIMO \
      -DBENCH_TEST=0 -DHIL_SIM=0 -DNO_ETH_WARNING \
      encoder_defect_harness.cpp -o run_tests_encoder
    PATH="/c/msys64/ucrt64/bin:$PATH" ./run_tests_encoder

Sweep mode, which is report-only and writes one CSV row per run:

    ./run_tests_encoder --sweep --duration 20 --out ../logs/encoder_harness

Generator equivalence:

    ../.venv_hil/Scripts/python.exe ../tools/encoder_edge_script.py \
        --profile ramp --duration 8 --cruise-i 6.0 --out ../logs/encoder_harness/verify_nominal
    ./run_tests_encoder --verify ../logs/encoder_harness/verify_nominal_edges.csv

The generator's own suite:

    .venv_hil/Scripts/python.exe -m pytest tools/test_encoder_edge_script.py

Note that `main()` is guarded by `ENCODER_HARNESS_NO_MAIN`, and the regression cases are reached
through the single function `run_encoder_defect_regression()`. A later round can therefore call
that function from `test_main.cpp` without a symbol collision.

---

## 4. Defect scripts

Defects are positioned by slot index, not by time, so a sweep over "where in the cycle" is a sweep
over the slot index. The generator records the seed and names every altered edge in the manifest.

| Script | Parameter | What it produces |
|---|---|---|
| `phase_offset_deg` | 0 to 360 | Channel B shifted from its nominal quarter-pitch lag |
| `bounce_slots` | slot, sub-pitch spacing | A `+1/-1/+1` tooth: one extra fall and rise inside one pitch |
| `missing_slots` | slot, run length | A run of slots deleted from both channels |
| `edge_jitter_us` | amplitude, seed | Zero-mean uniform jitter on every edge |
| `dropout_window` | start, end | A span with no edges at all |

A slot index maps to a different wall-clock instant at every speed. Every placement in the harness
therefore goes through `slot_at_time(v, t)`, so a defect always lands inside the scored window at
whatever speed the case runs. A fixed index would sit inside the launch ramp at 3 m/s and be out of
reach entirely at 0.3 m/s.

### 4.1 Metrics

`basin_ratio` is the ratio of published to true speed over the last 20 percent of a run. It is the
**absorbing** statistic: it answers whether the estimator ended in a wrong basin.

`ratio_win_min` and `ratio_win_max` are the extremes of a 50-tick moving-window ratio over the
scored span. They are the **transient** statistic. Both are needed. A single missing slot is a
four-millisecond event inside a twenty-second run, so its excursion is invisible in the settled
ratio and in the whole-window RMS alike; the first version of this harness reported a ratio of
exactly 1.00000 for every defect until the moving window was added.

---

## 5. First sweep: measured results

Sweep of 2026-09-08: 2676 runs, 20 s each, six cruise speeds (0.3, 0.6, 1.0, 1.5, 2.2 and
3.0 m/s), executed in about 10 s of host time. 1033 runs were flagged by the band test and 40
per-tick traces were written under the trace cap.

### 5.1 Nominal wheel

The nominal wheel tracks the truth to five decimal places at every speed. Settled RMS error rises
from 0.00001 m/s at 0.3 m/s to 0.00033 m/s at 3.0 m/s, and no interval is rejected by any of the
three drop paths. The adaptive reference `encPeriodRefUs` settles at the pitch period at each
speed: 17747 us at 0.3 m/s, 3547 us at 1.5 m/s and 1775 us at 3.0 m/s, against a predicted
5.3198 mm divided by the speed. The estimator delay model, `(N+1)` pitches divided by twice the speed with
`ENC_PERIOD_AVG_N` = 2, gives 5.32 ms at 1.5 m/s.

### 5.2 Missing slots: the halving basin is never entered

**This is the deliverable the specification named, and the answer is a negative result.** No run
length up to 80 deleted slots, at any speed in the grid, left the settled reading outside
[0.95, 1.05]. Of 1080 missing-slot runs, zero were absorbing.

The mechanism is the fw v15 pitch count taken from the decoder's own position delta, refined by
the fw v17 fractional-pitch ledger. An interval that really spans `k` pitches carries a position
delta of about `2k`, so the stored per-pitch period is correct and the reference walks back to the
truth instead of confirming a wrong value. **The absorbing halving basin documented in the
specification is a pre-fw-v15 behaviour that the position-delta ledger removed.** Recording that
here is a finding against the standing documentation, not a widened band.

What does occur is a bounded transient, and it is a **slow** reading, which is the safe direction.
Its size is governed by the `.ino`'s own "known undercount" note in `doEncoderA()`: when an entire
slot is unseen by channel A, the `AfirstUp`/`BfirstUp` handshake loses that pitch's counts too, so
the position delta under-reads by one and the interval is stored slow. Measured worst 50-tick
window ratio for a single deleted slot:

| Cruise | 0.3 | 0.6 | 1.0 | 1.5 | 2.2 | 3.0 m/s |
|---|---|---|---|---|---|---|
| window ratio min | 0.7211 | 0.8655 | 0.9217 | 0.9446 | 0.9658 | 0.9729 |

The excursion is worse at low speed because the estimator's ring holds a fixed number of pitches
while the control loop runs at a fixed rate, so one corrupted pitch occupies more control ticks.
Across the 30 slot positions the spread is small: at 0.3 m/s the window minimum ranges 0.7211 to
0.7309, at 3.0 m/s 0.9729 to 0.9796. **Where in the revolution the slot is missing does not
matter; only how many slots and how fast the wheel is turning.**

The reading does eventually go to zero, but by the staleness path, not by a basin. The governing
bound is wall-clock: `updateWheelSpeed()` uses
`max(ENC_VEL_STALE_K * lastPeriod, ENC_VEL_TIMEOUT_US)`, and 1.5 times the pitch period is 5.3 ms
at 1.5 m/s and 26.6 ms at 0.3 m/s, both far under the 100 ms floor. The floor therefore governs at
every speed this vehicle runs.

The run length that trips it follows from the length of the silent gap. When `n` consecutive slots
are deleted, the surviving interval runs from the last edge before the run to the first edge after
it, and therefore spans `n + 1` pitch periods, not `n`. The reset condition is
`(n + 1) * T > ENC_VEL_TIMEOUT_US`, so the predicted onset is

    n_pred = ceil(ENC_VEL_TIMEOUT_US / T - 1) = ceil(100 ms / T - 1)

The `- 1` term is the load-bearing part: the regression harness prints the *unadjusted* ratio
`100 / T_ms` on its per-speed header line (5.64 pitches at 0.3 m/s, 28.2 at 1.5 m/s) because that
line describes the staleness floor in pitches, not the onset. The onset predictions are one less:
**4.6 at 0.3 m/s and 27.2 at 1.5 m/s**, giving `n_pred` of 5 and 28.

The fine scan measured the first excess reset at **n = 6 at 0.3 m/s** and **n = 28 at 1.5 m/s**.
The 1.5 m/s reading is exact. The 0.3 m/s reading is one step high against `n_pred = 5` only
because the scan grid (`MISS_SCAN`) steps 4, 6 and does not contain 5. After the reset the
estimator publishes zero, recovers cleanly, and the settled ratio returns to 1.00000.

### 5.3 Bounce: the floor and the gate both hold

A bounce spacing of 50 us is rejected by the absolute `ENC_PERIOD_MIN_US` floor at every speed:
`encDropRawFloor` increments once and the window ratio does not move at all.

Spacings of 150, 250, 400 and 600 us pass the absolute floor and are then caught by the adaptive
low-side gate, `encDropLowGate` incrementing once, with no effect on the reading. That is the
expected behaviour whenever the spacing is below 0.625 times the pitch period, which at these
speeds is 1108 us at 3.0 m/s and 11083 us at 0.3 m/s.

**The T/2 doubling basin was not entered by any single-tooth bounce, at any spacing or speed:
zero of 1080 bounce runs ended outside [0.95, 1.05].** The largest transient was a window ratio of
0.9401, at 900 us spacing and 2.2 m/s, and the next largest 0.9446 at 900 us and 1.5 m/s. The specification's documented escape, the T/2 doubling
basin, therefore requires a *sustained* chatter stream and not an isolated tooth; the sustained
case is reproduced by the jitter family below, where it does occur.

At 0.3 m/s the bounce is absorbed without any drop-path increment at all, because the inserted
interval still exceeds 0.625 of an 17.7 ms pitch period, and the fractional-pitch ledger stores it
at the correct per-pitch rate.

### 5.4 Phase offset: a hard sign inversion at 180 degrees, with no fault

The A-rising period estimator is blind to the phase offset, as expected, because it timestamps one
channel. The magnitude of the reading is unaffected across the entire sweep. What changes is the
sign, and it changes as a step:

| Offset | 0 to 179 deg | 180 to 358 deg |
|---|---|---|
| settled ratio | +1.00000 | −1.00000 |
| saturation ticks (of 20000) | up to 212 | **19900** |
| peak `I_cmd` | 12.00 A | 12.00 A |

**The reported sign first inverts at exactly a 180 degree B-channel offset**, and it stays
inverted all the way round to 358 degrees. There is no gradual region and no dither: the decode is
either right or exactly backwards.

The consequence is the most safety-relevant result in this sweep. With the sign inverted the
velocity error is twice the setpoint at all times, the drive controller sits on the
`MOTOR_I_CMD_MAX` rail for **19900 of 20000 control ticks**, and no fault is raised. `detectFaults()`
has no encoder-sign check, and the fw v20 phase diagnostic does not help: `encPhaseEwma` reads
zero throughout, because the statistic only folds forward-direction samples, so a full inversion is
indistinguishable from "no data". A swapped sensor pair, or a B sensor mounted half a pitch out,
would present on the bench as a motor that runs away at full current with a clean-looking status
dump.

The exact 0 degree and exact 180 degree cases are decided in this harness by the firing order of
two simultaneous events, and are therefore a property of the model rather than of the hardware.
Real channels have skew. Section 5.5 is the physically meaningful version of that boundary.

### 5.5 Near-aligned channels with jitter: the undercount claim, confirmed and bounded

The `doEncoderB()` phase-tap comment states that as the phase drifts toward 0.0 or 0.5 pitch "the
`AfirstUp`/`BfirstUp` handshake starts losing cycles, and `encoderPos` under-counts silently".

A noiseless offset alone does not reproduce that. Section 5.4 shows the decode is exact at every
offset from 0 to 179 degrees. **Read literally against a clean edge stream, the comment's claim is
not measurable, and that is a documentation finding.**

Add front-end jitter and the claim is correct. At 1.5 m/s with 100 us of jitter, which is
10.1 degrees of a 3548 us pitch period:

| Offset | 2 deg | 5 deg | 20 deg | 90 deg | 160 deg | 175 deg | 178 deg |
|---|---|---|---|---|---|---|---|
| settled ratio | +0.0413 | +0.3525 | +1.0002 | +1.0001 | +1.0003 | +0.3270 | +0.0699 |
| direction flips | 780 | 472 | 0 | 0 | 0 | 509 | 821 |
| low-gate drops | 2443 | 1764 | 0 | 0 | 0 | 1768 | 2710 |
| saturation ticks (of 8000) | 5634 | 4476 | 64 | 64 | 64 | 4772 | 5998 |

**The criterion is that the decode collapses when the offset comes within roughly one jitter
amplitude, expressed in degrees, of 0 or 180.** At 10.1 degrees of jitter, 2 and 5 degrees fail and
20 degrees does not; 178 and 175 fail and 160 does not. This is the ML0140 to ML0145 signature
reproduced in the estimator: a sign-alternating reading, thousands of low-side gate rejections, and
the drive on the rail for a quarter of the run.

### 5.6 Edge jitter: a clean threshold at 0.6 of the quarter-pitch separation

At the nominal 90 degree mount the estimator absorbs jitter well. Settled ratios stay within
0.4 percent of unity for every amplitude and speed up to and including 200 us, with zero drop-path
rejections and zero direction flips. RMS error scales as expected with amplitude and speed, from
0.00007 m/s at 10 us and 0.3 m/s to 0.135 m/s at 200 us and 3.0 m/s. The 400 us family is also
clean at and below 1.5 m/s, settling within 0.34 percent of unity.

The collapse appears at 400 us and only at the two highest speeds:

| Amplitude, speed | quarter pitch | ratio amp / quarter pitch | settled ratio | flips | saturation ticks |
|---|---|---|---|---|---|
| 400 us, 1.5 m/s | 887 us | 0.45 | 1.0029 to 1.0034 | 0 | 64 |
| 400 us, 2.2 m/s | 605 us | 0.66 | 0.9188 to 0.9470 | 54 | 4142 |
| 400 us, 3.0 m/s | 444 us | 0.90 | **0.0050 to 0.0413** | 3006 | **17656** |
| 200 us, 3.0 m/s | 444 us | 0.45 | 1.0032 to 1.0038 | 0 | 382 |

**The governing quantity is the jitter amplitude relative to the quarter-pitch quadrature
separation, and the threshold sits near 0.6.** Below it the estimator is essentially unaffected;
above it the two channels' edge order stops being determined by the mount and the decode collapses
into the sign-alternating regime of section 5.5. Twelve of the 180 jitter runs were absorbing, and
all twelve are in the 400 us family at 2.2 and 3.0 m/s.

At the worst cell, 400 us and 3.0 m/s, the published speed settles at about 1 percent of the truth
while the true wheel keeps turning, the RMS error reaches 9.64 m/s, and the drive sits on the rail
for 17656 of 20000 ticks. No fault is raised.

### 5.7 Dropout window: the 100 ms bound, exactly

The reading-age bound behaves precisely as documented. A 20 ms or 60 ms silent span produces no
staleness reset at 0.6 m/s and above; the estimator holds, and the transient window ratio dips to
between 0.67 and 0.80 as the post-gap interval is stored slow by the same handshake undercount as
section 5.2. A 150 ms or 400 ms span always resets, the window ratio reaches exactly 0.0000, and
the settled ratio recovers to 1.00000 in every one of the 144 dropout runs.

The 0.3 m/s column resets one extra time in every case, including the nominal baseline, because a
slow launch from standstill costs a reset regardless of the defect. Reset counts in this family
must be read differentially.

The cost is again on the actuator side: a 400 ms dropout puts the drive on the 12 A rail for
roughly 500 to 610 ticks, because the estimator publishes zero while the setpoint stands. The
recovery is clean but the current excursion is not bounded by anything except `MOTOR_I_CMD_MAX`.

### 5.8 Summary of the absorbing set

Of 2676 runs, 84 ended outside [0.95, 1.05]: 72 phase runs, all of them at 180 degrees or beyond
(12 offsets times six speeds), and 12 jitter runs, all of them at 400 us and 2.2 or 3.0 m/s. **No missing-slot run and no bounce
run was absorbing at any parameter or speed.**

---

## 6. Findings against the firmware and its documentation

These are recorded, not fixed. The specification's rule applies: where the firmware's documented
behaviour and the measured harness behaviour disagree, the harness result is a finding.

1. **The absorbing halving basin for missing slots does not exist in fw v15 and later.** The
   specification expected a run length at which it becomes absorbing; there is none up to 80
   deleted slots at any speed. The fw v15 position-delta count and the fw v17 fractional-pitch
   ledger removed it. What remains is a bounded slow transient and, past 100 ms of silence, the
   ordinary staleness reset.

2. **A single missing slot does not cause the reading to hold.** The specification expected the
   low-side gate to reject the doubled period and the reading to hold. Measured, the doubled
   interval is *accepted* and divided by its counted pitches; the resulting error is a slow
   transient of up to 28 percent at 0.3 m/s, not a hold. `encDropLowGate` stays at zero for a
   single deleted slot at every speed. Measured worst case, 0.3 m/s: window ratio 0.7211, peak
instantaneous error 0.1346 m/s, `encDropLowGate` zero.

3. **The T/2 doubling basin is not reachable from an isolated bounce tooth**, at any spacing
   between 50 and 900 us and any speed in the grid. It is reachable from sustained jitter.

4. **A 180 degree phase error produces a sign-inverted reading with no fault and a permanently
   railed drive.** 19900 of 20000 ticks at `MOTOR_I_CMD_MAX`. There is no encoder-sign or
   sign-versus-command plausibility check anywhere in `detectFaults()`. This is the strongest
   candidate for a firmware change arising from this round, and it is deliberately left as a
   finding.

5. **`encPhaseEwma` is blind to a full inversion.** Because the statistic only folds
   forward-direction samples, a wholly reversed decode leaves it reading zero, which is the same
   value it holds when no data has been folded at all. The fw v20 diagnostic cannot distinguish
   "reversed" from "not yet measured".

6. **The `doEncoderB()` aligned-edges claim is true only in the presence of jitter.** Against a
   clean edge stream the decode is exact at every offset from 0 to 179 degrees. The comment should
   name the jitter precondition and the measured criterion, which is that the offset comes within
   about one jitter amplitude, in degrees, of alignment.

7. **Every degraded case ends with the drive on the current rail, and none of them raises a
   fault.** Missing slots, dropouts, near-aligned channels and large jitter all converge on the
   same actuator behaviour. The estimator's defences bound the *reading*; nothing bounds the
   *command* that a wrong reading produces beyond `MOTOR_I_CMD_MAX`.

---

## 7. Follow-on, not this round

A physical pulse generator on pins 14 and 15, replaying an edge script from a spare
microcontroller, plus a `#if HIL_SIM` switch that stops overriding `v_actual` from the injection
frame. That run is a board reading and belongs in `run_hil_suite.py`. Interrupt latency and GPIO
jitter are covered only by that route; this harness models neither.

On the evidence above, the edge scripts worth replaying physically are, in order: the 180 degree
phase inversion (finding 4), the 400 us jitter case at 3.0 m/s (section 5.6), and a
near-aligned-plus-jitter pair at 5 and 175 degrees (section 5.5). The missing-slot and bounce
families are not worth board time; the harness shows them fully absorbed.

---

## 8. Not changed

The interrupt service routines, `updateWheelSpeed()`, `encoderVelReset()` and the drive controller
are untouched, per the "What NOT to change" list. The harness replicates `test_main.cpp`'s
`enc_reset()` pattern in its own file rather than adding a reset seam to the firmware. No mock
header was modified. The wire protocols are untouched: the 40-byte injection frame, the 18-byte
observation frame and the v4 58-byte telemetry packet all stand.
