# fw v37 noise round: Pi rosbag analysis, share-ratio noise, and firmware actions (2026-11-05)

This record covers the first Pi rosbag taken with the lower-crossover drive law of fw v37. It
compares that bag with the matched fw v35 bag, breaks down the share-ratio noise spectrum, and
answers whether the share balance controller needs a bandwidth change. Section 6 lists the
firmware actions for the board as built. Board re-spin items are in a separate note,
[`docs/respin_noise_notes_2026-11-05.md`](../../respin_noise_notes_2026-11-05.md).

Method: `.claude/skills/rosbag-agent-analysis/`. Five analysis agents ran in parallel: a
before/after comparison, a share-spectrum decomposition, a share-loop model and firmware trace, a
freeform sweep, and a sensing-chain review. Each load-bearing claim then went to two adversarial
verifiers, one re-deriving the numbers from the arrays and one checking physics and source. A
completeness critic resolved contradictions between the reports. Section 8 lists the agents'
figures. Code line numbers are `teensy_controller/teensy_controller.ino` at `da0746c`
(fw v37 rev 2).

## 1. Data and firmware bound

Table 1 lists the bags. The firmware version is not in the telemetry, so every bound comes from
dates and code diffs (WORK_QUEUE 0j).

**Table 1.** Bags used in this round.

| Bag | Role | Firmware bound | Duration | Notes |
|---|---|---|---:|---|
| `rosbag_sdp_2026-11-05_20-09-52` | after | fw v37 rev 2 (`da0746c`), vehicle build | 167 s | First bag with `/h2_usage`. Bridge 2026-11-03A. |
| `rosbag_sdp_2026-10-30_01-49-38` | before | fw v35 | 188 s | No fault. Same SDP cycle and command staircase. |
| `rosbag_sdp_2026-10-26_23-57-14` | control | fw <= v31a | 246 s | Battery only (share 0). No share loop activity. |
| `rosbag_sdp_2026-10-28_20-46-53`, `-10-29_19-51-48` | extra before | fw <= v35 | pre-fault spans | Both latched OC_FC late in the run. |

The student's `Teensy_v37.ino` (`6b1ca57` on `phd/siddhesh-2026-11-03`) differs from `da0746c`
only in `BENCH_TEST 0` and `USE_ETHERNET 1`. Between fw v35 (`ab4a705`) and `da0746c`, the share
path is byte-identical. The only Run-path change is `drive_controller_coeffs.h`.

The two runs are near-replicates. Their `v_setpoint` traces differ by 0.35 mm/s rms. The SDP
command staircase has 44 steps above 0.05 at the same instants (within 0.04 s). The H-20 purges
fall at the same drive-cycle phase (10.340 s period). Every moving tick is `switch_state` 0x27;
0x26 occurs only at standstill.

**Analysis conventions.** All statistics in this record use the following conventions unless a
line states otherwise:
- **own share** s = I_fc/(I_fc + I_batt), in 0x27 only, with I_tot > 0.3 A. The bridge field
  `vs[:,9]` is not used.
- **clean window**: moving (v > 0.3 m/s), with ±0.5 s excluded around each H-20 purge and
  ±0.2 s (or −0.2/+1.0 s) around each `power_share_cmd` step.
- **de-duplicated**: one repeated row in every 21 is removed, and the time base is 47.62 Hz
  (Section 5.1).
- The fields `vs[:,10]` and `vs[:,11]` are Q16 droop gains (`droop_gain_*_actual × 65535`,
  :7687), not MDAC codes.

## 2. Before and after the drive-law change

### 2.1 The 1x flywheel line fell on every channel, including the share

Table 2 gives the 1x line under matched conditions: 7 paired steady chunks, 24.7 s per run,
1.95–2.72 m/s, `power_share_cmd` 0.16, clean windows. The lock-in uses the tracked rotation phase,
f_rot = 2.089 Hz per m/s.

**Table 2.** 1x amplitude, fw v35 → fw v37 (ratio in brackets).

