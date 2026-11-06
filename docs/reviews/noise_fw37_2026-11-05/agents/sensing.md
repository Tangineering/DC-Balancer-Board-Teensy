# Sensing chain as a noise source: label `sensing`

**Scope.** This report covers the analog sense path, the ADC path and the droop-injection path, for the fw v35 bag (`rosbag_sdp_2026-10-30_01-49-38`) and the fw v37 rev 2 bag (`rosbag_sdp_2026-11-05_20-09-52`). The battery-only bag `rosbag_sdp_2026-10-26_23-57-14` (fw ≤ v31a, 0x26 throughout) serves as a control.

**Windows.** Steady-state statistics use these windows:
- **Moving:** `switch_state` 0x27, v > 0.3 m/s, I_tot > 0.3 A, with ±0.5 s masked around each purge. Purges were detected as V_fc dips > 0.8 V below a 2 s median: 21 before and 19 after, median interval 10.33 s. Contiguous runs ≥ 128 samples were kept, giving 3140 samples before and 3763 after.
- **Standstill:** v < 0.05 m/s, giving 4158 samples before and 3161 after.

**Receive timing.** max(diff(t)) is 21.4 ms before and 22.0 ms after. No gap exceeds 25 ms.

## 1. Signal chain (schematic 2026-06-22, BOM 20260622, datasheets)

**Current-sense path.** INA253A1: 2 mΩ shunt on the boost OUTPUT side (VOUT-x to VBUS-x, after the C4 22 µF ceramics), gain 100 mV/A (= 50 V/V), BW 350 kHz, input noise 40 nV/√Hz, 1 nF maximum capacitive load (DS SLOS954A p.5–6). REF1 and REF2 are tied to GND, so the output is unipolar and clips at ~0 A: at standstill in 0x26, I_fc reads 0 counts in 2799 of 2802 samples. VS is the 3V3 net with the 100 nF CSNS bypass. The OUT pin drives the Teensy pin (40 or 41) directly and also the AD5443 VREF (R-2R ladder, 8–12 kΩ input, DS Table 1).
- **No anti-alias network on any ADC input.** The BOM has no ADC-pin capacitor.
- **Divider Thevenin impedances:** V_fc 7.3 kΩ, V_batt 6.2 kΩ, V_bus 8.2 kΩ, V_chg / V_rgn 8.9 kΩ.

**Droop-injection path.** INA OUT → MDAC (g = code/4096) → OPA197 (A_v 5.02, on 5 V) → RINJ 53.6 k → FB node (RD1 215 k bodged / RD2 10 k). An INA output perturbation e therefore shifts that boost's V0 by 20.1·g·e. This is equivalent to a current error e/K_sns inside the droop.

**Boost switching (TPS61288, DS p.5, §8.4.2).** f_sw is 500 kHz (440–600 kHz) in PWM. The converter enters PFM (extended off-time, variable frequency) when the inductor peak falls to 2.6 A typical. With L = 2.2 µH the inductor ripple is ~3.4–3.6 A p-p, so PFM is estimated below I_out ≈ 0.56 A (FC, V_in 10 V) and ≈ 0.40 A (BT, V_in 7.6 V). The rig's moving medians are I_fc 0.15 A and I_bt 0.48–0.52 A. **Both boosts therefore sit at or inside the PFM boundary, so the ripple frequency depends on load.** This estimate uses nominal L and typical thresholds; it is unverified and needs a scope on the SW nodes.

## 2. Firmware sampling

**Configuration.** The firmware calls `analogReadResolution(12)` and `analogReadAveraging(16)`; the Teensy default is 4 (`analog.c`: `analog_num_average = 4`). Teensyduino 1.62 `analog.c` uses the async clock ADACK with ADIV(1), and 12-bit mode costs 25 conversion + 24 settling clocks. **Estimate (ADACK ≈ 20 MHz/2 is TODO(verify: i.MX RT1062 RM)):** 4.9 µs per conversion, 78 µs per `analogRead()`, ~550 µs per tick for the 7 reads. This is consistent with the in-code note that averaging 8 left > 0.6 ms of margin.

**Read order in `updateSensors()`.** The reads are I_fc, I_batt, V_fc, V_batt, V_bus, V_chg, V_rgn. **I_fc and I_batt are therefore sampled in separate ~78 µs windows about 78 µs apart, both on ADC1.** In addition, `analogRead()` spins on `yield()`.

