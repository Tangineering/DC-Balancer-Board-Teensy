## V_bus residual in the Pi bags (label: bagtest)

**Answer.** Of all the variables tested, **vehicle speed (and the load that comes with it) is the only one that moves the V_bus residual by a large amount**. In fw v37, the residual above about 5 Hz grows from 3.1 mV rms below 0.5 m/s, which is the standstill floor, to 13.5 mV rms at 2.5-3.5 m/s. That is 4.4x. At a fixed speed band, I_tot moves it only 1.2-1.3x.

Once speed and I_tot are held constant, the other variables have almost no effect:
- I_fc, including the 0.10/0.12 A handoff band: the residual stays within 0.94-1.08x.
- I_batt, across the estimated BT PFM boundary at about 0.44 A: 0.95-1.06x, with no step at the boundary.
- power_share_cmd rail versus in-band: 0.95-1.02x.
- Time since the last H-20 purge: 0.92-1.04x.
- Switch state at standstill (0x26 versus 0x27): no measurable change.

The residual is broadband (white), near-Gaussian and mostly independent of the 50 Hz current samples. It co-moves with V_rgn, which is the motor-side node read about 0.16 ms later. My best reading is that it is real bus/motor-node ripple **above Nyquist (> 24 Hz, likely far above)**, driven by the motor operating point, and that the 1 kHz snapshot aliases it into the band. The RT1987 light-load and boost-PFM hypotheses are not supported at this resolution. Confidence: medium. The 50 Hz data cannot see the above-Nyquist source directly.

### Data and method
- **Bags (de-duplicated to 47.62 Hz; max gap 21-22 ms):** 10-30 (fw v35), 11-05 (fw v37 rev 2) and 10-26 (battery only, 0x26). Firmware is bound by date only (trap 3).
- **Moving mask:** switch 0x27 (0x26 for 10-26), v > 0.05 or v > 0.3 m/s, fault_flags = 0, purges excluded (+/-0.5 s).
- **Standstill mask:** v < 0.05, v_setpoint = 0. The 0x27 standstill sets have only 1115 (v35) and 330 (v37) ticks.
- **Residual:** V_bus = poly2(t) + Z*I_tot, fitted by OLS in each contiguous chunk of up to 192 ticks. The "hp" figures subtract a 9-tick moving mean, which keeps content above about 5 Hz.
- **Quantization:** V_bus LSB = 3.3*56.4/10/4095 = **4.545 mV** (`SCALE_V_BUS`, teensy_controller.ino:2028, ADC_MAX 4095 :2020). The raw values are exact integer counts.
- Scripts are in scratchpad/vbus/bagtest (lib.py, a1-a6.py, fig.py).

### 1. Residual size and distribution

| Run | Band (Hz) | Moving residual (mV) | Standstill 0x26 floor (mV) |
|---|---|---|---|
| v35 | 2-6 / 6-12 / 12-23.8 | 6.7 / 6.5 / 8.2 | 1.27 / 1.67 / 2.26 |
| v37 | 2-6 / 6-12 / 12-23.8 | 5.1 / 5.5 / 7.6 | 1.09 / 1.43 / 1.94 |
| battery only | 2-6 / 6-12 / 12-23.8 | 6.8 / 10.2 / 11.6 | 1.96 / 2.30 / 3.25 |

(Moving = clean cruise: v > 0.3, I_tot > 0.3, command steps excluded.)

- **Both levels are spectrally flat.** v37 moving is about 5-6.5 mV^2/Hz in every band, and the floor is about 0.3 mV^2/Hz (figure panel c).
- **The moving residual is about 15x the floor in power.** 93-94 % of the moving 2-24 Hz variance lies above the standstill floor in all three bags (v37: 10.7 mV total against a 2.65 mV floor).
- **Distribution, dual-source moving:** kurtosis -0.2 to -0.5; 0.1-0.2 % of ticks beyond 3 sigma; none beyond 4 sigma. This is not impulsive. It is slightly sub-Gaussian; in v35 the cause is a 1x residual tone at 4.1-4.6 Hz, 20-30x the periodogram floor.
- **Distribution, battery-only moving:** kurtosis +1.2 (hp +1.6) and 0.2 % of ticks beyond 4 sigma. These heavier tails sit in the I_batt 1-2 A bin, where the residual is 24 mV.
- **LSB structure:** the moving residual is 2.4-3.4 LSB rms, so quantization (LSB/sqrt12 = 1.31 mV) is negligible. At standstill, the first-difference std is 0.93-1.07 LSB, which is consistent with white noise of 0.66-0.76 LSB (3.0-3.4 mV).
- **The floors are not one value.** The 10-26 standstill floor is 4.7-4.9 mV against 2.8-3.35 mV in the other two bags, at the same switch state 0x26 and about 24 mA. The cause is unresolved.