| Channel | 1.95 m/s (4.1 Hz) | 2.15 m/s (4.5 Hz) | 2.70 m/s (5.6 Hz) |
|---|---|---|---|
| I_tot (A) | 0.233 → 0.061 (0.26) | 0.225 → 0.058 (0.26) | 0.222 → 0.045 (0.20) |
| I_fc (A) | 0.038 → 0.010 (0.27) | 0.033 → 0.012 (0.36) | 0.036 → 0.007 (0.20) |
| I_batt (A) | 0.213 → 0.055 (0.26) | 0.202 → 0.051 (0.25) | 0.187 → 0.038 (0.20) |
| V_bus (mV) | 10.3 → 3.9 (0.38) | 14.6 → 4.0 (0.27) | 16.6 → 4.5 (0.27) |
| own share | 0.063 → 0.015 (0.23) | 0.043 → 0.014 (0.31) | 0.010 → 0.002 (0.21) |
| v_actual (mm/s) | 24.3 → 12.6 (0.52) | 20.1 → 14.2 (0.71) | 16.8 → 10.1 (0.60) |

The bins hold 1, 4 and 2 chunks. The data verifier found no resolvable speed dependence and puts
the I_tot ratio at 0.24 ± 0.04 over the cruise band. Independently, the cruise 1x line on I_batt
at 2.2 m/s fell by an amplitude ratio of 0.29. The design rotation-band ratio |C·S| new/old is
0.29 at 4.6 Hz.

The controller part of the reduction matches the design. The bus-side 1x gain
|I_tot / v_actual| fell from 11.1 / 13.6 to 3.6 / 4.5 A per m/s at 2.15 / 2.70 m/s. That is a
ratio of 0.33, against the design |C_new / C_old| of 0.34. The phase is 136–144° in both runs.

The once-per-rev disturbance also appears to be smaller in the fw v37 bag. The nominal |S| ratio
predicts v_actual 1x at 0.84–0.86 of before. The measured ratio is 0.60–0.71. Four pre-v37 bags
agree at 15–24 mm/s, and the fw v37 bag reads 10.6–14.5 mm/s. Confidence that the disturbance
changed is moderate: there is one after-bag, and the residual is inside the ±15 % spread of |S|
over the 72 design plants. The bags cannot say whether something mechanical changed between
2026-10-30 and 2026-11-05.

### 2.2 Why the share appeared not to improve

The share 1x reduction is present, but two other terms hide it. These terms are the SDP command
staircase and the H-20 purges, and the drive law touches neither. The staircase explains 90–92 %
of the total share variance. The purges dominate the 2–6 Hz band. Table 3 shows the effect of the
masks.

**Table 3.** Own share, 2–6 Hz rms, fw v35 → fw v37, under successive masks.

| Mask | fw v35 | fw v37 | Ratio |
|---|---:|---:|---:|
| Moving 0x27, nothing excluded | 0.034–0.037 | 0.038–0.041 | 1.1 |
| Purges excluded, command steps kept | 0.029 | 0.024 | 0.81 |
| Purges and command steps excluded (clean) | 0.020–0.028 | 0.011 | 0.40–0.55 |
| Clean, 1x-angle-locked part only | 0.017 | 0.007 | 0.39 |

The unmasked rise from 0.034 to 0.041 comes from the purge term, which is about 67 % of the
2–6 Hz variance in fw v37 and 44 % in fw v35. The purge depth is the same in both bags (10/10
moving purges), so the larger purge share in fw v37 is the purge term standing out after the 1x
term fell.

### 2.3 What did not fall

The 12–24 Hz band did not change. The critic's same-mask check gives share 0.0129 → 0.0119
(0.92x) and I_tot 0.060 → 0.056 A (0.93x). The sensing and share-spectrum analysts agree with it.
The before/after analyst reported a 0.52x fall in that band from a 27 s speed-matched subset; that
figure is the outlier and is not used. The drive-law change therefore moved content only below
about 12 Hz.

The stationary sensor floors did not change. I_batt reads 4.91 / 4.97 mA, V_bus 3.44 / 2.87 mV
and V_batt 8.90 / 9.03 mV (fw v35 / fw v37). This excludes a cable, grounding or temperature
change in the sensing chain between the runs.

### 2.4 Tracking cost seen in the bag