**Clock relationship.** The ADC clock is asynchronous to both boosts and to the VESC PWM, and a 78 µs boxcar suppresses a 20 kHz tone by only ~0.2. Ripple therefore aliases twice: first into the 1 kHz samples as near-white noise, then into the 50 Hz telemetry. The telemetry is a single-tick **snapshot**; `sendTelemetry()` copies the globals.

**Dual-ADC option.** The pedvide ADC library tables (`ADC.cpp`, `ADC_TEENSY_4_1`) map A16/A17 (pins 40/41) on **both** ADC0 and ADC1 (sc1a 9/10). A synchronous I_fc/I_batt read is therefore possible. V_bus (A12) is on ADC1 only.

## 3. Expected floor vs measured

**Predicted floor.** INA253 output noise is 2.0 µV/√Hz over an ENBW of 1.57 × 350 kHz, giving 1.48 mV rms (1.84 LSB) per conversion. Averaging 16 independent conversions reduces this to 0.46 LSB. Adding quantization (0.29 LSB) gives **0.54 LSB = 4.4 mA** per sample.

**Measured standstill floor.** The tick-difference σ/√2 values are:
- I_batt (~22 mA DC): 0.68 / 0.63 LSB before / after.
- V_bus: 0.73 / 0.63 LSB, i.e. 3.3 / 2.9 mV.

The sensor floor is therefore ~0.6–0.8 LSB, and fw v37 did not change it. The prediction explains ~70 % of the floor variance; the rest is likely ADC and reference noise. V_bus is ratiometric to the 3.3 V ADC reference (×4.8 gain to the bus), so the 2.9 mV floor bounds the reference noise at ≤ 0.6 mV rms. That the reference is the 3.3 V rail is TODO(verify: PJRC schematic).

**Moving floor.** The per-sample σ is:
- I_fc: 5.91 → 4.26 LSB.
- I_batt: 10.05 → 6.51 LSB.

Both grow monotonically with I_tot. After the update, I_fc goes from 2.54 to 4.49 LSB between the I_tot 0.3–0.5 A and 0.9–1.5 A bins. **The sensor floor is therefore 1.4–3 % of the moving current variance.** At 12–25 Hz the after-update densities are I_fc 6.5 mA/√Hz, I_bt 9.4 mA/√Hz and V_bus 2.3 mV/√Hz, against floors of 1.1 mA/√Hz and 0.63 mV/√Hz.

## 4. Share signal: what the sensor chain does and does not explain

**Unchanged high-band floor.** The own share s = I_fc/I_tot has a flat 12–25 Hz floor: 0.00369 /√Hz before and 0.00374 /√Hz after (band rms 0.0134 / 0.0137). **The drive-law change did not change it** (figure).

**Sensor-floor contribution.** The floor-implied share noise is √((1−s)²σ_F² + s²σ_B²)/I_tot = 0.56 LSB/0.70 A, i.e. 0.00128 /√Hz. **This is ~12 % of the share high-band variance.**

**Load-split contribution.** The fast load split is not the DC split. Regressing tick increments of I_fc on I_tot gives β = 0.337 before and 0.369 after, against a median share of 0.237–0.238. Band transfer functions I_tot→I_fc give 0.29–0.37. The FC therefore carries ~1.5× its DC share of each fast load excursion. However, the coherence I_tot→s is only 0.09–0.14 at 12–25 Hz, so the load-linear part is ≤ 14 % of the share high-band variance.

**Contribution through the droop.** INA253 intrinsic noise fed through the droop gives about 20 µA/√Hz × √(1.57 × 10 kHz boost-loop BW) × R_F/(R_F+R_B), i.e. ~1.8 mA rms of physical FC current or ~0.0026 share. This is ≤ 2–5 % of the variance (an estimate). The share controller's own MDAC dither at 12–25 Hz (ΔR_F 0.023–0.033 Ω rms) predicts ~0.003 share, or ~4 %; the measured coherence R_F→s is 0.08–0.13.

**Unexplained remainder.** The remaining **~70–75 % of the share high-band variance** is a differential, load-proportional component. Its tick residual after the β fit is 3.33 → 2.28 LSB, rising with I_tot from 1.73 to 2.58 LSB. Its correlation with dV_bus is weak (0.05 / 0.16). The V_bus test does **not** discriminate: the bus impedance at these frequencies is ~0.13 Ω (battery-only control, corr −0.68) or less, so even a fully physical circulating current would give corr ≤ ~0.2.

**Candidate mechanisms for the remainder (unverified):**
- (a) Inter-channel sampling skew of ~78 µs on fast load ripple.
- (b) Aliasing of VESC-PWM and PFM ripple through 78 µs boxcars, which is uncorrelated between the two reads.
- (c) Real 25–500 Hz differential dynamics folded into the snapshots.

