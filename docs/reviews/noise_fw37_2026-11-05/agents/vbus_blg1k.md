## blg1k: V_bus at the loop rate, and what folds into the bag telemetry

### 1. Inventory and time base
- **ML0226** (fw v37, BLG v9, BENCH_TEST 1, State 98, 422 s). FC input: a stiff bench DC supply (V_fc flat at 11.00-11.12 V with no purge dips; the same-day ML0227 entry documents a bench supply at 10-11 V, `docs/boost-bringup-debug.md:1530`). BT input: the 2S pack at 7.66-7.73 V. Both sources are on the bus with share_sp 0.50 throughout. Currents are I_fc 0.06-0.32 A and I_batt 0.03-0.30 A. The segments are: standstill with I_cmd 0 (0.3-3.5 s and 419.5-421.9 s); open-loop `A` 3.0/3.4/3.8/4.2 A (OL3.0..OL4.2); closed-loop `V` 0.5/1.0/1.5/2.0 m/s (CL0.5..CL2.0).
- **The loop does not run at 1 kHz.** The median tick is 1131 us, so fs = 884.2 Hz and the Nyquist frequency is 442 Hz. Ticks are uniform to 1127-1137 us, with a 1337-1341 us tail (p99). There are 5 gaps over 1.5 ms (max 9.76 ms, at 330.3/369.7/370.0/411.0/411.4 s) and none inside the analysis windows except 2 each in CL1.5 and CL2.0. The older ML/YP/TP logs also show 1127-1133 us. `logSampleTick()` gates at `POWER_BAL_PERIOD_US` 1000 us, which a 1131 us loop always passes, so the BLG holds every loop iteration. The telemetry gate is `millis()-lastSend > 20` (`teensy_controller.ino:6811`). On this loop the emulated snapshot spacing is 21.16 ms (47.26 Hz). The bags' 47.62 Hz implies a loop of 1.0 ms or less in Run without SD logging. TODO(verify): the State-2 loop period.
- **No BLG has the H-20 on the FC input.** The H-20 first ran on 2026-09-15 with no SD log (`boost-bringup-debug.md:1482-1489`). The last earlier BLG is SY0001 (2026-08-31), and ML0226/ML0227 used a bench supply. Purge interaction therefore cannot be studied at 1 kHz.
- **Single-source and dual-source runs** come from the same sessions (fw 16-19, `T` 6 A trapezoid, 2.3 s flat-tops while accelerating): BT-only TP0170/0171/0199/0205, FC-input-only TP0176/0177/0202/0210, and dual TP0172/0174/0200/0208. In August the FC input source held about 8.3-8.6 V. It cannot be the H-20 (the logs predate 09-15); TODO(verify: boost-bringup-debug.md, Aug entries) for its type. TP0201 is the handoff-sag log and is excluded.
- **No no-VESC control exists.** BLG carries no switch_state, and every standstill span sits after `G` with MOT_PWR up. The ML0226 I_cmd 0 spans are the closest available control.

### 2. V_bus 0-442 Hz (ML0226; Welch with 2048-4096 points, detrended)
| Segment | 0.5-24 | 24-100 | 100-250 | 250-442 Hz | total (mV rms) | floor (uV/rtHz) |
|---|---|---|---|---|---|---|
| standstill (x2) | 0.54-0.57 | 0.87-0.96 | 1.21-1.30 | 1.40-1.50 | 2.17-2.28 | 94-97 |
| OL3.0 / OL3.4 | 0.88 / 0.62 | 1.04 / 0.96 | 1.44 / 1.32 | 1.60 / 1.47 | 2.55 / 2.30 | 113 / 103 |
| OL3.8 / OL4.2 | 0.73 / 0.76 | 1.29 / 1.61 | 1.76 / 1.98 | 2.08 / 3.90 | 3.12 / 4.74 | 140 / 157 |
| CL0.5 / CL1.0 | 0.82 / 1.33 | 1.04 / 1.44 | 1.41 / 1.47 | 1.58 / 2.15 | 2.51 / 3.29 | 112 / 121 |
| CL1.5 / CL2.0 | 3.01 / 3.74 | 1.63 / 6.07 | 2.11 / 3.53 | 4.73 / 2.37 | 6.27 / 8.31 | 168 / 149 |