The tracking cost of fw v37 is visible in the bag. Over the 105 s drive window, the speed-error
rms below 0.7 Hz rose from 5.0 to 9.8 mm/s (1.96x; the HIL `ems-drive-cycle` leg gave 1.9x). The
error during acceleration rose from 22.5 to 36.2 mm/s rms. The ramp-tracking delay roughly
doubled, from about 38 to 76 ms on acceleration, which is consistent with 1/ω_c going from 63 to
153 ms. Overshoot at ramp ends did not grow (27–34 mm/s against 31–39 mm/s). The final stop
undershot by 48 mm/s once; this matches the HIL brake-target undershoot item.

## 3. The share-ratio noise spectrum and its components

### 3.1 Noise budget

Table 4 gives the clean-window budget of the uncommanded share n = s − clip(cmd, 0.15, 0.85)
for fw v37 (13 runs, 1950 ticks before; 17 runs, 2524 ticks after).

**Table 4.** Clean-window share budget, band rms, fw v35 → fw v37.

| Band | n total | 1x-locked | I_tot + V_fc coherent | Quantization | Uncorrelated residual |
|---|---|---|---|---|---|
| 2–6 Hz | 0.0237 → 0.0111 | 0.0173 → 0.0068 | 0.0211 → 0.0083 | 0.0011 → 0.0012 | 0.0107 → 0.0072 |
| 6–12 Hz | 0.0130 → 0.0089 | 0.0058 → 0.0019 | 0.0086 → 0.0048 | 0.0014 → 0.0015 | 0.0097 → 0.0073 |
| 12–25 Hz | 0.0125 → 0.0114 | 0.0031 → 0.0019 | 0.0074 → 0.0066 | 0.0020 → 0.0021 | 0.0099 → 0.0091 |

The columns overlap and do not sum. The 1x-locked term is part of the I_tot-coherent term.

### 3.2 Components, ranked by size in fw v37

1. **SDP command steps, 0.1–2 Hz, about 0.05 rms.** These are intended. The loop tracks steps
   larger than 0.3 to 90 % in 1–3 samples (20–60 ms). The loop passes them by design.
2. **H-20 purges, 0.02–0.03 rms in each band.** The drop of s toward 0 during the 80–120 ms
   purge is physical. The firmware adds a kick on top of it. During each purge, the droop ratio
   r = g_BT/(g_FC + g_BT) winds by +0.17 to +0.41 at the low-share rail, partly at
   `DROOP_RATIO_SLEW_HANDOFF_PER_TICK` 0.002 (:3292), because the FC channel reads dark. At the
   0.85 rail it winds by only +0.01 to +0.15, because r saturates. When the stack returns, the
   first I_fc sample is 0.15–0.89 A, up to 3.6x the pre-purge value, and s recovers within
   20–40 ms. This holds in 10/10 moving purges in both bags.
3. **Governor minority floor, the main steady 2–6 Hz term.** At the 0.16 command rail, which is
   73–76 % of run time, `powerBalance()` clips the setpoint to
   `lo = SHARE_MINORITY_I_MIN_A / share_govTotAFilt` (:14581, clamp at :14623). With
   `SHARE_MINORITY_I_MIN_A` 0.125 A, the clip binds whenever the filtered total is below 0.781 A.
   This knee is the mode of the rig's moving total. The floor follows the total current through
   the 19.5 ms EMA (`SHARE_GOV_FILT_ALPHA` 0.05, :3330), which passes most of a 4.6 Hz ripple. The
   setpoint itself therefore moves with the 1x ripple. The predicted setpoint ripple in the floor
   regime is 0.0141 rms (2–6 Hz), against 0.0128 measured for s. The transfer r → s is 0.79–0.97
   at 0 to −12°, which is the signature of reference tracking, not of disturbance rejection.
4. **Load ripple divides at the droop ratio, not at the DC share.** At cmd 0.16 above the knee,
   the 6–25 Hz transfer I_tot → I_fc is 0.255 (phase about −5°, coherence 0.91), while
   s = 0.165 and r = 0.204. The droop slopes set the incremental split, and the no-load offset
   ΔV0 moves the DC split away from it. The estimate ΔV0 ≈ −45 to −65 mV comes from a static fit
   with R² ≤ 0.23 and is low confidence. The resulting share term is about 0.006–0.008 rms.
