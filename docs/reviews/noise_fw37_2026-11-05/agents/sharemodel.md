## Share-loop model and firmware path (label: sharemodel)

**Answer first.** At the operating point, the share loop rejects the 1x band and is not the source of the 1x share ripple, so it does not need a bandwidth change. Nominal discrete |S| (generated coeffs, Ts 1 ms, K 1, Td 1 ms, firmware prefilter A = 0.2865) is:

- 0.056-0.112 at 1-2 Hz;
- 0.112-0.331 at 2-6 Hz (0.256 at 4.6 Hz);
- 0.33-1.09 at 6-25 Hz, crossing |S| = 1 near 22 Hz.

||S|| is 1.32 at 49.5 Hz nominally and 1.80 at 46 Hz at the corner K 1.45 / Td 2 ms; the design file reports 1.867. Both peaks sit above the 23.8 Hz telemetry Nyquist. 49.5 Hz folds to about 1.9 Hz in the bags.

The dominant remaining 1x share ripple comes from the setpoint. `powerBalance()` clamps the commanded share up to a minority-current floor that follows the filtered total `share_govTotAFilt`. The EMA has τ = 19.5 ms, which is effectively unfiltered at 1x. The loop tracks this moving setpoint with |T| ≈ 1. The share loop does not amplify anything here; it simply tracks the setpoint it is given.

### 1. Correction to the quick scan: share noise went DOWN with fw v37

Method:
- Windows: switch_state 0x27, v > 0.3, I_tot > 0.3 A.
- Exclusions: H-20 purges ±0.5 s; every `power_share_cmd` change -0.2 s/+1.0 s, with the cmd held ZOH (not interpolated).
- Bridge duplicates removed (below). Butterworth band-pass applied with filtfilt per segment.

Own share s = I_fc/I_tot, 2-6 Hz RMS, before (10-30_01-49-38, fw v35) → after (11-05_20-09-52, fw v37 rev 2):

| steady window | N before / after | s 2-6 Hz | r (codes) 2-6 Hz | I_tot 2-6 Hz | s 6-23 Hz |
|---|---|---|---|---|---|
| all | 772 / 1433 | 0.0200 → **0.0108** | 0.0227 → 0.0103 | 0.134 → 0.043 A | 0.0180 → 0.0140 |
| floor (cmd < 0.125/I_tot) | 370 / 968 | 0.0268 → 0.0128 | 0.0299 → 0.0128 | 0.157 → 0.044 | 0.0194 → 0.0144 |
| cmd 0.16, not floor (k_d = 0.300) | 297 / 409 | 0.0075 → 0.0051 | 0.0108 → 0.0023 | 0.120 → 0.033 | 0.0151 → 0.0131 |

Two effects inflated the scan's "share UP" (0.029 → 0.044):
- **SDP command steps.** There are 88 cmd changes per bag, and in the 0.2 < cmd < 0.8 band the coherence(cmd, s) at 2-6 Hz is 0.97-0.98. That is the step response, not noise.
- **Bridge duplicates.** The Teensy sends every 21 ms (`if (millis() - lastSend > 20)`, `teensy_controller.ino:6812`), i.e. 47.62 Hz. The bridge republishes the latest packet on a 50 Hz timer (`teensy_bridge_node_2026-11-03A.py:599`). The result is one exact duplicate every 21 samples: 456/9379 rows (4.86 %) before and 404/8355 (4.84 %) after. A simulation shows this puts sidebands at about 10-12 % amplitude at f ± 2.38 Hz on any line; a 4.6 Hz line lands at 2.2 and 7.0 Hz. **Bag spectra must be de-duplicated and treated as 47.62 Hz.** The "fixed" 6.93 Hz line could be a 4.55 Hz + 2.38 Hz sideband; this is unverified.

Confidence is moderate. The steady windows are short (16 s before, 30 s after; 6 and 9 segments).

### 2. The share-noise components (after, steady)

**(a) Minority-floor setpoint, the dominant 1x term when active.** `const float lo = SHARE_MINORITY_I_MIN_A / share_govTotAFilt;` and `spTarget = constrain(spTarget, lo, hi)` (`:14582`, `:14623`). With cmd 0.16 and `SHARE_MINORITY_I_MIN_A` 0.125 A, the knee sits at I_tot = **0.781 A**, which is the mode of the rig's moving-total distribution. Below the knee the firmware commands a constant I_fc of 0.125 A, so δs = -(0.125/I²)·δI_tot (-0.34 /A at 0.60 A).