**The white floor is the ADC chain, not the bus.** At standstill V_bus carries 0.44-0.46 LSB rms over 50-442 Hz. The quiet V_rgn channel (13.5 V, same ADC) carries 0.49-0.50 LSB, and I_fc/I_batt near zero carry 0.42-0.49 LSB. For reference, 1-LSB quantization is 0.27 LSB, or 62 uV/rtHz at 4.545 mV/LSB (`SCALE_V_BUS`, :2028). With the motor running, broadband regions away from the lines rise only to 0.51 LSB (OL3.0). Aliased boost switching ripple on V_bus is therefore at most sqrt(0.51^2-0.44^2) = 0.26 LSB (1.2 mV). By contrast, V_fc carries 5-24 LSB (16-72 mV rms): the boost input ripple at the bench-supply terminal aliases strongly there.

**Lines (all scale with speed):**
- 1x flywheel: 0.46/1.07/2.78/3.47 mV at 0.5/1.0/1.5/2.0 m/s.
- Motor mechanical 1x, at 33.4 Hz per m/s (16.0 x f_rot; phi 6.86 x tire 2.31 = 15.84, so 1 % off): 0.14-0.69 mV.
- **1x electrical** (2 pole pairs), at 66.9 Hz per m/s: 0.51/1.06/2.08 mV.
- **6x electrical** (commutation/torque-ripple order), at 401 Hz per m/s. It appears at 399-405 Hz at 1.0 m/s (0.7 mV per peak). At 1.5 m/s it folds from 602 to 282 Hz (2.64 mV). At 2.0 m/s it folds from 802 to 82 Hz, where it coincides with an unidentified 41.3 Hz per m/s order (19.8 x f_rot; possibly 3x the spur-gear rate, UNVERIFIED). That 82 Hz peak is the largest V_bus line in the log, at 3.98 mV.
- OL4.2's 320-380 Hz hump is the same 6x line, smeared by the speed drift from 1.29 to 1.40 m/s.

**Single versus dual source (TP logs).** Over 24-440 Hz, V_bus is 2.8-3.2 / 6.4-9.3 / 3.4-8.9 mV single-source against 1.7-1.8 / 3.2-5.3 / 3.2-4.5 mV dual-source, with coherence against I_tot of 0.66-0.83 (single) and 0.48-0.74 (dual). Dual-source operation roughly halves the HF bus ripple, in line with the 159 versus ~70 mOhm low-frequency Z (Figure psd, lower panel).

### 3. Coherence and Z(f)
- On the drive lines, V_bus is coherent with I_tot at 0.98-1.00, with I_fc and I_batt separately at 0.99, and with I_cmd at only 0.01-0.05 above 24 Hz (the VESC regulates phase current). The HF lines are real bus current.
- Away from the lines, coherence sits at the estimator bias (OL3.0: 0.03-0.04 against a 0.03 bias), so that content is independent measurement noise.
- At the lines, |Z| = |-dV_bus/dI_tot| is:
  - CL1.0: 52 mOhm (1x), 46 (mech), 52 (elec) and 81 mOhm (401 Hz true).
  - CL1.5: 85 / 89 / 98 mOhm, and 128 mOhm at 602 Hz true.
  - CL2.0: 81 / 85 / 84 mOhm, and 133 mOhm at 802 Hz true.
- Z is therefore flat within ±20 % from 2 to 134 Hz and about 1.5x higher at 400-800 Hz. The rise could be ~20 uH-equivalent wiring or the droop-path bandwidth; this is unresolved.
- **Skew.** The phase of Z grows linearly: +10 deg at 66.9 Hz and +19..+25 deg at 100-134 Hz. That gives V_bus lagging I_tot by 415-520 us, which is 4 read slots of about 125 us each, not the 78 us previously estimated. TODO(verify): stamp micros() around updateSensors(). 7 x 125 us = 0.88 ms of the 1.131 ms loop. I_fc to I_batt is one slot, or 0.9 deg at 20 Hz, which is negligible for the share's 6-24 Hz floor.

### 4. Fold test (21 ms millis()-gate snapshot emulated on the 884 Hz data)
V_bus over 0.5-23.8 Hz (mV), given as true / snapshot / 21 ms boxcar-then-decimate:

| Segment | true | snapshot | boxcar |
|---|---|---|---|
| standstill | 0.56-0.58 | 2.31-2.48 | 0.54 |
| OL3.0 | 0.84 | 2.42 | 0.83 |
| OL4.2 | 0.72 | 4.65 | 0.77 |
| CL0.5 | 0.76 | 2.47 | 0.81 |
| CL1.0 | 1.36 | 3.15 | 1.33 |
| CL1.5 | 3.03 | 5.77 | 2.96 |
| CL2.0 | 3.76 | 8.04 | 3.80 |