5. **A flat 6–24 Hz floor, about 0.012 rms, unchanged by fw v37.** The PSD is flat at about
   1.1e-5 /Hz, so it is not shaped by |S|² and is most likely folded content from above 23.8 Hz.
   The standstill sensor floor explains 7–12 % of its variance and quantization about 2 %. The
   share floor times I_tot is roughly constant at 10.8–12.7 mA in every I_tot bin from 0.3 to
   1.5 A (fw v37), so it acts as a fixed differential current of about 1.5 ADC counts. Three
   mechanisms remain open:
   - inter-channel skew, because I_fc and I_batt are read in separate, sequential `analogRead()`
     calls (:7025–7026);
   - aliasing of VESC PWM or boost ripple through the short 16-sample burst average;
   - real 25–500 Hz differential current dynamics.

   The 50 Hz bags cannot separate these mechanisms (Section 7).
6. **Minor terms.** Share quantization is 0.001–0.002 rms per band. The k_d schedule moves the
   share by about 0.0005 after S. MDAC quantization is 0.8–2.3e-4 share per code. V_fc adds
   almost nothing beyond I_tot: the multiple coherence rises from 0.0081 to 0.0083 rms at 2–6 Hz.

The proposed alternative to component 3, a 1x modulation of the load-scheduled k_d, is not
supported. It predicts about 0.0005 rms; the floor term predicts 0.0141. The floor knee at
0.781 A lies next to the k_d crossover at 0.755 A, which is why the share 1x splits by region.

### 3.3 The floor does not hold the FC current constant at 1x

The floor term moves the share, but it does not hold I_fc flat at 1x. Table 5 gives the measured
FC fraction of the 1x total-current ripple at the 0.16 rail (orchestrator check, de-duplicated,
clean windows).

**Table 5.** H(I_fc / I_tot), 2–6 Hz, at `power_share_cmd` 0.16.

| Run | Floor regime (I_tot < 0.78 A) | Above the knee (I_tot ≥ 0.80 A) | I_fc 2–6 Hz rms, floor regime |
|---|---|---|---|
| fw v35 | 0.151 at +43° | 0.165 at +11° | 25.2 mA |
| fw v37 | 0.191 at +26° | 0.232 at −6° | 10.5 mA |

The floor cuts the FC share of the ripple by only 8–18 %. The cause is lag: the 19.5 ms EMA and
the loop's phase at 4.6 Hz put the setpoint motion out of phase with the ripple that it would
need to cancel. Today's behaviour is therefore between the two clean choices, a flat share or a
flat FC current, and it achieves neither. Section 6 (F2) returns to this choice.

## 4. Does the share controller need a bandwidth change?

### 4.1 The loop rejects the 1x band and amplifies nothing in the telemetry band

The share loop rejects the 1x band at the operating point. For the generated coefficients
(Ts 1 ms, measurement prefilter A = 0.2865) and the nominal plant (K 1, Td 1 ms), the discrete
sensitivity is:
- |S| = 0.056–0.112 at 1–2 Hz;
- |S| = 0.112–0.331 at 2–6 Hz, with |S(4.6 Hz)| = 0.256;
- |S| crosses 1 near 22 Hz (|L| = 1 at 17.6 Hz).

Over the design corners, |S(4.6 Hz)| spans 0.18–0.44. The peak ||S|| is 1.32 at 49.6 Hz
(nominal) and 1.80 at 46 Hz (corner K 1.45, Td 2 ms, τr 300 µs). The synthesis file reports
1.867 because it uses a Padé delay with a continuous prefilter. Both peaks lie above the
23.8 Hz telemetry Nyquist, so any amplification there appears folded in the bags. The share PSD
shows no bump at the folded frequencies.

### 4.2 Bandwidth trade

Table 6 gives the effect of scaling the present loop gain. This is a gain-scaling proxy, not a
re-synthesis.

**Table 6.** Share-loop gain scaling.