### 2. Dependence tests (v37; v35 in brackets)

Raw hp-residual rms by bin. Counts are in the tables printed by a2.py.
- **v_actual** (bins 0.05-0.5 / 0.5-1 / 1-1.5 / 1.5-2 / 2-2.5 / 2.5-3.5 m/s): 3.1 / 5.5 / 6.5 / 9.0 / 10.5 / 13.5 mV (5.0 / 8.1 / 9.1 / 11.0 / 12.6 / 14.2). n = 56 (68) in the lowest bin and 1332 (1336) in the highest.
- **I_tot** (bins < 0.3 to 0.9-1.2 A): 5.4 to 13.3 mV (7.9 to 14.0).

Speed x I_tot cells, I_tot 0.5-0.8 A then 0.8-2.5 A:

| v band | v37 (mV) | v35 (mV) | battery only (mV) |
|---|---|---|---|
| 1.2-2 m/s | 9.1 / 9.4 | 10.6 / 10.0 | 11.8 / 13.3 |
| 2-3.5 m/s | 10.7 / 13.2 | 13.0 / 14.2 | 14.7 / 17.1 |

At matched speed and load, the battery-only bag reads 1.2-1.3x the dual-source bags. Its DC impedance ratio is larger, at 2.2-2.6x.

Normalized by the cell mean of each (0.25 m/s x 0.1 A) cell:
- I_fc: below 0.1 A 0.83 (0.93), n = 288 (456); 0.10-0.12 A 0.99 (0.94); 0.12-0.15 A 1.05 (1.00); all other bins 0.96-1.08.
- I_batt: 0.3-0.4 A 0.95 (1.06), 0.4-0.5 A 0.99 (0.98), 0.5-0.6 A 1.04 (1.04).
- Command: 0.16 rail 1.01 (1.02); 0.84 rail 0.96 (0.95).
- Time since purge: 0-1 s 0.92 (0.97); 1-11 s 0.95-1.04.

A hidden I_fc-, purge- or PFM-linked term is therefore bounded at about +/-16 % of the variance, which is roughly 4 mV rms.

**RT1987 at near-zero load:** the standstill floor at 0x27 (FC_BUS on, I_fc = 0) is 3.33 mV against 3.35 mV at 0x26 for v35, and 3.28 mV against 2.91 mV for v37 (330 ticks).

**Extra regressors** do little. Adding I_fc/I_batt split, I_tot lags from -2 to +1 tick, the droop gains g_FC/g_BT and the products g*I removes 20.5 % (29 %) of the residual variance, mostly at 2-6 Hz. The 12-24 Hz band falls only from 7.27 to 6.48 mV (7.76 to 7.00 mV).

### 3. Cross-channel tests (hp residuals, same tick)

**Standstill.** Every inter-channel correlation is |r| <= 0.05 except two:
- V_chg/V_rgn at -0.27. They are adjacent reads, and V_chg sits at 0 V; I read this as charge carry-over in the ADC sample capacitor (inferred).
- V_bus/V_rgn at 0.16, in the battery-only bag.

The per-volt noise also differs by channel: V_bus 176-292 ppm/V, V_batt 800-1150 ppm/V, V_rgn 470-620 ppm/V. A common ADC-reference term would give equal ppm/V and r near 1 on every channel. **It is rejected as the source of the floor and of the moving residual.**

