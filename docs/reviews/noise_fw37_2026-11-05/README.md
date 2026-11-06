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

### 2.4 V_bus is the droop image of the total current at 1x only

The bus voltage follows V_bus ≈ V0 − Z·I_tot, where Z is the bus impedance that the two droops
set in parallel. Table 3a gives Z, estimated per band from the I_tot → V_bus cross-spectrum, and
the fraction of the V_bus variance that I_tot explains (coherence). The windows are the clean
cruise windows of this section.

**Table 3a.** Bus impedance and the droop-driven part of V_bus.

| Run | Band | \|Z\| (mΩ) | V_bus rms (mV) | Variance explained by I_tot |
|---|---|---:|---:|---:|
| fw v35 | 2–6 Hz | 57 | 10.8 | 67 % |
| fw v35 | 6–24 Hz | 41–47 | 7.0–8.7 | 9–12 % |
| fw v37 | 2–6 Hz | 41 | 5.4 | 21 % |
| fw v37 | 6–24 Hz | not resolved | 5.5–8.1 | 5–7 % |
| Battery only (2026-10-26) | 2–6 Hz | 159 | 23.1 | 92 % |

At the 1x line, V_bus/I_tot is 14.2 mV / 213 mA = 67 mΩ before and 3.9 mV / 53.5 mA = 73 mΩ
after. The impedance did not change, so the V_bus 1x reduction (0.28x) is the I_tot 1x reduction
(0.25x) passed through an unchanged droop.

The measured impedance is about 0.2 of the design value. Two droops of k_d/r and k_d/(1 − r) in
parallel give k_d, which is 0.30–0.36 Ω by design. The measured 40–70 mΩ agrees with the
realized droop of about 0.21 of design (`agents/sharemodel.md`, Section 2(c)). With the battery alone, Z is 159 mΩ, so dual-source operation roughly
halves the bus impedance.

Most of the remaining V_bus noise in fw v37 does not come through the droop. In 2–6 Hz, 79 % of
the variance is incoherent with I_tot; above 6 Hz, more than 90 % is incoherent in both runs. The
standstill floor (2.9 mV broadband) explains only 1.2–2 mV per band. Real total-current ripple
above 6 Hz would appear on V_bus through Z. Either the 6–24 Hz I_tot content is partly a sampling
artefact, or V_bus carries an independent noise source. The 1 kHz BLG run of Section 7 settles
this as well. In addition, the fw v35 2–6 Hz impedance below the 0.755 A knee (45 mΩ) is lower
than above it (71 mΩ), which is the opposite of the k_d schedule. A likely cause is the floor
regime moving the droop codes, and therefore V0, with I_tot. This is low confidence (339 ticks).

Consequently, V_bus at 1x falls further only with less I_tot ripple (action F6) or a lower bus
impedance. A lower impedance means a lower droop, which reduces share authority and increases the
share's sensitivity to ΔV0.

### 2.5 Tracking cost seen in the bag

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

   The 50 Hz bags cannot separate these mechanisms (Section 7). **Update (Section 9):** the 1 kHz
   log ML0226 rules out inter-channel skew (I_fc to I_batt is one read slot, 0.9° at 20 Hz). On
   the bench, 84–95 % of the snapshot share variance in 6–24 Hz is folded content from above
   23.8 Hz.
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
- **The FC boost always runs in PFM, and the BT boost runs near its boundary.** The corrected
  estimate is in Section 9.2: FC 0.57–0.75 A, BT 0.45 A. The rig's moving medians are 0.15 A and
  0.48–0.52 A. The PFM ripple frequencies are far above the ADC band, and their contribution to
  V_bus is small (Section 9.2).
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

The drive-tracking cost (Section 2.5) has its own candidate: setpoint feedforward of
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

## 9. V_bus ripple: switching noise and the RT1987 ideal diodes (follow-up, 2026-11-06)

This section explains the V_bus noise that Section 2.4 found not to come through the droop. It
compares that noise with the expected switching noise and with the behaviour of the RT1987 ideal
diodes. Four analysts ran in parallel: an RT1987 topology and physics review, a switching-noise
budget, an analysis of the 1 kHz SD logs, and dependence tests on the bags. Two adversarial
verifiers checked each claim, and a critic reconciled the reports. The reports are
`agents/vbus_*.md`.

The main 1 kHz log is ML0226 (fw v37, bench, closed- and open-loop speed holds). Its FC input is a
bench supply (11.06 V, no purges), and its battery input is the pack. No 1 kHz log exists with the
H-20 on the FC input.

### 9.1 The firmware loop runs at about 875–884 Hz, not 1 kHz

The loop in `loop()` (:6768) is free-running. The 1000 µs rate limiter (`POWER_BAL_PERIOD_US`)
is shorter than one loop pass, so it never holds the loop back. The median tick in ML0226 is
1131 µs (884 Hz), and the mean is 1142–1153 µs (867–875 Hz), with a second mode at 1332 µs. The
BLG logs every pass. The bag telemetry rate of 47.62 Hz implies a loop of 1.0 ms or less in Run
without SD logging; the vehicle loop rate is `TODO(verify)`.