| Crossover | \|S\| at 2.1 / 4.6 Hz | Nominal \|\|S\|\| | Worst-corner \|\|S\|\| (M2) | rms \|T\|, 0–500 Hz |
|---|---|---|---|---|
| 51 rad/s | 0.254 / 0.514 | 1.14 | 1.29 (0.77) | 0.167 |
| 111 rad/s (now) | 0.118 / 0.256 | 1.32 | 1.80 (0.55) | 0.262 |
| 243 rad/s | 0.052 / 0.114 | 1.93 | 7.83 (0.13) | 0.467 |

A higher bandwidth would reduce only the output-disturbance terms (component 4, about 0.006 rms
at 2–6 Hz). However, at 243 rad/s the worst corner comes within about 16 % of instability, and
measurement noise gains a factor of 1.8 through T. Raising the bandwidth cannot reduce the floor
term (component 3), because that term is a reference and |T(4.6 Hz)| ≈ 1 at any gain. The
purge kick (component 2) is windup, which bandwidth does not address. The present 111 rad/s is
set by the plant delay corner (Td 2 ms with K 1.45).

### 4.3 Interaction with the other noise sources

The share loop does not interact dynamically with the drive loop. The VESC runs in current mode,
so there is no feedback path from the share loop to the motor current. The coupling runs one way:
the drive loop's I_tot ripple enters the share through the governor floor (component 3) and
through the droop-ratio split (component 4). The share loop then tracks the first and partly
rejects the second. The separation between the two loops grew from 6.4x (2.76 Hz drive crossover)
to 17x (1.04 Hz), and fw v37 helped the share entirely by reducing the I_tot ripple.

Two in-situ results are weaker than the model predicts. The transfer from the governor reference
to n at 4.7 Hz measures 0.66∠−57° in fw v37, against about 0.85∠−43° nominal. This hints that the
loop rejects less at I_tot 0.7 A than the nominal model says. In addition, `youlaController_Power()`
(:14728) gates on `now - last >= 1000 µs` with `last = now`, inside a second rate limit with the
same pattern. The drive loop received `DRIVE_CTRL_GATE_TOL_US` for this class of problem; the
share loop did not. The real share step period is unmeasured.

**Verdict.** The share controller bandwidth is not the lever, and the coefficients should not be
regenerated for noise. The levers are the governor floor (Section 6, F2), purge handling (F3),
and the sampling of the two currents (F4). An in-situ S/T measurement at I_tot 0.7 A on a 1 kHz
BLG should precede any later retune (Section 7).

## 5. Freeform findings

### 5.1 Telemetry runs at 47.62 Hz and the bags carry one duplicate row in 21 (new)

The firmware sends telemetry on `if (millis() - lastSend > 20)` and then sets `lastSend = millis()`
(:6812–6816). The strict inequality gives a 21 ms period, which is 47.62 Hz. The bridge
republishes the latest packet on a 50 Hz timer, so one row in 21 is an exact repeat: 398/8356
rows (fw v37), 447/9380 (fw v35), 585/12293 (2026-10-26). There are no triple repeats. The
consequences are:
- The Nyquist frequency is 23.8 Hz, not 25 Hz.
- The repeat pattern is a 2.381 Hz sampling modulation. It puts image lines at f ± 2.38 Hz,
  about −19 to −22 dB below a line at f.
- About half of the "fixed 6.93 Hz line" in `docs/fw37_planning_2026-11-04.md` section 6.1 is
  probably the image of the 1x line at 4.55 Hz. De-duplication halves the PSD at 1x + 2.381 Hz
  in fw v35 cruise I_batt. A 6.84 Hz V_fc line at standstill, 10–12 mV rms, is a separate,
  H-20-side line. The 4.10 Hz line is not explained.
- The EKF and `/h2_usage` use per-packet `_dt`, so they are not biased by the repeats.

### 5.2 The H-20 has a second periodic event at +5.5 s after each purge (new)

V_fc shows a rectangular step of about −0.7 V (−0.68 V at idle, sem 0.002, n = 23 in
2026-10-26), 0.50–0.54 s wide, starting 5.22–5.70 s after every purge onset. It appears in every
purge cycle of the 10-26, 10-30 and 11-05 bags. It is present with the FC off the bus (10-26,
I_fc = 0), so it is internal to the stack or its controller (fan, valve or controller; not
identified). Under load it shrinks to −0.3 to −0.6 V, and I_fc does not change, so the boost
absorbs it. No other channel moves with it. It is far above `LIMIT_V_FC_MIN` 4.5 V. It raises the
bridge's `i_stack` estimate by about 7 % for 5 % of the time, about 0.35 % in hydrogen.