**Moving.**
- The residual correlates with **V_rgn: r = 0.38 (v37), 0.48 (v35), 0.47 (battery only)**. Adding V_rgn as a regressor removes 16 %, 28 % and 49.5 % of the residual variance respectively.
- Its correlation with V_fc and V_batt is only 0.09-0.14.
- Its correlation with the I_fc and I_batt hp residuals is between -0.05 and +0.09.
- The hp magnitudes of V and I_tot rise together with speed. The ratio runs from 187 down to 132 mΩ (v37) and from 120 down to 74 mΩ (v35), but the two are uncorrelated tick by tick.
- One-tick lag correlations are -0.15 to -0.20, and the sign differs between bags: Itot(t-1) for v35, Itot(t+1) for v37 and battery only. I read this as droop-dynamics leftovers, not a fixed skew.

**Droop gains.** In moving windows the gains change on 97-98 % of ticks (10-90 % range 0.19-0.96). As regressors they explain 2-8 % of the residual.

### 4. Tone search in steady holds (v std <= 0.06 m/s, about 220 ticks each)

- **v35:** the dominant residual peak sits on 1x f_rot (4.11-4.57 Hz) at 1.9-2.3 m/s.
- **v37:** the 1x is gone and the peaks are scattered (3.5-23 Hz, 4-12x the median bin). There is no repeatable alias of a motor-mechanical harmonic, assuming f_mech = 33.1 Hz per m/s from phi 6.86 and r_t 0.033 m in calibration/motor_id_20260815.md (`TODO(verify)` for the rig).
- **Battery only, one hold at 4.17 m/s:** a 10.6 Hz line at 69x. This would be consistent with a 2x f_mech alias (9.9 Hz +/- 2.8 Hz for a 1 % phi error). It is low confidence: a single hold.

### 5. Ranking of the hypotheses
1. **(c)+(f), most likely: motor/VESC-driven bus ripple above Nyquist, aliased by the 1-in-21 snapshot of 1 kHz samples.** Evidence for: the residual scales with speed and current, is white, is above the floor by 15x in power, co-moves with V_rgn (a physical node, not the ADC), and is larger with the single source. Evidence against: no repeatable aliased tone at the motor harmonics; the source frequency is not identified.
2. **(e) Read skew combined with (c).** V_bus is the 5th read, about 0.3 ms after I_fc (each read is roughly 78 us, `TODO(verify: Teensy ADC clock)`). Above about 1 kHz this skew decorrelates real ripple, which would explain why the I_tot and V hp magnitudes co-scale but do not correlate. This is untested with 50 Hz data.
3. **(a) ADC floor: real but small.** It is 2.8-3.35 mV (4.7-4.9 mV in the 10-26 bag), which is 6 % of the moving variance, with no common-reference term.
4. **(b) Aliased boost switching / PFM: weak.** By my re-derivation from DS SLVSFP3C §8.4.2 p.11-12 (off-time extension below a 2.6 A typ peak), the BOM's L = 2.2 uH (BOM line 9) and f_sw = 500 kHz (DS p.6, line 335 of the text dump), PFM onset is at about **0.64 A (FC, Vin 10.2 V)** and **0.44 A (BT, Vin 7.6 V)** of output current. That puts the FC boost in PFM at all times on this rig. No step appears at I_batt 0.44 A, and the 16-sample ADC average attenuates 500 kHz unless the sampling is coherent with it.
5. **(d) RT1987 light-load servo: not supported.** There is no I_fc, handoff, purge or 0x26/0x27 dependence (all within +/-8 %), with a hidden-term bound of about 4 mV rms. The 50 Hz data cannot exclude a servo oscillation that is independent of current.

### Unverified
- The ADC conversion time per read.
- The motor gear and electrical frequency for the rig.
- The VESC switching frequency.
- Whether an anti-alias capacitor is fitted on the V_bus divider (`TODO(verify: schematic)`).
- The cause of the higher floor in the 10-26 bag.
- The schematic, the RT1987 datasheet and the 1 kHz BLG logs were not read for this item.

Figure: docs/reviews/noise_fw37_2026-11-05/figs/vbus_bagtest_residual_dependence.png. It has three panels: (a) residual versus speed with the standstill floors, (b) the normalized dependence on I_fc and I_batt, and (c) the residual PSD moving versus standstill.

## Adversarial verification (data and physics lenses)