- **72-98 % of the snapshot variance is fold** (94-95 % at standstill, 78 % at CL2.0).
- Per band at CL1.0-CL2.0, the snapshot gives 1.45-3.88 / 1.42-3.67 / 2.19-5.89 mV (2-6 / 6-12 / 12-23.8 Hz) against true 0.85-3.57 / 0.42-0.74 / 0.44-0.94 mV. The 6-24 Hz snapshot content is 3-8x the real content.
- The bag figures (standstill 2.9-3.4 mV; fw v37 cruise 5.4/5.5/8.1 mV) are 1.2-1.5x these emulations at heavier vehicle currents. Their rising-with-frequency shape (12-23.8 Hz largest) is the folded white floor plus the folded drive lines.
- The boxcar removes the fold almost completely and leaves the 1x content intact.

### 5. The same test for currents and share
- Over 0.5-23.8 Hz, the snapshot fold share is 52-98 % for I_fc, I_batt and I_tot. For example, I_tot at CL2.0 is 45.6 mA true against 82.9 mA snapshot.
- **The share over 6-23.8 Hz is 0.0037-0.0159 true against 0.0160-0.0465 snapshot** (fold 84-95 % of the 0.5-23.8 Hz variance; CL0.5 63 %).
- The bags' flat ~0.012 share floor is therefore mostly folded content above 23.8 Hz: the white ADC floor (about 2.5 mA per channel) plus the drive lines. Inter-channel skew is ruled out (0.9 deg at 20 Hz).

### 6. Light load and the ideal diodes
- **No light-load dropout.** With a 101-tick median I_fc of 0.03-0.16 A (121,284 moving ticks), I_fc never reads 0. Deviations are Gaussian (kurtosis 2.9-3.2) at 9.3/17.1/19.3 mA rms, growing about in proportion to I_fc, which matches real drive-line ripple.
- Isolated zero readings in TP0172/TP0206 (1.7-2.1 % in the 0.08-0.12 A bin) fall on the trapezoid share transitions, not on a limit cycle.
- **No chatter signature.** I_fc and I_batt are 0.99 coherent at every line. A chattering switch would add uncorrelated per-channel spikes.
- **RT1987 expectations** (RT1987_DS-00):
  - p.16 (Section 17.6): the servo regulates VIN-VOUT = VFWD while IOUT x RON < VFWD.
  - p.7: VFWD is 35 mV typ and RON is 20 mOhm typ; neither has a min/max.
  - Hence the regulated regime holds below about 1.75 A, which covers every rig current.
  - Within the servo bandwidth, the incremental resistance is about 0. The HIL model's 35 mV + i*R_on adds 20 mOhm per channel, or about 10 mOhm to the parallel Z, which is 12-20 % of the measured 52-98 mOhm. The servo bandwidth is not in the datasheet: TODO(verify: RT1987_DS-00).
  - The flat 2-134 Hz Z shows no in-band ideal-diode element. Isolating it needs a scope across VIN/VOUT of D-FC/D-BT.
- **TPS61288 PFM boundary, re-derived.**
  - p.12 Section 8.4.2: off-time extension (PFM) begins as the peak current falls to 2.6 A typ, and the peak is clamped at 1.3 A.
  - p.6: f_sw is 500 kHz. The BOM gives L-FC/L-BT = 2.2 uH.
  - Single-pulse DCM delivery is P = 0.5*L*Ipk^2*f*Vout/(Vout-Vin) = 3.72 W x 16/(16-Vin). The boundary is therefore 0.74 A at FC 11 V, 0.50 A at 8.5 V, 0.93 A at 12 V, and 0.45 A at BT 7.7 V.
  - At the rig medians, FC (0.15 A) runs deep in PFM (about 100 kHz) and BT (0.5 A) runs near the boundary.
  - The PFM ripple frequency is far above 442 Hz, and on V_bus it is bounded at 1.2 mV or less (Section 2). Confidence: moderate.

Figures: vbus_blg1k_psd.png (V_bus ASD by condition; single versus dual source), vbus_blg1k_fold.png (true / snapshot / boxcar).

## Adversarial verification (data and physics lenses)