### 5.3 Pack R0 is about 0.025 Ω, and the EKF innovations confirm it (new)

The cross-spectrum of the inferred pack current against V_batt gives a flat 0.021–0.028 Ω over
0.2–12 Hz, with phase within ±10°. High-passed least-squares fits give 0.0235–0.0266 Ω over four
bags. Independently, the `/soc_diagnostics` innovation of the fw v37 bag regresses on `i_pack`
with a slope of +0.0257 Ω. That is the 0.050 Ω placeholder minus a true value of about 0.024 Ω.
The value is referred to the board's V_batt sense point (wiring, connector and the BT_SEQ path
included) and scales with the assumed boost efficiency of 0.90.

### 5.4 The V_batt channel floor is three times V_bus

At rest, V_batt reads 9.0 mV rms (4.3 LSB), white from 1 to 24 Hz, Gaussian, and uncorrelated
with the other channels. V_bus reads 2.9–3.4 mV. While moving, V_batt is at 8.4–10.7 mV, so the
R0·I signal is below the floor except at the 1x line. The cause is not identified (candidates: BT
boost input ripple, or the divider and ADC node). The floor sets the EKF's voltage-measurement
noise; the bridge's `r_meas` 4e-4 V² (σ 20 mV) is about twice the measured floor.

### 5.5 Speed-locked lines near 10 Hz are not rotation orders and did not fall

Lines at 9.9–13.6 Hz, 50–124 mA in 2.56 s windows at about 2.7 m/s, appear in all three
dual-source bags. One example is the 10.0 Hz line at about 137 s, which rose from 37 to 59 mA in
the matched chunk. A 9.96 Hz line in moving I_batt is in phase with I_fc (+11°, coherence 0.66),
so it is common-mode and affects the share little. These lines are not 1x, 2x, 2.31x or 3x, and
fw v37 did not reduce them. The most likely source is folded content above 23.8 Hz locked to
speed (VESC electrical or tire); this is low confidence.

### 5.6 Other findings

- **OC_FC headroom roughly doubled.** The I_fc snapshot maximum went from 1.160 to 0.903 A and
  the 99.9th percentile from 0.996 to 0.857 A. The snapshot margin to the 1.4 A latch went from
  0.24 to 0.50 A. The 1 kHz crest is not sampled.
- **V_fc 2–6 Hz ripple halved**, 0.124 → 0.059 V, following the lower FC current ripple through
  the stack impedance. The stack impedance is about 1.2–1.3 Ω below 1 Hz and 0.37–0.54 Ω at
  7–12 Hz, with capacitive phase.
- **`/h2_usage` is not biased by current noise.** The Faraday integral is linear in current and
  per packet. Its only bias is `purge_g_s` = 0. Against the repo's A0 of 6.633e-5 g/s, the
  bridge under-reports by about 2.1x over 167 s, if the brochure A0 applies to this stack.
- **Single-source operation has about 2.2x the V_bus 1x per ampere** of dual-source operation
  (2026-10-26: 33–38 mV for 0.22 A of 1x current, against 12–18 mV with both sources).
- **The boosts may sit at the PFM boundary.** From the TPS61288 datasheet light-load threshold and
  L = 2.2 µH, the estimated PFM boundary is about 0.56 A (FC) and 0.40 A (BT). The rig's moving
  medians are 0.15 A and 0.48–0.52 A. In PFM the ripple frequency varies with load and aliases
  unpredictably. This estimate uses nominal values and needs a scope on the SW nodes.
- **Purges cap clean windows at about 9.3 s** (465 samples). A purge-excluded Welch estimate
  with nperseg 512 returns nothing.

## 6. Firmware actions with the board as built

The actions are ranked by expected value against risk. Each behavioural change goes through the
`orchestrated-feature` round with host tests and HIL legs. A telemetry layout change goes through
`protocol-bump`. `share_controller_coeffs.h` is generated and must not be edited by hand.