The seven `analogRead()` calls take about 83 µs each. The phase delay of the speed-locked line
between V_bus and V_rgn, two reads apart, gives 166 µs. V_bus is therefore read about 300 µs
after I_fc. I_fc and I_batt are adjacent reads, so their skew is negligible for the share.

### 9.2 What each source contributes

Table 9 ranks the sources of the V_bus noise that the bag sees at fw v37 cruise. The total there
is about 12.6 mV rms per sample. The variance split comes from ML0226 at 1.5–2.0 m/s and is scaled
to the vehicle. That scaling is unverified.

**Table 9.** Budget of the V_bus noise in the bag band (fw v37 cruise).

| Rank | Source | Expected mV rms | Confidence |
|---|---|---:|---|
| 1 | Folded speed-locked bus ripple: the motor 6x electrical line plus 1x electrical and its orders, through the bus impedance | 8–10 | Medium |
| 2 | Folded broadband excess, incoherent between channels; the leading candidate is VESC PWM ripple aliasing through the 16-sample ADC average | 5–6 | Low to medium |
| 3 | ADC floor, folded | 2.7–3.3 | High |
| 4 | Real in-band droop response to I_tot (1x, 2–6 Hz) | about 2.4 | High |
| 5 | TPS61288 switching and PFM ripple aliased through the 16-sample average | ≤ 1.2 | Medium |
| 6 | RT1987 in-band effect (about 10 mΩ series, common 35 mV offset, no dropout or chatter) | ≤ 0.6 | Medium to high |

The quadrature sum of the central values is about 12.3 mV, against 12.6 mV measured.

The dominant source is the motor's 6x electrical line. Its frequency is 397 Hz per m/s
(6 × f_e, with f_e = 2.089 × 15.84 × 2 pole pairs per m/s), so it is real at 600–1000 Hz at
cruise. In ML0226 it carries 61–66 % of the snapshot variance at 1.5–2.0 m/s. It is coherent with
I_tot at 0.94–0.99, with I_fc and I_batt at 0.99, and with the commanded motor current I_cmd at
only 0.01–0.05. It is therefore real bus current drawn by the VESC, not a measurement artefact.
The bus impedance at this line is 81–133 mΩ, about 1.5x the 2–134 Hz value of 52–98 mΩ.

The TPS61288 contributes little to V_bus. Re-derived from DS §8.4.2 (p.11–12), L = 2.2 µH and
f_sw = 500 kHz, the PFM boundary is about 0.45 A for BT (7.7 V) and 0.57–0.75 A for FC
(9.5–11 V). The FC boost therefore always runs in PFM, and the BT boost runs near its boundary at
cruise. All PFM frequencies are far above the ADC band. The motor-on broadband floor of V_bus
rises from 0.44 to only 0.51 LSB, so aliased boost ripple on V_bus is at most 1.2 mV per sample.
The ripple is large elsewhere: I_fc broadband rises from 0.42 to 5.0 LSB (about 40 mA per sample)
and V_fc from 5–7 to 25–29 LSB. The INA253 shunt sits upstream of the RT1987, so the shunt sees
the boost output ripple that the bus does not.

The standstill floor is the ADC chain. V_bus, V_rgn, I_fc and I_batt all read 0.42–0.50 LSB at
standstill, and their cross-channel correlation is at most 0.06, so a common reference term is
excluded. The vehicle standstill floor (2.9–3.5 mV, and 4.7–4.9 mV in the battery-only bag) is
higher than the bench floor (2.2–2.5 mV per snapshot). This difference is not explained.

### 9.3 The RT1987 ideal diodes

The RT1987 adds no measurable noise to V_bus. Its effects are as follows:
- **Topology.** On the 20260622 netlist, each path runs from the boost output (FB tap and output
  ceramics) through the INA253 shunt, a 10 µF capacitor and the RT1987 to the common VBUS node.
  The V_bus divider taps the post-diode VBUS node. The shunt and the switch are therefore outside
  each boost's regulation and droop loop.
- **Forward regulation.** The servo holds VIN − VOUT at about 35 mV while I·RON < 35 mV, that is
  below about 1.75 A (DS p.7, §17.6 p.16). Every rig current is in this regime. The typical curve
  (DS p.13, VIN 28 V) is not flat: it reads 35 / 46 / 55 mV at 0 / 1 / 2 A, so the incremental
  resistance is about 10.5 mΩ.
- **Effect on the share.** The common 35 mV offset cancels in the split. VFWD changes by only
  0.03 mV/°C, and its part-to-part spread is not specified (`TODO(verify: Richtek)`). The RT1987
  is therefore not the source of the −45 to −65 mV ΔV0 estimate. The TPS61288 reference tolerance
  (0.588–0.612 V, DS §6.5 p.6, about ±320 mV at 16 V) can account for it.
- **Light load.** No dropout or limit cycle occurs at the FC minority floor:
  - ML0226: 0 of 245 879 ticks with I_tot > 0.2 A have I_fc below 4 mA; the minimum is 0.048 A.
  - Bags: every zero I_fc sample while moving falls inside a purge.
  - I_fc and I_batt are positively correlated in every band, so the two sources do not trade
    current.