The 50 Hz bags cannot separate these mechanisms.

**Battery-only control.** Here I_bt σ is 15.6 LSB and dV_bus/dI is −0.131 Ω (corr −0.68); this bag has no share loop.

**V_fc.** The moving V_fc tick σ fell from 61.5 to 34.7 mV, which follows the lower FC current ripple through the stack resistance. The standstill V_fc floor is 19–23 mV with one-sample dips of −20 to −35 mV; the source of the dips is unknown.

## 5. Conclusions

1. The sensor chain floor is 0.6–0.8 LSB per channel and was not changed by fw v37. It is negligible for the currents (≤ 3 %) and minor for the share (~12 %). Re-spin sensing upgrades alone therefore cap the share-noise reduction near **6 % rms** unless the dominant remainder turns out to be aliasing or skew.
2. The dominant share high-band component is load-proportional, differential, and invariant to the drive law at 12–25 Hz. The firmware sampling structure (skewed, short-window, asynchronous) is a credible contributor that firmware can fix. The A/B tests below would decide whether it is the main one.
3. Physical coupling of sensor noise into the droop exists, but it is small at the INA253 intrinsic level. Large ripple seen by the INA253 also enters the FB node, attenuated above the 4–19 kHz boost crossover.

**Confidence.** The floor and band numbers are high confidence, being derived from the arrays. The ADC timing is medium confidence (inferred from the core source, not measured). The PFM regime and the remainder mechanisms are low confidence and unverified.

Figure: `docs/reviews/noise_fw37_2026-11-05/figs/sensing_asd_vs_floor.png`. It shows the ASDs of I_fc, I_bt and the share before and after the update, against the standstill floor. The share curves overlay above ~7 Hz.


## Adversarial verification (data and physics lenses)

- [C1] The standstill sensor floor is 0.63-0.78 LSB per sample (I_batt 5.1-6.3 mA, V_bus 2.9-3.4 mV) in both firmware versions, against an INA253+16-avg+quantization prediction of 0.54 LSB.
   data: PARTLY -- Using contiguous standstill samples only (v<0.05 m/s, consecutive ticks; 4155/3159 pairs), the per-sample floor is 0.62-0.74 LSB in both fw v35 (10-30) and fw v37 (11-05). That is I_batt 5.0-5.5 mA and V_bus 2.9-3.4 mV. Diffs across segment gaps inflate I_batt to about 0.77 LSB (6.2 mA). The I_batt floor is measured about 3 counts above zero on a unipolar sensor, with 2-3 % of samples clipped at zero. The V_bus floor includes the boost's regulation. I_fc's floor cannot be measured at standstill 
   physics: PARTLY -- At standstill (v<0.05 m/s), the high-frequency floor from successive differences of contiguous samples is 0.62-0.68 LSB for I_batt (5.0-5.5 mA) and 0.64-0.74 LSB for V_bus (2.9-3.4 mV) in both fw v35 and fw v37. Differencing across gaps raises this to about 0.78 LSB. V_bus has no INA253 in its path yet shows the same floor, so the floor is set by the Teensy ADC chain (12-bit, 16-average, quantization), not by INA253 noise. The 0.54 LSB INA253 + quantization prediction is incomplete because it om
- [C2] In 0x27 moving windows the per-sample current noise is 6-13x the standstill floor (I_fc 5.91->4.26 LSB, I_batt 10.05->6.51 LSB) and grows with I_tot, so the sensor floor is <=3% of the moving current variance.
   data: PARTLY -- In 0x27 moving windows (purges excluded, 3925/4116 contiguous pairs), the tick-difference current noise is I_fc 5.5 -> 4.1 LSB and I_batt 9.3 -> 6.3 LSB (fw v35 -> fw v37). It grows with I_tot, monotonically except before-I_batt, which is flat above 0.7 A (10.8 vs 10.7 LSB). That is 10-17x the zero-current standstill reading (0.4-0.6 LSB). The standstill reading is taken at ~0 A on a unipolar sensor, so it is only a lower bound on the sensor floor under load. The "sensor floor <= ~1 % of moving 
   physics: PARTLY -- In 0x27 moving windows (purges excluded, 3925 / 4116 adjacent pairs), the tick-difference per-sample current noise is:
- I_fc: 5.5 -> 4.1 LSB (before -> after).
- I_batt: 9.3 -> 6.3 LSB.