Evidence for this term:
- I_fc 2-6 Hz RMS is lowest in this regime (0.0105 A after), as a constant-FC-current law predicts.
- Predicted spEff = max(cmd, 0.125/EMA(I_tot)) has 2-6 Hz RMS 0.0307/0.0141 against measured s 0.0268/0.0128 (before/after).
- r → s at 2-6 Hz: |H| 0.79-0.97, phase -0 to -12°, coherence 0.66-0.90. This in-phase, unity-gain relation is the reference-tracking signature; an output disturbance being rejected would show |H| ≈ |1/(CF)| ≈ 0.26 at about -90°.
- I_tot → r phase is 129-143°, against a predicted ≈ 150° (sign inversion minus EMA lag).
- The term is about 62 % of steady samples after (lo > cmd).

**(b) The folded broadband floor.** This term is common to all regimes. The share PSD is flat at about 1.1e-5 /Hz from 6 to 23.8 Hz (20-23/7-9 Hz ratio 0.86-1.66), so it is not |S|²-shaped and is mostly a fold. Integrated over 2-6 Hz it gives ≈ 0.0065, which explains all of the non-floor 2-6 Hz residual (0.0051; coherence(r, s) 0.16, controller quiet at r 0.0023).

The fold is real current ripple, not sensor noise:
- 10-23 Hz I_bt is 3.3e-4 A²/Hz (≈ 0.065 A RMS) against an idle I_bt σ of 4.5-5.6 mA (< 1 LSB of 8.06 mA).
- Its source above 23.8 Hz cannot be resolved from 47.6 Hz snapshots; a 1 kHz BLG is needed.

**(c) Small terms (split law, `governor_split_law_20260903.md` §9 candidate (c), I 0.74 A, r 0.2).** All three are an order of magnitude below (a) at 1x:
- dα/dI at fixed k_d: -0.012 /A.
- The k_d schedule: dα/dk_d -0.14 /Ω × dk_d/dI -0.41 Ω/A = +0.06 /A before S. Measured k_d 2-6 Hz ripple is 0.015 Ω after (0.043 before), which gives ≈ 0.0005 share after S.
- Differential V₀ ripple: 2.5-3.0 share per real volt. This is very large because the realized droop is about 0.21 × design, but it needs a differential 1x V₀ ripple, which is unobserved.

**(d) Remaining sources.**
- V_fc ripple enters only through TPS61288 line rejection (converter crossover 7-22 kHz), so it is negligible below 25 Hz. This is not measured.
- MDAC quantization is 0.8-2.3e-4 share per code at r 0.25, which is negligible.

### 3. Firmware path per tick (file:line)

1. **Sensing.** `loop()` → `updateSensors()` (`:6894`) runs every iteration. I_fc and I_batt are single `analogRead` snapshots, sequential, with `analogReadAveraging(16)` (`:6682`). That is a burst of tens of µs, so there is no anti-alias for the 25-500 Hz content.
2. **Total filter.** `share_govTotAFilt` is an EMA with α 0.05 per 1 ms tick (τ 19.5 ms; `:14292`).
3. **k_d schedule.** It runs off the hysteretic input `shareKdSchedTot` (0.05 A, `:13899`), slewed at 2.35 %/tick. Its kink is at 0.755 A, also at the operating point.
4. **Setpoint chain.** Floor clamp → `applyShareCurrentCeilings()` → `share_spEffPrev` slew (0.02/tick).
5. **Controller.** `youlaController_Power()` (`:14728`) prefilters alphaRaw at 200 Hz and is gated by `now - last >= 1000 µs` with `last = now`. It is nested inside `rateLimitDue` (also `last = now`), so the period is ≥ 1 ms plus jitter and it can skip a step. The drive loop received `DRIVE_CTRL_GATE_TOL_US` for this class of problem; the share loop did not. The effect is unmeasured.
6. **Telemetry.** `sendTelemetry()` packs instantaneous snapshots (no averaging) at 47.62 Hz.

The share path is byte-identical between v35 and v37 rev 2: `git diff ab4a705 da0746c` touches only `drive_controller_coeffs.h` and non-share `.ino` lines.

### 4. Bandwidth trade (gain-scaling proxy, not a re-synthesis)

| crossover | \|S\| 2.1 / 4.6 Hz | nominal \|\|S\|\| | worst corner \|\|S\|\| (M2) | rms\|T\| 0-500 Hz |
|---|---|---|---|---|
| 51 rad/s | 0.254 / 0.514 | 1.14 | 1.29 (0.77) | 0.167 |
| 111 rad/s (now) | 0.118 / 0.256 | 1.32 | 1.80 (0.55) | 0.262 |
| 243 rad/s | 0.052 / 0.114 | 1.93 | 7.83 (0.13) | 0.467 |

The present 110 rad/s is limited by the plant corner set: the Td 2 ms delay together with K 1.45. Raising it cannot reduce the dominant term (a), because that term is reference-driven with |T| ≈ 1 at any bandwidth. It would roughly halve only the small output-disturbance part, and it nearly destabilizes the worst corner. Lowering it to about 50 rad/s doubles |S| in the 1x band.