| ID | Action | Expected effect | Risk |
|---|---|---|---|
| F1 | Send telemetry on a fixed 20 ms schedule: `if (millis() - lastSend >= 20) { lastSend += 20; ... }` (:6812). In the bridge, publish on receipt, or republish the Teensy timestamp and counter that it already parses. | Rate becomes 50.0 Hz. The duplicates and their ±2.38 Hz images go away. Bag spectra become correct without de-duplication. | Low. `pollAg105()` runs 5 % more often. Check every test and HIL tool that pins the 21 ms cadence. |
| F2 | Decide the noise metric for the minority rail, then make the governor floor consistent with it. Option (a), recommended if FC stress is the metric: a frequency-split FC reference, I_fc,ref = cmd·LPF(I_tot) with τ about 0.3–1 s, as spEff = I_fc,ref / I_tot. Option (b), if a flat share is the metric: feed the floor `lo` from a separate 100–300 ms filter of the total instead of `share_govTotAFilt`. | (a) FC 1x ripple falls to about \|S(4.6 Hz)\| ≈ 0.26 of today's (10.5 → about 3 mA rms), and the battery takes the fast ripple. The share signal becomes noisier by design. (b) Floor share term at 2–6 Hz falls from 0.013 to about 0.005 (100 ms) or 0.002 (300 ms); I_fc 1x stays at about today's level. | (a) Medium to high. It changes control semantics, and it interacts with the fw v26 ceiling, the fw v28 selector and the cuts. It needs a design ruling and a `governor_model` mirror. (b) Medium. On a falling total the floor under-reads, and I_fc can dip toward `SHARE_HANDOFF_MIN_A` 0.10 A. |
| F3 | Purge-aware share freeze. While a purge-class V_fc dip is detected with FC_BUS closed, hold `share_spEffPrev` and the droop ratio, and freeze the Youla state (no integrator or biquad update, no handoff slew). Use a hard timeout of about 200 ms, then resume from the held ratio. | Removes the +0.17 to +0.41 ratio windup and the post-purge I_fc kick of up to 3.6x (0.89 A). The physical s → 0 dip stays. | Medium. It can mask a real FC dropout for up to the timeout. It interacts with the UV_FC dwell, the fw v30 FC-only lockout, the isolation cuts and the sliver hold. A BLG must first confirm that the detector fires inside the 80–120 ms purge. |
| F4 | Read I_fc and I_batt at the same instant: a synchronous dual-ADC read (pins 40/41 exist on both ADC modules), or an A-B-B-A interleave with averaging 8. Log the duration of `updateSensors()` in micros. | Removes the inter-channel skew. Decides whether the 6–24 Hz share floor (about 0.012 rms) is a sampling artefact. | Low. Keep the single-sample semantics of the 1.4 A OC_FC latch. The test ADC mock needs a sync-read stub. |
| F5 | Telemetry boxcar means: accumulate the analog channels at 1 kHz and send the 20 ms mean. Keep a snapshot or extremum field for fault visibility. This is protocol v5, already queued (`docs/fw37_planning_2026-11-04.md` section 4). | Removes all folding above 23.8 Hz from the bags. White floors fall by up to √20 (V_batt about 9 → 2 mV). The 1x line is attenuated by 1.2 %. Observability only. | Low for control. Needs `protocol-bump` and a lockstep bridge update. |
| F6 | Implement the planned fw v38 1x drive canceller (`docs/fw37_planning_2026-11-04.md` section 9.5). | Reduces I_tot 1x toward the open-loop level. V_bus 1x, the floor share term and the FC 1x ripple scale with it. | As in section 9.5: the margin at ω0 near the 6.55 rad/s crossover (0.5 m/s). |
| F7 | Give `youlaController_Power()` a gate tolerance like `DRIVE_CTRL_GATE_TOL_US`, or a fixed-increment schedule. Log the step period on a BLG. | Restores the designed Ts. The noise effect is not quantified and is probably small. | Low. Needs a cadence test. |

Two actions are not recommended:
- **Share-controller bandwidth change.** It reduces only about 0.006 rms and costs the worst-corner
  margin (Section 4.2).