- [C1] In ML0226, 72-98 % of the 21 ms snapshot V_bus variance in 0.5-23.8 Hz is folded content from above 23.8 Hz; at standstill the snapshot reads 2.31-2.48 mV rms against 0.56-0.58 mV true and 0.54 mV after a 21 ms boxcar.
   data: CONFIRMED -- In ML0226, 73-97 % of the 21 ms snapshot V_bus variance in 0.5-23.8 Hz is content folded down from above 23.8 Hz. This holds across 15 constant-command windows: 89-97 % in the open-loop and idle windows, and 73-81 % in the 1.0-2.0 m/s closed-loop holds, where the real low-frequency content is 1.4-3.8 mV. In the I_cmd = 0 windows the snapshot reads 2.0-2.6 mV rms. The true in-band value is 0.47-0.60 mV, and a 19-sample (21 ms) boxcar reads 0.47-0.55 mV, which matches the true value to within 0.02 mV. The exact standstill ranges depend on how the windows are chosen; three of the five windows are
   physics: PARTLY -- In ML0226 (875 Hz BLG series, 422 s), 76-98 % of the 21 ms snapshot V_bus variance in 0.5-23.8 Hz on steady holds is folded content from above 23.8 Hz. The value is 94-96 % at standstill and 76-80 % in the 1.5-2.0 m/s closed-loop holds. At standstill the snapshot reads 2.26-2.37 mV rms. The 875 Hz series gives 0.49-0.55 mV in-band, and a 19-sample (21 ms) boxcar gives 0.48-0.54 mV.

The 875 Hz in-band figure is not the true V_bus content. The 875 Hz series is white at standstill (2.21 mV full-band ≈ the snapshot rms), and white noise predicts 0.51 mV in-band. So 0.5 mV is a per-sample ADC and 
- [C2] The standstill V_bus HF floor (0.44-0.46 LSB rms over 50-442 Hz, 94-97 uV/rtHz) equals the ADC-common floor of the quiet V_rgn channel (0.49-0.50 LSB), so it is measurement-chain noise and not bus switching ripple; aliased boost ripple on V_bus is bounded at 1.2 mV or less.
   data: CONFIRMED -- In ML0226 at standstill, the V_bus floor over 50-442 Hz is 0.44-0.47 LSB rms (2.0-2.1 mV, about 100-106 uV/rtHz). The effective fs is about 884 Hz, not 1 kHz. This floor matches the floors of V_rgn (0.48-0.50 LSB), I_fc (0.43-0.48) and I_batt (0.39-0.47), which are mutually uncorrelated (|r| < 0.04). It is therefore per-conversion ADC noise, not bus switching ripple. Aliased boost ripple in the 50-442 Hz band is at most about 1.2 mV rms at standstill. Below-50 Hz and DC aliases are not bounded by this test. Under load the V_bus floor rises to 1.0-1.6 LSB, above the ADC floor.
   physics: PARTLY -- At standstill (ML0226, fw v37, fs 884 Hz), V_bus over 50-442 Hz is 0.44-0.47 LSB = 2.0-2.1 mV rms (100-107 uV/rtHz). That is the same count-domain level as every other quiet ADC channel (V_rgn 0.49-0.50, I_fc/I_batt 0.42-0.49 LSB). It is incoherent with V_rgn (median coherence 0.045, about the bias level). V_rgn sits on a bus-level node, so a physical bus ripple would appear on it coherently and with about 1.8x more counts on V_bus. The standstill floor is therefore measurement-chain noise and not bus ripple. Aliased boost ripple at standstill is bounded at 2.1 mV rms with no subtraction, or a