- [C1] Speed is the dominant driver of the fw v37 V_bus residual above ~5 Hz: 3.1 mV rms at v<0.5 m/s (n=56) rising to 13.5 mV at 2.5-3.5 m/s (n=1332), 4.4x, while I_tot at fixed speed moves it only 1.2-1.3x.
   data: CONFIRMED -- Speed is the dominant driver of the fw v37 V_bus residual above about 5 Hz. The residual is 3.1 mV rms at v < 0.5 m/s (n of about 60-80) and rises to 13.4 mV at 2.5-3.5 m/s (n of about 1300), a ratio of about 4.3x. At a fixed speed, I_tot terciles move it only 1.0-1.4x. The result holds with a raw first-difference estimator (3.0 to 14.0 mV) and with a 5 Hz Butterworth high-pass (2.5 to 12.3 mV). fw v35 shows the same trend (4.8 to 14.2 mV). Battery-only also shows it: 5.3 mV, rising to 18.2 mV at 2.5-3.5 m/s and 33.6 mV at 3.5-6 m/s; the 24.5 mV figure does not reproduce in the 2.5-3.5 m/s bin
   physics: CONFIRMED -- In fw v37 0x27 cruise, the high-passed (above about 5 Hz) V_bus residual rises steadily with speed. The bins are 3.1 mV at v<0.5 m/s (n=56, about 1.2 s), 5.5 mV at 0.5-1 m/s (n=116) and 13.5 mV at 2.5-3.5 m/s (n=1308). That is about 2.5x on well-populated bins and 4.4x if the thin lowest bin is included. Most of the rise is broadband in 8-23.8 Hz, not the 1x line.

At fixed speed, mean I_tot moves the residual by 1.1-1.4x. High-pass current ripple adds nothing once speed is in the fit (coefficient about 0). The residual has no sample-level correlation with I_tot (|r| <= 0.14). The Z*I_tot term
- [C2] After controlling for speed and I_tot, I_fc (including 0.10-0.12 A), I_batt across the ~0.44 A BT PFM onset, power_share_cmd and time since purge each change the residual rms by at most 0.92-1.08x (one bin, v37 I_fc<0.1 A, reads 0.83x), so no RT1987 light-load or PFM signature is visible.
   data: CONFIRMED -- After controlling for speed and I_tot, the >5 Hz V_bus residual rms changes by no more than about 0.92-1.08x across bins of I_fc (including 0.10-0.12 A), I_batt (across the ~0.44 A BT PFM onset), power_share_cmd and time since purge. There are two exceptions. v37 I_fc < 0.1 A reads 0.81-0.83x, which is significant and lower. v35 I_fc 0.2-0.3 A reads up to 1.19x on n=44, which is marginal. The test resolves about +/-10 % with only ~10 independent segments per bag, it does not cover 2-6 Hz, and cmd is barely sampled off the rails. No current-dependent RT1987 or PFM signature is visible at that r
   physics: PARTLY -- The fw v35 and v37 bags were controlled for speed and I_tot (0.25 m/s x 0.1 A cells, residual high-passed to about 5-24 Hz). After that, binning by I_fc, I_batt, power_share_cmd or time since purge changes the V_bus residual rms by only 0.92-1.08x, with one v37 bin at I_fc below 0.1 A reading 0.83x. The battery-only bag's I_batt bins are tautological at 1.000. This is a null for any EXTRA level dependence. It does not test for RT1987 or PFM signatures. The RT1987 is in its regulated-V_FWD regime (about 35 mV) at every rig current (RT1987_DS-00 p.7, p.16). The TPS61288 datasheet gives no numeri