The drive/share separation is 6.4× before (2.76 vs 17.6 Hz) and 17× after (1.04 Hz). The coupling runs one way only: drive I_tot ripple → floor/k_d → share. There is no feedback path to the motor current (VESC in current mode), so there is no closed-loop interaction at either crossover. v37 helped the share loop entirely by cutting the I_tot ripple.

### 5. Interpretation that matters for the next step

In the floor regime, the "share noise" is the battery absorbing the 1x ripple while I_fc stays at its 0.125 A floor. Physically this is the desirable outcome for the H-20. Share ratio is the wrong noise metric there; the metric should be I_fc ripple. A firmware change that makes the share signal flatter would push more 1x ripple into the fuel cell.

Unverified:
- the source of the content above 23.8 Hz;
- whether the 6.93 Hz line survives de-duplication;
- the real share-loop step period;
- the split-law constants near r 0.2. The law predicts α(0.2) = 0.26, but the bags show about 0.20 at r 0.25, so it over-predicts near the rail.

## Adversarial verification (data and physics lenses)

- [C1] With steady windows (0x27, v>0.3, I_tot>0.3, purges ±0.5 s and cmd changes -0.2/+1.0 s excluded, duplicates removed), the own-share 2-6 Hz RMS fell from 0.0200 (fw v35, 10-30_01-49-38, N=772) to 0.0108 (fw v37r2, 11-05_20-09-52, N=1433); the scan's 'share up' came from SDP command-step tracking (coherence(cmd,s) 0.97-0.98 at 2-6 Hz in the 0.2<cmd<0.8 band) and mixed windows.
   data: PARTLY -- In steady windows (0x27, v>0.3, I_tot>0.3, purges ±0.5 s and cmd changes -0.2/+1.0 s excluded, duplicates removed), the own-share 2-6 Hz RMS fell from about 0.020 (fw v35, 10-30_01-49-38) to about 0.011 (fw v37r2, 11-05_20-09-52). Two independent estimators agree to within 5 %, though the before sample is small (507 samples after trimming). Command-step tracking adds about 0.01 RMS to both bags (coherence(cmd,s) 2-6 Hz: 0.86-0.95 before, 0.93-0.97 after), but on its own it does not make after ex
   physics: PARTLY -- With steady windows (0x27, v>0.3, I_tot>0.3, purges ±0.5 s and cmd changes -0.2/+1.0 s excluded, duplicates removed), own-share 2-6 Hz RMS fell from 0.0200 (fw v35, 10-30_01-49-38; 6 segments, N≈500 after trim) to 0.0108 (fw v37r2, 11-05_20-09-52; 9 segments, N≈1000), a 1.85x drop against a 3.1x drop in I_tot 2-6 Hz ripple (0.134 -> 0.043 A).