- **Extra digital filtering of the measured share ahead of `youlaController_Power()`.** The
  0.8 ms prefilter is part of the synthesized plant, and an added lag consumes the 11.74 ms
  delay margin.

Widening `SHARE_KD_HYST_A` from 0.05 to 0.10 A would quieten the MDAC gains, but its share effect
is about 0.0005 rms. It is low priority.

The following items are on the Pi side:
- Set the bridge `pack_r_int_ohm` to about 0.025 Ω and `r_meas` to about 1e-4 V² (σ 10 mV),
  pending a pack-terminal step test (Section 5.3).
- Add a minimum dwell or hysteresis to the SDP share command. This is the largest single
  reduction of raw share variance, but it changes EMS economics and needs an EMS ruling.
- Measure the H-20 purge flow, so that `purge_g_s` is not zero.

The drive-tracking cost (Section 2.4) has its own candidate: setpoint feedforward of
(m_eff·dv_sp/dt + F_drag(v_sp))/K_F, with m_eff 3.5 kg, K_F 0.7538 N/A and F about 2.92 v^0.26 N
(ML0226). This addresses tracking, not noise.

## 7. Open items and the measurement that settles them

The 50 Hz bags cannot resolve anything above 23.8 Hz. Four questions remain open:
1. the origin of the 6–24 Hz share floor (about 0.012 rms, now the largest uncommanded steady
   term);
2. the origin of the speed-locked 10 Hz lines;
3. the in-situ share-loop S/T at I_tot 0.7 A;
4. whether the purge-class dip detector fires inside the 80–120 ms purge.

One bench measurement answers all four. Run the rig at steady cruise (about 2.2 m/s) with the
1 kHz BLG logging, `power_share_cmd` at 0.16 and then at 0.49, for at least 30 s each, with purges
included and flagged. Then repeat the run with action F4 applied. Interpret the result as follows:
- If the I_fc − r·I_tot PSD changes between the two runs, the share floor is a sampling artefact,
  and F4 removes it.
- If the PSD does not change, the floor is physical, and the re-spin filter and boost items
  apply.

The same logs give the pre-fold spectrum of the 10 Hz lines, a direct S/T estimate from the
existing 1x excitation, and the real controller step period.

Two further items are not settled. First, the bags cannot say whether the once-per-rev
disturbance changed mechanically between 2026-10-30 and 2026-11-05 (Section 2.1). The disc
re-seat test in `docs/fw37_planning_2026-11-04.md` section 6.3 discriminates. Second, the cause
of the V_batt floor excess (Section 5.4) is not known; a scope on the BT_VOLTAGE pin settles it.

## 8. Figures

The figures are in `figs/`, named by the agent that produced them:

| File | Content |
|---|---|
| `beforeafter_matched_order_spectra.png` | Matched spectra, fw v35 vs fw v37, per channel |
| `beforeafter_1x_vs_speed.png` | 1x amplitude against speed, all SDP bags |
| `sharespec_peel_psd.png` | Raw share PSD with the purge and command terms peeled |
| `sharespec_budget_psd.png` | Clean-window share budget (Table 4) |
| `sharespec_coherence.png` | Share coherence with I_tot, V_fc, droop gains and the 1x angle |
| `sharespec_purge_overlay.png` | Share, I_fc and droop ratio across the 10 moving purges |
| `sharemodel_loop_and_disturbance_bode.png` | \|S\|, \|T\| and disturbance-to-share transfers |
| `sharemodel_kd_and_floor_schedule.png` | k_d schedule and minority floor against I_tot |
| `sharemodel_share_psd_by_regime.png` | Share PSD in the floor and non-floor regimes |
| `freeform_dup_image.png` | Duplicate-row images around the 1x line |
| `freeform_rail_share_vs_load.png` | Delivered share against load at the 0.16 rail |
| `freeform_fc_midcycle_dip.png` | The +5.5 s V_fc event |
| `freeform_purge_epoch.png` | Purge-locked epoch averages |
| `sensing_asd_vs_floor.png` | Current and share ASDs against the standstill floor |

The agents' full reports and the verifier verdicts are in `agents/`.