- [C3] The V_bus content above 24 Hz under load is real bus current at drive orders, namely 1x electrical at 66.9 Hz per m/s and 6x electrical at 401 Hz per m/s (aliased at fs 884 Hz to 282 Hz at 1.5 m/s and 82 Hz at 2.0 m/s, up to 3.98 mV), with coherence 0.98-1.00 against I_tot and |Z| 52-133 mOhm.
   data: PARTLY -- On ML0226 CL1.0 / CL1.5 / CL2.0, the V_bus content above 24 Hz is dominated by two drive-order lines that are coherent with I_tot (coherence 0.97-1.00). The 1x line is at 66.2 Hz per m/s (66.2 / 99.3 / 132.2 Hz). The 6x line is at 397 Hz per m/s, and the mean record rate of about 875 Hz (not the 884 Hz median, because of logging gaps) aliases it to about 397 Hz, 279 Hz and 81 Hz at 1.0, 1.5 and 2.0 m/s. The 6x line amplitude rises with speed: band rms 1.3 / 3.8 / 5.5 mV (single-bin 0.55 / 2.1 / 3.1 mV), with 15-42 mA rms of current. The V/I ratio is 42-98 mOhm at 1x and 78-121 mOhm at 6x, but 
   physics: PARTLY -- In ML0226 closed-loop holds, the strongest V_bus content above 24 Hz under load is real bus current at 6x electrical (6 x 66.9 Hz per m/s). It shows up at 401 Hz at 1.0 m/s, and at 1.5 and 2.0 m/s it aliases to about 279 Hz and 81 Hz. That aliasing follows the dominant 1130-us BLG record interval (about 883 Hz); the index-based rate is about 875 Hz. The line reaches about 1.5, 3.9 and 5.6 mV rms over a ±10 Hz cluster (peak bin up to 3.1 mV), with coherence 0.97-1.00 against I_fc+I_batt and |Z| 78-142 mOhm, and it carries 24-56 % of the V_bus power above 24 Hz. The 1x-electrical line (66.9 Hz p
- [C4] The firmware loop and BLG sample at 884 Hz (median tick 1131 us), not 1 kHz, and V_bus lags I_tot by 415-520 us (about 4 read slots of roughly 125 us), not by 4 x 78 us.
   data: PARTLY -- The firmware loop is free-running, with no 1 kHz gate in loop() at teensy_controller.ino:6768, and the BLG logs every pass. The median tick is 1127-1133 us (about 884 Hz) in ML0203/ML0225/ML0226/YP0214, and the mean rate is 867-877 Hz because of occasional 1.34-1.37 ms ticks. In cruise windows, the coherent in-band lines (80-137 Hz) show V_bus phase-lagging I_tot by +17 to +32 deg, which is 490-690 us if read as a pure delay. That is consistent with V_bus being sampled 3-4 analogRead slots after the current reads, each slot at most about 160 us. However, single-frequency phase cannot separate 
   physics: PARTLY -- The BLG records once per free-running loop iteration because the 1000 us rate limiter (POWER_BAL_PERIOD_US, rateLimitDue :3751) is slower than the loop. The median record interval is 1131 us (884 Hz) and the mean is about 1142-1153 us (867-875 Hz). The intervals are bimodal at 1128 and 1332 us, so the BLG is neither 1 kHz nor uniformly sampled. The V_bus read (slot 5) follows I_fc (slot 1) by 4 ADC reads and I_batt (slot 2) by 3. The Z phase is consistent with an effective skew of roughly 0.4-0.5 ms at 130 Hz and in the aliased 280-400 Hz lines. However, the implied delay is not constant acros
- [C5] The I_fc minority floor shows no light-load dropout or limit cycle: with a median I_fc of 0.03-0.16 A, ML0226 has 0 zero readings in 121,284 moving ticks and Gaussian deviations (kurtosis 2.9-3.2).
   data: PARTLY -- In ML0226 (FC input = bench supply at about 11.06 V, not the H-20), the I_fc minority floor shows no dropout to zero. Of the 121,284 gated ticks (I_cmd > 2.5 A, I_batt >= 5 counts, 101-tick median of 0.03-0.16 A), none reads 0 counts; the minimum is 2 counts (16 mA). The deviations from the median are not uniformly Gaussian. The pooled Pearson kurtosis is 4.0, and the dominant 0.06-0.10 A bin (62 % of the ticks) reads 4.5, with 4.8 at 0.07-0.09 A. Only the edge bins (0.03-0.06 A and 0.10-0.16 A) read 2.4-3.4. A limit cycle is not excluded by this test.
   physics: PARTLY -- In ML0226 (fw v37), the 121,284 moving ticks with a median I_fc of 0.03-0.16 A (4-19 counts at 8.06 mA) have 0 zero readings, and the minimum is 2 counts. This rules out full I_fc dropouts at the 1 kHz sample level. The deviations are near-Gaussian only in the populated bins at median 5-9 counts (kurtosis 2.8-3.3). Pooled kurtosis is 4.0, and the bins at median 10-11 counts read 4.9-5.5. The test cannot exclude a PFM or limit cycle faster than the 16x-averaged sample, or slower than about 10 Hz (it is hidden by the 101-tick median).
- [C6] Over 6-23.8 Hz the true power share is 0.0037-0.0159 rms while the 21 ms snapshot gives 0.0160-0.0465, so the bags' flat ~0.012 share floor is mostly fold, not inter-channel skew (0.9 deg at 20 Hz).
   