The scan's 'share up' is mainly an H-20 purge artefact:
- Purges excluded but cmd steps kept: 0.0291 -> 0.0235 (down).
- Purges kept: 0.0372 -> 0.0398 (up
- [C2] The dominant remaining 1x share ripple is reference-driven by the minority-floor clamp spTarget=constrain(cmd, 0.125/share_govTotAFilt, hi) (teensy_controller.ino:14582/14623): predicted spEff 2-6 Hz RMS 0.0141 against measured s 0.0128 after (0.0307 vs 0.0268 before), with r→s gain 0.79-0.97 at -0..-12 deg (unity in-phase tracking, not rejection) and I_tot→r phase 129-143 deg.
   data: PARTLY -- In floor-clamped spans (cmd 0.16, I_tot about 0.6 A), the predicted 2-6 Hz spEff ripple matches the measured share ripple in RMS: 0.029-0.032 against 0.027-0.030 before, and 0.012-0.015 against 0.012-0.014 after. The droop ratio r is delivered almost one-to-one (|H(r->s)| 0.83-0.99 at -4 to -14 deg).
For fw v35 (before), the data agree with share ripple driven by the reference through the minority floor 0.125/I_tot_filt: I_tot->r is 132-152 deg and I_tot->s is about 125 deg.
For fw v37 (after), 
   physics: PARTLY -- The claim holds in part. In the steady floor regime (cmd 0.16 < 0.125/I_tot, both sources on the bus), the minority-floor clamp at teensy_controller.ino:14623 turns the 1x total-current ripple into reference motion. In the 2-6 Hz band the predicted spEff RMS is 0.0141 against 0.0128 measured for s after (0.0307 against 0.0268 before). r->s is 0.79-0.97 at -12..+1 deg, which is in-phase tracking by the droop path. I_tot->r is 0.16-0.22/A at 136-175 deg, which matches -0.125/I^2 through the 19.5 m
- [C3] The share loop rejects the 1x band: nominal discrete |S| is 0.112-0.331 over 2-6 Hz (0.256 at 4.6 Hz) and crosses 1 near 22 Hz; ||S|| is 1.32 at 49.5 Hz nominal and 1.80 at 46 Hz at the corner (K 1.45, Td 2 ms), both above the 23.8 Hz telemetry Nyquist.
   data: CONFIRMED -- CONFIRMED as stated. The share loop rejects the 1x band: in the nominal design model, discrete |S| is 0.112-0.332 over 2-6 Hz (0.256 at 4.6 Hz) and crosses 1 at about 22 Hz. At the corner (K 1.45, Td 2 ms, taur 300 us) the 2-6 Hz range is 0.078-0.235 (0.179 at 4.6 Hz). The model's ||S|| peak is 1.32 at 49.6 Hz nominal and 1.80 at 46 Hz at the corner, with the exact delay. Both are above the telemetry Nyquist (23.8-25 Hz), so in 50 Hz snapshots any peak amplification appears folded, not at its tr
   physics: CONFIRMED -- In the linear, unsaturated regime the share loop attenuates the 1x band. Nominal discrete |S| is 0.112-0.332 over 2-6 Hz and 0.256 at 4.6 Hz; |S| rises above 1 at about 22 Hz (|L| = 1 at 17.6 Hz).

The sensitivity peak ||S|| is 1.32 at 49.6 Hz nominal and 1.80 at 46 Hz at the worst corner (K 1.45, Td 2 ms, taur 300 us). The synthesis reports 1.867 because it uses a Pade-2 delay with a continuous tauf.

Across the design corners, |S(4.6 Hz)| ranges from 0.18 to 0.44. The 46-50 Hz amplification ba
- [C4] Raising the share crossover to ~243 rad/s (gain ×2.27) cuts |S| at 4.6 Hz only from 0.256 to 0.114 but drives the worst-corner ||S|| from 1.80 to 7.83 (M2 0.13), and it cannot touch the reference-driven floor term (|T|≈1 at any bandwidth); the present bandwidth is limited by the plant delay corner.
   data: CONFIRMED -- Scaling the present Youla-H share controller's loop gain by 2.27 (|L|=1 at ~38.6 Hz, ~243 rad/s) lowers |S| at 4.6 Hz from 0.256 to 0.114 (a 2.25x / -7 dB cut of the disturbance-driven part) but raises the worst-corner ||S|| over K 0.55-1.45 x Td 0.5-2 ms x taur 20-300 us from 1.80 to 7.83 (M2 0.13) at K 1.45 / Td 2 ms / taur 300 us, ~16 % gain short of instability (unstable near g 2.7-3.0). |T| at 4.6 Hz stays ~1.0 at either gain, so a reference-driven component cannot be cut by bandwidth. The 
   physics: CONFIRMED -- Uniformly raising the share-loop gain by 2.27x moves the crossover from 111 to 243 rad/s. That cuts |S| at 4.6 Hz from 0.256 to 0.114. It also raises the worst-corner ||S|| over the 30-corner grid from 1.80 to 7.83 (M2 0.13, at K 1.45 / Td 2 ms / taur 300 us); the loop stays stable, and goes unstable at about 3x. It cannot reduce reference-driven content, because |T| at 4.6 Hz is about 1 at every gain. The Td = 2 ms delay corner limits the bandwidth. This is a gain-scaling proxy, not a re-synthe
- [C5] The bags carry one exact duplicate row every 21 samples (456/9379 = 4.86 % before, 404/8355 = 4.84 % after) because the Teensy sends every 21 ms (millis()-lastSend > 20, :6812) and the bridge republishes on a 50 Hz timer; this puts ~10-12 % sidebands at f ± 2.38 Hz on any line.
   data: PARTLY -- The bags carry one repeated row per 21 publishes: 456/9379 before and 404/8355 after on the 6-column check, and 4.76 % = 1/21 on full rows. The cause is that the Teensy sends every 21 ms (millis()-lastSend > 20, teensy_controller.ino:6812) while the bridge republishes the latest packet on a 50 Hz timer (:599, publish_hz 50.0). The resulting 0-20 ms sawtooth timing error at 2.381 Hz phase-modulates any line f. That gives first-order sidebands at f ± 2.38 Hz of about 2.5 % per Hz of f: ~9 %/11 % (
   physics: PARTLY -- About 4.85 % of the bag rows are exact repeats, spaced every 21 samples. The cause is a beat between the Teensy's 21 ms send period (`millis()-lastSend > 20` re-latched each send, teensy_controller.ino:6812-6815; 47.62 Hz) and the bridge's 50 Hz take-latest publish timer (teensy_bridge_node_2026-11-03A.py:599). The expected rate is 4.76 %; the small excess fits occasional 22 ms gaps from pollAg105() I2C. The repeats act as a sawtooth timing error of about 20 ms peak-to-peak, which phase-modulate