- **Above the servo bandwidth.** The datasheet does not give the servo bandwidth. Above it, the
  switch acts as a resistance of about VFWD/I: 0.23 Ω at 0.15 A and 0.07 Ω at 0.5 A. With the VBUS
  ceramics this forms a low-pass of 9–120 kHz, which attenuates the boost ripple by 0.03–0.36. The
  same mechanism is a candidate for the impedance rise at 600–800 Hz (Section 9.2). Neither effect
  has been measured.
- **HIL model.** The HIL plant models the drop as 35 mV + I × 21 mΩ (`tools/hil_electrical.py`
  :139–140, :1601). Against the typical curve this overstates the drop by 1.5 mV at 0.15 A and by
  10 mV at 1 A. The error does not matter for the share or the handoff logic, because
  `DROOP_FIXED_SERIES_OHM` (0.033 Ω) lands on the empirical series resistance of 30 mΩ.

### 9.4 Why the bags show low coherence and a flat spectrum

The bag's low V_bus–I_tot coherence above 6 Hz does not show an independent voltage source. Two
effects explain it:
- **Folding.** In ML0226, 72–98 % of the 21 ms snapshot V_bus variance below 23.8 Hz is folded
  content from above 23.8 Hz. At standstill the snapshot reads 2.3–2.5 mV against 0.56 mV of true
  in-band content. A 21 ms boxcar mean followed by decimation removes the fold almost completely
  (`figs/vbus_blg1k_fold.png`). Folding many components with different transfer functions
  scrambles coherence: the bench line coherence of 0.94–0.99 falls to 0.08–0.39 after decimation.
- **Read skew.** V_bus is read about 300 µs after the currents. For the 6x line the same-tick
  correlation goes as cos(2π · 397 v · 0.33 ms). It is +0.34 at 1.5 m/s and −0.48 at 2.5 m/s, so
  pooling over speed drives it to about zero.

The bag excess is white: the fw v37 cruise bands of 5.7 / 6.2 / 8.7 mV match the 5.2 / 6.4 /
8.9 mV that white noise of 12.6 mV per sample predicts. The 12–23.8 Hz band is larger only
because it is wider. Speed is the only variable that moves the bag residual by a large amount:
from 3.1 mV below 0.5 m/s to 13.5 mV at 2.5–3.5 m/s. I_fc level, I_batt across the BT PFM
boundary, the share command and the time since a purge each change it by at most ±8 %.

### 9.5 Consequences

A 20 ms boxcar mean in the telemetry (action F5) would remove most of the V_bus and share noise
that the bags show. However, the loop itself samples at 875–1000 Hz, so the 6x line folds near
DC in the control samples when v ≈ f_loop / 397, which is about 2.2–2.5 m/s, the cruise speed. A
boxcar applied after sampling cannot remove that alias. Only an analog filter at the ADC pin, or
averaging over the full tick, prevents it. That near-DC alias also reaches the drive and share
controllers, which use the same samples. Its size in the vehicle is not measured.

The firmware and re-spin actions from this section are:
- **Firmware:** keep F5. Add continuous ADC conversion that averages over the full tick (the
  DMA proposal in `agents/sensing.md`), which places nulls at multiples of the loop rate.
  Stamp `micros()` around `updateSensors()` and log the loop period. Consider a fixed 1 kHz loop
  so that the sampling and the logs have a defined rate.
- **Re-spin:** an RC at the V_bus divider tap (100 nF gives 194 Hz with the 8.2 kΩ source), test
  points across each RT1987, and better VESC input decoupling at V-MOT to reduce the 6x line at
  its source. The details are in `docs/respin_noise_notes_2026-11-05.md`.

### 9.6 The measurement that settles the rest

A vehicle 1 kHz `K` log with the H-20 and the pack (switch state 0x27) settles most of the open
items. The run needs 10 s at standstill, steady holds of at least 15 s each at 1.0, 1.5, 2.0 and
2.5 m/s, and at least one natural purge. It gives:
- the vehicle loop rate;
- the vehicle split of the V_bus excess into folded line, broadband excess and floor;
- the vehicle standstill floor;
- the bus impedance at 1x and 6x at the vehicle operating point;
- the first look at a purge and at the RT1987 at 1 kHz.

A differential scope across VIN–VOUT of D-FC and D-BT at 2 m/s would settle the RT1987
high-frequency behaviour. The board has no test points for this.

**Figures for this section:**

| File | Content |
|---|---|
| `vbus_blg1k_fold.png` | True, snapshot and boxcar V_bus band rms for each ML0226 segment |
| `vbus_blg1k_psd.png` | V_bus ASD by condition; single versus dual source |
| `vbus_switching_speedline.png` | ML0226 V_bus spectrogram with the speed-locked line. The frequency axis assumes a 1 kHz sample rate; multiply by 0.876 for true Hz. |
| `vbus_switching_budget.png` | Switching budget against measurement |
| `vbus_rt1987_drop_and_spectra.png` | RT1987 drop models and the V_bus spectra |
| `vbus_bagtest_residual_dependence.png` | Bag residual against speed, currents and load |