Both currents grow monotonically with I_tot (I_fc 3.7 -> 6.4 LSB before, 2.4 -> 4.8 after; I_bt 5.5 -> 10.6 before, 3.7 -> 8.0 after, across 0.3-1.5 A). That is 10-27x the standstill value (0.15-0.6 LSB), so the standstill noise is about 1 % or less of the moving variance.

The standstill value is measured at a
- [C3] The own-share 12-25 Hz floor is unchanged by fw v37 (0.00369 vs 0.00374 /rtHz; band rms 0.0134 vs 0.0137), and the sensor floor explains only ~12% of that variance (floor 0.00128 /rtHz).
   data: CONFIRMED -- With purges excluded (+/-0.5 s), the own-share 12-24.6 Hz floor (0x27, moving, I_tot>0.3 A) is unchanged by fw v37: about 0.0037-0.0038 /rtHz and band rms about 0.0133-0.0139 in both bags. The two bags still match without purge exclusion (both ~0.0057 /rtHz), but the level is about 1.5x higher. A 0.558 LSB per-channel sensor floor (0.00128 /rtHz) explains about 11-12 % of the band variance; ideal quantization explains only about 2 %. Most of the band is real folded (>25 Hz) or broadband share va
   physics: CONFIRMED -- fw v37 leaves the own-share 12-24.6 Hz floor unchanged: 0.00379 vs 0.00377 /rtHz, band rms 0.0135 vs 0.0133 (nperseg 128, 0x27 moving, purges excluded, which is essential; without the exclusion the ASD is 0.0059/0.0056). Taking the 0.558 LSB per-channel sigma as given, the sensor floor explains at most about 12 % of that variance. With the share-ratio propagation weight (0.85 at s 0.16) and the actual I_tot of 0.75-0.79 A, it is about 7-9 %. Quantization alone would explain about 2 %. Most of th
- [C4] Fast load excursions split about 1.5x more onto FC than the DC share: the tick-increment regression beta of I_fc on I_tot is 0.337/0.369 against a median share of 0.237/0.238, yet the I_tot->share coherence at 12-25 Hz is only 0.09-0.14.
   data: PARTLY -- In 0x27, moving and with purges excluded, the tick-increment beta of I_fc on I_tot is 0.343 (fw v35, 10-30) and 0.369 (fw v37, 11-05). It stays 0.30-0.37 across 1/3/10-tick increments and large-step-only subsets, against a median share of 0.241 in both bags (1.4-1.5x). Part of that excess is the ratio law's ordinary marginal split: the slow level slope of I_fc on I_tot is already 0.28-0.30. The fast-specific excess over the slow marginal is therefore about 1.2-1.3x. The I_tot-to-share coherence 
   physics: PARTLY -- In switch_state 0x27 with purges excluded, the small-signal split of I_tot excursions onto FC is bF = 0.343 (fw v35, 10-30) and 0.369 (fw v37, 11-05). The median DC share is 0.241 in both bags, so the incremental split is 1.42x / 1.53x the DC share. The split is not a fast-transient effect: bF is flat at 0.31-0.38 across the folded 2-25 Hz band. It matches an affine droop law, where the incremental fraction R_bt/(R_fc+R_bt) differs from the DC share by the dV0 offset while the controller is park
- [C5] I_fc and I_batt are read in separate, sequential, roughly 78 us blocking analogRead() windows on ADC1 (estimated ~550 us of reads per tick at averaging 16), although pins 40/41 are available on both ADC modules, so a skew-free synchronous read is possible.
   data: CONFIRMED -- I_fc (pin 40) and I_batt (pin 41) are read one after the other by blocking analogRead() calls on the core-level ADC1 (sc1a 9 and 10). Each read is a 16-sample hardware average of 49-clock 12-bit conversions on the ADACK/2 clock. That is about 78 us per read, and about 550 us for the 7 reads per tick, IF ADACK is about 20 MHz with ADHSC set. The ADACK frequency is unverified; at 10 MHz the figures double to about 157 us and 1.1 ms. So the two current samples are about one read period apart, about
   physics: CONFIRMED -- I_fc (pin 40) and I_batt (pin 41) are read one after the other by two blocking analogRead() calls on the same module (core ADC1, ch 9/10; teensy_controller.ino:7025-7026), so I_batt is sampled one averaged-conversion window after I_fc. My model gives about 78 us per read at 12-bit with 16 hardware averages, assuming ADACK of about 20 MHz /2 (not verified), and about 550 us for the seven reads per tick. A16/A17 also exist on the second ADC module (ADC.cpp ADC_TEENSY_4_1 tables, sc1a 9/10 in both)