- [C3] In every bag, 93-94 % of the moving 2-24 Hz V_bus residual variance lies above the standstill floor (v37: 10.7 mV vs 2.65 mV), and both spectra are flat (about 5-6.5 vs 0.3 mV^2/Hz).
   data: PARTLY -- In every bag, 93-95 % of the moving V_bus residual variance in the 2-23.8 Hz band, after the I_tot regression, lies above the battery-only standstill floor. Each band separately is 0.92-0.97. The estimates were v37 10.7 vs 2.6 mV, v35 12.3 vs 3.0 mV and battery-only 16.9 vs 4.4 mV, and they are robust to the estimator, detrend, run length and de-dup. Only in fw v37 are both spectra roughly flat (moving 4.8-6.5 vs floor about 0.3 mV^2/Hz). In fw v35 the moving residual still falls by 1.8x from 2-6 to 12-24 Hz (10.4 to 5.9 mV^2/Hz; floor 0.4). In the battery-only bag it peaks at 6-12 Hz (16.7 mV
   physics: PARTLY -- In every bag, 93-94 % of the moving 2-23.8 Hz V_bus residual variance lies above the 0x26 standstill floor:
- v35: 12.9 vs 3.2 mV.
- v37: 11.2 vs 2.7 mV.
- Battery only: 17.6 vs 4.6 mV.

Per band the fraction is 92-96 %. Only the v37 moving spectrum is roughly flat, at about 6 mV^2/Hz (range 3.7-9.8) against a standstill level of about 0.36 mV^2/Hz. The other two moving spectra have peaks:
- v35: a 4.5 Hz (once-per-rev band) peak of 21.7 mV^2/Hz on a 5-9 baseline.
- Battery only: a 10-12 Hz peak of 29 mV^2/Hz on a 10-14 baseline.

The standstill floors (0.36-1.0 mV^2/Hz) are 5-14x the white qu
- [C4] There is no common ADC-reference noise: at standstill every inter-channel hp-residual correlation is |r|<=0.05 (except the adjacent-read V_chg/V_rgn at -0.27) and the per-volt noise differs by channel (V_bus 176-292 ppm/V, V_batt 800-1150, V_rgn 470-620), whereas when moving the residual correlates with V_rgn at r=0.38-0.48.
   data: PARTLY -- At standstill there is no common ADC-reference noise: no pair of channels correlates broadly. Most inter-channel hp-residual correlations are |r| <= 0.06, but three pairs fall outside that:
- V_chg/V_rgn is -0.27 in v37; they are adjacent reads, and V_chg sits at about 0 V.
- V_bus/V_chg is +0.13 to +0.15 in v37.
- V_bus/V_rgn is +0.16 in the battery-only bag. That is consistent with V_rgn seeing the V-MOT node, which is connected to the bus through MOT_PWR (not verified on the schematic).

The per-volt noise differs by channel:
- V_bus: 175-291 ppm/V
- V_batt: 804-1145 ppm/V
- V_rgn: 466-668 
   physics: PARTLY -- No common ADC-reference noise is evident. At standstill the per-volt hp-residual noise differs by channel: V_bus 179-292 ppm/V (0.6-1.0 LSB of 4.55 mV), V_batt 810-1110 ppm/V, V_rgn 460-630 ppm/V. Inter-channel |r| is <=0.05 on fw v35 but up to 0.15-0.16 on the v37 and battery-only bags. The V_chg/V_rgn -0.28 appears only in the v37 bag (-0.01 elsewhere), so it is not a general adjacent-read artefact. When moving, the V_bus residual correlates with V_rgn at r = 0.53-0.85 (not 0.38-0.48), and with I_batt at -0.38 to -0.83. That is physical coupling through the bus and V-MOT node via the closed 
- [C5] Lagged I_tot (-2..+1 tick), a separate I_fc/I_batt split, and the droop gains with their products with current together remove only 20.5 % (v37) / 29 % (v35) of the residual variance; the 12-24 Hz band falls only from 7.27 to 6.48 mV in v37.
   data: CONFIRMED -- Lagged I_tot (-2..+1 tick), the separate I_fc/I_batt split, and the droop gains with their current products remove at most 20.5 % (v37) / 29 % (v35) of the V_bus residual variance left after I_tot, fitted per chunk in-sample. My re-derivation with different gating gives 24 % / 28.5 %. With one set of coefficients per bag tested out-of-sample, they remove only 7 % / 15 %. The v37 12-24 Hz band falls only from 7.27 to 6.48 mV (independent estimate 7.26 to 6.32 mV). The 20.5 % / 29 % figures are an upper bound inflated by per-chunk overfitting.
   physics: CONFIRMED -- In fw v37 cruise, lagged I_tot (-2..+1 tick), the separate I_fc/I_batt split, the droop gains and their products with current together remove 20.5 % of the high-passed V_bus residual variance after the I_tot fit. In fw v35 they remove 29 %. About 4 percentage points of each is chance fitting: nine white-noise regressors remove 3.7-3.9 % in the same per-chunk OLS. The v37 12-24 Hz band falls only from 7.27 to 6.48 mV, against about 7.15 mV for the null. Most of the residual is therefore not a linear function of the sampled currents or gains. A single V_rgn regressor removes a comparable or larg